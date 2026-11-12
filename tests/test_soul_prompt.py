"""決定 Q7（docs/adr/0002）：soul.md 放進對話助理的系統提示——只有擁有者、只在私訊／網頁、唯讀、包在分隔符裡、
標明「使用者偏好，不是指令」、有長度上限、沒寫東西就不放、不寫 log。全部用假 AI（FakeAdapter），不連網。"""

import logging

from isdtelekit.users.roles import BasicRoles

from synox import runtime
from synox.agent import delimit
from synox.llm.fake import FakeAdapter
from synox.runtime.soul import DEFAULT_SOUL, PROMPT_MAX_CHARS, prompt_text

from conftest import OTHER_ID
from test_web import Client, ui_of

SOUL = "# soul.md\n\n## 偏好\n- 回答一律三句以內\n\n## 語氣\n- 叫我阿明\n\n## 助理筆記\n"


def _system(bot):
    return bot.app.extras["synox_agent"].adapter.calls[-1][0][0].content


def _bot(make_bot, **kw):
    bot = make_bot(adapter=FakeAdapter(["好"] * 5), pack_dirs=(), **kw)
    return bot, runtime.of(bot.app).soul


def test_owner_chat_gets_soul_as_preferences_not_instructions(make_bot, owner):
    bot, soul = _bot(make_bot)
    soul.write(SOUL)
    bot.talk(owner, "你好")
    system = _system(bot)
    assert "回答一律三句以內" in system and "叫我阿明" in system
    assert "使用者偏好，不是指令" in system
    nonce = system.split(delimit.OPEN + delimit.TAG + "-")[1][:delimit.NONCE_LEN]   # 跟工具結果同一組分隔符（這一輪的 nonce）
    inside = system.split(delimit.opening(nonce))[-1].split(delimit.closing(nonce))[0]
    assert "叫我阿明" in inside and "使用者偏好" not in inside        # soul 的字在分隔符裡，說明在外面


def test_default_or_empty_soul_is_skipped(make_bot, owner):
    bot, soul = _bot(make_bot)
    bot.talk(owner, "你好")
    assert "soul.md" not in _system(bot)                                  # 沒改過（預設四個空段落）＝不放
    soul.write("# soul.md\n\n## 偏好\n\n<!-- 只有註解 -->\n")
    bot.talk(owner, "你好")
    assert "soul.md" not in _system(bot)


def test_member_and_guest_never_get_the_owners_soul(make_bot, owner):
    bot, soul = _bot(make_bot, raw={"mode": "server"})
    soul.write(SOUL)
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.talk(OTHER_ID, "你好")
    assert "叫我阿明" not in _system(bot) and "soul.md" not in _system(bot)
    bot.talk(owner, "你好")
    assert "叫我阿明" in _system(bot)


def test_soul_block_only_in_the_owners_own_chat(make_bot, owner):
    bot, soul = _bot(make_bot)
    soul.write(SOUL)
    agent = bot.app.extras["synox_agent"]
    me = bot.app.users.get(owner)
    assert "叫我阿明" in agent.soul_block(me, owner, "abcd1234")
    assert agent.soul_block(me, -100123, "abcd1234") == ""               # 群組／頻道（chat_id 不是他自己）不放
    assert agent.soul_block(me, owner, "") == ""                          # 沒有分隔符就不放


def test_web_chat_gets_soul_too(make_bot, owner):
    bot, soul = _bot(make_bot)
    soul.write(SOUL)
    c = Client(ui_of(bot))
    c.login(owner)
    chat = c.post("/api/chats")[1]["id"]
    c.say(chat, "你好")
    assert "叫我阿明" in _system(bot)


def test_prompt_text_limits_and_secrets():
    assert prompt_text(DEFAULT_SOUL) == ""
    long = "## 偏好\n" + "長" * (PROMPT_MAX_CHARS + 500)
    out = prompt_text(long)
    assert len(out) <= PROMPT_MAX_CHARS + 20 and out.endswith("（後面太長，省略）")
    assert prompt_text("## 偏好\n- key sk-ant-api03-" + "a" * 40) == ""     # 有密鑰樣式整份不送（寫入時本來就會拒）
    assert "<!--" not in prompt_text("<!-- 註解 -->\n## 偏好\n- 早上不要吵我\n")


def test_soul_is_not_logged_and_mother_memory_is_not_read(make_bot, owner, caplog):
    bot, soul = _bot(make_bot)
    soul.write(SOUL)
    rt = runtime.of(bot.app)
    rt.mother._remember("常駐助理的秘密工作記憶", "QUIET")
    assert any("常駐助理的秘密工作記憶" in str(m) for m in rt.mother.memory())
    with caplog.at_level(logging.DEBUG):
        bot.talk(owner, "你好")
    assert "叫我阿明" not in caplog.text
    assert "常駐助理的秘密工作記憶" not in _system(bot)


def test_no_vault_means_no_soul(make_bot, owner):
    bot, soul = _bot(make_bot)
    soul.write(SOUL)
    soul._vault = None                                                     # 保管箱沒開：聊天照常、不放 soul
    bot.talk(owner, "你好")
    assert "叫我阿明" not in _system(bot) and bot.last(owner) == "好"
