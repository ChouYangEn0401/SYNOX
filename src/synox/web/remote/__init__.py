"""手機入口（ADR 0026）：在手機上打開一個工具的畫面。通道只碰得到閘門（RemoteGate），閘門驗過身分才把請求交給那個工具的站。

    manager = install(app, config, ui)       # web.install 裝好工具服務之後呼叫；只建管理員，不開任何東西

一定會關的掛點：工具服務「服務停了」（含 /web_off）、app.on_stop、stepup.on_disable、runtime 任務 system.remote（時間、閒置、通道斷了）。
"""

from __future__ import annotations

from typing import Optional

from synox.web.remote.manager import RemoteError, RemoteManager

EXTRA = "synox_remote"


def of(app) -> Optional[RemoteManager]:
    return (getattr(app, "extras", None) or {}).get(EXTRA)


def install(app, config, ui, **kw) -> Optional[RemoteManager]:
    from synox import guard
    from synox.web import apps
    tool_apps = apps.of(app)
    gate = guard.of(app)
    if tool_apps is None or gate is None:
        return None
    manager = RemoteManager(app, config, tool_apps, gate, **kw)
    app.extras[EXTRA] = manager
    tool_apps.on_stopped(manager.on_service_stopped)
    if gate.stepup is not None:
        gate.stepup.on_disable(lambda _uid: manager.close("stepup_disabled"))
    app.on_stop.append(lambda _app: manager.close("shutdown"))
    manager.register_task()
    return manager


__all__ = ["RemoteError", "RemoteManager", "install", "of"]
