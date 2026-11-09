"""
/remind_add <HH:MM> <文字> [date=YYYY-MM-DD]、/remind_list、/remind_rm <n>（掛在 packs/remind 的群組）；
/schedule_add <HH:MM> /<指令> …、/schedule_list、/schedule_rm <n>（這裡自己定義 schedule 群組）。

/schedule_add 設了 Node.wraps：「之後替你執行另一個指令」的節點，危險程度連裡面那個一起算（Node.effect_of），
所以 AI 想排一個危險指令會先出核准卡；建立時用 via=SCHEDULE 對裡面那個指令跑一次 authorize()
（「要看參數才知道」的權限檢查，SDK invariant 1 允許的例外），觸發時 runner 再以 via=ROUTINE 檢查一次。
"""

from __future__ import annotations

import re
from datetime import date as Date
from typing import List, Optional, Tuple

from isdtelekit.core.registry import SCHEDULE, WRITE, Field, Node

from synox.packs import kit
from synox.schedule.store import ScheduleStore

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_date(value: str) -> Optional[str]:
    if not DATE_RE.match(value):
        return "要是 YYYY-MM-DD（例如 2026-11-20）"
    try:
        day = Date.fromisoformat(value)
    except ValueError:
        return "不是真的日期"
    if day < Date.today():
        return "已經過了"
    return None


def store_for(app) -> ScheduleStore:
    store = app.extras.get("synox_schedule_store")
    if store is None:
        store = app.extras["synox_schedule_store"] = ScheduleStore(app.config.data_dir, app.extras.get("vault"))
    return store


def _when(item: dict) -> str:
    return f"{item['date']} {item['time']}（一次）" if item.get("date") else f"每天 {item['time']}"


# ── /remind_* ────────────────────────────────────────────────────────

def install_remind(app, group) -> None:
    store = store_for(app)

    def add(api, chat_id, user, values):
        item = store.add("remind", values["time"], user.tg_id, text=values["text"].strip(),
                         date=values.get("date", ""))
        n = len(store.items("remind"))
        api.send_message(chat_id, f"⏰ 好，{_when(item)} 提醒你：{item['text']}（第 {n} 個）\n"
                                  "（提醒只有 bot 開著時才會送出）")

    def list_(api, chat_id, user, values):
        items = store.items("remind")
        if not items:
            api.send_message(chat_id, "⏰ 還沒有提醒。用 /remind_add 08:00 吃藥 加一個。")
            return
        lines = ["⏰ 提醒"] + [f"{i}. {_when(it)}  {it['text']}" for i, it in enumerate(items, 1)]
        api.send_message(chat_id, "\n".join(lines))

    def rm(api, chat_id, user, values):
        gone = store.remove_nth("remind", int(values["n"]))
        if gone is None:
            api.send_message(chat_id, f"❌ 沒有第 {values['n']} 個（/remind_list 看編號）。")
            return
        api.send_message(chat_id, f"🗑 刪掉提醒：{_when(gone)} {gone['text']}")

    kit.command(group, "add", add, "加一個提醒（每天，或 date= 指定那天一次）", effect=WRITE, positional=2, fields=[
        Field("time", "時間 HH:MM", required=True, check=kit.hhmm),
        Field("text", "提醒什麼", required=True),
        Field("date", "只提醒一次的日期 YYYY-MM-DD", check=check_date)])
    kit.command(group, "list", list_, "列出提醒")
    kit.command(group, "rm", rm, "刪掉一個提醒", effect=WRITE,
                fields=[Field("n", "編號", required=True, check=kit.positive_int)])


# ── /schedule_* ──────────────────────────────────────────────────────

SCHEDULE_FIELDS = (Field("time", "時間 HH:MM", required=True, check=kit.hhmm),
                   Field("command", "要執行的指令（/ 開頭，可以帶參數）", required=True),
                   Field("date", "只跑一次的日期 YYYY-MM-DD", check=check_date))


def install_schedule(app) -> None:
    registry = app.registry
    store = store_for(app)
    registry.ensure_group("schedule", "🗓 排程指令", "每天幾點自動替你執行一個指令", owner_only=True)
    g = registry.group("schedule")

    def wraps(args: List[str]) -> Optional[Tuple[Node, List[str]]]:
        values, _missing, _errors = kit.parse_args(SCHEDULE_FIELDS, args, 2)
        command = values.get("command", "").strip()
        if not command.startswith("/"):
            return None
        node, inner_args = registry.resolve(command)
        if node is None or node.is_group or node is add_node:
            return None
        return node, inner_args

    def add(api, chat_id, user, values):
        found = add_node.inner(["time=" + values["time"], "command=" + values["command"]])
        if found is None:
            api.send_message(chat_id, "❌ 看不懂要排的指令：要是一個存在的 /指令（不能是群組名、也不能排 /schedule_add 自己）。")
            return
        inner, _inner_args = found
        decision = registry.authorize(user, inner, SCHEDULE, chat_id)
        if not decision.allowed:
            api.send_message(chat_id, f"❌ {inner.command} 不能排進排程：{decision.message}")
            return
        item = store.add("command", values["time"], user.tg_id, command=values["command"].strip(),
                         date=values.get("date", ""))
        api.send_message(chat_id, f"🗓 好，{_when(item)} 替你執行：{item['command']}\n（只有 bot 開著時才會執行）")

    def list_(api, chat_id, user, values):
        items = store.items("command")
        if not items:
            api.send_message(chat_id, "🗓 還沒有排程。例：/schedule_add 21:00 /money_month")
            return
        lines = ["🗓 排程"] + [f"{i}. {_when(it)}  {it['command']}" for i, it in enumerate(items, 1)]
        api.send_message(chat_id, "\n".join(lines))

    def rm(api, chat_id, user, values):
        gone = store.remove_nth("command", int(values["n"]))
        if gone is None:
            api.send_message(chat_id, f"❌ 沒有第 {values['n']} 個（/schedule_list 看編號）。")
            return
        api.send_message(chat_id, f"🗑 刪掉排程：{_when(gone)} {gone['command']}")

    add_node = kit.command(g, "add", add, "排一個指令（每天，或 date= 那天一次）", effect=WRITE, positional=2,
                           fields=SCHEDULE_FIELDS)
    add_node.wraps = wraps
    kit.command(g, "list", list_, "列出排程")
    kit.command(g, "rm", rm, "刪掉一個排程", effect=WRITE,
                fields=[Field("n", "編號", required=True, check=kit.positive_int)])
