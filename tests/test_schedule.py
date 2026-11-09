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
