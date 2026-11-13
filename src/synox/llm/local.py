"""
本地模型（docs/adr/0007）：SYNOX 內建的 platform ability，不是另裝的套件（沒有登入要包）。

    {"kind": "local", "server": "ollama", "base_url": "http://127.0.0.1:11434", "model": "qwen3.5:9b",
     "context_size": 8192, "timeout": 450, "max_total_timeout": 1800, "tools": true, "max_tokens": 1024}

- server：ollama（預設，原生 /api/chat）｜vllm｜lmstudio｜other（後三種走 OpenAI 相容的 /v1/chat/completions）。
- context_size：ollama 用 options.num_ctx 帶過去（0＝伺服器預設）；其他三種客戶端設不了，忽略（probe 會說明）。
- timeout：**無進展逾時**（秒；0＝自動 450）。每一次 socket 讀取最多等這麼久——第一個字出來之前也算（CPU 上長提示要很久），
  只要模型還在吐字就不砍。max_total_timeout：很寬的總上限（預設 1800 秒），在兩次讀取之間檢查（最多再多等一個無進展逾時）。
- 只用標準函式庫（urllib）、不走系統 proxy；`opener(request, timeout) -> response` 可以換掉（測試用假的，不開 port、不連網）。
- probe()／inspect() **唯讀**：ollama 只打 GET /api/tags、POST /api/show（只讀模型的中繼資料，不載入模型），
  其他打 GET /v1/models；絕不送 chat／generate。
- 截斷：回報的 prompt token ≥ context 的 97%＝「很可能被截斷」（Ollama 超過 num_ctx 是靜默截掉前面），
  寫 logging.warning、放進 Reply.warnings 與 adapter.last_warning（網頁設定頁、doctor 看得到），不靜默。
- 之後的 VLM（docs 2026-11-13-vlm-vision-design）：訊息轉換集中在 `ollama_message`／`openai_message`，
  Message 多了圖片欄位時只要在這兩個函式加；這一輪不做。
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import math
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence

from synox.llm.base import ASSISTANT, TOOL, ChatAdapter, LLMError, Message, Reply, ToolCall, ToolSpec, http_error

SERVERS = ("ollama", "vllm", "lmstudio", "other")
SERVER_LABELS = {"ollama": "Ollama", "vllm": "vLLM", "lmstudio": "LM Studio", "other": "OpenAI 相容伺服器"}
DEFAULT_URLS = {"ollama": "http://127.0.0.1:11434", "vllm": "http://127.0.0.1:8000",
                "lmstudio": "http://127.0.0.1:1234", "other": "http://127.0.0.1:8000"}
DEFAULT_TIMEOUT = 450.0               # 90 秒的 5 倍（擁有者 2026-11-13）；是「無進展」逾時，不是總時限
DEFAULT_MAX_TOTAL = 1800.0
MAX_SECONDS = 86400.0
CONTEXT_MIN, CONTEXT_MAX = 512, 1048576
TRUNCATION_RATIO = 0.97
OLLAMA_DEFAULT_CTX = 4096             # Ollama 沒設 num_ctx／OLLAMA_CONTEXT_LENGTH 時的預設（測試紀錄 /api/ps 看到的）
CHARS_PER_TOKEN = 2.5                 # 估 token 用；中文偏保守（實際 1 個中文字常常 ≥ 1 token）
PROBE_TIMEOUT = 15.0

DEFAULTS = {"server": "ollama", "base_url": "", "model": "", "context_size": 0, "timeout": 0,
            "max_total_timeout": DEFAULT_MAX_TOTAL, "tools": True}

Opener = Callable[[urllib.request.Request, float], object]

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))     # 本地伺服器不走系統 proxy


def default_opener(request: urllib.request.Request, timeout: float):
    return _DIRECT.open(request, timeout=timeout)


# ── 設定檢查（config.py、精靈、網頁共用）────────────────────────────────

def _number(value, name: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"llm.{name} 要是秒數（數字）。")
    value = float(value)
    if value < 0 or (value == 0 and not allow_zero) or value > MAX_SECONDS:
        raise ValueError(f"llm.{name} 要在 {'0' if allow_zero else '1'}～{int(MAX_SECONDS)} 秒之間。")
    return int(value) if value.is_integer() else value


def parse_context(value) -> int:
    """context_size：整數；0＝用伺服器預設；其他要在 512～1048576。字串的數字也收（表單送來的）。"""
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if value in (None, ""):
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"llm.context_size 要是整數（0＝用伺服器預設，或 {CONTEXT_MIN}～{CONTEXT_MAX}）。")
    if value != 0 and not CONTEXT_MIN <= value <= CONTEXT_MAX:
        raise ValueError(f"llm.context_size 要是 0（用伺服器預設）或 {CONTEXT_MIN}～{CONTEXT_MAX}。")
    return value


def validate(llm: dict) -> dict:
    """kind=local 的 llm 那一塊 → 補好預設、檢查過的一份；不合丟 ValueError（一句中文）。"""
    out = {**DEFAULTS, **{k: v for k, v in (llm or {}).items()}}
    out["kind"] = "local"
    server = str(out.get("server") or "ollama").strip().lower()
    if server not in SERVERS:
        raise ValueError(f"llm.server 只能是 {'、'.join(SERVERS)}（現在是 {out.get('server')!r}）。")
    out["server"] = server
    base = str(out.get("base_url") or "").strip() or DEFAULT_URLS[server]
    if not base.startswith(("http://", "https://")):
        raise ValueError("llm.base_url 要以 http:// 或 https:// 開頭（例如 http://127.0.0.1:11434）。")
    out["base_url"] = base
    if not isinstance(out.get("model"), str):
        raise ValueError("llm.model 要是文字（模型名稱，例如 qwen3.5:9b）。")
    out["model"] = out["model"].strip()
    out["context_size"] = parse_context(out.get("context_size"))
    out["timeout"] = _number(out.get("timeout", 0), "timeout")
    out["max_total_timeout"] = _number(out.get("max_total_timeout", DEFAULT_MAX_TOTAL), "max_total_timeout",
                                       allow_zero=False)
    if out["timeout"] and out["max_total_timeout"] < out["timeout"]:
        raise ValueError("llm.max_total_timeout（總上限）不能比 llm.timeout（無進展逾時）小。")
    if not isinstance(out.get("tools"), bool):
        raise ValueError("llm.tools 只能是 true 或 false（false＝走文字協定）。")
    return out


# ── 網址 ──────────────────────────────────────────────────────────────

_PRIVATE_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")


def host_kind(base_url: str) -> str:
    """loopback｜private｜public｜unknown（主機名不是 IP 又看不出來；不查 DNS）。"""
    host = (urllib.parse.urlsplit(base_url or "").hostname or "").strip().lower()
    if not host:
        return "unknown"
    if host == "localhost" or host.endswith(".localhost"):
        return "loopback"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or host.endswith(_PRIVATE_SUFFIXES):
            return "private"
        return "unknown"
    if ip.is_loopback:
        return "loopback"
    if ip.is_private or ip.is_link_local:
        return "private"
    return "public"


def is_local_url(base_url: str) -> bool:
    return host_kind(base_url) in ("loopback", "private")


def url_warning(base_url: str) -> str:
    """不是本機／私網位址時的一句提醒（""＝沒事）。不擋：使用者可能真的有自己的主機。"""
    kind = host_kind(base_url)
    if kind == "public":
        return (f"⚠️ {base_url} 是公網位址：對話內容會經網路送到那台機器。本地模型通常是 127.0.0.1 或家裡網路的 192.168.x.x；"
                "確定是你自己的主機再用，最好走 https。")
    if kind == "unknown":
        return f"⚠️ 看不出 {base_url} 是不是這台或家裡網路的電腦（SYNOX 不查 DNS）；確定是你自己的主機再用。"
    return ""


def root_url(base_url: str) -> str:
    """去掉結尾的 / 與 /v1（使用者常貼 http://127.0.0.1:11434/v1）。"""
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3].rstrip("/")
    return base


