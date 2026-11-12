"""網頁發起的 Discord 擁有者配對：網頁設定頁產生六位數字 → 擁有者私訊 bot 傳這六個數字 → 正在跑的 SYNOX 直接接上。

跟 `python -m synox discord pair` 的差別：那個要另開一條 Gateway 連線等私訊（所以要先關掉 SYNOX）；這個用 SYNOX 自己已經連著的
那條，不用關、不用開終端機。一次只有一組碼、15 分鐘有效、用掉就作廢。

防猜：碼只有六位數字，所以私訊 bot 傳了「六位數字但不對」累積 MAX_WRONG 次，這一組碼就作廢（要在網頁重新產生）。
碼的比對用 secrets.compare_digest。只有擁有者在網頁（已登入）按了才會產生碼；沒產生碼的時候私訊傳六位數字不會有任何作用。
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Callable, Optional

TTL = 15 * 60
MAX_WRONG = 10


class WebPairing:

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._code = ""
        self._expires = 0.0
        self._wrong = 0
        self.last_paired: Optional[dict] = None        # {"id", "username"}：最近一次配對成功的人（網頁用來顯示「配對好了」）

    def start(self) -> dict:
        from synox.wizard.telegram_probe import new_pairing_code
        with self._lock:
            self._code = new_pairing_code()
            self._expires = self._clock() + TTL
            self._wrong = 0
            self.last_paired = None
            return {"code": self._code, "expires_in": TTL}

    def pending(self) -> Optional[dict]:
        """有效的碼 {"code", "expires_in"}；沒有或過期＝None。"""
        with self._lock:
            left = self._expires - self._clock()
            if not self._code or left <= 0:
                self._code = ""
                return None
            return {"code": self._code, "expires_in": int(left)}

    def code(self) -> str:
        found = self.pending()
        return found["code"] if found else ""

    def matches(self, text: str) -> bool:
        with self._lock:
            return bool(self._code) and self._expires > self._clock() and \
                secrets.compare_digest("".join(str(text or "").split()), self._code)

    def wrong_guess(self) -> None:
        """有人私訊傳了六位數字但不對：記一次，太多次就作廢這組碼。"""
        with self._lock:
            self._wrong += 1
            if self._wrong >= MAX_WRONG:
                self._code = ""

    def done(self, who: dict) -> None:
        with self._lock:
            self._code = ""
            self.last_paired = {"id": str(who.get("id", "")), "username": str(who.get("username", ""))}

    def cancel(self) -> None:
        with self._lock:
            self._code = ""
