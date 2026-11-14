"""給測試用（SYNOX 自己與 SYNOX_Libs 的工具測試都用；不開埠）。

    listen = FakeListen()                                  # 記下被要求開的位址與埠；可設定某個埠丟 OSError、close() 回 False
    manager = AppManager(app, config, ui, listen=listen)   # 或 apps.of(app).listen = listen
    client = AppClient(manager, "counter")                 # 假瀏覽器：Host 自動帶對、不帶任何 cookie
    me = client.enter(client.open_from_console(owner_id))
    client.read("state"); client.do("add", {"n": "3"}); client.do_confirmed("reset", {})
"""

from __future__ import annotations

import json
import threading
from typing import Dict, List, Optional
from urllib.parse import urlencode

from synox.web.apps.listen import APP_HOST
from synox.web.apps.sessions import ConsoleParent
from synox.web.tokens import digest


class FakeListener:
    def __init__(self, site, port: int, close_ok: bool = True, block: Optional[threading.Event] = None):
        self.site, self.port, self.close_ok, self.block = site, port, close_ok, block
        self.closed = 0

    def close(self, timeout: float = 5.0) -> bool:
        if self.block is not None:
            self.block.wait(timeout)
        self.closed += 1
        return self.close_ok


class FakeListen:
    """假的 open_listener：calls 記下 (位址, 埠)；busy＝這些埠丟 OSError；close_ok＝close() 回什麼；
    hold＝開的時候卡在這個 Event 上（測同時動手）；block_close＝close() 卡在這個 Event 上。"""

    def __init__(self, busy=(), close_ok: bool = True, hold: Optional[threading.Event] = None,
                 block_close: Optional[threading.Event] = None):
        self.calls: List[tuple] = []
        self.listeners: List[FakeListener] = []
        self.busy, self.close_ok, self.hold, self.block_close = set(busy), close_ok, hold, block_close
        self.entered = threading.Event()

    def __call__(self, site, port: int, *, handler=None):
        self.calls.append((APP_HOST, int(port)))
        self.handler = handler
        self.entered.set()
        if self.hold is not None:
            self.hold.wait(5)
        if int(port) in self.busy:
            raise OSError("address in use")
        listener = FakeListener(site, port, self.close_ok, self.block_close)
        self.listeners.append(listener)
        return listener


class AppClient:
    def __init__(self, manager, name: str, *, origin_host: Optional[str] = None):
        self.manager, self.name = manager, name
        self.token = ""
        self.console_sid = ""
        self.origin_host = origin_host

    @property
    def site(self):
        return self.manager.site_of(self.name)

    def open_from_console(self, tg_id: int) -> str:
        """照主機台「打開」那一步：建一個真的主機台登入，再用它發一張交接票。"""
        ui = self.manager.ui
        sid, _session = ui.sessions.create(int(tg_id))
        self.console_sid = sid
        return self.manager.issue_ticket(self.name, int(tg_id), ConsoleParent(ui, digest(sid)))

    def raw(self, method: str, path: str, *, headers: Optional[Dict[str, str]] = None, body: bytes = b"",
            token: Optional[str] = None):
        site = self.site
        if site is None:
            raise RuntimeError("service is not on")
        h = {"Host": site.host_header}
        use = self.token if token is None else token
        if path.startswith("/api/") and use and not path.startswith("/api/export/"):
            h["X-SYNOX-App"] = use
        if method == "POST" and not path.startswith("/api/export/"):
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        return site.handle(method, path, h, body)

    def _json(self, resp):
        status, headers, body = resp
        ctype = dict(headers).get("Content-Type", "")
        return status, (json.loads(body) if ctype.startswith("application/json") else body)

    def get(self, path: str, **kw):
        return self._json(self.raw("GET", path, **kw))

    def post(self, path: str, data=None, **kw):
        return self._json(self.raw("POST", path, body=json.dumps(data if data is not None else {}).encode(), **kw))

    def enter(self, ticket: str) -> dict:
        status, data = self.post("/api/enter", {"ticket": ticket})
        if status != 200:
            raise AssertionError(f"enter failed: {status} {data}")
        self.token = data["token"]
        return data["me"]

    def read(self, name: str, **params):
        q = ("?" + urlencode(params)) if params else ""
        return self.get(f"/api/read/{name}{q}")

    def do(self, name: str, values=None, confirmed=False):
        data = {"values": values or {}}
        if confirmed is not False:
            data["confirmed"] = confirmed
        return self.post(f"/api/do/{name}", data)

    def do_confirmed(self, name: str, values=None):
        status, data = self.do(name, values)
        if status == 409 and data.get("code") == "confirm":
            return self.do(name, values, confirmed=True)
        return status, data

    def export(self, name: str, params=None, confirmed=False, token: Optional[str] = None, headers=None):
        form = {"t": self.token if token is None else token, **(params or {})}
        if confirmed:
            form["confirmed"] = "1"
        h = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
        return self.raw("POST", f"/api/export/{name}", headers=h, body=urlencode(form).encode())
