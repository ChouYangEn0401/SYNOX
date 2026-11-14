"""遠端閘門（ADR 0026 §2–§5；計畫 K7）：通道那一頭唯一碰得到的東西。`handle_raw(method, target, header_items, body)`。

依序：入口已關 → 404；`guard.http.parse`（不合＝固定的拒絕）；次數；
`GET /`（沒有有效的登入）→ SYNOX 自己的進門頁（不是工具的檔）；`/_synox/enter.js|css`；
`POST /_synox/enter {"k", "code"}`：鑰匙（5 分鐘、只能換一次）＋一組**新的**驗證碼 → 一個只給這個瀏覽器的登入
（`__Host-` cookie；整條入口只發這一次）＋一張工具服務的交接票；失敗一律同一個回應；
其他路徑：登入有效（否則 404）→ 路由在白名單（否則 404）→ 標頭只留白名單、Host／Origin 換成工具站認得的 →
在 `Origin("remote", …)` 底下呼叫工具站的 `handle` → 回應拿掉 Set-Cookie、加上 HSTS、noindex 那幾個標頭。
對方送來的路徑、參數、標頭、內容一個字都不記。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Dict, List, Tuple

from synox.guard import http as guard_http, inputs, origin as origin_mod

Resp = Tuple[int, List[Tuple[str, str]], bytes]
STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
COOKIE = "__Host-synox_remote"
FORWARD_HEADERS = ("content-type", "content-length", "accept", "user-agent", "x-synox-app", "sec-fetch-site",
                   "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-user")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; worker-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
REMOTE_HEADERS = [("Strict-Transport-Security", "max-age=31536000"), ("X-Robots-Tag", "noindex, nofollow"),
                  ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer"), ("X-Content-Type-Options", "nosniff"),
                  ("X-Frame-Options", "DENY"), ("Cross-Origin-Opener-Policy", "same-origin"),
                  ("Cross-Origin-Resource-Policy", "same-origin"), ("Content-Security-Policy", CSP)]
ENTER_FILES = {"/_synox/enter.js": ("remote_enter.js", "text/javascript; charset=utf-8"),
               "/_synox/enter.css": ("remote_enter.css", "text/css; charset=utf-8")}
API_ROUTES = [("POST", re.compile(r"^/api/enter$")), ("GET", re.compile(r"^/api/me$")),
              ("GET", re.compile(r"^/api/read/[a-z0-9][a-z0-9_-]{0,31}$")),
              ("POST", re.compile(r"^/api/do/[a-z0-9][a-z0-9_-]{0,31}$")),
              ("POST", re.compile(r"^/api/(alive|leave|close-service)$"))]
ENTER_FAIL = {"ok": False, "error": "進不去：連結或驗證碼不對、過期了，或已經用過了。"}


def digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _cookie_values(headers: Dict[str, str]) -> List[str]:
    out = []
    for part in headers.get("cookie", "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == COOKIE:
            out.append(value)
    return out


class RemoteGate:
    def __init__(self, manager, link=None, app_site=None, *, clock=time.time):
        self.manager, self.link, self.app_site, self.clock = manager, link, app_site, clock

    # ── 出口：每個回應都加的標頭 ─────────────────────────────────────

    def _finish(self, resp: Resp, extra: List[Tuple[str, str]] = ()) -> Resp:
        status, headers, body = resp
        names = {k.lower() for k, _v in REMOTE_HEADERS}
        kept = [(k, v) for k, v in headers if k.lower() not in names and k.lower() != "set-cookie"
                and not k.lower().startswith("access-control-") and k.lower() != "clear-site-data"]
        return status, kept + list(REMOTE_HEADERS) + list(extra), body

    def _reject(self, status: int, code: str = "") -> Resp:
        self.manager.rejected(self.link, code or guard_http.CODES.get(status, "bad_request"))
        return self._finish(guard_http.reply(status, code))

    # ── 入口 ─────────────────────────────────────────────────────────

    def handle_raw(self, method, target, header_items, body) -> Resp:
        link = self.link
        if link is None or link.state == "closed":
            return self._finish(guard_http.reply(404))
        try:
            req = guard_http.parse(method, target, header_items, body, host=link.host)
        except guard_http.Reject as e:
            return self._reject(e.status, e.code)
        entered = self._session_ok(req.headers)
        if not self.manager.rate_ok(link, entered):
            return self._reject(429)
        if req.path in ENTER_FILES and req.method == "GET" and not entered:
            name, ctype = ENTER_FILES[req.path]
            with open(os.path.join(STATIC, name), "rb") as f:
                return self._finish((200, [("Content-Type", ctype)], f.read()))
        if req.path == "/_synox/enter":
            if req.method != "POST":
                return self._reject(404)
            return self._enter(req)
        if not entered:
            if req.path == "/" and req.method == "GET":
                with open(os.path.join(STATIC, "remote_enter.html"), "rb") as f:
                    return self._finish((200, [("Content-Type", "text/html; charset=utf-8")], f.read()))
            return self._reject(404)
        return self._forward(req)

    def _session_ok(self, headers: Dict[str, str]) -> bool:
        link = self.link
        if link.state != "entered" or not link.session_digest:
            return False
        values = _cookie_values(headers)
        if len(values) != 1:
            return False
        ok = hmac.compare_digest(digest(values[0]), link.session_digest)
        ua = hmac.compare_digest(digest(headers.get("user-agent", "")), link.ua_digest or "")
        return ok and ua

    def _fail_page(self) -> Resp:
        return self._finish((403, [("Content-Type", "application/json; charset=utf-8")],
                             json.dumps(ENTER_FAIL, ensure_ascii=False).encode("utf-8")))

    def _enter(self, req) -> Resp:
        """進門。已經有人進門了（這條入口只發一個登入）：一律回固定的失敗、**不計次**——知道網域的外人不能靠亂敲把擁有者踢出去。
        任何意外（例如怪字元的驗證碼）都變成同一個、有計次的失敗，不會變成別的狀態碼。"""
        if self.link.state != "waiting":
            return self._fail_page()
        try:
            return self._enter_checked(req)
        except Exception:
            self.manager.enter_failed(self.link)
            return self._fail_page()

    def _enter_checked(self, req) -> Resp:
        link = self.link
        fail = self._fail_page()
        try:
            data = inputs.json_object(req.body, max_bytes=4096, max_depth=2)
            key, code = data.get("k"), data.get("code")
            if not isinstance(key, str) or not isinstance(code, str):
                raise inputs.Bad("type")
        except inputs.Bad:
            self.manager.enter_failed(link)
            return fail
        now = self.clock()
        if link.state != "waiting" or now > link.entry_deadline or \
                not hmac.compare_digest(digest(key), link.key_digest):
            self.manager.enter_failed(link)
            return fail
        remote = origin_mod.Origin("remote", link.owner, surface="remote:" + link.id)
        r = self.manager.verify_entry(link, code.strip()[:16], remote)
        if not r:
            self.manager.enter_failed(link)
            return fail
        sid = secrets.token_urlsafe(32)
        link.session_digest = digest(sid)
        link.ua_digest = digest(req.headers.get("user-agent", ""))
        link.state = "entered"
        link.key_digest = ""                                   # 鑰匙只能換一次
        link.last_activity = now
        ticket = self.manager.entered(link)
        cookie = f"{COOKIE}={sid}; Secure; HttpOnly; SameSite=Strict; Path=/"
        body = json.dumps({"ok": True, "next": f"/#t={ticket}"}).encode("utf-8")
        return self._finish((200, [("Content-Type", "application/json; charset=utf-8")], body),
                            [("Set-Cookie", cookie)])

    def _forward(self, req) -> Resp:
        link = self.link
        if req.path.startswith("/api/"):
            if not any(m == req.method and rx.match(req.path) for m, rx in API_ROUTES):
                return self._reject(404)
        elif req.method != "GET":
            return self._reject(404)
        site = self.app_site
        if site is None:
            return self._reject(404)
        headers = {k: v for k, v in req.headers.items() if k in FORWARD_HEADERS}
        headers["host"] = site.host_header
        if "origin" in req.headers:
            headers["origin"] = "http://" + site.host_header
        from urllib.parse import urlencode
        target = req.path + ("?" + urlencode(req.query) if req.query else "")
        remote = origin_mod.Origin("remote", link.owner, surface="remote:" + link.id)
        with origin_mod.using(remote):
            resp = site.handle(req.method, target, headers, req.body)
        link.last_activity = self.clock()
        link.warned_idle = False
        self.manager.used(link)
        return self._finish(resp)
