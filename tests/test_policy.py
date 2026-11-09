# -*- coding: utf-8 -*-
"""PERM-1 policy 層：synox/policy.py 的 decide、config.json policy.roles 的能力上限、loader 依上限決定可見性、
ai_decision 走 decide。pack 都是 tmp 裡的小 python pack（只掛一個葉節點），不連網、不開埠、不跑子程序。"""
import json
import os

import pytest

from isdtelekit.core.registry import AI, TYPED, CommandRegistry
from isdtelekit.host.config import ConfigError
from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID, OWNER_ID

from synox import policy
from synox.agent import tools as tools_mod
from synox.agent.loop import ai_decision
from synox.config import SynoxConfig

ADMIN_ID, GUEST_ID = 666, 777

PACK_PY = r'''
from isdtelekit.core.registry import READ

def install(app, pack):
    def run(api, chat_id, user, args):
        app.extras.setdefault("ran", []).append((pack.name, user.tg_id))
        api.send_message(chat_id, "跑了 " + pack.name)
    pack.group.leaf("run", run, "跑一下", effect=READ, default=True)
'''


def _pack(base, name, caps, access="member"):
    folder = os.path.join(base, name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "title": name, "summary": "測試", "version": "0.1.0", "kind": "python",
                   "group": name, "access": access, "python": {"module": "pack"}, "capabilities": caps,
                   "skill": "SKILL.md"}, f)
    with open(os.path.join(folder, "pack.py"), "w", encoding="utf-8") as f:
        f.write(PACK_PY)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: x\ndescription: 測試\n---\n")


def _dirs(tmp_path):
    base = str(tmp_path / "packs")
    _pack(base, "plain", [])                                  # 什麼能力都沒宣告
    _pack(base, "net", ["network"])
    _pack(base, "sub", ["subprocess"])
    _pack(base, "anyfs", ["filesystem:any"])
    _pack(base, "pub", [], access="everyone")
    _pack(base, "pubnet", ["network"], access="everyone")
    return (base,)


def _server(make_bot, tmp_path, script=None, **raw):
    bot = make_bot(script, raw={"mode": "server", **raw}, pack_dirs=_dirs(tmp_path))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.make(ADMIN_ID, BasicRoles.ADMIN)
    bot.say(GUEST_ID, "/start")
    return bot


def _visible(bot, tg_id):
    reg = bot.app.registry
    user = bot.app.users.get_or_create(tg_id)
    names = ("plain", "net", "sub", "anyfs", "pub", "pubnet")
    return {g for g in names if reg.node(g) is not None and reg.visible(user, reg.node(g))}


def _ai_groups(bot, tg_id):
    user = bot.app.users.get_or_create(tg_id)
    specs = tools_mod.build(bot.app.registry, lambda n: ai_decision(bot.app, user, n))
    return {s.name.split("__")[0] for s in specs}


def _cfg(policy_raw):
    return SynoxConfig.from_dict({"owner_id": OWNER_ID, "policy": policy_raw}, require_token=False)


# ── config.json policy.roles（第 1 關式檢查） ──────────────────────────────


def test_default_ceilings_when_policy_not_written():
    roles = SynoxConfig.from_dict({"owner_id": OWNER_ID}, require_token=False).policy["roles"]
    assert roles["guest"] == frozenset()
    assert roles["member"] == {"network", "filesystem:own"}
    assert roles["admin"] == {"network", "filesystem:own", "subprocess"}


@pytest.mark.parametrize("cap", ["exec", "filesystem:any"])
@pytest.mark.parametrize("role", ["guest", "member", "admin"])
def test_owner_only_capabilities_cannot_be_given_to_any_role(cap, role):
    caps = ["network", "filesystem:own", "subprocess", cap]
    ladder = ("guest", "member", "admin")
    upward = ladder[ladder.index(role):]                    # 這一級以上都給（上限單調，免得被別的規則先擋）
    with pytest.raises(ConfigError, match="只有擁有者"):
        _cfg({"roles": {r: {"capabilities": caps} for r in upward}})


