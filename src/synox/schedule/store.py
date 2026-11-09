"""
排程的資料：一份清單。有保管箱就存 data/schedule.json.enc（提醒的文字也是私人的），沒有就 data/schedule.json。

伺服器版（per_user=True）：每個人一份 data/users/<id>/schedule.json(.enc)，金鑰是那個人的（vault.for_user）。
  store.of(user) 拿那個人的；runner 用 all_stores() 掃全部人。個人版 of() 就是共用的那一份（照舊）。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional

from isdtelekit.core import jsonstore

from synox.vault.vault import SUFFIX, USERS_DIR

NAME = "schedule"


class ScheduleStore:

    def __init__(self, data_dir: str, vault=None, *, per_user: bool = False, tg_id: Optional[int] = None):
        self._vault = vault
        self._data_dir = data_dir
        self._path = os.path.join(data_dir, NAME + ".json")
        self._lock = threading.RLock()
        self.per_user = per_user
        self.tg_id = tg_id                     # 伺服器版每人一份時：這份是誰的
        self._scoped: Dict[int, "ScheduleStore"] = {}

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

    def items(self, kind: Optional[str] = None) -> List[dict]:
        with self._lock:
            return [it for it in self._load() if kind is None or it.get("kind") == kind]

    def add(self, kind: str, time_hhmm: str, owner: int, *, text: str = "", command: str = "",
            date: str = "") -> dict:
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
            mine = [it for it in items if it.get("kind") == kind]
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
