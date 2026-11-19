"""
延後與完成（docs/adr/0029 §3.3 ReminderActions）：使用者在任何管道按了「完成／知道了／延後／改到別天」，送達層回頭叫這裡。
登記在 app.extras["synox_reminder_actions"]（delivery.ACTIONS_EXTRA）。

- act(uid, rid, occurrence, action, until=, typed=, via=)：
  done（我完成了）→ 這一次結束、記成 done；ack（我知道了）→ 這一次結束、記成 dismissed（不響了，但不算做完）。
  一次性的就此收掉；每天型記進 history、等下一天。
  snooze → 同一次延後到 until（ISO），或解析 typed（「15:30」「+2h」「半小時後」「明天 9 點」，見 timeparse），
  都沒給＝5 分鐘後（卡片寫「延後第 N 次」）。
  reschedule（改到別天）→ 一次性的提醒整個改時間：due＝until／typed，都沒給＝明天同一個時刻；回到 pending、
  不算延後（到時候當新的一次響）。每天型：只能改到下一次之前（＝延後這一次）；改到下一次以後回 bad_time
  （每天的明天本來就會響）。
  然後 delivery.resolve 讓其他管道收掉（按鈕拿掉、字改成「✅ 在電腦上做完了」「📅 在電腦上改到 …」）。
  冪等：同一次已經處理過（或不是正在響的那一次）回 ok=False、reason="gone"。
- on_delivery(uid, rid, occurrence, record)：某個管道的送達紀錄變了 → 寫進提醒的 deliveries[管道]。不丟例外。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from synox.notify import delivery
from synox.schedule import reminder as R
from synox.schedule import timeparse
from synox.schedule.engine import close_occurrence, ring_key
from synox.schedule.reminder import Reminder

SNOOZE_DEFAULT_MIN = 5
VIA_TEXT = {"telegram": " Telegram 上", "discord": " Discord 上", "web": "網頁上", "desktop": "電腦上",
            "command": "聊天裡", "chat": "聊天裡"}
GONE = "這則提醒已經處理過了。"
ACTIONS = ("done", "ack", "snooze", "reschedule")
DAILY_LATER = "每天的提醒下一次本來就會響；要改每天的時間，到「⏰ 提醒」清單改。"


def via_text(via: str) -> str:
    return VIA_TEXT.get(via, "別的地方")


TODO_SHOW = 20                      # 電腦視窗下半部最多幾筆待辦（同 notify.desk.TODO_SHOW）


def todo_list(st) -> List[Dict[str, Any]]:
    """這個人的待辦（沒有時間的），給電腦視窗下半部：[{"rid", "text"}]，照清單順序、最多 TODO_SHOW 筆。"""
    from synox.schedule.store import is_todo
    return [{"rid": int(it["id"]), "text": str(it.get("text", ""))}
            for it in st.items("remind") if is_todo(it)][:TODO_SHOW]


class Actions:
    """delivery.ReminderActions 的實作。store＝ScheduleStore（根）；resolve(uid, key, note=, via=)。
    todos（選填）：todos(uid, items) — 待辦有變動時（在視窗上按掉一筆）把整份交出去（delivery.publish_todos）。"""

    def __init__(self, store, *, resolve: Optional[Callable[..., Any]] = None,
                 clock: Callable[[], datetime] = datetime.now,
                 todos: Optional[Callable[[int, List[Dict[str, Any]]], Any]] = None):
        self.store = store
        self._resolve = resolve
        self._clock = clock
        self._todos = todos

    def publish_todos(self, uid: int) -> None:
        if self._todos is None:
            return
        try:
            self._todos(int(uid), todo_list(self.store.of(int(uid))))
        except Exception:
            logging.exception("[REMIND] publishing todos failed")

    def act(self, uid: int, rid: int, occurrence: str, action: str, *, until: Optional[str] = None,
            typed: str = "", via: str = "") -> delivery.ActionOutcome:
        now = R.aware(self._clock())
        if action not in ACTIONS:
            return delivery.ActionOutcome(False, "bad_action", "看不懂要做什麼。")
        if not occurrence and action in ("done", "ack"):
            return self._todo_done(uid, rid, via)
        target = None
        if action == "snooze":
            target, problem = self._snooze_target(now, until, typed)
            if target is None:
                return delivery.ActionOutcome(False, "bad_time", problem)
        elif action == "reschedule":
            target, problem = self._reschedule_target(now, occurrence, until, typed)
            if target is None:
                return delivery.ActionOutcome(False, "bad_time", problem)
        st = self.store.of(int(uid))
        box: dict = {}

        def apply(rem: Reminder) -> Reminder:
            if rem.status not in (R.RINGING, R.SNOOZED) or rem.occurrence != occurrence:
                return rem
            box["key"] = ring_key(rem, int(uid))
            if action == "reschedule" and rem.repeat == R.DAILY:
                if rem.due_at is not None and target >= rem.due_at:
                    box["problem"] = DAILY_LATER
                    return rem
                box["ok"] = True                         # 每天型：下一次之前＝延後這一次
                return replace(rem, status=R.SNOOZED, snooze_until=R.to_iso(target), snooze_count=rem.snooze_count + 1)
            if action == "reschedule":
                box["ok"] = True
                return replace(rem, status=R.PENDING, due=R.to_iso(target), occurrence=None, rang_at=None,
                               snooze_until=None, snooze_count=0, deliveries={}, done_at=None, done_via="")
            if action == "snooze":
                box["ok"] = True
                return replace(rem, status=R.SNOOZED, snooze_until=R.to_iso(target), snooze_count=rem.snooze_count + 1)
            box["ok"] = True
            return close_occurrence(rem, R.DONE if action == "done" else R.DISMISSED, now, via=via)

        found, _ = st.update_reminder(int(rid), apply)
        if box.get("problem"):
            return delivery.ActionOutcome(False, "bad_time", box["problem"])
        if found and not box.get("ok") and action in ("done", "ack"):
            missed = self._missed_ack(st, uid, rid, occurrence, via)
            if missed is not None:
                return missed
        if not found or not box.get("ok"):
            return delivery.ActionOutcome(False, "gone", GONE)
        if action == "snooze":
            hhmm = timeparse.hm(R.aware(target).astimezone(R.local_tz()))
            note = f"⏰ 在{via_text(via)}延後到 {hhmm}"
            self._resolved(uid, box["key"], note, via)
            return delivery.ActionOutcome(True, "", f"好，{hhmm} 再叫你一次。", note)
        if action == "reschedule":
            when = self._when(target, now)
            note = f"📅 在{via_text(via)}改到 {when}"
            self._resolved(uid, box["key"], note, via)
            return delivery.ActionOutcome(True, "", f"好，改到 {when} 再叫你。", note)
        note = f"✅ 在{via_text(via)}" + ("做完了" if action == "done" else "按了知道了")
        self._resolved(uid, box["key"], note, via)
        return delivery.ActionOutcome(True, "", "好，記下來了。" if action == "done" else "知道了", note)

    def on_delivery(self, uid: int, rid: int, occurrence: str, record: delivery.DeliveryRecord) -> None:
        try:
            data = record.to_dict() if hasattr(record, "to_dict") else dict(record)

            def apply(rem: Reminder) -> Reminder:
                if rem.occurrence != occurrence:
                    return rem
                deliveries = dict(rem.deliveries)
                deliveries[str(data.get("channel", ""))] = data
                return replace(rem, deliveries=deliveries)

            self.store.of(int(uid)).update_reminder(int(rid), apply)
        except Exception:
            logging.exception("[REMIND] on_delivery failed")

    # ── 內部 ─────────────────────────────────────────────────────────

    def _todo_done(self, uid: int, rid: int, via: str) -> delivery.ActionOutcome:
        """待辦（沒有時間、沒有 occurrence）按了完成：從清單拿掉，整份待辦再交出去一次。"""
        st = self.store.of(int(uid))
        found, _ = st.update_reminder(int(rid), lambda r: None if r.is_todo else r)
        still = any(it.get("id") == int(rid) for it in st.items("remind"))
        if not found or still:
            return delivery.ActionOutcome(False, "gone", GONE)
        self.publish_todos(uid)
        return delivery.ActionOutcome(True, "", "好，記下來了。", f"✅ 在{via_text(via)}做完了")

    def _missed_ack(self, st, uid: int, rid: int, occurrence: str, via: str) -> Optional[delivery.ActionOutcome]:
        """「你錯過了」那一則按了知道了／完成：那一次早就記成錯過，這裡只讓其他管道收掉（不算 gone）。"""
        hit = False
        for it in st.raw_items():
            if it.get("id") != int(rid) or not R.is_v2(it):
                continue
            if it.get("status") == R.MISSED and it.get("occurrence") == occurrence:
                hit = True
            elif any(h.get("occurrence") == occurrence and h.get("status") == R.MISSED for h in it.get("history") or []):
                hit = True
        if not hit:
            return None
        note = f"✅ 在{via_text(via)}按了知道了"
        self._resolved(uid, delivery.message_key(int(rid), occurrence, int(uid)), note, via)
        return delivery.ActionOutcome(True, "", "知道了", note)

    def _snooze_target(self, now: datetime, until: Optional[str], typed: str):
        if until:
            try:
                at = R.from_iso(until)
            except ValueError:
                at = None
            if at is None or at <= now:
                return None, "延後的時間要在現在之後。"
            return at, ""
        if typed and typed.strip():
            w = timeparse.parse(typed, now)
            if w.kind == timeparse.AT and w.at is not None:
                at = R.aware(w.at)
                return (at, "") if at > now else (None, "延後的時間要在現在之後。")
            if w.kind == timeparse.PAST and w.at is not None:
                return None, timeparse.past_question(w.at, now.astimezone(R.local_tz()).replace(tzinfo=None))
            if w.kind == timeparse.ASK:
                return None, w.question
            return None, "看不懂這個時間。可以打「15:30」「+2h」「半小時後」「明天 9 點」。"
        return now + timedelta(minutes=SNOOZE_DEFAULT_MIN), ""

    def _reschedule_target(self, now: datetime, occurrence: str, until: Optional[str], typed: str):
        """改到別天的時間：until（ISO）＞ typed（timeparse）＞ 明天同一個時刻（照這一次原本的牆上時間）。"""
        if until or (typed and typed.strip()):
            return self._snooze_target(now, until, typed)
        try:
            occ = R.from_iso(occurrence)
        except ValueError:
            occ = None
        base = (occ or now).astimezone(R.local_tz()).replace(tzinfo=None)
        at = R.aware(base + timedelta(days=1))
        while at <= now:                                  # 響了快一天才按：再往後一天
            at = R.aware(at.astimezone(R.local_tz()).replace(tzinfo=None) + timedelta(days=1))
        return at, ""

    @staticmethod
    def _when(at: datetime, now: datetime) -> str:
        from synox.notify.alarms import friendly
        return friendly(at.astimezone(R.local_tz()).replace(tzinfo=None),
                        now.astimezone(R.local_tz()).replace(tzinfo=None))

    def _resolved(self, uid: int, key: str, note: str, via: str) -> None:
        if self._resolve is None:
            return
        try:
            self._resolve(int(uid), key, note=note, via=via)
        except NotImplementedError:
            pass
        except Exception:
            logging.exception("[REMIND] resolve failed")


__all__ = ["ACTIONS", "Actions", "DAILY_LATER", "GONE", "SNOOZE_DEFAULT_MIN", "TODO_SHOW", "todo_list", "via_text"]
