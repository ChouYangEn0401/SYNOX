"""
config.json 的 `health` 這一塊（選填）：預設值與檢查（docs/tool-health.md）。只用標準函式庫，config.py 直接 import。

    "health": {"enabled": true, "consecutive": 3, "window_count": 5, "window_s": 600, "untrusted_consecutive": 2,
               "cooldowns_s": [300, 900, 3600, 21600, 86400], "flip_limit": 3, "flip_window_s": 86400,
               "daily_trials": 4, "prompt_lines": 5, "trust_self_report": true, "check_interval_s": 60}
"""

from __future__ import annotations

import copy

DEFAULT_HEALTH = {
    "enabled": True,                 # false＝整個健康管理關掉（所有工具當成正常）
    "consecutive": 3,                # 同一指紋連續幾次 → broken
    "window_count": 5,               # 或 window_s 秒內幾次
    "window_s": 600,
    "untrusted_consecutive": 2,      # 沒有宣告合約（沒有 failure 物件）的工具、匯入的工具（MCP）
    "cooldowns_s": [300, 900, 3600, 21600, 86400],
    "flip_limit": 3,                 # flip_window_s 內好壞反覆幾次 → quarantined
    "flip_window_s": 86400,
    "daily_trials": 4,               # 沒有自我檢查的工具：一天最多放回清單試用幾次
    "prompt_lines": 5,               # 系統提示最後「暫時不能用的功能」最多幾行
    "trust_self_report": True,       # 工具自己說 needs_config／dependency_missing／auth_expired／needs_update → 立刻標壞
    "check_interval_s": 60,          # runtime 任務 system.health 多久看一次
}
_INTS = {"consecutive": (1, 100), "window_count": (1, 1000), "window_s": (10, 86400), "untrusted_consecutive": (1, 100),
         "flip_limit": (2, 100), "flip_window_s": (60, 7 * 86400), "daily_trials": (0, 100), "prompt_lines": (0, 20),
         "check_interval_s": (10, 3600)}
_BOOLS = ("enabled", "trust_self_report")


class HealthConfigError(ValueError):
    """config.json 的 health 寫錯；訊息是給人看的一句話（config.py 轉成 ConfigError）。"""


def defaults() -> dict:
    return copy.deepcopy(DEFAULT_HEALTH)


def parse(raw) -> dict:
    """config.json 的 health（可以沒寫）→ 補好預設、檢查過的 dict。錯丟 HealthConfigError。"""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise HealthConfigError("config.json 的 health 要是一個 {…} 物件。")
    unknown = sorted(k for k in raw if k not in DEFAULT_HEALTH)
    if unknown:
        raise HealthConfigError(f"config.json 的 health 不認得 {'、'.join(unknown)}"
                                f"（只收 {'、'.join(DEFAULT_HEALTH)}；見 docs/tool-health.md）。")
    out = defaults()
    out.update(raw)
    for key in _BOOLS:
        if not isinstance(out[key], bool):
            raise HealthConfigError(f"health.{key} 要是 true 或 false。")
    for key, (low, high) in _INTS.items():
        value = out[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise HealthConfigError(f"health.{key} 要是 {low}～{high} 的整數。")
    cool = out["cooldowns_s"]
    if not isinstance(cool, list) or not 1 <= len(cool) <= 10 or \
            any(isinstance(c, bool) or not isinstance(c, int) or not 10 <= c <= 7 * 86400 for c in cool):
        raise HealthConfigError("health.cooldowns_s 要是 1～10 個整數（秒，10～604800），例如 [300, 900, 3600, 21600, 86400]。")
    if any(b < a for a, b in zip(cool, cool[1:])):
        raise HealthConfigError("health.cooldowns_s 要一段比一段長（或一樣長）。")
    out["cooldowns_s"] = list(cool)
    return out


__all__ = ["DEFAULT_HEALTH", "HealthConfigError", "defaults", "parse"]
