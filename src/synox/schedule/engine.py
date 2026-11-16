"""
提醒引擎（docs/adr/0028 §3.1「到點與補送」）：讀排程清單裡的提醒（kind=remind），到點就經過送達層送出。

    engine = ReminderEngine(store, deliver=lambda msg: app_deliver(app, msg), resolve=…)
    engine.tick(now)            # runtime 任務 system.schedule 每 30 秒叫；提醒哨兵用 reminder.headless_engine

1. 讀檔時舊格式自動轉 v2（reminder.upgrade_item），存回去；讀不懂的原樣留著、不響、不刪。
2. 到點＝「due ≤ 現在、而且這一次（occurrence）還沒處理」；多叫幾次結果一樣。
   每天型只看最近的那一次（更早的不補）；同一分鐘裡建立的照響（以前的行為）。
3. 晚 ≤ 60 分鐘：照常響（帶「知道了」「5 分鐘後再提醒」），寫晚了幾分鐘；60 分鐘～6 小時：一則一則「你錯過了」；
   超過 6 小時：這一輪所有這種的併成一則。
4. 送出一律 deliver(Message(key=message_key(...), ref=ReminderRef(...)))——引擎自己不寫任何送出的程式。
   deliver 丟例外＝這一次沒處理，下一輪再試；送了但沒有任何管道成功＝還在響（ringing），每一輪再叫一次 deliver
   （送達層同一個 key 不重送，只回現況），**不刪**。
5. ringing 超過 24 小時沒人按 → expired，叫 resolve 讓其他管道收掉。
6. 每天型一次結束：結果記進 history（最多 10 筆），due 推到下一天、回 pending。
   一次性的處理完（done／missed／expired／cancelled）、而且沒有管道還在重試，才從清單拿掉。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from synox.notify import delivery
from synox.schedule import reminder as R
from synox.schedule.reminder import Reminder

RING_LATE = timedelta(minutes=R.RING_LATE_MAX_MIN)
MISSED_NOTICE = timedelta(hours=R.MISSED_NOTICE_MAX_H)
EXPIRE_AFTER = timedelta(hours=R.EXPIRE_AFTER_H)
CLOSED_KEEP = timedelta(hours=R.MISSED_NOTICE_MAX_H + 1)    # 處理完了還在等送達結果：最多留這麼久
DIGEST_SHOW = 10

T_OK = "知道了"
T_SNOOZE = "5 分鐘後再提醒"
LATE_WHY = "剛剛電腦可能睡著了，或 SYNOX 沒在跑。"
EXPIRED_NOTE = "⌛ 24 小時沒人回，先收起來了。"
MISSED_MARK = "（錯過了）"           # 電腦視窗卡片上：補送的「你錯過了」只有「完成」一顆鍵
BTN_DONE = "done"                   # 同 notify.desk.BTN_DONE


def _labels() -> Tuple[str, str]:
    try:
        from synox.notify.hub import T
        return T.get("ok", T_OK), T.get("snooze", T_SNOOZE)
    except Exception:
        return T_OK, T_SNOOZE


def local(dt: datetime) -> datetime:
    """帶時區 → 本機、不帶時區（給 notify.alarms.friendly 與舊欄位）。"""
    return R.aware(dt).astimezone(R.local_tz()).replace(tzinfo=None)


def friendly(dt: datetime, now: datetime) -> str:
    from synox.notify.alarms import friendly as f
    return f(local(dt), local(now))


def ring_text(text: str, *, late_min: int = 0, snooze_count: int = 0) -> str:
    body = f"⏰ 提醒：{text}"
    if snooze_count:
        body += f"\n（延後第 {snooze_count} 次之後）"
    if late_min > 0:
        body += f"\n（晚了 {late_min} 分鐘才叫你：{LATE_WHY}）"
    return body


def missed_text(when: str, text: str) -> str:
    return f"⏰ 你錯過了 1 個鬧鐘：{when} {text}\n（那時候 SYNOX 沒在跑，或電腦睡著了，所以沒叫到你。）"


def digest_text(lines: List[str], daily: bool) -> str:
    n = len(lines)
    shown = lines[:DIGEST_SHOW]
    body = f"⏰ 有 {n} 個提醒在 SYNOX 沒開（或電腦睡著）的時候過了：\n" + "\n".join("・" + x for x in shown)
    if n > len(shown):
        body += f"\n…還有 {n - len(shown)} 個"
    if daily:
        body += "\n（每天的提醒從下一次起照常響。）"
    return body


def ring_key(rem: Reminder, owner: int) -> str:
    key = delivery.message_key(rem.id, rem.occurrence or "", owner)
    return key + (f"#s{rem.snooze_count}" if rem.snooze_count else "")


def records_of(ticket: Any) -> Dict[str, Dict[str, Any]]:
    recs = getattr(ticket, "records", None)
    if not isinstance(recs, dict):
        return {}
    out = {}
    for ch, r in recs.items():
        out[str(ch)] = r.to_dict() if hasattr(r, "to_dict") else dict(r)
    return out


def notified(rem: Reminder) -> bool:
    return any(r.get("state") == delivery.SENT for r in rem.deliveries.values())


def settled(rem: Reminder) -> bool:
    """沒有任何管道還在重試／等確認。"""
    return all(r.get("next_try") is None and r.get("state") not in (delivery.QUEUED, delivery.FAILED)
               for r in rem.deliveries.values())


def removable(rem: Reminder, now: datetime) -> bool:
    if rem.status not in R.CLOSED or rem.repeat == R.DAILY:
        return False
    if rem.status == R.CANCELLED or settled(rem):
        return True
    closed = R.from_iso(rem.done_at)
    return closed is not None and now - closed >= CLOSED_KEEP


def _wall(rem: Reminder) -> Tuple[int, int]:
    at = local(rem.due_at)
    return at.hour, at.minute


def slot_on(day: datetime, hm: Tuple[int, int]) -> datetime:
    """本機那一天的那一刻（帶時區）。"""
    return R.aware(day.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0, tzinfo=None))


def next_daily(occ: datetime, hm: Tuple[int, int]) -> datetime:
    return slot_on(local(occ) + timedelta(days=1), hm)


def occurrence_due(rem: Reminder, now: datetime) -> Optional[datetime]:
    """這一筆（pending）現在該處理的那一次；沒有＝None。"""
    due = rem.due_at
    if due is None:
        return None
    if rem.repeat == R.ONCE:
        return due if due <= now else None
    hm = _wall(rem)
    now_l = local(now)
    slot = slot_on(now_l, hm)
    if slot > now:
        slot = slot_on(now_l - timedelta(days=1), hm)
    if slot >= due:
        return slot
    # 同一分鐘：剛建立的「每天 08:00」在 08:00 那一分鐘照響（以前的行為），今天還沒處理過才算
    if (now - slot) < timedelta(minutes=1) and rem.last_run != local(slot).strftime("%Y-%m-%d"):
        return slot
    return None


def _history(rem: Reminder, status: str, via: str = "") -> List[Dict[str, Any]]:
    hist = list(rem.history) + [{"occurrence": rem.occurrence, "status": status, "via": via}]
    return hist[-R.HISTORY_KEEP:]


def close_occurrence(rem: Reminder, status: str, now: datetime, via: str = "") -> Reminder:
    """這一次結束：每天型記 history、回 pending（due 早就推到下一天）；一次性的改成 status。"""
    if rem.repeat == R.DAILY:
        return replace(rem, status=R.PENDING, history=_history(rem, status, via), occurrence=None, rang_at=None,
                       snooze_until=None, snooze_count=0, deliveries={}, done_at=R.to_iso(now), done_via=via)
    return replace(rem, status=status, done_at=R.to_iso(now), done_via=via, snooze_until=None)


STATUS_FILE = "engine.json"        # data/remind/engine.json：上一次到點檢查（給健康檢查；沒有個人資料）


def status_path(data_dir: str) -> str:
    from synox.notify import desk as deskmod
    return os.path.join(deskmod.remind_dir(data_dir), STATUS_FILE)


def write_status(data_dir: str, who: str, last_tick: float, failed_stores: int) -> None:
    """記下「誰在什麼時候檢查過」（主程式／哨兵）。寫不進去只記 log，不影響提醒。"""
    from synox.notify import desk as deskmod
    try:
        deskmod._write_json(deskmod.remind_dir(data_dir), STATUS_FILE,
                            {"v": 1, "who": who, "last_tick": float(last_tick), "failed_stores": int(failed_stores),
                             "pid": os.getpid()})
    except Exception as e:
        logging.warning("[REMIND] cannot write engine status: %s", type(e).__name__)


def read_status(data_dir: str) -> Optional[Dict[str, Any]]:
    try:
        with open(status_path(data_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class ReminderEngine:
    """reminder.Engine 的實作。store＝ScheduleStore（個人版一份、伺服器版 all_stores() 每人一份）。
    status_dir（選填）：每一輪把「誰、幾點檢查過」寫進 data/remind/engine.json（who＝app｜sentinel）。"""

    def __init__(self, store, deliver: Callable[[delivery.Message], Any], *,
                 resolve: Optional[Callable[..., Any]] = None, owner_default: Optional[int] = None,
                 status_dir: Optional[str] = None, who: str = "app"):
        self.store = store
        self._deliver = deliver
        self._resolve = resolve
        self.owner_default = owner_default
        self.status_dir = status_dir
        self.who = who
        self.failed_stores = 0
        self.last_tick: Optional[float] = None

    # ── 一輪 ─────────────────────────────────────────────────────────

    def tick(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        now = R.aware(now or datetime.now())
        fired: List[Dict[str, Any]] = []
        self.failed_stores = 0
        for st in self.store.all_stores():
            try:
                fired += self._tick_store(st, now)
            except Exception:
                self.failed_stores += 1
                logging.exception("[REMIND] engine failed on one list")
        self.last_tick = time.time()
        if self.status_dir:
            write_status(self.status_dir, self.who, self.last_tick, self.failed_stores)
        return fired

    def _owner(self, st, rem: Reminder) -> int:
        if getattr(st, "tg_id", None) is not None:
            return int(st.tg_id)                       # 伺服器版：檔案是誰的就是誰的（不信檔案裡寫的 owner）
        return int(rem.owner or self.owner_default or 0)

    def _tick_store(self, st, now: datetime) -> List[Dict[str, Any]]:
        fired: List[Dict[str, Any]] = []
        digest: List[Tuple[Reminder, datetime]] = []
        for data in st.upgrade_all():
            if not R.is_v2(data):
                continue
            try:
                rem = Reminder.from_dict(data)
            except ValueError:
                logging.warning("[REMIND] reminder %s: bad record, left as is", data.get("id"))
                continue
            try:
                done = self._one(st, rem, now, digest)
            except Exception:
                logging.exception("[REMIND] reminder %s failed", rem.id)
                continue
            if done is not None:
                fired.append(done)
        if digest:
            self._send_digest(st, digest, now)
        return fired

    def _one(self, st, rem: Reminder, now: datetime, digest: list) -> Optional[Dict[str, Any]]:
        owner = self._owner(st, rem)
        if rem.status in R.CLOSED:
            if removable(rem, now):
                st.update_reminder(rem.id, lambda r: None)
            return None
        if rem.repeat == R.NONE:
            return None
        if rem.status in (R.RINGING, R.SNOOZED):
            rang = R.from_iso(rem.rang_at)
            if rem.repeat == R.DAILY and rem.due_at is not None and rem.due_at <= now:
                rem = self._close(st, rem, owner, R.EXPIRED, now, note=EXPIRED_NOTE)     # 下一天到了：上一次收掉
                if rem is None:
                    return None
            elif rem.status == R.RINGING and rang is not None and now - rang >= EXPIRE_AFTER:
                self._close(st, rem, owner, R.EXPIRED, now, note=EXPIRED_NOTE)
                return None
            elif rem.status == R.SNOOZED:
                until = R.from_iso(rem.snooze_until)
                if until is None or until > now:
                    return None
                late = int((now - until).total_seconds() // 60)
                return self._ring(st, rem, owner, now, R.from_iso(rem.occurrence) or until,
                                  late_min=late if late <= R.RING_LATE_MAX_MIN else 0, snoozed=True)
            else:
                if not notified(rem):
                    self._redeliver(st, rem, owner, now)
                return None
        occ = occurrence_due(rem, now)
        if occ is None:
            return None
        late = now - occ
        if late <= RING_LATE:
            return self._ring(st, rem, owner, now, occ, late_min=int(late.total_seconds() // 60))
        if late <= MISSED_NOTICE:
            self._missed(st, rem, owner, now, occ)
            return None
        digest.append((rem, occ))
        return None

    # ── 動作 ─────────────────────────────────────────────────────────

    def _send(self, msg: delivery.Message) -> Any:
        return self._deliver(msg)

    def _ring(self, st, rem: Reminder, owner: int, now: datetime, occ: datetime, *, late_min: int,
              snoozed: bool = False) -> Optional[Dict[str, Any]]:
        occ_iso = R.to_iso(occ)
        rem_now = replace(rem, occurrence=occ_iso)
        if not snoozed:
            rem_now = replace(rem_now, snooze_count=0)
        ok, snooze = _labels()
        msg = delivery.Message(
            key=ring_key(rem_now, owner), uid=owner,
            text=ring_text(rem.text, late_min=late_min, snooze_count=rem_now.snooze_count),
            kind="alarm", level="alarm", actions=[{"id": "ok", "label": ok}, {"id": "snooze", "label": snooze}],
            data={"text": rem.text, "alarm": rem.id, "rid": rem.id, "occurrence": occ_iso},
            ref=delivery.ReminderRef(rem.id, occ_iso),
            desktop={"text": rem.text, "when": friendly(occ, now), "late_min": late_min,
                     "snooze_count": rem_now.snooze_count})
        logging.info("[REMIND] reminder %s rings → %s", rem.id, owner)
        ticket = self._send(msg)                     # 丟例外：不改任何東西，下一輪再試
        records = records_of(ticket)

        def apply(r: Reminder) -> Reminder:
            r = replace(r, status=R.RINGING, occurrence=occ_iso, rang_at=R.to_iso(now), deliveries=records,
                        snooze_until=None, snooze_count=rem_now.snooze_count)
            if r.repeat == R.DAILY and not snoozed:
                r = replace(r, due=R.to_iso(next_daily(occ, _wall(rem))), last_run=local(occ).strftime("%Y-%m-%d"))
            return r
        st.update_reminder(rem.id, apply)
        return {**rem.to_dict(), "occurrence": occ_iso, "late_min": late_min}

    def _redeliver(self, st, rem: Reminder, owner: int, now: datetime) -> None:
        """響著、卻還沒有任何管道成功：再交給送達層一次（同一個 key＝不重送，只回現況；舊路沒有佇列＝再試一次）。"""
        ok, snooze = _labels()
        occ = R.from_iso(rem.occurrence)
        msg = delivery.Message(key=ring_key(rem, owner), uid=owner, text=ring_text(rem.text, snooze_count=rem.snooze_count),
                               kind="alarm", level="alarm",
                               actions=[{"id": "ok", "label": ok}, {"id": "snooze", "label": snooze}],
                               data={"text": rem.text, "alarm": rem.id, "rid": rem.id, "occurrence": rem.occurrence},
                               ref=delivery.ReminderRef(rem.id, rem.occurrence or ""),
                               desktop={"text": rem.text, "when": friendly(occ, now) if occ is not None else "",
                                        "late_min": 0, "snooze_count": rem.snooze_count})
        records = records_of(self._send(msg))
        if records:
            st.update_reminder(rem.id, lambda r: replace(r, deliveries=records) if r.occurrence == rem.occurrence else r)

    def _missed(self, st, rem: Reminder, owner: int, now: datetime, occ: datetime) -> None:
        occ_iso = R.to_iso(occ)
        ok, _ = _labels()
        msg = delivery.Message(key=delivery.message_key(rem.id, occ_iso, owner), uid=owner,
                               text=missed_text(friendly(occ, now), rem.text), kind="alarm", level="alarm",
                               actions=[{"id": "ok", "label": ok}],
                               data={"text": rem.text, "missed": True, "rid": rem.id, "occurrence": occ_iso},
                               ref=delivery.ReminderRef(rem.id, occ_iso),
                               desktop={"text": f"{MISSED_MARK}{rem.text}", "when": friendly(occ, now),
                                        "late_min": int((now - occ).total_seconds() // 60), "buttons": [BTN_DONE]})
        logging.info("[REMIND] reminder %s missed → %s", rem.id, owner)
        records = records_of(self._send(msg))
        st.update_reminder(rem.id, lambda r: self._mark_missed(r, occ, now, records))

    def _mark_missed(self, r: Reminder, occ: datetime, now: datetime, records: Dict[str, Any]) -> Reminder:
        r = replace(r, occurrence=R.to_iso(occ), deliveries=records)
        if r.repeat == R.DAILY:
            r = replace(r, due=R.to_iso(next_daily(occ, _wall(r))), last_run=local(occ).strftime("%Y-%m-%d"))
        return close_occurrence(r, R.MISSED, now, via="auto")

    def _send_digest(self, st, items: List[Tuple[Reminder, datetime]], now: datetime) -> None:
        by_owner: Dict[int, List[Tuple[Reminder, datetime]]] = {}
        for rem, occ in items:
            by_owner.setdefault(self._owner(st, rem), []).append((rem, occ))
        for owner, mine in by_owner.items():
            mine.sort(key=lambda p: p[1])
            ids = ",".join(f"{r.id}@{R.to_iso(o)}" for r, o in mine)
            key = f"rem:{owner}:digest:" + hashlib.sha256(ids.encode("utf-8")).hexdigest()[:16]
            lines = [f"{friendly(o, now)} {r.text}" for r, o in mine]
            ok, _ = _labels()
            msg = delivery.Message(key=key, uid=owner, text=digest_text(lines, any(r.repeat == R.DAILY for r, _ in mine)),
                                   kind="alarm", level="alarm", actions=[{"id": "ok", "label": ok}],
                                   data={"missed": True, "digest": [r.id for r, _ in mine]})
            logging.info("[REMIND] %d old reminders folded into one notice → %s", len(mine), owner)
            try:
                records = records_of(self._send(msg))
            except Exception:
                logging.exception("[REMIND] digest failed")
                continue
            for rem, occ in mine:
                st.update_reminder(rem.id, lambda r, occ=occ: self._mark_missed(r, occ, now, records))

    def _close(self, st, rem: Reminder, owner: int, status: str, now: datetime, *, note: str = "",
               via: str = "auto") -> Optional[Reminder]:
        key = ring_key(rem, owner)
        _found, result = st.update_reminder(
            rem.id, lambda r: close_occurrence(r, status, now, via) if r.occurrence == rem.occurrence else r)
        self.resolve(owner, key, note=note, via=via)
        return result

    def resolve(self, owner: int, key: str, *, note: str = "", via: str = "") -> None:
        if self._resolve is None:
            return
        try:
            self._resolve(owner, key, note=note, via=via)
        except NotImplementedError:
            pass
        except Exception:
            logging.exception("[REMIND] resolve failed")


# ── 在 App 裡：送達層（W2）還沒接上時，退回通知中心現在的送法 ─────────────────

def app_deliver(app, msg: delivery.Message) -> Any:
    try:
        return delivery.deliver(app, msg)
    except NotImplementedError:
        return hub_deliver(app, msg)


def app_resolve(app, uid: int, key: str, *, note: str = "", via: str = "") -> None:
    try:
        delivery.resolve(app, uid, key, note=note, via=via)
    except NotImplementedError:
        pass


def hub_deliver(app, msg: delivery.Message) -> delivery.DeliveryTicket:
    """舊路（送達層還沒合併時）：Hub.notify 一次送完、不重試；把它回的結果換成 DeliveryTicket。"""
    from synox import notify
    now = time.time()
    hub = notify.of(app)

    def sent(ch: str) -> delivery.DeliveryRecord:
        return delivery.DeliveryRecord(ch, state=delivery.SENT, tries=1, first_try=now, last_try=now, ok_at=now)

    ticket = delivery.DeliveryTicket(msg.key, msg.uid)
    if hub is None:
        app.notify(msg.uid, msg.text)
        ticket.records[delivery.CHAT] = sent(delivery.CHAT)
        return ticket
    out = hub.notify(msg.uid, msg.text, kind=msg.kind, level=msg.level, key=msg.key, actions=msg.actions,
                     data=msg.data)
    if out.get("skipped") == "dup":
        ticket.records[delivery.WEB] = sent(delivery.WEB)          # 之前送過了
        return ticket
    if out.get(delivery.WEB) is not None:
        ticket.records[delivery.WEB] = sent(delivery.WEB)
    for ch in (delivery.TELEGRAM, delivery.DISCORD, delivery.CHAT):
        if out.get(ch):
            ticket.records[ch] = sent(ch)
    return ticket


__all__ = ["ReminderEngine", "STATUS_FILE", "app_deliver", "app_resolve", "close_occurrence", "hub_deliver",
           "notified", "occurrence_due", "read_status", "removable", "ring_key", "ring_text", "settled", "status_path",
           "write_status"]
