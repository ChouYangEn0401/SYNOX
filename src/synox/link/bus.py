"""
事件匯流排（SYNOX Link，架構 v1 §L5）：程序內的 publish／subscribe，讓「收到什麼」跟「要做什麼」分開。

    bus = EventBus()
    off = bus.subscribe("task.*", lambda topic, event: print(topic, event["task"]["id"]))
    bus.publish("task.done", task=task.to_dict(), peer="3f2a-…")
    off()                                              # 取消訂閱

- 主題是用點分的字串（link.in.task.offer、task.done、peer.online…）；pattern 用 fnmatch（* 什麼都配，
  所以 "task.*" 也配 "task.a.b"；"*" 全收）。
- 同步呼叫（在 publish 的那條執行緒上，照訂閱順序）；handler 丟例外只記 log、不影響別的 handler、不往外丟。
  要慢慢做的事（跑指令）handler 自己丟 app.tasks。
- history：最近 HISTORY 筆（debug、/link_status、測試看）。
- wait_for(pattern, timeout)：等某個事件（測試、CLI 用）。
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
from collections import deque
from typing import Callable, Deque, List, Optional, Tuple

Handler = Callable[[str, dict], None]
HISTORY = 200


class EventBus:

    def __init__(self, history: int = HISTORY):
        self._subs: List[Tuple[str, Handler]] = []
        self._lock = threading.RLock()
        self._history: Deque[Tuple[int, str, dict]] = deque(maxlen=history)   # (流水號, 主題, 事件)
        self._changed = threading.Condition(self._lock)
        self._n = 0

    def subscribe(self, pattern: str, handler: Handler) -> Callable[[], None]:
        entry = (pattern, handler)
        with self._lock:
            self._subs.append(entry)

        def off() -> None:
            with self._lock:
                if entry in self._subs:
                    self._subs.remove(entry)
        return off

    def publish(self, topic: str, **event) -> int:
        """回傳有幾個 handler 收到。"""
        with self._lock:
            subs = [h for p, h in self._subs if fnmatch.fnmatchcase(topic, p)]
            self._n += 1
            self._history.append((self._n, topic, dict(event)))
            self._changed.notify_all()
        for handler in subs:
            try:
                handler(topic, event)
            except Exception:
                logging.exception("[BUS] handler for %s failed", topic)
        return len(subs)

    def history(self, pattern: str = "*", limit: int = 50) -> List[Tuple[str, dict]]:
        """最近的事件（主題, 事件），舊的在前。"""
        with self._lock:
            items = [(t, e) for _n, t, e in self._history if fnmatch.fnmatchcase(t, pattern)]
        return items[-limit:]

    def wait_for(self, pattern: str, timeout: float = 10.0,
                 where: Optional[Callable[[str, dict], bool]] = None) -> Optional[Tuple[str, dict]]:
        """等下一個配得上 pattern（且 where 成立）的事件；逾時回 None。只看呼叫這一刻之後發佈的事件。"""
        deadline = time.time() + timeout
        with self._lock:
            since = self._n
            while True:
                for n, topic, event in self._history:
                    if n > since and fnmatch.fnmatchcase(topic, pattern) and (where is None or where(topic, event)):
                        return topic, event
                since = self._n
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._changed.wait(remaining)


__all__ = ["EventBus", "Handler"]
