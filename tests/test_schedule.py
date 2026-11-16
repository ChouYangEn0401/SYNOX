from datetime import datetime, timedelta

from conftest import OTHER_ID


def _runner(bot):
    return bot.app.extras["synox_schedule_runner"]


def test_remind_fires_once_per_day(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/remind_add 08:00 吃藥")
    assert "每天 08:00 提醒你：吃藥" in bot.last(owner)
    runner = _runner(bot)
    assert runner.tick(datetime(2026, 11, 9, 7, 59)) == []
    fired = runner.tick(datetime(2026, 11, 9, 8, 0, 10))
    assert len(fired) == 1 and bot.last(owner) == "⏰ 提醒：吃藥"
    assert runner.tick(datetime(2026, 11, 9, 8, 0, 40)) == []          # 同一分鐘第二次掃：今天跑過了
    assert len(runner.tick(datetime(2026, 11, 10, 8, 0))) == 1         # 隔天照跑
    bot.say(owner, "/remind_list")
    assert "1. 每天 08:00  吃藥" in bot.last(owner)


def test_one_shot_reminder_removed(make_bot, owner):
    bot = make_bot()
    day = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    bot.say(owner, f"/remind_add 15:30 繳費 date={day}")
    assert f"{day} 15:30（一次）" in bot.last(owner)
    runner = _runner(bot)
    when = datetime.strptime(day + " 15:30", "%Y-%m-%d %H:%M")
    assert runner.tick(when - timedelta(days=1)) == []                 # 前一天同一時間不跑
    assert len(runner.tick(when)) == 1
    bot.say(owner, "/remind_list")
    assert "還沒有提醒" in bot.last(owner)


def test_remind_validation_and_rm(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/remind_add 25:00 吃藥")
    assert "HH:MM" in bot.last(owner)
    bot.say(owner, "/remind_add 08:00")
    assert "用法：/remind_add" in bot.last(owner)
    bot.say(owner, "/remind_add 08:00 吃藥 date=2020-01-01")
    assert "已經過了" in bot.last(owner)
    bot.say(owner, "/remind_add 08:00 吃藥")
    bot.say(owner, "/remind_rm 1")
    assert "刪掉提醒" in bot.last(owner)


def test_schedule_command_runs_via_routine(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/money 50 早餐")
    bot.say(owner, "/schedule_add 21:00 /money_month")
    assert "每天 21:00 替你執行：/money_month" in bot.last(owner)
    _runner(bot).tick(datetime(2026, 11, 9, 21, 0))
    assert "共 50 元" in bot.last(owner)


def test_schedule_rejects_unknown_and_self(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/schedule_add 21:00 /nope")
    assert "看不懂要排的指令" in bot.last(owner)
    bot.say(owner, "/schedule_add 21:00 /schedule_add 22:00 /help")
    assert "看不懂要排的指令" in bot.last(owner)
    bot.say(owner, "/schedule_add 21:00 money")
    assert "看不懂要排的指令" in bot.last(owner)


def test_schedule_effect_follows_inner(make_bot):
    bot = make_bot()
    node = bot.app.registry.node("schedule.add")
    assert node.effect_of(["time=21:00", "command=/note_clear"]) == "danger"
    assert node.effect_of(["21:00", "/money_month"]) == "write"


def test_schedule_is_owner_only(make_bot, owner):
    bot = make_bot()
    bot.say(OTHER_ID, "/schedule_add 21:00 /help")
    assert "未知" in bot.last(OTHER_ID) or "不認得" in bot.last(OTHER_ID) or "/schedule_add" in bot.last(OTHER_ID)
    assert bot.app.extras["synox_schedule_store"].items() == []


def test_schedule_data_encrypted(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/remind_add 08:00 吃藥")
    raw = open(bot.app.extras["vault"].path("schedule"), "rb").read()
    assert "吃藥".encode() not in raw


# ── ⏰ 提醒（系統）：系統指令，不是 pack（QuestionToUser QL5，2026-11-12）────────────────

OLD_REMIND_PACK = {          # SYNOX_Libs 的 remind 0.1.1（現在在它的 legacy/remind/）：裝過它的人機器上還有這一份
    "name": "remind", "title": "⏰ 提醒", "summary": "每天幾點提醒你一件事，或指定哪一天提醒一次", "version": "0.1.1",
    "kind": "python", "group": "remind", "access": "member", "surfaces": ["dm"], "data": "user", "order": 30,
    "python": {"module": "pack"}, "requires": {"pip": [], "config": [], "env": {}, "synox": ">=0.2"}, "skill": "SKILL.md",
    "storage": "plain"}
OLD_REMIND_PY = ("from synox.schedule import commands\n\n\n"
                 "def install(app, pack):\n    commands.install_remind(app, pack.group)\n")


def test_remind_is_a_system_command_without_any_pack(make_bot, owner):
    bot = make_bot(pack_dirs=())
    group = bot.app.registry.node("remind")
    assert group is not None and group.title == "⏰ 提醒（系統）"
    assert "remind" not in {p.manifest.group for p in bot.app.extras.get("synox_packs", [])}
    bot.say(owner, "/remind_add 08:00 吃藥")
    assert "每天 08:00 提醒你：吃藥" in bot.last(owner)
    bot.say(owner, "/remind_list")
    assert bot.last(owner).startswith("⏰ 提醒（系統）") and "吃藥" in bot.last(owner)
    bot.say(owner, "/help all")
    assert any("提醒（系統）" in t for t in bot.texts(owner))


def test_remind_keeps_old_data(make_bot, owner, tmp_path):
    """舊資料：data/schedule.json.enc 是以前 remind 工具（和更早的內建版）寫的同一份，系統指令直接接上。"""
    from synox.schedule.store import ScheduleStore
    from synox.vault import Vault
    data = tmp_path / "data"
    ScheduleStore(str(data), Vault(b"k" * 32, str(data))).add("remind", "07:30", owner, text="以前設的提醒")
    bot = make_bot(pack_dirs=())
    bot.say(owner, "/remind_list")
    assert "1. 每天 07:30  以前設的提醒" in bot.last(owner)
    assert len(_runner(bot).tick(datetime(2026, 11, 13, 7, 30))) == 1 and bot.last(owner) == "⏰ 提醒：以前設的提醒"


def test_old_remind_pack_is_not_loaded_and_says_why(make_bot, owner, tmp_path):
    import json
    import os
    folder = tmp_path / "packs" / "remind"
    os.makedirs(folder)
    (folder / "pack.json").write_text(json.dumps(OLD_REMIND_PACK, ensure_ascii=False), encoding="utf-8")
    (folder / "pack.py").write_text(OLD_REMIND_PY, encoding="utf-8")
    (folder / "SKILL.md").write_text("---\nname: remind\ndescription: 提醒\n---\n", encoding="utf-8")
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "remind")
    assert item.status == "incompatible" and "系統指令" in item.detail and "移除" in item.detail
    assert bot.app.extras["synox_pack_report"].ok                    # 不算壞掉
    assert bot.app.registry.node("remind").title == "⏰ 提醒（系統）"
    bot.say(owner, "/remind_add 08:00 吃藥")                           # 沒有掛兩次、照常能用
    assert "每天 08:00 提醒你：吃藥" in bot.last(owner)


def test_remind_permissions_follow_the_old_pack(make_bot, owner):
    """權限沿用以前的 remind pack（access: member、surfaces: dm）：個人版只有擁有者、伺服器版成員以上、只在私訊。"""
    from isdtelekit.users.roles import BasicRoles
    personal = make_bot(pack_dirs=())
    personal.say(OTHER_ID, "/remind_add 08:00 偷設")
    assert personal.app.extras["synox_schedule_store"].items() == []
    group = personal.app.registry.node("remind")
    assert group.own.private_only and group.own.owner_only
    server = make_bot(raw={"mode": "server"}, pack_dirs=())
    server.make(OTHER_ID, BasicRoles.MEMBER)
    server.say(OTHER_ID, "/remind_add 08:00 成員吃藥")
    assert "成員吃藥" in server.last(OTHER_ID)
    assert server.app.registry.node("remind").own.private_only


# ── 提醒引擎（docs/adr/0028）：回執、時間用語、待辦、試響 ──────────────────────────

def test_remind_add_replies_with_a_receipt(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/remind_add 08:00 吃藥")
    text = bot.last(owner)
    assert text.startswith("⏰ 排好了：") and "提醒你「吃藥」（每天）。" in text
    assert "會送到：網頁。" in text and "不會響的情況：" in text and "SYNOX 沒開時" in text
    item = bot.app.extras["synox_schedule_store"].items("remind")[0]
    assert item["v"] == 2 and item["repeat"] == "daily" and item["source"] == "command"


def test_remind_add_understands_words_and_asks(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/remind_add 半小時後 喝水")
    assert "排好了" in bot.last(owner) and "（只一次）" in bot.last(owner)
    item = bot.app.extras["synox_schedule_store"].items("remind")[0]
    assert item["repeat"] == "once" and item["date"]
    bot.say(owner, "/remind_add 等等 喝水")
    assert bot.last(owner).startswith("❓") and "多久" in bot.last(owner)
    bot.say(owner, "/remind_add 明天 喝水")
    assert bot.last(owner).startswith("❓")
    assert len(bot.app.extras["synox_schedule_store"].items("remind")) == 1          # 問的不排


def test_remind_add_past_time_asks_about_tomorrow(make_bot, owner):
    now = datetime.now()
    if now.hour == 0 and now.minute == 0:
        import pytest
        pytest.skip("剛好午夜")
    bot = make_bot()
    bot.say(owner, f"/remind_add 00:00 倒垃圾 date={now.strftime('%Y-%m-%d')}")
    assert "已經過了，是要明天 00:00 嗎？" in bot.last(owner) and "date=" in bot.last(owner)
    bot.say(owner, "/remind_add 00:00 倒垃圾 repeat=once")
    assert "已經過了" in bot.last(owner)
    assert bot.app.extras["synox_schedule_store"].items() == []


def test_todo_list_and_done(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/remind_add 08:00 吃藥")
    bot.say(owner, "/remind_todo 繳電話費")
    assert bot.last(owner).startswith("📝 記下了待辦：「繳電話費」") and "/remind_done 2" in bot.last(owner)
    bot.say(owner, "/remind_list")
    listing = bot.last(owner)
    assert "1. 每天 08:00  吃藥" in listing and "📝 待辦" in listing and "2. 繳電話費" in listing
    assert _runner(bot).tick(datetime(2026, 11, 9, 8, 0, 10))[0]["text"] == "吃藥"   # 待辦不會響
    bot.say(owner, "/remind_done 1")
    assert bot.last(owner) == "✅ 做完了：吃藥"                           # 正在響的那一次：按掉
    item = bot.app.extras["synox_schedule_store"].items("remind")[0]
    assert item["status"] == "pending" and item["history"][-1]["status"] == "done"
    bot.say(owner, "/remind_done 1")
    assert "還沒響" in bot.last(owner)
    bot.say(owner, "/remind_done 2")
    assert "✅ 做完了：繳電話費" in bot.last(owner)
    bot.say(owner, "/remind_list")
    assert "繳電話費" not in bot.last(owner)


def test_remind_test_rings_in_a_minute(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/remind_test")
    assert "排好了" in bot.last(owner) and "一分鐘後會響一次" in bot.last(owner)
    store = bot.app.extras["synox_schedule_store"]
    item = store.raw_items()[0]
    assert item["source"] == "test" and item["repeat"] == "once"
    from synox.schedule.reminder import from_iso
    due = from_iso(item["due"]).replace(tzinfo=None)
    assert len(_runner(bot).tick(due - timedelta(seconds=20))) == 0
    assert len(_runner(bot).tick(due + timedelta(seconds=5))) == 1
    assert "試響一下" in bot.last(owner)


def test_no_channel_means_no_receipt(make_bot, owner, monkeypatch):
    bot = make_bot()
    from synox.schedule import commands
    monkeypatch.setattr(commands, "planned_channels", lambda app, uid: [])
    bot.say(owner, "/remind_add 08:00 吃藥")
    assert "沒有任何地方可以叫你" in bot.last(owner) and "排好了" not in bot.last(owner)
    assert bot.app.extras["synox_schedule_store"].items() == []
