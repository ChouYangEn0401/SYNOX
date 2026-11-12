"""
/remind_add <HH:MM> <文字> [date=YYYY-MM-DD]、/remind_list、/remind_rm <n>（系統群組「⏰ 提醒（系統）」，install_system_remind）；
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
from synox.packs.loader import group_policy
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
        config = app.extras.get("synox_config")
        server = getattr(config, "mode", "personal") == "server"
        store = app.extras["synox_schedule_store"] = ScheduleStore(app.config.data_dir, app.extras.get("vault"),
                                                                   per_user=server)
    return store


def _when(item: dict) -> str:
    return f"{item['date']} {item['time']}（一次）" if item.get("date") else f"每天 {item['time']}"


# ── /remind_*：⏰ 提醒（系統）───────────────────────────────────────────
#
# 提醒是 SYNOX 的**系統指令**（擁有者 2026-11-12，QuestionToUser QL5），跟 /help、/schedule_* 同一層：不是可裝可卸的
# pack，不在工具庫（SYNOX_Libs 的舊 remind 工具在它的 legacy/）。名字刻意標「（系統）」：工具很容易也叫 remind／reminder，
# Apple 提醒事項（connector apple-reminders）也是另一回事。群組名 remind 保留給這裡：pack 宣告 group=remind 會載不進去
# （loader.system_group_problem）。指令名、AI 工具名（remind__add…）、資料（data/schedule.json.enc）都跟以前一樣。

REMIND_GROUP = "remind"
REMIND_TITLE = "⏰ 提醒（系統）"
REMIND_SUMMARY = "SYNOX 內建的提醒：每天幾點、或指定哪一天提醒你一件事（不是 Apple 提醒事項）"
REMIND_RETIRED = ("提醒已經是 SYNOX 的系統指令（⏰ 提醒（系統），/remind_* 照舊能用、資料沒動），"
                  "這個工具不需要了：到網頁「設定」移除它就好（移除只是搬到 packs/_removed/）。")


def install_system_remind(app) -> None:
    """⏰ 提醒（系統）：在 packs.load_all **之前**掛（群組名先佔住；舊的 remind 工具或撞名的 pack 由 loader 說明、不載入）。
    權限照以前的 remind pack（access: member、surfaces: dm）：個人版只有擁有者；伺服器版成員以上；只在私訊。"""
    from synox.packs.loader import SYSTEM_GROUPS_KEY
    config = app.extras.get("synox_config")
    server = getattr(config, "mode", "personal") == "server"
    group = app.registry.define_group(REMIND_GROUP, REMIND_TITLE, REMIND_SUMMARY, private_only=True,
                                      **group_policy(app, "member", server))
    install_remind(app, group)
    app.extras.setdefault(SYSTEM_GROUPS_KEY, {})[REMIND_GROUP] = REMIND_RETIRED


def install_remind(app, group) -> None:
    store = store_for(app)

    def add(api, chat_id, user, values):
        mine = store.of(user)
        item = mine.add("remind", values["time"], user.tg_id, text=values["text"].strip(),
                        date=values.get("date", ""))
        n = len(mine.items("remind"))
        api.send_message(chat_id, f"⏰ 好，{_when(item)} 提醒你：{item['text']}（第 {n} 個）\n"
                                  "（提醒只有 bot 開著時才會送出）")

    def list_(api, chat_id, user, values):
        items = store.of(user).items("remind")
        if not items:
            api.send_message(chat_id, "⏰ 還沒有提醒。用 /remind_add 08:00 吃藥 加一個。")
            return
        lines = [REMIND_TITLE] + [f"{i}. {_when(it)}  {it['text']}" for i, it in enumerate(items, 1)]
        api.send_message(chat_id, "\n".join(lines))

    def rm(api, chat_id, user, values):
        gone = store.of(user).remove_nth("remind", int(values["n"]))
        if gone is None:
            api.send_message(chat_id, f"❌ 沒有第 {values['n']} 個（/remind_list 看編號）。")
            return
        api.send_message(chat_id, f"🗑 刪掉提醒：{_when(gone)} {gone['text']}")

    # 欄位說明也是給 AI 看的（以前寫在 remind 工具的 SKILL.md）
    kit.command(group, "add", add, "加一個提醒（系統；每天，或 date= 指定那天一次）", effect=WRITE, positional=2, fields=[
        Field("time", "時間 HH:MM（24 小時制，下午 3 點＝15:00）", required=True, check=kit.hhmm),
        Field("text", "提醒什麼", required=True),
        Field("date", "只提醒一次的日期 YYYY-MM-DD（沒說年份就用今年；不填＝每天）", check=check_date)])
    kit.command(group, "list", list_, "列出提醒（系統）")
    kit.command(group, "rm", rm, "刪掉一個提醒（系統；先 /remind_list 看編號）", effect=WRITE,
                fields=[Field("n", "編號", required=True, check=kit.positive_int)])


# ── /schedule_* ──────────────────────────────────────────────────────

SCHEDULE_FIELDS = (Field("time", "時間 HH:MM", required=True, check=kit.hhmm),
                   Field("command", "要執行的指令（/ 開頭，可以帶參數）", required=True),
                   Field("date", "只跑一次的日期 YYYY-MM-DD", check=check_date))


def install_schedule(app) -> None:
    registry = app.registry
    store = store_for(app)
    config = app.extras.get("synox_config")
    server = getattr(config, "mode", "personal") == "server"
    # 個人版：只有擁有者；伺服器版：成員以上，每個人排自己的（建立時以他的身分 via=SCHEDULE 檢查裡面那個指令）
    registry.ensure_group("schedule", "🗓 排程指令", "每天幾點自動替你執行一個指令",
                          **group_policy(app, "member", server))
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
        item = store.of(user).add("command", values["time"], user.tg_id, command=values["command"].strip(),
                                  date=values.get("date", ""))
        api.send_message(chat_id, f"🗓 好，{_when(item)} 替你執行：{item['command']}\n（只有 bot 開著時才會執行）")

    def list_(api, chat_id, user, values):
        items = store.of(user).items("command")
        if not items:
            api.send_message(chat_id, "🗓 還沒有排程。例：/schedule_add 21:00 /money_month")
            return
        lines = ["🗓 排程"] + [f"{i}. {_when(it)}  {it['command']}" for i, it in enumerate(items, 1)]
        api.send_message(chat_id, "\n".join(lines))

    def rm(api, chat_id, user, values):
        gone = store.of(user).remove_nth("command", int(values["n"]))
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
