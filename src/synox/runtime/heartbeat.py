"""
心跳（docs/adr/0001 §3）：runtime loop 裡的任務 system.heartbeat，每 interval_min 分鐘叫常駐助理巡一次。

    hb = Heartbeat(app, loop, mother, settings=config.runtime["heartbeat"], read_chat=True, soul_append=True)
    hb.run(ctx)            loop 叫的（回一句結果）；也可以 loop.run_now("system.heartbeat") 手動
    hb.view()              網頁 API 的 heartbeat 物件
    hb.update(enabled=, interval_min=)   改設定（網頁 POST；寫 config.json 是呼叫端的事）

沒事別吵（規則，不交給 AI）：
  1. 事實快照（不含時間）跟上一次一樣、而且沒有失敗的任務 → 不叫 AI
  2. 一天最多叫 AI daily_max_calls 次
  3. 安靜時段不通知（手動那一次不看）
  4. 一天最多通知 daily_max_notify 次；跟上一次通知同一句不送
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from synox.runtime import settings as rs
from synox.runtime.loop import MESSAGE_MAX, clean_text, iso

TASK_ID = "system.heartbeat"
TASK_NAME = "心跳（常駐助理巡一次）"
TIMEOUT = 180.0
CHAT_TURNS = 3
CHAT_CUT = 150
REMIND_MAX = 10

R_QUIET_FACTS = "巡過了，沒有新狀況（沒有叫 AI）。"
R_NOTHING = "巡過了，沒有要通知你的事。"
R_NO_AI = "巡過了；沒有可用的 AI，只看了任務狀態"
R_CAP = "巡過了；今天叫 AI 的次數用完了，只看了任務狀態"
R_MOTHER_OFF = "巡過了；常駐助理關著（runtime.mother.enabled=false），只看了任務狀態"


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
        saved = loop.saved("heartbeat", {}) or {}
        self.last_result: Optional[str] = saved.get("last_result") if isinstance(saved.get("last_result"), str) else None
        self._last_hash: str = ""
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

    def facts(self) -> Tuple[str, str, int]:
        """(給 AI 看的快照, 不含時間的雜湊, 失敗的任務數)。"""
        lines: List[str] = ["## 背景任務"]
        stable: List[str] = []
        failed = 0
        for t in self.loop.views():
            if t["id"] == TASK_ID:
                continue
            failed += t["state"] == "failed"
            lines.append(f"- {t['name']}（{t['id']}）：{t['state']}，上次 {t['last_run_at'] or '還沒跑過'}"
                         + (f"，訊息：{t['last_message']}" if t["last_message"] else ""))
            # 只有「壞了」算變化（ok／idle／running 來回切換不算，不然每次都叫 AI）
            stable.append(f"{t['id']}|{t['last_message']}" if t["state"] == "failed" else f"{t['id']}|fine")
        reminders = self._reminders()
        lines.append("## 今天還沒到的提醒")
        lines += [f"- {r}" for r in reminders] or ["- （沒有）"]
        stable += reminders
        if self.read_chat:
            chat = self._recent_chat()
            lines.append("## 擁有者跟對話助理最近說的")
            lines += chat or ["- （沒有）"]
            stable += chat
        stable.append(self._now().strftime("%Y-%m-%d"))
        digest = hashlib.sha256("\n".join(stable).encode("utf-8")).hexdigest()
        return "\n".join(lines), digest, failed

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
            facts, digest, failed = self.facts()
            if self.mother is None or self.mother.state == "off":
                base = R_MOTHER_OFF if (self.mother is not None and not self.mother.enabled) else R_NO_AI
                result = f"{base}（{failed} 個失敗）。" if failed else f"{base}，都正常。"
            elif digest == self._last_hash and not failed and not manual:
                result = R_QUIET_FACTS
            elif self._calls_today >= int(self.settings.get("daily_max_calls", 40)):
                result = f"{R_CAP}（{failed} 個失敗）。"
            else:
                self._calls_today += 1
                when = self._now().strftime("%Y-%m-%d %H:%M")
                verdict = self.mother.supervise(facts, summary=f"{failed} 個任務失敗", when=when)
                self._last_hash = digest
                result = self._act(verdict, manual)
            self.last_result = clean_text(result, MESSAGE_MAX)
            self.loop.save(heartbeat={"last_result": self.last_result})
            if ctx is not None:
                ctx.log(result)
            return self.last_result

    def _act(self, verdict, manual: bool) -> str:
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
        reason = self._hold_reason(text, manual)
        if reason:
            return f"有一件事，但{reason}，沒有通知：{text}"
        self._notifies_today += 1
        self._last_notify = text
        self.app.notify_owner(f"🫀 常駐助理：{text}")
        return f"通知了你：{text}"

    def _hold_reason(self, text: str, manual: bool) -> str:
        if text == self._last_notify:
            return "上次說過一樣的"
        if self._notifies_today >= int(self.settings.get("daily_max_notify", 4)):
            return "今天通知的次數到上限了"
        if not manual:
            now = self._now()
            quiet = rs.parse_quiet(self.settings.get("quiet_hours", ""))
            if rs.in_quiet(quiet, now.hour * 60 + now.minute):
                return "在安靜時段"
        return ""
