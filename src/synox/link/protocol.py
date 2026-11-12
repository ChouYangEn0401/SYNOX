"""
任務協定（SYNOX Link，架構 v1 §L4）：主控台跟哨兵之間講的話。信封的 kind 與 body：

    主控台 → 哨兵                               哨兵 → 主控台
    task.offer   {task}                          task.accepted  {id}
    task.cancel  {id}                            task.rejected  {id, reason}
    ping         {}                              task.progress  {id, text}
                                                 task.result    {id, ok, text, error}
                                                 pong           {}
    雙向：hello {name, role}（連上時）、heartbeat {}、pair.request／pair.ok（pairing.py）

任務（Task）的狀態機：offered → accepted → running → done｜failed｜rejected｜cancelled；
重做（redo）與交接（handoff）都是「開一個新任務、lineage 指回舊的」，舊的不動——歷史永遠看得到。
TaskBook：主控台的任務簿（保管箱 data/link_tasks.json.enc；最多留 MAX_TASKS 筆，舊的從已結束的開始丟）。
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

OFFERED, ACCEPTED, RUNNING, DONE, FAILED, REJECTED, CANCELLED = (
    "offered", "accepted", "running", "done", "failed", "rejected", "cancelled")
OPEN_STATES = (OFFERED, ACCEPTED, RUNNING)
END_STATES = (DONE, FAILED, REJECTED, CANCELLED)
STATE_LABELS = {OFFERED: "已送出", ACCEPTED: "對方接了", RUNNING: "執行中", DONE: "完成", FAILED: "失敗",
                REJECTED: "被拒", CANCELLED: "取消"}

TASK_OFFER, TASK_CANCEL, TASK_ACCEPTED, TASK_REJECTED, TASK_PROGRESS, TASK_RESULT = (
    "task.offer", "task.cancel", "task.accepted", "task.rejected", "task.progress", "task.result")
HELLO, HEARTBEAT, PING, PONG = "hello", "heartbeat", "ping", "pong"
PAIR_REQUEST, PAIR_OK = "pair.request", "pair.ok"

VAULT_NAME = "link_tasks"
MAX_TASKS = 500
MAX_TEXT = 8000                     # 結果文字最多留這麼多字（信封本身 1 MB 以內）


def new_task_id() -> str:
    return time.strftime("%m%d") + "-" + secrets.token_hex(3)


@dataclass
class Task:
    id: str
    command: str                        # 要在哨兵上跑的指令（跟打字一樣：/note 買牛奶）
    worker: str                         # 哨兵的 node_id
    state: str = OFFERED
    created: int = field(default_factory=lambda: int(time.time()))
    updated: int = field(default_factory=lambda: int(time.time()))
    result: str = ""                    # 哨兵回的文字（指令的回覆）
    error: str = ""                     # 失敗／被拒的原因
    progress: str = ""
    lineage: str = ""                   # 重做／交接自哪一個任務
    context: dict = field(default_factory=dict)   # 交接時帶過去的東西（上一個任務的結果…）
    requested_by: int = 0               # 主控台這邊是誰下的（tg_id）
    attempts: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Task":
        known = {k: raw.get(k) for k in cls.__dataclass_fields__ if k in raw}
        return cls(**known)

    @property
    def open(self) -> bool:
        return self.state in OPEN_STATES

    def wire(self) -> dict:
        """送給哨兵的部分（不含主控台自己的紀錄）。"""
        return {"id": self.id, "command": self.command, "lineage": self.lineage, "context": self.context,
                "attempts": self.attempts}


class TaskBook:
    """主控台的任務簿。"""

    def __init__(self, vault):
        self._vault = vault
        self._lock = threading.RLock()
        self._tasks: Optional[Dict[str, Task]] = None

    def _load(self) -> Dict[str, Task]:
        if self._tasks is None:
            raw = self._vault.load_json(VAULT_NAME, None) or {}
            self._tasks = {}
            for item in raw.get("tasks") or []:
                try:
                    task = Task.from_dict(item)
                except TypeError:
                    continue
                self._tasks[task.id] = task
        return self._tasks

    def _save(self) -> None:
        tasks = list(self._load().values())
        if len(tasks) > MAX_TASKS:
            ended = sorted((t for t in tasks if not t.open), key=lambda t: t.updated)
            for old in ended[:len(tasks) - MAX_TASKS]:
                del self._tasks[old.id]
        self._vault.save_json(VAULT_NAME, {"v": 1, "tasks": [t.to_dict() for t in self._load().values()]})

    def add(self, task: Task) -> Task:
        with self._lock:
            self._load()[task.id] = task
            self._save()
            return task

    def get(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self._load().get(task_id)

    def find(self, text: str) -> Optional[Task]:
        text = (text or "").strip()
        with self._lock:
            tasks = self._load()
            if text in tasks:
                return tasks[text]
            hits = [t for t in tasks.values() if t.id.endswith(text)] if text else []
        return hits[0] if len(hits) == 1 else None

    def update(self, task_id: str, **changes) -> Optional[Task]:
        with self._lock:
            task = self._load().get(task_id)
            if task is None:
                return None
            for key, value in changes.items():
                if key in ("result", "error", "progress") and isinstance(value, str):
                    value = value[:MAX_TEXT]
                setattr(task, key, value)
            task.updated = int(time.time())
            self._save()
            return task

    def items(self, *, open_only: bool = False, limit: int = 20) -> List[Task]:
        with self._lock:
            tasks = sorted(self._load().values(), key=lambda t: t.created, reverse=True)
        if open_only:
            tasks = [t for t in tasks if t.open]
        return tasks[:limit]


__all__ = ["Task", "TaskBook", "new_task_id", "OFFERED", "ACCEPTED", "RUNNING", "DONE", "FAILED", "REJECTED",
           "CANCELLED", "OPEN_STATES", "END_STATES", "STATE_LABELS", "TASK_OFFER", "TASK_CANCEL", "TASK_ACCEPTED",
           "TASK_REJECTED", "TASK_PROGRESS", "TASK_RESULT", "HELLO", "HEARTBEAT", "PING", "PONG", "PAIR_REQUEST",
           "PAIR_OK", "MAX_TEXT"]
