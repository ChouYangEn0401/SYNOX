"""一個工具的站（計畫 C4–C6.1、C11；ADR 0024 第三版）：`AppSite.handle(method, target, headers, body) -> (status, headers, body)`。

- **不讀任何 cookie、不發任何 Set-Cookie**。登入是一個 token：`POST /api/enter` 用交接票換，之後放在 `X-SYNOX-App` 標頭
  （匯出那一條放在表單欄位 `t`）。每個請求都重新查登入：token 的雜湊、沒過期、上一層還 alive、這個人現在仍看得到這個工具。
- Host 一定是 `127.0.0.2:<埠>`（`site.host_header`；同程序直接呼叫的手機入口閘門會換成這一個，ADR 0026 對接 d）。
- 讀、動作、匯出都在 `guard.origin` 底下跑：外面沒設＝web；已經是 remote（手機入口）就沿用（對接 e）。
  來源是 remote：匯出 → 403 `remote_no_export`、危險動作 → 403 `remote_no_danger`，工具的函式不會被叫到。
- 錯誤一律 `{"ok": false, "code", "error"}`；別的例外的訊息永遠不出現在回應、log、稽核（log 用 safe_trace）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from isdtelekit.core.registry import TYPED

from synox.guard import inputs, origin as origin_mod
from synox.web.apps.audit import safe_trace
from synox.web.apps.sessions import AppSessions

Resp = Tuple[int, List[Tuple[str, str]], bytes]
MAX_JSON = 64 * 1024
MAX_EXPORT = 20 * 1024 * 1024
ALIVE_EVERY_S = 60
EXPORT_TYPES = ("text/csv; charset=utf-8",)
STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; worker-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = [("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
                    ("Cache-Control", "no-store"), ("X-Frame-Options", "DENY"),
                    ("Cross-Origin-Opener-Policy", "same-origin"), ("Cross-Origin-Resource-Policy", "same-origin"),
                    ("Content-Security-Policy", CSP)]
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".json": "application/json; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2"}
TEXT = {
    "forbidden_page": "forbidden",
    "login": "請從 SYNOX 再打開一次。",
    "origin": "來源不對（不是從這個工具自己的畫面送出的）。",
    "forbidden": "你不能做這個動作。",
    "not_found": "沒有這個東西。",
    "invalid": "有欄位不對。",
    "required": "這一欄一定要填",
    "confirm": "這個動作要你確認",
    "button": "確定",
    "too_large": "送來的東西太大。",
    "error": "出錯了：{name}",
    "owner_only": "只有擁有者能關這個服務。",
    "export_encrypted_only": "這台 SYNOX 是多人共用的，只能匯出加密的檔；這個功能還沒做好。",
    "export_confirm": "匯出的檔案沒有加密，打得開這個檔的人都看得到內容。存在你放心的地方，用完就刪。",
    "export_button": "下載",
    "remote_no_export": "從手機不能匯出：檔案會落在手機上。回到電腦再匯出。",
    "remote_no_danger": "這個動作要回到電腦或 Telegram 做。",
    "body": "內容格式不對（要是 JSON 物件）。",
}


class AppsError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(code)
        self.code, self.message, self.status = code, message, int(status)


def load_snapshot(spec, locked_files: Dict[str, str]) -> Dict[str, bytes]:
    """把 root 底下的檔讀進記憶體；有鎖就逐檔對 SHA-256，不符（或鎖裡沒有這個檔）丟 AppsError("tampered")。"""
    out: Dict[str, bytes] = {}
    folder = spec.pack.manifest.folder
    for rel in spec.files:
        with open(os.path.join(folder, *rel.split("/")), "rb") as f:
            data = f.read()
        if locked_files:
            want = locked_files.get(rel)
            if want is None or hashlib.sha256(data).hexdigest() != want:
                raise AppsError("tampered", f"畫面的檔 {rel} 跟安裝時不一樣，先不開。重新安裝或重新核准這個工具。", 409)
        out[rel] = data
    return out


def _json(status: int, data) -> Resp:
    return status, [("Content-Type", "application/json; charset=utf-8")], json.dumps(data, ensure_ascii=False).encode()


def _fail(status: int, code: str, error: str, **extra) -> Resp:
    return _json(status, {"ok": False, "code": code, "error": error, **extra})


class AppSite:
    def __init__(self, manager, spec, port: int, *, clock=time.time, console_url: str = ""):
        self.manager, self.spec, self.port, self.clock = manager, spec, int(port), clock
        self.host_header = f"127.0.0.2:{self.port}"
        self.sessions = AppSessions(clock)
        self.snapshot = load_snapshot(spec, dict(getattr(spec.pack, "locked_files", {}) or {}))
        self.console_url = console_url
        self._cleared = False
        self._mu = threading.Lock()
        self._denied: Dict[str, float] = {}

    # ── 入口 ─────────────────────────────────────────────────────────

    def handle(self, method: str, target: str, headers, body: bytes = b"") -> Resp:
        items = headers.items() if hasattr(headers, "items") else headers
        h = {str(k).lower(): str(v) for k, v in items}
        try:
            status, extra, payload = self._route(str(method or "").upper(), str(target or ""), h, body or b"")
        except Exception as e:                     # 最後一道網：不讓任何例外的訊息出去
            logging.error("[APPS] %s request failed: %s", self.spec.name, safe_trace(e))
            status, extra, payload = _fail(500, "error", TEXT["error"].format(name=type(e).__name__))
        names = {k.lower() for k, _v in extra}
        out = [(k, v) for k, v in extra if not k.lower().startswith("access-control-")]
        out += [(k, v) for k, v in SECURITY_HEADERS if k.lower() not in names]
        return status, out, payload

    def _deny(self, reason: str, code: str = "") -> None:
        now = self.clock()
        with self._mu:
            if now - self._denied.get(reason, -1e9) < 60:
                return
            self._denied[reason] = now
        self.manager.audit.write("denied", self.spec.name, via=self._via(), ok=False, code=code, reason=reason,
                                 port=self.port)

    def _via(self) -> str:
        return "remote" if origin_mod.current().kind == "remote" else "app"

    def _route(self, method: str, target: str, h: Dict[str, str], body: bytes) -> Resp:
        if h.get("host", "") != self.host_header:
            self._deny("host")
            return 403, [("Content-Type", "text/plain; charset=utf-8")], TEXT["forbidden_page"].encode()
        if any(k in ("forwarded", "via", "service-worker") or k.startswith("x-forwarded-") for k in h):
            self._deny("proxy")
            return 403, [("Content-Type", "text/plain; charset=utf-8")], TEXT["forbidden_page"].encode()
        if method not in ("GET", "POST"):
            return 405, [("Content-Type", "text/plain; charset=utf-8"), ("Allow", "GET, POST")], b"method"
        parts = urlsplit(target)
        path = parts.path
        if path.startswith("/api/"):
            return self._api(method, path, parse_qs(parts.query), h, body)
        if method != "GET":
            return _fail(404, "not_found", TEXT["not_found"])
        return self._static(path)

    # ── 靜態（公開：就是工具附的檔，沒有任何人的資料）──────────────────────

    def _static(self, path: str) -> Resp:
        if path == "/":
            extra = [("Content-Type", TYPES[".html"])]
            with self._mu:
                if not self._cleared:
                    self._cleared = True
                    extra.append(("Clear-Site-Data", '"storage"'))
            return 200, extra, self.snapshot[self.spec.entry]
        if path in ("/_synox/kit.js", "/_synox/kit.css"):
            name = "appkit.js" if path.endswith(".js") else "appkit.css"
            with open(os.path.join(STATIC, name), "rb") as f:
                data = f.read()
            if name == "appkit.js":
                data = data.replace(b"/*{{CONSOLE_URL}}*/", json.dumps(self.console_url).encode(), 1)
            return 200, [("Content-Type", TYPES[os.path.splitext(name)[1]])], data
        try:
            rel = inputs.rel_path(path)
        except inputs.Bad:
            return _fail(404, "not_found", TEXT["not_found"])
        key = f"{self.spec.root}/{rel}"
        data = self.snapshot.get(key)
        ctype = TYPES.get(os.path.splitext(key)[1].lower())
        if data is None or ctype is None:
            return _fail(404, "not_found", TEXT["not_found"])
        return 200, [("Content-Type", ctype)], data

    # ── /api/ ───────────────────────────────────────────────────────

    def _origin_ok(self, h: Dict[str, str]) -> bool:
        site = h.get("sec-fetch-site")
        if site is not None and site != "same-origin":
            return False
        origin = h.get("origin")
        if origin is None:
            return True
        if origin == "null":
            return site == "same-origin"
        return urlsplit(origin).netloc == self.host_header

    def _api(self, method: str, path: str, query, h: Dict[str, str], body: bytes) -> Resp:
        if not self._origin_ok(h):
            self._deny("origin", "origin")
            return _fail(403, "origin", TEXT["origin"])
        if path.startswith("/api/export/"):
            return self._export(method, path[len("/api/export/"):], h, body) if method == "POST" else \
                _fail(404, "not_found", TEXT["not_found"])
        data: dict = {}
        if method == "POST":
            if not h.get("content-type", "").lower().startswith("application/json"):
                return _fail(400, "invalid", TEXT["body"])
            if len(body) > MAX_JSON:
                return _fail(413, "too_large", TEXT["too_large"])
            try:
                data = inputs.json_object(body or b"{}", max_bytes=MAX_JSON, max_depth=4)
            except inputs.Bad as bad:
                return _fail(400, "invalid", bad.text)
        if path == "/api/enter" and method == "POST":
            return self._enter(data)
        token = h.get("x-synox-app", "")
        session, user = self._login(token)
        if session is None:
            return _fail(401, "login", TEXT["login"])
        with self._as(user, session):
            return self._api_logged_in(method, path, query, data, token, session, user)

    def _as(self, user, session):
        """這個請求的來源：外面已經是 remote（手機入口）就沿用；不然是 web（上一層的那個主機台登入）。"""
        current = origin_mod.current()
        if current.kind == "remote":
            return origin_mod.using(current)
        surface = getattr(session.parent, "surface", "") or "web:app"
        return origin_mod.using(origin_mod.Origin("web", int(user.tg_id), surface=surface))

    def _user(self, tg_id: int):
        return self.manager.app.users.get_or_create(int(tg_id))

    def _visible(self, user) -> bool:
        group = self.manager.app.registry.node(self.spec.group)
        return group is not None and self.manager.app.registry.visible(user, group)

    def _login(self, token: str):
        session = self.sessions.get(token)
        if session is None:
            return None, None
        user = self._user(session.tg_id)
        alive = getattr(session.parent, "alive", None)
        if session.expires <= self.clock() or not callable(alive) or not alive() or not self._visible(user):
            self.sessions.drop(token)
            return None, None
        return session, user

    def _enter(self, data: dict) -> Resp:
        found = self.manager.redeem_ticket(self.spec.name, self.port, data.get("ticket"))
        if found is None:
            self.manager.audit.write("enter", self.spec.name, via=self._via(), ok=False, code="login", reason="ticket",
                                     port=self.port)
            return _fail(401, "login", TEXT["login"])
        tg_id, parent = found
        user = self._user(tg_id)
        alive = getattr(parent, "alive", None)
        if not callable(alive) or not alive() or not self._visible(user):
            return _fail(401, "login", TEXT["login"])
        token, session = self.sessions.create(tg_id, parent)
        self.manager.touch(self.spec.name)
        self.manager.audit.write("enter", self.spec.name, by=tg_id, via=self._via(), port=self.port)
        with self._as(user, session):
            return _json(200, {"ok": True, "token": token, "me": self.me(user)})

    def _api_logged_in(self, method, path, query, data, token, session, user) -> Resp:
        name = self.spec.name
        if path == "/api/me" and method == "GET":
            self.manager.touch(name)
            return _json(200, self.me(user))
        m = re.match(r"^/api/read/([a-z0-9][a-z0-9_-]{0,31})$", path)
        if m and method == "GET":
            self.manager.touch(name)
            return self._read(m.group(1), user, query)
        m = re.match(r"^/api/do/([a-z0-9][a-z0-9_-]{0,31})$", path)
        if m and method == "POST":
            self.manager.touch(name)
            return self._do(m.group(1), user, data)
        if method != "POST":
            return _fail(404, "not_found", TEXT["not_found"])
        if path == "/api/alive":
            if session.alive_ok(self.clock(), ALIVE_EVERY_S):
                self.manager.touch(name)
            return _json(200, {"ok": True})
        if path == "/api/keep":
            self.manager.keep(name, by=user.tg_id, via=self._via())
            return _json(200, {"ok": True})
        if path == "/api/leave":
            self.sessions.drop(token)
            self.manager.audit.write("leave", name, by=user.tg_id, via=self._via(), port=self.port)
            return _json(200, {"ok": True})
        if path == "/api/close-service":
            if not self.manager.app.registry.is_owner(user):
                return _fail(403, "forbidden", TEXT["owner_only"])
            via = self._via()
            self.manager.app.tasks.run(lambda: self.manager.stop(name, by=user.tg_id, via=via, reason="owner"),
                                       name="app-close")
            return _json(200, {"ok": True})
        return _fail(404, "not_found", TEXT["not_found"])

    # ── me、讀、動作、匯出 ───────────────────────────────────────────

    def me(self, user) -> dict:
        from synox.web import toolpage
        registry = self.manager.app.registry
        spec = self.spec
        meta = toolpage_meta(spec)
        actions = {}
        for n, eff in spec.actions.items():
            node = registry.node(f"{spec.group}.{n}")
            fields = [toolpage.field_info(f, meta.get("kinds", {}), meta.get("helps", {}))
                      for f in getattr(node, "fields", ()) or () if not getattr(f, "fresh_code", False)]
            actions[n] = {"effect": eff, "summary": getattr(node, "summary", "") or "", "fields": fields}
        server = getattr(self.manager.config, "mode", "personal") == "server"
        remote = origin_mod.current().kind == "remote"
        exports = {}
        for n in spec.exports:
            if remote:
                exports[n] = {"available": False, "reason": TEXT["remote_no_export"]}
            elif server:
                exports[n] = {"available": False, "reason": TEXT["export_encrypted_only"]}
            else:
                exports[n] = {"available": True, "reason": ""}
        policy = self.manager.policy_of(spec.name)
        out = {"ok": True,
               "user": {"id": int(user.tg_id), "name": getattr(user, "username", "") or str(user.tg_id),
                        "owner": registry.is_owner(user)},
               "app": {"name": spec.name, "title": spec.title, "app_title": spec.app_title, "version": spec.version},
               "reads": list(spec.reads), "actions": actions, "exports": exports, "console_url": self.console_url,
               "policy": {k: policy[k] for k in ("mode", "suggest_min", "close_min", "text")},
               "alive_every_s": ALIVE_EVERY_S, "remote": remote}
        if remote and self.manager.remote_until is not None:
            out["remote_until"] = self.manager.remote_until(spec.name)
        return out

    def _read(self, name: str, user, query) -> Resp:
        fn = getattr(self.spec.pack, "app_reads", {}).get(name)
        if name not in self.spec.reads or fn is None:
            return _fail(404, "not_found", TEXT["not_found"])
        params = {str(k): str(v[0]) for k, v in (query or {}).items() if v}
        try:
            inputs.values(list(params), params, max=1000)
            return _json(200, {"ok": True, "data": fn(user, params)})
        except inputs.Bad as bad:
            return _fail(400, "invalid", bad.text)
        except Exception as e:
            return self._tool_error(e, name, "read")

    def _tool_error(self, e: Exception, name: str, what: str) -> Resp:
        from synox.packs import kit
        if isinstance(e, kit.AppError):
            return _fail(e.status if 400 <= e.status < 600 else 409, e.code if e.code else "refused", e.message)
        logging.error("[APPS] %s %s %s failed: %s", self.spec.name, what, name, safe_trace(e))
        self.manager.audit.write("error", self.spec.name, via=self._via(), action=name, ok=False, code="error")
        return _fail(500, "error", TEXT["error"].format(name=type(e).__name__))

    def _do(self, name: str, user, data: dict) -> Resp:
        from synox.packs import kit
        spec = self.spec
        fn = getattr(spec.pack, "app_actions", {}).get(name)
        if name not in spec.actions or fn is None:
            return _fail(404, "not_found", TEXT["not_found"])
        effect = spec.actions[name]
        confirmed = data.get("confirmed") is True
        via = self._via()

        def audit(ok: bool, code: str = "") -> None:
            self.manager.audit.write("action", spec.name, by=user.tg_id, via=via, action=name, effect=effect, ok=ok,
                                     code=code, confirmed=confirmed, port=self.port)

        if via == "remote" and effect == "danger":
            audit(False, "remote_no_danger")
            return _fail(403, "remote_no_danger", TEXT["remote_no_danger"])
        node = self.manager.app.registry.node(f"{spec.group}.{name}")
        decision = self.manager.app.registry.authorize(user, node, TYPED, user.tg_id)
        if not decision.allowed:
            audit(False, "forbidden")
            message = decision.text or (decision.message if decision.reason != "owner_only" else "") or TEXT["forbidden"]
            return _fail(403, "forbidden", message)
        values = data.get("values", {})
        if not isinstance(values, dict):
            audit(False, "invalid")
            return _fail(400, "invalid", TEXT["invalid"], fields={})
        clean, missing, errors = kit.check_values(node.fields, values)
        if errors or missing:
            fields = {} if not clean and errors else kit.field_errors(node.fields, values)
            for f in missing:
                fields[f.name] = TEXT["required"]
            audit(False, "invalid")
            return _fail(400, "invalid", errors[0] if errors else TEXT["invalid"], fields=fields)
        if effect == "danger" and not confirmed:
            describe = getattr(spec.pack, "app_describe", {}).get(name)
            try:
                text = describe(user, clean) if describe else (getattr(node, "summary", "") or name)
            except Exception as e:
                logging.error("[APPS] %s describe %s failed: %s", spec.name, name, safe_trace(e))
                text = getattr(node, "summary", "") or name
            return _fail(409, "confirm", TEXT["confirm"], confirm={"text": str(text)[:300], "button": TEXT["button"]})
        try:
            result = fn(user, clean)
        except Exception as e:
            audit(False, "refused" if isinstance(e, kit.AppError) else "error")
            return self._tool_error(e, name, "action")
        if not isinstance(result, dict):
            audit(False, "error")
            logging.error("[APPS] %s action %s returned %s, not a dict", spec.name, name, type(result).__name__)
            return _fail(500, "error", TEXT["error"].format(name=type(result).__name__))
        audit(True)
        return _json(200, {"ok": True, "data": result})

    def _export(self, method: str, name: str, h: Dict[str, str], body: bytes) -> Resp:
        from synox.packs import kit
        if len(body) > MAX_JSON:
            return _fail(413, "too_large", TEXT["too_large"])
        try:
            form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "strict"), keep_blank_values=True).items()}
        except UnicodeDecodeError:
            return _fail(400, "invalid", TEXT["body"])
        token = form.pop("t", "")
        session, user = self._login(token)
        if session is None:
            return _fail(401, "login", TEXT["login"])
        spec = self.spec
        with self._as(user, session):
            via = self._via()
            confirmed = form.pop("confirmed", "") == "1"
            fn = getattr(spec.pack, "app_exports", {}).get(name)
            if name not in spec.exports or fn is None:
                return _fail(404, "not_found", TEXT["not_found"])
            self.manager.touch(spec.name)

            def audit(ok: bool, code: str = "", size: int = 0) -> None:
                self.manager.audit.write("export", spec.name, by=user.tg_id, via=via, action=name, ok=ok, code=code,
                                         confirmed=confirmed, bytes=size, port=self.port)

            if via == "remote":
                audit(False, "remote_no_export")
                return _fail(403, "remote_no_export", TEXT["remote_no_export"])
            if getattr(self.manager.config, "mode", "personal") == "server":
                audit(False, "export_encrypted_only")
                return _fail(403, "export_encrypted_only", TEXT["export_encrypted_only"])
            if not confirmed:
                return _fail(409, "confirm", TEXT["confirm"],
                             confirm={"text": TEXT["export_confirm"], "button": TEXT["export_button"]})
            try:
                inputs.values(list(form), form, max=1000)
                result = fn(user, form)
            except inputs.Bad as bad:
                return _fail(400, "invalid", bad.text)
            except Exception as e:
                audit(False, "refused" if isinstance(e, kit.AppError) else "error")
                return self._tool_error(e, name, "export")
            ok = isinstance(result, kit.Download) and isinstance(result.data, (bytes, bytearray)) \
                and result.content_type in EXPORT_TYPES and len(result.data) <= MAX_EXPORT
            if not ok:
                audit(False, "error")
                logging.error("[APPS] %s export %s returned an unusable download", spec.name, name)
                return _fail(500, "error", TEXT["error"].format(name=type(result).__name__))
            filename = clean_filename(result.filename)
            audit(True, size=len(result.data))
            return 200, [("Content-Type", result.content_type),
                         ("Content-Disposition", f'attachment; filename="{filename}"')], bytes(result.data)


def clean_filename(name) -> str:
    """只留英數與 -_.（其他換成 _）、最多 80 字、一定要有副檔名。"""
    text = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(str(name or "").replace("\\", "/")))
    text = text.lstrip(".") or "export"
    if "." not in text:
        text += ".csv"
    stem, ext = os.path.splitext(text)
    return (stem[:80 - len(ext)] + ext)[:80]


def toolpage_meta(spec) -> dict:
    """pack.json 的 commands 給的欄位型別與說明（kind=python 沒有：回空的）。"""
    return {}
