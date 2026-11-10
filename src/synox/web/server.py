"""
Web UI 的 HTTP 那一層（標準函式庫 ThreadingHTTPServer，只綁 127.0.0.1）。

設計：所有判斷都在 WebUI.route(method, path, headers, body, session) -> (status, headers, body)；
BaseHTTPRequestHandler 只是薄殼（讀 body、呼叫 handle、寫回去）。測試直接呼叫 route／handle，不開埠。

    GET  /                          app.html（每次回應一個 nonce 的 CSP；沒有 inline 事件、沒有外部資源）
    GET  /login?t=<token>           一次性登入連結 → 確認頁「你將以 <名字> 登入」（不用掉連結；防 login CSRF）
    POST /login                     確認頁的按鈕（f＝一次性表單 token＋synox_login cookie、Origin 要是自己）
                                    → 用掉連結 → cookie session → 303 到 /#chat
    GET  /packs/<name>/panel        pack 的 web.panel（工具頁用 <iframe sandbox> 掛）
    GET  /api/pack-staged/<token>   `python -m synox install` 暫存好的 pack 的檢查報告（擁有者；網頁 ?pack=<token>#settings）
    GET  /api/pack-secrets/<name>   工具頁「連接」：auth.fields 的狀態（有填、最後 4 碼；secret 的值永遠不回）
    POST /api/pack-secrets/<name>   {"values": {欄位: 值}, "clear": [...]}：存進保管箱（空字串＝沿用原值）
                                    個人版只有擁有者、伺服器版每人設自己的
    /api/...                        JSON；都要登入；改東西的（非 GET）都要 X-SYNOX-CSRF 等於 session 的 csrf，
                                    有 Origin 的話要跟 Host 一樣

每個 API 都用 session 的那個人（app.users）算權限：工具頁問 registry.visible、送出的指令經 dispatcher（authorize），
設定頁的 AI、pack、備份只有擁有者；帳號頁是伺服器版的擁有者／管理員。
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from isdtelekit.core.channel import CallbackInfo, Inbound

from synox.web.channel import WEB, WebChannel
from synox.web.chats import TOOLS_CHAT, ChatStore
from synox.web.tokens import LoginTokens, Session, Sessions, digest

HOST = "127.0.0.1"                    # 永遠只綁這個；要對外由營運者自己架反向代理＋TLS（docs/security.md）
COOKIE = "synox_session"
LOGIN_COOKIE = "synox_login"          # 登入確認頁發的、綁這個瀏覽器（POST /login 要帶）
LOGIN_FORM_TTL = 600.0
LOGIN_FORMS_MAX = 200
LOGIN_BAD = "這個連結用過了、過期了（7 天），或打錯了。在 Telegram 再打一次 /web 拿新的。"
CSRF_HEADER = "x-synox-csrf"
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 256 * 1024
MAX_TEXT = 4000
CHAT_RE = re.compile(r"^(c\d{1,6}|tools)$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

Resp = Tuple[int, List[Tuple[str, str]], bytes]

BASE_HEADERS = [("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
                ("Cache-Control", "no-store")]


def _json(status: int, data, extra: Optional[List[Tuple[str, str]]] = None) -> Resp:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return status, BASE_HEADERS + [("Content-Type", "application/json; charset=utf-8"),
                                   ("X-Frame-Options", "DENY")] + (extra or []), body


def _err(status: int, message: str) -> Resp:
    return _json(status, {"error": message})


def _page(status: int, title: str, text: str, extra: Optional[List[Tuple[str, str]]] = None) -> Resp:
    """伺服器自己產生的小頁（登入失敗等）：內容一律 escape。"""
    html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{escape(title)}</title></head><body style=\"font-family:system-ui,sans-serif;padding:24px\">"
            f"<h1>{escape(title)}</h1><p>{escape(text)}</p><p><a href=\"/\">回 SYNOX</a></p></body></html>")
    return status, BASE_HEADERS + [("Content-Type", "text/html; charset=utf-8"), ("X-Frame-Options", "DENY"),
                                   ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; "
                                                               "frame-ancestors 'none'")] + (extra or []), \
        html.encode("utf-8")


def _cookie(headers: Dict[str, str], name: str) -> Optional[str]:
    for part in (headers.get("cookie") or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


def login_link(config, token: str, port: Optional[int] = None) -> str:
    web = getattr(config, "web", {}) or {}
    base = (web.get("public_url") or "").rstrip("/") or f"http://{HOST}:{port or web.get('port', 8830)}"
    return f"{base}/login?t={token}"


class WebUI:

    def __init__(self, app, config, vault=None, *, pack_dirs=None, config_path: Optional[str] = None,
                 clock=time.time):
        self.app = app
        self.config = config
        self.vault = vault
        self.pack_dirs = tuple(pack_dirs) if pack_dirs is not None else tuple(app.extras.get("synox_pack_dirs", ()))
        self.config_path = config_path or os.path.join(getattr(config, "root", "."), "config.json")
        web = getattr(config, "web", {}) or {}
        self.enabled = bool(web.get("enabled", True))
        self.port = int(web.get("port", 8830))
        self.disabled = False                 # /web_off 之後：到重開之前都不收
        self.error = ""                       # 開不起來的原因（埠被占用…）
        data = config.data_dir
        self.tokens = LoginTokens(os.path.join(data, "web_tokens.json"), clock=clock)
        self.sessions = Sessions(os.path.join(data, "web_sessions.json"), clock=clock)
        self.chats = ChatStore(os.path.join(data, "web_chats"), vault, clock=clock)
        self._clock = clock
        self._login_forms: Dict[str, tuple] = {}     # 表單 token 的雜湊 → (登入 token 雜湊, 瀏覽器 cookie 雜湊, 到期)
        self._login_lock = threading.Lock()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ── 登入連結 ─────────────────────────────────────────────────────

    def login_link(self, tg_id: int) -> str:
        return login_link(self.config, self.tokens.issue(tg_id), self.port)

    @property
    def running(self) -> bool:
        return self._server is not None

    # ── 開／關 ───────────────────────────────────────────────────────

    def start(self) -> bool:
        """開始收網頁請求（App.run 開始時）。埠開不起來只記錯誤、回 False——bot 其他部分照常跑。"""
        if not self.enabled or self.disabled or self._server is not None:
            return False
        try:
            server = ThreadingHTTPServer((HOST, self.port), _Handler)
        except OSError as e:
            self.error = (f"網頁介面開不起來：127.0.0.1:{self.port} 不能用（{e}）。"
                          f"改 config.json 的 web.port 換一個埠，或設 web.enabled=false 不開；bot 其他功能照常。")
            logging.error("[WEB] %s", self.error)
            return False
        server.daemon_threads = True
        server.ui = self
        self.port = server.server_address[1]
        self._server = server
        self.error = ""
        self._thread = threading.Thread(target=server.serve_forever, daemon=True, name="WebUI")
        self._thread.start()
        logging.info("[WEB] http://%s:%s/ （/web 拿登入連結）", HOST, self.port)
        return True

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            threading.Thread(target=lambda: (server.shutdown(), server.server_close()), daemon=True,
                             name="WebUI-stop").start()

    def turn_off(self) -> None:
        """/web_off：關掉、把所有網頁 session 登出，到重開 bot 之前不再開。"""
        self.disabled = True
        self.sessions.drop_all()
        self.stop()

    # ── 入口 ─────────────────────────────────────────────────────────

    def session_from(self, headers: Dict[str, str]) -> Optional[Session]:
        return self.sessions.get(_cookie(headers, COOKIE))

    def handle(self, method: str, target: str, headers: Dict[str, str], body: bytes = b"") -> Resp:
        headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        return self.route(method, target, headers, body, self.session_from(headers))

    def route(self, method: str, target: str, headers: Dict[str, str], body: bytes,
              session: Optional[Session]) -> Resp:
        headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        if self.disabled:
            return _page(503, "網頁介面關掉了", "擁有者用 /web_off 關掉了，重開 SYNOX 才會再開。")
        method = method.upper()
        parts = urlsplit(target)
        path, query = parts.path, parse_qs(parts.query)
        try:
            if path == "/" and method == "GET":
                return self.app_page()
            if path == "/login" and method == "GET":
                return self.login_page((query.get("t") or [""])[0], headers, session)
            if path == "/login" and method == "POST":
                return self.login_post(headers, body)
            m = re.match(r"^/packs/([a-z][a-z0-9_-]{0,31})/panel$", path)
            if m and method == "GET":
                if session is None:
                    return _page(401, "請先登入", "在 Telegram 打 /web 拿登入連結。")
                return self.panel(self._user(session), m.group(1))
            if path.startswith("/api/"):
                if session is None:
                    return _err(401, "請先登入：在 Telegram 打 /web 拿登入連結。")
                if method != "GET":
                    problem = self._csrf_problem(headers, session)
                    if problem:
                        return _err(403, problem)
                return self.api(method, path, query, headers, body, session)
            return _page(404, "找不到", "沒有這一頁。")
        except Exception as e:
            logging.exception("[WEB] %s %s failed", method, path)
            return _err(500, f"出錯了：{type(e).__name__}")

    def _csrf_problem(self, headers: Dict[str, str], session: Session) -> str:
        origin = headers.get("origin")
        if origin and origin != "null":
            host = headers.get("host", "")
            if urlsplit(origin).netloc != host:
                return "來源不對（Origin 跟 Host 不一樣）。"
        if not session.csrf_ok(headers.get(CSRF_HEADER)):
            return "缺少或不對的 CSRF token（重新整理頁面再試）。"
        return ""

    def _user(self, session: Session):
        return self.app.users.get_or_create(session.tg_id)

    def is_owner(self, user) -> bool:
        return self.app.registry.is_owner(user)

    def is_admin(self, user) -> bool:
        return self.is_owner(user) or user.role >= self.app.users.top_role

    @property
    def server_mode(self) -> bool:
        return getattr(self.config, "mode", "personal") == "server"

    # ── 頁面 ─────────────────────────────────────────────────────────

    def app_page(self) -> Resp:
        nonce = secrets.token_urlsafe(16)
        with open(os.path.join(STATIC, "app.html"), "r", encoding="utf-8") as f:
            html = f.read().replace("{{NONCE}}", nonce)
        csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
               "img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; "
               "base-uri 'none'; form-action 'self'")
        return 200, BASE_HEADERS + [("Content-Type", "text/html; charset=utf-8"), ("X-Frame-Options", "DENY"),
                                    ("Content-Security-Policy", csp)], html.encode("utf-8")

    # 登入（兩步，防 login CSRF）：GET /login?t= 只顯示「你將以 <名字> 登入」，不用掉連結；
    # 按頁上的按鈕 POST /login（一次性表單 token f＋這個瀏覽器的 LOGIN_COOKIE、Origin 要是自己）才兌換。
    # 別人塞給你的連結（他的帳號）：你會先看到要登入的是誰；跨站自動送出的表單拿不到 f、也帶不了 cookie。

    def _who(self, tg_id: int) -> str:
        user = self.app.users.get(tg_id)
        name = (getattr(user, "username", "") or "").strip()
        return f"{name}（id {tg_id}）" if name else f"id {tg_id}"

    def _login_forms_prune(self) -> None:
        now = self._clock()
        self._login_forms = {k: v for k, v in self._login_forms.items() if v[2] > now}

    def login_page(self, token: str, headers: Dict[str, str], session: Optional[Session]) -> Resp:
        tg_id = self.tokens.peek(token)
        if tg_id is None:
            return _page(403, "登入連結不能用", LOGIN_BAD)
        form, binder = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        with self._login_lock:
            self._login_forms_prune()
            if len(self._login_forms) >= LOGIN_FORMS_MAX:          # 有人狂刷確認頁：丟最舊的
                self._login_forms.pop(next(iter(self._login_forms)))
            self._login_forms[digest(form)] = (digest(token), digest(binder), self._clock() + LOGIN_FORM_TTL)
        now_text = ""
        if session is not None and session.tg_id != tg_id:
            now_text = f"<p><b>注意：</b>這個瀏覽器現在登入的是 {escape(self._who(session.tg_id))}，按下去會換成上面這個帳號。</p>"
        html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>登入 SYNOX</title></head>"
                "<body style=\"font-family:system-ui,sans-serif;padding:24px;max-width:560px\">"
                "<h1>登入 SYNOX</h1>"
                f"<p style=\"font-size:1.2em\">你將以 <b>{escape(self._who(tg_id))}</b> 登入。</p>{now_text}"
                "<p>這不是你的帳號（例如別人傳給你的連結）就<b>不要按</b>，直接關掉這一頁。</p>"
                "<form method=\"post\" action=\"/login\">"
                f"<input type=\"hidden\" name=\"f\" value=\"{escape(form)}\">"
                "<button type=\"submit\" style=\"font-size:1.1em;padding:8px 20px\">登入</button></form>"
                "</body></html>")
        csp = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        cookie = (f"{LOGIN_COOKIE}={binder}; HttpOnly; SameSite=Strict; Path=/login; Max-Age={int(LOGIN_FORM_TTL)}"
                  + self._secure())
        return 200, BASE_HEADERS + [("Content-Type", "text/html; charset=utf-8"), ("X-Frame-Options", "DENY"),
                                    ("Content-Security-Policy", csp), ("Set-Cookie", cookie)], html.encode("utf-8")

    def login_post(self, headers: Dict[str, str], body: bytes) -> Resp:
        origin = headers.get("origin")
        if origin and (origin == "null" or urlsplit(origin).netloc != headers.get("host", "")):
            return _page(403, "登入沒有完成", "來源不對（不是從 SYNOX 自己的登入頁送出的）。")
        if headers.get("sec-fetch-site") not in (None, "", "same-origin", "none"):
            return _page(403, "登入沒有完成", "來源不對（跨站送出的登入）。")
        try:
            form = (parse_qs(body.decode("utf-8")).get("f") or [""])[0]
        except UnicodeDecodeError:
            form = ""
        binder = _cookie(headers, LOGIN_COOKIE)
        with self._login_lock:
            self._login_forms_prune()
            found = self._login_forms.get(digest(form)) if form else None
            if found is None or not binder or not hmac.compare_digest(found[1], digest(binder)):
                found = None
            else:
                self._login_forms.pop(digest(form), None)            # 對得上才用掉（一次性）
        if found is None:
            return _page(403, "登入沒有完成", "這個登入頁過期了，或不是在這個瀏覽器打開的。回去再點一次登入連結。")
        tg_id = self.tokens.redeem_digest(found[0])
        if tg_id is None:
            return _page(403, "登入連結不能用", LOGIN_BAD)
        self.sessions.drop(_cookie(headers, COOKIE))
        sid, _session = self.sessions.create(tg_id)
        self.app.users.get_or_create(tg_id)
        cookie = f"{COOKIE}={sid}; HttpOnly; SameSite=Lax; Path=/; Max-Age={int(self.sessions.ttl)}" + self._secure()
        gone = f"{LOGIN_COOKIE}=; HttpOnly; SameSite=Strict; Path=/login; Max-Age=0" + self._secure()
        return 303, BASE_HEADERS + [("Location", "/#chat"), ("Set-Cookie", gone), ("Set-Cookie", cookie),
                                    ("Content-Type", "text/plain; charset=utf-8")], b"OK"

    def _secure(self) -> str:
        """對外網址是 https（反向代理＋TLS）：cookie 加 Secure，瀏覽器不會在明文 http 上送出 session。
        只開本機 http://127.0.0.1 時不加（不然瀏覽器收不下 cookie）。"""
        public = str((getattr(self.config, "web", {}) or {}).get("public_url") or "").strip().lower()
        return "; Secure" if public.startswith("https://") else ""

    def _pack(self, name: str):
        return next((p for p in self.app.extras.get("synox_packs", []) if p.name == name), None)

    def _pack_visible(self, user, pack) -> bool:
        group = self.app.registry.node(pack.manifest.group)
        return group is not None and self.app.registry.visible(user, group)

    def panel(self, user, name: str) -> Resp:
        pack = self._pack(name)
        if pack is None or not pack.manifest.web.get("panel") or not self._pack_visible(user, pack):
            return _page(404, "找不到", "沒有這個面板。")
        with open(pack.manifest.panel_path, "rb") as f:
            html = f.read()
        csp = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
               "connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
        return 200, BASE_HEADERS + [("Content-Type", "text/html; charset=utf-8"), ("X-Frame-Options", "SAMEORIGIN"),
                                    ("Content-Security-Policy", csp)], html

    # ── API ──────────────────────────────────────────────────────────

    def api(self, method: str, path: str, query, headers, body: bytes, session: Session) -> Resp:
        user = self._user(session)
        if method == "GET":
            if path == "/api/me":
                return _json(200, self.me(user, session))
            if path == "/api/chats":
                return _json(200, {"chats": self.chats.list_chats(user.tg_id)})
            m = re.match(r"^/api/chat/([a-z0-9]+)/events$", path)
            if m:
                return self.events(user, m.group(1), (query.get("since") or ["0"])[0])
            if path == "/api/tools":
                return _json(200, self.tools(user))
            m = re.match(r"^/api/pack-staged/([A-Za-z0-9_-]{8,64})$", path)
            if m:
                return self.pack_staged(user, m.group(1))
            m = re.match(r"^/api/packs/([a-z][a-z0-9_-]{0,31})/([a-z0-9][a-z0-9_-]{0,31})$", path)
            if m:
                return self.pack_api(user, m.group(1), m.group(2))
            m = re.match(r"^/api/pack-secrets/([a-z][a-z0-9_-]{0,31})$", path)
            if m:
                return self.pack_secrets_get(user, m.group(1))
            if path == "/api/settings":
                return _json(200, self.settings(user))
            if path == "/api/accounts":
                return self.accounts(user)
            return _err(404, "沒有這個 API。")
        if method != "POST":
            return _err(405, "只收 GET、POST。")
        if path == "/api/packs/upload":
            return self.pack_upload(user, body)
        try:
            data = json.loads(body.decode("utf-8") or "{}") if body else {}
        except (ValueError, UnicodeDecodeError):
            return _err(400, "送來的不是 JSON。")
        if not isinstance(data, dict):
            return _err(400, "送來的 JSON 要是物件。")
        if path == "/api/logout":
            self.sessions.drop(_cookie(headers, COOKIE))
            return _json(200, {"ok": True}, [("Set-Cookie", f"{COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
                                                            + self._secure())])
        if path == "/api/chats":
            chat = self.chats.new_chat(user.tg_id)
            return _json(200, {"id": chat["id"], "title": chat["title"]})
        m = re.match(r"^/api/chat/([a-z0-9]+)/(send|press)$", path)
        if m:
            return self.send(user, m.group(1), data) if m.group(2) == "send" else self.press(user, m.group(1), data)
        if path == "/api/settings/llm":
            return self.save_llm(user, data)
        if path == "/api/settings/llm/test":
            return self.test_llm(user, data)
        m = re.match(r"^/api/pack-secrets/([a-z][a-z0-9_-]{0,31})$", path)
        if m:
            return self.pack_secrets_save(user, m.group(1), data)
        if path == "/api/packs/install":
            return self.pack_install(user, data)
        if path == "/api/packs/remove":
            return self.pack_remove(user, data)
        if path == "/api/packs/reload":
            return self.pack_reload(user)
        if path == "/api/accounts/role":
            return self.set_role(user, data)
        if path == "/api/backup":
            return self.backup(user)
        return _err(404, "沒有這個 API。")

    # ── 我 ───────────────────────────────────────────────────────────

    def role_name(self, role) -> str:
        try:
            return self.app.users.roles(int(role)).name.lower()
        except ValueError:
            return str(role)

    def me(self, user, session: Session) -> dict:
        ai = self.app.registry.node("agent.ai")
        can_ai = ai is not None and self.app.registry.authorize(user, ai, "typed", user.tg_id).allowed and \
            self.app.extras.get("synox_agent") is not None
        return {"id": user.tg_id, "username": user.username, "role": self.role_name(user.role),
                "owner": self.is_owner(user), "admin": self.is_admin(user), "mode": self.config.mode,
                "csrf": session.csrf, "ai": bool(can_ai), "accounts": self.server_mode and self.is_admin(user)}

    # ── 對話 ─────────────────────────────────────────────────────────

    def _chat(self, user, chat_id: str):
        if not CHAT_RE.match(chat_id or ""):
            return None
        if chat_id == TOOLS_CHAT:
            return self.chats.ensure(user.tg_id, TOOLS_CHAT, "🧰 工具頁")
        return self.chats.get(user.tg_id, chat_id)

    def events(self, user, chat_id: str, since: str) -> Resp:
        if self._chat(user, chat_id) is None:
            return _err(404, "沒有這段對話。")
        try:
            since_n = max(0, int(since))
        except ValueError:
            since_n = 0
        messages, rev = self.chats.events(user.tg_id, chat_id, since_n)
        return _json(200, {"messages": messages, "rev": rev})

    def channel(self, user, chat_id: str) -> WebChannel:
        return WebChannel(self.chats, user.tg_id, chat_id, home=self.app.home)

    def send(self, user, chat_id: str, data: dict) -> Resp:
        if self._chat(user, chat_id) is None:
            return _err(404, "沒有這段對話。")
        text = str(data.get("text") or "").strip()
        if not text:
            return _err(400, "沒有內容。")
        if len(text) > MAX_TEXT:
            return _err(400, f"太長了（最多 {MAX_TEXT} 字）。")
        self.chats.append(user.tg_id, chat_id, "me", text)
        inbound = Inbound(WEB, user.tg_id, user.tg_id, text, username=user.username or "web", sent_at=time.time())
        route = self.app.dispatcher.handle(self.channel(user, chat_id), inbound)
        return _json(200, {"ok": True, "route": getattr(route, "kind", ""), "rev": self.chats.rev(user.tg_id)})

    def press(self, user, chat_id: str, data: dict) -> Resp:
        if self._chat(user, chat_id) is None:
            return _err(404, "沒有這段對話。")
        try:
            message_id = int(data.get("message_id"))
        except (TypeError, ValueError):
            return _err(400, "message_id 要是數字。")
        callback = str(data.get("data") or "")
        msg = self.chats.has_button(user.tg_id, chat_id, message_id, callback)
        if msg is None:
            return _err(409, "這顆按鈕已經不在了（可能按過或過期了）。")
        label = next((b.get("text", "") for row in msg.get("buttons") or [] for b in row
                      if b.get("data") == callback), "")
        self.chats.append(user.tg_id, chat_id, "note", f"你按了「{label}」")
        cb = CallbackInfo(chat_id=user.tg_id, message_id=message_id, cq_id="web", clicker_id=user.tg_id,
                          data=callback, text=msg.get("text", ""), message_date=float(msg.get("at") or time.time()))
        route = self.app.dispatcher.handle(self.channel(user, chat_id),
                                           Inbound(WEB, user.tg_id, user.tg_id, button=cb,
                                                   username=user.username or "web"))
        return _json(200, {"ok": True, "route": getattr(route, "kind", ""), "rev": self.chats.rev(user.tg_id)})

    # ── 工具頁 ───────────────────────────────────────────────────────

    def _leaf_info(self, node) -> dict:
        return {"command": node.command, "usage": node.usage, "summary": node.summary,
                "effect": node.effect, "path": node.path}

    def tools(self, user) -> dict:
        registry = self.app.registry
        packs_out, pack_groups = [], set()
        for pack in self.app.extras.get("synox_packs", []):
            group = registry.node(pack.manifest.group)
            pack_groups.add(pack.manifest.group)
            if group is None or not registry.visible(user, group):
                continue
            leaves = [n for n in group.walk() if not n.is_group and registry.visible(user, n)]
            connector = getattr(pack.manifest, "registered_only", pack.manifest.kind in ("connector", "mcp"))
            row = {
                "name": pack.name, "title": pack.manifest.title, "summary": pack.manifest.summary,
                "kind": pack.manifest.kind, "version": pack.manifest.version,
                "status": "要先設定" if connector else "已連接",
                "panel": f"/packs/{pack.name}/panel" if pack.manifest.web.get("panel") else None,
                "commands": [self._leaf_info(n) for n in leaves]}
            fields = getattr(pack, "secret_fields", None) or []
            if fields:                          # auth.fields 由 SYNOX 收：照這個人存了沒算狀態
                store = self._secret_store()
                missing = store.missing(pack.name, fields, user) if store is not None else [f["label"] for f in fields]
                row["connect"] = self._can_connect(user)
                row["missing"] = missing
                row["status"] = "要先設定" if missing else "已連接"
            packs_out.append(row)
        groups_out = []
        basics = [n for n in registry.root.children.values() if not n.is_group and registry.visible(user, n)]
        if basics:
            groups_out.append({"title": "🧭 基本", "summary": "開始、說明、結束問答",
                               "commands": [self._leaf_info(n) for n in basics]})
        for node in registry.root.children.values():
            if not node.is_group or node.name in pack_groups or not registry.visible(user, node):
                continue
            leaves = [n for n in node.walk() if not n.is_group and registry.visible(user, n)
                      and n.path != "agent.ai_approve"]
            if leaves:
                groups_out.append({"title": node.title, "summary": node.summary,
                                   "commands": [self._leaf_info(n) for n in leaves]})
        return {"packs": packs_out, "groups": groups_out}

    def pack_api(self, user, name: str, route: str) -> Resp:
        pack = self._pack(name)
        if pack is None or not self._pack_visible(user, pack):
            return _err(404, "沒有這個 pack。")
        fn = pack.web_routes.get(route)
        if route not in pack.manifest.web.get("api", []) or fn is None:
            return _err(404, f"{name} 沒有宣告 GET /{route}。")
        return _json(200, fn(user))

    # ── pack 的 secret（工具頁的「連接」） ────────────────────────────
    # 個人版：只有擁有者；伺服器版：每個人設自己的（看得到這個 pack 的人）。值永遠不回傳（只回有填、最後 4 碼）。

    def _secret_store(self):
        from synox.packs import secrets as pack_secrets
        return pack_secrets.of(self.app)

    def _can_connect(self, user) -> bool:
        return self.server_mode or self.is_owner(user)

    def _secret_pack(self, user, name: str):
        """(pack, 錯誤回應)。"""
        pack = self._pack(name)
        if pack is None or not self._pack_visible(user, pack):
            return None, _err(404, "沒有這個 pack。")
        if not getattr(pack, "secret_fields", None):
            return None, _err(404, f"{name} 不用在這裡連接（沒有宣告 auth.fields，或 pack 自己有設定指令）。")
        if not self._can_connect(user):
            return None, _err(403, "只有擁有者能設定這台電腦的 pack 連接。")
        store = self._secret_store()
        if store is None or not store.available:
            return None, _err(400, "保管箱沒有打開，secret 沒地方放（python -m synox doctor 看原因）。")
        return pack, None

    def _secret_view(self, user, pack) -> dict:
        store = self._secret_store()
        fields = store.status(pack.name, pack.secret_fields, user)
        missing = store.missing(pack.name, pack.secret_fields, user)
        return {"name": pack.name, "title": pack.manifest.title, "type": pack.manifest.auth_info.get("type", ""),
                "fields": fields, "missing": missing, "connected": not missing,
                "status": "要先設定" if missing else "已連接"}

    def pack_secrets_get(self, user, name: str) -> Resp:
        pack, denied = self._secret_pack(user, name)
        if denied:
            return denied
        return _json(200, self._secret_view(user, pack))

    def pack_secrets_save(self, user, name: str, data: dict) -> Resp:
        """{"values": {欄位: 值（空字串＝沿用原值）}, "clear": [欄位…]}。"""
        from synox.packs.secrets import SecretError, short_warning
        pack, denied = self._secret_pack(user, name)
        if denied:
            return denied
        values = data.get("values") or {}
        clear = data.get("clear") or []
        if not isinstance(values, dict) or not isinstance(clear, list) or \
                not all(isinstance(c, str) for c in clear):
            return _err(400, "values 要是 {欄位: 值}，clear 要是欄位名的清單。")
        try:
            short = self._secret_store().update(pack.name, pack.secret_fields, values, user, clear=clear)
        except SecretError as e:
            return _err(400, str(e))
        logging.info("[WEB] %s saved secrets for pack %s (fields: %s)", user.tg_id, pack.name,
                     ",".join(sorted(k for k, v in values.items() if v)) or "-")
        out = self._secret_view(user, pack)
        out["ok"] = True
        out["message"] = "✅ 已連接（存在保管箱，密文）。" if out["connected"] else \
            "存好了，還缺：" + "、".join(out["missing"])
        if short:                                    # 存了，但太短的 secret 第 4 關保護不全：照實說
            out["warning"] = short_warning(short)
            out["message"] += "\n" + out["warning"]
        return _json(200, out)

    # ── 設定頁 ───────────────────────────────────────────────────────

    def settings(self, user) -> dict:
        out = {"owner": self.is_owner(user), "mode": self.config.mode, "accounts": self.server_mode and
               self.is_admin(user)}
        budget = self.app.extras.get("synox_budget")
        if budget is not None and not budget.exempt(user):
            out["ai_budget"] = {"used": round(budget.month_usd(user.tg_id), 4), "limit": budget.limit(user.tg_id)}
        if not self.is_owner(user):
            return out
        from synox.wizard import logic
        llm = dict(self.config.llm or {})
        out["llm"] = {"kind": llm.get("kind", "none"), "model": llm.get("model", ""),
                      "base_url": llm.get("base_url", ""), "has_key": bool(llm.get("api_key"))}
        out["llm_choices"] = [{"choice": "claude_code", "label": logic.CLAUDE_TITLE}] + \
            [{"choice": "keys", "provider": code, "label": v[0], "model": v[2], "needs_url": v[3]}
             for code, v in logic.KEY_PROVIDERS.items()] + [{"choice": "none", "label": "先不用 AI"}]
        report = self.app.extras.get("synox_pack_report")
        user_dir = os.path.realpath(self.pack_dirs[0]) if self.pack_dirs else ""
        out["packs"] = [{"name": i.name, "status": i.status, "detail": i.detail, "kind": i.kind,
                         "version": i.version, "lock": getattr(i, "lock", ""),
                         "removable": bool(user_dir) and os.path.realpath(os.path.dirname(i.folder)) == user_dir}
                        for i in (report.items if report else [])]
        out["vault"] = self.vault is not None
        return out

    def _owner_only(self, user) -> Optional[Resp]:
        return None if self.is_owner(user) else _err(403, "只有擁有者能做這件事。")

    def _llm_from(self, data: dict) -> Tuple[dict, str]:
        from synox.wizard import logic
        choice = str(data.get("choice") or "")
        provider = str(data.get("provider") or "openai")
        api_key = str(data.get("api_key") or "")
        current = dict(self.config.llm or {})
        keep = False
        if choice == "keys" and not api_key.strip() and provider in logic.KEY_PROVIDERS and \
                current.get("kind") == logic.KEY_PROVIDERS[provider][1] and current.get("api_key"):
            api_key, keep = "（沿用）", True               # 留空＝沿用原本的金鑰
        llm, problem = logic.llm_settings(choice, base_url=str(data.get("base_url") or ""), api_key=api_key,
                                          model=str(data.get("model") or ""), provider=provider)
        if problem:
            return {}, problem
        if keep:
            llm["api_key"] = current["api_key"]
        return llm, ""

    def save_llm(self, user, data: dict) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.llm.factory import VAULT_PREFIX
        from synox.wizard import logic
        llm, problem = self._llm_from(data)
        if problem:
            return _err(400, problem)
        key = llm.get("api_key", "")
        if key and not str(key).startswith((VAULT_PREFIX, "env:")):
            if self.vault is None:
                return _err(400, "保管箱沒有打開，金鑰沒地方放。")
            self.vault.set_secret(logic.SECRET_NAME, key)
            llm["api_key"] = VAULT_PREFIX + logic.SECRET_NAME
        cfg = logic.read_existing(self.config_path)
        old = cfg.get("llm") or {}
        cfg["llm"] = {"max_steps": old.get("max_steps", 6), "max_tokens": old.get("max_tokens", 1024), **llm}
        logic.write_config(self.config_path, cfg)
        self.config.llm = {**self.config.llm, **cfg["llm"]}
        return _json(200, {"ok": True, "message": "存好了。重開 SYNOX 之後就換成新的 AI 來源。", "kind": llm["kind"]})

    def test_llm(self, user, data: dict) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.llm.factory import resolve_secret
        from synox.wizard import logic
        llm, problem = self._llm_from(data)
        if problem:
            return _err(400, problem)
        if str(llm.get("api_key", "")).startswith(("vault:", "env:")):
            llm["api_key"] = resolve_secret(llm["api_key"], self.vault)
        result = logic.probe_llm(llm)
        return _json(200, {"ok": result is None, "message": "✅ 接得通" if result is None else f"❌ {result}"})

    def pack_upload(self, user, body: bytes) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.packs.admin import GateRefused, PackAdminError, stage
        try:
            _token, summary = stage(body, self.config.data_dir)        # 安全管線第 1、2 關
        except GateRefused as e:
            return _json(400, {"error": str(e), "refused": e.summary})
        except PackAdminError as e:
            return _err(400, str(e))
        return _json(200, self._with_upgrade(summary))

    def _with_upgrade(self, summary: dict) -> dict:
        """同名的已經裝了：摘要多一段 upgrade（「改了什麼」、版本檢查；見 packs/upgrade.py）。"""
        from synox.packs.admin import PackAdminError
        from synox.packs.upgrade import staged_upgrade
        if not self.pack_dirs or not summary.get("token"):
            return summary
        try:
            upg = staged_upgrade(summary["token"], self.config.data_dir, self.pack_dirs[0])
        except PackAdminError:
            upg = None
        return {**summary, "upgrade": upg} if upg else summary

    def pack_staged(self, user, token: str) -> Resp:
        """`python -m synox install` 已經暫存好、跑過 1、2 關的那一份：網頁拿報告給人看、按確認。"""
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.packs.admin import PackAdminError, staged_summary
        try:
            return _json(200, self._with_upgrade(staged_summary(token, self.config.data_dir)))
        except PackAdminError as e:
            return _err(404, str(e))

    def pack_install(self, user, data: dict) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.packs.admin import GateRefused, PackAdminError, install_staged
        if not self.pack_dirs:
            return _err(400, "沒有可以裝 pack 的資料夾。")
        if data.get("upgrade"):
            return self._pack_upgrade(user, data)
        try:                                                            # 再跑 1、2 關 → 第 3 關（packs.lock）
            name = install_staged(str(data.get("token") or ""), self.config.data_dir, self.pack_dirs[0],
                                  approved_by=user.tg_id, via="web", trust=data.get("trust") or None,
                                  trust_publisher=str(data.get("trust_publisher") or "") or None,
                                  runtime=str(data.get("runtime") or "") or None)       # S2：用容器／不用
        except GateRefused as e:
            return _json(400, {"error": str(e), "refused": e.summary})
        except PackAdminError as e:
            return _err(400, str(e))
        env = self._start_env_build(name)
        report = self._reload()
        status = next((i for i in report.items if i.name == name), None)
        return _json(200, {"ok": True, "name": name, "status": status.status if status else "",
                           "detail": status.detail if status else "", "env": env})

    def _start_env_build(self, name: str, what: str = "裝好了") -> str:
        """裝好（或升級好）之後建環境（runtime.python／node = auto）：在 JobRunner 上背景跑，好了重新載入、通知擁有者。
        回 ""（不用建）｜"building"｜"failed: …"（叫不起來）。失敗不影響已經裝好的 pack（升級也不退回）。"""
        from synox.packs.admin import PackAdminError, build_env

        def done(result):
            try:
                self._reload()
            except Exception:
                logging.exception("[WEB] reload after env build failed")
            text = (f"✅ pack {name} 的環境建好了，可以用了。" if result.ok
                    else f"⚠️ pack {name} {what}，但環境沒建好：{result.detail}")
            try:
                self.app.notify_owner(text)
            except Exception:
                logging.exception("[WEB] env build notice failed")

        try:
            return "building" if build_env(name, self.config.data_dir, self.pack_dirs[0], self.app.jobs, done) else ""
        except (PackAdminError, OSError) as e:
            return f"failed: {e}"

    def _pack_upgrade(self, user, data: dict) -> Resp:
        """看過「改了什麼」按了「確認升級」：舊的搬到 _removed、新的搬進來、鎖換新、
        環境要建／重建就跟全新安裝一樣在背景建（升級報告的 env.needed）、重新載入。"""
        from synox.packs.admin import GateRefused, PackAdminError
        from synox.packs.upgrade import upgrade_staged
        try:
            done = upgrade_staged(str(data.get("token") or ""), self.config.data_dir, self.pack_dirs[0],
                                  approved_by=user.tg_id, via="web", allow_downgrade=bool(data.get("allow_downgrade")),
                                  trust=data.get("trust") or None,
                                  trust_publisher=str(data.get("trust_publisher") or "") or None,
                                  runtime=str(data.get("runtime") or "") or None)
        except GateRefused as e:
            return _json(400, {"error": str(e), "refused": e.summary})
        except PackAdminError as e:
            return _err(400, str(e))
        env = self._start_env_build(done["name"], "升級好了") if (done.get("env") or {}).get("needed") else ""
        report = self._reload()
        status = next((i for i in report.items if i.name == done["name"]), None)
        return _json(200, {"ok": True, "name": done["name"], "upgraded": True, "from": done["from"], "to": done["to"],
                           "backup": os.path.relpath(done["backup"], os.path.dirname(self.pack_dirs[0])),
                           "status": status.status if status else "", "detail": status.detail if status else "",
                           "env": env})

    def pack_remove(self, user, data: dict) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.packs.admin import PackAdminError, remove
        name = str(data.get("name") or "")
        if not NAME_RE.match(name) or not self.pack_dirs:
            return _err(400, "pack 名字不對。")
        try:
            dest = remove(name, self.pack_dirs[0], data_dir=self.config.data_dir)
        except PackAdminError as e:
            return _err(400, str(e))
        self._reload()
        return _json(200, {"ok": True, "moved_to": os.path.relpath(dest, os.path.dirname(self.pack_dirs[0]))})

    def _reload(self):
        from synox.packs.admin import reload
        return reload(self.app, self.config, self.vault, self.pack_dirs)

    def pack_reload(self, user) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        report = self._reload()
        return _json(200, {"ok": report.ok, "packs": [{"name": i.name, "status": i.status, "detail": i.detail}
                                                       for i in report.items]})

    # ── 帳號（伺服器版） ─────────────────────────────────────────────

    def accounts(self, user) -> Resp:
        if not self.server_mode:
            return _err(404, "個人版沒有帳號管理。")
        if not self.is_admin(user):
            return _err(403, "只有擁有者和管理員能看帳號。")
        limiter = self.app.limiter
        budget = self.app.extras.get("synox_budget")
        rows = []
        for u in sorted(self.app.users.list_all(), key=lambda u: (-int(u.role), u.tg_id)):
            row = {"id": u.tg_id, "username": u.username, "role": self.role_name(u.role),
                   "owner": self.app.registry.is_owner(u), "pending": bool(u.pending_ts)}
            if limiter is not None:
                row["messages_today"] = limiter.used(u.tg_id, "messages")
                row["messages_limit"] = limiter.limit(int(u.role), "messages")
            if budget is not None and not self.app.registry.is_owner(u):
                row["ai_month_usd"] = round(budget.month_usd(u.tg_id), 4)
                row["ai_limit_usd"] = budget.limit(u.tg_id)
            rows.append(row)
        return _json(200, {"users": rows, "roles": [r.name.lower() for r in self.app.users.roles]})

    def set_role(self, user, data: dict) -> Resp:
        if not self.server_mode:
            return _err(404, "個人版沒有帳號管理。")
        if not self.is_admin(user):
            return _err(403, "只有擁有者和管理員能改角色。")
        try:
            target = int(data.get("id"))
        except (TypeError, ValueError):
            return _err(400, "id 要是數字。")
        role = str(data.get("role") or "").lower()
        if role not in [r.name.lower() for r in self.app.users.roles]:
            return _err(400, "不認得的角色。")
        # 走 SDK accounts pack 的同一個指令（同一套保護：擁有者不能被降級、管理員不能升別人當管理員…）
        collector = Collector(user.tg_id, self.app.home)
        inbound = Inbound(WEB, user.tg_id, user.tg_id, f"/user_role {target} {role}",
                          username=user.username or "web", sent_at=time.time())
        self.app.dispatcher.handle(collector, inbound)
        changed = self.app.users.get(target)
        return _json(200, {"ok": True, "message": "\n".join(collector.texts) or "（沒有回覆）",
                           "role": self.role_name(changed.role) if changed else ""})

    # ── 備份 ─────────────────────────────────────────────────────────

    def backup(self, user) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox import backup
        try:
            blob = backup.export_backup(self.config.data_dir, self.vault)
        except ValueError as e:
            return _err(400, str(e))
        name = backup.filename()
        return 200, BASE_HEADERS + [("Content-Type", "application/zip"),
                                    ("Content-Disposition", f"attachment; filename=\"{name}\"")], blob


