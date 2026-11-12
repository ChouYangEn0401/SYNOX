"""網頁「新對話」：AI 的記憶每一段對話各自一份（以前整個人共用一份，開了新對話 AI 還記得前面）。"""
from tests.test_web import Client, ui_of


def _prompts(adapter):
    return ["\n".join(m.content for m in msgs) for msgs, _tools in adapter.calls]


def test_new_web_chat_does_not_remember_the_previous_chat(make_bot, owner):
    bot = make_bot(script=["好，記住了。", "我不知道你說的是什麼。"])
    c = Client(ui_of(bot))
    c.login(owner)
    first = c.post("/api/chats")[1]["id"]
    c.say(first, "我最喜歡的顏色是秘密橘")
    second = c.post("/api/chats")[1]["id"]
    c.say(second, "我最喜歡什麼顏色？")
    adapter = bot.app.extras["synox_agent"].adapter
    prompts = _prompts(adapter)
    assert "秘密橘" in prompts[0]
    assert "秘密橘" not in prompts[1]                      # 第二段對話的提示裡沒有第一段的內容
    loop = bot.app.extras["synox_agent"]
    keys = [k for k in loop.history if isinstance(k, tuple) and str(k[1]).startswith("thread:")]
    assert len(keys) == 2 and len({k[1] for k in keys}) == 2


def test_same_web_chat_keeps_its_own_memory(make_bot, owner):
    bot = make_bot(script=["好。", "你說過秘密橘。"])
    c = Client(ui_of(bot))
    c.login(owner)
    chat = c.post("/api/chats")[1]["id"]
    c.say(chat, "我最喜歡的顏色是秘密橘")
    c.say(chat, "我剛說了什麼？")
    assert "秘密橘" in _prompts(bot.app.extras["synox_agent"].adapter)[1]


def test_ai_reset_in_one_web_chat_only_clears_that_chat(make_bot, owner):
    bot = make_bot(script=["好。", "好。", "好。"])
    c = Client(ui_of(bot))
    c.login(owner)
    a, b = c.post("/api/chats")[1]["id"], c.post("/api/chats")[1]["id"]
    c.say(a, "甲的秘密")
    c.say(b, "乙的秘密")
    c.say(a, "/ai_reset")
    loop = bot.app.extras["synox_agent"]
    texts = {k: " ".join(m.content for m in v) for k, v in loop.history.items()}
    assert not any("甲的秘密" in t for t in texts.values()) and any("乙的秘密" in t for t in texts.values())


def test_latest_history_picks_the_most_recent_chat_of_that_person(make_bot, owner):
    bot = make_bot(script=["好。", "好。"])
    c = Client(ui_of(bot))
    c.login(owner)
    a, b = c.post("/api/chats")[1]["id"], c.post("/api/chats")[1]["id"]
    c.say(a, "較早的話")
    c.say(b, "較晚的話")
    loop = bot.app.extras["synox_agent"]
    assert any("較晚的話" in m.content for m in loop.latest_history(owner))

