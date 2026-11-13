"""🔐 解鎖指令（ADR 0025 §5.3）：/unlock、只打 /unlock 的下一則、單獨 6 位數不送 AI、網頁紀錄遮掉碼。"""

import pytest

from synox import guard
from synox.guard.testing import Clock, code_for, enroll

from test_web import Client

pytestmark = pytest.mark.usefixtures("no_sockets")


def setup(make_bot, owner, script=None):
    bot = make_bot(script or ["（AI 說話）"])
    g = guard.of(bot.app)
    clock = Clock()
    secret = enroll(g, owner, clock)
    return bot, g, clock, secret


def llm_calls(bot):
    return len(bot.app.extras["synox_agent"].adapter.calls)


def test_unlock_with_code(make_bot, owner):
    bot, g, clock, secret = setup(make_bot, owner)
    bot.say(owner, f"/unlock {code_for(secret, clock)}")
    assert "已解鎖 15 分鐘" in bot.last(owner)
    assert g.stepup.remaining(owner, guard.origin_mod.Origin("telegram", owner, surface="telegram")) > 0
    bot.say(owner, "/unlock_off")
    assert bot.last(owner) == "🔒 已鎖回去。"


def test_sudo_alias(make_bot, owner):
    bot, g, clock, secret = setup(make_bot, owner)
    bot.say(owner, f"/sudo {code_for(secret, clock)}")
    assert "已解鎖" in bot.last(owner)


def test_bare_unlock_takes_next_message_not_llm(make_bot, owner):
    bot, g, clock, secret = setup(make_bot, owner)
    bot.say(owner, "/unlock")
    assert "6 位數" in bot.last(owner)
    bot.talk(owner, code_for(secret, clock))
    assert "已解鎖" in bot.last(owner)
    assert llm_calls(bot) == 0


def test_six_digits_alone_are_not_sent_to_llm(make_bot, owner):
    bot, g, clock, secret = setup(make_bot, owner)
    code = code_for(secret, clock)
    bot.talk(owner, code[:3] + " " + code[3:])
    assert "看起來是驗證碼" in bot.last(owner) and llm_calls(bot) == 0
    button = [b for b in bot.buttons(owner) if b.startswith("unlock_code:")][0]
    assert code not in button
    bot.press(owner, button)
    assert "已解鎖" in bot.last(owner)


def test_six_digits_go_to_llm_when_not_enrolled(make_bot, owner):
    bot = make_bot(["好"])
    bot.talk(owner, "123456")
    assert llm_calls(bot) == 1


def test_wrong_code_and_not_enrolled(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/unlock 123456")
    assert "還沒設定手機驗證器" in bot.last(owner)
    bot2, g, clock, secret = setup(make_bot, owner)
    bad = "000000" if code_for(secret, clock) != "000000" else "111111"
    bot2.say(owner, f"/unlock {bad}")
    assert "驗證碼不對" in bot2.last(owner) and "/unlock <6 位數>" in bot2.last(owner)


def test_unlock_only_in_private(make_bot, owner):
    bot, g, clock, secret = setup(make_bot, owner)
    bot.say(owner, f"/unlock {code_for(secret, clock)}", chat_id=-100)
    assert "已解鎖" not in bot.last(-100) if bot.texts(-100) else True
    assert not g.stepup.unlocked(owner, guard.origin_mod.Origin("telegram", owner, surface="telegram"))


def test_web_chat_log_has_no_code(make_bot, owner):
    bot, g, clock, secret = setup(make_bot, owner)
    ui = bot.app.extras["synox_web"]
    c = Client(ui)
    c.login(owner)
    code = code_for(secret, clock)
    c.say("tools", f"/unlock {code}")
    clock.t += 30
    code2 = code_for(secret, clock)
    c.say("tools", code2)
    messages = c.events("tools")
    texts = " ".join(str(m) for m in messages)
    assert code not in texts and code2 not in texts
    assert "/unlock ······" in texts
    assert any("已解鎖" in str(m) for m in messages)
