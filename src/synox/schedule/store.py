"""
排程的資料：一份清單。有保管箱就存 data/schedule.json.enc（提醒的文字也是私人的），沒有就 data/schedule.json。

伺服器版（per_user=True）：每個人一份 data/users/<id>/schedule.json(.enc)，金鑰是那個人的（vault.for_user）。
  store.of(user) 拿那個人的；runner 用 all_stores() 掃全部人。個人版 of() 就是共用的那一份（照舊）。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from isdtelekit.core import jsonstore

from synox.vault.vault import SUFFIX, USERS_DIR

NAME = "schedule"


def is_todo(it: dict) -> bool:
    return it.get("v") == 2 and it.get("repeat") == "none"


def visible(it: dict) -> bool:
    """清單上看得到嗎（舊格式、/schedule_* 的一律看得到）。"""
    if not isinstance(it, dict) or it.get("v") != 2 or it.get("kind") != "remind":
        return True
    status = it.get("status")
    if status in ("done", "dismissed", "missed", "cancelled", "expired"):
        return False
    if it.get("repeat") == "once" and status == "ringing":
        return False                     # 響過了、等人按（或還在重送）：以前這時候就從清單刪掉了
    return True


class ScheduleStore:

    def __init__(self, data_dir: str, vault=None, *, per_user: bool = False, tg_id: Optional[int] = None):
        self._vault = vault
        self._data_dir = data_dir
        self._path = os.path.join(data_dir, NAME + ".json")
        self._lock = threading.RLock()
        self.per_user = per_user
        self.tg_id = tg_id                     # 伺服器版每人一份時：這份是誰的
        self._scoped: Dict[int, "ScheduleStore"] = {}
        self._listeners: List[Callable[[], None]] = []   # 清單存檔之後叫（排程馬上重看：新提醒、延後）；每人一份的共用同一串

    def add_listener(self, fn: Callable[[], None]) -> None:
        """清單有寫入（新增、改、刪、延後…）之後叫 fn()（在寫入的那條執行緒、還拿著清單的鎖時叫：要快，不要等別的執行緒來讀這份清單；例外只記 log）。"""
        self._listeners.append(fn)

    def _changed(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                logging.exception("[SCHEDULE] change listener failed")

    # ── 每人一份 ─────────────────────────────────────────────────────

    def of(self, user) -> "ScheduleStore":
        if not self.per_user:
            return self
        tg_id = user if isinstance(user, int) and not isinstance(user, bool) else getattr(user, "tg_id", None)
        if not isinstance(tg_id, int) or isinstance(tg_id, bool):
            raise ValueError("schedule store .of(user) needs a user with an integer tg_id")
        with self._lock:
            found = self._scoped.get(tg_id)
            if found is None:
                folder = os.path.join(self._data_dir, USERS_DIR, str(tg_id))
                vault = self._vault.for_user(tg_id) if self._vault is not None else None
                found = self._scoped[tg_id] = ScheduleStore(folder, vault, tg_id=tg_id)
                found._listeners = self._listeners
            return found

    def all_stores(self) -> List["ScheduleStore"]:
        """runner 掃的那些：個人版＝自己；伺服器版＝data/users/<id>/ 底下有排程檔的每個人。"""
        if not self.per_user:
            return [self]
        base = os.path.join(self._data_dir, USERS_DIR)
        found = set()
        if os.path.isdir(base):
            for name in os.listdir(base):
                if not name.isdigit():
                    continue
                folder = os.path.join(base, name)
                if os.path.exists(os.path.join(folder, NAME + SUFFIX)) or \
                        os.path.exists(os.path.join(folder, NAME + ".json")):
                    found.add(int(name))
        with self._lock:
            found |= set(self._scoped)
        return [self.of(tg_id) for tg_id in sorted(found)]

    # ── 清單 ─────────────────────────────────────────────────────────

    def _load(self) -> List[dict]:
        data = self._vault.load_json(NAME, []) if self._vault is not None else jsonstore.load_json(self._path, [])
        return data if isinstance(data, list) else []

    def _save(self, items: List[dict]) -> None:
        if self._vault is not None:
            self._vault.save_json(NAME, items)
        else:
            os.makedirs(self._data_dir, exist_ok=True)
            jsonstore.save_json(self._path, items)
        self._changed()

    @property
    def lock(self):
        return self._lock

    def raw_items(self) -> List[dict]:
        """檔案裡的全部（含已經響過、等送達結果的提醒）：給提醒引擎。"""
        with self._lock:
            return self._load()

    def items(self, kind: Optional[str] = None) -> List[dict]:
        """清單上看得到的（/remind_list、/schedule_list、網頁鬧鐘、remove_nth 都照這個順序）：
        提醒＝有時間的在前、待辦在後；響過了等人按的一次性提醒、已經處理完的不列（以前「響過就刪」，看起來一樣）。"""
        with self._lock:
            shown = [it for it in self._load() if (kind is None or it.get("kind") == kind) and visible(it)]
        if kind == "remind":
            shown.sort(key=lambda it: 1 if is_todo(it) else 0)
        return shown

    def add_reminder(self, build: Callable[[int], "object"]) -> dict:
        """新的一筆提醒／待辦（v2）：build(新 id) → reminder.Reminder。回存進去的 dict。"""
        with self._lock:
            items = self._load()
            rem = build(max([int(it.get("id", 0) or 0) for it in items] + [0]) + 1)
            data = rem.to_dict()
            items.append(data)
            self._save(items)
            return data

    def upgrade_all(self) -> List[dict]:
        """讀檔、把舊格式的提醒轉成 v2（reminder.upgrade_item）存回去；讀不懂的原樣留著（記 log、不刪）。回全部。"""
        from synox.schedule import reminder
        with self._lock:
            items = self._load()
            out, changed = [], False
            for it in items:
                if isinstance(it, dict) and it.get("kind") == reminder.KIND and not reminder.is_v2(it):
                    up = reminder.upgrade_item(it)
                    if up is None:
                        logging.warning("[SCHEDULE] reminder %s: time unreadable, left as is", it.get("id"))
                        out.append(it)
                        continue
                    out.append(up)
                    changed = True
                else:
                    out.append(it)
            if changed:
                self._save(out)
            return out

    def update_reminder(self, rid: int, fn: Callable[["object"], "object"]) -> Tuple[bool, "object"]:
        """改一筆提醒（v2）：fn(Reminder) → Reminder（存回去）｜None（從清單拿掉）。回 (找到了嗎, fn 的回傳)。
        舊格式的先轉；讀不懂的不動（找不到）。"""
        from synox.schedule import reminder
        with self._lock:
            items = self._load()
            for i, it in enumerate(items):
                if not isinstance(it, dict) or it.get("kind") != reminder.KIND or it.get("id") != rid:
                    continue
                data = it if reminder.is_v2(it) else reminder.upgrade_item(it)
                if data is None:
                    return False, None
                try:
                    rem = reminder.Reminder.from_dict(data)
                except ValueError:
                    return False, None
                result = fn(rem)
                if result is None:
                    del items[i]
                else:
                    items[i] = result.to_dict()
                self._save(items)
                return True, result
            return False, None

    def add(self, kind: str, time_hhmm: str, owner: int, *, text: str = "", command: str = "",
            date: str = "") -> dict:
        """舊的加法（v1 格式；/schedule_add、通知中心的「5 分鐘後再提醒」）。提醒引擎讀到時自動轉成 v2。"""
        with self._lock:
            items = self._load()
            item = {"id": max([it.get("id", 0) for it in items] + [0]) + 1, "kind": kind, "time": time_hhmm,
                    "date": date, "text": text, "command": command, "owner": owner, "last_run": "",
                    "created": int(time.time())}
            items.append(item)
            self._save(items)
            return item

    def remove_nth(self, kind: str, n: int) -> Optional[dict]:
        """這一類的第 n 個（照 *_list 顯示的順序，從 1 開始）。"""
        with self._lock:
            items = self._load()
            mine = self.items(kind)
            mine = [next(it for it in items if it == shown) for shown in mine]
            if not 0 < n <= len(mine):
                return None
            gone = mine[n - 1]
            self._save([it for it in items if it is not gone])
            return gone

    def remove_id(self, item_id: int) -> None:
        with self._lock:
            self._save([it for it in self._load() if it.get("id") != item_id])

    def mark_run(self, item_id: int, date: str) -> None:
        with self._lock:
            items = self._load()
            for it in items:
                if it.get("id") == item_id:
                    it["last_run"] = date
            self._save(items)
