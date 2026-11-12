"""
健康狀態的存檔：data/health/tools.json.enc，**經保管箱加密**（synox/vault，跟 pack 資料同一把主金鑰）。
只存狀態、類別碼、次數、時間、指紋雜湊與截短（遮過密鑰）的原因；diag 不存。

- 沒有保管箱（vault=None）＝只在記憶體，不存檔。
- 讀不開（金鑰不對、檔案壞掉）＝`broken=True`：這次執行一律當作沒有任何紀錄、**也不寫回去**
  （保管箱解不開時絕不當成空的再蓋過去，照 vault 的規則），doctor 會說；擁有者處理（刪掉那個檔或修好金鑰）之後重開就好。
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from synox.health.state import Entry

FOLDER = "health"
NAME = "tools"
FORMAT = 1


class HealthStore:

    def __init__(self, vault=None, data_dir: str = ""):
        self._vault = vault.at(os.path.join(data_dir or vault.data_dir, FOLDER)) if vault is not None else None
        self.broken = ""                         # 讀不開的原因（""＝正常）

    @property
    def available(self) -> bool:
        return self._vault is not None and not self.broken

    @property
    def path(self) -> str:
        return self._vault.path(NAME) if self._vault is not None else ""

    def load(self) -> Dict[str, Entry]:
        """讀出所有紀錄；讀不開或格式不對 → {}（並標 broken，之後不寫）。"""
        if self._vault is None:
            return {}
        try:
            data = self._vault.load_json(NAME, None)
            if data is None:
                return {}
            if not isinstance(data, dict) or data.get("v") != FORMAT or not isinstance(data.get("entries"), list):
                raise ValueError("unknown format")
            out: Dict[str, Entry] = {}
            for raw in data["entries"]:
                entry = Entry.from_dict(raw)
                out[entry.key] = entry
            return out
        except Exception as e:
            self.broken = f"{type(e).__name__}: {e}"
            logging.error("[HEALTH] cannot read %s, treating every tool as healthy: %s", NAME, self.broken)
            return {}

    def save(self, entries: List[Entry]) -> bool:
        if not self.available:
            return False
        try:
            self._vault.save_json(NAME, {"v": FORMAT, "entries": [e.to_dict() for e in entries]})
            return True
        except Exception:
            logging.exception("[HEALTH] cannot write %s", NAME)
            return False


def read_only(data_dir: str) -> "tuple[Optional[Dict[str, Entry]], str]":
    """doctor 用：不產生金鑰、不寫檔。回 (紀錄, 問題)；沒有金鑰或沒有檔案 → ({}, "")。"""
    key = os.path.join(data_dir, ".synox.key")
    target = os.path.join(data_dir, FOLDER, NAME + ".json.enc")
    if not os.path.exists(target):
        return {}, ""
    if not os.path.exists(key):
        return None, "有健康紀錄的檔，但保管箱金鑰不在"
    try:
        from synox.vault import Vault
        from synox.vault.keyring import read_key
        store = HealthStore(Vault(read_key(key), data_dir), data_dir)
    except Exception as e:
        return None, f"打不開保管箱（{type(e).__name__}）"
    entries = store.load()
    if store.broken:
        return None, "健康紀錄的檔讀不開（這次執行把每個工具都當成正常）"
    return entries, ""


__all__ = ["HealthStore", "read_only"]
