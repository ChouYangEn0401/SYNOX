"""安全紀錄（ADR 0025 §4）：`data/security_audit.jsonl`，一行一件事。

    Audit(path, clock).write("stepup_fail", by=42, origin="telegram", target="", ok=False, code="bad", tries=3)

- 一行：時間、事件、誰、來源、對象、成功與否、固定的原因代碼、只收數字的額外欄位。
  **沒有任何自由文字、沒有值、沒有碼、沒有金鑰**：event／origin／target／code 只收短的識別字（不合的換成 "?"）。
- 1 MB 換檔，留一份（`.1`）；寫檔持鎖。寫不進去只記 log，不讓呼叫端失敗。
這個檔不 import synox 的其他模組。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Callable, List

FILE = "security_audit.jsonl"
MAX_BYTES = 1 << 20
_IDENT = re.compile(r"^[A-Za-z0-9_.:@/-]{0,80}$")


def _ident(value) -> str:
    s = str(value or "")
    return s if _IDENT.match(s) else "?"


class Audit:
    def __init__(self, path: str, clock: Callable[[], float] = time.time, max_bytes: int = MAX_BYTES):
        self.path, self.clock, self.max_bytes = path, clock, int(max_bytes)
        self._mu = threading.Lock()

    def write(self, event: str, *, by: int = 0, origin: str = "", target: str = "", ok: bool = True, code: str = "",
              **nums) -> None:
        try:
            by_id = int(by or 0)
        except (TypeError, ValueError):
            by_id = 0
        row = {"t": round(float(self.clock()), 3), "event": _ident(event), "by": by_id, "origin": _ident(origin),
               "target": _ident(target), "ok": bool(ok), "code": _ident(code)}
        for key, value in nums.items():
            if _IDENT.match(str(key)) and isinstance(value, (int, float)) and not isinstance(value, bool):
                row[str(key)] = value
        line = json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n"
        with self._mu:
            try:
                folder = os.path.dirname(self.path)
                if folder:
                    os.makedirs(folder, exist_ok=True)
                if os.path.exists(self.path) and os.path.getsize(self.path) + len(line) > self.max_bytes:
                    os.replace(self.path, self.path + ".1")
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError as e:
                logging.warning("[AUDIT] cannot write: %s", type(e).__name__)

    def tail(self, limit: int = 50) -> List[dict]:
        with self._mu:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-int(limit):]
            except OSError:
                return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