class Collector:
    """只收「回給這個人」的純文字（帳號頁用）；送給別人的照常走 app.home。"""

    channel_name = WEB

    def __init__(self, tg_id: int, home=None):
        self.tg_id = tg_id
        self.home = home
        self.texts: List[str] = []

    def send_message(self, chat_id, text, reply_markup=None, **kw):
        from isdtelekit.core.richtext import plain
        if chat_id == self.tg_id:
            self.texts.append(plain(text))
            return {"ok": True, "result": {"message_id": 0}}
        if self.home is None:
            return {"ok": False}
        if reply_markup is not None:
            return self.home.send_message(chat_id, text, reply_markup=reply_markup)
        return self.home.send_message(chat_id, text)

    def __getattr__(self, name):
        return lambda *a, **kw: {"ok": True}


class _Handler(BaseHTTPRequestHandler):
    """薄殼：讀 body（有上限）→ server.ui.handle → 寫回去。"""

    server_version = "SYNOX"
    sys_version = ""

    def _go(self, method: str) -> None:
        from synox.packs.admin import MAX_UPLOAD
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        limit = MAX_UPLOAD + 1024 if self.path.startswith("/api/packs/upload") else MAX_BODY
        if length < 0 or length > limit:
            status, headers, body = _err(413, "送來的東西太大。")
        else:
            data = self.rfile.read(length) if length else b""
            status, headers, body = self.server.ui.handle(method, self.path, dict(self.headers.items()), data)
        self.send_response(status)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        self._go("GET")

    def do_POST(self):
        self._go("POST")

    def log_message(self, fmt, *args):
        logging.debug("[WEB] " + fmt, *args)
