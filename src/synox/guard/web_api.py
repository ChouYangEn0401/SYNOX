"""主機台的驗證器 API（ADR 0025 §5.2–5.3；計畫 K5）。都要登入、POST 要防偽造 token（server.route 先擋過），來源是 web。

    GET  /api/stepup                 狀態＋can_enroll_here、why_not
    POST /api/stepup/begin           → {"secret": "ABCD EFGH …", "uri", "qr": ["0101…"] 或 null, "expires_in": 600}
    POST /api/stepup/confirm         {"code", "protect": true} → {"ok": true, "recovery": [...]}（只有這一次）
    POST /api/stepup/unlock          {"code"} → {"ok", "left_s"}；錯 → 403 {"error", "code"}
    POST /api/stepup/lock            → {"ok", "left_s": 0}
    POST /api/stepup/protect         {"on": bool}
    POST /api/stepup/recovery        {"code"} → {"recovery": [...]}
    POST /api/stepup/disable         {"code"}（備用碼只在本機的請求收）

「本機的請求」：Host 是 127.0.0.1:<埠>／localhost:<埠>，而且沒有任何代理標頭（Forwarded、X-Forwarded-*、Via）。
金鑰只給本機的請求；伺服器版的成員另外准：對外網址是 https、這個登入不到 10 分鐘。擁有者一律本機。
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from synox.guard import inputs, qr
from synox.guard.stepup import Refused, group_secret

FRESH_LOGIN_S = 600
TEXT = {
    "not_here": "請在跑 SYNOX 的那台電腦上設定（打開 SYNOX 網頁 → 設定 → 🔐 安全）。",
    "member_remote": "從外面設定要用 https 的網址，而且要剛登入（10 分鐘內）；請重新用 /web 拿登入連結再來。",
    "bad_body": "內容格式不對。",
    "no_vault": "保管箱打不開，現在不能設定手機驗證器（先看 doctor 的說明）。",
    "unknown": "沒有這個動作。",
}
PROXY_HEADERS = ("forwarded", "via")


LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def is_local(ui, headers) -> bool:
    """本機的請求：連線的對方真的是 loopback、Host 是 127.0.0.1／localhost、沒有任何代理標頭；
    而且不是「對外網址＋反向代理」或容器（那兩種情況代理或埠轉發的連線看起來也是 loopback）。"""
    from synox.web.server import current_peer, in_container
    if current_peer() not in LOOPBACK:
        return False
    if str((getattr(ui.config, "web", {}) or {}).get("public_url") or "").strip() or in_container():
        return False
    host = str(headers.get("host", "")).lower()
    if host not in (f"127.0.0.1:{ui.port}", f"localhost:{ui.port}"):
        return False
    return not any(k in PROXY_HEADERS or k.startswith("x-forwarded-") for k in headers)


def enroll_here(ui, user, session, headers) -> tuple:
    """(可不可以在這裡看金鑰, 不行的話為什麼)。"""
    if is_local(ui, headers):
        return True, ""
    if ui.is_owner(user):
        return False, TEXT["not_here"]
    public = str((getattr(ui.config, "web", {}) or {}).get("public_url") or "").strip().lower()
    created = float(getattr(session, "created", 0) or 0)
    if ui.server_mode and public.startswith("https://") and time.time() - created < FRESH_LOGIN_S:
        return True, ""
    return False, TEXT["member_remote"] if ui.server_mode else TEXT["not_here"]


def _body(body: bytes) -> Optional[dict]:
    try:
        return inputs.json_object(body or b"{}", max_bytes=4096)
    except inputs.Bad:
        return None


def _code(data: dict) -> str:
    value = data.get("code", "")
    if not isinstance(value, str):
        return ""
    try:
        return inputs.text(value.strip(), max=32)
    except inputs.Bad:
        return ""


def route(ui, user, session, method: str, path: str, headers, body: bytes):
    from synox import guard
    from synox.guard import origin as origin_mod
    from synox.web.server import _err, _json

    g = guard.of(ui.app)
    hub = g.stepup if g is not None else None
    if hub is None:
        return _err(503, TEXT["no_vault"])
    uid = int(user.tg_id)
    o = origin_mod.current()
    local = is_local(ui, headers)

    def refused(r, status=403):
        return _json(status, {"error": r.text, "code": r.code})

    if method == "GET" and path == "/api/stepup":
        ok, why = enroll_here(ui, user, session, headers)
        return _json(200, {**hub.status(uid, o), "can_enroll_here": ok, "why_not": why})
    if method != "POST":
        return _err(404, TEXT["unknown"])
    data = _body(body)
    if data is None:
        return _err(400, TEXT["bad_body"])
    action = path[len("/api/stepup/"):] if path.startswith("/api/stepup/") else ""
    if action == "begin":
        ok, why = enroll_here(ui, user, session, headers)
        if not ok:
            return _json(403, {"error": why, "code": "not_here"})
        if ui.app.extras.get("vault") is None:
            return _err(503, TEXT["no_vault"])
        try:
            started = hub.begin(uid)
        except ValueError:
            return _json(409, {"error": "已經設定過手機驗證器了。", "code": "already"})
        try:
            grid = qr.matrix(started["uri"])
        except ValueError:
            grid = None
        return _json(200, {"secret": group_secret(started["secret"]), "uri": started["uri"], "qr": grid,
                           "expires_in": started["expires_in"]})
    if action == "confirm":
        try:
            codes = hub.confirm(uid, _code(data))
        except Refused as e:
            return refused(e.result)
        if data.get("protect", True) is True:
            hub.set_protect(uid, True, origin=o)
        logging.info("[STEPUP] %s enrolled from the web", uid)
        return _json(200, {"ok": True, "recovery": codes})
    if action == "unlock":
        r = hub.unlock(uid, _code(data), origin=o, allow_recovery=local)
        return _json(200, {"ok": True, "left_s": hub.remaining(uid, o)}) if r.ok else refused(r)
    if action == "lock":
        hub.lock(uid, o)
        return _json(200, {"ok": True, "left_s": 0})
    if action == "protect":
        on = data.get("on")
        if not isinstance(on, bool):
            return _err(400, TEXT["bad_body"])
        r = hub.set_protect(uid, on, origin=o)
        return _json(200, {"ok": True, "protect_danger": hub.protects_danger(uid)}) if r.ok else refused(r)
    if action == "recovery":
        try:
            codes = hub.new_recovery(uid, _code(data), origin=o)
        except Refused as e:
            return refused(e.result)
        return _json(200, {"ok": True, "recovery": codes})
    if action == "disable":
        r = hub.disable(uid, _code(data), origin=o, allow_recovery=local)
        return _json(200, {"ok": True}) if r.ok else refused(r)
    return _err(404, TEXT["unknown"])