@pytest.mark.parametrize("bad, words", [
    ({"roles": {"owner": {"capabilities": []}}}, "owner"),
    ({"roles": {"vip": {"capabilities": []}}}, "不認得"),
    ({"roles": {"member": {"capabilities": ["root"]}}}, "不認得能力"),
    ({"roles": {"member": ["network"]}}, "capabilities"),
    ({"roles": ["member"]}, "policy.roles"),
    ("all", "policy"),
])
def test_bad_policy_shapes_are_rejected(bad, words):
    with pytest.raises(ConfigError, match=words):
        _cfg(bad)


def test_ceilings_must_widen_upward():
    with pytest.raises(ConfigError, match="一級比一級寬"):
        _cfg({"roles": {"admin": {"capabilities": ["subprocess"]}}})      # member 預設有 network，admin 卻沒有


def test_guest_wider_than_member_is_rejected_partial_override_keeps_defaults():
    with pytest.raises(ConfigError, match="一級比一級寬"):
        _cfg({"roles": {"guest": {"capabilities": ["subprocess"]}}})
    roles = _cfg({"roles": {"member": {"capabilities": ["network"]}}}).policy["roles"]
    assert roles["member"] == {"network"} and roles["admin"] == {"network", "filesystem:own", "subprocess"}


# ── loader：上限裝不下＝整組不可見 ─────────────────────────────────────────


def test_member_cannot_see_subprocess_pack_owner_can(make_bot, tmp_path):
    bot = _server(make_bot, tmp_path)
    assert _visible(bot, OTHER_ID) == {"plain", "net", "pub", "pubnet"}
    assert _visible(bot, OWNER_ID) == {"plain", "net", "sub", "anyfs", "pub", "pubnet"}
    bot.say(OTHER_ID, "/sub")                               # PERM-4：能力上限造成的隱藏也回未知指令（不洩漏存在）
    assert bot.last(OTHER_ID).startswith("未知指令")
    bot.say(OTHER_ID, "/anyfs")                             # 哪一級都裝不下＝owner_only：當作沒有這個指令
    assert bot.last(OTHER_ID).startswith("未知指令")
    assert bot.app.extras.get("ran", []) == []
    bot.say(OWNER_ID, "/sub")
    assert bot.last(OWNER_ID) == "跑了 sub"


def test_admin_sees_subprocess_but_not_owner_only_caps(make_bot, tmp_path):
    bot = _server(make_bot, tmp_path)
    assert _visible(bot, ADMIN_ID) == {"plain", "net", "sub", "pub", "pubnet"}
    assert bot.app.registry.node("anyfs").policy.owner_only
    bot.say(ADMIN_ID, "/sub")
    assert bot.last(ADMIN_ID) == "跑了 sub"


def test_guest_sees_only_everyone_packs_without_capabilities(make_bot, tmp_path):
    bot = _server(make_bot, tmp_path)
    assert _visible(bot, GUEST_ID) == {"pub"}               # pubnet 要 network：訪客上限是 []


def test_help_hides_packs_above_the_ceiling(make_bot, tmp_path):
    bot = _server(make_bot, tmp_path)
    bot.say(OTHER_ID, "/help")
    text = " ".join(bot.texts(OTHER_ID))
    assert "/sub" not in text and "/anyfs" not in text


def test_config_can_open_subprocess_to_members(make_bot, tmp_path):
    caps = ["network", "filesystem:own", "subprocess"]
    bot = _server(make_bot, tmp_path, policy={"roles": {"member": {"capabilities": caps}}})
    assert "sub" in _visible(bot, OTHER_ID) and "sub" in _ai_groups(bot, OTHER_ID)
    assert "anyfs" not in _visible(bot, OTHER_ID)


def test_personal_mode_stranger_cannot_see_everyone_pack_needing_network(make_bot, tmp_path):
    bot = make_bot(pack_dirs=_dirs(tmp_path))
    bot.say(GUEST_ID, "/start")
    assert _visible(bot, GUEST_ID) == {"pub"}


# ── AI：ai_decision＝decide(via=AI) ───────────────────────────────────────


