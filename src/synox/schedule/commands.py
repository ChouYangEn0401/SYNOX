"""
/remind_add <時間> <文字> [date=YYYY-MM-DD] [repeat=daily|once]、/remind_todo <文字>、/remind_done <n>、/remind_list、
/remind_rm <n>、/remind_test（系統群組「⏰ 提醒（系統）」，install_system_remind；docs/adr/0029）；
  時間＝HH:MM（沒給日期＝每天，以前的用法）或時間用語（timeparse：「半小時後」「明天 9 點」…，兩種讀法差很多時反問、
  已經過了問「是要明天嗎？」）；排上了才用 receipt.emit 回固定的排程回執（字由程式產生）。
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
from synox.schedule.store import ScheduleStore, is_todo

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clock():
    """/remind_* 的「現在」（本機、不帶時區）。測試換成假時鐘：monkeypatch commands.clock。"""
    from datetime import datetime
    return datetime.now()


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
    if item.get("v") == 2 and item.get("repeat") == "none":
        return "待辦"
    text = f"{item['date']} {item['time']}（一次）" if item.get("date") else f"每天 {item['time']}"
    if item.get("v") == 2 and item.get("status") == "snoozed" and item.get("snooze_until"):
        from synox.schedule.reminder import from_iso, local_tz
        try:
            text += f"（延後到 {from_iso(item['snooze_until']).astimezone(local_tz()).strftime('%H:%M')}）"
        except ValueError:
            pass
    return text


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


REPEAT_WORDS = {"daily": "daily", "每天": "daily", "once": "once", "一次": "once", "只一次": "once"}
TIME_HELP = "要是 HH:MM（24 小時制，例如 08:00），或「半小時後」「明天9點」「+2h」這種說法"
SENTINEL_EXTRA = "synox_remind_sentinel"     # 提醒哨兵在跑（W2 設）：回執就不說「SYNOX 沒開時不會響」
CHANNEL_TEXT = {"web": "網頁", "telegram": "Telegram", "discord": "Discord", "chat": "聊天"}


def check_when(value: str) -> Optional[str]:
    """/remind_add 的時間：HH:MM，或時間用語（timeparse 看得懂的形狀；要不要問、過了沒，加的時候再判斷）。"""
    from synox.schedule import timeparse
    if kit.hhmm(value) is None:
        return None
    return None if timeparse.parse(value).kind != timeparse.NONE else TIME_HELP


def check_repeat(value: str) -> Optional[str]:
    return None if value.strip().lower() in REPEAT_WORDS else "要是 daily（每天）或 once（只一次）"


def planned_channels(app, uid: int) -> List[str]:
    """會送到哪些管道（id）：送達層接上了就問它（含電腦視窗）；還沒接上就照通知中心現在的判斷。"""
    from synox import notify
    from synox.notify import delivery
    from synox.notify.hub import CHANNEL_LABELS
    try:
        return list(delivery.planned_channels(app, uid, "alarm"))
    except NotImplementedError:
        pass
    hub = notify.of(app)
    if hub is None:
        return [delivery.CHAT]
    back = {label: cid for cid, label in CHANNEL_LABELS.items()}
    return [back[label] for label in hub.where(uid, "alarm") if label in back]


def make_receipt(app, uid: int, item: dict, now):
    """排上了的那一筆（v2 dict）→ 排程回執（docs/adr/0029 §3.2）。字由 receipt.reply_text() 產生。"""
    from synox.notify import alarms, delivery
    from synox.schedule import receipt, reminder
    from synox.schedule.engine import friendly
    todo = item.get("repeat") == reminder.NONE
    channels = planned_channels(app, uid)
    labels = [delivery.DESKTOP_LABEL if c == delivery.DESKTOP else CHANNEL_TEXT.get(c, c) for c in channels]
    config = app.extras.get("synox_config")
    server = getattr(config, "mode", "personal") == "server"
    sentinel = bool(app.extras.get(SENTINEL_EXTRA))
    not_when = [] if server else ["off", "asleep"]
    if not sentinel:
        not_when.append("app_closed")
    if channels == [delivery.WEB]:
        not_when.append("web_only")
    try:
        warns = [w["id"] for w in alarms.warnings(app, uid, uid == getattr(app, "owner_id", None))]
    except Exception:
        warns = []
    due = reminder.from_iso(item.get("due"))
    return receipt.ScheduleReceipt(
        kind=receipt.TODO if todo else receipt.REMIND, id=int(item["id"]), text=str(item.get("text", "")),
        repeat=str(item.get("repeat")), due=item.get("due"), when="" if due is None else friendly(due, now),
        channels=channels, channel_labels=labels, not_when=[] if todo else not_when,
        catch_up="boot" if sentinel else "next_start", ring_late_max_min=reminder.RING_LATE_MAX_MIN,
        missed_notice_max_h=reminder.MISSED_NOTICE_MAX_H, warnings=warns)


def publish_todos(app, uid: int) -> None:
    """待辦有變動（新增／完成／刪除）：整份交給電腦視窗的下半部（delivery.publish_todos；不是 Windows 個人版就不做）。"""
    from synox.notify import delivery
    from synox.schedule.actions import todo_list
    try:
        delivery.publish_todos(app, int(uid), todo_list(store_for(app).of(int(uid))))
    except Exception:
        import logging
        logging.exception("[REMIND] publishing todos failed")


def removed(app, uid: int, item: dict) -> None:
    """刪掉一筆之後：待辦就更新視窗的待辦；正在響／延後中的提醒就讓各管道收掉（按鈕拿掉、視窗卡片關掉）。"""
    from synox.schedule import reminder
    if is_todo(item):
        publish_todos(app, uid)
        return
    if not reminder.is_v2(item) or item.get("status") not in (reminder.RINGING, reminder.SNOOZED):
        return
    from synox.schedule.engine import app_resolve, ring_key
    try:
        rem = reminder.Reminder.from_dict(item)
        app_resolve(app, int(uid), ring_key(rem, int(uid)), note="🗑 這個提醒刪掉了", via="command")
    except Exception:
        import logging
        logging.exception("[REMIND] retracting a removed reminder failed")


def _source() -> str:
    try:
        kind = kit.caller().kind
    except Exception:
        return "command"
    return {"ai": "ai", "web": "web"}.get(kind, "command")


def _position(mine, rid: int) -> int:
    return next((i for i, it in enumerate(mine.items("remind"), 1) if it.get("id") == rid), 0)


def install_remind(app, group) -> None:
    store = store_for(app)

    def nowhere(api, chat_id, uid) -> bool:
        if planned_channels(app, uid):
            return False
        api.send_message(chat_id, "⚠️ 現在沒有任何地方可以叫你，所以先不排：到網頁「設定 → 電腦與備份 → 通知要送到哪裡」"
                                  "打開一個，再設一次。")
        return True

    def schedule(api, chat_id, user, text: str, at, repeat: str, now, *, source: str = "", extra: str = "") -> dict:
        from synox.schedule import receipt, reminder
        mine = store.of(user)
        item = mine.add_reminder(lambda rid: reminder.new_reminder(rid, user.tg_id, text, due=at, repeat=repeat,
                                                                   source=source or _source()))
        rec = make_receipt(app, user.tg_id, item, now)
        n = _position(mine, item["id"])
        if rec.kind == receipt.TODO:
            tail = f"（第 {n} 個；做完了打 /remind_done {n}）"
            publish_todos(app, user.tg_id)
        else:
            tail = f"（第 {n} 個；不要了打 /remind_rm {n}）"
        receipt.emit(api, chat_id, rec, extra=tail + (("\n" + extra) if extra else ""))
        return item

    def add(api, chat_id, user, values):
        from datetime import date, timedelta
        from synox.schedule import timeparse
        now = clock()
        text = values["text"].strip()
        raw, day = values["time"].strip(), values.get("date", "")
        repeat = REPEAT_WORDS.get(values.get("repeat", "").strip().lower(), "")
        if nowhere(api, chat_id, user.tg_id):
            return
        if not day and repeat != "once" and kit.hhmm(raw) is None:
            h, m = (int(x) for x in raw.split(":"))                 # HH:MM、沒給日期＝每天（以前的用法）
            at = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if at < now.replace(second=0, microsecond=0):
                at += timedelta(days=1)
            schedule(api, chat_id, user, text, at, "daily", now)
            return
        w = timeparse.parse(raw, now, day=date.fromisoformat(day) if day else None)
        if w.kind == timeparse.ASK:
            api.send_message(chat_id, "❓ " + w.question + "\n（說清楚一點再設一次，例如「明天 09:00」或「今天 21:00」。）")
            return
        if w.kind == timeparse.PAST:
            if w.at is None:
                api.send_message(chat_id, "❌ 那一天已經過了。")
                return
            api.send_message(chat_id, "❌ " + timeparse.past_question(w.at, now) +
                             f"\n要的話：/remind_add {timeparse.hm(w.at)} {text} date={w.at.strftime('%Y-%m-%d')}")
            return
        if w.kind != timeparse.AT or w.at is None:
            api.send_message(chat_id, "❌ 時間" + ("：有給日期時，時間要寫幾點幾分（例如 15:30）" if w.relative else TIME_HELP))
            return
        if repeat == "daily":
            if w.relative:
                api.send_message(chat_id, "❌ 每天的提醒要寫幾點幾分（例如 08:00），不能用「半小時後」。")
                return
            schedule(api, chat_id, user, text, w.at, "daily", now)
            return
        schedule(api, chat_id, user, text, w.at, "once", now, extra=f"（{w.note}）" if w.note else "")

    def todo(api, chat_id, user, values):
        schedule(api, chat_id, user, values["text"].strip(), None, "none", clock())

    def test(api, chat_id, user, values):
        from datetime import timedelta
        if nowhere(api, chat_id, user.tg_id):
            return
        now = clock()
        schedule(api, chat_id, user, "試響一下（/remind_test）", now + timedelta(minutes=1), "once", now, source="test",
                 extra="一分鐘後會響一次：上面列的每個地方都應該收到；沒收到的那一個就是沒接好。")

    def list_(api, chat_id, user, values):
        items = store.of(user).items("remind")
        if not items:
            api.send_message(chat_id, "⏰ 還沒有提醒。用 /remind_add 08:00 吃藥 加一個；/remind_todo 繳電話費 記一個待辦。")
            return
        lines = [REMIND_TITLE]
        lines += [f"{i}. {_when(it)}  {it['text']}" for i, it in enumerate(items, 1) if not is_todo(it)]
        todos = [(i, it) for i, it in enumerate(items, 1) if is_todo(it)]
        if todos:
            lines.append("📝 待辦（沒有時間，不會響）")
            lines += [f"{i}. {it['text']}" for i, it in todos]
        api.send_message(chat_id, "\n".join(lines))

    def rm(api, chat_id, user, values):
        gone = store.of(user).remove_nth("remind", int(values["n"]))
        if gone is None:
            api.send_message(chat_id, f"❌ 沒有第 {values['n']} 個（/remind_list 看編號）。")
            return
        removed(app, user.tg_id, gone)
        api.send_message(chat_id, f"🗑 刪掉提醒：{_when(gone)} {gone['text']}")

    def done(api, chat_id, user, values):
        from synox.notify import delivery
        from synox.schedule import reminder
        mine = store.of(user)
        items = mine.items("remind")
        n = int(values["n"])
        if not 0 < n <= len(items):
            api.send_message(chat_id, f"❌ 沒有第 {n} 個（/remind_list 看編號）。")
            return
        it = items[n - 1]
        if is_todo(it):
            mine.update_reminder(it["id"], lambda r: None)
            publish_todos(app, user.tg_id)
            api.send_message(chat_id, f"✅ 做完了：{it['text']}")
            return
        actions = app.extras.get(delivery.ACTIONS_EXTRA)
        if actions is not None and it.get("v") == 2 and it.get("status") in (reminder.RINGING, reminder.SNOOZED):
            out = actions.act(user.tg_id, it["id"], it.get("occurrence") or "", "done", via="command")
            api.send_message(chat_id, f"✅ 做完了：{it['text']}" if out.ok else ("❌ " + out.text))
            return
        api.send_message(chat_id, f"這個提醒還沒響。不要了的話：/remind_rm {n}")

    # 欄位說明也是給 AI 看的（以前寫在 remind 工具的 SKILL.md）
    kit.command(group, "add", add, "加一個提醒（系統；HH:MM 沒給日期＝每天，其他說法或 date= ＝只一次）", effect=WRITE,
                positional=2, fields=[
                    Field("time", "時間：HH:MM（24 小時制，下午 3 點＝15:00），或照使用者原話填「半小時後」「明天 9 點」"
                                  "「+2h」（系統會換算；聽不清楚會反問）", required=True, check=check_when),
                    Field("text", "提醒什麼", required=True),
                    Field("date", "只提醒一次的日期 YYYY-MM-DD（沒說年份就用今年；不填＝看時間：HH:MM 是每天）",
                          check=check_date),
                    Field("repeat", "daily（每天）或 once（只一次）；不填照上面的規則", check=check_repeat)])
    kit.command(group, "todo", todo, "記一個待辦（系統；沒有時間、不會響，/remind_list 看得到）", effect=WRITE,
                fields=[Field("text", "要做什麼", required=True)])
    kit.command(group, "done", done, "把一個待辦（或正在響的提醒）標成做完（先 /remind_list 看編號）", effect=WRITE,
                fields=[Field("n", "編號", required=True, check=kit.positive_int)])
    kit.command(group, "list", list_, "列出提醒與待辦（系統）")
    kit.command(group, "rm", rm, "刪掉一個提醒或待辦（系統；先 /remind_list 看編號）", effect=WRITE,
                fields=[Field("n", "編號", required=True, check=kit.positive_int)])
    kit.command(group, "test", test, "試響一下：一分鐘後響一次，看每個地方有沒有收到（系統）", effect=WRITE)


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
