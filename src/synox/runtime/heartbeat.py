"""
心跳（docs/adr/0001 §3）：runtime loop 裡的任務 system.heartbeat，每 interval_min 分鐘叫常駐助理巡一次。

    hb = Heartbeat(app, loop, mother, settings=config.runtime["heartbeat"], read_chat=True, soul_append=True)
    hb.run(ctx)            loop 叫的（回一句結果）；也可以 loop.run_now("system.heartbeat") 手動
    hb.view()              網頁 API 的 heartbeat 物件
    hb.update(enabled=, interval_min=)   改設定（網頁 POST；寫 config.json 是呼叫端的事）

沒事別吵（規則，不交給 AI）：
  1. 事實快照（不含時間）跟上一次一樣 → 不叫 AI（手動那一次不看）。有失敗的任務也一樣：失敗只記
     「哪個任務＋去掉數字、空白、截短的原因」（failure_key），同一批失敗只是次數、時間不同不算變化；
     新的任務壞了、原因變了、恢復了、換日才算。上一次的快照指紋存在 state.json，重開後接著用。
     例外：上一次有失敗要通知、卻被安靜時段擋下 → 安靜時段過了再叫一次（不然沒變的失敗永遠不會通知）
  2. 一天最多叫 AI daily_max_calls 次
  3. 安靜時段不通知（手動那一次不看）
  4. 一天最多通知 daily_max_notify 次；跟上一次通知同一句不送；同一批失敗通知過就不再為它通知
     （組成變了才清掉；提醒或對話也變了的那一次不擋；只存任務 id 與原因的雜湊，不存訊息原文）
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from datetime import datetime
from typing import Callable, Dict, List, NamedTuple, Optional, Set

from synox.runtime import settings as rs
from synox.runtime.loop import MESSAGE_MAX, clean_text, iso

TASK_ID = "system.heartbeat"
TASK_NAME = "心跳（常駐助理巡一次）"
TIMEOUT = 180.0
CHAT_TURNS = 3
CHAT_CUT = 150
REMIND_MAX = 10
FAIL_CUT = 80                                  # 失敗原因的指紋只看前幾個字

R_QUIET_FACTS = "巡過了，沒有新狀況（沒有叫 AI）。"
R_SAME_FAILED = "巡過了，失敗狀態沒有變化（{n} 個失敗，之前已經看過），沒有叫 AI。"
R_NOTHING = "巡過了，沒有要通知你的事。"
R_NO_AI = "巡過了；沒有可用的 AI，只看了任務狀態"
R_CAP = "巡過了；今天叫 AI 的次數用完了，只看了任務狀態"
R_MOTHER_OFF = "巡過了；常駐助理關著（runtime.mother.enabled=false），只看了任務狀態"

HOLD_REPEAT = "上次說過一樣的"
HOLD_SAME_FAILED = "這批失敗之前已經通知過"
HOLD_DAILY = "今天通知的次數到上限了"
HOLD_QUIET = "在安靜時段"

_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"\s+")
_HASH = re.compile(r"[0-9a-f]{64}")


def failure_key(message) -> str:
    """失敗原因的指紋用的那一段：數字（次數、時間、秒數）換成 #、空白壓成一個、截到 FAIL_CUT 字。"""
    text = _DIGITS.sub("#", str(message or ""))
    return _SPACES.sub(" ", text).strip()[:FAIL_CUT]


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _digest_or_empty(value) -> str:
    return value if isinstance(value, str) and _HASH.fullmatch(value) else ""


def _marks(value) -> Dict[str, str]:
    """存檔裡的 {任務 id: 失敗原因的雜湊}；格式不對＝當作沒有（壞掉的存檔不能讓心跳不能跑）。"""
    if not isinstance(value, dict):
        return {}
    if not all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in value.items()):
        return {}
    return dict(value)


class Snapshot(NamedTuple):
    text: str                    # 給 AI 看的快照
    digest: str                  # 不含時間的雜湊（失敗的原因用 failure_key）
    failures: Dict[str, str]     # 失敗的任務 → 原因的雜湊
    seen: Set[str]               # 這次看得到的任務 id（重開後 pack 還沒回報的不在裡面）
    context: str                 # 任務以外（提醒、對話）的雜湊：變了＝AI 可能在講新的事

    @property
    def failed(self) -> int:
        return len(self.failures)


