"""主機台的手機入口 API（ADR 0026；計畫 K7）。都要登入、POST 要防偽造 token（server.route 先擋過），來源是 web。

| 路由 | 內容 |
|---|---|
| `GET /api/remote` | 狀態：總開關、通道程式（核准了沒）、每個工具（宣告了沒、打開了沒）、現在開著的那一條 |
| `POST /api/remote/open` | `{"name", "code", "minutes"}` → `{"ok", "url", "minutes", "qr"}`（每次都要一組新的碼） |
| `POST /api/remote/close` | 關掉現在那一條 |
| `POST /api/remote/enabled` `{"on"}`、`/allow` `{"name", "on"}`、`/binary/approve` | 要已解鎖（沒解鎖 → 403 `code: "stepup"`，畫面跳輸入框） |

只有擁有者（成員 → 403）。
"""

from __future__ import annotations

from synox.guard import inputs, origin as origin_mod
from synox.web.remote.manager import RemoteError

TEXT = {"owner": "只有擁有者能用手機入口。", "body": "內容格式不對。", "not_found": "沒有這個東西。"}


def route(ui, user, method: str, path: str, body: bytes):
    from synox.web import remote
    from synox.web.server import _json
    manager = remote.of(ui.app)
    if manager is None:
        return _json(404, {"error": TEXT["not_found"]})
    if not ui.is_owner(user):
        return _json(403, {"error": TEXT["owner"], "code": "forbidden"})
    o = origin_mod.current()
    if method == "GET" and path == "/api/remote":
        return _json(200, manager.status(user))
    if method != "POST":
        return _json(404, {"error": TEXT["not_found"]})
    try:
        data = inputs.json_object(body or b"{}", max_bytes=4096, max_depth=2)
    except inputs.Bad:
        return _json(400, {"error": TEXT["body"]})
    try:
        if path == "/api/remote/open":
            name, code = data.get("name"), data.get("code")
            if not isinstance(name, str) or not isinstance(code, str):
                return _json(400, {"error": TEXT["body"]})
            out = manager.open(name, user, code.strip()[:16], origin=o, minutes=data.get("minutes"))
            from synox.guard import qr
            try:
                grid = qr.matrix(out["url"])
            except ValueError:
                grid = None
            return _json(200, {"ok": True, "url": out["url"], "minutes": out["minutes"], "qr": grid})
        if path == "/api/remote/close":
            return _json(200, {"ok": manager.close("owner", by=user.tg_id)})
        if path == "/api/remote/enabled":
            if not isinstance(data.get("on"), bool):
                return _json(400, {"error": TEXT["body"]})
            return _json(200, manager.set_enabled(data["on"], user, o))
        if path == "/api/remote/allow":
            if not isinstance(data.get("name"), str) or not isinstance(data.get("on"), bool):
                return _json(400, {"error": TEXT["body"]})
            return _json(200, manager.allow_tool(data["name"], data["on"], user, o))
        if path == "/api/remote/binary/approve":
            return _json(200, manager.approve_binary(user, o))
    except RemoteError as e:
        status = 403 if e.code in ("stepup", "not_owner", "not_human", "stepup_unset") else 409
        return _json(status, {"error": e.text, "code": e.code})
    return _json(404, {"error": TEXT["not_found"]})
