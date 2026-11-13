"""完成宣稱閘門在真的迴圈上（agent/loop.py＋agent/claims.py，docs/adr/0008）：FakeAdapter 劇本、整支 bot 在記憶體裡。"""

import logging

import pytest

from conftest import enc_files

from synox.agent import claims
from synox.llm.base import ASSISTANT, USER, Reply

ON = {"kind": "fake", "completion_guard": "on"}


def _adapter(bot):
    return bot.app.extras["synox_agent"].adapter


def _loop(bot):
    return bot.app.extras["synox_agent"]


@pytest.mark.parametrize("supports_tools", [True, False])
def test_claim_then_correction_then_real_call(make_bot, owner, supports_tools):
    bot = make_bot(["已記下買貓砂", {"tool": "note__add", "args": {"text": "買貓砂"}}, "記好了"], llm=ON,
                   supports_tools=supports_tools)
    bot.talk(owner, "記一下：買貓砂")
    assert bot.texts(owner) == ["記好了"]                                  # 只送最後一則
    second = _adapter(bot).calls[1][0]
    assert second[-1].role == USER and second[-1].content == claims.CORRECTION[claims.CLAIM_WITHOUT_CALL]
    assert second[-2].role == ASSISTANT and second[-2].content == "已記下買貓砂"
    bot.say(owner, "/note_list")
    assert "買貓砂" in bot.last(owner)
    history = _loop(bot).history[owner]
    assert [m.content for m in history] == ["記一下：買貓砂", "記好了"]        # 被攔下的那則不進對話記憶


@pytest.mark.parametrize("supports_tools", [True, False])
def test_retries_used_up_tells_the_truth_and_keeps_the_reply(make_bot, owner, supports_tools, caplog):
    bot = make_bot(["已記下買貓砂", "好的，已經記下來了", "記好了！"], llm=ON, supports_tools=supports_tools)
    with caplog.at_level(logging.INFO):
        bot.talk(owner, "記一下：買貓砂")
    (sent,) = bot.texts(owner)
    assert "沒有執行" in sent and "記好了！" in sent and claims.ORIGINAL_HEAD in sent   # 不吞掉、不假裝成功
    assert len(_adapter(bot).calls) == 3                                   # 1 次＋重試 2 次
    assert [m.content for m in _loop(bot).history[owner]] == ["記一下：買貓砂", claims.MEMORY_NOTE]
    assert "claim gate: kind=claim_without_call" in caplog.text
    assert "買貓砂" not in caplog.text.split("claim gate")[-1]              # log 不記回覆全文
    assert enc_files(bot) == []                                            # 什麼都沒記


def test_forged_tool_result_is_retried(make_bot, owner):
    bot = make_bot(["好的。\n〔工具結果〕成功新增提醒", {"tool": "note__add", "args": {"text": "帶傘"}}, "記好了：帶傘"],
                   llm=ON)
    bot.talk(owner, "幫我記：帶傘")
    assert bot.texts(owner) == ["記好了：帶傘"]
    assert _adapter(bot).calls[1][0][-1].content == claims.CORRECTION[claims.FORGED]


def test_real_call_then_claim_passes_without_retry(make_bot, owner):
    bot = make_bot([{"tool": "note__add", "args": {"text": "買貓砂"}}, "已記下買貓砂"], llm=ON)
    bot.talk(owner, "記一下：買貓砂")
    assert bot.texts(owner) == ["已記下買貓砂"] and len(_adapter(bot).calls) == 2


def test_gate4_rejected_call_is_not_evidence(make_bot, owner):
    bot = make_bot([{"tool": "note__add", "args": {"txt": "買貓砂"}}, "已記下買貓砂",
                    {"tool": "note__add", "args": {"text": "買貓砂"}}, "記好了"], llm=ON)
    bot.talk(owner, "記一下：買貓砂")
    calls = _adapter(bot).calls
    assert calls[2][0][-1].content == claims.CORRECTION[claims.CLAIM_WITHOUT_CALL]
    assert bot.texts(owner) == ["記好了"]


