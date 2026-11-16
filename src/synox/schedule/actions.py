"""
延後與完成（docs/adr/0028 §3.3 ReminderActions）：使用者在任何管道按了「完成／知道了／延後」，送達層回頭叫這裡。
登記在 app.extras["synox_reminder_actions"]（delivery.ACTIONS_EXTRA）。

- act(uid, rid, occurrence, action, until=, typed=, via=)：
  done／ack → 這一次結束（一次性：done；每天型：記進 history、等下一天）；snooze → 延後到 until（ISO），
  或解析 typed（「15:30」「+2h」「半小時後」「明天 9 點」，見 timeparse），都沒給＝5 分鐘後。
  然後 delivery.resolve 讓其他管道收掉（按鈕拿掉、字改成「✅ 在電腦上做完了」）。
  冪等：同一次已經處理過（或不是正在響的那一次）回 ok=False、reason="gone"。
- on_delivery(uid, rid, occurrence, record)：某個管道的送達紀錄變了 → 寫進提醒的 deliveries[管道]。不丟例外。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from synox.notify import delivery
from synox.schedule import reminder as R
from synox.schedule import timeparse
from synox.schedule.engine import close_occurrence, ring_key
from synox.schedule.reminder import Reminder

SNOOZE_DEFAULT_MIN = 5
VIA_TEXT = {"telegram": "Telegram 上", "discord": "Discord 上", "web": "網頁上", "desktop": "電腦上",
            "command": "聊天裡", "chat": "聊天裡"}
GONE = "這則提醒已經處理過了。"


def via_text(via: str) -> str:
    return VIA_TEXT.get(via, "別的地方")


class Actions:
    """delivery.ReminderActions 的實作。store＝ScheduleStore（根）；resolve(uid, key, note=, via=)。"""

    def __init__(self, store, *, resolve: Optional[Callable[..., Any]] = None,
                 clock: Callable[[], datetime] = datetime.now):
        self.store = store
        self._resolve = resolve
        self._clock = clock

    def act(self, uid: int, rid: int, occurrence: str, action: str, *, until: Optional[str] = None,
            typed: str = "", via: str = "") -> delivery.ActionOutcome:
        now = R.aware(self._clock())
        if action not in ("done", "ack", "snooze"):
            return delivery.ActionOutcome(False, "bad_action", "看不懂要做什麼。")
        target = None
        if action == "snooze":
            target, problem = self._snooze_target(now, until, typed)
            if target is None:
                return delivery.ActionOutcome(False, "bad_time", problem)
        st = self.store.of(int(uid))
        box: dict = {}

        def apply(rem: Reminder) -> Reminder:
            if rem.status not in (R.RINGING, R.SNOOZED) or rem.occurrence != occurrence:
                return rem
            box["key"] = ring_key(rem, int(uid))
            if action == "snooze":
                box["ok"] = True
                return replace(rem, status=R.SNOOZED, snooze_until=R.to_iso(target), snooze_count=rem.snooze_count + 1)
            box["ok"] = True
            return close_occurrence(rem, R.DONE, now, via=via)

        found, _ = st.update_reminder(int(rid), apply)
        if not found or not box.get("ok"):
            return delivery.ActionOutcome(False, "gone", GONE)
        if action == "snooze":
            hhmm = timeparse.hm(R.aware(target).astimezone(R.local_tz()))
            note = f"⏰ 在{via_text(via)}延後到 {hhmm}"
            self._resolved(uid, box["key"], note, via)
            return delivery.ActionOutcome(True, "", f"好，{hhmm} 再叫你一次。", note)
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

    def _resolved(self, uid: int, key: str, note: str, via: str) -> None:
        if self._resolve is None:
            return
        try:
            self._resolve(int(uid), key, note=note, via=via)
        except NotImplementedError:
            pass
        except Exception:
            logging.exception("[REMIND] resolve failed")


__all__ = ["Actions", "GONE", "SNOOZE_DEFAULT_MIN", "via_text"]
