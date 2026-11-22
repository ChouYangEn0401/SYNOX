"""
經創始維護者的套件 ntu_easy_llm 取得的 AI 來源（docs/adr/0046；之前的寫法見 0.5 時代的說明，下面「舊路」）。

兩種設定：

    舊的四種 kind（照舊能讀、照舊存）：
    {"kind": "openai",        "api_key": "vault:llm_api_key", "model": "gpt-4.1-mini"}
    {"kind": "anthropic",     "api_key": "vault:llm_api_key", "model": "claude-sonnet-4-5"}
    {"kind": "gemini",        "api_key": "vault:llm_api_key", "model": "gemini-2.5-flash"}
    {"kind": "openai_compat", "base_url": "http://localhost:11434/v1", "api_key": "", "model": "llama3.1",
     "tools": true}             公司閘道、Ollama；閘道沒開 tool-calling 就寫 false → agent 走文字協定（textproto）

    新的 kind=source（來源目錄上的任何一個，路徑＝ntu_easy_llm 的分類樹；llm/sources.py 檢查）：
    {"kind": "source", "source": "remote/api_key/llop", "model": "any",
     "source_options": {"llop_profile": "default", "transport": "auto"}}

- ntu_easy_llm 是選用相依（pyproject 的 `llm` 組）：**用到的時候才 import**，沒裝就丟 LLMError 說怎麼裝，
  其他功能（指令、Claude Code、本地模型、假 AI）不受影響。SYNOX **不直接 import llmop**（LLOP 經 ntu_easy_llm[llop]）。
- 0.6 起（`ntu_easy_llm.adapters`）：用 `get_adapter(Profile)` 拿 adapter（`SourceAdapter` 包成 SYNOX 的 ChatAdapter）。
  舊的四種 kind：這台的 ntu_easy_llm 有那個來源的 adapter 就用它（新路）；沒有（0.5，或 0.6 的預發布版還沒有
  HTTP adapter）就照舊經 `ntu_easy_llm.agent.chat`（舊路）。兩條路對使用者一樣。
- adapter 只會聊天（invariant 2）：這裡只做 SYNOX 的 Message／ToolSpec／Reply 跟 ntu_easy_llm 的格式互轉，
  以及把它的錯誤照**種類**（`.kind`，llm/kinds.py）翻成一句中文；沒有種類（0.5）才退回看狀態碼（base.http_error）。
- 停止詞（docs/adr/0010）：新路照 adapter 的 `capabilities().stop`；舊路 `agent.chat` 沒有 stop 參數＝supports_stop=False。
- 圖片（docs/adr/0021）：新路用 ntu_easy_llm 正式的 `types.ImagePart`；舊路照舊把有圖的 user 訊息 content 換成
  各家自己的 content parts（依賴 0.5 原樣傳遞，不是套件公開保證的介面；套件改版前要重跑 tests/test_vision.py）：
    openai／gemini（OpenAI 相容端點）／openai_compat：[{"type":"text"}, {"type":"image_url","image_url":{"url":"data:…"}}]
    anthropic：[{"type":"image","source":{"type":"base64","media_type":…,"data":…}}, {"type":"text"}]
  `vision`＝auto（內建名單，vision.cloud_supports）｜on｜off；不支援卻收到圖＝LLMError「此來源不支援圖片」，不偷偷丟掉圖。
- session：測試傳一個假的 requests 風格物件（不連網），舊路交給 agent.chat、新路交給 get_adapter(http=)。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from synox.llm import kinds
from synox.llm.base import (ASSISTANT, USER, ChatAdapter, LLMError, Message, Reply, ToolCall, ToolSpec, has_images,
                            http_error, no_vision)

INSTALL_HINT = ("在 SYNOX 資料夾跑 `.venv\\Scripts\\python.exe -m pip install -e .[llm]`（裝官方 release 的 wheel），"
                "或改選 Claude Code／本地模型／先不用 AI。")
MISSING = "還沒安裝 ntu_easy_llm：用 API 金鑰的 AI（OpenAI、Anthropic、Gemini、相容端點）要靠它。" + INSTALL_HINT
MIN_VERSION = (0, 5, 0)
CONTRACT_VERSION = (0, 6, 0)        # get_adapter、ErrorKind、catalog、waterfall 的型別從這一版起才有
NEEDS_06 = "這個來源要 ntu_easy_llm 0.6 以上（現在的版本沒有來源目錄）。" + INSTALL_HINT

# kind → (ntu_easy_llm 的 provider, 顯示名稱)
PROVIDERS = {
    "openai": ("openai", "OpenAI"),
    "anthropic": ("anthropic", "Anthropic"),
    "gemini": ("gemini", "Gemini"),
    "openai_compat": ("openai_compatible", "OpenAI 相容"),
}
# 舊的四種 kind 在 0.6 分類樹上的位置（設定照舊存舊 kind；這張表只用來找新路的 adapter、在目錄上對位置）
LEGACY_SOURCES = {
    "openai": "remote/api_key/openai",
    "anthropic": "remote/api_key/anthropic",
    "gemini": "remote/api_key/gemini",
    "openai_compat": "remote/api_key/openai_compatible",
}
SECRET_REF = "synox:llm_api_key"     # Profile 裡只放引用；真的金鑰由 SYNOX 自己給（resolve_secret）


def _version_of(module) -> tuple:
    version = getattr(module, "__version__", "0")
    parts = []
    for p in str(version).split(".")[:3]:
        digits = "".join(ch for ch in p if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
        if digits != p:                 # 0.6.0.dev0、0.6.0a1：數字後面還有字就停
            break
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def load_agent_module():
    """import ntu_easy_llm.agent；沒裝或太舊丟 LLMError（中文、說怎麼裝）。"""
    try:
        import ntu_easy_llm
        from ntu_easy_llm import agent
    except ImportError:
        raise LLMError(MISSING)
    if _version_of(ntu_easy_llm) < MIN_VERSION:
        raise LLMError(f"ntu_easy_llm 版本太舊（{getattr(ntu_easy_llm, '__version__', '?')}），要 0.5.0 以上才有工具呼叫。"
                       + INSTALL_HINT)
    return agent


def installed() -> bool:
    try:
        load_agent_module()
    except LLMError:
        return False
    return True


def contract():
    """ntu_easy_llm 0.6 的介面（`adapters` 模組）；沒裝或太舊＝None。不 import 任何 SDK。"""
    try:
        import ntu_easy_llm
        if _version_of(ntu_easy_llm) < CONTRACT_VERSION:
            return None
        from ntu_easy_llm import adapters
    except ImportError:
        return None
    if not callable(getattr(adapters, "get_adapter", None)):
        return None
    return adapters


def version_text() -> str:
    """裝了哪一版（設定頁、doctor）；沒裝＝""。"""
    try:
        import ntu_easy_llm
    except ImportError:
        return ""
    return str(getattr(ntu_easy_llm, "__version__", "?"))


# ── 格式互轉（新路）───────────────────────────────────────────────────


def to_easy_messages(messages: Sequence[Message]) -> list:
    """SYNOX 的 Message → ntu_easy_llm.types.Message（圖片用正式的 ImagePart）。"""
    from ntu_easy_llm.agent import ToolCall as EasyCall
    from ntu_easy_llm.types import ImagePart as EasyImage
    from ntu_easy_llm.types import Message as EasyMessage
    out = []
    for m in messages:
        calls = [EasyCall(c.id or f"call_{i}", c.name, dict(c.args or {})) for i, c in enumerate(m.tool_calls)] \
            if m.role == ASSISTANT else []
        images = [EasyImage(p.mime, p.data) for p in m.images] if m.role == USER else []
        out.append(EasyMessage(m.role, m.content or "", tool_calls=calls, tool_call_id=m.tool_call_id or "",
                               name=m.name or "", images=images))
    return out


def to_easy_tools(tools: Sequence[ToolSpec]) -> list:
    from ntu_easy_llm.agent import Tool as EasyTool
    return [EasyTool(t.name, t.description, t.parameters) for t in tools]


def from_easy_reply(reply) -> Reply:
    """ntu_easy_llm 的 ChatReply（或 ChatResult）→ SYNOX 的 Reply（思考段拿掉；finish 只留 length／thinking）。"""
    from synox.llm.textproto import strip_think
    calls = [ToolCall(name=c.name, args=dict(c.arguments or {}), id=c.id) for c in (reply.tool_calls or [])]
    usage = getattr(reply, "usage", None)
    finish = str(getattr(reply, "finish", "") or "")
    return Reply(text=strip_think(reply.text or "")[0], tool_calls=calls,
                 usage={"input": int(getattr(usage, "input_tokens", 0) or 0),
                        "output": int(getattr(usage, "output_tokens", 0) or 0)},
                 warnings=[str(w) for w in (getattr(reply, "warnings", None) or [])],
                 finish=finish if finish in ("length", "thinking") else "")


def error_from(e: BaseException, where: str) -> LLMError:
    """ntu_easy_llm 的例外 → SYNOX 的 LLMError（一句中文，帶 kind）。沒有 kind（0.5）＝照狀態碼。"""
    if isinstance(e, LLMError):
        return e
    kind = kinds.kind_of(e)
    status = getattr(e, "status", None)
    body = str(getattr(e, "body", "") or "")
    if kind is None:
        if status is not None:
            return LLMError(http_error(int(status), body))
        return LLMError(f"{where}：{e}")
    return LLMError(kinds.message_for(kind, where, body, status if isinstance(status, int) else None), kind=kind)


def make_profile(source: str, model: str = "", *, base_url: str = "", has_key: bool = False,
                 options: Optional[Dict[str, Any]] = None, label: str = "", profile_id: str = "synox"):
    """SYNOX 的設定 → ntu_easy_llm 的 Profile（金鑰只放引用 SECRET_REF）。設定不對＝LLMError（一句中文）。"""
    from ntu_easy_llm.profiles import Profile, SecretRef
    try:
        return Profile(id=profile_id, source=source, model=model or "", base_url=(base_url or "").strip() or None,
                       secret=SecretRef(SECRET_REF) if has_key else None, options=dict(options or {}),
                       label=label)
    except ValueError as e:                     # ConfigError 是 ValueError；訊息只寫欄位，不寫值
        raise LLMError(f"AI 來源的設定不對：{e}")


def native_adapter(source: str, model: str = "", *, base_url: str = "", api_key: str = "",
                   options: Optional[Dict[str, Any]] = None, http=None, label: str = "",
                   profile_id: str = "synox", required: bool = False):
    """ntu_easy_llm 0.6 的 adapter；這台沒有（沒裝、太舊、沒有這個來源的 adapter、它的 check 說不能用）：
    required=False＝回 None（呼叫端走舊路），required=True＝丟 LLMError 說原因。"""
    adapters = contract()
    if adapters is None:
        if required:
            raise LLMError(NEEDS_06 if installed() else MISSING)
        return None
    ok, reason = adapters.adapter_status(source)
    if not ok:
        if required:
            from synox.llm.sources import unavailable_text
            raise LLMError(unavailable_text(source, reason))
        return None
    profile = make_profile(source, model, base_url=base_url, has_key=bool(api_key), options=options, label=label,
                           profile_id=profile_id)
    key = api_key or ""
    try:
        return adapters.get_adapter(profile, http=http, resolve_secret=lambda ref: key)
    except ValueError as e:                     # AdapterNotFound／ConfigError
        if required:
            raise LLMError(f"AI 來源還不能用：{e}")
        return None


# ── 新路：任何 ntu_easy_llm adapter 包成 SYNOX 的 ChatAdapter ───────────────


class SourceAdapter(ChatAdapter):
    """包住一個 ntu_easy_llm 0.6 的 adapter（kind=source，以及舊的四種 kind 找得到新路時）。

    - supports_tools：設定寫了 tools 就照它；沒寫＝adapter 的 capabilities().tools 不是 False 就算支援。
    - supports_stop＝capabilities().stop；supports_vision：capabilities().vision 是 True＝支援、False＝不支援、
      None（不知道）＝照 llm.vision（on 才算支援）。
    - weak：本地來源（local/…）＝True（auto 開關當本地／弱來源，agent/auto.py）。
    """

    def __init__(self, adapter, *, kind: str = "source", name: str = "", tools=None, vision: str = "auto",
                 max_tokens: int = 1024, temperature=None, timeout: Optional[float] = None, where: str = ""):
        self.inner = adapter
        self.kind = kind
        profile = getattr(adapter, "profile", None)
        self.source = str(getattr(profile, "source", "") or "")
        self.model = str(getattr(profile, "model", "") or "")
        self.base_url = str(getattr(profile, "base_url", "") or "")
        self.name = name or f"{self.source}（{self.model or '未指定模型'}）"
        self.where = where or self.base_url or self.name
        caps = adapter.capabilities()
        self.caps = caps
        self.supports_tools = bool(tools) if tools is not None else caps.tools is not False
        self.supports_stop = bool(caps.stop)
        mode = vision if vision in ("auto", "on", "off") else "auto"
        self.vision = mode
        if mode == "off" or caps.vision is False:
            self.supports_vision = False
        else:
            self.supports_vision = caps.vision is True or mode == "on"
        self.weak = self.source.startswith("local/")
        self.max_tokens = int(max_tokens)
        self.temperature = temperature
        self.timeout = timeout

    supports_max_tokens = True          # chat(max_tokens=) 可以這一次放大回覆上限（agent 自動接續用）

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = (), *, stop: Sequence[str] = (),
             max_tokens: Optional[int] = None) -> Reply:
        if has_images(messages) and not self.supports_vision:
            raise no_vision(self.name)
        specs = to_easy_tools(tools) if tools and self.supports_tools else None
        try:
            reply = self.inner.chat(to_easy_messages(messages), specs, max_tokens=int(max_tokens or self.max_tokens),
                                    temperature=self.temperature, stop=tuple(stop) if self.supports_stop else (),
                                    timeout=self.timeout)
        except Exception as e:
            if isinstance(e, (TypeError, AttributeError, AssertionError)) and kinds.kind_of(e) is None:
                raise                                  # 程式錯誤不翻成「AI 出錯」，讓 log 看得到
            raise error_from(e, self.where)
        return from_easy_reply(reply)

    def probe(self) -> Optional[str]:
        """「測一下」：真的送一句（probe(send=True)）。None＝好；否則一句中文。"""
        if not self.model and not self.source.startswith("remote/subscription/"):
            if self.source != "remote/api_key/llop":
                return "還沒填模型名稱。"
        try:
            result = self.inner.probe(send=True, timeout=self.timeout or 60.0)
        except Exception as e:                         # probe 照約定不丟例外；丟了也不讓設定頁當掉
            return str(error_from(e, self.where))
        if result.ok:
            return None
        if result.kind is not None:
            return kinds.message_for(result.kind, self.where, result.reason)
        return result.reason or "接不通（原因不明）。"

    def list_models(self, timeout: float = 15.0) -> List[dict]:
        """這個來源有哪些模型（給設定頁）：聊天用的排前面、已載入的排最前面；embedding 不列。失敗丟 LLMError。"""
        try:
            found = self.inner.list_models(timeout=timeout)
        except Exception as e:
            raise error_from(e, self.where)
        return models_view(found)


def models_view(found) -> List[dict]:
    rows = []
    for m in found or []:
        if str(getattr(m, "kind", "chat") or "chat") == "embedding":
            continue
        rows.append({"id": str(m.id), "label": str(getattr(m, "label", "") or ""),
                     "context": getattr(m, "context", None), "loaded": getattr(m, "loaded", None),
                     "vision": getattr(m, "vision", None), "tools": getattr(m, "tools", None)})
    rows.sort(key=lambda r: (r["loaded"] is not True, r["id"].lower()))
    return rows


# ── 舊的四種 kind ─────────────────────────────────────────────────────


class EasyLLMAdapter(ChatAdapter):

    def __init__(self, kind: str, api_key: str = "", model: str = "", *, base_url: str = "", tools: bool = True,
                 max_tokens: int = 1024, timeout: float = 90.0, session=None, vision: str = "auto"):
        if kind not in PROVIDERS:
            raise LLMError(f"不認得的 AI 來源 {kind}。")
        if kind == "openai_compat" and not (base_url or "").strip():
            raise LLMError("相容端點要填網址（例如 http://localhost:11434/v1 或公司給的 https://…/v1）。")
        self.kind = kind
        self.provider, label = PROVIDERS[kind]
        self.api_key = api_key or ""
        self.model = model or ""
        self.base_url = (base_url or "").strip().rstrip("/")
        self.supports_tools = bool(tools)
        self.max_tokens = int(max_tokens)
        self.timeout = timeout
        self._session = session
        from synox.llm.vision import cloud_supports, resolve
        self.vision = vision if vision in ("auto", "on", "off") else "auto"
        self.supports_vision = resolve(self.vision, lambda: cloud_supports(kind, self.model))
        self.name = f"{label}（{self.model or '未指定模型'}）"
        self._native = None
        self._looked = False

    def native(self) -> Optional[SourceAdapter]:
        """新路（0.6 有這個來源的 adapter）；沒有＝None（走舊路）。只找一次。"""
        if self._looked:
            return self._native
        self._looked = True
        try:
            inner = native_adapter(LEGACY_SOURCES[self.kind], self.model, base_url=self.base_url,
                                   api_key=self.api_key, http=self._session)
        except LLMError:
            inner = None
        if inner is not None:
            self._native = SourceAdapter(inner, kind=self.kind, name=self.name, tools=self.supports_tools,
                                         vision="on" if self.supports_vision else "off", max_tokens=self.max_tokens,
                                         timeout=self.timeout, where=self.base_url or PROVIDERS[self.kind][1])
        return self._native

    @property
    def supports_stop(self) -> bool:            # 舊路 agent.chat 沒有 stop 參數；新路照 capabilities
        native = self.native()
        return bool(native is not None and native.supports_stop)

    def to_neutral(self, messages: Sequence[Message]) -> List[dict]:
        out = []
        for m in messages:
            item = {"role": m.role, "content": self.content_of(m)}
            if m.tool_calls:
                item["tool_calls"] = [{"id": c.id, "name": c.name, "arguments": c.args} for c in m.tool_calls]
            if m.tool_call_id:
                item["tool_call_id"] = m.tool_call_id
            if m.name:
                item["name"] = m.name
            out.append(item)
        return out

    def content_of(self, m: Message):
        """沒有圖＝原本的字串；有圖（只有 user 訊息）＝這家的 content parts（見檔頭，舊路才用）。"""
        if not m.images or m.role != USER:
            return m.content
        if self.kind == "anthropic":
            return [{"type": "image", "source": {"type": "base64", "media_type": p.mime, "data": p.b64()}}
                    for p in m.images] + [{"type": "text", "text": m.content or ""}]
        return [{"type": "text", "text": m.content or ""}] + \
            [{"type": "image_url", "image_url": {"url": p.data_uri()}} for p in m.images]

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = (), *, stop: Sequence[str] = ()) -> Reply:
        if has_images(messages) and not self.supports_vision:
            raise no_vision(self.name)
        agent = load_agent_module()
        if self.kind != "openai_compat" and not self.api_key:
            raise LLMError(f"還沒填 {PROVIDERS[self.kind][1]} 的 API key。")
        native = self.native()
        if native is not None:
            return native.chat(messages, tools, stop=stop)
        specs = [agent.Tool(t.name, t.description, t.parameters) for t in tools] \
            if tools and self.supports_tools else None
        where = self.base_url or PROVIDERS[self.kind][1]
        try:
            reply = agent.chat(self.provider, self.model, self.to_neutral(messages), specs, api_key=self.api_key,
                               base_url=self.base_url or None, max_tokens=self.max_tokens, timeout=self.timeout,
                               session=self._session)
        except agent.LLMHTTPError as e:
            if kinds.kind_of(e) is None:
                raise LLMError(http_error(e.status, e.body))
            raise error_from(e, where)
        except agent.LLMConnectionError as e:
            kind = kinds.kind_of(e) or "connection"
            if kind == "timeout":
                raise LLMError(kinds.message_for("timeout", where), kind=kind)
            raise LLMError(f"連不到 {where}。檢查網址和網路。", kind="connection")
        except agent.LLMResponseError:
            raise LLMError(f"{where} 回的格式看不懂（是不是網址填錯了？）。", kind="bad_response")
        except ValueError as e:
            raise LLMError(f"設定不完整：{e}")
        return from_easy_reply(reply)

    def probe(self) -> Optional[str]:
        if not self.model:
            return "還沒填模型名稱。"
        try:
            load_agent_module()
        except LLMError as e:
            return str(e)
        return super().probe()


# ── kind=source ──────────────────────────────────────────────────────


def build_source(llm: dict, api_key: str = "", *, http=None, vision: str = "auto",
                 max_tokens: int = 1024) -> SourceAdapter:
    """config 的 llm（kind=source，已經過 sources.validate）→ SourceAdapter。這台不能用＝LLMError 說原因。"""
    from synox.llm import sources
    s = sources.validate(llm)
    options = dict(s["options"])
    if "max_tokens" in options:
        max_tokens = int(options["max_tokens"])
    timeout = options.get("timeout")
    temperature = options.get("temperature")
    tools = options.get("tools")
    inner = native_adapter(s["source"], s["model"], base_url=s["base_url"], api_key=api_key, options=options,
                           http=http, required=True)
    label = sources.label_of(s["source"])
    name = f"{label}（{s['model'] or '預設模型'}）"
    if timeout in (None, ""):
        timeout = sources.default_timeout(s["source"], s["base_url"])
    return SourceAdapter(inner, kind=sources.KIND, name=name, tools=tools, vision=vision, max_tokens=max_tokens,
                         temperature=temperature, timeout=float(timeout), where=s["base_url"] or label)
