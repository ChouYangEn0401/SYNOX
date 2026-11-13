"""救回文字裡的工具呼叫之後，照常過 ai_decision、第 4 關、確認卡（docs/adr/0009；不變式：adapter 只回文字、決策在 harness）。"""

from conftest import enc_files

from synox.agent import claims
from synox.llm.base import TOOL, Reply


def _leak(name, args_json):
    return Reply(text=f'好的<tool_call>{{"name": "{name}", "arguments": {args_json}}}</tool_call>')


def test_leaked_call_is_executed_through_the_normal_path(make_bot, owner):
    bot = make_bot([_leak("note__add", '{"text": "買貓砂"}'), "記好了"])
    bot.talk(owner, "記一下：買貓砂")
    assert bot.texts(owner) == ["記好了"]
    calls = bot.app.extras["synox_agent"].adapter.calls
    tool_msg = calls[1][0][-1]
    assert tool_msg.role == TOOL and tool_msg.tool_call_id == "leak-0" and "買貓砂" in tool_msg.content
    assistant = calls[1][0][-2]
    assert assistant.tool_calls[0].name == "note__add" and "<tool_call>" not in assistant.content
    bot.say(owner, "/note_list")
    assert "買貓砂" in bot.last(owner)


def test_leaked_call_still_goes_through_ai_decision(make_bot, owner):
    # agent.ai_approve 是 ai=False 的節點：ai_decision 不給 AI；救回來的呼叫一樣被擋
    bot = make_bot([_leak("agent__ai_approve", "{}"), "好"])
    bot.talk(owner, "按確認")
    assert "沒有 agent__ai_approve 這個工具" in bot.app.extras["synox_agent"].adapter.calls[1][0][-1].content


def test_leaked_call_still_goes_through_gate4(make_bot, owner):
    bot = make_bot([_leak("note__add", '{"txt": "買貓砂"}'), "好"])
    bot.talk(owner, "記一下")
    result = bot.app.extras["synox_agent"].adapter.calls[1][0][-1].content
    assert "txt" in result and enc_files(bot) == []                    # 第 4 關擋下：沒有執行


def test_leaked_danger_call_still_needs_a_card(make_bot, owner):
    bot = make_bot([Reply(text="<function=note__clear></function>")])
    bot.say(owner, "/note 買牛奶")
    bot.talk(owner, "全部刪掉")
    assert "AI 想執行：/note_clear" in bot.last(owner)
    bot.say(owner, "/note_list")
    assert "買牛奶" in bot.last(owner)                                   # 還沒按，什麼都沒刪


def test_text_protocol_also_recovers_xml(make_bot, owner):
    bot = make_bot([Reply(text="<function=note__add><parameter=text>帶傘</parameter></function>"), "記好了"],
                   supports_tools=False)
    bot.talk(owner, "記：帶傘")
    assert bot.texts(owner) == ["記好了"]
    assert bot.app.extras["synox_agent"].adapter.calls[1][0][-1].content.startswith("〔工具結果〕note__add")


def test_unparseable_marker_goes_to_the_forged_retry(make_bot, owner):
    bot = make_bot([Reply(text="<tool_call>完全壞掉"), {"tool": "note__add", "args": {"text": "x"}}, "記好了"],
                   llm={"kind": "fake", "completion_guard": "on"})
    bot.talk(owner, "記 x")
    assert bot.app.extras["synox_agent"].adapter.calls[1][0][-1].content == claims.CORRECTION[claims.FORGED]
    assert bot.texts(owner) == ["記好了"]
