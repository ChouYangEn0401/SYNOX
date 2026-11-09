"""
一個資料夾只跑一支 bot：兩支用同一個 token 會同時 getUpdates（Telegram 回 409、互相踢掉），
也會同時寫同一份 users.json。

    other = claim_lock("data/host.lock")
    if other:
        raise SystemExit(f"已經有一支在跑（pid {other}）")

鎖檔記的是 pid＋行程建立時間：pid 會被別的程式重用，兩個都對得上才算「那一支還活著」。
沒有建立時間可以比的平台（非 Windows）就只看 pid 還在不在。
"""

from __future__ import annotations

import os
from typing import Optional

from isdtelekit.core.jsonstore import load_json, save_json
from isdtelekit.jobs.runner import process_created


def claim_lock(path: str) -> Optional[int]:
    """另一支還活著就回傳它的 pid（呼叫端結束自己）；沒有就寫上自己，回 None。"""
    held = load_json(path, {})
    held = held if isinstance(held, dict) else {}
    pid, created = held.get("pid"), held.get("created")
    if pid and int(pid) != os.getpid() and _alive(int(pid), created):
        return int(pid)
    save_json(path, {"pid": os.getpid(), "created": process_created(os.getpid())})
    return None


def release_lock(path: str) -> None:
    """結束時把鎖拿掉（是自己的才拿）。"""
    held = load_json(path, {})
    if isinstance(held, dict) and held.get("pid") == os.getpid():
        try:
            os.remove(path)
        except OSError:
            pass


def _alive(pid: int, created) -> bool:
    now = process_created(pid)
    if now is None:
        return False
    return created is None or now == created
