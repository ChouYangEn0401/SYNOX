"""
Telegram 指令（群組 link，只給擁有者；主控台跟哨兵都有 /link_status、/link_peers，派任務的只有主控台）：

    /link_status                     這台的角色、node_id、傳輸層、每個 peer 在不在線、任務數
    /link_peers                      名單（名字、node_id、角色、上次看到）
    /link_run <哨兵> <指令…>          主控台：派一個指令給一台哨兵（哨兵可以寫名字或 node_id 前幾碼）
    /link_tasks                      主控台：最近的任務
    /link_task <編號>                 主控台：一個任務的結果全文
    /link_redo <編號>                 主控台：同一台再做一次
    /link_handoff <編號> <哨兵>       主控台：交給另一台（帶上一個任務的結果）
    /link_cancel <編號>               主控台：取消
    /link_forget <哨兵>               把一台從名單拿掉（它寄來的信從此不收）
配對不在聊天裡做（配對碼是祕密）：`python -m synox link pair`／`link join`，見 docs/link.md。
"""

from __future__ import annotations

import time
from typing import Optional

from isdtelekit.core.registry import DANGER, WRITE

from synox.link import protocol as P
from synox.link.identity import short_id
from synox.packs.loader import group_policy

NO_CONSOLE = "這台是哨兵（link.role=worker），派任務要在主控台那邊打。"


def _ago(stamp: Optional[float]) -> str:
    if not stamp:
        return "還沒看到"
    s = int(time.time() - stamp)
    return "剛剛" if s < 5 else (f"{s} 秒前" if s < 120 else f"{s // 60} 分鐘前")


def _task_line(task: P.Task) -> str:
    return f"{task.id}  {P.STATE_LABELS.get(task.state, task.state)}  {short_id(task.worker)}  {task.command}"


