"""
Web UI 的 HTTP 那一層（標準函式庫 ThreadingHTTPServer，只綁 127.0.0.1；唯一例外是 SYNOX 自己的容器，見 bind_host）。

設計：所有判斷都在 WebUI.route(method, path, headers, body, session) -> (status, headers, body)；
BaseHTTPRequestHandler 只是薄殼（讀 body、呼叫 handle、寫回去）。測試直接呼叫 route／handle，不開埠。

    GET  /                          app.html（每次回應一個 nonce 的 CSP；沒有 inline 事件、沒有外部資源）
    GET  /login?t=<token>           一次性登入連結 → 確認頁「你將以 <名字> 登入」（不用掉連結；防 login CSRF）
    POST /login                     確認頁的按鈕（f＝一次性表單 token＋synox_login cookie、Origin 要是自己）
                                    → 用掉連結 → cookie session → 303 到 /#chat
    GET  /packs/<name>/panel        pack 的 web.panel（工具頁用 <iframe sandbox> 掛）
    GET  /tutorials/<name>/         圖文教學 docs/tutorials/<name>/index.html（公開文件，不用登入；synox/tutorials.py）
    GET  /api/pack-staged/<token>   `python -m synox install` 暫存好的 pack 的檢查報告（擁有者；網頁 ?pack=<token>#settings）
    GET  /api/pack-secrets/<name>   工具頁「連接」：auth.fields 的狀態（有填、最後 4 碼；secret 的值永遠不回）
    POST /api/pack-secrets/<name>   {"values": {欄位: 值}, "clear": [...]}：存進保管箱（空字串＝沿用原值）
                                    個人版只有擁有者、伺服器版每人設自己的
    GET  /api/tools                 工具頁：看得到的工具（說明、指令、參數表單）＋這個人的群組排版（layout）
    POST /api/tools/layout          {"groups": [{"id", "title", "tools": [...]}]}｜{"reset": true}：存這個人自己的排版
                                    （web/toolpage.py；不寫進 pack 資料夾，擁有者與成員各自一份）
    POST /api/tools/health          {"key", "action": "recheck"|"release"}：擁有者重新檢查／解除隔離一個工具（docs/tool-health.md）
    GET  /api/usage?period=hour|day|week|month   擁有者：AI 用量與花費（依期間分組；agent/usage_report.py）
    GET  /api/settings/channels     擁有者：Telegram／Discord 的狀態（存了沒、bot 名字、要不要重開；token 永遠不回）
    /api/runtime/...                擁有者：主控面板（心跳、常駐助理、soul.md、任務狀態；合約 docs/runtime-api.md，
                                    `PUT /api/runtime/soul` 是唯一收 PUT 的）
    POST /api/settings/channels/telegram|discord   {"token"}：跟精靈一樣先驗（getMe）再存；重開 SYNOX 才生效
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
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from isdtelekit.core.channel import CallbackInfo, Inbound

from synox import tutorials
from synox.packs.manifest import stage_text
from synox.web import toolpage
from synox.web.channel import WEB, WebChannel
from synox.web.chats import MOTHER_CHAT, TOOLS_CHAT, ChatStore
from synox.web.tokens import LoginTokens, Session, Sessions, digest

HOST = "127.0.0.1"                    # 只綁這個；要對外由營運者自己架反向代理＋TLS（docs/security.md）。
#                                       唯一的例外是 SYNOX 自己的容器（bind_host，docs/docker.md「為什麼容器裡綁 0.0.0.0 是安全的」）
CONTAINER_ENV = "SYNOX_IN_CONTAINER"  # 映像檔（Dockerfile）設成 1
BIND_ENV = "SYNOX_WEB_BIND"           # 容器裡才收：0.0.0.0（讓宿主經 compose 發佈到宿主 127.0.0.1 的埠連進來）
CONTAINER_BIND_HOSTS = (HOST, "0.0.0.0")
# 「真的在容器裡」的證據（任一個存在就算）：Docker 的 /.dockerenv、podman 的 /run/.containerenv、
# SYNOX 映像檔自己放的 /etc/synox/container。光有環境變數不夠：怕有人在一般電腦上照抄容器的環境變數
CONTAINER_MARKERS = ("/.dockerenv", "/run/.containerenv", "/etc/synox/container")
COOKIE = "synox_session"
LOGIN_COOKIE = "synox_login"          # 登入確認頁發的、綁這個瀏覽器（POST /login 要帶）
LOGIN_FORM_TTL = 600.0
LOGIN_FORMS_MAX = 200
LOGIN_HOW = ("在跑 SYNOX 的這台電腦上雙擊桌面的「SYNOX」捷徑（或 SYNOX 資料夾裡的 Open-SYNOX.bat）會打開新的登入連結；"
             "有接 Telegram／Discord 的話，也可以跟 bot 打 /web。")
LOGIN_BAD = "這個連結用過了、過期了（7 天），或打錯了。" + LOGIN_HOW
CSRF_HEADER = "x-synox-csrf"
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 256 * 1024
MAX_TEXT = 4000
CHAT_RE = re.compile(r"^(c\d{1,6}|tools|mother)$")
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


# app.html 裡的 /*{{INCLUDE:檔名}}*/ 換成 static/ 裡那個檔的內容（主控頁的 control.js／control.css）。
# 分成檔好維護、好測；送出去仍是一頁、同一個 nonce，不多開靜態檔的路由。只認 static/ 底下的 .js／.css 檔名。
INLINE_RE = re.compile(r"/\*\{\{INCLUDE:([a-z][a-z0-9_-]{0,40}\.(?:js|css))\}\}\*/")


# 伺服器自己產生的小頁（登入確認、登入失敗）共用的樣式：跟 static/app.html 同一套 token 的精簡版
# （CSP 是 style-src 'unsafe-inline'，沒有 script；改顏色先改 app.html，再對這裡）。
PAGE_CSS = (
    ":root{--bg:#f3f5f8;--surface:#fff;--line:#e2e7ee;--text:#131b26;--muted:#6a7687;--accent:#0a7c70;"
    "--accent-ink:#fff;--accent-soft:#e0f2ef;--warn-soft:#fdf1dc;--warn:#9a6400;color-scheme:light dark}"
    "@media (prefers-color-scheme:dark){:root{--bg:#0b0f14;--surface:#121924;--line:#1f2b3b;--text:#dbe4ef;"
    "--muted:#7f90a7;--accent:#35e0c4;--accent-ink:#04221d;--accent-soft:rgba(53,224,196,.12);"
    "--warn-soft:rgba(255,180,84,.12);--warn:#ffb454}}"
    "*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;"
    "background:var(--bg);color:var(--text);font:15px/1.6 \"Segoe UI\",\"Microsoft JhengHei UI\","
    "\"Microsoft JhengHei\",\"PingFang TC\",\"Noto Sans TC\",system-ui,sans-serif}"
    ".card{width:min(500px,100%);background:var(--surface);border:1px solid var(--line);border-radius:14px;"
    "padding:28px;box-shadow:0 10px 30px -10px rgba(19,27,38,.22)}"
    ".mark{width:44px;height:44px;border-radius:13px;display:grid;place-items:center;margin-bottom:16px;"
    "font-weight:800;font-size:20px;color:var(--accent-ink);background:var(--accent)}"
    "h1{font-size:22px;margin:0 0 10px}p{margin:10px 0}.big{font-size:1.15em}.muted{color:var(--muted);font-size:14px}"
    ".warn{background:var(--warn-soft);color:var(--warn);border-radius:10px;padding:10px 12px}"
    "a{color:var(--accent)}button{font:inherit;font-weight:650;font-size:16px;min-height:44px;padding:8px 26px;"
    "margin-top:8px;border-radius:10px;border:1px solid var(--accent);background:var(--accent);"
    "color:var(--accent-ink);cursor:pointer}button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}"
)


def _page(status: int, title: str, text: str, extra: Optional[List[Tuple[str, str]]] = None) -> Resp:
    """伺服器自己產生的小頁（登入失敗等）：內容一律 escape。"""
    html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{escape(title)}</title><style>{PAGE_CSS}</style></head><body><main class=\"card\">"
            "<div class=\"mark\" aria-hidden=\"true\">S</div>"
            f"<h1>{escape(title)}</h1><p>{escape(text)}</p><p><a href=\"/\">回 SYNOX</a></p></main></body></html>")
    return status, BASE_HEADERS + [("Content-Type", "text/html; charset=utf-8"), ("X-Frame-Options", "DENY"),
                                   ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; "
                                                               "frame-ancestors 'none'")] + (extra or []), \
        html.encode("utf-8")


# app.html 裡的 <!-- include: 檔名 -->：送出頁面時換成 static/ 裡那個檔的內容（同一個 nonce 的 <style>／<script>），
# CSP 不用放寬、也不多一個靜態檔的路由。只收這張清單裡的檔（工具頁；scripts/make_ui_preview.py 用同一個函式）。
INCLUDES = {"tools.css": "style", "tools.js": "script"}
INCLUDE_RE = re.compile(r"<!-- include: ([a-z0-9_.-]+) -->")


def render_app(nonce: str) -> str:
    """app.html＋include 的檔，{{NONCE}} 換成這次的 nonce。"""
    def include(m):
        name = m.group(1)
        tag = INCLUDES.get(name)
        if tag is None:
            raise ValueError(f"app.html includes an unknown file: {name}")
        with open(os.path.join(STATIC, name), "r", encoding="utf-8") as f:
            text = f.read()
        if f"</{tag}" in text.lower() or "<!--" in text:      # 會提早結束（或攪亂）那個 <style>／<script>
            raise ValueError(f"{name} must not contain </{tag} or <!--")
        return f'<{tag} nonce="{nonce}">\n{text}</{tag}>'
    def inline(m):
        with open(os.path.join(STATIC, m.group(1)), "r", encoding="utf-8") as f:
            return f.read()
    with open(os.path.join(STATIC, "app.html"), "r", encoding="utf-8") as f:
        html = f.read().replace("{{NONCE}}", nonce)
    return INCLUDE_RE.sub(include, INLINE_RE.sub(inline, html))


app_html = render_app          # 主控頁的測試與預覽沿用的舊名字


def _cookie(headers: Dict[str, str], name: str) -> Optional[str]:
    for part in (headers.get("cookie") or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


class BindError(ValueError):
    """SYNOX_WEB_BIND／SYNOX_IN_CONTAINER 不合規則：網頁不開（fail closed），訊息是給人看的那句。"""


def bind_host(environ=None, *, exists=os.path.exists, platform: Optional[str] = None) -> str:
    """網頁要綁哪個位址。預設（沒設 SYNOX_WEB_BIND，或設成 127.0.0.1）＝127.0.0.1，跟以前一樣。
    只有三件事同時成立才綁 0.0.0.0：SYNOX_WEB_BIND=0.0.0.0、SYNOX_IN_CONTAINER=1、不是 Windows 而且看得到容器的證據
    （CONTAINER_MARKERS）。容器裡的 0.0.0.0 只是容器自己的網卡；宿主那一邊由 compose 只發佈到 127.0.0.1（docs/docker.md）。
    其他值（區網位址、::、localhost、打錯字）、或不在容器裡卻要改綁 → BindError，網頁不開。"""
    environ = os.environ if environ is None else environ
    platform = os.name if platform is None else platform
    wanted = (environ.get(BIND_ENV) or "").strip()
    if not wanted or wanted == HOST:
        return HOST
    if wanted not in CONTAINER_BIND_HOSTS:
        raise BindError(f"{BIND_ENV}={wanted!r} 不收：只能是 127.0.0.1（預設）或 0.0.0.0（只限 SYNOX 的容器裡）。"
                        "要讓別台電腦連進來請架反向代理＋TLS（docs/security.md「網頁介面」）。")
    flag = (environ.get(CONTAINER_ENV) or "").strip()
    if flag != "1":
        raise BindError(f"{BIND_ENV}={wanted} 只能在 SYNOX 的容器裡用（要 {CONTAINER_ENV}=1，現在是 {flag or '沒設'}）；"
                        "一般電腦上網頁只綁 127.0.0.1。拿掉這個環境變數就好。")
    if platform == "nt" or not any(exists(p) for p in CONTAINER_MARKERS):
        raise BindError(f"設了 {CONTAINER_ENV}=1，但這裡看起來不是容器（找不到 {'、'.join(CONTAINER_MARKERS)}）："
                        f"不改綁位址。一般電腦上請拿掉 {BIND_ENV}。")
    return wanted


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
        self.prefs = toolpage.UserPrefs(os.path.join(data, "web_prefs"), vault)   # 每個人的工具頁排版
        self._clock = clock
        self._login_forms: Dict[str, tuple] = {}     # 表單 token 的雜湊 → (登入 token 雜湊, 瀏覽器 cookie 雜湊, 到期)
        self._login_lock = threading.Lock()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.channel_probes = None            # (telegram_probe, discord_probe)；None＝真的（wizard 那兩個）
        self._mother_fresh: set = set()       # 這次執行中已經清過「常駐助理」聊天畫面的人（重開 SYNOX＝它的記憶清空）
        self._channels_changed: set = set()   # 這次執行中改過的聊天通道（要重開才生效）
        self.bind_host = bind_host            # 綁哪個位址（start 時讀環境變數；測試換成假的容器證據）

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
            host = self.bind_host()
        except BindError as e:
            self.error = f"網頁介面沒有開：{e}"
            logging.error("[WEB] %s", self.error)
            return False
        try:
            server = _Server((host, self.port), _Handler)
        except OSError as e:
            self.error = (f"網頁介面開不起來：{host}:{self.port} 不能用（{e}）。"
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
        if host != HOST:
            logging.info("[WEB] 容器模式：綁容器裡的 %s:%s；宿主那一邊只該發佈到 127.0.0.1（docs/docker.md）",
                         host, self.port)
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
                if session is None and self._local_owner_navigation(headers):
                    return self._auto_login_page()
                return self.app_page()
            if path == "/login" and method == "GET":
                return self.login_page((query.get("t") or [""])[0], headers, session)
            if path == "/login" and method == "POST":
                return self.login_post(headers, body)
            m = re.match(r"^/packs/([a-z][a-z0-9_-]{0,31})/panel$", path)
            if m and method == "GET":
                if session is None:
                    return _page(401, "請先登入", LOGIN_HOW)
                return self.panel(self._user(session), m.group(1))
            m = re.match(r"^/tutorials/([a-z][a-z0-9_-]{0,31})/?$", path)
            if m and method == "GET":
                return self.tutorial(m.group(1))
            if path.startswith("/api/"):
                if session is None:
                    return _err(401, "請先登入：" + LOGIN_HOW)
                if method != "GET":
                    problem = self._csrf_problem(headers, session)
                    if problem:
                        return _err(403, problem)
                return self.api(method, path, query, headers, body, session)
            return _page(404, "找不到", "沒有這一頁。")
        except Exception as e:
            logging.exception("[WEB] %s %s failed", method, path)
            return _err(500, f"出錯了：{type(e).__name__}")

    # 本機擁有者直接開網址就進（不用連結）：這台電腦的人本來就能改設定檔、裝 pack，網頁不該再擋他。
    # 但網頁能裝 pack＝能在這台電腦跑程式，所以只認「使用者自己在瀏覽器網址列打／書籤／桌面捷徑開」的那一下，
    # 不認別的網站戳過來的請求：Host 必須是 127.0.0.1／localhost 本身（擋 DNS rebinding）、
    # Sec-Fetch-Site 必須是 none（使用者直接導覽；別的網站的連結、圖片、fetch、表單都是 cross-site／same-site）、
    # Sec-Fetch-Mode=navigate 且 Dest=document（不是 API／iframe）。沒有這些標頭（curl、舊瀏覽器）就不自動登入，
    # 照舊用連結。個人版才有；伺服器版、有 public_url（反向代理）、或 web.local_auto_login=false 都關掉。

    def _local_auto_login_enabled(self) -> bool:
        web = getattr(self.config, "web", {}) or {}
        return (not self.server_mode and not str(web.get("public_url") or "").strip()
                and bool(web.get("local_auto_login", True)))

    def _local_owner_navigation(self, headers: Dict[str, str]) -> bool:
        if not self._local_auto_login_enabled():
            return False
        if headers.get("host", "").lower() not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return False
        return (headers.get("sec-fetch-site") == "none" and headers.get("sec-fetch-mode") == "navigate"
                and headers.get("sec-fetch-dest") == "document" and not headers.get("origin"))

    def _auto_login_page(self) -> Resp:
        owner = int(self.config.owner_id)
        sid, _session = self.sessions.create(owner)
        self.app.users.get_or_create(owner)
        status, headers, body = self.app_page()
        cookie = f"{COOKIE}={sid}; HttpOnly; SameSite=Lax; Path=/; Max-Age={int(self.sessions.ttl)}" + self._secure()
        return status, headers + [("Set-Cookie", cookie)], body

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
        html = render_app(nonce)
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
            now_text = (f"<p class=\"warn\"><b>注意：</b>這個瀏覽器現在登入的是 {escape(self._who(session.tg_id))}，"
                        "按下去會換成上面這個帳號。</p>")
        html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>登入 SYNOX</title>"
                f"<style>{PAGE_CSS}</style></head><body><main class=\"card\">"
                "<div class=\"mark\" aria-hidden=\"true\">S</div>"
                "<h1>登入 SYNOX</h1>"
                f"<p class=\"big\">你將以 <b>{escape(self._who(tg_id))}</b> 登入。</p>{now_text}"
                "<p class=\"muted\">這不是你的帳號（例如別人傳給你的連結）就<b>不要按</b>，直接關掉這一頁。</p>"
                "<form method=\"post\" action=\"/login\">"
                f"<input type=\"hidden\" name=\"f\" value=\"{escape(form)}\">"
                "<button type=\"submit\">登入</button></form>"
                "</main></body></html>")
        csp = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        cookie = (f"{LOGIN_COOKIE}={binder}; HttpOnly; SameSite=Strict; Path=/login; Max-Age={int(LOGIN_FORM_TTL)}"
                  + self._secure())
        base = [h for h in BASE_HEADERS if h[0] != "Referrer-Policy"] + [("Referrer-Policy", "same-origin")]
        return 200, base + [("Content-Type", "text/html; charset=utf-8"), ("X-Frame-Options", "DENY"),
                            ("Content-Security-Policy", csp), ("Set-Cookie", cookie)], html.encode("utf-8")

    def login_post(self, headers: Dict[str, str], body: bytes) -> Resp:
        origin = headers.get("origin")
        fetch_site = headers.get("sec-fetch-site")
        if origin == "null":
            # 頁面帶 Referrer-Policy: no-referrer 時，瀏覽器連「同源」表單 POST 都送 Origin: null（真的 Edge／Chrome 會）。
            # Sec-Fetch-Site 是瀏覽器自己加、網頁改不了的標頭：same-origin 才放行；別的網站送來的是 cross-site／缺標頭。
            origin_ok = fetch_site == "same-origin"
        else:
            origin_ok = not origin or urlsplit(origin).netloc == headers.get("host", "")
        if not origin_ok:
            return _page(403, "登入沒有完成", "來源不對（不是從 SYNOX 自己的登入頁送出的）。")
        if fetch_site not in (None, "", "same-origin", "none"):
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

    # 圖文教學（docs/tutorials/<名字>/index.html；synox/tutorials.py）：公開的說明文件，不碰任何資料、不用登入
    # （第一次設定的人可能還沒配對、還登不進來）。只收合規則的名字、只讀那個資料夾裡的 index.html；
    # CSP 只放行內嵌樣式與 data: 圖，頁裡就算有 <script> 也不會跑。
    def tutorial(self, name: str) -> Resp:
        html = tutorials.read(name)
        if html is None:
            return _page(404, "找不到", "沒有這份教學。")
        csp = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'; base-uri 'none'"
        return 200, BASE_HEADERS + [("Content-Type", "text/html; charset=utf-8"), ("X-Frame-Options", "DENY"),
                                    ("Content-Security-Policy", csp)], html

    # ── API ──────────────────────────────────────────────────────────

    def api(self, method: str, path: str, query, headers, body: bytes, session: Session) -> Resp:
        user = self._user(session)
        if path.startswith("/api/runtime/"):          # 主控面板：常駐助理／心跳／任務（docs/runtime-api.md；含 PUT）
            from synox.runtime import web_api as runtime_api
            return runtime_api.route(self, user, method, path, body)
        if method == "GET":
            if path == "/api/me":
                return _json(200, self.me(user, session))
            if path == "/api/chats":
                if self.is_owner(user):
                    self._chat(user, MOTHER_CHAT)                 # 擁有者的側欄固定有「常駐助理」
                chats = self.chats.list_chats(user.tg_id)
                rest = [c for c in chats if c["id"] != MOTHER_CHAT]
                mine = [c for c in chats if c["id"] == MOTHER_CHAT] if self.is_owner(user) else []
                return _json(200, {"chats": rest + mine,        # 「常駐助理」排最後；畫面自己把它釘在最上面
                                   "archived_count": self.chats.archived_count(user.tg_id)})
            if path == "/api/chats/archived":
                return _json(200, {"chats": self.chats.list_chats(user.tg_id, archived=True)})
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
            if path == "/api/settings/channels":
                return self.channels(user)
            if path == "/api/settings/channels/discord/pair":
                return self.discord_pair_state(user)
            if path == "/api/settings/channels/telegram/pair":
                return self.telegram_pair_state(user)
            if path == "/api/usage":
                return self.usage_report(user, (query.get("period") or ["day"])[0])
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
        if path == "/api/tools/layout":
            return self.save_layout(user, data)
        if path == "/api/tools/health":
            return self.tool_health(user, data)
        m = re.match(r"^/api/chat/([a-z0-9]+)/(send|press|archive|restore|delete)$", path)
        if m:
            if m.group(2) in ("archive", "restore", "delete"):
                return self.chat_keeping(user, m.group(1), m.group(2))
            return self.send(user, m.group(1), data) if m.group(2) == "send" else self.press(user, m.group(1), data)
        if path == "/api/settings/llm":
            return self.save_llm(user, data)
        if path == "/api/settings/llm/test":
            return self.test_llm(user, data)
        if path == "/api/settings/llm/local-advice":
            return self.local_advice(user, data)
        if path == "/api/settings/channels/telegram":
            return self.save_telegram(user, data)
        if path == "/api/settings/channels/discord":
            return self.save_discord(user, data)
        if path == "/api/settings/channels/discord/pair":
            return self.discord_pair(user, data)
        if path == "/api/settings/channels/telegram/pair":
            return self.telegram_pair(user, data)
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
        if chat_id == MOTHER_CHAT:
            if not self.is_owner(user):
                return None                                       # 只有擁有者；成員當作沒有這段
            first = user.tg_id not in self._mother_fresh
            chat = self.chats.ensure(user.tg_id, MOTHER_CHAT, "🫀 常駐助理")
            if first:                                             # 這次執行的第一次：它的記憶是空的，畫面也跟著清空
                self._mother_fresh.add(user.tg_id)
                self.chats.clear(user.tg_id, MOTHER_CHAT)
            return chat
        return self.chats.get(user.tg_id, chat_id)

    def chat_keeping(self, user, chat_id: str, action: str) -> Resp:
        """對話的封存／還原／徹底刪除。刪除只收已封存的（要先封存）；刪掉時 AI 對這段的記憶也一起丟。"""
        if not CHAT_RE.match(chat_id or "") or chat_id in (TOOLS_CHAT, MOTHER_CHAT):
            return _err(404, "這一段不能封存或刪除。")
        if self.chats.get(user.tg_id, chat_id) is None:
            return _err(404, "沒有這段對話。")
        if action == "archive":
            ok = self.chats.archive(user.tg_id, chat_id)
        elif action == "restore":
            ok = self.chats.restore(user.tg_id, chat_id)
        else:
            ok = self.chats.delete_archived(user.tg_id, chat_id)
            if ok:
                loop = self.app.extras.get("synox_agent")
                if loop is not None:
                    loop.reset(user.tg_id, user, chat_id)       # AI 記得的這段也一起忘掉
            elif self.chats.get(user.tg_id, chat_id) is not None:
                return _err(409, "要先封存，才能徹底刪除。")
        if not ok and action != "delete":
            return _err(409, "這段已經是那個狀態了。")
        logging.info("[WEB] %s %s chat %s", user.tg_id, action, chat_id)
        return _json(200, {"ok": True, "archived_count": self.chats.archived_count(user.tg_id)})

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
        if (self._chat(user, chat_id) or {}).get("archived"):
            return _err(409, "這段對話封存了：先還原才能繼續。")
        self.chats.append(user.tg_id, chat_id, "me", text)
        if chat_id == MOTHER_CHAT:
            return self._send_mother(user, text)
        inbound = Inbound(WEB, user.tg_id, user.tg_id, text, username=user.username or "web", sent_at=time.time())
        route = self.app.dispatcher.handle(self.channel(user, chat_id), inbound)
        return _json(200, {"ok": True, "route": getattr(route, "kind", ""), "rev": self.chats.rev(user.tg_id)})

    def _send_mother(self, user, text: str) -> Resp:
        """跟常駐助理聊天：不經 dispatcher／對話助理，叫 runtime 的母 session（沒有工具）；背景跑，不卡 request。"""
        from synox import runtime
        rt = runtime.of(self.app)
        tg_id = user.tg_id

        def run():
            try:
                answer = rt.mother.chat(text) if rt is not None else "常駐助理沒有啟用（runtime 沒有裝上）。"
            except Exception as e:
                logging.exception("[WEB] mother chat failed")
                answer = f"⚠️ 常駐助理沒有回應：{e}"
            self.chats.append(tg_id, MOTHER_CHAT, "bot", answer)

        self.app.tasks.run(run, name="mother-chat")
        return _json(200, {"ok": True, "route": "mother", "rev": self.chats.rev(tg_id)})

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
        """工具頁的一張指令卡（說明、危險程度、參數表單；web/toolpage.py）。"""
        meta = (self.app.extras.get("synox_tool_meta") or {}).get(node.path) or {}
        return toolpage.command_info(node, meta)

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
                "id": pack.manifest.group, "name": pack.name, "title": pack.manifest.title,
                "summary": pack.manifest.summary, "description": toolpage.skill_description(pack.manifest),
                "category": getattr(pack.manifest, "category", ""),
                "kind": pack.manifest.kind, "version": pack.manifest.version,
                "stage": pack.manifest.stage, "stage_label": pack.manifest.stage_label,     # 穩定度（沒寫＝alpha）
                "stage_text": stage_text(pack.manifest.stage),
                "status": "要先設定" if connector else "已連接",
                "panel": f"/packs/{pack.name}/panel" if pack.manifest.web.get("panel") else None,
                "commands": [self._leaf_info(n) for n in leaves]}
            self._health_marks(row, user)
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
            groups_out.append({"id": toolpage.BASICS_ID, "title": "🧭 基本", "summary": "開始、說明、結束問答",
                               "category": toolpage.BUILTIN, "commands": [self._leaf_info(n) for n in basics]})
        for node in registry.root.children.values():
            if not node.is_group or node.name in pack_groups or not registry.visible(user, node):
                continue
            leaves = [n for n in node.walk() if not n.is_group and registry.visible(user, n)
                      and n.path != "agent.ai_approve"]
            if leaves:
                groups_out.append({"id": node.name, "title": node.title, "summary": node.summary,
                                   "category": toolpage.BUILTIN, "commands": [self._leaf_info(n) for n in leaves]})
        out = {"packs": packs_out, "groups": groups_out}
        if self.is_owner(user):                       # 只有擁有者裝得了工具；工具頁空的時候給「去哪裡裝」
            from synox.packs import library
            out["library"] = library.status(self.app)
        try:
            stored = self.prefs.get(user.tg_id, toolpage.LAYOUT_KEY)
        except Exception as e:                    # 保管箱解不開：照預設排，不蓋掉原本的檔
            logging.warning("[WEB] tool layout of %s unreadable: %s", user.tg_id, type(e).__name__)
            stored, out["layout_error"] = None, "你的群組排版讀不到（保管箱解不開），先照預設排；存檔前請先看 doctor。"
        out["layout"] = toolpage.effective(stored, self._tool_categories(out))
        return out

    def _health_marks(self, row: dict, user) -> None:
        """工具頁每張指令卡的健康狀態（docs/tool-health.md）：不正常的才帶 health（狀態、原因、下次檢查）；
        擁有者另外看得到 diag、能按「重新檢查」「解除隔離」（health_admin）。別人的 scope=user 紀錄不給。出錯＝不顯示（fail open）。"""
        from synox import health
        reg = health.of(self.app)
        owner = self.is_owner(user)
        row["health_admin"] = owner and reg is not None and reg.enabled
        if reg is None or not reg.enabled:
            return
        try:
            for cmd in row["commands"]:
                mine = [e for e in reg.problems(cmd["path"]) if e.user is None or e.user == user.tg_id]
                if mine:
                    cmd["health"] = [reg.view(e, owner=owner) for e in mine]
        except Exception:
            logging.exception("[WEB] health marks failed (ignored)")

    def tool_health(self, user, data: dict) -> Resp:
        """POST /api/tools/health {"key": "<工具>[@<id>]", "action": "recheck"|"release"}：只有擁有者。
        recheck＝用 pack 宣告的自我檢查重新檢查一次（背景跑，不叫 AI）；release＝解除（含隔離）。"""
        from synox import health
        if not self.is_owner(user):
            return _err(403, "只有擁有者能重新檢查或解除隔離。")
        reg = health.of(self.app)
        if reg is None or not reg.enabled:
            return _err(409, "工具健康管理沒有開（config.json 的 health.enabled）。")
        key, action = str(data.get("key") or ""), data.get("action")
        entry = reg.entry(key)
        if entry is None or action not in ("recheck", "release"):
            return _err(404, "沒有這筆紀錄，或動作不對（recheck｜release）。")
        if action == "release":
            reg.release(key)
            return _json(200, {"ok": True, "state": entry.state})
        if entry.state == health.QUARANTINED:
            return _err(409, "隔離中的工具要先「解除隔離」。")
        self.app.tasks.run(lambda: health.recheck(self.app, entry, manual=True), name="health-recheck")
        return _json(200, {"ok": True, "queued": True})

    @staticmethod
    def _tool_categories(tools: dict):
        return [(row["id"], row.get("category") or "") for row in tools["packs"] + tools["groups"]]

    def save_layout(self, user, data: dict) -> Resp:
        """工具頁的「編輯群組」：存這個人自己的排版（{"reset": true}＝回到 pack 建議的排法）。"""
        tools = self.tools(user)
        if "layout_error" in tools:
            return _err(409, tools["layout_error"])
        visible = [tid for tid, _cat in self._tool_categories(tools)]
        if data.get("reset") is True:
            self.prefs.set(user.tg_id, toolpage.LAYOUT_KEY, None)
            return _json(200, {"ok": True, "layout": toolpage.effective(None, self._tool_categories(tools))})
        try:
            layout = toolpage.parse_layout(data)
        except toolpage.LayoutError as e:
            return _err(400, str(e))
        old = self.prefs.get(user.tg_id, toolpage.LAYOUT_KEY)
        layout = toolpage.merge_hidden(layout, old, visible)
        self.prefs.set(user.tg_id, toolpage.LAYOUT_KEY, layout)
        logging.info("[WEB] %s saved tool layout (%d groups)", user.tg_id, len(layout["groups"]))
        return _json(200, {"ok": True, "layout": toolpage.effective(layout, self._tool_categories(tools))})

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
        if llm.get("kind") == "local":
            out["llm"].update({k: llm.get(k) for k in ("server", "context_size", "timeout", "max_total_timeout", "tools")})
            current = self.app.extras.get("synox_agent")
            warning = getattr(getattr(current, "adapter", None), "last_warning", "")
            if warning:
                out["llm"]["warning"] = warning              # 本地模型最近一次的截斷提醒（不靜默）
        from synox.llm.local import DEFAULT_URLS
        from synox.llm.local_advice import OPTIONS
        out["llm_choices"] = [{"choice": "claude_code", "label": logic.CLAUDE_TITLE,
                               "models": [{"value": v, "label": lbl} for v, lbl in logic.CLAUDE_MODELS]}] + \
            [{"choice": "keys", "provider": code, "label": v[0], "model": v[2], "needs_url": v[3]}
             for code, v in logic.KEY_PROVIDERS.items()] + \
            [{"choice": "local", "label": logic.LOCAL_TITLE,
              "servers": [{"value": k, "label": lbl, "base_url": DEFAULT_URLS[k]} for k, lbl in logic.LOCAL_SERVERS.items()],
              "context_options": list(OPTIONS)}] + [{"choice": "none", "label": "先不用 AI"}]
        report = self.app.extras.get("synox_pack_report")
        user_dir = os.path.realpath(self.pack_dirs[0]) if self.pack_dirs else ""
        out["packs"] = [{"name": i.name, "status": i.status, "detail": i.detail, "kind": i.kind,
                         "version": i.version, "lock": getattr(i, "lock", ""),
                         "removable": bool(user_dir) and os.path.realpath(os.path.dirname(i.folder)) == user_dir}
                        for i in (report.items if report else [])]
        from synox.packs import library             # 出廠不帶工具：裝了幾個、工具庫在哪、怎麼裝（packs/library.py）
        out["library"] = library.status(self.app)
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
        if choice == "local":
            tools = data.get("tools", current.get("tools", True) if current.get("kind") == "local" else True)
            return logic.llm_settings("local", server=str(data.get("server") or "ollama"),
                                      base_url=str(data.get("base_url") or ""), model=str(data.get("model") or ""),
                                      context_size=data.get("context_size", 0), tools=tools,
                                      timeout=data.get("timeout") if data.get("timeout") not in (None, "") else
                                      (current.get("timeout") if current.get("kind") == "local" else None),
                                      max_total_timeout=data.get("max_total_timeout")
                                      if data.get("max_total_timeout") not in (None, "") else
                                      (current.get("max_total_timeout") if current.get("kind") == "local" else None))
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
        stale = ("kind", "api_key", "base_url", "model", "tools", "server", "context_size", "timeout",
                 "max_total_timeout")                       # 換來源時，舊來源的欄位不要留在記憶體裡
        self.config.llm = {**{k: v for k, v in (self.config.llm or {}).items() if k not in stale}, **cfg["llm"]}
        return _json(200, self._apply_llm(llm))

    def _apply_llm(self, llm: dict) -> dict:
        """存好之後立刻換上：對話助理與常駐助理都用新的 AI 來源，不用重開。接不上就說原因（設定已經存了）。"""
        from synox import agent
        from synox.llm import make_adapter
        from synox.llm.base import LLMError
        kind = llm["kind"]
        try:
            adapter = make_adapter(self.config, self.vault)
        except LLMError as e:
            self.app.extras["llm_error"] = str(e)
            return {"ok": True, "kind": kind, "applied": False,
                    "message": f"存好了，但現在還接不上：{e}　（修好之後重開 SYNOX，或再按一次「存起來」）"}
        self.app.extras.pop("llm_error", None)
        agent.set_adapter(self.app, adapter, self.config)
        if adapter is None:
            return {"ok": True, "kind": kind, "applied": True, "message": "存好了。現在不用 AI；打指令照常可以用。"}
        msg = "存好了，已經換上，現在就能在對話裡用。常駐助理（主控頁）也用這個來源。"
        if kind == "claude_code":
            from synox.llm.claude_code import find_claude
            if not find_claude():
                msg += "　⚠ 這台電腦還找不到 claude，按「測一下」看安裝方法。"
        return {"ok": True, "kind": kind, "applied": True, "message": msg}

    def usage_report(self, user, period: str) -> Resp:
        """AI 用量與花費（設定頁的小儀表板）：總帳 data/llm_usage.json 依每小時／天／週／月分組。只給擁有者。"""
        denied = self._owner_only(user)
        if denied:
            return denied
        from datetime import datetime
        from isdtelekit.core import jsonstore
        from synox.agent import usage_report
        from synox.agent.budget import usd_of
        if period not in usage_report.PERIODS:
            return _err(400, "period 要是 " + "、".join(usage_report.PERIODS) + " 其中之一。")
        data = jsonstore.load_json(self.config.path("llm_usage.json"), {}) or {}
        out = usage_report.series(data, period, datetime.now(),
                                  lambda tin, tout: usd_of(self.config, {"input": tin, "output": tout}))
        kind = (self.config.llm or {}).get("kind", "none")
        out["kind"] = kind
        out["subscription"] = kind == "claude_code"          # 訂閱制：美元是照 API 價換算的約數
        return _json(200, out)

    def test_llm(self, user, data: dict) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.llm.factory import resolve_secret
        from synox.wizard import logic
        llm, problem = self._llm_from(data)
        if problem:
            return _err(400, problem)
        if llm.get("kind") == "local":               # 唯讀探測（不載入模型）：模型在不在、context 合不合理
            from synox.llm import make_adapter
            from synox.llm.local import report_lines
            try:
                report = make_adapter({"llm": llm}).inspect()
            except Exception as e:
                return _json(200, {"ok": False, "message": f"❌ {e}"})
            ok = not report["problems"]
            head = "✅ 找到模型，設定看起來合理（只讀了模型資料，沒有真的載入模型）" if ok else "❌ " + report["problems"][0]
            return _json(200, {"ok": ok, "message": head, "lines": report_lines(report)})
        if str(llm.get("api_key", "")).startswith(("vault:", "env:")):
            llm["api_key"] = resolve_secret(llm["api_key"], self.vault)
        result = logic.probe_llm(llm)
        out = {"ok": result is None, "message": "✅ 接得通" if result is None else f"❌ {result}"}
        if result is not None and llm.get("kind") == "claude_code":
            from synox.llm.claude_code import NOT_FOUND
            if result == NOT_FOUND:                 # 沒裝：跟精靈一樣給下載點，裝好再按「測一下」
                out["download_url"] = logic.CLAUDE_DOWNLOAD_URL
            elif "登入" in result:                  # 裝了但還沒登入
                out["message"] += "　→ 在終端機輸入 claude，照畫面登入一次，再按「測一下」。"
        return _json(200, out)

    def local_advice(self, user, data: dict) -> Resp:
        """本地模型的 context-size 建議（docs/adr/0007）：只給擁有者；唯讀探測（Ollama /api/tags、/api/show，不載入模型）＋
        這台的記憶體＋這個人實際的提示長度（系統提示＋全部工具規格）。連不上就退回靜態表並說明。
        用 POST（要 CSRF header）：這個 API 會讓 SYNOX 去連使用者填的網址，不能被別的網頁用連結觸發。"""
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.wizard import logic
        server = str(data.get("server") or "ollama")
        if server not in logic.LOCAL_SERVERS:
            return _err(400, "server 只能是 " + "、".join(logic.LOCAL_SERVERS) + "。")
        base_url = str(data.get("base_url") or "").strip()
        if base_url and not base_url.startswith(("http://", "https://")):
            return _err(400, "網址要以 http:// 或 https:// 開頭。")
        try:
            from synox.agent import prompt_chars
            chars = prompt_chars(self.app, user)
        except Exception:
            logging.exception("[WEB] cannot measure the prompt size (advice falls back to a fixed estimate)")
            chars = None
        try:
            max_tokens = int((self.config.llm or {}).get("max_tokens") or 1024)
        except (TypeError, ValueError):
            max_tokens = 1024
        try:
            advice = logic.local_advice(server, base_url, str(data.get("model") or ""), prompt_chars=chars,
                                        max_tokens=max_tokens)
        except Exception as e:
            return _err(400, f"算不出建議：{e}")
        from synox.llm.local_advice import option_label
        for row in advice["options"]:
            row["label"] = option_label(row)
        from synox.llm.local import url_warning
        if url_warning(base_url):
            advice["notes"].insert(0, url_warning(base_url))
        return _json(200, advice)

    # ── 聊天通道（Telegram／Discord）：跟精靈同一套檢查與存法；token 永遠不回傳、不寫 log ──────
    # 改了要重開 SYNOX 才生效（App 沒有「執行中換通道」）。擁有者配對不在這裡做（Setup.bat／discord pair）。

    def _probes(self):
        """(telegram_probe, discord_probe)；測試換成假的（channel_probes），不連網。"""
        if self.channel_probes is not None:
            return self.channel_probes
        from synox.wizard import discord_probe, telegram_probe
        return telegram_probe, discord_probe

    @staticmethod
    def _scrub(text, token: str) -> str:
        text = str(text or "")
        return text.replace(token, "（token）") if token else text

    def _file_owner(self, cfg: dict) -> int:
        owner = cfg.get("owner_id", cfg.get("machine_owner_id"))
        try:
            return int(owner)
        except (TypeError, ValueError):
            return int(self.config.owner_id or 0)

    def _discord_paired(self, owner: int, settings: dict) -> bool:
        if str(settings.get("owner_user_id") or "").strip():
            return True
        try:
            from synox.discord.events import DISCORD
            from synox.identity import Identities
            return Identities(self.config.path("identities.json")).external(DISCORD, owner) is not None
        except Exception:
            return False

    def channels(self, user) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.identity import BASE
        from synox.wizard import logic
        tg, dc = self._probes()
        cfg = logic.read_existing(self.config_path)
        owner = self._file_owner(cfg)
        token = str(cfg.get("bot_token") or "").strip()
        telegram = {"saved": tg.valid_token(token), "active": bool(self.config.has_token),
                    "owner_paired": 0 < owner < BASE, "bot": "", "problem": ""}
        if telegram["saved"]:
            ok, info = tg.get_me(token)
            telegram["bot" if ok else "problem"] = self._scrub(info, token)
        telegram["restart"] = "telegram" in self._channels_changed or (telegram["saved"] and not telegram["active"])
        link = self.app.extras.get("telegram_link")          # 擁有者是保留號段（只用網頁／Discord 安裝）才有
        tp = self.app.extras.get("telegram_pairing")
        telegram["pairable"] = link is not None or (telegram["saved"] and owner >= BASE)     # 要用網頁配對（不是精靈）
        telegram["paired_as"] = (link.external() or "") if link is not None else ""
        if telegram["paired_as"]:
            telegram["owner_paired"] = True
        telegram["pairing"] = tp.pending() if tp is not None else None
        telegram["pair_ready"] = link is not None and telegram["active"] and not telegram["restart"]
        d = (cfg.get("channels") or {}).get("discord") if isinstance(cfg.get("channels"), dict) else None
        d = d if isinstance(d, dict) else {}
        discord = {"multi": "bots" in d, "saved": False, "active": "discord" in self.app.extras,
                   "owner_paired": self._discord_paired(owner, d), "bot": "", "problem": "", "invite": ""}
        if not discord["multi"] and d.get("bot_token") and d.get("enabled", True):
            discord["saved"] = True
            dtoken = ""
            try:
                from synox.llm.factory import resolve_secret
                dtoken = resolve_secret(str(d["bot_token"]), self.vault).strip()
            except Exception:
                discord["problem"] = "token 在保管箱裡讀不出來（保管箱沒打開，或還沒存）：重新貼一次。"
            if dtoken:
                ok, info = dc.get_me(dtoken)
                discord["bot" if ok else "problem"] = self._scrub(info, dtoken)
                bid = dc.bot_id(dtoken) if ok else None
                discord["invite"] = dc.invite_url(bid) if bid else ""
        discord["restart"] = "discord" in self._channels_changed or (discord["saved"] and not discord["active"])
        discord["paired_as"] = self._discord_external(owner)
        wp = self._discord_pairing()
        discord["pairing"] = wp.pending() if wp is not None else None
        discord["pair_ready"] = wp is not None and discord["active"] and not discord["restart"]   # bot 上線了才收得到配對碼
        return _json(200, {"telegram": telegram, "discord": discord})

    def _discord_pairing(self):
        """配對碼的保管者：Discord 正在跑時 discord.install 建的那個（沒跑＝None）。"""
        return self.app.extras.get("discord_pairing")

    def _discord_external(self, owner: int) -> str:
        """擁有者配對好的 Discord 使用者 id（沒有＝空字串）。"""
        try:
            from synox.discord.events import DISCORD
            from synox.identity import Identities
            ids = Identities(self.config.path("identities.json"))
            return str(ids.external(DISCORD, owner) or "")
        except Exception:
            return ""

    def telegram_pair_state(self, user) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        link = self.app.extras.get("telegram_link")
        tp = self.app.extras.get("telegram_pairing")
        return _json(200, {"pairing": tp.pending() if tp is not None else None,
                           "paired_as": (link.external() or "") if link is not None else "",
                           "just_paired": tp.last_paired if tp is not None else None})

    def telegram_pair(self, user, data: dict) -> Resp:
        """擁有者配對 Telegram 帳號（只給擁有者是保留號段的安裝）：start 產生六位數字（私訊 bot 傳它）、cancel、
        manual（直接給 Telegram 編號）。做法是 telegram_link.py 的對照表：資料不動、不換擁有者 id。"""
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox import telegram_link
        link = self.app.extras.get("telegram_link")
        tp = self.app.extras.get("telegram_pairing")
        action = str(data.get("action") or "")
        if action == "cancel":
            if tp is not None:
                tp.cancel()
            return _json(200, {"ok": True})
        if link is None:
            return _err(409, "Telegram 還沒在執行（先存好 bot token、重新啟動 SYNOX），或你的擁有者本來就是 Telegram 帳號"
                             "（用安裝精靈配對的，不用在這裡配）。")
        if action == "start":
            started = tp.start()
            logging.info("[WEB] %s started a Telegram owner pairing", user.tg_id)
            return _json(200, {"ok": True, **started})
        if action == "manual":
            raw = "".join(str(data.get("user_id") or "").split())
            if not (raw.isdigit() and 5 <= len(raw) <= 15):
                return _err(400, "Telegram 編號是一串 6～12 位的數字（對 Telegram 的 @userinfobot 傳任何訊息，它會告訴你）。")
            try:
                notes = telegram_link.bind_owner(link.identities, raw, link.owner_id)
            except Exception as e:
                return _err(400, str(e))
            logging.info("[WEB] %s paired Telegram user %s as the owner", user.tg_id, raw)
            return _json(200, {"ok": True, "paired_as": raw,
                               "message": "✅ 配對好了：這個 Telegram 帳號現在是擁有者。" + "".join(notes)})
        return _err(400, "action 要是 start、cancel 或 manual。")

    def discord_pair_state(self, user) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        wp = self._discord_pairing()
        owner = int(self.config.owner_id)
        return _json(200, {"pairing": wp.pending() if wp is not None else None, "paired_as": self._discord_external(owner),
                           "just_paired": wp.last_paired if wp is not None else None})

    def discord_pair(self, user, data: dict) -> Resp:
        """擁有者配對 Discord 帳號：action=start 產生六位數字（私訊 bot 傳它，正在跑的 SYNOX 接上，不用開終端機）、
        cancel、manual（直接給 Discord 使用者 ID，馬上接上）。接上的做法跟 `discord pair` 同一個（discord.bind_owner）。"""
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox import discord as dc_mod
        from synox.identity import Identities, IdentityError, IdentityFileError
        action = str(data.get("action") or "")
        wp = self.app.extras.get("discord_pairing")           # Discord 正在跑才有
        owner = int(self.config.owner_id)
        if action == "start":
            if wp is None:
                return _err(409, "Discord 還沒在執行：先存好 bot token、重新啟動 SYNOX，再來配對。")
            started = wp.start()
            logging.info("[WEB] %s started a Discord owner pairing", user.tg_id)
            return _json(200, {"ok": True, **started})
        if action == "cancel":
            if wp is not None:
                wp.cancel()
            return _json(200, {"ok": True})
        if action == "manual":
            raw = "".join(str(data.get("user_id") or "").split())
            if not (raw.isdigit() and 15 <= len(raw) <= 22):
                return _err(400, "Discord 使用者 ID 是一串 17～19 位的數字（Discord 設定 → 進階 → 開啟開發者模式，"
                                 "再對自己的頭像按右鍵 → 複製使用者 ID）。")
            try:
                ids = Identities(self.config.path("identities.json"))
                notes = dc_mod.bind_owner(ids, raw, owner)
            except (IdentityError, IdentityFileError) as e:
                return _err(400, str(e))
            logging.info("[WEB] %s paired Discord user %s as the owner", user.tg_id, raw)
            return _json(200, {"ok": True, "paired_as": raw, "message": "✅ 配對好了：這個 Discord 帳號現在是擁有者。"
                                                                          + ("".join(notes) if notes else "")})
        return _err(400, "action 要是 start、cancel 或 manual。")

    def save_telegram(self, user, data: dict) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.identity import BASE
        from synox.wizard import logic
        tg, _dc = self._probes()
        token = str(data.get("token") or "").strip()
        if not token:
            return _err(400, "要貼上 Telegram bot 的 token（@BotFather 給的那串）。")
        ok, info = tg.get_me(token)
        if not ok:
            return _err(400, self._scrub(info, token))
        cfg = logic.read_existing(self.config_path)
        if not cfg:
            return _err(400, "讀不到 config.json，沒有存（重跑 Setup.bat）。")
        cfg["bot_token"] = token                                # 跟精靈一樣寫在 config.json
        if cfg.get("owner_id", cfg.get("machine_owner_id")) in (None, ""):
            cfg["owner_id"] = int(self.config.owner_id)         # 只用 Discord 的設定沒寫 owner_id：照現在的擁有者寫
        logic.write_config(self.config_path, cfg)
        self._channels_changed.add("telegram")
        bot = self._scrub(info, token)
        logging.info("[WEB] %s saved a Telegram bot token (bot @%s)", user.tg_id, bot)
        if 0 < self._file_owner(cfg) < BASE:
            after = "之後在 Telegram 私訊 bot 打 /web 也能拿網頁的登入連結。（只能私訊 bot；加進群組沒有用。）"
        else:
            after = ("還沒配對擁有者：bot 還不認得你的 Telegram 帳號（陌生人會被擋）。"
                     "重新啟動 SYNOX 後，到設定 → 聊天通道 → Telegram →「配對我的 Telegram 帳號」，照畫面私訊 bot 六個數字。")
        return _json(200, {"ok": True, "bot": bot,
                           "message": f"✅ 存好了：bot @{bot}。重新啟動 SYNOX 後生效（雙擊 Stop.bat，再雙擊桌面的 SYNOX 捷徑）。"
                                      + after})

    def save_discord(self, user, data: dict) -> Resp:
        denied = self._owner_only(user)
        if denied:
            return denied
        from synox.wizard import logic
        _tg, dc = self._probes()
        token = str(data.get("token") or "").strip()
        if not token:
            return _err(400, "要貼上 Discord bot 的 token（Developer Portal 的 Bot 頁）。")
        cfg = logic.read_existing(self.config_path)
        if not cfg:
            return _err(400, "讀不到 config.json，沒有存（重跑 Setup.bat）。")
        d = (cfg.get("channels") or {}).get("discord") if isinstance(cfg.get("channels"), dict) else None
        if isinstance(d, dict) and "bots" in d:
            return _err(400, "config.json 的 channels.discord 已經用 bots 寫法（多個 bot）：網頁不動它，"
                             "請直接改 config.json（或用 python -m synox discord token --bot 名字）。")
        if self.vault is None:
            return _err(400, "保管箱沒有打開，token 沒地方放（python -m synox doctor 看原因）。")
        ok, info = dc.get_me(token)
        if not ok:
            return _err(400, self._scrub(info, token))
        bid = dc.bot_id(token)
        try:
            logic.save_discord_token(self.config_path, cfg, token, vault_opener=lambda _c: self.vault)
        except ValueError as e:
            return _err(400, self._scrub(e, token))
        self._channels_changed.add("discord")
        bot = self._scrub(info, token)
        logging.info("[WEB] %s saved a Discord bot token (bot %s)", user.tg_id, bot)
        invite = dc.invite_url(bid) if bid else ""
        return _json(200, {"ok": True, "bot": bot, "invite": invite,
                           "message": f"✅ 存好了：bot {bot}（token 在保管箱，密文）。⚠ 要重新啟動 SYNOX 才會生效。接下來："
                                      "① 用邀請連結把 bot 加進你也在的（任一個）Discord 伺服器（只是為了能私訊它；bot 只回私訊，不會在伺服器頻道裡回話）；"
                                      "② 配對擁有者：在 SYNOX 資料夾跑 python -m synox discord pair（或重跑 Setup.bat），"
                                      "私訊 bot 畫面上的六個數字（配對前 bot 不認得你的 Discord 帳號）；"
                                      "③ 重新啟動 SYNOX（雙擊 Stop.bat，再雙擊桌面的 SYNOX 捷徑）才會生效。"})

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


class _Server(ThreadingHTTPServer):
    """埠一定要「獨佔」：HTTPServer 預設 allow_reuse_address=True，在 Windows 上 SO_REUSEADDR 會讓第二支程式
    綁上「已經有人在聽」的埠還回報成功（兩支都說在 8830，連線卻進了別支）——登入連結就被送到別的 SYNOX、
    認不得 token。Windows 改用 SO_EXCLUSIVEADDRUSE；其他平台的 SO_REUSEADDR 不會搶別人正在聽的埠，維持原樣。"""

    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if os.name == "nt" and exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


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

    def do_PUT(self):
        self._go("PUT")

    def log_message(self, fmt, *args):
        logging.debug("[WEB] " + fmt, *args)
