"""範圍（ADR 0025 §3）：每個指令收誰叫。只能收緊；沒寫＝今天的行為。

    scope.restrict("money.export", callers=("human",), stepup=True)
    scope.allows(node, "ai")        → False（只收人）
    scope.always_stepup(node)       → True（一定要先解鎖；沒設定驗證器的人不能用）

對照表放在 SYNOX 這邊（不動 vendor 的 Node）；工具的 `pack.json` 的 `callers`／`stepup` 由 loader 掛上來，
重新載入時 `clear_prefix` 先清掉那個工具的。判斷在 `policy.decide`。
"""

from __future__ import annotations

import threading
from typing import Dict, Iterable, Optional

CALLERS = ("human", "remote", "ai", "schedule", "system")
TEXT = {
    "caller": "🔐 這個動作要你本人在 Telegram 或 SYNOX 網頁做。",
}
CALLER_WORDS = {"human": "你本人（Telegram、網頁、終端機）", "remote": "手機入口", "ai": "AI", "schedule": "排程",
                "system": "SYNOX 自己的背景工作"}


class Scope:
    def __init__(self):
        self._map: Dict[str, dict] = {}
        self._mu = threading.Lock()

    def restrict(self, path: str, *, callers: Optional[Iterable[str]] = None, stepup: bool = False) -> None:
        with self._mu:
            entry = dict(self._map.get(path) or {})
            if callers is not None:
                wanted = tuple(c for c in CALLERS if c in set(callers))
                if not wanted:
                    raise ValueError("callers must be a non-empty subset of CALLERS")
                old = entry.get("callers")
                entry["callers"] = wanted if old is None else tuple(c for c in old if c in wanted)  # 只會更緊
            if stepup:
                entry["stepup"] = True
            self._map[path] = entry

    def clear_prefix(self, prefix: str) -> None:
        """重新載入一個工具前清掉它的（prefix＝群組名）。"""
        with self._mu:
            for key in [k for k in self._map if k == prefix or k.startswith(prefix + ".")]:
                del self._map[key]

    def allows(self, node, caller: str) -> bool:
        if node is None or getattr(node, "is_group", False):
            return True
        entry = self._map.get(node.path)
        if not entry or entry.get("callers") is None:
            return True
        return caller in entry["callers"]

    def always_stepup(self, node) -> bool:
        if node is None or getattr(node, "is_group", False):
            return False
        return bool((self._map.get(node.path) or {}).get("stepup"))

    def of(self, path: str) -> dict:
        entry = self._map.get(path) or {}
        return {"callers": list(entry["callers"]) if entry.get("callers") else None,
                "stepup": bool(entry.get("stepup"))}
