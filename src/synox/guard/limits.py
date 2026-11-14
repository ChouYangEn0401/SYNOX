"""次數（ADR 0025 §4）：只在記憶體、時鐘可以換（測試用假時鐘）。這個檔不 import synox 的其他模組。

    Attempts(max_fail=5, window=900, lock=900)   幾秒內錯幾次就鎖多久（防猜）
    Rate(per_min)                                每分鐘最多幾次（滑動的 60 秒）
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Hashable, List


class Attempts:
    def __init__(self, max_fail: int = 5, window: float = 900, lock: float = 900,
                 clock: Callable[[], float] = time.time):
        self.max_fail, self.window, self.lock_s, self.clock = int(max_fail), float(window), float(lock), clock
        self._fails: Dict[Hashable, List[float]] = {}
        self._until: Dict[Hashable, float] = {}
        self._mu = threading.Lock()

    def locked(self, key: Hashable) -> float:
        """還要等幾秒（0＝沒鎖）。"""
        with self._mu:
            left = self._until.get(key, 0.0) - self.clock()
            if left <= 0:
                self._until.pop(key, None)
                return 0.0
            return left

    def fail(self, key: Hashable) -> bool:
        """記一次錯。回 True＝這一下剛好把它鎖起來（呼叫端在這時候通知本人，只一次）。"""
        with self._mu:
            now = self.clock()
            if self._until.get(key, 0.0) > now:
                return False
            recent = [t for t in self._fails.get(key, []) if now - t < self.window]
            recent.append(now)
            if len(recent) >= self.max_fail:
                self._fails.pop(key, None)
                self._until[key] = now + self.lock_s
                return True
            self._fails[key] = recent
            return False

    def ok(self, key: Hashable) -> None:
        with self._mu:
            self._fails.pop(key, None)

    def count(self, key: Hashable) -> int:
        with self._mu:
            now = self.clock()
            return len([t for t in self._fails.get(key, []) if now - t < self.window])


class Rate:
    def __init__(self, per_min: int, clock: Callable[[], float] = time.time):
        self.per_min, self.clock = int(per_min), clock
        self._hits: Dict[Hashable, Deque[float]] = {}
        self._mu = threading.Lock()

    def allow(self, key: Hashable) -> bool:
        with self._mu:
            now = self.clock()
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= 60:
                hits.popleft()
            if len(hits) >= self.per_min:
                return False
            hits.append(now)
            return True
