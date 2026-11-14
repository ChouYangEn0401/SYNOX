"""工具服務的登入與交接票（計畫 C4、C7、C12）：只在記憶體、只存 SHA-256。

- 交接票：256 位元隨機、30 秒、只能用一次、綁（app、埠、tg_id、上一層）。每個 app 最多 20 張沒用過的（多的丟最舊的）。
- app 的登入：256 位元的 token（放在分頁裡、用標頭帶）、12 小時、每人每個 app 最多 5 個（新的擠掉最舊的）。
- 「上一層」（ADR 0026 對接 d）：票與登入綁在一個有 `alive()` 的物件上——本機是主機台的登入（`ConsoleParent`，
  主機台登出、過期、/web_off 之後就不 alive），手機入口是那一條入口。每個請求都問一次，不快取。
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from synox.web.tokens import digest

APP_SESSION_TTL = 12 * 3600
APP_SESSIONS_PER_USER = 5
HANDOFF_TTL = 30
MAX_TICKETS = 20


class ConsoleParent:
    """本機的上一層：主機台的那一個登入（雜湊）。"""
    kind = "web"

    def __init__(self, ui, key_digest: str, surface: str = ""):
        self.ui, self.key, self.surface = ui, key_digest, surface or ("web:" + key_digest[:16])

    def alive(self) -> bool:
        return not getattr(self.ui, "disabled", False) and self.ui.sessions.has(self.key)


@dataclass
class AppSession:
    tg_id: int
    parent: object
    created: float
    expires: float
    last_alive: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def alive_ok(self, now: float, every: float) -> bool:
        """「人還在」的節流：比較與更新在這個登入自己的鎖裡一次做完。"""
        with self.lock:
            if now - self.last_alive < every:
                return False
            self.last_alive = now
            return True


class AppSessions:
    def __init__(self, clock=time.time):
        self.clock = clock
        self._items: "OrderedDict[str, AppSession]" = OrderedDict()
        self._mu = threading.Lock()

    def create(self, tg_id: int, parent) -> Tuple[str, AppSession]:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        session = AppSession(int(tg_id), parent, now, now + APP_SESSION_TTL)
        with self._mu:
            mine = [k for k, s in self._items.items() if s.tg_id == int(tg_id)]
            while len(mine) >= APP_SESSIONS_PER_USER:
                self._items.pop(mine.pop(0), None)
            self._items[digest(token)] = session
        return token, session

    def get(self, token: Optional[str]) -> Optional[AppSession]:
        if not token or not isinstance(token, str) or len(token) > 200:
            return None
        with self._mu:
            return self._items.get(digest(token))

    def drop(self, token: Optional[str]) -> None:
        if token:
            with self._mu:
                self._items.pop(digest(token), None)

    def drop_all(self) -> None:
        with self._mu:
            self._items.clear()

    def __len__(self) -> int:
        with self._mu:
            return len(self._items)


class HandoffTickets:
    """由 manager 在它的大鎖裡叫（C12）：查與用掉一次做完。"""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._items: Dict[str, "OrderedDict[str, tuple]"] = {}

    def issue(self, app: str, port: int, tg_id: int, parent) -> str:
        ticket = secrets.token_urlsafe(32)
        bucket = self._items.setdefault(app, OrderedDict())
        now = self.clock()
        for key in [k for k, v in bucket.items() if v[3] <= now]:
            bucket.pop(key, None)
        while len(bucket) >= MAX_TICKETS:
            bucket.popitem(last=False)
        bucket[digest(ticket)] = (int(port), int(tg_id), parent, now + HANDOFF_TTL)
        return ticket

    def redeem(self, app: str, port: int, ticket: Optional[str]) -> Optional[Tuple[int, object]]:
        if not ticket or not isinstance(ticket, str) or len(ticket) > 200:
            return None
        bucket = self._items.get(app) or {}
        want = digest(ticket)
        found = None
        for key in list(bucket):
            if hmac.compare_digest(key, want):
                found = key
                break
        if found is None:
            return None
        item_port, tg_id, parent, expires = bucket.pop(found)
        if item_port != int(port) or expires <= self.clock():
            return None
        return tg_id, parent

    def clear(self, app: str) -> None:
        self._items.pop(app, None)

    def count(self, app: str) -> int:
        return len(self._items.get(app) or {})
