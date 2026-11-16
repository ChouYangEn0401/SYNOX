"""
網頁的 🔔 與鬧鐘（docs/notifications.md）。每個登入的人只看得到自己的。

| 方法與路徑 | 做什麼 |
|---|---|
| `GET /api/notifications?since=<rev>` | rev 之後變了的通知、沒讀幾則、下一個鬧鐘 |
| `POST /api/notifications/read` `{"id"}`（沒給 id＝全部已讀） | 知道了／全部已讀 |
| `POST /api/notifications/<id>/snooze` | 5 分鐘後再提醒（交給提醒引擎延後同一個提醒，不另加一筆） |
| `POST /api/notifications/<id>/done` | 完成（有登記提醒引擎就交給它；沒有＝知道了） |
| `GET/POST /api/notifications/prefs` `{"off": {kind: [channel]}}` | 哪一類送到哪裡（Windows 個人版的擁有者多一塊 `desk`） |
| `POST /api/notifications/desk` `{"window", "sentinel"}` | 電腦提醒視窗開／關、登入時啟動提醒哨兵（擁有者、Windows 個人版） |
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


def _desk(ui):
    from synox.notify import deskapp
    deskapp.ensure(ui.app)
    return ui.app.extras.get(deskapp.DESK_EXTRA)


def _with_desk(ui, user, view: dict) -> dict:
    """設定頁多一塊「電腦提醒視窗」：只有 Windows 個人版的擁有者看得到、改得到。"""
    desk = _desk(ui)
    if desk is not None and desk.supported and ui.is_owner(user):
        view = {**view, "desk": desk.view()}
    return view


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
            return _resp(200, _with_desk(ui, user, hub.prefs_view(uid)))
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
            if hub.press(uid, nid, "ok", "web") is None:      # 送達層送的提醒＋引擎有登記：「知道了」交給引擎
                hub.dismiss(uid, nid)
        else:
            hub.store.mark_read(uid)
        return _resp(200, {"ok": True})
    m = re.match(r"^/api/notifications/(\d{1,9})/(snooze|done)$", path)
    if m:
        if not can_alarm(ui, user):
            return _err(403, "你現在不能用提醒。")
        got = hub.press_result(uid, int(m.group(1)), m.group(2), "web")
        if got is not None:
            ok, answer = got
            return _resp(200, {"ok": True, "message": answer}) if ok else _err(404, answer)
        if m.group(2) == "done":                              # 沒有提醒引擎：「完成」＝知道了
            if not hub.dismiss(uid, int(m.group(1))):
                return _err(404, T["gone"])
            return _resp(200, {"ok": True, "message": T["done_ok"]})
        hhmm = hub.snooze(uid, int(m.group(1)))              # press 沒接（不是提醒）＝這裡也是 None
        if hhmm is None:
            return _err(404, T["gone"])
        return _resp(200, {"ok": True, "at": hhmm, "message": T["snoozed"].format(hhmm=hhmm)})
    if path == "/api/notifications/prefs":
        off = data.get("off")
        if not isinstance(off, dict):
            return _err(400, "off 要是物件。")
        hub.save_prefs(uid, off)
        return _resp(200, _with_desk(ui, user, hub.prefs_view(uid)))
    if path == "/api/notifications/desk":
        desk = _desk(ui)
        if desk is None or not ui.is_owner(user) or not desk.supported:
            return _err(403, "只有這台 Windows 電腦的擁有者能改電腦提醒視窗。")
        window, sentinel = data.get("window"), data.get("sentinel")
        if any(v is not None and not isinstance(v, bool) for v in (window, sentinel)):
            return _err(400, "window、sentinel 要是 true／false。")
        desk.save_settings(window=window, sentinel=sentinel)
        if sentinel is not None and desk.armed:                # 跑著的時候才真的去放／拿掉啟動檔
            from synox.remindwin import launcher
            try:
                command, cwd = launcher.sentinel_command(getattr(ui, "config_path", "") or "")
                desk.sync_autostart(command, cwd)
            except OSError as e:
                return _err(500, f"啟動檔沒有改成：{e}")
        return _resp(200, {"ok": True, "desk": desk.view()})
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
        from synox.schedule.commands import removed, store_for
        mine = store_for(ui.app).of(uid)
        aid = int(m.group(1))
        gone = next((it for it in mine.items("remind") if it.get("id") == aid), None)
        if gone is None:
            return _err(404, "沒有這個鬧鐘（可能已經刪掉了）。")
        mine.remove_id(aid)
        removed(ui.app, uid, gone)                            # 待辦：更新電腦視窗；正在響的：各管道收掉
        return _resp(200, {"ok": True})
    return _err(404, "沒有這個 API。")