def estimate_tokens(chars: int) -> int:
    return int(math.ceil(max(0, chars) / CHARS_PER_TOKEN))


# ── 訊息轉換（VLM 之後在這兩個函式加圖片）────────────────────────────────

def ollama_message(m: Message) -> dict:
    item = {"role": m.role, "content": m.content or ""}
    if m.role == ASSISTANT and m.tool_calls:
        item["tool_calls"] = [{"function": {"name": c.name, "arguments": dict(c.args or {})}} for c in m.tool_calls]
    if m.role == TOOL and m.name:
        item["tool_name"] = m.name
    return item


def openai_message(m: Message) -> dict:
    item = {"role": m.role, "content": m.content or ""}
    if m.role == ASSISTANT and m.tool_calls:
        item["tool_calls"] = [{"id": c.id or f"call_{i}", "type": "function",
                               "function": {"name": c.name, "arguments": json.dumps(c.args or {}, ensure_ascii=False)}}
                              for i, c in enumerate(m.tool_calls)]
    if m.role == TOOL:
        item["tool_call_id"] = m.tool_call_id or ""
    return item


def tool_schema(t: ToolSpec) -> dict:
    return {"type": "function", "function": {"name": t.name, "description": t.description,
                                             "parameters": t.parameters or {"type": "object", "properties": {}}}}


