"""驗證器的保管（ADR 0025 §5.2）：存進保管箱（密文）。保管箱的名字 `stepup`。

- 個人版：一份 `stepup`，裡面 {"users": {"<id>": {...}}}（個人版的成員也能設定，各自一格）。
- 伺服器版：每個人自己的保管箱（`vault.for_user(id)`）裡一份 `stepup`。
- 保管箱打不開（`vault is None`）：用 `NullStore`（永遠沒設定、存不進去），什麼都不保護＝跟沒有這個功能一樣。
"""

from __future__ import annotations

import threading
from typing import Dict, Optional

NAME = "stepup"


class MemoryStore:
    """測試用：只在記憶體。"""

    def __init__(self):
        self._data: Dict[int, dict] = {}
        self._mu = threading.Lock()

    def load(self, user_id: int) -> Optional[dict]:
        with self._mu:
            found = self._data.get(int(user_id))
            return dict(found) if found else None

    def save(self, user_id: int, data: dict) -> None:
        with self._mu:
            self._data[int(user_id)] = dict(data)

    def delete(self, user_id: int) -> None:
        with self._mu:
            self._data.pop(int(user_id), None)


class NullStore:
    def load(self, user_id: int) -> Optional[dict]:
        return None

    def save(self, user_id: int, data: dict) -> None:
        raise RuntimeError("vault unavailable")

    def delete(self, user_id: int) -> None:
        return None


class VaultStore:
    def __init__(self, vault, server_mode: bool):
        self.vault, self.server_mode = vault, bool(server_mode)
        self._mu = threading.Lock()

    def _box(self, user_id: int):
        return self.vault.for_user(int(user_id)) if self.server_mode else self.vault

    def load(self, user_id: int) -> Optional[dict]:
        with self._mu:
            raw = self._box(user_id).load_json(NAME, None)
        if not isinstance(raw, dict):
            return None
        if not self.server_mode:
            raw = (raw.get("users") or {}).get(str(int(user_id)))
        return dict(raw) if isinstance(raw, dict) else None

    def save(self, user_id: int, data: dict) -> None:
        with self._mu:
            box = self._box(user_id)
            if self.server_mode:
                box.save_json(NAME, dict(data))
                return
            raw = box.load_json(NAME, None)
            users = dict((raw or {}).get("users") or {}) if isinstance(raw, dict) else {}
            users[str(int(user_id))] = dict(data)
            box.save_json(NAME, {"users": users})

    def delete(self, user_id: int) -> None:
        import os
        with self._mu:
            box = self._box(user_id)
            if self.server_mode:
                if box.exists(NAME):
                    os.remove(box.path(NAME))
                return
            raw = box.load_json(NAME, None)
            users = dict((raw or {}).get("users") or {}) if isinstance(raw, dict) else {}
            if users.pop(str(int(user_id)), None) is not None:
                box.save_json(NAME, {"users": users})
