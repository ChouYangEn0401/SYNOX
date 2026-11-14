"""
每個人一份的通知清單（網頁的 🔔）：data/notifications/<id>.json(.enc)。

    {"rev": 7, "next_id": 5,
     "items": [{"id": 4, "rev": 7, "at": 1731550000, "kind": "alarm", "level": "alarm", "text": "⏰ 提醒：吃藥",
                "read": false, "actions": [{"id": "snooze", "label": "5 分鐘後再提醒"}], "data": {...}}],
     "prefs": {"off": {"greeting": ["web"]}, "set": true},   # 哪一類不要送到哪裡（沒存過＝用預設）
     "keys": {"alarm:3:2026-11-14 08:00": 1731550000}}       # 送過的 key（同一件事不重送）

- 有保管箱 → 用那個人的金鑰加密（跟網頁對話紀錄同一套：vault.for_user(id).at(folder)）；沒有 → 明文 json。
- 只留最近 KEEP 則；keys 只留最近 KEYS_KEPT 個。
- rev：每次新增或改動 +1，網頁每幾秒問「rev 比 N 新的有哪些」。
- 記憶體快取一份，寫入時同步存檔（輪詢不用每次解密）。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Dict, List, Optional

from isdtelekit.core import jsonstore

KEEP = 100
KEYS_KEPT = 300
FOLDER = "notifications"


def _empty() -> dict:
    return {"rev": 0, "next_id": 1, "items": [], "prefs": {}, "keys": {}}


class NotifyStore:

    def __init__(self, folder: str, vault=None, clock: Callable[[], float] = time.time, keep: int = KEEP):
        self.folder = folder
        self._vault = vault
        self._clock = clock
        self.keep = keep
        self._lock = threading.RLock()
        self._cache: Dict[int, dict] = {}

    # ── 檔案 ─────────────────────────────────────────────────────────

    def _user_vault(self, tg_id: int):
        return self._vault.for_user(tg_id).at(self.folder) if self._vault is not None else None

    def path(self, tg_id: int) -> str:
        vault = self._user_vault(tg_id)
        return vault.path(str(int(tg_id))) if vault is not None else os.path.join(self.folder, f"{int(tg_id)}.json")

    def _data(self, tg_id: int) -> dict:
        tg_id = int(tg_id)
        data = self._cache.get(tg_id)
        if data is None:
            vault = self._user_vault(tg_id)
            try:
                data = vault.load_json(str(tg_id), None) if vault is not None else \
                    jsonstore.load_json(self.path(tg_id), None)
            except Exception:                       # 壞掉的檔：從空的開始（不要讓通知拖垮主動通知）
                data = None
            if not isinstance(data, dict):
                data = _empty()
            for k, v in _empty().items():
                data.setdefault(k, v)
            self._cache[tg_id] = data
        return data

    def _save(self, tg_id: int) -> None:
        data = self._cache[int(tg_id)]
        os.makedirs(self.folder, exist_ok=True)
        vault = self._user_vault(tg_id)
        if vault is not None:
            vault.save_json(str(int(tg_id)), data)
        else:
            jsonstore.save_json(self.path(tg_id), data)

    # ── 通知 ─────────────────────────────────────────────────────────

    def add(self, tg_id: int, text: str, *, kind: str, level: str = "info", actions: Optional[List[dict]] = None,
            data: Optional[dict] = None) -> dict:
        with self._lock:
            d = self._data(tg_id)
            d["rev"] += 1
            item = {"id": d["next_id"], "rev": d["rev"], "at": int(self._clock()), "kind": kind, "level": level,
                    "text": str(text), "read": False, "actions": list(actions or []), "data": dict(data or {})}
            d["next_id"] += 1
            d["items"].append(item)
            del d["items"][:-self.keep]
            self._save(tg_id)
            return dict(item)

    def get(self, tg_id: int, item_id: int) -> Optional[dict]:
        with self._lock:
            for it in self._data(tg_id)["items"]:
                if it.get("id") == item_id:
                    return dict(it)
            return None

    def since(self, tg_id: int, rev: int = 0) -> dict:
        """rev 比這個新的（rev=0＝全部）＋現在的 rev、沒讀的數目。"""
        with self._lock:
            d = self._data(tg_id)
            items = [dict(it) for it in d["items"] if it.get("rev", 0) > rev]
            return {"rev": d["rev"], "unread": sum(1 for it in d["items"] if not it.get("read")), "items": items}

    def mark_read(self, tg_id: int, item_id: Optional[int] = None) -> int:
        """item_id=None＝全部已讀。回改了幾則。"""
        with self._lock:
            d = self._data(tg_id)
            n = 0
            for it in d["items"]:
                if not it.get("read") and (item_id is None or it.get("id") == item_id):
                    d["rev"] += 1
                    it["read"] = True
                    it["rev"] = d["rev"]
                    n += 1
            if n:
                self._save(tg_id)
            return n

    def update(self, tg_id: int, item_id: int, *, actions=None, read: Optional[bool] = None, **data) -> bool:
        """改一則（例如按了「5 分鐘後再提醒」→ 按鈕拿掉、標成已讀、data 記下做了什麼）。"""
        with self._lock:
            d = self._data(tg_id)
            for it in d["items"]:
                if it.get("id") == item_id:
                    d["rev"] += 1
                    it["rev"] = d["rev"]
                    if actions is not None:
                        it["actions"] = list(actions)
                    if read is not None:
                        it["read"] = bool(read)
                    it.setdefault("data", {}).update(data)
                    self._save(tg_id)
                    return True
            return False

    # ── 同一件事不重送 ───────────────────────────────────────────────

    def seen_key(self, tg_id: int, key: str, within: float) -> bool:
        with self._lock:
            at = self._data(tg_id)["keys"].get(key)
            return at is not None and (within <= 0 or self._clock() - at < within)

    def remember_key(self, tg_id: int, key: str) -> None:
        with self._lock:
            d = self._data(tg_id)
            keys = d["keys"]
            keys.pop(key, None)
            keys[key] = int(self._clock())
            while len(keys) > KEYS_KEPT:
                keys.pop(next(iter(keys)))
            self._save(tg_id)

    # ── 設定：哪一類送到哪裡 ─────────────────────────────────────────

    def prefs(self, tg_id: int) -> dict:
        with self._lock:
            prefs = self._data(tg_id).get("prefs") or {}
            return {"off": {k: list(v) for k, v in (prefs.get("off") or {}).items()}, "set": bool(prefs.get("set"))}

    def save_prefs(self, tg_id: int, off: Dict[str, List[str]]) -> None:
        with self._lock:
            d = self._data(tg_id)
            d["prefs"] = {"off": {k: sorted(set(v)) for k, v in off.items() if v}, "set": True}
            d["rev"] += 1
            self._save(tg_id)
