"""
登入連結與網頁 session。

- 登入連結：/web（Telegram）或精靈最後一頁產生 `http://127.0.0.1:<port>/login?t=<token>`。token 隨機（256 bit）、
  只能用一次、7 天、綁一個 Telegram id。data/web_tokens.json 只存 token 的 SHA-256（檔案被看到也拿不到能用的連結）。
- 兌換要兩步（防 login CSRF：別人把**他的**登入連結塞給你，你的瀏覽器就登入成他）：GET 連結只顯示
  「你將以 <名字> 登入」的確認頁（peek，不用掉）；按頁上的按鈕 POST（一次性表單 token＋綁這個瀏覽器的 cookie、
  Origin 要是自己）才 redeem。見 web/server.py 的 login_page／login_post。
- session：換到的 cookie（HttpOnly、SameSite=Lax）。記憶體一份＋data/web_sessions.json（同樣只存 SHA-256），
  重開 bot 不用重新登入；7 天過期。每個 session 一個 CSRF token（網頁送出改東西的請求要帶 X-SYNOX-CSRF）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from isdtelekit.core import jsonstore

TOKEN_TTL = 7 * 24 * 3600
SESSION_TTL = 7 * 24 * 3600


def digest(secret: str) -> str:
    return hashlib.sha256(str(secret).encode("utf-8")).hexdigest()


class LoginTokens:

    def __init__(self, path: str, clock: Callable[[], float] = time.time, ttl: float = TOKEN_TTL):
        self.path = path
        self._clock = clock
        self.ttl = ttl
        self._lock = threading.Lock()

    def _load(self) -> dict:
        data = jsonstore.load_json(self.path, {})
        return data if isinstance(data, dict) else {}

    def _prune(self, data: dict) -> dict:
        now = self._clock()
        return {k: v for k, v in data.items() if isinstance(v, dict) and float(v.get("expires", 0)) > now}

    def issue(self, tg_id: int) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            data = self._prune(self._load())
            data[digest(token)] = {"tg_id": int(tg_id), "expires": self._clock() + self.ttl}
            jsonstore.save_json(self.path, data)
        return token

    def peek(self, token: str) -> Optional[int]:
        """看這個 token 是誰的（不用掉）：給登入確認頁顯示「你將以誰登入」。不對、過期 → None。"""
        if not token or len(token) > 200:
            return None
        with self._lock:
            found = self._load().get(digest(token))
        if not isinstance(found, dict) or float(found.get("expires", 0)) <= self._clock():
            return None
        return int(found["tg_id"])

    def redeem(self, token: str) -> Optional[int]:
        """用掉一個 token：回 tg_id；不對、過期、用過 → None。"""
        if not token or len(token) > 200:
            return None
        return self.redeem_digest(digest(token))

    def redeem_digest(self, key: str) -> Optional[int]:
        """同 redeem，但給的是 token 的 SHA-256（登入確認頁只在記憶體留雜湊，不留 token 本身）。"""
        with self._lock:
            data = self._load()
            found = data.pop(key, None)
            data = self._prune(data)
            jsonstore.save_json(self.path, data)
        if not isinstance(found, dict) or float(found.get("expires", 0)) <= self._clock():
            return None
        return int(found["tg_id"])


@dataclass
class Session:
    tg_id: int
    csrf: str
    created: float
    expires: float

    def csrf_ok(self, value: Optional[str]) -> bool:
        return bool(value) and hmac.compare_digest(str(value), self.csrf)


class Sessions:

    def __init__(self, path: str, clock: Callable[[], float] = time.time, ttl: float = SESSION_TTL):
        self.path = path
        self._clock = clock
        self.ttl = ttl
        self._lock = threading.Lock()
        self._items: Dict[str, Session] = {}
        raw = jsonstore.load_json(path, {})
        if isinstance(raw, dict):
            for key, v in raw.items():
                try:
                    self._items[key] = Session(int(v["tg_id"]), str(v["csrf"]), float(v["created"]),
                                               float(v["expires"]))
                except (KeyError, TypeError, ValueError):
                    continue

    def _save(self) -> None:
        now = self._clock()
        self._items = {k: s for k, s in self._items.items() if s.expires > now}
        jsonstore.save_json(self.path, {k: {"tg_id": s.tg_id, "csrf": s.csrf, "created": s.created,
                                            "expires": s.expires} for k, s in self._items.items()})

    def create(self, tg_id: int) -> Tuple[str, Session]:
        sid = secrets.token_urlsafe(32)
        now = self._clock()
        session = Session(int(tg_id), secrets.token_urlsafe(24), now, now + self.ttl)
        with self._lock:
            self._items[digest(sid)] = session
            self._save()
        return sid, session

    def get(self, sid: Optional[str]) -> Optional[Session]:
        if not sid or len(sid) > 200:
            return None
        with self._lock:
            session = self._items.get(digest(sid))
            if session is None:
                return None
            if session.expires <= self._clock():
                self._items.pop(digest(sid), None)
                self._save()
                return None
            return session

    def has(self, key_digest: str) -> bool:
        """這個雜湊（digest(sid)）的登入還在而且沒過期（工具服務的 app 登入綁在主機台的登入上）。"""
        if not isinstance(key_digest, str) or not key_digest:
            return False
        with self._lock:
            session = self._items.get(key_digest)
            return session is not None and session.expires > self._clock()

    def drop(self, sid: Optional[str]) -> None:
        if not sid:
            return
        with self._lock:
            if self._items.pop(digest(sid), None) is not None:
                self._save()

    def drop_all(self) -> None:
        with self._lock:
            self._items.clear()
            self._save()
