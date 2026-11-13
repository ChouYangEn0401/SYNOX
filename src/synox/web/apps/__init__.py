"""工具服務（ADR 0024 第三版、計畫 WP2）：每個宣告了 web.app 的工具，擁有者可以開一個只在這台電腦打得開的完整畫面。

    manager = install(app, config, ui)      # web.install 建好 ui 之後呼叫

- 位址 `127.0.0.2`、只由 `listen.py` 開埠、app 的埠不用 cookie、只能用主機台發的一次性交接票進（site.py）。
- `app.on_start`：清狀態檔、登記 runtime 任務 `system.tool_apps`（只有服務開著時才排）；`app.on_stop`：全部關掉。
- SYNOX 每次重開，所有服務都是關的。
"""

from __future__ import annotations

from typing import Optional

from synox.web.apps.manager import AppManager
from synox.web.apps.site import AppsError

EXTRA = "synox_apps"


def of(app) -> Optional[AppManager]:
    return (getattr(app, "extras", None) or {}).get(EXTRA)


def install(app, config, ui, **kw) -> AppManager:
    manager = AppManager(app, config, ui, **kw)
    app.extras[EXTRA] = manager
    ui.apps = manager
    manager.clear_state_file()

    def on_start(_app) -> None:
        manager.clear_state_file()
        manager.register_task()

    def on_stop(_app) -> None:
        manager.stop_all(reason="shutdown")
        manager.clear_state_file()

    app.on_start.append(on_start)
    app.on_stop.append(on_stop)
    manager.register_task()
    return manager


__all__ = ["AppManager", "AppsError", "install", "of"]
