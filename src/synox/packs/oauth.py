"""
遠端 MCP 的 OAuth 授權碼流程（P4b，選配、預設關：pack.json 寫了 auth.type=oauth＋auth.oauth 才有）。

    "auth": {"type": "oauth",
             "oauth": {"authorize_url": "https://…/authorize", "token_url": "https://…/token",
                       "client_id": "…", "scope": "read write",
                       "redirect_uri": "http://127.0.0.1:47232/",      沒寫＝這個；SYNOX 不在這個埠聽
                       "receiver": "paste"}}                          paste（預設）｜loopback（只有介面，執行時拒）

**貼回網址（receiver=paste，這一版唯一能用的）**：仿 connectors/google-calendar——
/<群組>_login（只收私訊、不給 AI）→ SYNOX 產 PKCE（S256）＋隨機 state（32 bytes、15 分鐘、只能用一次，
只放在記憶體）→ 給一個授權網址 → 使用者在瀏覽器登入、按允許 → 瀏覽器被轉到 redirect_uri，**那裡沒有人在聽**
（SYNOX 不開任何埠），畫面打不開 → 使用者把網址列整串用 /<群組>_code <貼上> 傳回來 → state 對得上才拿 code＋
code_verifier 去 token_url 換 token。就算這台電腦上剛好有別的程式在聽那個埠，沒有 code_verifier 也換不到 token。
token 存進保管箱（PackSecrets，跟「連接」表單同一個地方；伺服器版每人一份），access token 過期前用 refresh token 換新的。
授權請求與換 token 都帶 resource＝mcp.url（RFC 8707，MCP 授權規格要求）。client_id 要事先在服務那邊登記
（這一版不做動態註冊、不做 metadata 探索：端點都寫在 pack.json，第 1 關檢查一定 https）。

**loopback（receiver=loopback）只有介面**：設計是「伺服器上暫時開 127.0.0.1 的隨機埠、收到一次授權碼就關、最久 5 分鐘」。
擁有者同意它在別台伺服器上可行，但這台電腦不開埠，所以 LoopbackListener 只定義介面，叫它一律丟 OAuthError（說明為什麼）。
要做的人：實作 Listener.redirect_uri（綁 127.0.0.1:0 拿隨機埠）與 Listener.wait（收一次 GET、比 state、回一頁「可以關了」、
關掉 socket；超過 max_seconds 自己關），其他（PKCE、state、換 token、存保管箱）照用這支。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import requests

DEFAULT_REDIRECT = "http://127.0.0.1:47232/"
PENDING_SECONDS = 900
LOOPBACK_MAX_SECONDS = 300
REFRESH_EARLY = 60
TIMEOUT = (10, 30)
ACCESS = "oauth_access_token"
REFRESH = "oauth_refresh_token"
EXPIRES = "oauth_expires_at"
FIELDS = [{"name": ACCESS, "label": "OAuth access token", "secret": True, "env": "", "kind": "text",
           "required": True, "help": ""},
          {"name": REFRESH, "label": "OAuth refresh token", "secret": True, "env": "", "kind": "text",
           "required": False, "help": ""},
          {"name": EXPIRES, "label": "OAuth 到期時間", "secret": False, "env": "", "kind": "text",
           "required": False, "help": ""}]
LOOPBACK_TODO = ("這個 pack 要用 loopback 收授權碼（SYNOX 暫時開 127.0.0.1 的埠），這一版沒有實作：這台電腦不開任何網路埠。"
                 "請 pack 作者改用 receiver=paste（把瀏覽器網址列貼回來），或在允許開埠的伺服器上等之後的版本。")


class OAuthError(Exception):
    """給人看的一句話。"""


def pkce_pair() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)                              # 86 字（規定 43–128）
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def parse_pasted(text: str) -> Tuple[str, str, str]:
    """使用者貼的東西 → (code, state, error)。整串網址、只有 ?code=… 的那一段、或只有授權碼都收。"""
    text = (text or "").strip().strip("<>\"'")
    if "code=" in text or "error=" in text:
        query = urlparse(text).query if "://" in text else text.split("?", 1)[-1]
        q = parse_qs(query)
        return (q.get("code") or [""])[0], (q.get("state") or [""])[0], (q.get("error") or [""])[0]
    return text, "", ""


# ── 收授權碼的方式 ───────────────────────────────────────────────────

class Listener:
    """授權碼怎麼回到 SYNOX。redirect_uri(設定的) → 這一次要用的 redirect_uri；instructions(code 指令) → 給人看的步驟。"""
    name = ""

    def redirect_uri(self, configured: str) -> str:          # pragma: no cover - 介面
        raise NotImplementedError

    def instructions(self, code_command: str) -> List[str]:  # pragma: no cover - 介面
        raise NotImplementedError


class PasteListener(Listener):
    """不開埠：瀏覽器轉到一個沒有人在聽的 127.0.0.1 網址，使用者把網址列貼回來。"""
    name = "paste"

    def redirect_uri(self, configured: str) -> str:
        return configured or DEFAULT_REDIRECT

    def instructions(self, code_command: str) -> List[str]:
        return ["2. 最後瀏覽器會顯示「無法連上這個網站」——這是正常的（SYNOX 沒有開任何網路埠）。",
                f"3. 把瀏覽器網址列那一整串（裡面有 code=…）複製，傳：{code_command} <貼上>",
                f"連結 {PENDING_SECONDS // 60} 分鐘內有效、只能用一次。"]


class LoopbackListener(Listener):
    """（預留）暫時開 127.0.0.1 的隨機埠、收一次授權碼就關、最久 LOOPBACK_MAX_SECONDS 秒。這一版不實作：一律拒。"""
    name = "loopback"
    max_seconds = LOOPBACK_MAX_SECONDS

    def redirect_uri(self, configured: str) -> str:
        raise OAuthError(LOOPBACK_TODO)

    def instructions(self, code_command: str) -> List[str]:
        raise OAuthError(LOOPBACK_TODO)

    def wait(self, state: str, timeout: float = LOOPBACK_MAX_SECONDS) -> Tuple[str, str]:
        raise OAuthError(LOOPBACK_TODO)


LISTENERS = {"paste": PasteListener, "loopback": LoopbackListener}


# ── 一個 pack 的流程 ─────────────────────────────────────────────────

def _http():
    from synox.packs import mcp_http
    return mcp_http.new_session()                 # 測試換掉這一個（同一個假傳輸）


class Flow:
    """一個 kind=mcp http、auth.type=oauth 的 pack。pending（state、code_verifier）只放記憶體。"""

    def __init__(self, pack, clock=time.time):
        self.pack = pack
        self.m = pack.manifest
        self.cfg = dict((self.m.auth_info or {}).get("oauth") or {})
        self.resource = self.m.mcp.get("url", "")
        self.listener: Listener = LISTENERS.get(self.cfg.get("receiver") or "paste", PasteListener)()
        self.clock = clock
        self._pending: Dict[object, dict] = {}
        self._lock = threading.Lock()
        self.names = {"login": "login", "code": "code", "logout": "logout"}

    # 保管箱

    def _store(self):
        store = self.pack.secrets
        if store is None or not store.available:
            raise OAuthError(f"🔌 {self.m.title} 要先登入，但保管箱沒有打開（python -m synox doctor 看原因）。")
        return store

    def _save(self, user, body: dict) -> None:
        values = {ACCESS: str(body["access_token"]),
                  EXPIRES: str(int(self.clock() + int(body.get("expires_in") or 3600)))}
        if body.get("refresh_token"):
            values[REFRESH] = str(body["refresh_token"])
        self._store().update(self.m.name, FIELDS, values, user)

    def forget(self, user) -> None:
        self._store().update(self.m.name, FIELDS, {}, user, clear=[f["name"] for f in FIELDS])

    def token(self, user) -> str:
        """這個人的 access token（快過期就先用 refresh token 換新的）；還沒登入回 ""。"""
        try:
            store = self._store()
        except OAuthError:
            return ""
        access = store.get(self.m.name, ACCESS, user) or ""
        try:
            expires = float(store.get(self.m.name, EXPIRES, user) or 0)
        except ValueError:
            expires = 0.0
        if access and (not expires or self.clock() < expires - REFRESH_EARLY):
            return access
        refresh = store.get(self.m.name, REFRESH, user) or ""
        if not refresh:
            return access
        body = self._post_token({"grant_type": "refresh_token", "refresh_token": refresh,
                                 "client_id": self.cfg["client_id"], "resource": self.resource})
        self._save(user, body)
        return str(body["access_token"])

    def not_connected(self, user) -> str:
        try:
            self._store()
        except OAuthError as e:
            return str(e)
        if self.pack.secrets.get(self.m.name, ACCESS, user):
            return ""
        return f"🔌 {self.m.title} 還沒登入：私訊打 /{self.m.group}_{self.names['login']}。"

    def relogin_hint(self) -> str:
        return f"用 /{self.m.group}_{self.names['login']} 重新登入。"

    # 流程

    def start(self, user) -> str:
        redirect = self.listener.redirect_uri(self.cfg.get("redirect_uri") or "")
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(32)
        with self._lock:
            self._pending[getattr(user, "tg_id", None)] = {"state": state, "verifier": verifier,
                                                           "redirect": redirect, "at": self.clock()}
        query = {"response_type": "code", "client_id": self.cfg["client_id"], "redirect_uri": redirect,
                 "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
                 "resource": self.resource}
        if self.cfg.get("scope"):
            query["scope"] = self.cfg["scope"]
        base = self.cfg["authorize_url"]
        return base + ("&" if "?" in base else "?") + urlencode(query)

    def finish(self, user, pasted: str) -> None:
        got, state, error = parse_pasted(pasted)
        with self._lock:
            pending = self._pending.get(getattr(user, "tg_id", None))
            if pending is None or self.clock() - pending["at"] > PENDING_SECONDS:
                self._pending.pop(getattr(user, "tg_id", None), None)
                raise OAuthError(f"沒有等待中的登入（或已經超過 {PENDING_SECONDS // 60} 分鐘）。"
                                 f"請先 /{self.m.group}_{self.names['login']}。")
            if error:
                self._pending.pop(getattr(user, "tg_id", None), None)
                raise OAuthError(f"對方說沒有允許（{error[:40]}）。要連的話重新 /{self.m.group}_{self.names['login']}。")
            if not state or not secrets.compare_digest(state, pending["state"]):
                raise OAuthError("這個網址不是剛剛那次登入的（state 對不上）。請貼最新一次登入之後瀏覽器網址列的整串。")
            if not got or any(c.isspace() for c in got) or len(got) > 4096:
                raise OAuthError("看不到授權碼。請貼瀏覽器網址列那一整串（裡面有 code=…）。")
            self._pending.pop(getattr(user, "tg_id", None), None)      # 只能用一次
        body = self._post_token({"grant_type": "authorization_code", "code": got,
                                 "redirect_uri": pending["redirect"], "client_id": self.cfg["client_id"],
                                 "code_verifier": pending["verifier"], "resource": self.resource})
        self._save(user, body)

    def _post_token(self, data: dict) -> dict:
        try:
            r = _http().post(self.cfg["token_url"], data=data, timeout=TIMEOUT, allow_redirects=False,
                             headers={"Accept": "application/json"})
        except requests.RequestException as e:
            raise OAuthError(f"連不到授權伺服器（{type(e).__name__}），等一下再試。")
        try:
            body = r.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if r.status_code != 200:
            err = str(body.get("error") or r.status_code)[:60]
            if err == "invalid_grant":
                raise OAuthError(f"授權失效了（被收回或過期）。請重新 /{self.m.group}_{self.names['login']}。")
            raise OAuthError(f"授權伺服器拒絕了（{err}）。")
        if not body.get("access_token") or str(body.get("token_type") or "bearer").lower() != "bearer":
            raise OAuthError("授權伺服器的回應看不懂（沒有 Bearer access_token）。")
        return body

    # 指令（只給人、只收私訊、不給 AI）

    def install_commands(self, group, taken: List[str]) -> None:
        from isdtelekit.core.registry import WRITE, Field

        from synox.packs import kit
        for key in list(self.names):
            name = key
            while name in taken:
                name = "auth_" + name
            self.names[key] = name
            taken.append(name)
        prefix = f"/{self.m.group}_"

        def login(api, chat_id, user, values):
            try:
                url = self.start(user)
                steps = self.listener.instructions(prefix + self.names["code"])
            except OAuthError as e:
                api.send_message(chat_id, f"❌ {e}")
                return
            api.send_message(chat_id, "\n".join([f"🔑 登入 {self.m.title}：", "1. 打開這個連結，登入、按「允許」：", url]
                                                + steps), link_preview=False)

        def code(api, chat_id, user, values):
            try:
                self.finish(user, values["pasted"])
            except OAuthError as e:
                api.send_message(chat_id, f"❌ {e}")
                return
            api.send_message(chat_id, f"✅ 登入 {self.m.title} 了（授權存在加密的保管箱）。建議把剛剛貼網址的那則訊息刪掉。")

        def logout(api, chat_id, user, values):
            try:
                self.forget(user)
            except OAuthError as e:
                api.send_message(chat_id, f"❌ {e}")
                return
            api.send_message(chat_id, f"🔌 {self.m.title} 的授權拿掉了（要徹底停用，也到對方的網站撤銷授權）。")

        kit.command(group, self.names["login"], login, "登入（OAuth，私訊）", effect=WRITE, ai=False,
                    private_only=True)
        kit.command(group, self.names["code"], code, "貼回登入後的網址（私訊）", effect=WRITE, ai=False,
                    private_only=True, fields=[Field("pasted", "瀏覽器網址列的整串", required=True)])
        kit.command(group, self.names["logout"], logout, "拿掉登入的授權", effect=WRITE, ai=False)


def flow_for(app, pack) -> Optional[Flow]:
    if (pack.manifest.auth_info or {}).get("type") != "oauth":
        return None
    return Flow(pack)


__all__ = ["DEFAULT_REDIRECT", "FIELDS", "Flow", "LISTENERS", "Listener", "LoopbackListener", "OAuthError",
           "PasteListener", "flow_for", "parse_pasted", "pkce_pair"]