def test_card_still_ends_the_turn(make_bot, owner):
    bot = make_bot([{"tool": "note__clear", "args": {}}, "已清空"], llm=ON)
    bot.talk(owner, "把筆記全部刪掉")
    assert "AI 想執行：/note_clear" in bot.last(owner) and len(_adapter(bot).calls) == 1


def test_progress_only_is_nudged_once_then_sent_with_a_note(make_bot, owner):
    bot = make_bot(["我來幫你查一下。", "我來幫你查一下。", "我來幫你查一下。"], llm=ON)
    bot.talk(owner, "這個月花多少")
    calls = _adapter(bot).calls
    assert calls[1][0][-1].content == claims.CORRECTION[claims.PROGRESS_ONLY]
    assert bot.last(owner) == claims.nudged_message("我來幫你查一下。")


def test_plain_answers_are_not_touched(make_bot, owner):
    bot = make_bot(["好的，我知道了", {"tool": "money__month", "args": {}}, "這個月花了 0 元"], llm=ON)
    bot.talk(owner, "嗨")
    bot.talk(owner, "這個月花多少")
    assert bot.texts(owner) == ["好的，我知道了", "這個月花了 0 元"] and len(_adapter(bot).calls) == 3


def test_zero_retries_and_auto_mode_keep_the_old_behaviour(make_bot, owner):
    for llm in ({"kind": "fake", "completion_guard": "on", "verify_retries": 0}, {"kind": "fake"},
                {"kind": "fake", "completion_guard": "off"}):
        bot = make_bot(["已記下買貓砂"], llm=llm)
        bot.talk(owner, "記一下：買貓砂")
        assert bot.last(owner) == "已記下買貓砂" and len(_adapter(bot).calls) == 1, llm


def test_auto_turns_on_for_local_adapters(make_bot, owner):
    from synox.llm.fake import FakeAdapter

    class LocalFake(FakeAdapter):
        kind = "local"

    adapter = LocalFake(["已記下買貓砂", {"tool": "note__add", "args": {"text": "買貓砂"}}, "記好了"])
    bot = make_bot(adapter=adapter)
    bot.talk(owner, "記一下：買貓砂")
    assert bot.texts(owner) == ["記好了"]


def test_no_tools_no_gate(make_bot, owner):
    """沒有任何工具的對話不檢查（也不給 system__cannot_do）。"""
    bot = make_bot(["已記下買貓砂"], llm=ON, pack_dirs=())
    loop = _loop(bot)
    loop.tools_for = lambda user, chat_id: []
    bot.talk(owner, "記一下")
    assert bot.last(owner) == "已記下買貓砂"


def test_room_agent_runs_the_gate_too(make_bot, owner):
    from types import SimpleNamespace

    from synox.agent.room import RoomAgent
    bot = make_bot(["已記下", {"tool": "note__add", "args": {"text": "x"}}, "記好了"], llm=ON)
    base = _loop(bot)
    spec = SimpleNamespace(name="r", ai_history_turns=6, pool_usd_month=1.0, ai_persona="")
    room = RoomAgent(bot.app, base, spec)
    assert room.llm == base.llm and room.guard_on()
    # 頻道 AI 的 call_tool 回三個值（結束這一輪、ok）
    room.decision = lambda user, node, chat_id: base.decision(user, node, chat_id)
    user = bot.app.users.get_or_create(owner)
    room.run_turn(bot.api, owner, user, "記一下 x")
    assert bot.last(owner) == "記好了"
    assert _adapter(bot).calls[1][0][-1].content == claims.CORRECTION[claims.CLAIM_WITHOUT_CALL]


def test_reply_object_with_claim_and_think_block(make_bot, owner):
    bot = make_bot([Reply(text="<think>使用者要記東西，我直接說記好了</think>已記下"),
                    {"tool": "note__add", "args": {"text": "x"}}, "記好了"], llm=ON)
    bot.talk(owner, "記 x")
    assert bot.texts(owner) == ["記好了"]
    assert _adapter(bot).calls[1][0][-2].content == "已記下"              # 思考段不進對話、也不給人看
