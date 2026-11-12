"""
config.json 的 `runtime` 這一塊：預設值與檢查（docs/adr/0001）。只用標準函式庫，config.py 直接 import。

    "runtime": {
      "heartbeat": {"enabled": true, "interval_min": 45, "quiet_hours": "23:00-08:00",
                    "daily_max_notify": 4, "daily_max_calls": 40},
      "mother": {"enabled": true, "memory_turns": 20, "read_chat": true, "soul_append": true}
    }
"""

from __future__ import annotations

import copy
import re
from typing import Optional, Tuple

MIN_INTERVAL_MIN = 15
MAX_INTERVAL_MIN = 1440

DEFAULT_RUNTIME = {
    "heartbeat": {"enabled": True, "interval_min": 45, "quiet_hours": "23:00-08:00",
                  "daily_max_notify": 4, "daily_max_calls": 40},
    "mother": {"enabled": True, "memory_turns": 20, "read_chat": True, "soul_append": True},
}

_HHMM = r"([01]\d|2[0-3]):([0-5]\d)"
QUIET_RE = re.compile(rf"^{_HHMM}-{_HHMM}$")


class RuntimeConfigError(ValueError):
    """config.json 的 runtime 寫錯；訊息是給人看的一句話（config.py 轉成 ConfigError）。"""


def defaults() -> dict:
    return copy.deepcopy(DEFAULT_RUNTIME)


def interval_problem(value) -> str:
    """心跳間隔（分鐘）合不合法：""＝合法。bool、小數、字串都不收（網頁與 config.json 共用這一句）。"""
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_INTERVAL_MIN <= value <= MAX_INTERVAL_MIN:
        return f"間隔要是 {MIN_INTERVAL_MIN}～{MAX_INTERVAL_MIN} 的整數（分鐘）。"
    return ""


def parse_quiet(text: str) -> Optional[Tuple[int, int]]:
    """"23:00-08:00" → (1380, 480)（一天裡的第幾分鐘）；空字串 → None（沒有安靜時段）。格式錯丟 RuntimeConfigError。"""
    text = (text or "").strip()
    if not text:
        return None
    m = QUIET_RE.match(text)
    if not m:
        raise RuntimeConfigError("runtime.heartbeat.quiet_hours 要寫成 \"HH:MM-HH:MM\"（例如 \"23:00-08:00\"），或空字串＝不設。")
    start, end = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
    return start, end


def in_quiet(quiet: Optional[Tuple[int, int]], minute_of_day: int) -> bool:
    """跨午夜也算（23:00-08:00）；開始＝結束＝沒有安靜時段。"""
    if quiet is None:
        return False
    start, end = quiet
    if start == end:
        return False
    if start < end:
        return start <= minute_of_day < end
    return minute_of_day >= start or minute_of_day < end


def _bool(section: dict, key: str, where: str) -> bool:
    value = section[key]
    if not isinstance(value, bool):
        raise RuntimeConfigError(f"runtime.{where}.{key} 要是 true 或 false。")
    return value


def _int(section: dict, key: str, where: str, low: int, high: int) -> int:
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise RuntimeConfigError(f"runtime.{where}.{key} 要是 {low}～{high} 的整數。")
    return value


def parse(raw) -> dict:
    """config.json 的 runtime（可以沒寫）→ 補好預設、檢查過的 dict。錯丟 RuntimeConfigError。"""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RuntimeConfigError("config.json 的 runtime 要是一個 {…} 物件。")
    out = defaults()
    for name in ("heartbeat", "mother"):
        section = raw.get(name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise RuntimeConfigError(f"config.json 的 runtime.{name} 要是一個 {{…}} 物件。")
        out[name].update(section)
    hb, mother = out["heartbeat"], out["mother"]
    _bool(hb, "enabled", "heartbeat")
    problem = interval_problem(hb["interval_min"])
    if problem:
        raise RuntimeConfigError("runtime.heartbeat.interval_min：" + problem)
    if not isinstance(hb["quiet_hours"], str):
        raise RuntimeConfigError("runtime.heartbeat.quiet_hours 要是字串（\"23:00-08:00\" 或 \"\"）。")
    hb["quiet_hours"] = hb["quiet_hours"].strip()
    parse_quiet(hb["quiet_hours"])
    _int(hb, "daily_max_notify", "heartbeat", 0, 48)
    _int(hb, "daily_max_calls", "heartbeat", 0, 200)
    for key in ("enabled", "read_chat", "soul_append"):
        _bool(mother, key, "mother")
    _int(mother, "memory_turns", "mother", 0, 100)
    return out
