"""
伺服器版：成員的 AI 每月額度（美元）。

- 每個人的用量：data/users/<id>/llm_usage.json（跟 data/llm_usage.json 同一種格式，多一個 usd）。
  全部的總帳仍記在 data/llm_usage.json（營運者看的）。
- 額度：config.json 的 ai_member_monthly_usd（預設 2.0）；管理員可以替某個人另外設（/ai_budget <id> <美元>，
  存在 data/ai_budgets.json）。擁有者沒有額度。
- 價錢：token 換美元用 llm.price_in／llm.price_out（每百萬 token 多少美元）；沒寫就用保守的預設
  （輸入 3、輸出 15，約等於中階雲端模型）。本機模型可以設成 0。
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from isdtelekit.core import jsonstore

from synox.vault.vault import USERS_DIR

EXHAUSTED = "這個月的 AI 額度用完了，請管理員加"
DEFAULT_PRICE_IN = 3.0          # 美元／百萬 token
DEFAULT_PRICE_OUT = 15.0
BUDGETS_FILE = "ai_budgets.json"


def _price(llm: dict, key: str, default: float) -> float:
    try:
        return max(0.0, float(llm.get(key, default)))
    except (TypeError, ValueError):
        return default


class MemberBudget:

    def __init__(self, app, config):
        self.app = app
        self.data_dir = config.data_dir
        self.default_usd = float(getattr(config, "ai_member_monthly_usd", 2.0))
        llm = getattr(config, "llm", {}) or {}
        self.price_in = _price(llm, "price_in", DEFAULT_PRICE_IN)
        self.price_out = _price(llm, "price_out", DEFAULT_PRICE_OUT)
        self._lock = threading.Lock()
        self._books = {}

    # ── 用量 ─────────────────────────────────────────────────────────

    def cost(self, usage: dict) -> float:
        usage = usage or {}
        return (int(usage.get("input", 0) or 0) * self.price_in +
                int(usage.get("output", 0) or 0) * self.price_out) / 1_000_000

    def book(self, tg_id: int):
        from synox.agent.loop import UsageBook
        with self._lock:
            found = self._books.get(tg_id)
            if found is None:
                path = os.path.join(self.data_dir, USERS_DIR, str(int(tg_id)), "llm_usage.json")
                found = self._books[tg_id] = UsageBook(path)
            return found

    def record(self, tg_id: int, usage: dict) -> float:
        usd = self.cost(usage)
        if usage:
            os.makedirs(os.path.join(self.data_dir, USERS_DIR, str(int(tg_id))), exist_ok=True)
            self.book(tg_id).record(usage, usd=usd)
        return usd

    def month_usd(self, tg_id: int) -> float:
        return float(self.book(tg_id).summary()["month"].get("usd", 0.0))

    # ── 額度 ─────────────────────────────────────────────────────────

    def _overrides(self) -> dict:
        data = jsonstore.load_json(os.path.join(self.data_dir, BUDGETS_FILE), {})
        return data if isinstance(data, dict) else {}

    def limit(self, tg_id: int) -> float:
        value = self._overrides().get(str(int(tg_id)))
        try:
            return float(value) if value is not None else self.default_usd
        except (TypeError, ValueError):
            return self.default_usd

    def set_limit(self, tg_id: int, usd: Optional[float]) -> None:
        with self._lock:
            data = self._overrides()
            if usd is None:
                data.pop(str(int(tg_id)), None)
            else:
                data[str(int(tg_id))] = round(max(0.0, float(usd)), 4)
            jsonstore.save_json(os.path.join(self.data_dir, BUDGETS_FILE), data)

    def exempt(self, user) -> bool:
        return self.app.registry.is_owner(user)

    def exhausted(self, user) -> bool:
        if self.exempt(user):
            return False
        return self.month_usd(user.tg_id) >= self.limit(user.tg_id)

    def left(self, user) -> float:
        return max(0.0, self.limit(user.tg_id) - self.month_usd(user.tg_id))
