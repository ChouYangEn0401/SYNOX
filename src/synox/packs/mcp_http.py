"""
kind=mcp、mcp.transport=http（SDK P4b）：遠端 MCP 伺服器，Streamable HTTP（MCP 2025-06-18）。

    pack.json  "kind": "mcp", "capabilities": ["network"],
               "auth": {"type": "token", "fields": [{"name": "token", "label": "API token", "secret": true}]},
               "mcp": {"transport": "http", "url": "https://mcp.example.com/mcp", "timeout": 60,
                       "tools_allow": ["search"], "effects": {"search": "READ"}}

**協定**（只做子集，跟 stdio 一樣：initialize → notifications/initialized → tools/list → tools/call；ping）：
每個 JSON-RPC 訊息 POST 到 mcp.url（Accept: application/json, text/event-stream）。回應可以是
application/json（一個物件），或 text/event-stream——**只讀這一次 POST 的回應串流、找到自己那個 id 的回應就停**；
串流裡夾的通知、伺服器反問（sampling、roots…）不處理；不開 GET 的長連線、不做續傳（Last-Event-ID）。
initialize 的回應有 Mcp-Session-Id 就記住，之後每個請求都帶；也帶 MCP-Protocol-Version（協商出來的版本）。
帶了 Mcp-Session-Id 卻回 404＝伺服器那邊的連線過期了 → 丟掉、重新 initialize、再試一次（只一次）。
收掉時（閒置 10 分鐘、bot 關閉）送 DELETE 結束那個 session（盡力，失敗不管）。

**只往宣告的主機連**：每個請求都 POST 到 pack.json 寫死的那個網址（https；第 1 關檢查）；allow_redirects=False，
伺服器回 3xx 一律拒（不管轉到哪裡）。網址不能有樣板、帳密、#。

**token**：auth.type=token → auth.fields 的 secret 欄位（mcp.bearer 指定，沒寫＝第一個 secret 欄位；P2 的保管箱，
網頁「連接」表單填）；auth.type=oauth → packs/oauth.py 貼回網址的授權碼流程存的 access token。
只放在 Authorization: Bearer 標頭——不寫 log（這支檔案不 log 標頭）、不進 argv（沒有子程序）、不進給人／AI 看的字
（packs/mcp.py 的 redact 把這個人存的 secret 從結果與錯誤訊息遮掉；第 4 關擋 AI 把 secret 當參數）。
token 換了（指紋變）→ 下一次呼叫換一條新連線。

HTTP 用 requests；測試把 new_session 換成假的傳輸（不連網、不開埠）。
"""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import requests

from synox.packs.mcp import DEFAULT_TIMEOUT, MAX_LINE, Backend, McpError, McpPool, _snip, missing_secrets

CONNECT_TIMEOUT = 10.0
CLOSE_TIMEOUT = 5.0
MAX_BODY = MAX_LINE                     # 一次回應最多 4 MB（跟 stdio 一行的上限一樣）
SESSION_ID_MAX = 256
ACCEPT = "application/json, text/event-stream"


def new_session():
    """HTTP 傳輸。測試把這個換成假的（不連網）。"""
    return requests.Session()


def origin_of(url: str) -> Tuple[str, str, int]:
    parts = urlsplit(url)
    return (parts.scheme.lower(), (parts.hostname or "").lower(), parts.port or (443 if parts.scheme == "https" else 80))


def _visible_ascii(text: str) -> bool:
    return bool(text) and len(text) <= SESSION_ID_MAX and all(0x21 <= ord(c) <= 0x7E for c in text)


def parse_sse(body: str) -> List[str]:
    """text/event-stream → 每個事件的 data（多行 data: 用 \\n 接起來）。不認得的欄位（id、retry…）不管。"""
    events, data = [], []
    for raw in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw == "":
            if data:
                events.append("\n".join(data))
            data = []
            continue
        if raw.startswith(":"):
            continue
        name, _, value = raw.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name == "data":
            data.append(value)
    if data:
        events.append("\n".join(data))
    return events


