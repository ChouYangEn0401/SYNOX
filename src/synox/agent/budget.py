"""
伺服器版：成員的 AI 每月額度（美元）。

- 每個人的用量：data/users/<id>/llm_usage.json（跟 data/llm_usage.json 同一種格式，多一個 usd）。
  全部的總帳仍記在 data/llm_usage.json（營運者看的）。
- 額度：config.json 的 ai_member_monthly_usd（預設 2.0）；管理員可以替某個人另外設（/ai_budget <id> <美元>，
  存在 data/ai_budgets.json）。擁有者沒有額度。
- 價錢：token 換美元用 llm.price_in／llm.price_out（每百萬 token 多少美元）；沒寫就用保守的預設
  （輸入 3、輸出 15，約等於中階雲端模型）。本機模型可以設成 0。

頻道 AI 的 bot 池（PERM-6，個人版、伺服器版都有）：BotPool——頻道型 bot 的 ai.pool_usd_month 是**整個 bot 一池**，
用量記在 data/bot_pools/<bot 名字>/llm_usage.json（同一種格式），不算進任何人的個人額度；全部的總帳一樣記在
data/llm_usage.json。這個月用到 pool 就整個 bot 的頻道 AI 停（回 POOL_EXHAUSTED），下個月自動重來。
價錢跟個人額度同一套（llm.price_in／price_out）。
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
POOLS_DIR = "bot_pools"
POOL_EXHAUSTED = "🤖 這個 bot 這個月的頻道 AI 額度用完了（整個 bot 共用一池，下個月重來）；指令照樣能用（@我 /help）。"


def _price(llm: dict, key: str, default: float) -> float:
    try:
        return max(0.0, float(llm.get(key, default)))
    except (TypeError, ValueError):
        return default


def reported_usd(usage: dict):
    """AI 來源自己回報了這次花多少（Claude Code 的 total_cost_usd；訂閱制下是照 API 價換算的約數）→ 那個數字；沒有＝None。"""
    try:
        value = (usage or {}).get("usd")
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def usd_of(config, usage: dict) -> float:
    """這次的 token 用量換成美元（llm.price_in／price_out，每百萬 token）。"""
    llm = getattr(config, "llm", {}) or {}
    usage = usage or {}
    reported = reported_usd(usage)
    if reported is not None:
        return reported
    return (int(usage.get("input", 0) or 0) * _price(llm, "price_in", DEFAULT_PRICE_IN) +
            int(usage.get("output", 0) or 0) * _price(llm, "price_out", DEFAULT_PRICE_OUT)) / 1_000_000


class BotPool:
    """頻道型 bot 的頻道 AI 額度池（整個 bot 一池，每月）。"""

    def __init__(self, config, bot_name: str, usd_month: float):
        from synox.agent.loop import UsageBook
        self.config = config
        self.name = bot_name
        self.usd_month = max(0.0, float(usd_month or 0.0))
        self.folder = os.path.join(config.data_dir, POOLS_DIR, bot_name)
        self.book = UsageBook(os.path.join(self.folder, "llm_usage.json"))

    def cost(self, usage: dict) -> float:
        return usd_of(self.config, usage)

    def record(self, usage: dict) -> float:
        usd = self.cost(usage)
        if usage:
            os.makedirs(self.folder, exist_ok=True)
            self.book.record(usage, usd=usd)
        return usd

    def month_usd(self) -> float:
        return float(self.book.summary()["month"].get("usd", 0.0))

    def exhausted(self) -> bool:
        return self.month_usd() >= self.usd_month

    def left(self) -> float:
        return max(0.0, self.usd_month - self.month_usd())

    def line(self) -> str:
        """給 /bot_status 看的一行。"""
        s = self.book.summary()["month"]
        used = float(s.get("usd", 0.0))
        return (f"頻道 AI 這個月：用了約 US${used:.2f}／US${self.usd_month:.2f}（整個 bot 一池）、{s.get('calls', 0)} 次"
                + ("；用完了，頻道 AI 停到下個月" if used >= self.usd_month else ""))


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
        reported = reported_usd(usage)
        if reported is not None:
            return reported
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
