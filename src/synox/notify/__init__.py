"""
通知中心（docs/notifications.md）：提醒、鬧鐘、工具畫面太久沒人用、新版、常駐助理的消息……
同時送到網頁（🔔＋跳出來的小卡）、Telegram、Discord，而不是只有 app.home 那一條。

    hub = notify.install(app, config, vault)     # app.build 一開始就裝（載入 pack 時就可能要通知）
    notify.install_buttons(app)                  # 最後裝：Telegram／Discord 上的按鈕（要等 remind、apps 群組都在）
    notify.of(app).notify(uid, text, kind="alarm")

install 會把 app.notify_owner 換成 hub.notify_owner（SDK 的 App 不用改）：舊的呼叫 app.notify_owner(text) 照樣能用，
多帶 kind=… 就能分類（設定頁可以分類關掉）。app.notify(chat_id, …)（送給某個特定的人，例如手機驗證碼）不經過這裡。
"""

from __future__ import annotations

from typing import Optional

from synox.notify.hub import CHANNEL_LABELS, KINDS, Hub
from synox.notify.hub import install_buttons as _install_buttons

EXTRA = "synox_notify"


def install(app, config, vault=None) -> Hub:
    hub = Hub(app, config.data_dir, vault)
    app.extras[EXTRA] = hub
    app.notify_owner = hub.notify_owner              # 實例屬性蓋過 App.notify_owner
    return hub


def install_delivery(app, config, vault=None, *, config_path: str = ""):
    """送達層（ADR 0028）：佇列＋重試（runtime 任務 system.notify.outbox）、電腦提醒視窗、提醒引擎鎖、哨兵的啟動檔。
    要在 runtime.install 之後叫（登記任務）。視窗、鎖、啟動檔只有 app 真的 start 之後才動（notify/deskapp.py）。"""
    from synox.notify import deskapp
    return deskapp.install(app, config, vault, config_path=config_path)


def of(app) -> Optional[Hub]:
    return getattr(app, "extras", {}).get(EXTRA)


def install_buttons(app) -> None:
    hub = of(app)
    if hub is not None:
        _install_buttons(app, hub)


def owner(app, text, *, kind: str = "general", **kw):
    """給擁有者的通知，帶分類。有通知中心走它；沒有（測試的假 app）就照舊 app.notify_owner(text)。"""
    hub = of(app)
    if hub is not None:
        return hub.notify_owner(text, kind=kind, **kw)
    return app.notify_owner(text)


def where_text(app, uid: int, kind: str = "alarm") -> str:
    """「網頁、Telegram」這種白話的清單（沒有任何地方＝""）。"""
    hub = of(app)
    return "、".join(hub.where(uid, kind)) if hub is not None else ""


__all__ = ["CHANNEL_LABELS", "EXTRA", "Hub", "KINDS", "install", "install_buttons", "install_delivery", "of",
           "where_text"]
