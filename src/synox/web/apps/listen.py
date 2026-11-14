"""整個工具服務（與手機入口的閘門）**唯一**會開埠的地方（ADR 0024 第三版；AGENT.md invariant 9）。越短越好。

- 位址永遠是 `APP_HOST = "127.0.0.2"`：不從 config.json 讀、沒有環境變數可以改、不經 `bind_host()`、永遠不會是 0.0.0.0。
- `open_listener(site, port, *, handler=None)`：site 是有 `handle(...)` 的物件（`AppSite`；手機入口的閘門給
  `handler=GuardedHandler`，ADR 0026 對接 f）。
- `Listener.close(timeout=5.0)` 是同步的：shutdown → server_close → 等聽連線的那條執行緒（最多 5 秒）；回有沒有關乾淨。
"""

from __future__ import annotations

import threading

APP_HOST = "127.0.0.2"


class Listener:
    def __init__(self, server, thread: threading.Thread, port: int):
        self._server, self._thread, self.port = server, thread, int(port)

    def close(self, timeout: float = 5.0) -> bool:
        server = self._server
        stopper = threading.Thread(target=server.shutdown, daemon=True, name=f"app-stop-{self.port}")
        stopper.start()
        stopper.join(timeout)
        if stopper.is_alive():
            return False
        server.server_close()
        self._thread.join(timeout)
        return not self._thread.is_alive()


def open_listener(site, port: int, *, handler=None) -> Listener:
    from synox.web import server as web_server
    srv = web_server._Server((APP_HOST, int(port)), handler or web_server._Handler)
    srv.daemon_threads = True
    srv.ui = site
    thread = threading.Thread(target=srv.serve_forever, daemon=True, name=f"app-{port}")
    thread.start()
    return Listener(srv, thread, port)