class Heartbeat:

    def __init__(self, app, loop, mother, *, settings: dict, read_chat: bool = True, soul_append: bool = True,
                 now: Callable[[], datetime] = datetime.now):
        self.app = app
        self.loop = loop
        self.mother = mother
        self.settings = dict(settings)
        self.read_chat = read_chat
        self.soul_append = soul_append
        self._now = now
        self._lock = threading.Lock()
        saved = loop.saved("heartbeat", {})
        if not isinstance(saved, dict):
            saved = {}
        self.last_result: Optional[str] = saved.get("last_result") if isinstance(saved.get("last_result"), str) else None
        self._last_hash: str = _digest_or_empty(saved.get("last_hash"))
        self._last_context: str = _digest_or_empty(saved.get("last_context"))
        self._notified_failures: Dict[str, str] = _marks(saved.get("notified_failures"))   # 通知過的那批失敗
        self._held_failures: Dict[str, str] = _marks(saved.get("held_failures"))           # 被安靜時段擋下的那批
        self._last_notify: str = ""
        self._day = ""
        self._calls_today = 0
        self._notifies_today = 0

    # ── 設定 ─────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("enabled", True))

    @property
    def interval_min(self) -> int:
        return int(self.settings.get("interval_min", 45))

    def register(self) -> None:
        interval = self.interval_min * 60 if self.enabled else None
        task = self.loop.register(TASK_ID, TASK_NAME, fn=self.run, interval=interval, timeout=TIMEOUT)
        if interval:
            self.loop.reschedule(TASK_ID, interval)   # 有上一次（state.json）就接著算，沒有＝一個間隔後
        task.set_schedule_text("" if self.enabled else "關閉")

    def update(self, *, enabled: Optional[bool] = None, interval_min: Optional[int] = None) -> dict:
        if interval_min is not None:
            problem = rs.interval_problem(interval_min)
            if problem:
                raise ValueError(problem)
            self.settings["interval_min"] = interval_min
        if enabled is not None:
            self.settings["enabled"] = bool(enabled)
        task = self.loop.reschedule(TASK_ID, self.interval_min * 60 if self.enabled else None)
        if task is not None:
            task.set_schedule_text("" if self.enabled else "關閉")
        return self.view()

    def view(self) -> dict:
        task = self.loop.task(TASK_ID)
        next_due = task.next_due if (task is not None and self.enabled and self.loop.started) else None
        return {"enabled": self.enabled, "interval_min": self.interval_min,
                "last_run_at": iso(task.last_run_at) if task is not None else None,
                "next_run_at": iso(next_due), "last_result": self.last_result,
                "min_interval_min": rs.MIN_INTERVAL_MIN, "max_interval_min": rs.MAX_INTERVAL_MIN,
                "quiet_hours": self.settings.get("quiet_hours", "")}

    # ── 快照 ─────────────────────────────────────────────────────────

    def facts(self) -> Snapshot:
        """這一次的快照（給 AI 看的字、不含時間的雜湊、失敗的任務）。"""
        lines: List[str] = ["## 背景任務"]
        stable: List[str] = []
        failures: Dict[str, str] = {}
        seen: Set[str] = set()
        for t in self.loop.views():
            if t["id"] == TASK_ID:
                continue
            seen.add(t["id"])
            lines.append(f"- {t['name']}（{t['id']}）：{t['state']}，上次 {t['last_run_at'] or '還沒跑過'}"
                         + (f"，訊息：{t['last_message']}" if t["last_message"] else ""))
            # 只有「壞了」算變化（ok／idle／running 來回切換不算，不然每次都叫 AI）；
            # 失敗的原因去掉數字（次數、時間、秒數），不然「第 3 次」→「第 4 次」每次都算新的
            if t["state"] == "failed":
                key = failure_key(t["last_message"])
                failures[t["id"]] = _short_hash(key)
                stable.append(f"{t['id']}|failed|{key}")
            else:
                stable.append(f"{t['id']}|fine")
        other: List[str] = []                        # 任務以外的（提醒、對話）
        reminders = self._reminders()
        lines.append("## 今天還沒到的提醒")
        lines += [f"- {r}" for r in reminders] or ["- （沒有）"]
        other += reminders
        if self.read_chat:
            chat = self._recent_chat()
            lines.append("## 擁有者跟對話助理最近說的")
            lines += chat or ["- （沒有）"]
            other += chat
        stable += other
        stable.append(self._now().strftime("%Y-%m-%d"))
        digest = hashlib.sha256("\n".join(stable).encode("utf-8")).hexdigest()
        context = hashlib.sha256("\n".join(other).encode("utf-8")).hexdigest()
        return Snapshot("\n".join(lines), digest, failures, seen, context)

    def _reminders(self) -> List[str]:
        runner = self.app.extras.get("synox_schedule_runner")
        if runner is None:
            return []
        now = self._now()
        today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
        out = []
        try:
            store = runner.store.of(self.app.owner_id)
            for it in store.items("remind"):
                if it.get("time", "") > hhmm and it.get("last_run") != today and (not it.get("date") or it["date"] == today):
                    out.append(f"{it.get('time')} {clean_text(it.get('text', ''), 80)}")
        except Exception:
            logging.exception("[HEARTBEAT] cannot read reminders")
        return sorted(out)[:REMIND_MAX]

    def _recent_chat(self) -> List[str]:
        agent = self.app.extras.get("synox_agent")
        if agent is None:
            return []
        owner = self.app.owner_id
        try:
            history = agent.latest_history(owner)
        except Exception:
            return []
        out = []
        for msg in history[-2 * CHAT_TURNS:]:
            who = "他" if msg.role == "user" else "對話助理"
            out.append(f"- {who}：{clean_text(msg.content, CHAT_CUT)}")
        return out

    # ── 巡一次 ───────────────────────────────────────────────────────

    def _roll_day(self) -> None:
        day = self._now().strftime("%Y-%m-%d")
        if day != self._day:
            self._day, self._calls_today, self._notifies_today = day, 0, 0

    def run(self, ctx=None) -> str:
        manual = bool(getattr(ctx, "manual", False))
        with self._lock:
            self._roll_day()
            snap = self.facts()
            failed = snap.failed
            self._forget_changed(snap)
            if self.mother is None or self.mother.state == "off":
                base = R_MOTHER_OFF if (self.mother is not None and not self.mother.enabled) else R_NO_AI
                result = f"{base}（{failed} 個失敗）。" if failed else f"{base}，都正常。"
            elif not manual and snap.digest == self._last_hash and not self._ask_again(snap):
                result = R_SAME_FAILED.format(n=failed) if failed else R_QUIET_FACTS
            elif self._calls_today >= int(self.settings.get("daily_max_calls", 40)):
                result = f"{R_CAP}（{failed} 個失敗）。"
            else:
                self._calls_today += 1
                when = self._now().strftime("%Y-%m-%d %H:%M")
                verdict = self.mother.supervise(snap.text, summary=f"{failed} 個任務失敗", when=when)
                news = snap.context != self._last_context      # 提醒或對話也變了：AI 可能在講別的事
                self._last_hash, self._last_context = snap.digest, snap.context
                self._held_failures = {}
                result = self._act(verdict, manual, snap.failures, news=news)
            self.last_result = clean_text(result, MESSAGE_MAX)
            self.loop.save(heartbeat=self._saved_state())
            if ctx is not None:
                ctx.log(result)
            return self.last_result

    def _saved_state(self) -> dict:
        """存進 state.json 的（沒有個人資料：結果那句、快照的雜湊、任務 id＋失敗原因的雜湊）。"""
        return {"last_result": self.last_result, "last_hash": self._last_hash, "last_context": self._last_context,
                "notified_failures": dict(self._notified_failures), "held_failures": dict(self._held_failures)}

    def _forget_changed(self, snap: Snapshot) -> None:
        """記著的那批失敗（通知過的、被安靜時段擋下的）跟現在不一樣了（新的壞了、原因變了、恢復了）→ 清掉。
        現在看不到的任務（重開後 pack 還沒再回報）不算變化，先留著。"""
        for name in ("_notified_failures", "_held_failures"):
            marks = getattr(self, name)
            if marks and {k: v for k, v in marks.items() if k in snap.seen} != snap.failures:
                setattr(self, name, {})

    def _ask_again(self, snap: Snapshot) -> bool:
        """快照沒變，但上一次這批失敗要通知卻碰上安靜時段，現在可以通知了 → 再叫一次 AI。"""
        return bool(snap.failures and self._held_failures and not self._in_quiet()
                    and self._notifies_today < int(self.settings.get("daily_max_notify", 4)))

    def _in_quiet(self) -> bool:
        now = self._now()
        quiet = rs.parse_quiet(self.settings.get("quiet_hours", ""))
        return rs.in_quiet(quiet, now.hour * 60 + now.minute)

    def _act(self, verdict, manual: bool, failures: Optional[Dict[str, str]] = None, *, news: bool = True) -> str:
        failures = failures or {}
        parts = []
        if verdict.soul_lines and self.soul_append and self.mother.soul is not None:
            try:
                added = self.mother.soul.append_notes(verdict.soul_lines, by="mother")
            except Exception as e:
                logging.warning("[HEARTBEAT] soul append skipped: %s", e)
                added = []
            if added:
                parts.append(f"記進 soul.md {len(added)} 行")
        text = verdict.notify.strip()
        if not text:
            return R_NOTHING + ("（" + "、".join(parts) + "）" if parts else "")
        reason = self._hold_reason(text, manual, failures, news=news)
        if reason:
            if reason == HOLD_QUIET and failures:
                self._held_failures = dict(failures)      # 安靜時段過了再問一次（_ask_again）
            return f"有一件事，但{reason}，沒有通知：{text}"
        self._notifies_today += 1
        self._last_notify = text
        if failures:
            self._notified_failures = dict(failures)
        self.app.notify_owner(f"🫀 常駐助理：{text}")
        return f"通知了你：{text}"

    def _hold_reason(self, text: str, manual: bool, failures: Optional[Dict[str, str]] = None, *,
                     news: bool = True) -> str:
        if text == self._last_notify:
            return HOLD_REPEAT
        # _forget_changed 已經把「組成變了」的清掉：還留著＝現在這批就是通知過的那批（手動、換日那次也不再送）。
        # 提醒或對話也變了（news）就不擋：AI 可能在講那件新的事
        if failures and self._notified_failures and not news:
            return HOLD_SAME_FAILED
        if self._notifies_today >= int(self.settings.get("daily_max_notify", 4)):
            return HOLD_DAILY
        if not manual and self._in_quiet():
            return HOLD_QUIET
        return ""
