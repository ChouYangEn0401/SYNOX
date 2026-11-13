"""每輪工具數上限（agent/toolpick.py，docs/adr/0014）：2-gram 挑工具、永遠保留做不到的出口與系統指令、
limit=0 原樣、auto 只對本地／弱來源；迴圈裡清單外但有權的工具照常執行、下一步退回全集。"""

import pytest

from synox.agent import auto, toolpick
from synox.agent import tools as tools_mod
from synox.agent.skills import SKILL_READ
from synox.config import SynoxConfig
from synox.llm.base import ToolSpec
from synox.llm.fake import FakeAdapter
from isdtelekit.host.config import ConfigError


def _spec(name, desc, params=()):
    return ToolSpec(name, desc, {"type": "object", "properties": {p: {"type": "string", "description": d}
                                                                  for p, d in params}})


def _twenty():
    tools = [_spec(f"misc{i}__run", f"第 {i} 號雜項工具：查詢天氣、匯率、行程") for i in range(17)]
    tools.insert(14, _spec("note__add", "新增一則筆記。情境：使用者說「記一下…」「幫我記…」時。", [("text", "內容")]))
    tools.append(_spec("remind__add", "新增提醒", [("time", "時間")]))
    tools.append(_spec(SKILL_READ, "讀技能"))
    tools.append(tools_mod.cannot_do_spec())
    return tools


def test_pick_keeps_the_relevant_tool_and_the_system_tools():
    tools = _twenty()
    assert len(tools) == 21
    got = toolpick.pick(tools, "記一下買貓砂", 12)
    names = [t.name for t in got]
    assert "note__add" in names
    assert {tools_mod.CANNOT_DO, SKILL_READ, "remind__add"} <= set(names)        # 系統工具永遠在
    assert len([n for n in names if not toolpick.kept(n)]) == 12
    assert names == [t.name for t in tools if t.name in names]                  # 照原本的順序


def test_limit_zero_or_small_list_returns_everything_in_order():
    tools = _twenty()
    assert toolpick.pick(tools, "記一下", 0) == tools
    assert toolpick.pick(tools, "記一下", 18) == tools                   # 一般工具 18 個 ≤ 18
    assert toolpick.pick(tools[:2] + tools[-3:], "x", 2) == tools[:2] + tools[-3:]


def test_extra_keep_prefixes():
    tools = _twenty() + [_spec("sched__list", "列出排程")]
    got = {t.name for t in toolpick.pick(tools, "記一下", 3, keep=("sched__",))}
    assert "sched__list" in got and tools_mod.CANNOT_DO in got


def test_grams_and_score():
    assert toolpick.grams("記一下") == {"記一", "一下"}
    assert toolpick.grams("Note_Add!") >= {"no", "ot", "te", "ad", "dd"}
    assert toolpick.score(_spec("note__add", "記一筆"), toolpick.grams("記一下")) == 1


def test_parse_and_limit_for():
    assert toolpick.parse_max_tools(None) == "auto" and toolpick.parse_max_tools("auto") == "auto"
    assert toolpick.parse_max_tools(0) == 0 and toolpick.parse_max_tools("12") == 12
    for bad in (-1, 201, True, "x", 1.5):
        with pytest.raises(ValueError):
            toolpick.parse_max_tools(bad)

    class _A:
        def __init__(self, kind, base_url=""):
            self.kind, self.base_url = kind, base_url

    assert toolpick.limit_for({}, _A("local")) == toolpick.DEFAULT_LOCAL_LIMIT
    assert toolpick.limit_for({}, _A("openai_compat", "http://192.168.1.5:8000/v1")) == 12
    assert toolpick.limit_for({}, _A("openai")) == 0 and toolpick.limit_for({}, _A("claude_code")) == 0
    assert toolpick.limit_for({"max_tools": 0}, _A("local")) == 0
    assert toolpick.limit_for({"max_tools": 5}, _A("anthropic")) == 5
    assert auto.weak_source(_A("local")) and not auto.weak_source(_A("gemini"))


def test_config_validates_max_tools():
    cfg = SynoxConfig.from_dict({"owner_id": 1, "llm": {"kind": "fake", "max_tools": "8"}}, require_token=False)
    assert cfg.llm["max_tools"] == 8
    with pytest.raises(ConfigError):
        SynoxConfig.from_dict({"owner_id": 1, "llm": {"kind": "fake", "max_tools": "many"}}, require_token=False)


# ── 迴圈 ─────────────────────────────────────────────────────────────

class _Local(FakeAdapter):
    kind = "local"                     # 當成本地來源（auto 的判斷只看 kind）


def _names(tools):
    return [t.name for t in tools]


def test_cloud_default_offers_every_tool(make_bot, owner):
    bot = make_bot(["好"])
    bot.talk(owner, "嗨")
    loop = bot.app.extras["synox_agent"]
    user = bot.app.users.get_or_create(owner)
    offered = _names(loop.adapter.calls[0][1])
    full = _names(loop.tools_for(user, owner))
    assert set(full) <= set(offered) and tools_mod.CANNOT_DO in offered


def test_outside_tool_still_runs_and_next_step_gets_everything(make_bot, owner):
    probe = make_bot(["好"])
    loop = probe.app.extras["synox_agent"]
    full = _names(loop.tools_for(probe.app.users.get_or_create(owner), owner))
    assert len([n for n in full if not toolpick.kept(n)]) > 1
    bot = make_bot(adapter=FakeAdapter([]), llm={"kind": "fake", "max_tools": 1})
    loop = bot.app.extras["synox_agent"]
    adapter = loop.adapter
    first = loop.pick_tools(loop.tools_for(bot.app.users.get_or_create(owner), owner), "嗨")
    shown = set(_names(first))
    assert "note__list" in full and "note__list" not in shown     # 「嗨」跟哪個都不像：照原本的順序留第一個
    outside = "note__list"
    adapter.script = [{"tool": outside, "args": {}}, "好了"]
    bot.talk(owner, "嗨")
    first_offer, second_offer = _names(adapter.calls[0][1]), _names(adapter.calls[1][1])
    assert outside not in first_offer and len([n for n in first_offer if not toolpick.kept(n)]) == 1
    assert tools_mod.CANNOT_DO in first_offer
    assert outside in second_offer and len(second_offer) > len(first_offer)        # 退回全集
    tool_msgs = [m for m in adapter.calls[1][0] if m.role == "tool"]
    assert tool_msgs and "還沒有筆記" in tool_msgs[0].content          # 真的執行了，不是「沒有這個工具」


def test_auto_limit_applies_to_local_sources_only(make_bot, owner):
    bot = make_bot(adapter=_Local(["好"]), llm={"kind": "fake", "max_tools": "auto"})
    loop = bot.app.extras["synox_agent"]
    many = [_spec(f"x{i}__y", "雜項") for i in range(20)] + [tools_mod.cannot_do_spec()]
    picked = loop.pick_tools(many, "嗨")
    assert len(picked) == toolpick.DEFAULT_LOCAL_LIMIT + 1 and picked[-1].name == tools_mod.CANNOT_DO
    cloud = make_bot(["好"]).app.extras["synox_agent"]
    assert cloud.pick_tools(many, "嗨") == many
