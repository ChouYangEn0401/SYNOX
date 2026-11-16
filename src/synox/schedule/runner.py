"""
排程器：每 30 秒掃一次 data/schedule.json(.enc)（伺服器版：每個人的 data/users/<id>/schedule.json.enc），到點就做。

- remind（/remind_*）：交給提醒引擎（engine.py，docs/adr/0028 §3.1）——到點判斷、晚了照響、錯過怎麼說、
  送達確認與「沒送到不刪」都在那裡；送出走送達層（notify/delivery.py；還沒接上時退回通知中心的舊送法）。
- command（/schedule_add）：以排程擁有者的身分造一則 Inbound 交給 dispatcher，via=ROUTINE——
  走的是跟打字一模一樣的指令路由與 authorize()（SDK invariant 1；建立時已經用 via=SCHEDULE 驗過）。
  一天只跑一次（last_run＝今天就跳過）；一次性的跑完就刪掉。這一輪不換資料格式。
- 提醒引擎連續失敗 ENGINE_ALERT_AFTER 次：直接通知「提醒引擎停了」（恢復時再說一聲）。
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
ENGINE_ALERT_AFTER = 3          # 提醒引擎連續失敗幾次就直接通知
MAX_BACKOFF = 60.0              # runtime 任務的失敗退避上限（秒）：提醒不能等 30 分鐘

T_ENGINE_DOWN = ("⚠️ 提醒引擎停了：連續 {n} 次檢查都失敗，到點的提醒可能不會響。"
                 "SYNOX 每分鐘會再試一次；一直這樣的話，到網頁主控面板看「提醒與排程」的日誌，或重開 SYNOX。")
T_ENGINE_BACK = "✅ 提醒引擎恢復了：剛剛沒響到的，會照補送的規則補上。"


class EngineDown(RuntimeError):
    pass


class ScheduleRunner:

    def __init__(self, app, store: ScheduleStore, clock: Callable[[], datetime] = datetime.now):
        from synox.schedule.engine import ReminderEngine, app_deliver, app_resolve
        self.app = app
        self.store = store
        self._clock = clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.engine = ReminderEngine(store, lambda msg: app_deliver(app, msg),
                                     resolve=lambda uid, key, **kw: app_resolve(app, uid, key, **kw),
                                     owner_default=getattr(app, "owner_id", None))
        self.engine_failures = 0
        self.engine_alerted = False

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

    # ── /schedule_*（指令）的到點判斷：格式不變 ──────────────────────────────

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
        """到點的排程指令 (那個人的 store, 項目)，包括晚了 LATE_MAX_MIN 分鐘以內的。"""
        now = now or self._clock()
        out = []
        for store in self.store.all_stores():
            for it in store.items("command"):
                late = self._late_min(it, now)
                if late is not None and late <= LATE_MAX_MIN:
                    out.append((store, it))
        return out

    def due(self, now: Optional[datetime] = None) -> List[dict]:
        return [it for _store, it in self.due_pairs(now)]

    # ── 一輪 ─────────────────────────────────────────────────────────

    def tick(self, now: Optional[datetime] = None) -> List[dict]:
        """做完到點的那些，回傳做了哪幾個（響了的提醒＋跑了的指令；測試用）。
        提醒引擎有清單讀不了＝丟 EngineDown（runtime 算一次失敗；連續失敗會通知）。"""
        now = now or self._clock()
        fired = self._tick_engine(now)
        today = now.strftime("%Y-%m-%d")
        for store, item in self.due_pairs(now):
            try:
                self._fire(item, store.tg_id)
            except Exception:
                logging.exception("[SCHEDULE] item %s failed", item.get("id"))
            if item.get("date"):
                store.remove_id(item["id"])
            else:
                store.mark_run(item["id"], today)
            fired.append(item)
        if self.engine.failed_stores:
            raise EngineDown(f"提醒引擎有 {self.engine.failed_stores} 份清單讀不了")
        return fired

    def _tick_engine(self, now: datetime) -> List[dict]:
        try:
            fired = self.engine.tick(now)
            broken = bool(self.engine.failed_stores)
        except Exception:
            logging.exception("[SCHEDULE] reminder engine failed")
            fired, broken = [], True
            self.engine.failed_stores = max(1, self.engine.failed_stores)
        if broken:
            self.engine_failures += 1
            if self.engine_failures >= ENGINE_ALERT_AFTER and not self.engine_alerted:
                self.engine_alerted = True
                self._alert(T_ENGINE_DOWN.format(n=self.engine_failures))
        else:
            if self.engine_alerted:
                self._alert(T_ENGINE_BACK)
            self.engine_failures = 0
            self.engine_alerted = False
        return fired

    def _alert(self, text: str) -> None:
        try:
            from synox import notify
            notify.owner(self.app, text, kind="safety", level="warn")
        except Exception:
            logging.exception("[SCHEDULE] cannot tell the owner the reminder engine is down")

    def _owner_of(self, item: dict, store_owner: Optional[int]) -> int:
        return int(store_owner if store_owner is not None else (item.get("owner") or self.app.owner_id))

    def _fire(self, item: dict, store_owner: Optional[int] = None) -> None:
        # 伺服器版：每人一份的檔案是誰的就以誰的身分跑（不信檔案裡寫的 owner）
        owner = self._owner_of(item, store_owner)
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
