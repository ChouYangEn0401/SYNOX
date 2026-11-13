"""工具服務的稽核與 log（計畫 C8）：`data/apps_audit.jsonl`，一行一個 JSON，**欄位固定、沒有自由文字**。

- 寫入函式用白名單檢查每個欄位（不在名單的值寫成 "other"），不可能有人把一段文字帶進來。
- **永遠不寫**：參數的值、檔案內容、token、票、cookie、例外的訊息。1 MB 換檔（`.1`，蓋掉舊的）。寫檔持自己的鎖。
- log：這個功能的每個 except 都用 `safe_trace(e)`：例外的類別名＋每一層的「檔名:行號 函式名」，不含 str(e)。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
from datetime import datetime
from typing import Callable, List

FILE = "apps_audit.jsonl"
MAX_BYTES = 1 << 20
EVENTS = ("start", "stop", "auto_stop", "suggest", "keep", "policy", "handoff", "enter", "leave", "action", "export",
          "denied", "error")
VIAS = ("web", "telegram", "app", "system", "remote")
REASONS = ("", "owner", "idle", "shutdown", "web_off", "reload", "blocked", "tampered", "stuck", "host", "proxy",
           "origin", "ticket", "port")
CODES = ("", "login", "origin", "forbidden", "not_found", "invalid", "confirm", "refused", "too_large", "error",
         "export_encrypted_only", "remote_no_export", "remote_no_danger", "busy", "max_running", "unavailable",
         "blocked", "port", "tampered")
EFFECTS = ("", "read", "write", "danger")
MODES = ("", "auto", "suggest", "keep", "blocked")
FIELDS = ("at", "event", "app", "by", "via", "action", "effect", "ok", "code", "confirmed", "port", "bytes", "reason",
          "mode", "close_min")
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _pick(value, allowed) -> str:
    value = "" if value is None else str(value)
    return value if value in allowed else "other"


def _name(value) -> str:
    value = "" if value is None else str(value)
    return value if value == "" or _NAME.match(value) else "other"


def _int(value) -> int:
    try:
        return int(value or 0) if not isinstance(value, bool) else int(value)
    except (TypeError, ValueError):
        return 0


def safe_trace(e: BaseException) -> str:
    """例外的類別名＋每一層「檔名:行號 函式名」；不含訊息、不含原始碼那一行、不含區域變數。"""
    frames = traceback.extract_tb(e.__traceback__) if e is not None else []
    where = "; ".join(f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in frames[-6:])
    return f"{type(e).__name__} at {where}" if where else type(e).__name__


class Audit:
    def __init__(self, path: str, clock: Callable[[], float] = time.time, max_bytes: int = MAX_BYTES):
        self.path, self.clock, self.max_bytes = path, clock, int(max_bytes)
        self._mu = threading.Lock()

    def write(self, event: str, app: str = "", **fields) -> dict:
        row = {"at": datetime.fromtimestamp(self.clock()).isoformat(timespec="seconds"),
               "event": _pick(event, EVENTS), "app": _name(app), "by": _int(fields.get("by")),
               "via": _pick(fields.get("via", ""), VIAS + ("",)), "action": _name(fields.get("action", "")),
               "effect": _pick(str(fields.get("effect", "") or "").lower(), EFFECTS),
               "ok": bool(fields.get("ok", True)), "code": _pick(fields.get("code", ""), CODES),
               "confirmed": bool(fields.get("confirmed", False)), "port": _int(fields.get("port")),
               "bytes": _int(fields.get("bytes")), "reason": _pick(fields.get("reason", ""), REASONS),
               "mode": _pick(fields.get("mode", ""), MODES), "close_min": _int(fields.get("close_min"))}
        line = json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n"
        with self._mu:
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                if os.path.exists(self.path) and os.path.getsize(self.path) + len(line) > self.max_bytes:
                    os.replace(self.path, self.path + ".1")
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                pass
        return row

    def tail(self, limit: int = 50) -> List[dict]:
        with self._mu:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError:
                return []
        out = []
        for line in reversed(lines[-max(1, min(int(limit), 200)):]):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
