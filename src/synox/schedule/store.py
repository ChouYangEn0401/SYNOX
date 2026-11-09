"""排程的資料：一份清單。有保管箱就存 data/schedule.json.enc（提醒的文字也是私人的），沒有就 data/schedule.json。"""

from __future__ import annotations

import os
import threading
import time
from typing import List, Optional

from isdtelekit.core import jsonstore

NAME = "schedule"


class ScheduleStore:

    def __init__(self, data_dir: str, vault=None):
        self._vault = vault
        self._path = os.path.join(data_dir, NAME + ".json")
        self._lock = threading.RLock()

    def _load(self) -> List[dict]:
        data = self._vault.load_json(NAME, []) if self._vault is not None else jsonstore.load_json(self._path, [])
        return data if isinstance(data, list) else []

    def _save(self, items: List[dict]) -> None:
        if self._vault is not None:
            self._vault.save_json(NAME, items)
        else:
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