def install(app, link) -> None:
    """link：synox.link.Link（node、console／worker 角色、book）。"""
    registry = app.registry
    registry.ensure_group("link", "🔗 兩台 SYNOX 連線", "主控台派任務給哨兵、看狀態、重做、交接",
                          **group_policy(app, "owner", getattr(app.config, "mode", "personal") == "server"))
    g = registry.group("link")
    node, console = link.node, link.console

    def cmd_status(api, chat_id, user, args):
        st = node.status()
        t = st["transport"]
        where = t.get("where") or t.get("dir") or t.get("kind")
        lines = [f"🔗 這台：{st['name']}（{st['node_id']}）　角色：{'主控台' if st['role'] == 'console' else '哨兵'}",
                 f"傳輸：{t.get('kind')} {where}" + (f"　❌ {t['error']}" if t.get("error") else "") +
                 ("" if st["started"] else "　（還沒啟動：終端機模式不開連線）")]
        if not st["peers"]:
            lines.append("名單是空的：先配對（python -m synox link pair／join，見 docs/link.md）。")
        for p in st["peers"]:
            lines.append(f"• {'🟢' if p['online'] else '⚪'} {p['name'] or '?'}（{short_id(p['node_id'])}）"
                         f" {'主控台' if p['role'] == 'console' else '哨兵'}　{_ago(p['last_seen'])}")
        if console is not None:
            open_tasks = console.book.items(open_only=True, limit=100)
            lines.append(f"任務：{len(open_tasks)} 個進行中（/link_tasks）")
        api.send_message(chat_id, "\n".join(lines))

    def cmd_peers(api, chat_id, user, args):
        entries = node.peers.entries()
        if not entries:
            api.send_message(chat_id, "名單是空的：先配對（python -m synox link pair／join，見 docs/link.md）。")
            return
        lines = ["🔗 名單："]
        for e in entries:
            card = e.get("card") or {}
            lines.append(f"• {card.get('name', '?')}  {e['node_id']}  {'主控台' if e.get('role') == 'console' else '哨兵'}"
                         f"　{'🟢 在線' if node.online(e['node_id']) else '⚪ ' + _ago(node.last_seen(e['node_id']))}")
        api.send_message(chat_id, "\n".join(lines))

    def _worker(api, chat_id, text) -> Optional[str]:
        found = node.peers.find(text)
        if found is None or node.peers.role_of(found) != "worker":
            names = "、".join(f"{(node.peers.get(w).name if node.peers.get(w) else '?')}（{short_id(w)}）"
                             for w in node.peers.ids(role="worker")) or "（名單裡沒有哨兵）"
            api.send_message(chat_id, f"❌ 找不到哨兵「{text}」。名單：{names}")
            return None
        return found

    def cmd_run(api, chat_id, user, args):
        if console is None:
            api.send_message(chat_id, NO_CONSOLE)
            return
        if len(args) < 2:
            api.send_message(chat_id, "用法：/link_run <哨兵> <指令…>　例如 /link_run 客廳 /note 買牛奶")
            return
        worker = _worker(api, chat_id, args[0])
        if worker is None:
            return
        try:
            task = console.dispatch(worker, " ".join(args[1:]), requested_by=user.tg_id)
        except ValueError as e:
            api.send_message(chat_id, f"❌ {e}")
            return
        if task.state == P.FAILED:
            api.send_message(chat_id, f"❌ 任務 {task.id} {task.error}（/link_redo {task.id} 等它上線再試）")
        else:
            api.send_message(chat_id, f"📤 任務 {task.id} 送給 {console.peer_name(worker)}：{task.command}\n"
                                      "做完會通知你；/link_tasks 看進度。")

    def cmd_tasks(api, chat_id, user, args):
        if console is None:
            api.send_message(chat_id, NO_CONSOLE)
            return
        tasks = console.book.items(limit=15)
        if not tasks:
            api.send_message(chat_id, "還沒有任務。/link_run <哨兵> <指令> 派一個。")
            return
        api.send_message(chat_id, "📋 最近的任務（編號　狀態　哨兵　指令）：\n" + "\n".join(_task_line(t) for t in tasks))

    def cmd_task(api, chat_id, user, args):
        if console is None:
            api.send_message(chat_id, NO_CONSOLE)
            return
        task = console.book.find(args[0]) if args else None
        if task is None:
            api.send_message(chat_id, "用法：/link_task <編號>（/link_tasks 看編號）")
            return
        lines = [f"📋 任務 {task.id}：{P.STATE_LABELS.get(task.state, task.state)}",
                 f"哨兵：{console.peer_name(task.worker)}　第 {task.attempts} 次", f"指令：{task.command}"]
        if task.lineage:
            lines.append(f"來自任務：{task.lineage}")
        if task.context.get("from_task"):
            lines.append(f"交接自：{task.context['from_task']}（{short_id(task.context.get('from_worker', ''))}）")
        if task.progress:
            lines.append(f"進度：{task.progress}")
        if task.error:
            lines.append(f"錯誤：{task.error}")
        if task.result:
            lines.append("回覆：\n" + task.result[:3000])
        api.send_message(chat_id, "\n".join(lines))

    def cmd_redo(api, chat_id, user, args):
        if console is None:
            api.send_message(chat_id, NO_CONSOLE)
            return
        try:
            task = console.redo(args[0] if args else "", requested_by=user.tg_id)
        except ValueError as e:
            api.send_message(chat_id, f"❌ {e}")
            return
        api.send_message(chat_id, f"🔁 任務 {task.id}（第 {task.attempts} 次，來自 {task.lineage}）送給 "
                                  f"{console.peer_name(task.worker)}：{task.command}")

    def cmd_handoff(api, chat_id, user, args):
        if console is None:
            api.send_message(chat_id, NO_CONSOLE)
            return
        if len(args) < 2:
            api.send_message(chat_id, "用法：/link_handoff <編號> <哨兵> [新指令…]")
            return
        worker = _worker(api, chat_id, args[1])
        if worker is None:
            return
        try:
            task = console.handoff(args[0], worker, command=" ".join(args[2:]), requested_by=user.tg_id)
        except ValueError as e:
            api.send_message(chat_id, f"❌ {e}")
            return
        api.send_message(chat_id, f"🤝 任務 {task.lineage} 交接成 {task.id}，送給 {console.peer_name(worker)}：{task.command}")

    def cmd_cancel(api, chat_id, user, args):
        if console is None:
            api.send_message(chat_id, NO_CONSOLE)
            return
        try:
            task = console.cancel(args[0] if args else "")
        except ValueError as e:
            api.send_message(chat_id, f"❌ {e}")
            return
        api.send_message(chat_id, f"🛑 任務 {task.id} 取消了（對方已經開始做的話會做完，但結果不會記）。")

    def cmd_forget(api, chat_id, user, args):
        found = node.peers.find(args[0]) if args else None
        if found is None:
            api.send_message(chat_id, "用法：/link_forget <哨兵或主控台>（/link_peers 看名單）")
            return
        name = node.peers.get(found).name if node.peers.get(found) else "?"
        node.peers.remove(found)
        api.send_message(chat_id, f"🗑 {name}（{short_id(found)}）從名單拿掉了；它寄來的信從此不收。要再接上就重新配對。")

    g.leaf("status", cmd_status, "這台的連線狀態、名單、任務數", ai=True)
    g.leaf("peers", cmd_peers, "名單：認得哪些 SYNOX", ai=True)
    g.leaf("run", cmd_run, "派一個指令給一台哨兵", usage="<哨兵> <指令…>", effect=WRITE, ai=True)
    g.leaf("tasks", cmd_tasks, "最近的任務", ai=True)
    g.leaf("task", cmd_task, "一個任務的結果全文", usage="<編號>", ai=True)
    g.leaf("redo", cmd_redo, "同一台再做一次", usage="<編號>", effect=WRITE, ai=True)
    g.leaf("handoff", cmd_handoff, "交給另一台哨兵（帶上一個任務的結果）", usage="<編號> <哨兵> [新指令…]",
           effect=WRITE, ai=True)
    g.leaf("cancel", cmd_cancel, "取消一個任務", usage="<編號>", effect=WRITE, ai=True)
    g.leaf("forget", cmd_forget, "把一台從名單拿掉", usage="<哨兵>", effect=DANGER, ai=False)


__all__ = ["install"]
