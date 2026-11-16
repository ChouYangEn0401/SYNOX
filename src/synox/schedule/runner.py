"""
排程器：每 30 秒掃一次 data/schedule.json(.enc)（伺服器版：每個人的 data/users/<id>/schedule.json.enc），到點就做（照 前身專案 routines/runner.py 的做法，只做
「每天 HH:MM」與「某一天 HH:MM 一次」）。

- remind（/remind_add）：送一則「⏰ 提醒：…」給建立的那個人——走通知中心（synox/notify）：網頁跳出來、Telegram、Discord
  都送，帶「知道了」「5 分鐘後再提醒」（伺服器版每個人收自己的）。
- 晚了（電腦剛醒、SYNOX 剛開）：時間過了 LATE_MAX_MIN 分鐘以內照樣叫，多說一句晚了幾分鐘；超過就送「你錯過了 1 個鬧鐘」
  （只算建立之後才到的那一次；每天的只看今天那一次）。一次性的不管叫了還是錯過都刪掉。
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
from typing import Callable, List, Optional, Tuple

from isdtelekit.core.channel import ROUTINE_CHANNEL, Inbound
from isdtelekit.core.registry import ROUTINE

from synox.schedule.store import ScheduleStore

CHECK_INTERVAL = 30
LATE_MAX_MIN = 60


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

    @staticmethod
    def _slot(it: dict, now: datetime) -> Optional[datetime]:
        """這個項目「今天該響的那一次」（一次性的：那一天那一刻；每天的：今天那一刻）。格式壞掉＝None。"""
        try:
            h, m = (int(x) for x in str(it.get("time", "")).split(":"))
            day = datetime.strptime(it["date"], "%Y-%m-%d") if it.get("date") else now
            return day.replace(hour=h, minute=m, second=0, microsecond=0)
        except (ValueError, TypeError):
            return None

    def _late_min(self, it: dict, now: datetime) -> Optional[int]:
        """到點了嗎：None＝還沒／不是今天／今天做過；0＝準時（同一分鐘）；>0＝晚了幾分鐘（建立之後才到的那一次）。"""
        today = now.strftime("%Y-%m-%d")
        if it.get("last_run") == today or (it.get("date") and it.get("date") != today):
            return None
        if it.get("time") == now.strftime("%H:%M"):
            return 0
        slot = self._slot(it, now)
        if slot is None or slot > now:
            return None
        if float(it.get("created") or 0) > slot.timestamp():          # 08:10 才設的「每天 08:00」：明天才算
            return None
        return max(1, int((now - slot).total_seconds() // 60))

    def due_pairs(self, now: Optional[datetime] = None) -> List[Tuple[ScheduleStore, dict]]:
        """到點的 (那個人的 store, 項目)，包括晚了 LATE_MAX_MIN 分鐘以內的。個人版只有一份；伺服器版掃每個人自己的。"""
        now = now or self._clock()
        out = []
        for store in self.store.all_stores():
            for it in store.items():
                late = self._late_min(it, now)
                if late is not None and late <= LATE_MAX_MIN:
                    out.append((store, it))
        return out

    def missed_pairs(self, now: Optional[datetime] = None) -> List[Tuple[ScheduleStore, dict]]:
        """錯過的提醒（晚超過 LATE_MAX_MIN 分鐘，或一次性的日期已經過了）：只算建立之後才到的那一次。"""
        now = now or self._clock()
        today = now.strftime("%Y-%m-%d")
        out = []
        for store in self.store.all_stores():
            for it in store.items("remind"):
                if it.get("date") and it.get("date") < today:
                    out.append((store, it))
                    continue
                late = self._late_min(it, now)
                if late is not None and late > LATE_MAX_MIN:
                    out.append((store, it))
        return out

    def due(self, now: Optional[datetime] = None) -> List[dict]:
        return [it for _store, it in self.due_pairs(now)]

    def tick(self, now: Optional[datetime] = None) -> List[dict]:
        """做完到點的那些，回傳做了哪幾個（測試用）。"""
        now = now or self._clock()
        today = now.strftime("%Y-%m-%d")
        fired = []
        for store, item in self.due_pairs(now):
            try:
                self._fire(item, store.tg_id, late=self._late_min(item, now) or 0, today=today)
            except Exception:
                logging.exception("[SCHEDULE] item %s failed", item.get("id"))
            if item.get("date"):
                store.remove_id(item["id"])
            else:
                store.mark_run(item["id"], today)
            fired.append(item)
        for store, item in self.missed_pairs(now):
            try:
                self._missed(item, store.tg_id, now)
            except Exception:
                logging.exception("[SCHEDULE] missed notice %s failed", item.get("id"))
            if item.get("date"):
                store.remove_id(item["id"])
            else:
                store.mark_run(item["id"], today)
        return fired

    def _owner_of(self, item: dict, store_owner: Optional[int]) -> int:
        return int(store_owner if store_owner is not None else (item.get("owner") or self.app.owner_id))

    def _missed(self, item: dict, store_owner: Optional[int], now: datetime) -> None:
        from synox import notify
        from synox.notify.alarms import friendly
        owner = self._owner_of(item, store_owner)
        slot = self._slot(item, now)
        when = friendly(slot, now) if slot is not None else item.get("time", "")
        hub = notify.of(self.app)
        logging.info("[SCHEDULE] remind %s missed → %s", item.get("id"), owner)
        if hub is not None:
            hub.missed(owner, when, item.get("text", ""), key=f"missed:{item.get('id')}:{item.get('date') or ''}:{when}")
        else:
            self.app.notify(owner, f"⏰ 你錯過了 1 個鬧鐘：{when} {item.get('text', '')}")

    def _fire(self, item: dict, store_owner: Optional[int] = None, *, late: int = 0, today: str = "") -> None:
        # 伺服器版：每人一份的檔案是誰的就以誰的身分跑（不信檔案裡寫的 owner）
        owner = self._owner_of(item, store_owner)
        if item.get("kind") == "remind":
            logging.info("[SCHEDULE] remind %s → %s", item.get("id"), owner)
            from synox import notify
            hub = notify.of(self.app)
            if hub is not None:
                hub.alarm(owner, item.get("text", ""), late_min=late, item_id=item.get("id"),
                          key=f"alarm:{item.get('id')}:{today}:{item.get('time')}:{item.get('created', '')}")
            else:
                self.app.notify(owner, f"⏰ 提醒：{item.get('text', '')}")
            return
        command = item.get("command", "")
        logging.info("[SCHEDULE] command %s → %s: %s", item.get("id"), owner, command)
        inbound = Inbound(ROUTINE_CHANNEL, user_id=owner, chat_id=owner, text=command, username="schedule",
                          sent_at=time.time())
        from synox.guard.origin import Origin, using
        with using(Origin("schedule", owner, surface="schedule")):          # 排程到點（ADR 0025 §2）
            route = self.app.dispatcher.handle(self.app.home, inbound, via=ROUTINE)
        if getattr(route, "kind", "") in ("denied", "unknown_command"):
            self.app.notify(owner, f"⏸ 排程 {item.get('time')} {command} 沒有跑成（{route.reason or route.kind}）。"
                                   "\n/schedule_list 看、/schedule_rm 刪。")
