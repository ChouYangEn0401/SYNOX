"""
鬧鐘看得到（docs/notifications.md「鬧鐘」）：接下來會響哪幾個、會在哪裡響、什麼情況會漏掉。

- upcoming(app, uid)：這個人的提醒（/remind_*，data/schedule.json.enc）排成「下一次響的時間」先後。
- warnings(app, uid, owner)：可能漏掉的原因，白話＋能一鍵修的就給按鈕（只有擁有者能按的才給擁有者）。
- friendly(dt, now)：「今天 08:00」「明天 08:00」「11 月 20 日 08:00」。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import List, Optional

WEEK = "一二三四五六日"


def friendly(dt: datetime, now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    days = (dt.date() - now.date()).days
    hhmm = dt.strftime("%H:%M")
    if days == 0:
        return f"今天 {hhmm}"
    if days == 1:
        return f"明天 {hhmm}"
    if days == 2:
        return f"後天 {hhmm}"
    if days == -1:
        return f"昨天 {hhmm}"
    return f"{dt.month} 月 {dt.day} 日（{WEEK[dt.weekday()]}）{hhmm}"


def next_at(item: dict, now: datetime) -> Optional[datetime]:
    """這個提醒下一次響的時間（一次性的已經過了＝None）。"""
    try:
        h, m = (int(x) for x in str(item.get("time", "")).split(":"))
    except ValueError:
        return None
    if item.get("date"):
        try:
            day = datetime.strptime(item["date"], "%Y-%m-%d")
        except ValueError:
            return None
        at = day.replace(hour=h, minute=m)
        return at if at >= now.replace(second=0, microsecond=0) else None
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if at < now.replace(second=0, microsecond=0) or item.get("last_run") == now.strftime("%Y-%m-%d"):
        at += timedelta(days=1)
    return at


def upcoming(app, uid: int, now: Optional[datetime] = None) -> List[dict]:
    from synox.schedule.commands import store_for
    now = now or datetime.now()
    out = []
    for n, it in enumerate(store_for(app).of(uid).items("remind"), 1):
        at = next_at(it, now)
        if at is None:
            continue
        out.append({"id": it.get("id"), "n": n, "text": it.get("text", ""), "daily": not it.get("date"),
                    "at": at.isoformat(timespec="minutes"), "when": friendly(at, now),
                    "repeat": "每天" if not it.get("date") else "一次"})
    out.sort(key=lambda r: r["at"])
    return out


def _autostart_on() -> Optional[bool]:
    """Windows：啟動資料夾裡有 SYNOX 的捷徑嗎（精靈勾「開機自動啟動」放的）。其他系統＝None（不知道）。"""
    if sys.platform != "win32":
        return None
    from synox.wizard.shortcuts import STARTUP_NAME, startup_dir
    folder = startup_dir()
    return any(os.path.exists(os.path.join(folder, STARTUP_NAME + ext)) for ext in (".cmd", ".lnk"))


def warnings(app, uid: int, owner: bool, *, platform: Optional[str] = None, autostart=_autostart_on) -> List[dict]:
    """可能漏掉的原因。每一則 {"id", "text", "fix": {"label", "action"｜"href"} 或沒有}。"""
    from synox import notify
    hub = notify.of(app)
    out: List[dict] = []
    where = hub.where(uid, "alarm") if hub is not None else []
    if not where:
        out.append({"id": "nowhere", "text": "現在沒有任何地方會叫你：鬧鐘時間到了也不會跳出來。",
                    "fix": {"label": "打開網頁通知", "href": "#settings:system"}})
    elif where == ["網頁"]:
        out.append({"id": "web_only",
                    "text": "現在只會在網頁上叫你：網頁要開著才會跳出來，沒開的話要等你下次打開才看得到。"
                            "接上 Telegram 或 Discord，手機也會響。",
                    "fix": {"label": "去接 Telegram／Discord", "href": "#settings:channels"} if owner else None})
    if (platform or sys.platform) == "win32" and owner:
        from synox import runtime
        rt = runtime.of(app)
        ka = getattr(rt, "keep_awake", None) if rt is not None else None
        if ka is not None and not ka.enabled:
            out.append({"id": "sleep", "text": "電腦睡著的時候鬧鐘不會響。想讓它準時響，電腦要開著、不要自己睡著。",
                        "fix": {"label": "讓電腦不要自己睡著", "action": "keep_awake"}})
        try:
            on = autostart()
        except Exception:
            on = None
        if on is False:
            out.append({"id": "autostart",
                        "text": "電腦重開之後，要等你打開 SYNOX，鬧鐘才會響。想開機就自己開：再跑一次安裝程式，"
                                "勾「開機自動啟動」。", "fix": None})
    return out


NOTE = "鬧鐘只有在 SYNOX 開著的時候才會響（電腦要開著、沒有睡著）。"
