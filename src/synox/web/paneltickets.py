"""
工具頁面板（pack 的 `web.panel`）的「票」（ADR 0028 §5）。

面板在 `<iframe sandbox="allow-scripts">` 裡跑（opaque origin：沒有 cookie、碰不到主頁），所以它的網址要自己帶一張票：
工具頁先 `POST /api/packs/<name>/panel-ticket`（要登入、要 CSRF）拿票，再開 `/packs/<name>/panel/<票>/`；
面板讀資料打相對網址 `api/<route>`（＝`/packs/<name>/panel/<票>/api/<route>`），伺服器只認票、不看 cookie。

- 票＝隨機 128 bit（urlsafe），綁：pack 名字、發票那個登入（session 的雜湊）、那個人的 tg_id。有效 8 小時。
- 只放記憶體（重開 SYNOX＝全部作廢，工具頁重拿就好），而且只存票的 SHA-256。
- 登出（drop_session）、/web_off（drop_all）一起作廢；用的時候伺服器還會再查那個登入還在不在（Sessions.has），
  所以就算哪一條登出的路忘了叫 drop_session，登出之後票也不能用。
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from synox.web.tokens import digest

TICKET_TTL = 8 * 3600          # 提案值（ADR 0028 §9 第 3 點，待擁有者確認）
MAX_TICKETS = 2000             # 記憶體上限：滿了先清過期的，再不夠就丟最舊的


@dataclass(frozen=True)
class PanelTicket:
    pack: str
    session_key: str           # digest(session id)（Sessions.has 查得到）
    tg_id: int
    expires: float


class PanelTickets:

    def __init__(self, clock: Callable[[], float] = time.time, ttl: float = TICKET_TTL):
        self._clock = clock
        self.ttl = ttl
        self._lock = threading.Lock()
        self._items: Dict[str, PanelTicket] = {}

    def _prune(self) -> None:
        now = self._clock()
        self._items = {k: t for k, t in self._items.items() if t.expires > now}
        while len(self._items) >= MAX_TICKETS:
            oldest = min(self._items, key=lambda k: self._items[k].expires)
            self._items.pop(oldest, None)

    def issue(self, pack: str, session_key: str, tg_id: int) -> str:
        ticket = secrets.token_urlsafe(16)                       # 128 bit
        with self._lock:
            self._prune()
            self._items[digest(ticket)] = PanelTicket(str(pack), str(session_key), int(tg_id),
                                                      self._clock() + self.ttl)
        return ticket

    def get(self, ticket: str, pack: str) -> Optional[PanelTicket]:
        """票對、沒過期、而且是發給這個 pack 的 → PanelTicket；其他一律 None（不說為什麼）。"""
        if not ticket or len(ticket) > 100:
            return None
        key = digest(ticket)
        with self._lock:
            found = self._items.get(key)
            if found is None:
                return None
            if found.expires <= self._clock():
                self._items.pop(key, None)
                return None
        return found if found.pack == pack else None

    def drop_session(self, session_key: Optional[str]) -> None:
        if not session_key:
            return
        with self._lock:
            self._items = {k: t for k, t in self._items.items() if t.session_key != session_key}

    def drop_all(self) -> None:
        with self._lock:
            self._items.clear()
