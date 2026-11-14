"""主機台這一側的工具服務（計畫 C7）：`/api/apps…` 與 `POST /apps/<名>/open`（交接）。照主機台的規矩：要登入、非 GET 要 CSRF。

| 路由 | 誰 |
|---|---|
| `GET /api/apps` | 登入的人（成員只看得到自己看得到的工具；`can_manage` 只有擁有者是 true） |
| `POST /api/apps/<名>/start`、`/stop`、`/keep`、`/policy` | 擁有者 |
| `POST /api/apps/stop-all`、`GET /api/apps/log?limit=` | 擁有者 |

`POST /apps/<名>/open` 是一個 `target="_blank"` 的表單送出（不在 /api/ 底下）：要有效的主機台登入、表單欄位 `csrf`、來源判斷照 login_post；
服務要開著（**打開不會順便把服務開起來**）→ 303 到 `http://127.0.0.2:<埠>/#t=<票>`。票不經過主機台的 JS、不放在任何回應的內容裡。
"""

from __future__ import annotations

import re
from typing import Dict, Optional
from urllib.parse import parse_qs, urlsplit

from synox.web.apps.site import AppsError

NAME = r"([a-z][a-z0-9_-]{0,31})"
TEXT = {
    "owner": "只有擁有者能開關工具服務。",
    "not_on_title": "這個工具的服務沒有開",
    "not_on": "要先在 SYNOX 的工具頁按「開啟」，再按「打開」。",
    "csrf": "這個按鈕過期了，重新整理工具頁再按一次。",
    "origin": "來源不對（不是從 SYNOX 自己的頁面送出的）。",
    "login": "請先登入 SYNOX。",
    "not_found": "沒有這個東西。",
    "body": "內容格式不對。",
}


def _err(status: int, code: str, message: str):
    from synox.web.server import _json
    return _json(status, {"ok": False, "code": code, "error": message})


def route(ui, user, method: str, path: str, data: Optional[dict], query=None):
    from synox.web.server import _json
    manager = getattr(ui, "apps", None)
    if manager is None:
        return _err(404, "not_found", TEXT["not_found"])
    owner = ui.is_owner(user)
    if method == "GET" and path == "/api/apps":
        return _json(200, manager.views(user))
    if method == "GET" and path == "/api/apps/log":
        if not owner:
            return _err(403, "forbidden", TEXT["owner"])
        try:
            limit = int(((query or {}).get("limit") or ["50"])[0])
        except ValueError:
            limit = 50
        return _json(200, {"events": manager.audit.tail(max(1, min(limit, 200)))})
    if method != "POST":
        return _err(404, "not_found", TEXT["not_found"])
    if not owner:
        return _err(403, "forbidden", TEXT["owner"])
    if not isinstance(data, dict):
        return _err(400, "invalid", TEXT["body"])
    if path == "/api/apps/stop-all":
        return _json(200, {"ok": True, "stopped": manager.stop_all(by=user.tg_id, via="web", reason="owner")})
    m = re.match(r"^/api/apps/" + NAME + r"/(start|stop|keep|policy)$", path)
    if not m:
        return _err(404, "not_found", TEXT["not_found"])
    name, action = m.group(1), m.group(2)
    try:
        if action == "start":
            if data.get("explained") is True:
                manager.mark_explained()
            view = manager.start(name, by=user, via="web")
        elif action == "stop":
            manager.stop(name, by=user.tg_id, via="web", reason="owner")
            view = manager.view(name)
        elif action == "keep":
            if name not in manager.specs():
                raise AppsError("not_found", TEXT["not_found"], 404)
            view = manager.keep(name, by=user.tg_id, via="web")
        else:
            view = manager.set_policy(name, data, by=user)
    except AppsError as e:
        return _err(e.status, e.code, e.message)
    return _json(200, {"ok": True, "app": view})


def _form(body: bytes) -> Dict[str, str]:
    try:
        return {k: v[0] for k, v in parse_qs((body or b"").decode("utf-8", "strict")).items()}
    except UnicodeDecodeError:
        return {}


def origin_problem(headers: Dict[str, str]) -> str:
    """跟 login_post 同一套：Sec-Fetch-Site 有值就要 same-origin；Origin 的 netloc 要等於 Host；Origin: null 只在 same-origin 時收。"""
    site = headers.get("sec-fetch-site")
    if site is not None and site != "same-origin":
        return TEXT["origin"]
    origin = headers.get("origin")
    if origin is None:
        return ""
    if origin == "null":
        return "" if site == "same-origin" else TEXT["origin"]
    return "" if urlsplit(origin).netloc == headers.get("host", "") else TEXT["origin"]


def open_handoff(ui, session, name: str, headers: Dict[str, str], body: bytes):
    from synox.web.server import BASE_HEADERS, _page, web_origin
    from synox.web.apps.sessions import ConsoleParent
    if session is None:
        return _page(401, TEXT["login"], TEXT["login"])
    if origin_problem(headers):
        return _page(403, TEXT["origin"], TEXT["origin"])
    if not session.csrf_ok(_form(body).get("csrf")):
        return _page(403, TEXT["csrf"], TEXT["csrf"])
    manager = getattr(ui, "apps", None)
    user = ui.app.users.get_or_create(session.tg_id)
    pack = next((p for p in ui.app.extras.get("synox_packs", []) if p.name == name), None)
    group = ui.app.registry.node(pack.manifest.group) if pack is not None else None
    visible = group is not None and ui.app.registry.visible(user, group)
    port = manager.port_of(name) if manager is not None else 0
    key = ui.session_key(headers)
    if not visible or not port or not key:
        return _page(200, TEXT["not_on_title"], TEXT["not_on"])
    try:
        ticket = manager.issue_ticket(name, user.tg_id, ConsoleParent(ui, key, web_origin(session).surface))
    except AppsError:
        return _page(200, TEXT["not_on_title"], TEXT["not_on"])
    manager.audit.write("handoff", name, by=user.tg_id, via="web", port=port)
    # BASE_HEADERS 已經有 Referrer-Policy: no-referrer 與 Cache-Control: no-store
    return 303, list(BASE_HEADERS) + [("Location", f"http://127.0.0.2:{port}/#t={ticket}")], b""
