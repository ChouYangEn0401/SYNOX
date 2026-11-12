"""
角色（SYNOX Link，架構 v1 §L8）：主控台派任務、哨兵做任務。兩邊都只訂閱事件匯流排，不直接碰傳輸層。

主控台 ConsoleRole
    dispatch(worker, "/note 買牛奶", requested_by=tg_id) → Task（寫進任務簿、送 task.offer）
    redo(task_id)      → 新任務、lineage 指回舊的、attempts+1
    handoff(task_id, other_worker) → 新任務給另一台、context 帶上一個任務的結果（交接）
    cancel(task_id)    → 送 task.cancel，本地標成取消
    收到 task.accepted／progress／result → 更新任務簿 → bus.publish("task.<狀態>") → 通知下任務的人（app.notify）

哨兵 WorkerRole
    收到 task.offer（只收名單上 role=console 的）→ 檢查：指令要在樹上、不能是群組／互動式、
    effect_of(args) 不能超過 link.max_effect、policy.decide(擁有者, via=ROUTINE) 要放行 → task.accepted
    → 自己的執行緒：Inbound(channel="link", 擁有者) 經 app.dispatcher.handle（同一個 authorize、同一條路）、
      CaptureChannel 把回覆收起來 → app.tasks.wait()（cli pack 的背景工作）→ task.result
    任何一關不過 → task.rejected（原因給主控台看）。同時最多 MAX_PARALLEL 個任務。
哨兵永遠以「哨兵自己的擁有者」身分跑指令：主控台那邊是誰下的，哨兵不管（也不信）——信任邊界是名單。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, List, Optional

from isdtelekit.core.channel import Inbound
from isdtelekit.core.registry import DANGER, READ, ROUTINE, WRITE
from isdtelekit.core.richtext import plain

from synox.link import protocol as P
from synox.link.identity import short_id
from synox.link.protocol import Task, TaskBook, new_task_id

LINK_CHANNEL = "link"
MAX_PARALLEL = 4
EFFECT_RANK = {READ: 0, WRITE: 1, DANGER: 2}


class CaptureChannel:
    """哨兵跑指令時的「回覆管子」：全部收進 texts，之後打包成 task.result。"""

    channel_name = LINK_CHANNEL

    def __init__(self):
        self.texts: List[str] = []
        self._n = 0

    def _ok(self) -> dict:
        self._n += 1
        return {"ok": True, "result": {"message_id": self._n}}

    def send_message(self, chat_id, text, reply_markup=None, quiet=False, link_preview=True, **kw):
        self.texts.append(plain(text))
        if reply_markup:
            self.texts.append("（這個指令出了按鈕；按鈕不能隔著 link 按）")
        return self._ok()

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kw):
        self.texts.append(plain(text))
        return self._ok()

    def send_photo(self, chat_id, photo, caption=""):
        self.texts.append(f"[圖片 {photo}] {caption}".strip())
        return self._ok()

    def send_document(self, chat_id, document, caption=""):
        self.texts.append(f"[檔案 {document}] {caption}".strip())
        return self._ok()

    def send_media_group(self, chat_id, photo_paths, caption="", kind="photo"):
        self.texts.append(f"[{len(photo_paths)} 張 {kind}] {caption}".strip())
        return self._ok()

    def remove_buttons(self, chat_id, message_id, **kw):
        return self._ok()

    def answer_callback_query(self, callback_query_id, text=None, **kw):
        return self._ok()

    def download_file(self, file_id, dest_path):
        return False

    def typing(self, chat_id):
        pass

    def delete_message(self, chat_id, message_id):
        return self._ok()

    def __getattr__(self, name):
        return lambda *a, **kw: self._ok()


# ── 主控台 ───────────────────────────────────────────────────────

class ConsoleRole:

    def __init__(self, node, book: TaskBook, notify: Callable[[int, str], None]):
        self.node = node
        self.book = book
        self.notify = notify
        bus = node.bus
        self._offs = [bus.subscribe("link.in." + P.TASK_ACCEPTED, self._accepted),
                      bus.subscribe("link.in." + P.TASK_REJECTED, self._rejected),
                      bus.subscribe("link.in." + P.TASK_PROGRESS, self._progress),
                      bus.subscribe("link.in." + P.TASK_RESULT, self._result)]

    def peer_name(self, node_id: str) -> str:
        card = self.node.peers.get(node_id)
        return f"{card.name}（{short_id(node_id)}）" if card else short_id(node_id)

    def workers(self) -> List[str]:
        return self.node.peers.ids(role="worker")

    def dispatch(self, worker: str, command: str, *, requested_by: int = 0, lineage: str = "",
                 context: Optional[dict] = None, attempts: int = 1) -> Task:
        if self.node.peers.role_of(worker) != "worker":
            raise ValueError(f"{short_id(worker)} 不是名單上的哨兵")
        command = (command or "").strip()
        if not command.startswith("/"):
            raise ValueError("要派的是一個指令（/ 開頭）")
        task = Task(id=new_task_id(), command=command, worker=worker, lineage=lineage, context=dict(context or {}),
                    requested_by=int(requested_by or 0), attempts=attempts)
        self.book.add(task)
        self.node.bus.publish("task.offered", task=task.to_dict())
        if not self.node.send(worker, P.TASK_OFFER, task.wire()):
            self.book.update(task.id, state=P.FAILED, error="送不出去：對方現在沒有連線")
            self.node.bus.publish("task.failed", task=task.to_dict())
        return task

    def redo(self, task_id: str, *, requested_by: int = 0) -> Task:
        old = self._need(task_id)
        return self.dispatch(old.worker, old.command, requested_by=requested_by or old.requested_by, lineage=old.id,
                             context=old.context, attempts=old.attempts + 1)

    def handoff(self, task_id: str, worker: str, *, command: str = "", requested_by: int = 0) -> Task:
        old = self._need(task_id)
        context = {"from_task": old.id, "from_worker": old.worker, "from_state": old.state,
                   "result": old.result, "error": old.error}
        return self.dispatch(worker, command or old.command, requested_by=requested_by or old.requested_by,
                             lineage=old.id, context=context)

    def cancel(self, task_id: str) -> Task:
        task = self._need(task_id)
        if not task.open:
            raise ValueError(f"任務 {task.id} 已經{P.STATE_LABELS[task.state]}了")
        self.node.send(task.worker, P.TASK_CANCEL, {"id": task.id})
        task = self.book.update(task.id, state=P.CANCELLED)
        self.node.bus.publish("task.cancelled", task=task.to_dict())
        return task

    def _need(self, task_id: str) -> Task:
        task = self.book.find(task_id)
        if task is None:
            raise ValueError(f"沒有任務 {task_id}（/link_tasks 看編號）")
        return task

    # ── 哨兵回來的 ──────────────────────────────────────────────

    def _task_of(self, event: dict) -> Optional[Task]:
        msg = event["msg"]
        task = self.book.get(str(msg.body.get("id", "")))
        if task is None or task.worker != msg.sender:
            logging.info("[LINK] %s for unknown task %s from %s", msg.kind, msg.body.get("id"), short_id(msg.sender))
            return None
        return task

    def _accepted(self, topic, event) -> None:
        task = self._task_of(event)
        if task is not None and task.state == P.OFFERED:
            task = self.book.update(task.id, state=P.RUNNING)
            self.node.bus.publish("task.running", task=task.to_dict())

    def _rejected(self, topic, event) -> None:
        task = self._task_of(event)
        if task is None or not task.open:
            return
        reason = str(event["msg"].body.get("reason") or "")
        task = self.book.update(task.id, state=P.REJECTED, error=reason)
        self._tell(task, f"⛔ 任務 {task.id} 被 {self.peer_name(task.worker)} 拒絕：{reason}\n指令：{task.command}")
        self.node.bus.publish("task.rejected", task=task.to_dict())      # 先通知人、再發事件（訂閱者看到時已通知）

    def _progress(self, topic, event) -> None:
        task = self._task_of(event)
        if task is not None and task.open:
            task = self.book.update(task.id, state=P.RUNNING, progress=str(event["msg"].body.get("text") or ""))
            self.node.bus.publish("task.progress", task=task.to_dict())

    def _result(self, topic, event) -> None:
        task = self._task_of(event)
        if task is None or not task.open:
            return
        body = event["msg"].body
        ok = bool(body.get("ok"))
        text, error = str(body.get("text") or ""), str(body.get("error") or "")
        task = self.book.update(task.id, state=P.DONE if ok else P.FAILED, result=text, error=error)
        who = self.peer_name(task.worker)
        if ok:
            self._tell(task, f"✅ 任務 {task.id}（{who}）完成：{task.command}\n{text or '（沒有回覆文字）'}")
        else:
            self._tell(task, f"❌ 任務 {task.id}（{who}）失敗：{task.command}\n{error or text}\n/link_redo {task.id} 重做")
        self.node.bus.publish("task.done" if ok else "task.failed", task=task.to_dict())

    def _tell(self, task: Task, text: str) -> None:
        if task.requested_by:
            try:
                self.notify(task.requested_by, text)
            except Exception:
                logging.exception("[LINK] notify failed")


# ── 哨兵 ─────────────────────────────────────────────────────────

class WorkerRole:

    def __init__(self, node, app, settings, *, run_in_thread: bool = True):
        self.node = node
        self.app = app
        self.settings = settings
        self.run_in_thread = run_in_thread
        self._cancelled: set = set()
        self._running: Dict[str, threading.Thread] = {}
        self._slots = threading.BoundedSemaphore(MAX_PARALLEL)
        self._lock = threading.Lock()
        bus = node.bus
        self._offs = [bus.subscribe("link.in." + P.TASK_OFFER, self._offer),
                      bus.subscribe("link.in." + P.TASK_CANCEL, self._cancel)]

    def check(self, command: str) -> Optional[str]:
        """這個指令能不能在這台跑；不能回原因（給主控台看的一句話）。"""
        command = (command or "").strip()
        if not command.startswith("/"):
            return "只接受指令（/ 開頭）"
        registry = self.app.registry
        node, args = registry.resolve(command)
        if node is None:
            return "這台沒有這個指令"
        if node.is_group:
            return "這是一個群組，不是指令"
        if node.interactive:
            return "互動式（會問問題）的指令不能隔著 link 跑"
        effect = node.effect_of(args)
        if EFFECT_RANK.get(effect, 2) > EFFECT_RANK[self.settings.max_effect]:
            return f"這個指令的效果是「{effect}」，超過這台 link.max_effect（{self.settings.max_effect}）"
        from synox import policy
        owner = self.app.users.get_or_create(self.app.owner_id)
        decision = policy.decide(self.app, owner, node, via=ROUTINE, chat_id=self.app.owner_id)
        if not decision.allowed:
            return f"這台的權限不放行（{decision.reason or 'denied'}）"
        return None

    def _offer(self, topic, event) -> None:
        msg = event["msg"]
        if self.node.peers.role_of(msg.sender) != "console":
            logging.info("[LINK] task.offer from non-console %s ignored", short_id(msg.sender))
            return
        task_id = str(msg.body.get("id") or "")
        command = str(msg.body.get("command") or "")
        if not task_id:
            return
        problem = self.check(command)
        if problem is not None:
            self.node.send(msg.sender, P.TASK_REJECTED, {"id": task_id, "reason": problem})
            self.node.bus.publish("worker.rejected", id=task_id, command=command, reason=problem)
            return
        if not self._slots.acquire(blocking=False):
            self.node.send(msg.sender, P.TASK_REJECTED, {"id": task_id, "reason": f"這台同時最多跑 {MAX_PARALLEL} 個任務"})
            return
        self.node.send(msg.sender, P.TASK_ACCEPTED, {"id": task_id})
        self.node.bus.publish("worker.accepted", id=task_id, command=command)
        if self.run_in_thread:
            t = threading.Thread(target=self._run, args=(msg.sender, task_id, command), daemon=True,
                                 name=f"Link-task-{task_id}")
            with self._lock:
                self._running[task_id] = t
            t.start()
        else:
            self._run(msg.sender, task_id, command)

    def _cancel(self, topic, event) -> None:
        task_id = str(event["msg"].body.get("id") or "")
        with self._lock:
            self._cancelled.add(task_id)

    def _run(self, console: str, task_id: str, command: str) -> None:
        try:
            with self._lock:
                if task_id in self._cancelled:
                    return
            ok, text, error = self.run_command(command)
            with self._lock:
                if task_id in self._cancelled:
                    self._cancelled.discard(task_id)
                    return
            self.node.send(console, P.TASK_RESULT, {"id": task_id, "ok": ok, "text": text[:P.MAX_TEXT],
                                                    "error": error[:P.MAX_TEXT]})
            self.node.bus.publish("worker.done" if ok else "worker.failed", id=task_id, command=command, text=text,
                                  error=error)
        except Exception as e:
            logging.exception("[LINK] task %s crashed", task_id)
            self.node.send(console, P.TASK_RESULT, {"id": task_id, "ok": False, "text": "", "error": f"{type(e).__name__}"})
        finally:
            with self._lock:
                self._running.pop(task_id, None)
            self._slots.release()

    def run_command(self, command: str):
        """以這台的擁有者身分跑一個指令，回 (ok, 回覆文字, 錯誤)。"""
        app = self.app
        api = CaptureChannel()
        inbound = Inbound(LINK_CHANNEL, user_id=app.owner_id, chat_id=app.owner_id, text=command, username="link",
                          sent_at=time.time())
        route = app.dispatcher.handle(api, inbound, via=ROUTINE)
        app.tasks.wait(self.settings.task_timeout)                 # cli pack 的背景工作
        text = "\n".join(t for t in api.texts if t)
        kind = getattr(route, "kind", "")
        if kind == "command" and not getattr(route, "error", ""):
            return True, text, ""
        if kind == "command":
            return False, text, f"指令執行時出錯：{route.error}"
        return False, text, f"沒有跑成（{route.reason or kind}）"


__all__ = ["ConsoleRole", "WorkerRole", "CaptureChannel", "LINK_CHANNEL", "MAX_PARALLEL"]