class HttpSession:
    """一條遠端 MCP 連線。介面跟 packs/mcp.py 的 Session 一樣（request／notify／close／alive／busy／last_used），
    所以池、handshake、install() 共用。token 只在 _headers() 裡用，不出現在 repr、錯誤訊息、log。"""

    def __init__(self, url: str, *, token: str = "", http=None, name: str = "mcp-http",
                 clock: Callable[[], float] = time.monotonic, auth_hint: str = ""):
        self.url = url
        self.origin = origin_of(url)
        self.host = urlsplit(url).netloc.lower()
        self._token = token or ""
        self.http = http if http is not None else new_session()
        self.name = name
        self.clock = clock
        self.auth_hint = auth_hint
        self.last_used = clock()
        self.fingerprint = ""
        self.tools: Dict[str, dict] = {}
        self.server_info: dict = {}
        self.session_id: Optional[str] = None
        self.protocol: Optional[str] = None
        self.dead: Optional[str] = None
        self.busy = 0
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def __repr__(self) -> str:                     # 不印 token
        return f"<HttpSession {self.name} {self.host} {'alive' if self.alive else 'dead'}>"

    @property
    def alive(self) -> bool:
        return self.dead is None

    def _headers(self) -> Dict[str, str]:
        from synox import __version__
        h = {"Accept": ACCEPT, "Content-Type": "application/json", "User-Agent": f"synox/{__version__}"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            h["MCP-Protocol-Version"] = self.protocol
        return h

    def _die(self, message: str, *, retry: bool = False) -> McpError:
        with self._lock:
            if self.dead is None:
                self.dead = message
        return McpError(message, fatal=True, retry=retry)

    def _post(self, msg: dict, timeout: float):
        if origin_of(self.url) != self.origin:          # 縱深：網址是 pack.json 寫死的，不該變
            raise self._die("連線的網址跟 pack.json 宣告的不一樣，拒絕")
        data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        try:
            r = self.http.post(self.url, data=data, headers=self._headers(), timeout=(CONNECT_TIMEOUT, timeout),
                               allow_redirects=False, stream=True)
        except requests.Timeout:
            raise self._die(f"超過 {timeout:g} 秒沒有回應（{msg.get('method')}）")
        except requests.RequestException as e:
            raise self._die(f"連不到遠端 MCP（{self.host}，{type(e).__name__}）")
        code = int(getattr(r, "status_code", 0) or 0)
        if 300 <= code < 400:
            target = r.headers.get("Location") or ""
            where = urlsplit(urljoin(self.url, target)).netloc.lower() if target else "（沒寫）"
            _close(r)
            raise self._die(f"遠端 MCP 要求轉址到 {where}：SYNOX 只連 pack.json 宣告的 {self.host}，不跟著轉址")
        if code == 401:
            _close(r)
            raise self._die(f"遠端 MCP 不認這個 token（401：打錯、過期或被撤銷）。{self.auth_hint}".strip())
        if code == 403:
            _close(r)
            raise McpError("遠端 MCP 說沒有權限（403）：這個 token 的權限不夠")
        if code == 404 and self.session_id:
            _close(r)
            raise self._die("遠端 MCP 的連線過期了", retry=True)
        if code == 429:
            wait = r.headers.get("Retry-After") or "幾"
            _close(r)
            raise McpError(f"遠端 MCP 說太頻繁了，{_snip(wait, 10)} 秒後再試")
        if code >= 400 or code < 200:
            _close(r)
            raise self._die(f"遠端 MCP 回了 HTTP {code}") if code >= 500 or code < 200 else \
                McpError(f"遠端 MCP 不收這個請求（HTTP {code}）")
        return r

    def _body(self, r) -> str:
        chunks, size = [], 0
        try:
            for chunk in r.iter_content(65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_BODY:
                    raise self._die("遠端 MCP 回了太大的回應（超過 4 MB），收掉了")
                chunks.append(chunk)
        except requests.RequestException as e:
            raise self._die(f"讀遠端 MCP 的回應失敗（{type(e).__name__}）")
        finally:
            _close(r)
        return b"".join(chunks).decode("utf-8", "replace")

    def _messages(self, r) -> List[Any]:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        body = self._body(r)
        if ctype == "application/json":
            texts = [body]
        elif ctype == "text/event-stream":
            texts = parse_sse(body)
        else:
            raise self._die(f"遠端 MCP 回了看不懂的內容類型（{_snip(ctype or '沒寫', 40)}）")
        out: List[Any] = []
        for text in texts:
            if not text.strip():
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                raise self._die(f"遠端 MCP 回了看不懂的東西（不是 JSON：{_snip(text)}）")
            out += msg if isinstance(msg, list) else [msg]
        return out

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        if self.dead is not None:
            raise McpError(self.dead, fatal=True)
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        _close(self._post(msg, DEFAULT_TIMEOUT))     # 202 Accepted，沒有內容

    def request(self, method: str, params: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
        if self.dead is not None:
            raise McpError(self.dead, fatal=True)
        rid = next(self._ids)
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        with self._lock:
            self.busy += 1
        try:
            r = self._post(msg, timeout)
            if method == "initialize":
                sid = r.headers.get("Mcp-Session-Id")
                if sid is not None:
                    if not _visible_ascii(sid):
                        _close(r)
                        raise self._die("遠端 MCP 給的 Mcp-Session-Id 不合規則")
                    self.session_id = sid
            if int(getattr(r, "status_code", 0) or 0) == 202:
                _close(r)
                raise self._die(f"遠端 MCP 沒有回 {method} 的結果")
            reply = None
            for item in self._messages(r):
                if isinstance(item, dict) and "method" not in item and item.get("id") == rid:
                    reply = item
                    break                              # 通知、伺服器反問一律不處理
        finally:
            with self._lock:
                self.busy -= 1
            self.last_used = self.clock()
        if reply is None:
            raise self._die(f"遠端 MCP 的回應裡沒有 {method} 的結果")
        if isinstance(reply.get("error"), dict):
            err = reply["error"]
            raise McpError(f"工具伺服器回了錯誤：{_snip(err.get('message') or '沒有說明', 200)}（代碼 {err.get('code')}）")
        result = reply.get("result")
        if not isinstance(result, dict):
            raise McpError("工具伺服器回的結果不是物件")
        if method == "initialize" and isinstance(result.get("protocolVersion"), str) and \
                _visible_ascii(result["protocolVersion"]):
            self.protocol = result["protocolVersion"]
        return result

    def close(self, grace: float = 1.0) -> None:
        """收掉：還活著、有 Mcp-Session-Id 的送一個 DELETE 結束伺服器那邊的 session（盡力，失敗不管）。"""
        with self._lock:
            was_alive = self.dead is None
            if was_alive:
                self.dead = "已經關閉"
        if was_alive and self.session_id and grace:
            try:
                _close(self.http.delete(self.url, headers=self._headers(), timeout=(CONNECT_TIMEOUT, CLOSE_TIMEOUT),
                                        allow_redirects=False))
            except Exception:
                logging.info("[MCP] %s: DELETE session failed (ignored)", self.name)


def _close(r) -> None:
    try:
        r.close()
    except Exception:
        pass


# ── 連法：給 packs/mcp.py 的 install() ─────────────────────────────────

def bearer_field(m) -> str:
    """auth.type=token：當 Bearer 送的欄位（mcp.bearer，沒寫＝第一個 secret 欄位）。"""
    from synox.packs import secrets as pack_secrets
    if (m.auth_info or {}).get("type") != "token":
        return ""
    wanted = (m.mcp or {}).get("bearer")
    secret = [f["name"] for f in pack_secrets.fields_of(m) if f["secret"]]
    if wanted:
        return wanted if wanted in secret else ""
    return secret[0] if secret else ""


class HttpBackend(Backend):
    start_failed = "連不上遠端 MCP"
    again = "（下一次呼叫會重新連線）"

    def __init__(self, app, pack, config, pool: McpPool):
        self.app, self.pack, self.config, self.pool = app, pack, config, pool
        self.m = pack.manifest
        self.url = self.m.mcp["url"]
        self.kind = (self.m.auth_info or {}).get("type", "none")
        self.field = bearer_field(self.m)
        self.flow = None
        if self.kind == "oauth":
            from synox.packs import oauth
            self.flow = oauth.flow_for(app, pack)

    def hint(self) -> str:
        if self.flow is not None:
            return self.flow.relogin_hint()
        return "到網頁介面的工具頁按「連接」重新填。" if self.field else ""

    def token(self, user) -> str:
        if self.flow is not None:
            return self.flow.token(user)
        if not self.field or self.pack.secrets is None or not self.pack.secrets.available:
            return ""
        try:
            return self.pack.secrets.get(self.m.name, self.field, user) or ""
        except Exception:
            logging.exception("[MCP] %s: cannot read the bearer token", self.m.name)
            return ""

    def plan(self, user):
        from synox.packs import oauth
        try:
            token = self.token(user)
        except oauth.OAuthError as e:
            raise McpError(str(e))
        digest = hashlib.sha256(json.dumps([self.url, token]).encode("utf-8")).hexdigest()
        return token, digest

    def open(self, user, ctx) -> HttpSession:
        tg = getattr(self.pool.scope.identity(user), "tg_id", None)
        logging.info("[MCP] %s: connecting to %s for %s", self.m.name, urlsplit(self.url).netloc, tg)
        return HttpSession(self.url, token=ctx, http=new_session(), name=f"{self.m.name}-{tg or 'x'}",
                           clock=self.pool.clock, auth_hint=self.hint())

    def not_connected(self, user) -> str:
        if self.flow is not None:
            return self.flow.not_connected(user)
        return missing_secrets(self.pack, user)

    def commands(self, group, taken: List[str]) -> None:
        if self.flow is not None:
            self.flow.install_commands(group, taken)


__all__ = ["HttpBackend", "HttpSession", "bearer_field", "new_session", "origin_of", "parse_sse"]
