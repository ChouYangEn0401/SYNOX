"""
每日配額速率限制器。

配額是「有名字的計數器」：每個角色每天各種東西最多幾個。

    QUOTAS = {
        Role.GUEST:  {MESSAGES: 10},
        Role.USER:   {MESSAGES: 50,  "downloads": 3},
        Role.ADMIN:  {},                      # unlimited_role（預設是表上最高那一級）以上不計數、不受限
    }
    limiter = RateLimiter(data_dir="data", quotas=QUOTAS)

  - messages 由 dispatcher 經 admit() 算（每則進來的訊息一次）：超過先警告一次、之後安靜擋掉；
    block_role（預設是表上最低那一級）超過 block_multiplier（2）倍就永久封鎖。
  - 其他計數器由功能自己在用量發生時算：allowed()（唯讀）、consume()（扣、不檢查）、try_consume()（夠扣才扣）。
    加一種配額＝在表上每個角色多一個名字，不用改這支程式。表上沒寫的計數器＝0（不能用）。
  - 每日依 UTC 日期重置（載入時丟掉不是今天的用量）。

另外三種限制（管理員設定，見 packs/limits_admin.py）：
  exemption  N 天不受任何配額（擁有者授予）
  mute       N 天不能用指令（自由文字照收）
  penalty    有時效的罰則：ignore_messages（當作沒收到）、no_self_service（不能自己申請解除）、no_promote（不能申請升級）

admit()：dispatcher 唯一呼叫的入口——靜音、罰則、豁免、訊息計數全在這裡決定，dispatcher 只把結果（Admission）
轉成 Route。讀檔一律走 core/jsonstore（壞檔改名留證據）；讀改寫在一把 RLock 裡（不同 channel 是不同執行緒）。

檔案（data_dir 底下）：blocked.json、daily_usage.json、rate_exemptions.json、muted.json、penalties.json。
"""

from __future__ import annotations

import functools
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional, Tuple

from isdtelekit.core.jsonstore import load_json, save_json
from isdtelekit.users.roles import BasicRoles

MESSAGES = "messages"
# 沒給 quotas 時（BasicRoles）：訪客一天 30 則、成員 300 則、管理員不限
DEFAULT_QUOTAS: Dict[int, Dict[str, float]] = {
    BasicRoles.GUEST: {MESSAGES: 30},
    BasicRoles.MEMBER: {MESSAGES: 300},
    BasicRoles.ADMIN: {},
}

CheckResult = Literal["allow", "warn", "blocked"]

MUTED_TEXT = "🔕 你已被靜音，暫時無法使用指令。"
NO_SELF_SERVICE_TEXT = "🔒 目前暫時禁止自助速率解除。請聯絡管理員。"
BLOCKED_TEXT = "🚫 你已被封鎖，無法使用此 bot。請聯絡管理員解除封鎖。"
PENALTY_KINDS = ("ignore_messages", "no_self_service", "no_promote")


def _locked(method):
    """讀改寫的方法一次只給一條執行緒。"""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


@dataclass(frozen=True)
class Admission:
    """admit() 擋下一則訊息時的結果。message 是要回給那個人的話（空的就不回）；
    silent=True 是「當作沒收到」（ignore_messages 罰則），dispatcher 記成 ignored 而不是 rate_limited。"""
    reason: str                 # muted / no_self_service / warn / blocked / ignore_messages
    message: str = ""
    silent: bool = False


@dataclass
class _DailyUsage:
    date: str = ""
    warned: bool = False        # 今天的超量警告送過了沒
    counts: Dict[str, float] = field(default_factory=dict)   # 計數器名稱 → 今天用了多少

    def to_dict(self) -> dict:
        return {"date": self.date, **self.counts, "warned": self.warned}

    @classmethod
    def from_dict(cls, d: dict) -> "_DailyUsage":
        counts = {k: v for k, v in d.items() if k not in ("date", "warned")}
        return cls(date=d.get("date", ""), warned=d.get("warned", False), counts=counts)