def _args(raw) -> tuple:
    """(dict, 合不合法)：Ollama 給物件、OpenAI 給 JSON 字串；壞掉的回 {}（第 4 關會把缺的欄位告訴 AI）。"""
    if isinstance(raw, dict):
        return raw, True
    if raw in (None, ""):
        return {}, True
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}, False
    return (value, True) if isinstance(value, dict) else ({}, False)


def _timeout_like(e: BaseException) -> bool:
    if isinstance(e, (socket.timeout, TimeoutError)):
        return True
    reason = getattr(e, "reason", None)
    return isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason or e).lower()


class LocalAdapter(ChatAdapter):
    kind = "local"
    supports_stop = True              # ollama：options.stop；其他：body.stop（docs/adr/0010）

    def __init__(self, model: str = "", *, server: str = "ollama", base_url: str = "", context_size: int = 0,
                 timeout: float = 0, max_total_timeout: float = DEFAULT_MAX_TOTAL, tools: bool = True,
                 max_tokens: int = 1024, opener: Optional[Opener] = None, clock: Optional[Callable[[], float]] = None):
        if server not in SERVERS:
            raise LLMError(f"不認得的本地模型伺服器 {server}（只能是 {'、'.join(SERVERS)}）。")
        self.server = server
        self.model = (model or "").strip()
        self.base_url = (base_url or "").strip() or DEFAULT_URLS[server]
        self.root = root_url(self.base_url)
        self.context_size = int(context_size or 0)
        self.timeout = float(timeout or 0) or DEFAULT_TIMEOUT
        self.max_total = max(float(max_total_timeout or DEFAULT_MAX_TOTAL), self.timeout)
        self.supports_tools = bool(tools)
        self.max_tokens = int(max_tokens or 1024)
        self._open = opener or default_opener
        self._clock = clock or time.monotonic
        self.server_ctx: Optional[int] = None        # 從伺服器讀到的 context（Ollama /api/ps、vLLM max_model_len）
        self._ctx_looked = False
        self._think = True                            # 送 think=false；伺服器不認得就拿掉再試一次
        self.last_warning = ""
        self.name = f"本地模型 {SERVER_LABELS[server]}（{self.model or '未指定模型'}）"
        warn = url_warning(self.base_url)
        if warn:
            logging.warning("[LLM] local base_url: %s", warn)

    # ── HTTP ─────────────────────────────────────────────────────────

    def _request(self, path: str, payload=None, method: str = "GET") -> urllib.request.Request:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json, text/event-stream, application/x-ndjson"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(self.root + path, data=data, headers=headers, method=method)

    def _where(self) -> str:
        return f"{SERVER_LABELS[self.server]}（{self.root}）"

    def _no_progress(self) -> LLMError:
        return LLMError(f"本地模型超過 {int(self.timeout)} 秒沒有任何進展（無進展逾時：連第一個字都還沒出來，或吐到一半停住）。"
                        f"CPU 上大模型、長提示可能要更久：調大 llm.timeout，或換小一點的模型、調小 context_size。")

    def _too_long(self) -> LLMError:
        return LLMError(f"本地模型一直有在回，但超過總上限 {int(self.max_total)} 秒，已中止（總上限 llm.max_total_timeout）。"
                        "要等更久就把它調大。")

    def _open_or_raise(self, request, timeout: float):
        try:
            resp = self._open(request, timeout)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            raise _HTTPProblem(e.code, body)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            if _timeout_like(e):
                raise self._no_progress()
            raise LLMError(f"連不到本地模型伺服器 {self._where()}："
                           + ("Ollama 有沒有開？（工作列有沒有 Ollama 圖示，或終端機跑 `ollama serve`）"
                              if self.server == "ollama" else "伺服器有沒有開、網址和連接埠對不對？"))
        status = int(getattr(resp, "status", 200) or 200)
        if status >= 400:
            body = ""
            try:
                body = resp.read().decode("utf-8", "replace")
            except Exception:
                pass
            _close(resp)
            raise _HTTPProblem(status, body)
        return resp

    def _lines(self, resp, start: float):
        """一行一行讀（NDJSON 或 SSE）。每次讀取最多等 self.timeout（socket 逾時）；總時間超過 max_total 就中止。"""
        try:
            while True:
                try:
                    line = resp.readline()
                except (socket.timeout, TimeoutError):
                    raise self._no_progress()
                except (OSError, http.client.HTTPException) as e:
                    if _timeout_like(e):
                        raise self._no_progress()
                    raise LLMError(f"本地模型的回應中途斷了：{type(e).__name__}。")
                if not line:
                    return
                if self._clock() - start > self.max_total:
                    raise self._too_long()
                yield line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
        finally:
            _close(resp)

    def _get_json(self, path: str, payload=None, method: str = "GET"):
        resp = self._open_or_raise(self._request(path, payload, method), min(self.timeout, PROBE_TIMEOUT))
        try:
            return json.loads(resp.read().decode("utf-8", "replace") or "null")
        except ValueError:
            raise LLMError(f"{self._where()} 回的格式看不懂（網址是不是填錯了？）。")
        finally:
            _close(resp)

    def _http_text(self, p: "_HTTPProblem") -> str:
        body = p.body or ""
        try:
            detail = str((json.loads(body) or {}).get("error") or body)
        except (ValueError, AttributeError):
            detail = body
        low = detail.lower()
        if p.status == 404 and ("not found" in low or "model" in low) or "try pulling" in low:
            if self.server == "ollama":
                return f"模型 {self.model} 不在這台 Ollama 上：先在終端機跑 `ollama pull {self.model}`，或改填已經下載的模型名稱。"
            return f"伺服器上沒有模型 {self.model}（或網址不對）：{' '.join(detail.split())[:160]}"
        if "memory" in low and ("more" in low or "insufficient" in low or "not enough" in low):
            return ("記憶體不夠載入這個模型（或這個 context）：把 context_size 調小、換小一點的模型，或關掉其他吃記憶體的程式。"
                    f"\n伺服器說：{' '.join(detail.split())[:200]}")
        return http_error(p.status, detail)

    # ── chat ─────────────────────────────────────────────────────────

    def effective_context(self) -> tuple:
        """(context 長度或 0, 怎麼知道的)。"""
        if self.server == "ollama" and self.context_size:
            return self.context_size, "llm.context_size"
        if self.server_ctx:
            return self.server_ctx, "伺服器回報"
        if self.server == "ollama":
            return OLLAMA_DEFAULT_CTX, f"沒設 context_size，假設 Ollama 預設 {OLLAMA_DEFAULT_CTX}"
        return 0, "不知道"

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = (), *, stop: Sequence[str] = ()) -> Reply:
        if not self.model:
            raise LLMError("還沒填本地模型的名稱（例如 qwen3.5:9b；Ollama 的話是 `ollama list` 看得到的名字）。")
        native = bool(tools) and self.supports_tools
        warnings: List[str] = []
        sent_chars = sum(len(m.content or "") for m in messages) + \
            (len(json.dumps([tool_schema(t) for t in tools], ensure_ascii=False)) if native else 0)
        stop = [s for s in (stop or ()) if isinstance(s, str) and s]
        try:
            if self.server == "ollama":
                reply = self._chat_ollama(messages, tools if native else (), warnings, stop)
            else:
                reply = self._chat_openai(messages, tools if native else (), warnings, stop)
        except _HTTPProblem as p:
            raise LLMError(self._http_text(p))
        from synox.llm.textproto import strip_think
        reply.text = strip_think(reply.text)[0]          # 思考段不給人看（think=false 不一定每個模型都照做）
        self._learn_context()
        ctx, how = self.effective_context()
        used = int(reply.usage.get("input", 0) or 0)
        if ctx and used >= ctx * TRUNCATION_RATIO:
            warnings.append(f"提示用了 {used} tokens，已到 context {ctx}（{how}）的 {int(TRUNCATION_RATIO * 100)}% 以上，"
                            "很可能被截斷（Ollama 會靜默丟掉最前面、也就是系統提示）：把 llm.context_size 調大。")
        elif ctx and estimate_tokens(sent_chars) >= ctx:
            warnings.append(f"送出的提示估計約 {estimate_tokens(sent_chars)} tokens（估算），超過 context {ctx}（{how}），"
                            "可能被截斷（伺服器回報的數字可能沒算快取的部分）：把 llm.context_size 調大。")
        for w in warnings:
            logging.warning("[LLM] local: %s", w)
        if warnings:
            self.last_warning = warnings[0]
        reply.warnings = warnings
        return reply

    def _chat_ollama(self, messages, tools, warnings, stop=()) -> Reply:
        body = {"model": self.model, "messages": [ollama_message(m) for m in messages], "stream": True,
                "options": {"num_predict": self.max_tokens}}
        if self.context_size:
            body["options"]["num_ctx"] = self.context_size
        if stop:
            body["options"]["stop"] = list(stop)
        if self._think:
            body["think"] = False                    # 關掉推理輸出（CPU 上太慢；測試紀錄）
        if tools:
            body["tools"] = [tool_schema(t) for t in tools]
        start = self._clock()
        try:
            resp = self._open_or_raise(self._request("/api/chat", body, "POST"), self.timeout)
        except _HTTPProblem as p:
            if self._think and p.status == 400 and "think" in (p.body or "").lower():
                self._think = False                  # 舊版 Ollama／不支援的模型：拿掉 think 再試一次
                return self._chat_ollama(messages, tools, warnings, stop)
            raise
        text: List[str] = []
        calls: List[ToolCall] = []
        usage: Dict[str, int] = {}
        done = False
        for line in self._lines(resp, start):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                raise LLMError(f"{self._where()} 回的格式看不懂（網址是不是填錯了？）。")
            if not isinstance(obj, dict):
                continue
            if obj.get("error"):
                raise LLMError(self._http_text(_HTTPProblem(500, json.dumps({"error": obj["error"]}))))
            msg = obj.get("message") or {}
            if msg.get("content"):
                text.append(str(msg["content"]))
            for tc in msg.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                args, ok = _args(fn.get("arguments"))
                if not ok:
                    warnings.append(f"工具 {fn.get('name')} 的參數不是合法的 JSON（當成沒有參數）。")
                calls.append(ToolCall(name=str(fn.get("name") or ""), args=args,
                                      id=str(tc.get("id") or f"local-{len(calls)}")))
            if obj.get("done"):
                usage = {"input": int(obj.get("prompt_eval_count") or 0), "output": int(obj.get("eval_count") or 0)}
                if obj.get("done_reason") == "length":
                    warnings.append(f"回覆到了 max_tokens（{self.max_tokens}）被切掉。")
                done = True
                break
        if not done:
            raise LLMError("本地模型的回應中途斷了（沒有收到結束訊號）。")
        return Reply(text="".join(text), tool_calls=[c for c in calls if c.name], usage=usage)

    def _chat_openai(self, messages, tools, warnings, stop=()) -> Reply:
        body = {"model": self.model, "messages": [openai_message(m) for m in messages], "stream": True,
                "stream_options": {"include_usage": True}, "max_tokens": self.max_tokens}
        if stop:
            body["stop"] = list(stop)[:4]           # OpenAI 相容的伺服器多半最多收 4 個
        if tools:
            body["tools"] = [tool_schema(t) for t in tools]
        start = self._clock()
        resp = self._open_or_raise(self._request("/v1/chat/completions", body, "POST"), self.timeout)
        text: List[str] = []
        parts: Dict[int, dict] = {}
        usage: Dict[str, int] = {}
        finished = False
        for line in self._lines(resp, start):
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("{"):                  # 不是 SSE（錯誤時有些伺服器直接回 JSON）
                data = line
            elif line.startswith("data:"):
                data = line[5:].strip()
            else:
                continue
            if data == "[DONE]":
                finished = True
                break
            try:
                obj = json.loads(data)
            except ValueError:
                raise LLMError(f"{self._where()} 回的格式看不懂（網址是不是填錯了？）。")
            if not isinstance(obj, dict):
                continue
            if obj.get("error"):
                err = obj["error"]
                detail = err.get("message") if isinstance(err, dict) else err
                raise LLMError(self._http_text(_HTTPProblem(500, json.dumps({"error": str(detail)}))))
            if isinstance(obj.get("usage"), dict):
                u = obj["usage"]
                usage = {"input": int(u.get("prompt_tokens") or 0), "output": int(u.get("completion_tokens") or 0)}
            for choice in obj.get("choices") or []:
                delta = choice.get("delta") or choice.get("message") or {}
                if delta.get("content"):
                    text.append(str(delta["content"]))
                for tc in delta.get("tool_calls") or []:
                    index = tc.get("index")
                    index = index if isinstance(index, int) else len(parts)
                    slot = parts.setdefault(index, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = str(tc["id"])
                    fn = tc.get("function") or {}
                    name = fn.get("name")
                    if name and name != slot["name"]:
                        slot["name"] = name if not slot["name"] else slot["name"] + name
                    arg = fn.get("arguments")
                    if isinstance(arg, dict):
                        slot["args"] = json.dumps(arg, ensure_ascii=False)
                    elif arg:
                        slot["args"] += str(arg)
                if choice.get("finish_reason"):
                    finished = True
                    if choice["finish_reason"] == "length":
                        warnings.append(f"回覆到了 max_tokens（{self.max_tokens}）被切掉。")
        if not finished:
            raise LLMError("本地模型的回應中途斷了（沒有收到結束訊號）。")
        calls = []
        for index in sorted(parts):
            slot = parts[index]
            if not slot["name"]:
                continue
            args, ok = _args(slot["args"])
            if not ok:
                warnings.append(f"工具 {slot['name']} 的參數不是合法的 JSON（當成沒有參數）。")
            calls.append(ToolCall(name=slot["name"], args=args, id=slot["id"] or f"local-{index}"))
        return Reply(text="".join(text), tool_calls=calls, usage=usage)

    def _learn_context(self) -> None:
        """伺服器實際用的 context（只讀、只問一次，問不到就算了）：Ollama 沒設 context_size 時看 /api/ps（剛剛那次 chat 已經
        載入模型）；vLLM／其他看 /v1/models 的 max_model_len。"""
        if self._ctx_looked or self.server_ctx or (self.server == "ollama" and self.context_size):
            return
        self._ctx_looked = True
        try:
            if self.server == "ollama":
                for m in (self._get_json("/api/ps") or {}).get("models") or []:
                    if _same_model(m.get("name") or m.get("model") or "", self.model) and m.get("context_length"):
                        self.server_ctx = int(m["context_length"])
            else:
                self.server_ctx = self._openai_max_len()
        except Exception:
            pass

    def _openai_max_len(self) -> Optional[int]:
        for m in (self._get_json("/v1/models") or {}).get("data") or []:
            if m.get("id") == self.model and m.get("max_model_len"):
                return int(m["max_model_len"])
        if self.server == "lmstudio":
            try:
                for m in (self._get_json("/api/v0/models") or {}).get("data") or []:
                    if m.get("id") == self.model:
                        found = m.get("loaded_context_length") or m.get("max_context_length")
                        return int(found) if found else None
            except (LLMError, _HTTPProblem):
                return None
        return None

    # ── 唯讀的探測 ─────────────────────────────────────────────────────

    def inspect(self) -> dict:
        """唯讀：模型在不在、最大 context、設定合不合理。不送 chat／generate，不載入模型。"""
        out = {"server": self.server, "base_url": self.root, "model": self.model, "reachable": False,
               "model_found": None, "models": [], "model_size": 0, "max_context": None,
               "context_size": self.context_size, "capabilities": [], "model_info": {}, "problems": [], "notes": []}
        warn = url_warning(self.base_url)
        if warn:
            out["notes"].append(warn)
        if not self.model:
            out["problems"].append("還沒填模型名稱。")
        try:
            if self.server == "ollama":
                self._inspect_ollama(out)
            else:
                self._inspect_openai(out)
        except _HTTPProblem as p:
            out["problems"].append(self._http_text(p))
        except LLMError as e:
            out["problems"].append(str(e))
        return out

    def _inspect_ollama(self, out: dict) -> None:
        tags = self._get_json("/api/tags") or {}
        out["reachable"] = True
        models = tags.get("models") or []
        out["models"] = [{"name": m.get("name") or m.get("model") or "", "size": int(m.get("size") or 0),
                          "parameter_size": (m.get("details") or {}).get("parameter_size", ""),
                          "quantization": (m.get("details") or {}).get("quantization_level", "")} for m in models]
        if not self.model:
            return
        found = next((m for m in models if _same_model(m.get("name") or m.get("model") or "", self.model)), None)
        out["model_found"] = found is not None
        if found is None:
            names = "、".join(m["name"] for m in out["models"][:8]) or "（一個都沒有）"
            out["problems"].append(f"模型 {self.model} 不在這台 Ollama 上：先在終端機跑 `ollama pull {self.model}`"
                                   f"（已下載的：{names}）。")
            return
        out["model_size"] = int(found.get("size") or 0)
        try:
            show = self._get_json("/api/show", {"model": found.get("name") or self.model}, "POST") or {}
        except (LLMError, _HTTPProblem):
            show = {}
        info = show.get("model_info") or {}
        out["model_info"] = {k: v for k, v in info.items() if not isinstance(v, list) or len(v) <= 512}
        out["capabilities"] = list(show.get("capabilities") or [])
        arch = info.get("general.architecture") or ""
        max_ctx = info.get(f"{arch}.context_length") or (found.get("details") or {}).get("context_length")
        out["max_context"] = int(max_ctx) if max_ctx else None
        self._judge(out)
        caps = out["capabilities"]
        if self.supports_tools and caps and "tools" not in caps:
            out["problems"].append("這個模型沒有原生工具呼叫（Ollama capabilities 沒有 tools）：把 llm.tools 設成 false（走文字協定）。")
        if "vision" in caps:
            out["notes"].append("這個模型看得懂圖（vision）；SYNOX 目前還不會把圖送給 AI（之後另做）。")

    def _inspect_openai(self, out: dict) -> None:
        data = self._get_json("/v1/models") or {}
        out["reachable"] = True
        models = data.get("data") or []
        out["models"] = [{"name": m.get("id") or "", "size": 0} for m in models]
        if self.context_size:
            out["notes"].append(f"context_size={self.context_size} 對 {SERVER_LABELS[self.server]} 沒辦法由 SYNOX 設定，會被忽略："
                                + ("在 vLLM 啟動參數設 --max-model-len。" if self.server == "vllm" else
                                   "在 LM Studio 載入模型時設 Context Length。" if self.server == "lmstudio" else
                                   "在伺服器那邊設。"))
        if not self.model:
            return
        found = next((m for m in models if m.get("id") == self.model), None)
        out["model_found"] = found is not None
        if found is None:
            names = "、".join(m["name"] for m in out["models"][:8]) or "（一個都沒有）"
            out["problems"].append(f"伺服器上沒有模型 {self.model}（有的：{names}）。")
            return
        try:
            out["max_context"] = self._openai_max_len()
        except (LLMError, _HTTPProblem):
            out["max_context"] = None
        if out["max_context"]:
            self.server_ctx = out["max_context"]
            out["notes"].append(f"伺服器的 context 上限：{out['max_context']}。")
        else:
            out["notes"].append("伺服器沒有回報 context 上限：SYNOX 只能用回報的 token 數事後提醒截斷。")

    def _judge(self, out: dict) -> None:
        max_ctx, ctx = out.get("max_context"), self.context_size
        if ctx and max_ctx and ctx > max_ctx:
            out["problems"].append(f"context_size={ctx} 比模型的上限 {max_ctx} 還大：調到 {max_ctx} 以下。")
        if not ctx:
            out["notes"].append(f"沒設 context_size：用 Ollama 的預設（通常 {OLLAMA_DEFAULT_CTX}）。SYNOX 的提示加上工具說明可能超過，"
                                "Ollama 超過時會靜默截掉最前面（系統提示）——建議照設定頁的建議選一個。")
        elif ctx < 8192:
            out["notes"].append(f"context_size={ctx} 偏小：工具一多、對話一長就可能被截斷。")

    def probe(self) -> Optional[str]:
        """唯讀（不載入模型）：None＝模型在、設定合理；否則第一個問題。細節看 inspect()。"""
        report = self.inspect()
        return report["problems"][0] if report["problems"] else None

    def advice(self, *, prompt_chars: Optional[int] = None, ram=None) -> dict:
        """context 建議（synox/llm/local_advice.py）：唯讀探測＋這台的記憶體。連不上就退回靜態表。"""
        from synox.llm import local_advice
        report = self.inspect() if self.model or self.server == "ollama" else None
        return local_advice.from_report(report, prompt_chars=prompt_chars, max_tokens=self.max_tokens,
                                        server=self.server, ram=ram)


def report_lines(report: dict) -> List[str]:
    """inspect() 的結果 → doctor／文字精靈印的幾行。"""
    lines = []
    if report.get("reachable"):
        found = report.get("model_found")
        size = report.get("model_size") or 0
        head = f"模型 {report.get('model') or '（沒填）'}：" + ("✅ 在" if found else "❌ 不在" if found is False else "—")
        if size:
            head += f"（權重約 {size / 1e9:.1f} GB）"
        if report.get("max_context"):
            head += f"；模型最大 context {report['max_context']}"
        head += f"；設定的 context_size {report.get('context_size') or '0（伺服器預設）'}"
        lines.append(head)
    lines += [f"❌ {p}" for p in report.get("problems") or []]
    lines += [f"ℹ️ {n}" for n in report.get("notes") or []]
    return lines


def _same_model(name: str, wanted: str) -> bool:
    name, wanted = (name or "").strip(), (wanted or "").strip()
    return bool(wanted) and (name == wanted or name == wanted + ":latest" or name + ":latest" == wanted)


def _close(resp) -> None:
    try:
        resp.close()
    except Exception:
        pass


class _HTTPProblem(Exception):
    def __init__(self, status: int, body: str = ""):
        super().__init__(f"HTTP {status}")
        self.status = int(status)
        self.body = body or ""
