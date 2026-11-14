"""
網頁的 🔔 與鬧鐘（docs/notifications.md）。每個登入的人只看得到自己的。

| 方法與路徑 | 做什麼 |
|---|---|
| `GET /api/notifications?since=<rev>` | rev 之後變了的通知、沒讀幾則、下一個鬧鐘 |
| `POST /api/notifications/read` `{"id"}`（沒給 id＝全部已讀） | 知道了／全部已讀 |
| `POST /api/notifications/<id>/snooze` | 5 分鐘後再提醒（加一個只響一次的提醒） |
| `GET/POST /api/notifications/prefs` `{"off": {kind: [channel]}}` | 哪一類送到哪裡 |
| `GET /api/alarms` | 接下來的鬧鐘、會在哪裡響、可能漏掉的原因 |
| `POST /api/alarms/<id>/delete` | 刪掉一個鬧鐘 |
| `POST /api/alarms/test` | 試響一下（每個接上的地方都送一次） |

工具畫面的「現在關掉」「再給我 N 分鐘」直接用 /api/apps/<名>/stop、/keep（擁有者、手機驗證規則照舊）。
"""

from __future__ import annotations

import json
import re

from synox import notify
from synox.notify import alarms
from synox.notify.hub import T


def _resp(status: int, data):
    from synox.web.server import _json
    return _json(status, data)


def _err(status: int, text: str):
    from synox.web.server import _err as err
    return err(status, text)


def _body(body: bytes):
    try:
        data = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def can_alarm(ui, user) -> bool:
    node = ui.app.registry.node("remind.add")
    return node is not None and ui.app.registry.authorize(user, node, "typed", user.tg_id).allowed


def _visible(items):
    return [it for it in items if not (it.get("data") or {}).get("hidden")]


def route(ui, user, method: str, path: str, body: bytes, query=None):
    hub = notify.of(ui.app)
    if hub is None:
        return _err(503, "通知沒有裝上。")
    uid = user.tg_id
    if method == "GET":
        if path == "/api/notifications":
            try:
                since = int(((query or {}).get("since") or ["0"])[0])
            except ValueError:
                since = 0
            got = hub.store.since(uid, since)
            items = _visible(got["items"])
            out = {"rev": got["rev"], "unread": sum(1 for it in _visible(hub.store.since(uid, 0)["items"])
                                                   if not it.get("read")),
                   "items": items, "next": None}
            if can_alarm(ui, user):
                up = alarms.upcoming(ui.app, uid)
                out["next"] = up[0] if up else None
            return _resp(200, out)
        if path == "/api/notifications/prefs":
            return _resp(200, hub.prefs_view(uid))
        if path == "/api/alarms":
            if not can_alarm(ui, user):
                return _err(403, "你現在不能用提醒。")
            return _resp(200, {"items": alarms.upcoming(ui.app, uid), "where": hub.where(uid, "alarm"),
                               "warnings": alarms.warnings(ui.app, uid, ui.is_owner(user)), "note": alarms.NOTE})
        return _err(404, "沒有這個 API。")
    if method != "POST":
        return _err(405, "只收 GET、POST。")
    data = _body(body)
    if data is None:
        return _err(400, "送來的不是 JSON 物件。")
    if path == "/api/notifications/read":
        nid = data.get("id")
        if nid is not None and (not isinstance(nid, int) or isinstance(nid, bool)):
            return _err(400, "id 要是整數。")
        if nid is not None:
            hub.dismiss(uid, nid)
        else:
            hub.store.mark_read(uid)
        return _resp(200, {"ok": True})
    m = re.match(r"^/api/notifications/(\d{1,9})/snooze$", path)
    if m:
        if not can_alarm(ui, user):
            return _err(403, "你現在不能用提醒。")
        hhmm = hub.snooze(uid, int(m.group(1)))
        if hhmm is None:
            return _err(404, T["gone"])
        return _resp(200, {"ok": True, "at": hhmm, "message": T["snoozed"].format(hhmm=hhmm)})
    if path == "/api/notifications/prefs":
        off = data.get("off")
        if not isinstance(off, dict):
            return _err(400, "off 要是物件。")
        hub.save_prefs(uid, off)
        return _resp(200, hub.prefs_view(uid))
    if path == "/api/alarms/test":
        if not can_alarm(ui, user):
            return _err(403, "你現在不能用提醒。")
        res = hub.notify(uid, T["test"], kind="alarm", level="alarm", actions=[{"id": "ok", "label": T["ok"]}],
                         data={"test": True})
        sent = [label for c, label in (("web", "網頁"), ("telegram", "Telegram"), ("discord", "Discord")) if res.get(c)]
        return _resp(200, {"ok": True, "sent": sent,
                           "message": ("響了：" + "、".join(sent)) if sent else "沒有任何地方可以叫你。"})
    m = re.match(r"^/api/alarms/(\d{1,9})/delete$", path)
    if m:
        if not can_alarm(ui, user):
            return _err(403, "你現在不能用提醒。")
        from synox.schedule.commands import store_for
        mine = store_for(ui.app).of(uid)
        aid = int(m.group(1))
        if not any(it.get("id") == aid for it in mine.items("remind")):
            return _err(404, "沒有這個鬧鐘（可能已經刪掉了）。")
        mine.remove_id(aid)
        return _resp(200, {"ok": True})
    return _err(404, "沒有這個 API。")
