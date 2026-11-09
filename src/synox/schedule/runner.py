"""
排程器：每 30 秒掃一次 data/schedule.json(.enc)，到點就做（照 ClawBot routines/runner.py 的做法，只做
「每天 HH:MM」與「某一天 HH:MM 一次」）。

- remind（/remind_add）：送一則「⏰ 提醒：…」給擁有者（app.home）。
- command（/schedule_add）：以排程擁有者的身分造一則 Inbound 交給 dispatcher，via=ROUTINE——
  走的是跟打字一模一樣的指令路由與 authorize()（SDK invariant 1；建立時已經用 via=SCHEDULE 驗過）。
- 一天只跑一次（last_run＝今天就跳過）；一次性的跑完就刪掉。
- 只在 App.run()（Start.bat）時啟動；終端機模式不跑排程（不然提醒會插在你打字的中間）。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, List, Optional

from isdtelekit.core.channel import ROUTINE_CHANNEL, Inbound
from isdtelekit.core.registry import ROUTINE

from synox.schedule.store import ScheduleStore

CHECK_INTERVAL = 30


class ScheduleRunner:

    def __init__(self, app, store: ScheduleStore, clock: Callable[[], datetime] = datetime.now):
        self.app = app
        self.store = store
        self._clock = clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ScheduleRunner")
        self._thread.start()
        logging.info("[SCHEDULE] runner started (every %ss)", CHECK_INTERVAL)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logging.exception("[SCHEDULE] tick failed")
            self._stop.wait(CHECK_INTERVAL)

    def due(self, now: Optional[datetime] = None) -> List[dict]:
        now = now or self._clock()
        today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
        return [it for it in self.store.items()
                if it.get("time") == hhmm and it.get("last_run") != today
                and (not it.get("date") or it.get("date") == today)]

    def tick(self, now: Optional[datetime] = None) -> List[dict]:
        """做完到點的那些，回傳做了哪幾個（測試用）。"""
        now = now or self._clock()
        today = now.strftime("%Y-%m-%d")
        fired = []
        for item in self.due(now):
            try:
                self._fire(item)
            except Exception:
                logging.exception("[SCHEDULE] item %s failed", item.get("id"))
            if item.get("date"):
                self.store.remove_id(item["id"])
            else:
                self.store.mark_run(item["id"], today)
            fired.append(item)
        return fired

    def _fire(self, item: dict) -> None:
        owner = int(item.get("owner") or self.app.owner_id)
        if item.get("kind") == "remind":
            logging.info("[SCHEDULE] remind %s → %s", item.get("id"), owner)
            self.app.notify(owner, f"⏰ 提醒：{item.get('text', '')}")
            return
        command = item.get("command", "")
        logging.info("[SCHEDULE] command %s → %s: %s", item.get("id"), owner, command)
        inbound = Inbound(ROUTINE_CHANNEL, user_id=owner, chat_id=owner, text=command, username="schedule",
                          sent_at=time.time())
        route = self.app.dispatcher.handle(self.app.home, inbound, via=ROUTINE)
        if getattr(route, "kind", "") in ("denied", "unknown_command"):
            self.app.notify(owner, f"⏸ 排程 {item.get('time')} {command} 沒有跑成（{route.reason or route.kind}）。"
                                   "\n/schedule_list 看、/schedule_rm 刪。")
