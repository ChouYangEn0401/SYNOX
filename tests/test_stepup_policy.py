"""驗證器接上 policy.decide（計畫 K3）：表格測試＋AI 與確認卡＋G5（伺服器版給管理員）。"""

import itertools

import pytest

from isdtelekit.core.registry import AI, BUTTON, DANGER, READ, ROUTINE, SCHEDULE, TYPED, WRITE
from isdtelekit.users.roles import BasicRoles

from synox import guard, policy
from synox.guard.origin import Origin
from synox.guard.testing import Clock, as_origin, code_for, enroll

from conftest import OTHER_ID

pytestmark = pytest.mark.usefixtures("no_sockets")

KINDS = ("read", "write", "danger", "elevated")
VIAS = (TYPED, BUTTON, SCHEDULE, ROUTINE, AI)
STATES = ("unset", "off", "on")


def nodes(bot):
    g = bot.app.registry.ensure_group("probe", "探測")
    made = {}
    for kind in KINDS:
        effect = {"read": READ, "write": WRITE}.get(kind, DANGER)
        made[kind] = g.leaf(kind, lambda api, chat_id, user, args: api.send_message(chat_id, "done"), kind,
                            effect=effect, elevated=(kind == "elevated"))
    return made


def expected(state, kind, via, unlocked):
    elevated = kind == "elevated"
    if via == ROUTINE:
        return True, ""
    need = elevated or (kind == "danger" and state == "on")
    if not need or (via == AI and not elevated):
        return True, ""
    if state == "unset":
        return False, "stepup_unset"
    return (True, "") if unlocked else (False, "stepup")


@pytest.mark.parametrize("state", STATES)
def test_decide_table(make_bot, owner, state):
    bot = make_bot()
    made = nodes(bot)
    g = guard.of(bot.app)
    clock = Clock()
    secret = enroll(g, owner, clock, protect=(state == "on")) if state != "unset" else None
    tg = Origin("telegram", owner, surface="telegram")
    user = bot.app.users.get_or_create(owner)
    for unlocked in (False, True):
        if unlocked:
            if secret is None:
                continue
            clock.t += 30
            assert g.stepup.unlock(owner, code_for(secret, clock), origin=tg).ok
        for kind, via in itertools.product(KINDS, VIAS):
            with as_origin("telegram", owner):
                d = policy.decide(bot.app, user, made[kind], via=via, chat_id=owner)
            want = expected(state, kind, via, unlocked)
            assert (d.allowed, d.reason if not d.allowed else "") == want, (state, kind, via, unlocked)


def test_unset_danger_is_exactly_as_before(make_bot, owner):
    bot = make_bot()
    made = nodes(bot)
    user = bot.app.users.get_or_create(owner)
    with as_origin("telegram", owner):
        now = {(k, v): policy.decide(bot.app, user, made[k], via=v, chat_id=owner) for k in KINDS for v in VIAS}
        bot.app.extras.pop(guard.EXTRA)                    # 沒有門禁核心＝這一包之前
        before = {(k, v): policy.decide(bot.app, user, made[k], via=v, chat_id=owner) for k in KINDS for v in VIAS}
    assert {k: (d.allowed, d.reason) for k, d in now.items()} == {k: (d.allowed, d.reason) for k, d in before.items()}


def test_typed_danger_blocked_then_unlock_then_continue(make_bot, owner):
    bot = make_bot()
    nodes(bot)
    g = guard.of(bot.app)
    clock = Clock()
    secret = enroll(g, owner, clock, protect=True)
    bot.say(owner, "/probe_danger")
    assert "要先解鎖" in bot.last(owner)
    bot.say(owner, f"/unlock {code_for(secret, clock)}")
    assert "已解鎖 15 分鐘" in bot.texts(owner)[-2]
    cont = [b for b in bot.buttons(owner) if b.startswith("sudo_go:")]
    assert cont and "繼續" in bot.last(owner)
    bot.press(owner, cont[0])
    assert bot.last(owner) == "done"
    bot.say(owner, "/probe_danger")
    assert bot.last(owner) == "done"                       # 15 分鐘內不再問


def test_ai_danger_card_needs_unlock_at_press(make_bot, owner):
    bot = make_bot([{"tool": "note__clear", "args": {}}])
    g = guard.of(bot.app)
    clock = Clock()
    secret = enroll(g, owner, clock, protect=True)
    bot.say(owner, "/note 買牛奶")
    bot.talk(owner, "把筆記全部刪掉")
    assert "AI 想執行：/note_clear" in bot.last(owner)          # 開關開著仍然出卡（沒有被擋在前面）
    go = [b for b in bot.buttons(owner) if b.startswith("agent_ok:go:")][0]
    bot.press(owner, go)
    assert "要先解鎖" in bot.last(owner) and "這張卡還有效" in bot.last(owner)
    bot.say(owner, "/note_list")
    assert "買牛奶" in bot.last(owner)                         # 沒執行
    bot.say(owner, f"/unlock {code_for(secret, clock)}")
    bot.press(owner, go)
    assert "全部筆記都刪掉了" in bot.last(owner)


def test_ai_has_no_unlock_tool_and_unlock_cannot_be_scheduled(make_bot, owner):
    bot = make_bot([{"tool": "unlock__on", "args": {"code": "123456"}}, "好"])
    bot.talk(owner, "幫我解鎖")
    adapter = bot.app.extras["synox_agent"].adapter
    assert not any(t.name.startswith("unlock") for t in adapter.calls[0][1])
    bot.say(owner, "/schedule_add 03:00 /unlock 123456")
    assert "03:00" not in bot.last(owner) or "不能" in bot.last(owner)
    bot.say(owner, "/schedule_list")
    assert "/unlock" not in bot.last(owner)


def test_g5_server_owner_can_give_admin_without_authenticator(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    assert bot.app.stepup is None
    bot.say(owner, f"/user_role {OTHER_ID} admin")
    assert bot.app.users.get(OTHER_ID).role == BasicRoles.ADMIN
    bot.say(owner, f"/user_role {OTHER_ID} member")
    g = guard.of(bot.app)
    clock = Clock()
    secret = enroll(g, owner, clock)
    assert bot.app.stepup is not None
    bot.say(owner, f"/user_role {OTHER_ID} admin")
    assert bot.app.users.get(OTHER_ID).role == BasicRoles.MEMBER
    assert "/unlock" in bot.last(owner) and "isdtelekit" not in bot.last(owner)
    bot.say(owner, f"/unlock {code_for(secret, clock)}")
    bot.say(owner, f"/user_role {OTHER_ID} admin")
    assert bot.app.users.get(OTHER_ID).role == BasicRoles.ADMIN