def test_ai_tool_list_follows_the_ceiling(make_bot, tmp_path):
    bot = _server(make_bot, tmp_path)
    member = _ai_groups(bot, OTHER_ID)
    assert {"plain", "net", "pubnet"} <= member and not {"sub", "anyfs"} & member
    owner = _ai_groups(bot, OWNER_ID)
    assert {"sub", "anyfs"} <= owner
    assert _ai_groups(bot, GUEST_ID) == set()                # 訪客沒有 AI


def test_member_ai_calling_hidden_tool_is_not_executed(make_bot, tmp_path):
    bot = _server(make_bot, tmp_path, [{"tool": "sub__run", "args": {}}, "好"])
    bot.talk(OTHER_ID, "幫我跑 sub")
    assert bot.last(OTHER_ID) == "好"
    assert bot.app.extras.get("ran", []) == []
    tool_msgs = [m for m in bot.app.extras["synox_agent"].adapter.calls[-1][0] if m.role == "tool"]
    assert any("沒有 sub__run 這個工具" in m.content for m in tool_msgs)


def test_decide_checks_ceiling_even_if_group_policy_is_loose(make_bot, tmp_path):
    """縱深：群組的門檻沒擋到（例如 pack.json 被改寬）時，decide 對這個人的角色再算一次。"""
    bot = _server(make_bot, tmp_path)
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "net")
    pack.manifest.capabilities = ["exec"]
    node = bot.app.registry.node("net.run")
    member = bot.app.users.get(OTHER_ID)
    sdk = CommandRegistry.authorize                                               # SDK 單獨看會放行
    assert sdk(bot.app.registry, member, node, TYPED, OTHER_ID).allowed
    d = policy.decide(bot.app, member, node, via=TYPED, chat_id=OTHER_ID)
    assert not d.allowed and d.reason == "capability"
    assert bot.app.registry.authorize(member, node, TYPED, OTHER_ID).reason == "owner_only"   # SDK 看到的＝不存在
    assert ai_decision(bot.app, member, node) is None
    assert policy.decide(bot.app, bot.app.users.get(OWNER_ID), node, via=AI, chat_id=OWNER_ID).allowed


def test_bot_scope_is_applied_by_decide(make_bot, tmp_path):
    from synox.discord.bots import BotSpec
    bot = _server(make_bot, tmp_path)
    owner = bot.app.users.get(OWNER_ID)
    node = bot.app.registry.node("plain.run")
    assert policy.decide(bot.app, owner, node, via=TYPED, chat_id=OWNER_ID).allowed
    only_net = BotSpec(name="n", token="vault:x", packs=("net",))
    d = policy.decide(bot.app, owner, node, via=TYPED, chat_id=OWNER_ID, bot=only_net)
    assert not d.allowed and d.reason == "bot_pack"                               # 擁有者也一樣：bot 範圍不看人
    assert policy.decide(bot.app, owner, bot.app.registry.node("net.run"), via=TYPED, chat_id=OWNER_ID,
                         bot=only_net).allowed
    with policy.using_bot(only_net):                                              # 沒直接傳：用收訊的那個 bot
        assert policy.decide(bot.app, owner, node, via=TYPED, chat_id=OWNER_ID).reason == "bot_pack"
    assert policy.current_bot() is None


def test_group_policy_for_only_tightens():
    roles = BasicRoles
    cfg = SynoxConfig.from_dict({"owner_id": OWNER_ID}, require_token=False)
    assert policy.group_policy_for(cfg, roles, [], {}) == {"role": BasicRoles.GUEST}
    assert policy.group_policy_for(cfg, roles, ["network"], {}) == {"role": BasicRoles.MEMBER}
    assert policy.group_policy_for(cfg, roles, ["network"], {"role": BasicRoles.ADMIN}) == {"role": BasicRoles.ADMIN}
    assert policy.group_policy_for(cfg, roles, ["subprocess"], {"role": BasicRoles.MEMBER}) == {"role": BasicRoles.ADMIN}
    assert policy.group_policy_for(cfg, roles, ["exec"], {}) == {"owner_only": True}
    assert policy.group_policy_for(cfg, roles, ["network"], {"owner_only": True}) == {"owner_only": True}
