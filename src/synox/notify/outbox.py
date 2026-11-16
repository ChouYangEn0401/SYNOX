"""
送達佇列（docs/adr/0028 §3.3 的 Outbox 實作）：要確定送到的那幾則，每人一份存檔，重開照樣重試。

    data/notifications/outbox/<id>.json(.enc)     跟通知清單同一套加密（vault.for_user(id).at(folder)）
    {"v": 1, "tickets": {"<key>": {"key", "uid", "created", "msg": {...}, "records": {管道: DeliveryRecord},
                                   "extra": {"nid": 12}, "resolved": false, "resolved_at", "via", "note"}}}

- submit(msg)：同一個 key 再來＝回原本那張 ticket（冪等）。新的：每個管道一筆紀錄，馬上試一次。
- 管道回 SENT 才算送到；FAILED 照 RetryPolicy 排下一次；blocked／bad_token 直接 GAVE_UP；QUEUED（等對方確認，
  例如電腦視窗的 shown）到期還沒確認＝FAILED（desktop 記 no_window），照樣重試。
- pump(now)：試所有到期的。由 runtime 任務 system.notify.outbox 每 15 秒叫（哨兵自己叫）。
- confirm：非同步確認（QUEUED → SENT）。resolve：這一則處理掉了，停止重試、其他管道收回（retract）。
- 送出去的那一刻不拿著資料鎖（網路可能慢）；同一時間只有一個人在送（_send_lock），不會重送。
- 另一個程序（哨兵）也可能寫同一份檔：每次讀之前看檔案有沒有變（mtime），變了就重讀。
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from isdtelekit.core import jsonstore

from synox.notify.delivery import (CHAT, DEFAULT_POLICY, DESKTOP, DISCORD, FAILED, GAVE_UP, QUEUED, RETRACTED, SENT,
                                   SKIPPED, TELEGRAM, DeliveryRecord, DeliveryResult, DeliveryTicket, Message,
                                   ReminderRef, RetryPolicy)

KEEP_S = 24 * 3600              # 處理完（沒有管道還要試）的 ticket 留多久（冪等：W1 再叫一次 deliver 不會重送）
KEEP_MAX = 300                  # 每人最多留幾張
CONFIRM_WAIT_S = 60.0           # QUEUED 沒說要等多久時，等確認的上限
_FILE = re.compile(r"^(\d{1,20})\.json(\.enc)?$")


def message_to_dict(msg: Message) -> Dict[str, Any]:
    return asdict(msg)


def message_from_dict(data: Dict[str, Any]) -> Message:
    names = Message.__dataclass_fields__
    kw = {k: v for k, v in (data or {}).items() if k in names}
    ref = kw.get("ref")
    if isinstance(ref, dict):
        kw["ref"] = ReminderRef(rid=int(ref.get("rid", 0)), occurrence=str(ref.get("occurrence", "")))
    return Message(**kw)


def _error_kind(e: BaseException) -> str:
    name = type(e).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if isinstance(e, (ConnectionError, OSError)) or "connection" in name:
        return "network"
    return "unknown"


class FileOutbox:
    """Outbox 的實作。adapters：管道 id → ChannelAdapter。plan(msg)：這一則要送哪些管道。
    anchor（選填）：prepare(msg, channels) → extra（例如網頁通知清單那一則的 id）；finish(uid, extra, note)：處理掉時收尾。
    listener（選填）：(msg, record) — 某個管道的紀錄變了（給 ReminderActions.on_delivery）。"""

    def __init__(self, folder: str, vault=None, *, adapters: Dict[str, Any], plan: Callable[[Message], List[str]],
                 anchor=None, listener: Optional[Callable[[Message, DeliveryRecord], None]] = None,
                 clock: Callable[[], float] = time.time, policy: RetryPolicy = DEFAULT_POLICY):
        self.folder = folder
        self._vault = vault
        self.adapters = adapters
        self.plan = plan
        self.anchor = anchor
        self.listener = listener
        self.clock = clock
        self.policy = policy
        self._lock = threading.RLock()
        self._send_lock = threading.RLock()
        self._cache: Dict[int, Tuple[Any, dict]] = {}

    # ── 檔案 ─────────────────────────────────────────────────────────

    def _user_vault(self, uid: int):
        return self._vault.for_user(int(uid)).at(self.folder) if self._vault is not None else None

    def path(self, uid: int) -> str:
        vault = self._user_vault(uid)
        return vault.path(str(int(uid))) if vault is not None else os.path.join(self.folder, f"{int(uid)}.json")

    def _stamp(self, uid: int):
        try:
            st = os.stat(self.path(uid))
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _data(self, uid: int) -> dict:
        uid = int(uid)
        stamp = self._stamp(uid)
        cached = self._cache.get(uid)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        data = None
        if stamp is not None:
            vault = self._user_vault(uid)
            try:
                data = vault.load_json(str(uid), None) if vault is not None else jsonstore.load_json(self.path(uid), None)
            except Exception as e:                       # 壞掉的檔：從空的開始，記 log（不記內容）
                logging.warning("[OUTBOX] cannot read queue of %s: %s", uid, type(e).__name__)
                data = None
        if not isinstance(data, dict) or not isinstance(data.get("tickets"), dict):
            data = {"v": 1, "tickets": {}}
        self._cache[uid] = (stamp, data)
        return data

    def _save(self, uid: int) -> None:
        uid = int(uid)
        data = self._cache[uid][1]
        self._prune(data)
        os.makedirs(self.folder, exist_ok=True)
        vault = self._user_vault(uid)
        if vault is not None:
            vault.save_json(str(uid), data)
        else:
            jsonstore.save_json(self.path(uid), data)
        self._cache[uid] = (self._stamp(uid), data)

    def _prune(self, data: dict) -> None:
        now = self.clock()
        tickets = data["tickets"]
        for key in list(tickets):
            t = tickets[key]
            recs = [DeliveryRecord.from_dict(r) for r in (t.get("records") or {}).values()]
            settled = all(r.next_try is None for r in recs)
            last = max([t.get("created") or 0] + [r.last_try or 0 for r in recs] + [t.get("resolved_at") or 0])
            if settled and now - last > KEEP_S:
                del tickets[key]
        if len(tickets) > KEEP_MAX:
            for key in sorted(tickets, key=lambda k: tickets[k].get("created") or 0)[:len(tickets) - KEEP_MAX]:
                del tickets[key]

    def uids(self) -> List[int]:
        """有佇列檔的人（重開之後 pump 要找得到）。"""
        found = set(self._cache)
        try:
            for name in os.listdir(self.folder):
                m = _FILE.match(name)
                if m:
                    found.add(int(m.group(1)))
        except FileNotFoundError:
            pass
        return sorted(found)

    # ── ticket ───────────────────────────────────────────────────────

    @staticmethod
    def _ticket(t: dict) -> DeliveryTicket:
        return DeliveryTicket(key=t["key"], uid=int(t["uid"]),
                              records={c: DeliveryRecord.from_dict(r) for c, r in (t.get("records") or {}).items()})

    def _raw(self, uid: int, key: str) -> Optional[dict]:
        return self._data(uid)["tickets"].get(key)

    def status(self, uid: int, key: str) -> Optional[DeliveryTicket]:
        with self._lock:
            t = self._raw(uid, key)
            return self._ticket(t) if t is not None else None

    def message(self, uid: int, key: str) -> Optional[Message]:
        with self._lock:
            t = self._raw(uid, key)
            return message_from_dict(t["msg"]) if t is not None else None

    def extra(self, uid: int, key: str) -> Dict[str, Any]:
        with self._lock:
            t = self._raw(uid, key)
            return dict((t or {}).get("extra") or {})

    def find(self, uid: int, channel: str, ref_key: str, value) -> Optional[str]:
        """哪一張 ticket 的某個管道 ref[ref_key] == value（例如電腦視窗的 token）→ key。
        同一個 token 可能有好幾張（延後之後再響，引擎給的 key 帶 #s<N>）：還沒處理掉的優先，再來是最新的。"""
        with self._lock:
            found = []
            for key, t in self._data(uid)["tickets"].items():
                rec = (t.get("records") or {}).get(channel)
                if rec and (rec.get("ref") or {}).get(ref_key) == value:
                    found.append((not t.get("resolved"), t.get("created") or 0, key))
            return max(found)[2] if found else None

    # ── 送 ───────────────────────────────────────────────────────────

    def submit(self, msg: Message) -> DeliveryTicket:
        uid = int(msg.uid)
        with self._send_lock:
            with self._lock:
                existing = self._raw(uid, msg.key)
                if existing is not None:
                    return self._ticket(existing)
                now = self.clock()
                try:
                    channels = [c for c in self.plan(msg) if c in self.adapters]
                except Exception as e:
                    logging.warning("[OUTBOX] planning failed: %s", type(e).__name__)
                    channels = []
                extra: Dict[str, Any] = {}
                if self.anchor is not None:
                    try:
                        extra = dict(self.anchor.prepare(msg, channels) or {})
                    except Exception as e:
                        logging.warning("[OUTBOX] anchor failed: %s", type(e).__name__)
                t = {"key": msg.key, "uid": uid, "created": now, "msg": message_to_dict(msg), "extra": extra,
                     "records": {c: DeliveryRecord(c, state=QUEUED, next_try=now).to_dict() for c in channels},
                     "resolved": False, "resolved_at": None, "via": "", "note": ""}
                self._data(uid)["tickets"][msg.key] = t
                self._save(uid)
            self._run(uid, msg.key, now)
            return self.status(uid, msg.key)

    def pump(self, now: Optional[float] = None) -> List[DeliveryTicket]:
        """試所有到期的；QUEUED 等確認等到期的先記成失敗再排重試。回有變動的那些。"""
        now = self.clock() if now is None else now
        changed: List[DeliveryTicket] = []
        with self._send_lock:
            for uid in self.uids():
                with self._lock:
                    keys = [k for k, t in self._data(uid)["tickets"].items()
                            if any(r.get("next_try") is not None and r["next_try"] <= now
                                   for r in (t.get("records") or {}).values())]
                for key in keys:
                    if self._run(uid, key, now):
                        ticket = self.status(uid, key)
                        if ticket is not None:
                            changed.append(ticket)
        return changed

    def _run(self, uid: int, key: str, now: float) -> bool:
        """這一張到期的管道各試一次（呼叫的人拿著 _send_lock）。回有沒有變動。"""
        with self._lock:
            t = self._raw(uid, key)
            if t is None or t.get("resolved"):
                return False
            msg = message_from_dict(t["msg"])
            extra = dict(t.get("extra") or {})
            due = [DeliveryRecord.from_dict(r) for r in t["records"].values()
                   if r.get("next_try") is not None and r["next_try"] <= now]
        if not due:
            return False
        if self.anchor is not None and "nid" not in extra:                 # 第一次掛清單失敗：再試一次
            try:
                extra = dict(self.anchor.prepare(msg, list(t["records"])) or {})
                with self._lock:
                    live = self._raw(uid, key)
                    if live is not None:
                        live["extra"] = extra
            except Exception as e:
                logging.warning("[OUTBOX] anchor failed: %s", type(e).__name__)
        results: List[Tuple[DeliveryRecord, Optional[DeliveryResult]]] = []
        for rec in due:
            if rec.state == QUEUED and rec.tries > 0:                       # 送出去了、等確認、等到期了
                results.append((rec, DeliveryResult(rec.channel, FAILED,
                                                    error="no_window" if rec.channel == DESKTOP else "timeout")))
                continue
            results.append((rec, self._send_one(msg, extra, rec)))
        changes: List[DeliveryRecord] = []
        retract_late: List[DeliveryRecord] = []
        with self._lock:
            live = self._raw(uid, key)
            if live is None:
                return False
            for rec, res in results:
                stored = DeliveryRecord.from_dict(live["records"].get(rec.channel) or rec.to_dict())
                if stored.state in (SENT, RETRACTED, GAVE_UP, SKIPPED) and stored.next_try is None:
                    continue                                                   # 別人（confirm／resolve）先改了
                new = self._apply(rec, res, now)
                if live.get("resolved") and new.state in (SENT, QUEUED):
                    retract_late.append(new)                                   # 送的同時被按掉了：馬上收回
                    new.state, new.next_try = RETRACTED, None
                live["records"][rec.channel] = new.to_dict()
                changes.append(new)
            note = live.get("note", "")
            self._save(uid)
        for rec in retract_late:
            self._retract(msg, rec, note)
        for rec in changes:
            self._tell(msg, rec)
        return bool(changes)

    def _send_one(self, msg: Message, extra: Dict[str, Any], rec: DeliveryRecord) -> DeliveryResult:
        adapter = self.adapters.get(rec.channel)
        if adapter is None:
            return DeliveryResult(rec.channel, SKIPPED)
        data = {**(msg.data or {}), **extra, "_try": rec.tries + 1, "_last_error": rec.error}
        one = Message(**{**message_to_dict(msg), "data": data, "ref": msg.ref})
        try:
            if not adapter.available(int(msg.uid)):
                return DeliveryResult(rec.channel, SKIPPED)
            res = adapter.send(one)
        except Exception as e:
            logging.warning("[OUTBOX] %s → %s failed: %s", rec.channel, msg.uid, type(e).__name__)
            return DeliveryResult(rec.channel, FAILED, error=_error_kind(e))
        if not isinstance(res, DeliveryResult):
            return DeliveryResult(rec.channel, FAILED, error="unknown")
        return res

    def _apply(self, rec: DeliveryRecord, res: DeliveryResult, now: float) -> DeliveryRecord:
        rec = DeliveryRecord.from_dict(rec.to_dict())
        timed_out = rec.state == QUEUED and rec.tries > 0 and res.state == FAILED and res.error in ("no_window", "timeout")
        if not timed_out:                                       # 等確認到期不算新的一次嘗試（送那一次已經算過了）
            rec.tries += 1
            rec.last_try = now
            if rec.first_try is None:
                rec.first_try = now
        if res.ref:
            rec.ref = {**rec.ref, **res.ref}
        if res.state == SENT:
            rec.state, rec.ok_at, rec.next_try, rec.error = SENT, now, None, ""
        elif res.state == QUEUED:
            wait = res.retry_after if res.retry_after else CONFIRM_WAIT_S
            rec.state, rec.next_try, rec.error = QUEUED, now + float(wait), ""
        elif res.state == SKIPPED:
            rec.state, rec.next_try = SKIPPED, None
        else:
            rec.error = res.error or "unknown"
            if res.permanent:
                rec.state, rec.next_try = GAVE_UP, None
            else:
                at = self.policy.next_try(rec, now, res.retry_after)
                rec.state, rec.next_try = (FAILED, at) if at is not None else (GAVE_UP, None)
            logging.info("[OUTBOX] %s failed (%s), tries=%s, next=%s", rec.channel, rec.error, rec.tries,
                         "give up" if rec.next_try is None else int(rec.next_try - now))
        return rec

    def _tell(self, msg: Message, rec: DeliveryRecord) -> None:
        if self.listener is None:
            return
        try:
            self.listener(msg, rec)
        except Exception as e:
            logging.warning("[OUTBOX] listener failed: %s", type(e).__name__)

    # ── 確認、處理掉 ─────────────────────────────────────────────────

    def confirm(self, uid: int, key: str, channel: str, ref: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            t = self._raw(uid, key)
            if t is None or channel not in t["records"]:
                return
            rec = DeliveryRecord.from_dict(t["records"][channel])
            if rec.state not in (QUEUED, FAILED):
                return
            now = self.clock()
            rec.state, rec.ok_at, rec.next_try, rec.error = SENT, now, None, ""
            if ref:
                rec.ref = {**rec.ref, **ref}
            t["records"][channel] = rec.to_dict()
            self._save(uid)
            msg = message_from_dict(t["msg"])
        self._tell(msg, rec)

    def resolve(self, uid: int, key: str, *, note: str = "", via: str = "") -> None:
        with self._lock:
            t = self._raw(uid, key)
            if t is None:
                return
            first = not t.get("resolved")
            t["resolved"], t["resolved_at"], t["via"], t["note"] = True, self.clock(), via, note
            msg = message_from_dict(t["msg"])
            extra = dict(t.get("extra") or {})
            todo: List[DeliveryRecord] = []
            stopped: List[DeliveryRecord] = []
            for channel, raw in t["records"].items():
                rec = DeliveryRecord.from_dict(raw)
                if channel == via:                                    # 就是在這裡按的：一定送到了
                    if rec.next_try is not None:
                        rec.next_try = None
                        if rec.state in (QUEUED, FAILED):
                            rec.state, rec.ok_at, rec.error = SENT, rec.ok_at or self.clock(), ""
                        stopped.append(rec)
                elif rec.state in (SENT, QUEUED, FAILED):
                    todo.append(rec)
                    rec.state, rec.next_try = RETRACTED, None
                t["records"][channel] = rec.to_dict()
            self._save(uid)
        for rec in todo:
            self._retract(msg, rec, note)
        if first and self.anchor is not None:
            try:
                self.anchor.finish(int(uid), extra, note)
            except Exception as e:
                logging.warning("[OUTBOX] anchor finish failed: %s", type(e).__name__)
        for rec in todo + stopped:
            self._tell(msg, rec)

    def _retract(self, msg: Message, rec: DeliveryRecord, note: str) -> None:
        adapter = self.adapters.get(rec.channel)
        if adapter is None or rec.tries == 0:                          # 還沒送過：沒有東西要收
            return
        text = f"{msg.text}\n{note}" if note and rec.channel in (TELEGRAM, DISCORD, CHAT) else note
        try:
            adapter.retract(rec, text)
        except Exception as e:
            logging.warning("[OUTBOX] retract %s failed: %s", rec.channel, type(e).__name__)


__all__ = ["CONFIRM_WAIT_S", "FileOutbox", "KEEP_MAX", "KEEP_S", "message_from_dict", "message_to_dict"]
