"""門禁核心：來源（ADR 0025 §2）。每個入口都設對；沒設＝unknown。"""

import threading
from datetime import datetime

import pytest

from isdtelekit.core.registry import DANGER, READ

from synox.guard import origin
from synox.guard.testing import as_origin

from test_web import Client

pytestmark = pytest.mark.usefixtures("no_sockets")


def probe(bot, name="probe", effect=READ):
    """掛一個指令，記下 handler 裡看到的來源。"""
    seen = []

    def fn(api, chat_id, user, args):
        seen.append(origin.current())
        api.send_message(chat_id, "probe ok")
    bot.app.registry.ensure_group(name, "探測").leaf("go", fn, "探測", effect=effect)
    return seen


def test_default_is_unknown_and_using_nests():
    assert origin.current().kind == "unknown" and not origin.current().human
    with as_origin("telegram", 1):
        assert origin.current().kind == "telegram" and origin.current().caller == "human"
        with as_origin("ai", 1):
            assert origin.current().caller == "ai"
        assert origin.current().kind == "telegram"
    assert origin.current().kind == "unknown"


def test_other_thread_does_not_see_it_but_carry_does():
    seen = {}
    with as_origin("web", 2):
        t = threading.Thread(target=lambda: seen.setdefault("plain", origin.current().kind))
        t.start(); t.join()
        carried = origin.carry(lambda: origin.current().kind)
    t = threading.Thread(target=lambda: seen.setdefault("carried", carried()))
    t.start(); t.join()
    assert seen == {"plain": "unknown", "carried": "web"}


def test_bad_kind_becomes_unknown():
    assert origin.Origin("root").kind == "unknown"
    assert origin.from_inbound("http").kind == "unknown"
    assert origin.from_inbound("telegram", "routine").kind == "schedule"
    assert origin.Origin("remote").caller == "remote"


def test_telegram_message_is_telegram(make_bot, owner):
    bot = make_bot()
    seen = probe(bot)
    bot.say(owner, "/probe_go")
    assert seen[-1].kind == "telegram" and seen[-1].user_id == owner


def test_outer_origin_is_kept(make_bot, owner):
    bot = make_bot()
    seen = probe(bot)
    with as_origin("console", owner):
        bot.say(owner, "/probe_go")
    assert seen[-1].kind == "console"


def test_web_send_and_press_are_web_and_logins_differ(make_bot, owner):
    bot = make_bot()
    seen = probe(bot)
    ui = bot.app.extras["synox_web"]
    a, b = Client(ui), Client(ui)
    a.login(owner)
    b.login(owner)
    a.say("tools", "/probe_go")
    b.say("tools", "/probe_go")
    assert [o.kind for o in seen[-2:]] == ["web", "web"]
    assert seen[-1].surface.startswith("web:") and seen[-1].surface != seen[-2].surface


def test_ai_tool_call_is_ai_on_behalf_of_telegram(make_bot, owner):
    bot = make_bot([{"tool": "probe__go", "args": {}}, "好了"])
    seen = probe(bot)
    bot.talk(owner, "跑一下 probe")
    assert seen and seen[-1].kind == "ai" and seen[-1].on_behalf.kind == "telegram"


def test_schedule_fire_is_schedule(make_bot, owner):
    bot = make_bot()
    seen = probe(bot)
    bot.say(owner, "/schedule_add 21:00 /probe_go")
    bot.app.extras["synox_schedule_runner"].tick(datetime(2026, 11, 9, 21, 0, 5))
    assert seen and seen[-1].kind == "schedule"


def test_card_press_is_the_human_not_ai(make_bot, owner):
    bot = make_bot([{"tool": "probe__go", "args": {}}])
    seen = probe(bot, effect=DANGER)
    bot.talk(owner, "跑一下 probe")
    go = [x for x in bot.buttons(owner) if x.startswith("agent_ok:go:")]
    assert go and not seen
    bot.press(owner, go[0])
    assert seen[-1].kind == "telegram"
