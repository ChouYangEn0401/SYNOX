"""給測試用（不開埠、不開子程序、不連網）。

    tunnel = FakeTunnel()                        # start() 回一個假的 https://<隨機>.trycloudflare.com
    manager.tunnel_factory = tunnel
    out = manager.open("counter", owner_user, code, origin=Origin("telegram", owner, surface="telegram"))
    phone = RemoteClient(manager)
    me = phone.enter(out["url"], new_code)      # 進門頁 → 鑰匙＋新碼 → 拿 cookie → 交接票 → 工具站的登入
    phone.read("state"); phone.do("add", {"n": "1"})
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit

from synox.web.remote.tunnel import TunnelError


class FakeTunnel:
    def __init__(self, url: str = "https://quiet-river-1234.trycloudflare.com", fail: Optional[str] = None,
                 dies_after: Optional[int] = None):
        self.url, self.fail, self.dies_after = url, fail, dies_after
        self.started: List[str] = []
        self.stopped = 0
        self.checks = 0

    def start(self, target_url: str, timeout: float = 45.0) -> str:
        self.started.append(target_url)
        self.running_since_stop = self.stopped
        if self.fail:
            raise TunnelError(self.fail)
        return self.url

    def stop(self) -> None:
        self.stopped += 1

    def alive(self) -> bool:
        self.checks += 1
        if self.stopped > getattr(self, "running_since_stop", 0):
            return False
        return self.dies_after is None or self.checks <= self.dies_after


class RemoteClient:
    """假手機：記 cookie、User-Agent、Origin 自動帶對（https://<這次的網域>）。"""

    def __init__(self, manager, user_agent: str = "PhoneBrowser/1.0"):
        self.manager = manager
        self.user_agent = user_agent
        self.cookie = ""
        self.token = ""
        self.host = ""

    @property
    def gate(self):
        return self.manager.gate

    def raw(self, method: str, path: str, *, headers: Optional[Dict[str, str]] = None, body: bytes = b"",
            items: Optional[List[Tuple[str, str]]] = None):
        if items is None:
            h = {"Host": self.host, "User-Agent": self.user_agent, "Sec-Fetch-Site": "same-origin"}
            if self.cookie:
                h["Cookie"] = self.cookie
            if method == "POST":
                h["Origin"] = f"https://{self.host}"
                h["Content-Type"] = "application/json"
                h["Content-Length"] = str(len(body))
            if self.token and path.startswith("/api/"):
                h["X-SYNOX-App"] = self.token
            h.update(headers or {})
            items = [(k, v) for k, v in h.items() if v is not None]
        return self.gate.handle_raw(method, path, items, body)

    def _json(self, resp):
        status, headers, body = resp
        ctype = dict(headers).get("Content-Type", "")
        return status, (json.loads(body) if ctype.startswith("application/json") else body)

    def get(self, path: str, **kw):
        return self._json(self.raw("GET", path, **kw))

    def post(self, path: str, data=None, **kw):
        return self._json(self.raw("POST", path, body=json.dumps(data if data is not None else {}).encode(), **kw))

    def knock(self, link_url: str, code: str):
        """只做進門那一步：回 (status, headers, body)。"""
        parts = urlsplit(link_url)
        self.host = parts.hostname or ""
        key = parts.fragment.split("k=", 1)[1] if "k=" in parts.fragment else ""
        resp = self.raw("POST", "/_synox/enter", body=json.dumps({"k": key, "code": code}).encode())
        for k, v in resp[1]:
            if k.lower() == "set-cookie":
                self.cookie = v.split(";", 1)[0]
        return resp

    def enter(self, link_url: str, code: str) -> dict:
        status, _h, body = self.knock(link_url, code)
        if status != 200:
            raise AssertionError(f"enter failed: {status} {body!r}")
        ticket = json.loads(body)["next"].split("#t=", 1)[1]
        status, data = self.post("/api/enter", {"ticket": ticket})
        if status != 200:
            raise AssertionError(f"app enter failed: {status} {data}")
        self.token = data["token"]
        return data["me"]

    def read(self, name: str, **params):
        return self.get(f"/api/read/{name}" + (("?" + urlencode(params)) if params else ""))

    def do(self, name: str, values=None, confirmed=False):
        data = {"values": values or {}}
        if confirmed is not False:
            data["confirmed"] = confirmed
        return self.post(f"/api/do/{name}", data)
