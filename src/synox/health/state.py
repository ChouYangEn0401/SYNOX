"""
每個工具（指令節點）的健康狀態機（docs/tool-health.md）：

    healthy ──同一指紋連續 N 次／視窗內 M 次──▶ broken（冷卻中，到時間自動重新檢查）
       ▲  └──工具自己明說要人處理──────────▶ needs_action（不自動檢查；人按「重新檢查」、或手動成功一次）
       │                                     quarantined（24 小時內好壞反覆太多次；只有擁有者能解除）
       └── 重新檢查過了／手動成功一次 ◀──────┘

後三種**不給 AI**（`HIDDEN`）。指紋＝pack＋指令＋類別碼＋工具版本＋正規化後的上游錯誤（去掉數字、路徑、時間），同一個根因只累加次數。
這個檔只有純邏輯（假時鐘直接傳 now），不碰檔案、不叫工具；HealthRegistry（health/__init__.py）組起來。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from synox.health.failure import Failure, one_line

HEALTHY, BROKEN, NEEDS_ACTION, QUARANTINED = "healthy", "broken", "needs_action", "quarantined"
STATES = (HEALTHY, BROKEN, NEEDS_ACTION, QUARANTINED)
HIDDEN = (BROKEN, NEEDS_ACTION, QUARANTINED)
STATE_LABELS = {HEALTHY: "正常", BROKEN: "暫停（冷卻中）", NEEDS_ACTION: "要人處理", QUARANTINED: "隔離中"}
STORED_REASON_MAX = 120
MAX_FINGERPRINTS = 8

_PATHISH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^\s\\/:'\"]+)+[\\/]?")
_NUMBERS = re.compile(r"\d+")
_HEXISH = re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE)


def normalize_upstream(text: str) -> str:
    """上游錯誤正規化（指紋用）：去掉路徑、數字（含時間、行號、id）、長的十六進位；小寫、空白收成一個。"""
    text = _PATHISH.sub("<path>", str(text or ""))
    text = _HEXISH.sub("<hex>", text)
    text = _NUMBERS.sub("#", text)
    return " ".join(text.lower().split())[:200]


def fingerprint(pack: str, command: str, f: Failure, tool_version: str = "") -> str:
    """同一個根因＝同一個指紋（sha256 的前 16 碼；只存雜湊，不存原文）。"""
    upstream = f.diag.get("upstream") or f.reason
    version = f.diag.get("tool_version") or tool_version
    raw = "\x1f".join([pack, command, f.code, version, normalize_upstream(upstream)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Entry:
    """一個工具（或一個工具對某個人：scope=user 的失敗只記在那個人身上）的狀態。只存這些（加密）；diag 只在記憶體。"""
    tool: str                      # 節點路徑（group.leaf）
    pack: str = ""
    user: Optional[int] = None     # None＝整個工具；有值＝只對這個人
    state: str = HEALTHY
    code: str = ""
    reason: str = ""               # 截短、遮過密鑰
    fingerprint: str = ""
    streak: int = 0                # 同一指紋連續失敗幾次（成功歸零）
    count: int = 0                 # 一共記過幾次失敗
    hits: Dict[str, List[float]] = field(default_factory=dict)   # 指紋 → 視窗內的時間
    since: Optional[float] = None  # 進這個狀態的時間
    last_failure_at: Optional[float] = None
    next_check: Optional[float] = None
    step: int = 0                  # 冷卻序列走到第幾段
    breaks: List[float] = field(default_factory=list)            # 「壞掉」的時間（反覆隔離用）
    trials: List[float] = field(default_factory=list)            # 沒有自我檢查的工具：放回清單試用的時間
    trial: bool = False            # 正在試用（放回清單一次）
    diag: Dict[str, str] = field(default_factory=dict)           # 不存檔

    @property
    def key(self) -> str:
        return key_of(self.tool, self.user)

    @property
    def hidden(self) -> bool:
        return self.state in HIDDEN and not self.trial

    def to_dict(self) -> dict:
        return {"tool": self.tool, "pack": self.pack, "user": self.user, "state": self.state, "code": self.code,
                "reason": self.reason, "fingerprint": self.fingerprint, "streak": self.streak, "count": self.count,
                "hits": {k: list(v) for k, v in self.hits.items()}, "since": self.since,
                "last_failure_at": self.last_failure_at, "next_check": self.next_check, "step": self.step,
                "breaks": list(self.breaks), "trials": list(self.trials), "trial": self.trial}

    @classmethod
    def from_dict(cls, raw: dict) -> "Entry":
        """存檔 → Entry；欄位不對丟 ValueError（呼叫端整份當壞掉，fail open）。"""
        if not isinstance(raw, dict) or not isinstance(raw.get("tool"), str) or raw.get("state") not in STATES:
            raise ValueError("bad health entry")
        user = raw.get("user")
        e = cls(tool=raw["tool"], pack=str(raw.get("pack") or ""),
                user=user if isinstance(user, int) and not isinstance(user, bool) else None, state=raw["state"])
        e.code = str(raw.get("code") or "")
        e.reason = one_line(raw.get("reason") or "", STORED_REASON_MAX)
        e.fingerprint = str(raw.get("fingerprint") or "")
        for name in ("streak", "count", "step"):
            value = raw.get(name)
            setattr(e, name, value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0)
        for name in ("since", "last_failure_at", "next_check"):
            value = raw.get(name)
            setattr(e, name, float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None)
        hits = raw.get("hits") or {}
        e.hits = {str(k): [float(t) for t in v if isinstance(t, (int, float))]
                  for k, v in hits.items() if isinstance(v, list)} if isinstance(hits, dict) else {}
        for name in ("breaks", "trials"):
            value = raw.get(name) or []
            setattr(e, name, [float(t) for t in value if isinstance(t, (int, float))] if isinstance(value, list) else [])
        e.trial = raw.get("trial") is True
        return e


def key_of(tool: str, user: Optional[int] = None) -> str:
    return tool if user is None else f"{tool}@{int(user)}"


@dataclass
class Rules:
    """門檻與冷卻（config.json 的 health，health/settings.py 檢查過的）。"""
    consecutive: int = 3
    window_count: int = 5
    window_s: float = 600.0
    untrusted_consecutive: int = 2
    cooldowns: tuple = (300, 900, 3600, 21600, 86400)
    flip_limit: int = 3
    flip_window_s: float = 86400.0
    daily_trials: int = 4
    trust_self_report: bool = True

    @classmethod
    def from_settings(cls, s: dict) -> "Rules":
        return cls(consecutive=s["consecutive"], window_count=s["window_count"], window_s=float(s["window_s"]),
                   untrusted_consecutive=s["untrusted_consecutive"], cooldowns=tuple(s["cooldowns_s"]),
                   flip_limit=s["flip_limit"], flip_window_s=float(s["flip_window_s"]), daily_trials=s["daily_trials"],
                   trust_self_report=s["trust_self_report"])

    def cooldown(self, step: int) -> float:
        return float(self.cooldowns[min(max(0, step), len(self.cooldowns) - 1)])


def _break(e: Entry, rules: Rules, now: float, state: str) -> None:
    """進入不給 AI 的狀態。broken 記一次「壞掉」；24 小時內第 flip_limit 次＝quarantined。"""
    e.trial = False
    e.since = now
    if state == BROKEN:
        e.breaks = [t for t in e.breaks if now - t < rules.flip_window_s] + [now]
        if len(e.breaks) >= rules.flip_limit:
            e.state, e.next_check = QUARANTINED, None
            return
        e.step = max(0, len(e.breaks) - 1)
        e.state, e.next_check = BROKEN, now + rules.cooldown(e.step)
        return
    e.state, e.next_check = state, None


def record_failure(e: Entry, f: Failure, fp: str, rules: Rules, now: float, *, untrusted: bool = False) -> str:
    """記一次失敗，回這次之後的狀態。untrusted：沒有宣告合約的工具、匯入的工具（門檻 untrusted_consecutive）。"""
    e.count += 1
    e.last_failure_at = now
    e.code, e.reason, e.diag = f.code, one_line(f.reason, STORED_REASON_MAX), dict(f.diag)
    if e.state == QUARANTINED:
        return e.state
    if e.state in (BROKEN, NEEDS_ACTION):
        if e.trial:                                   # 試用失敗：broken 進下一段冷卻（不算新的一次「壞掉」）
            e.trial = False
            if e.state == BROKEN:
                e.step += 1
                e.next_check = now + rules.cooldown(e.step)
        return e.state
    if e.fingerprint == fp:
        e.streak += 1
    else:
        e.fingerprint, e.streak = fp, 1
    recent = [t for t in e.hits.get(fp, []) if now - t < rules.window_s] + [now]
    e.hits[fp] = recent[-max(rules.window_count, 1) * 2:]
    if len(e.hits) > MAX_FINGERPRINTS:                # 只留最近的幾個指紋
        for old in sorted(e.hits, key=lambda k: max(e.hits[k] or [0]))[:len(e.hits) - MAX_FINGERPRINTS]:
            del e.hits[old]
    if rules.trust_self_report and f.immediate:
        _break(e, rules, now, NEEDS_ACTION)
        return e.state
    if not f.counts:
        return e.state
    limit = rules.untrusted_consecutive if untrusted else rules.consecutive
    if e.streak >= limit or len(recent) >= rules.window_count:
        _break(e, rules, now, BROKEN)
    return e.state


def record_success(e: Entry, now: float) -> bool:
    """成功一次（AI 或人手動、重新檢查過了、試用成功）。回 True＝狀態有變（要存檔）。quarantined 不會因此解除。
    連續數歸零；視窗內的次數不清（時好時壞的工具靠「10 分鐘內 5 次」抓）。"""
    changed = e.streak != 0
    e.streak = 0
    if e.state in (BROKEN, NEEDS_ACTION):              # 放回清單：重新開始算（壞掉之前的次數不再算）
        e.state, e.since, e.next_check, e.trial, e.hits = HEALTHY, now, None, False, {}
        return True
    return changed


def check_failed(e: Entry, rules: Rules, now: float) -> None:
    """自我檢查沒過：進下一段冷卻。"""
    e.trial = False
    if e.state == BROKEN:
        e.step += 1
        e.next_check = now + rules.cooldown(e.step)


def start_trial(e: Entry, rules: Rules, now: float) -> bool:
    """沒有自我檢查的工具，冷卻到了：放回清單試用一次（24 小時內最多 daily_trials 次）。回 False＝今天用完了，往後延。"""
    e.trials = [t for t in e.trials if now - t < 86400.0]
    if len(e.trials) >= rules.daily_trials:
        if e.state == BROKEN:
            e.next_check = min(e.trials) + 86400.0
        return False
    e.trials.append(now)
    e.trial = True
    e.next_check = None
    return True


def release(e: Entry, now: float) -> None:
    """擁有者手動解除（隔離或任何不正常的狀態）：回到正常，反覆紀錄與冷卻都歸零。"""
    e.state, e.since, e.next_check, e.trial = HEALTHY, now, None, False
    e.streak, e.hits, e.breaks, e.trials, e.step = 0, {}, [], [], 0


__all__ = ["BROKEN", "Entry", "HEALTHY", "HIDDEN", "NEEDS_ACTION", "QUARANTINED", "Rules", "STATES", "STATE_LABELS",
           "check_failed", "fingerprint", "key_of", "normalize_upstream", "record_failure", "record_success", "release",
           "start_trial"]
