"""人話 → AI（FakeAdapter）→ 工具 → 核准卡 → 執行，整支 bot 跑在記憶體裡（spec §7.7）。"""

from conftest import OTHER_ID, enc_files

from synox.llm.base import TOOL, Reply


def test_money_via_ai(make_bot, owner):
    bot = make_bot([{"tool": "money__add", "args": {"amount": "80", "category": "咖啡"}}, "記好了：咖啡 80 元"])
    bot.talk(owner, "幫我記一筆 80 元咖啡")
    assert bot.last(owner) == "記好了：咖啡 80 元"
    adapter = bot.app.extras["synox_agent"].adapter
    messages, tools = adapter.calls[1]
    assert any(t.name == "money__add" for t in tools)
    tool_msg = [m for m in messages if m.role == TOOL][0]
    assert "記了：咖啡 80 元" in tool_msg.content          # 指令回的字被攔下來交給 AI，不是直接送給人
    assert not any("記了" in t for t in bot.texts(owner))
    assert enc_files(bot) == ["money.json.enc"]
    raw = open(bot.app.extras["vault"].path("money"), "rb").read()
    assert "咖啡".encode() not in raw


def test_demo_adapter_money(make_bot, owner):
    bot = make_bot(None)                                     # 示範模式（config llm.kind=fake）
    bot.talk(owner, "幫我記一筆 80 元咖啡")
    assert "記了：咖啡 80 元" in bot.last(owner)


def test_danger_needs_card_then_executes(make_bot, owner):
    bot = make_bot([{"tool": "note__clear", "args": {}}])
    bot.say(owner, "/note 買牛奶")
    bot.talk(owner, "把筆記全部刪掉")
    assert "AI 想執行：/note_clear" in bot.last(owner)
    go = [b for b in bot.buttons(owner) if b.startswith("agent_ok:go:")]
    assert go and any(b.startswith("agent_ok:no:") for b in bot.buttons(owner))
    bot.say(owner, "/note_list")
    assert "買牛奶" in bot.last(owner)                       # 還沒按，什麼都沒刪
    bot.press(owner, go[0])
    assert "全部筆記都刪掉了（1 筆）" in bot.last(owner)
    bot.say(owner, "/note_list")
    assert "還沒有筆記" in bot.last(owner)
    bot.press(owner, go[0])                                  # 同一張卡只能用一次
    assert "過期" in bot.last(owner)


def test_card_cancel(make_bot, owner):
    bot = make_bot([{"tool": "note__clear", "args": {}}])
    bot.say(owner, "/note 買牛奶")
    bot.talk(owner, "清空筆記")
    no = [b for b in bot.buttons(owner) if b.startswith("agent_ok:no:")][0]
    bot.press(owner, no)
    assert "不執行" in bot.last(owner)
    bot.say(owner, "/note_list")
    assert "買牛奶" in bot.last(owner)


def test_card_button_forged_by_stranger(make_bot, owner):
    bot = make_bot([{"tool": "note__clear", "args": {}}])
    bot.talk(owner, "清空筆記")
    go = [b for b in bot.buttons(owner) if b.startswith("agent_ok:go:")][0]
    bot.press(OTHER_ID, go)                                   # 別人偽造：agent 群組只給擁有者，看起來像不存在
    assert bot.answers()[-1] == bot.app.dispatcher.texts.button_unknown
    bot.press(owner, go)                                      # 本人的卡還在
    assert "全部筆記都刪掉了" in bot.last(owner)


def test_stranger_free_text_does_not_reach_ai(make_bot, owner):
    bot = make_bot(["不該被叫到"])
    bot.talk(OTHER_ID, "幫我記一筆 80 元咖啡")
    assert bot.app.extras["synox_agent"].adapter.calls == []
    bot.say(OTHER_ID, "/note 偷記")                          # owner-only 的 pack：別人打了跟不存在一樣
    assert "偷記" not in " ".join(bot.texts(OTHER_ID))


def test_textproto_mode(make_bot, owner):
    bot = make_bot([{"tool": "money__add", "args": {"amount": "45", "category": "早餐"}}, "記好了"],
                   supports_tools=False)
    bot.talk(owner, "早餐 45")
    adapter = bot.app.extras["synox_agent"].adapter
    first_messages, first_tools = adapter.calls[0]
    assert first_tools == [] and '{"tool":' in first_messages[0].content      # 工具說明寫在系統提示裡
    assert adapter.calls[1][0][-1].content.startswith("〔工具結果〕money__add")
    assert bot.last(owner) == "記好了"


def test_unknown_tool_and_missing_args_fed_back(make_bot, owner):
    bot = make_bot([{"tool": "sudo__on", "args": {}}, {"tool": "money__add", "args": {"amount": "5"}}, "好"])
    bot.talk(owner, "隨便")
    calls = bot.app.extras["synox_agent"].adapter.calls
    assert "沒有 sudo__on 這個工具" in calls[1][0][-1].content
    assert "缺必填參數：category" in calls[2][0][-1].content
    assert enc_files(bot) == []


def test_max_steps(make_bot, owner):
    bot = make_bot([{"tool": "money__month", "args": {}}] * 10, raw={"llm": {"kind": "fake", "max_steps": 3}})
    bot.talk(owner, "一直查")
    assert "做了 3 步" in bot.last(owner)


def test_schedule_wrapping_danger_needs_card(make_bot, owner):
    bot = make_bot([{"tool": "schedule__add", "args": {"time": "21:00", "command": "/note_clear"}}])
    bot.talk(owner, "每天晚上九點清空筆記")
    assert "AI 想執行：/schedule_add" in bot.last(owner)


def test_skill_read_and_prompt(make_bot, owner):
    bot = make_bot([{"tool": "skill_read", "args": {"name": "money"}}, "懂了"])
    bot.talk(owner, "記帳怎麼用")
    calls = bot.app.extras["synox_agent"].adapter.calls
    system = calls[0][0][0].content
    assert "- money：" in system and "- notes：" in system and "notion" not in system   # 只登記的 connector 不進提示
    assert "amount" in calls[1][0][-1].content and "記帳" in calls[1][0][-1].content


def test_history_and_usage(make_bot, owner):
    bot = make_bot(["第一句", "第二句"])
    bot.talk(owner, "嗨")
    bot.talk(owner, "/ai 還記得嗎")
    second = bot.app.extras["synox_agent"].adapter.calls[1][0]
    assert [m.content for m in second[1:3]] == ["嗨", "第一句"]
    bot.say(owner, "/ai_usage")
    assert "今天：2 次" in bot.last(owner)
    bot.say(owner, "/ai_reset")
    assert "2 輪" in bot.last(owner)


def test_no_llm(make_bot, owner):
    bot = make_bot(llm={"kind": "none"})
    bot.say(owner, "/ai 你好")
    assert "還沒設定 AI" in bot.last(owner)
    bot.say(owner, "你好")
    assert bot.last(owner) == bot.app.dispatcher.texts.not_understood


def test_adapter_error_is_reported(make_bot, owner):
    from synox.llm.base import LLMError

    def boom(messages, tools):
        raise LLMError("金鑰不對（401）。")

    bot = make_bot([boom])
    bot.talk(owner, "嗨")
    assert "AI 沒有回應：金鑰不對" in bot.last(owner)


def test_reply_object_step(make_bot, owner):
    bot = make_bot([Reply(text="直接回")])
    bot.talk(owner, "嗨")
    assert bot.last(owner) == "直接回"
