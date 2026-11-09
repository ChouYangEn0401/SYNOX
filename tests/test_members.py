"""伺服器版的成員：AI（工具只有他能用的、每月額度）、每人自己的提醒與排程。個人版照舊。"""

import json
import os
from datetime import datetime

from isdtelekit.users.roles import BasicRoles

from synox.agent import tools as tools_mod
from synox.agent.budget import EXHAUSTED
from synox.agent.loop import ai_decision

from conftest import OTHER_ID

GUEST_ID = 777


def _tool_groups(bot, user):
    registry = bot.app.registry
    specs = tools_mod.build(registry, lambda n: ai_decision(registry, user, n))
    return {s.name.split("__")[0] for s in specs}


def test_guest_gets_no_tools_member_only_member_or_everyone_packs(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.say(GUEST_ID, "/start")
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    registry = bot.app.registry
    guest, member = bot.app.users.get(GUEST_ID), bot.app.users.get(OTHER_ID)
    assert _tool_groups(bot, guest) == set()
    groups = _tool_groups(bot, member)
    packs = {p.manifest.group: p.manifest.access for p in bot.app.extras["synox_packs"]}
    pack_groups = {g for g in groups if g in packs}
    assert pack_groups and all(packs[g] in ("member", "everyone") for g in pack_groups)
    assert {"note", "money", "remind"} <= pack_groups
    assert "gcal" not in groups and "user" not in groups and "limit" not in groups
    owner_groups = _tool_groups(bot, bot.app.users.get(owner))
    assert "user" in owner_groups or "limit" in owner_groups        # 擁有者照舊拿得到管理工具


def test_member_free_text_goes_to_ai_guest_does_not(make_bot, owner):
    bot = make_bot([{"tool": "note__add", "args": {"text": "成員的事"}}, "記好了"], raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.talk(GUEST_ID, "幫我記一下")
    assert "AI" not in bot.last(GUEST_ID) and bot.app.extras["synox_agent"].adapter.calls == []
    bot.talk(OTHER_ID, "幫我記一下成員的事")
    assert bot.last(OTHER_ID) == "記好了"
    bot.say(OTHER_ID, "/note_list")
    assert "成員的事" in bot.last(OTHER_ID)
    usage = os.path.join(bot.app.config.data_dir, "users", str(OTHER_ID), "llm_usage.json")
    assert os.path.isfile(usage)
    with open(usage, encoding="utf-8") as f:
        assert json.load(f)["total"]["calls"] == 2


def test_member_budget_exhausted(make_bot, owner):
    bot = make_bot(["一", "二", "三"], raw={"mode": "server", "ai_member_monthly_usd": 0.0001,
                                          "llm": {"kind": "fake", "price_in": 10, "price_out": 10}})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.talk(OTHER_ID, "嗨")                                    # 用掉 15 token × 10 美元／百萬 = 0.00015
    assert bot.last(OTHER_ID) == "一"
    bot.talk(OTHER_ID, "再一次")
    assert bot.last(OTHER_ID) == EXHAUSTED
    bot.talk(owner, "擁有者沒有額度")
    assert bot.last(owner) == "二"
    bot.say(owner, f"/ai_budget {OTHER_ID} 5")
    assert "US$5.00" in bot.last(owner)
    bot.talk(OTHER_ID, "加了之後")
    assert bot.last(OTHER_ID) == "三"
    bot.say(OTHER_ID, "/ai_budget 1 100")                       # 成員不能替自己加
    assert "US$" not in bot.last(OTHER_ID)


def test_personal_mode_strangers_still_have_no_ai(make_bot, owner):
    bot = make_bot(["不該被叫"])
    bot.talk(GUEST_ID, "嗨")
    assert bot.app.extras["synox_agent"].adapter.calls == []
    assert bot.app.registry.node("agent").policy.owner_only


def test_server_reminders_are_per_user_and_go_to_that_user(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.say(OTHER_ID, "/remind_add 08:00 成員吃藥")
    bot.say(owner, "/remind_add 09:00 擁有者開會")
    data = bot.app.config.data_dir
    assert os.path.isfile(os.path.join(data, "users", str(OTHER_ID), "schedule.json.enc"))
    assert not os.path.exists(os.path.join(data, "schedule.json.enc"))
    bot.say(owner, "/remind_list")
    assert "擁有者開會" in bot.last(owner) and "成員吃藥" not in bot.last(owner)
    runner = bot.app.extras["synox_schedule_runner"]
    fired = runner.tick(datetime(2026, 11, 9, 8, 0))
    assert len(fired) == 1 and bot.last(OTHER_ID) == "⏰ 提醒：成員吃藥"
    assert "成員吃藥" not in " ".join(bot.texts(owner))
    runner.tick(datetime(2026, 11, 9, 9, 0))
    assert bot.last(owner) == "⏰ 提醒：擁有者開會"


def test_member_schedule_authorizes_as_member(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.say(OTHER_ID, "/schedule_add 21:00 /user_list")         # 管理員指令：成員排不進去
    assert "不能排進排程" in bot.last(OTHER_ID) or "不能" in bot.last(OTHER_ID)
    bot.say(OTHER_ID, "/schedule_add 21:00 /money_month")
    assert "替你執行：/money_month" in bot.last(OTHER_ID)
    bot.say(OTHER_ID, "/money 50 早餐")
    runner = bot.app.extras["synox_schedule_runner"]
    runner.tick(datetime.now().replace(hour=21, minute=0))
    assert "共 50 元" in bot.last(OTHER_ID)
    bot.say(owner, "/schedule_list")
    assert "還沒有排程" in bot.last(owner)                         # 擁有者看不到成員的排程


def test_personal_mode_schedule_file_unchanged(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/remind_add 08:00 吃藥")
    assert os.path.isfile(os.path.join(bot.app.config.data_dir, "schedule.json.enc"))
    assert not os.path.exists(os.path.join(bot.app.config.data_dir, "users"))