class RateLimiter:

    def __init__(self, data_dir: str = "data", *, quotas: Optional[Dict[int, Dict[str, float]]] = None,
                 unlimited_role: Optional[int] = None, block_role: Optional[int] = None,
                 block_multiplier: float = 2,
                 blocked_path: Optional[str] = None, usage_path: Optional[str] = None,
                 exemptions_path: Optional[str] = None, muted_path: Optional[str] = None,
                 penalties_path: Optional[str] = None):
        self.quotas = quotas or DEFAULT_QUOTAS
        self.unlimited_role = max(self.quotas) if unlimited_role is None else unlimited_role
        self.block_role = min(self.quotas) if block_role is None else block_role
        self.block_multiplier = block_multiplier
        self._fallback_role = min(self.quotas)          # 表上沒有的角色照最低一級算
        # 所有計數器的名字：每天的用量一開始每個都是 0（daily_usage.json 的欄位才會齊）
        self._counters = list(dict.fromkeys([MESSAGES] + [n for row in self.quotas.values() for n in row]))
        self.blocked_path = blocked_path or os.path.join(data_dir, "blocked.json")
        self.usage_path = usage_path or os.path.join(data_dir, "daily_usage.json")
        self.exemptions_path = exemptions_path or os.path.join(data_dir, "rate_exemptions.json")
        self.muted_path = muted_path or os.path.join(data_dir, "muted.json")
        self.penalties_path = penalties_path or os.path.join(data_dir, "penalties.json")
        self._lock = threading.RLock()          # 可重入：admit → check、try_consume → consume
        self._blocked: Dict[int, dict] = {}
        self._usage: Dict[int, _DailyUsage] = {}
        self._exemptions: Dict[int, str] = {}   # tg_id -> 到期日 "YYYY-MM-DD"（含）
        self._muted: Dict[int, str] = {}        # tg_id -> 到期日 "YYYY-MM-DD"（含）
        self._penalties: Dict[int, dict] = {}   # tg_id -> {kind: 到期 ISO 時間}
        self._load()

    # ── dispatcher 的入口 ─────────────────────────────────────────────

    @_locked
    def admit(self, user, *, is_command: bool, quota_exempt: bool = False) -> Optional[Admission]:
        """一則進來的訊息要不要放行。None＝放行；擋下就回 Admission（dispatcher 送出 message、記成 Route）。

        is_command：「/」開頭的（靜音只擋指令）。quota_exempt：指令樹上標了 quota_exempt 的節點
        （申請解除配額用）——超過每日上限也放行，但靜音與 no_self_service 罰則照樣擋。"""
        tg_id = user.tg_id
        if user.role >= self.unlimited_role:
            return None
        if is_command and self.is_muted(tg_id):
            return Admission("muted", MUTED_TEXT)
        if quota_exempt:
            if self.is_penalized(tg_id, "no_self_service"):
                return Admission("no_self_service", NO_SELF_SERVICE_TEXT)
            return None
        if self.is_penalized(tg_id, "ignore_messages"):
            return Admission("ignore_messages", silent=True)
        status, warn_msg = self.check(tg_id, user.role, getattr(user, "username", ""))
        if status in ("blocked", "warn"):
            return Admission(status, warn_msg)
        return None

    @_locked
    def check(self, tg_id: int, role: int, username: str = "") -> Tuple[CheckResult, str]:
        """一則訊息的每日計數：(allow, "")／(warn, 第一次附警告，之後 "")／(blocked, 封鎖提示)。"""
        if role >= self.unlimited_role or self.is_exempt(tg_id):
            return "allow", ""
        if tg_id in self._blocked:
            self._blocked[tg_id]["attack_count"] += 1
            self._save_blocked()
            return "blocked", BLOCKED_TEXT
        usage = self._get_today(tg_id)
        max_msgs = self.limit(role, MESSAGES)
        usage.counts[MESSAGES] = usage.counts.get(MESSAGES, 0) + 1
        self._save_usage()
        if usage.counts[MESSAGES] <= max_msgs:
            return "allow", ""
        if role == self.block_role and usage.counts[MESSAGES] > max_msgs * self.block_multiplier:
            self._block(tg_id, username)
            name = getattr(role, "name", str(role))
            return "blocked", (f"🚫 你今日傳送訊息次數已超過 {name} 每日上限 {max_msgs:g} 條的 "
                               f"{self.block_multiplier:g} 倍，已被自動封鎖。請聯絡管理員解除。")
        if not usage.warned:
            usage.warned = True
            self._save_usage()
            return "warn", f"⚠️ 你今天已超過每日訊息上限（{max_msgs:g} 條）。\n今日剩餘配額已用盡，請明天再試。"
        return "warn", ""

    # ── 通用的計數器 ─────────────────────────────────────────────────

    def limit(self, role: int, counter: str) -> float:
        """這個角色每天 counter 最多多少（表上沒有這個角色就照最低一級；沒有這個計數器就是 0）。"""
        row = self.quotas.get(role, self.quotas[self._fallback_role])
        return row.get(counter, 0)

    def used(self, tg_id: int, counter: str) -> float:
        with self._lock:
            return self._get_today(tg_id).counts.get(counter, 0)

    def unlimited(self, tg_id: int, role: int) -> bool:
        """這個人現在完全不受配額限制（unlimited_role 以上，或在豁免期內）。"""
        return role >= self.unlimited_role or self.is_exempt(tg_id)

    def allowed(self, tg_id: int, role: int, counter: str, amount: float = 1) -> bool:
        """再用 amount 會不會超過今天的上限（唯讀，不扣）。"""
        if self.unlimited(tg_id, role):
            return True
        return self.used(tg_id, counter) + amount <= self.limit(role, counter)

    @_locked
    def consume(self, tg_id: int, role: int, counter: str, amount: float = 1) -> None:
        """扣掉 amount（不檢查上限；不受限的人不扣）。"""
        if self.unlimited(tg_id, role):
            return
        usage = self._get_today(tg_id)
        usage.counts[counter] = usage.counts.get(counter, 0) + amount
        self._save_usage()

    @_locked
    def try_consume(self, tg_id: int, role: int, counter: str, amount: float = 1) -> bool:
        """夠扣才扣，回傳有沒有扣成（不受限的人永遠 True、不扣）。"""
        if not self.allowed(tg_id, role, counter, amount):
            return False
        self.consume(tg_id, role, counter, amount)
        return True

    def get_daily_usage(self, tg_id: int) -> dict:
        """{"date", 每個計數器: 今天用了多少}。"""
        with self._lock:
            u = self._get_today(tg_id)
            return {"date": u.date, **{name: u.counts.get(name, 0) for name in self._counters}}

    # ── 豁免、重置 ───────────────────────────────────────────────────

    def is_exempt(self, tg_id: int) -> bool:
        expiry = self._exemptions.get(tg_id)
        return bool(expiry) and self._today() <= expiry

    @_locked
    def free_rate_limit(self, tg_id: int, days: int) -> str:
        """從今天起 days 天不受配額限制。回傳到期日（含）。"""
        expiry = (datetime.now(timezone.utc) + timedelta(days=days - 1)).strftime("%Y-%m-%d")
        self._exemptions[tg_id] = expiry
        self._save(self.exemptions_path, self._exemptions)
        logging.info("Rate-limit exemption granted: tg_id=%s until %s", tg_id, expiry)
        return expiry

    @_locked
    def reset_rate_limit(self, tg_id: int) -> None:
        """清掉今天的用量。"""
        if self._usage.pop(tg_id, None) is not None:
            self._save_usage()
        logging.info("Rate-limit usage reset: tg_id=%s", tg_id)

    # ── 靜音 ─────────────────────────────────────────────────────────

    def is_muted(self, tg_id: int) -> bool:
        expiry = self._muted.get(tg_id)
        return bool(expiry) and self._today() <= expiry

    def list_muted(self) -> dict:
        """{tg_id: 到期日}，只列還沒到期的。"""
        today = self._today()
        return {tg_id: expiry for tg_id, expiry in self._muted.items() if today <= expiry}

    @_locked
    def mute_user(self, tg_id: int, days: int) -> str:
        """靜音 N 天，回傳到期日（含）。"""
        expiry = (datetime.now(timezone.utc) + timedelta(days=days - 1)).strftime("%Y-%m-%d")
        self._muted[tg_id] = expiry
        self._save(self.muted_path, self._muted)
        logging.info("User muted: tg_id=%s until %s", tg_id, expiry)
        return expiry

    @_locked
    def unmute_user(self, tg_id: int) -> bool:
        if self._muted.pop(tg_id, None) is None:
            return False
        self._save(self.muted_path, self._muted)
        return True

    # ── 罰則 ─────────────────────────────────────────────────────────

    @_locked
    def set_penalty(self, tg_id: int, kind: str, seconds: int) -> str:
        """設定一種罰則 seconds 秒，回傳到期的 ISO 時間。"""
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")
        self._penalties.setdefault(tg_id, {})[kind] = expiry
        self._save(self.penalties_path, self._penalties)
        logging.info("Penalty set: %s -> %s until %s", tg_id, kind, expiry)
        return expiry

    @_locked
    def clear_penalty(self, tg_id: int, kind: Optional[str] = None) -> bool:
        """移除一種罰則；kind=None 全部移除。沒有可移除的回 False。"""
        entry = self._penalties.get(tg_id)
        if not entry or (kind is not None and kind not in entry):
            return False
        if kind is None or len(entry) == 1:
            del self._penalties[tg_id]
        else:
            del entry[kind]
        self._save(self.penalties_path, self._penalties)
        return True

    def is_penalized(self, tg_id: int, kind: str) -> bool:
        expiry = (self._penalties.get(tg_id) or {}).get(kind)
        return bool(expiry) and expiry >= _now_iso()

    def list_penalties(self) -> dict:
        """{tg_id: {kind: 到期}}，只列還沒到期的。"""
        now = _now_iso()
        out = {}
        for tg_id, entry in self._penalties.items():
            active = {k: v for k, v in entry.items() if v >= now}
            if active:
                out[tg_id] = active
        return out

    # ── 封鎖 ─────────────────────────────────────────────────────────

    def is_blocked(self, tg_id: int) -> bool:
        return tg_id in self._blocked

    @_locked
    def unblock(self, tg_id: int) -> bool:
        if self._blocked.pop(tg_id, None) is None:
            return False
        self._save_blocked()
        logging.info("Unblocked: %s", tg_id)
        return True

    def list_blocked(self) -> List[dict]:
        return list(self._blocked.values())

    # ── 內部 ─────────────────────────────────────────────────────────

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _get_today(self, tg_id: int) -> _DailyUsage:
        today = self._today()
        u = self._usage.get(tg_id)
        if u is None or u.date != today:
            u = self._usage[tg_id] = _DailyUsage(date=today, counts={name: 0 for name in self._counters})
        return u

    def _block(self, tg_id: int, username: str) -> None:
        self._blocked[tg_id] = {"tg_id": tg_id, "username": username, "attack_count": 0,
                                "blocked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self._save_blocked()
        logging.warning("AUTO-BLOCKED: @%s (%s)", username, tg_id)

    def _load(self) -> None:
        # 一律經 core/jsonstore.load_json：壞掉的檔案改名成 .corrupt-<時間> 留證據，從空的開始；格式不對也當空的
        raw = load_json(self.blocked_path, [])
        for entry in raw if isinstance(raw, list) else []:
            if isinstance(entry, dict) and "tg_id" in entry:
                self._blocked[int(entry["tg_id"])] = entry
        today, now = self._today(), _now_iso()
        for path, target in ((self.exemptions_path, self._exemptions), (self.muted_path, self._muted)):
            raw = load_json(path, {})
            for tg_id, expiry in (raw.items() if isinstance(raw, dict) else ()):
                if isinstance(expiry, str) and expiry >= today:
                    target[int(tg_id)] = expiry
        raw = load_json(self.penalties_path, {})
        for tg_id, entry in (raw.items() if isinstance(raw, dict) else ()):
            active = {k: v for k, v in entry.items() if isinstance(v, str) and v >= now} if isinstance(entry, dict) else {}
            if active:
                self._penalties[int(tg_id)] = active
        raw = load_json(self.usage_path, {})
        for tg_id, data in (raw.items() if isinstance(raw, dict) else ()):
            if not isinstance(data, dict):
                continue
            u = _DailyUsage.from_dict(data)
            if u.date == today:                 # 不是今天的不載入（每天自動歸零）
                for name in self._counters:
                    u.counts.setdefault(name, 0)
                self._usage[int(tg_id)] = u

    @staticmethod
    def _save(path: str, data: Dict[int, object]) -> None:
        save_json(path, {str(k): v for k, v in data.items()})

    def _save_blocked(self) -> None:
        save_json(self.blocked_path, list(self._blocked.values()))

    def _save_usage(self) -> None:
        save_json(self.usage_path, {str(k): v.to_dict() for k, v in self._usage.items()})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
