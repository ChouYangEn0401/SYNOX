"""
Runtime loop（docs/adr/0001 §1、§2）：一條排程執行緒＋登記的任務。

    loop = RuntimeLoop(app, clock=time.time)
    loop.register("system.schedule", "提醒與排程", fn=lambda ctx: "…", interval=30)
    loop.report("pack.weather", "failed", "API 回 503", name="🌤 天氣", owner="weather")   # 沒有 fn：只收回報
    loop.start() / loop.stop()          App.run 開始收訊時啟動、停止時停（終端機模式不跑）
    loop.tick()                         測試用：照假時鐘看一次（spawn 換成同步）

- 每個任務在**自己的執行緒**跑（`spawn`），排程執行緒只看「到點了沒、逾時了沒」：慢的不卡別的，例外不拖垮迴圈。
- fn(ctx) 回字串（或 None）＝ok；丟例外＝failed。ctx.log(line) 寫日誌尾巴。
- 逾時：超過 timeout 標 failed（算一次失敗）；那次執行晚回來的結果丟掉（generation 對不上）。上一次沒結束不開下一次。
- 失敗退避：下一次＝min(間隔, RETRY_BASE × 2^(n-1))；連續 NOTIFY_AFTER 次通知擁有者一次、退避拉長到 max(間隔, LONG_BACKOFF)；
  成功歸零（通知過的話說一聲「恢復了」）。例外、逾時、回報失敗全部算失敗。
- 存檔：data/runtime/state.json 只有 state、時間、連續失敗數（沒有訊息與日誌——那些可能有個人資料，只在記憶體）。
- 狀態變了（一次執行做完、逾時、pack 回報）→ 叫 listeners（連動 activator 掛在這裡，docs/adr/0004），在鎖外叫、
  例外只記 log。帶著「這次是誰引起的」（Cause：連動串 id、第幾層、走過哪些規則）：activator 叫 run_now(cause=…)
  或在 caused_by(…) 裡執行程式時，那個任務做完／那段程式回報的狀態就接在同一串上（防無限連動用）。
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from typing import Callable, Deque, Dict, List, NamedTuple, Optional, Tuple

from isdtelekit.core import jsonstore

STATES = ("ok", "running", "failed", "idle")
TICK_SECONDS = 5
RETRY_BASE = 60.0
LONG_BACKOFF = 30 * 60.0
NOTIFY_AFTER = 5
LOG_LINES = 200
LINE_MAX = 300
MESSAGE_MAX = 200
DEFAULT_TIMEOUT = 120.0
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
STATE_FILE = os.path.join("runtime", "state.json")


class Cause(NamedTuple):
    """這次狀態變化是哪一串連動引起的（activator 用）。chain＝串 id、depth＝第幾層、path＝走過的規則 id。"""
    chain: str
    depth: int
    path: Tuple[str, ...]


_CAUSE = threading.local()


def current_cause() -> Optional[Cause]:
    """這條執行緒現在在哪一串連動裡（activator 執行程式動作時設的）；不在＝None。"""
    return getattr(_CAUSE, "value", None)


@contextmanager
def caused_by(cause: Optional[Cause]):
    """這段程式裡回報的狀態、叫的 run_now 都算在 cause 那一串上。"""
    old = current_cause()
    _CAUSE.value = cause
    try:
        yield
    finally:
        _CAUSE.value = old


def iso(ts: Optional[float]) -> Optional[str]:
    """epoch 秒 → 本機時區的 ISO 8601（到秒）；None → None。"""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def clean_text(text, limit: int) -> str:
    """一行、截長、遮掉像密鑰的片段（日誌、訊息、回報都過這裡）。"""
    from synox.packs.kit import mask_tokens
    one = " ".join(str(text or "").split())
    one = mask_tokens(one)
    return one if len(one) <= limit else one[:limit - 1] + "…"


def every_text(seconds: Optional[float]) -> str:
    if not seconds:
        return "自己回報"
    if seconds < 120:
        return f"每 {int(seconds)} 秒"
    minutes = seconds / 60
    if minutes < 120 or minutes % 60:
        return f"每 {int(round(minutes))} 分鐘"
    return f"每 {int(minutes // 60)} 小時"


class TaskContext:
    """fn 拿到的：寫日誌、看是不是手動觸發。"""

    def __init__(self, task: "Task", manual: bool = False):
        self._task = task
        self.manual = manual

    def log(self, line: str) -> None:
        self._task.add_log(line)


class Task:

    def __init__(self, task_id: str, name: str, owner: str = "system", *, fn: Optional[Callable] = None,
                 interval: Optional[float] = None, timeout: float = DEFAULT_TIMEOUT, schedule: str = "",
                 clock: Callable[[], float] = time.time):
        if not ID_RE.match(task_id):
            raise ValueError(f"task id {task_id!r}: 只能用小寫英數字與 . _ -，64 字內")
        self.id = task_id
        self.name = name
        self.owner = owner
        self.fn = fn
        self.interval = float(interval) if interval else None
        self.timeout = float(timeout)
        self._schedule = schedule
        self._clock = clock
        self.state = "idle"
        self.last_run_at: Optional[float] = None
        self.last_message: Optional[str] = None
        self.failures = 0
        self.notified = False                 # 這一串失敗通知過擁有者了
        self.next_due: Optional[float] = None
        self.running_since: Optional[float] = None
        self.generation = 0
        self.before_run = "idle"              # 開始跑之前的 state（做完時當作 prev，判斷「從失敗恢復」用）
        self.cause: Optional[Cause] = None    # 這一次執行是哪一串連動叫的（沒有＝排程或手動）
        self.log: Deque[str] = deque(maxlen=LOG_LINES)
        self.lock = threading.Lock()

    @property
    def schedule(self) -> str:
        if self._schedule:
            return self._schedule
        if self.fn is not None and not self.interval:
            return "關閉"
        return every_text(self.interval)

    def set_schedule_text(self, text: str) -> None:
        self._schedule = text

    def add_log(self, line: str) -> None:
        self.log.append(f"{iso(self._clock())} {clean_text(line, LINE_MAX)}")

    def view(self) -> dict:
        return {"id": self.id, "name": self.name, "owner": self.owner, "schedule": self.schedule, "state": self.state,
                "last_run_at": iso(self.last_run_at), "last_message": self.last_message}


class RuntimeLoop:

    def __init__(self, app, *, clock: Callable[[], float] = time.time, spawn: Optional[Callable] = None,
                 notify: Optional[Callable[[str], None]] = None, state_path: Optional[str] = None):
        self.app = app
        self._clock = clock
        self._spawn = spawn or self._thread
        self._notify = notify or (lambda text: app.notify_owner(text))
        self.tasks: Dict[str, Task] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread_obj: Optional[threading.Thread] = None
        data_dir = getattr(getattr(app, "config", None), "data_dir", "") or ""
        self.state_path = state_path if state_path is not None else (os.path.join(data_dir, STATE_FILE) if data_dir else "")
        self._saved = self._load_saved()
        self.started = False
        self.listeners: List[Callable[[dict], None]] = []    # 狀態變了叫（activator.observe）

    # ── 存檔（沒有個人資料的部分）──────────────────────────────────────

    def _load_saved(self) -> dict:
        if not self.state_path:
            return {}
        try:
            data = jsonstore.load_json(self.state_path, {}) or {}
        except Exception:
            logging.exception("[RUNTIME] cannot read %s", self.state_path)
            return {}
        return data if isinstance(data, dict) else {}

    def saved(self, key: str, default=None):
        return self._saved.get(key, default)

    def save(self, **extra) -> None:
        """寫 data/runtime/state.json：每個任務的 state、時間、連續失敗數＋呼叫端給的（心跳的上一次）。"""
        if not self.state_path:
            return
        with self._lock:
            self._saved.update(extra)
            self._saved["tasks"] = {t.id: {"state": t.state, "last_run_at": t.last_run_at, "failures": t.failures}
                                    for t in self.tasks.values()}
            data = dict(self._saved)
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            jsonstore.save_json(self.state_path, data)
        except Exception:
            logging.exception("[RUNTIME] cannot write %s", self.state_path)

    # ── 登記 ─────────────────────────────────────────────────────────

    def register(self, task_id: str, name: str, *, owner: str = "system", fn: Optional[Callable] = None,
                 interval: Optional[float] = None, timeout: float = DEFAULT_TIMEOUT, first_delay: Optional[float] = None,
                 schedule: str = "") -> Task:
        """登記（同 id 再登記＝換掉設定，保留狀態）。first_delay：第一次在幾秒後跑（預設＝一個間隔後）。"""
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                task = Task(task_id, name, owner, fn=fn, interval=interval, timeout=timeout, schedule=schedule,
                            clock=self._clock)
                old = (self._saved.get("tasks") or {}).get(task_id) or {}
                if isinstance(old.get("last_run_at"), (int, float)):
                    task.last_run_at = float(old["last_run_at"])
                if old.get("state") in ("ok", "failed"):
                    task.state = old["state"]
                if isinstance(old.get("failures"), int):
                    task.failures = max(0, old["failures"])
                self.tasks[task_id] = task
            else:
                task.name, task.owner, task.fn, task.timeout = name, owner, fn, float(timeout)
                task.interval = float(interval) if interval else None
                task.set_schedule_text(schedule)
            if task.interval and task.fn is not None:
                delay = task.interval if first_delay is None else max(0.0, float(first_delay))
                task.next_due = self._clock() + delay
            else:
                task.next_due = None
            return task

    def reschedule(self, task_id: str, interval: Optional[float]) -> Optional[Task]:
        """改間隔（心跳的設定改了）：下一次＝上一次＋新間隔（已經過了＝60 秒後）；沒跑過＝現在＋新間隔；None＝關掉。"""
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return None
            task.interval = float(interval) if interval else None
            now = self._clock()
            if not task.interval or task.fn is None:
                task.next_due = None
                if task.state != "running":
                    task.state = "idle" if task.state != "failed" else task.state
            elif task.last_run_at is None:
                task.next_due = now + task.interval
            else:
                task.next_due = max(now + 60.0, task.last_run_at + task.interval)
            return task

    def task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def views(self) -> List[dict]:
        with self._lock:
            tasks = list(self.tasks.values())
        tasks.sort(key=lambda t: (0 if t.owner == "system" else 1, t.id))
        return [t.view() for t in tasks]

    # ── 回報（pack、或任務自己在執行中說）───────────────────────────────

    def report(self, task_id: str, state: str, message: str = "", *, name: str = "", owner: str = "",
               tag: str = "") -> Optional[Task]:
        """pack 回報狀態（SDK report_status／Pack.report_status）。state 不是四種之一＝忽略、回 None。
        tag：選填的短標籤（例如 "diary-image"；小寫英數字與 . _ -、32 字內，不合＝當作沒有），連動規則可以只聽某個標籤。"""
        if state not in STATES or not ID_RE.match(task_id or ""):
            return None
        tag = tag if isinstance(tag, str) and TAG_RE.match(tag) else ""
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                task = self.register(task_id, name or task_id, owner=owner or task_id.split(".", 1)[-1])
            if task.fn is not None and task.running_since is not None:
                # 排程的任務正在跑：只記一行，最後的狀態由那次執行決定
                task.add_log(f"回報 {state} {message}")
                return task
            if name:
                task.name = name
            prev = task.state
            task.state = state
            task.last_run_at = self._clock()
            task.last_message = clean_text(message, MESSAGE_MAX) or None
            task.add_log((f"{state} {message}".strip() + (f" #{tag}" if tag else "")).strip())
        self.save()
        self._emit(task, prev, tag, current_cause())
        return task

    def _emit(self, task: Task, prev: str, tag: str = "", cause: Optional[Cause] = None) -> None:
        """狀態變了 → 叫 listeners（鎖外；例外只記 log，不能弄壞任務或回報）。"""
        if not self.listeners:
            return
        change = {"task": task.id, "owner": task.owner, "state": task.state, "prev": prev, "tag": tag,
                  "at": task.last_run_at, "message": task.last_message or "", "cause": cause}
        for listener in list(self.listeners):
            try:
                listener(change)
            except Exception:
                logging.exception("[RUNTIME] listener failed for %s", task.id)

    def peer_states(self) -> Dict[str, dict]:
        """給工具看的別人的狀態：只有 state 與時間，沒有訊息（訊息可能有個人資料）。"""
        with self._lock:
            return {t.id: {"state": t.state, "at": iso(t.last_run_at)} for t in self.tasks.values()}

    # ── 跑 ───────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread_obj is not None and self._thread_obj.is_alive():
            return
        self._stop.clear()
        self.started = True
        self._thread_obj = threading.Thread(target=self._run, daemon=True, name="RuntimeLoop")
        self._thread_obj.start()
        logging.info("[RUNTIME] loop started (every %ss, %d tasks)", TICK_SECONDS, len(self.tasks))

    def stop(self) -> None:
        self._stop.set()
        self.started = False

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logging.exception("[RUNTIME] tick failed")
            self._stop.wait(TICK_SECONDS)

    @staticmethod
    def _thread(fn: Callable[[], None], name: str) -> None:
        threading.Thread(target=fn, daemon=True, name=f"Runtime-{name}").start()

    def tick(self, now: Optional[float] = None) -> List[str]:
        """看一次：逾時的標失敗、到點的開始跑。回這次開始跑的任務 id（測試用）。"""
        now = self._clock() if now is None else now
        started = []
        with self._lock:
            tasks = list(self.tasks.values())
        for task in tasks:
            timed_out = None
            with task.lock:
                if task.running_since is not None and now - task.running_since > task.timeout:
                    task.generation += 1
                    task.running_since = None
                    timed_out = (task.before_run, task.cause)
                    task.cause = None
                    self._failed(task, f"逾時（超過 {int(task.timeout)} 秒）", now)
            if timed_out is not None:
                self._emit(task, timed_out[0], "", timed_out[1])
                continue
            with task.lock:
                due = (task.fn is not None and task.next_due is not None and task.running_since is None
                       and now >= task.next_due)
            if due:
                self.run_now(task.id, manual=False)
                started.append(task.id)
        return started

    def run_now(self, task_id: str, *, manual: bool = True, cause: Optional[Cause] = None) -> bool:
        """開始跑一次（不等它做完）。上一次還沒結束／沒有這個任務／沒有 fn＝False。
        cause：連動叫的（沒給＝看這條執行緒是不是在某一串連動裡）；做完的狀態變化接在那一串上。"""
        task = self.tasks.get(task_id)
        if task is None or task.fn is None:
            return False
        cause = cause or current_cause()
        with task.lock:
            if task.running_since is not None:
                return False
            now = self._clock()
            task.running_since = now
            task.generation += 1
            gen = task.generation
            task.before_run = task.state
            task.cause = cause
            task.state = "running"
            task.add_log("開始" + ("（手動）" if manual else "（連動）" if cause is not None else ""))
        self._spawn(lambda: self._execute(task, gen, manual), task.id)
        return True

    def _execute(self, task: Task, gen: int, manual: bool) -> None:
        from synox.guard.origin import Origin, using
        try:
            with using(Origin("system", 0, surface="runtime:" + str(task.id)[:40])):      # 背景任務的來源（ADR 0025 §2）
                result = task.fn(TaskContext(task, manual))
            error = None
        except Exception as e:
            logging.exception("[RUNTIME] task %s failed", task.id)
            result, error = None, f"{type(e).__name__}: {e}"
        now = self._clock()
        with task.lock:
            if gen != task.generation or task.running_since is None:
                return                                    # 已經判逾時了：晚回來的結果不算
            task.running_since = None
            prev, cause, task.cause = task.before_run, task.cause, None
            if error is not None:
                self._failed(task, error, now)
            else:
                self._ok(task, "" if result is None else str(result), now)
        self.save()
        self._emit(task, prev, "", cause)

    def _ok(self, task: Task, message: str, now: float) -> None:
        recovered = task.notified
        task.state = "ok"
        task.last_run_at = now
        task.last_message = clean_text(message, MESSAGE_MAX) or None
        task.failures = 0
        task.notified = False
        task.add_log(f"ok {message}".strip())
        if task.interval:
            task.next_due = now + task.interval
        if recovered:
            self._say(f"✅ 背景任務「{task.name}」恢復正常了。")

    def _failed(self, task: Task, error: str, now: float) -> None:
        task.state = "failed"
        task.last_run_at = now
        task.last_message = clean_text(error, MESSAGE_MAX)
        task.failures += 1
        task.add_log(f"failed {error}")
        if task.interval:
            if task.failures >= NOTIFY_AFTER:
                wait = max(task.interval, LONG_BACKOFF)
            else:
                wait = min(task.interval, RETRY_BASE * (2 ** (task.failures - 1)))
            task.next_due = now + wait
        if task.failures >= NOTIFY_AFTER and not task.notified:
            task.notified = True
            self._say(f"⚠️ 背景任務「{task.name}」連續失敗 {task.failures} 次（最後：{task.last_message}）。"
                      "會繼續隔一段時間重試；網頁主控面板看得到日誌。")
        self.save()

    def _say(self, text: str) -> None:
        try:
            self._notify(text)
        except Exception:
            logging.exception("[RUNTIME] notify failed")
