"""網頁「🫀 常駐助理」聊天：只給擁有者、沒有工具、記憶只在記憶體（重開就清空）、跟巡邏的保管箱記憶分開。"""
from synox import runtime
from synox.llm.fake import FakeAdapter
from synox.runtime.mother import MEMORY_KEY, NO_AI, MotherSession
from tests.test_web import GUEST_ID, Client, ui_of


def _owner_client(make_bot, owner, **kw):
    bot = make_bot(**kw)
    c = Client(ui_of(bot))
    c.login(owner)
    return bot, c


def _events(c, since=0):
    return c.get(f"/api/chat/mother/events?since={since}")[1]["messages"]


def test_owner_chats_with_the_resident_assistant(make_bot, owner):
    bot, c = _owner_client(make_bot, owner, script=["我是常駐助理，目前一切正常。"])
    chats = c.get("/api/chats")[1]["chats"]
    assert any(x["id"] == "mother" and x["title"] == "🫀 常駐助理" for x in chats)
    status, data = c.post("/api/chat/mother/send", {"text": "你好，你在做什麼？"})
    assert status == 200 and data["route"] == "mother"
    bot.app.tasks.wait(5)
    msgs = _events(c)
    assert [m["from"] for m in msgs] == ["me", "bot"] and "常駐助理" in msgs[1]["text"]
    mother = runtime.of(bot.app).mother
    assert len(mother._chat_memory) == 2                       # 記在記憶體
    assert bot.app.extras["synox_agent"].history == {} or not any(bot.app.extras["synox_agent"].history.values())  # 不碰對話助理的記憶


def test_members_cannot_see_or_send(make_bot, owner):
    bot, _ = _owner_client(make_bot, owner)
    m = Client(ui_of(bot))
    m.login(GUEST_ID)
    assert all(x["id"] != "mother" for x in m.get("/api/chats")[1]["chats"])
    assert m.post("/api/chat/mother/send", {"text": "hi"})[0] == 404
    assert m.get("/api/chat/mother/events?since=0")[0] == 404


def test_chat_memory_is_not_written_to_the_vault(make_bot, owner):
    bot, c = _owner_client(make_bot, owner, script=["好。"])
    vault = bot.app.extras["vault"]
    before = vault.load_json(MEMORY_KEY, [])
    c.post("/api/chat/mother/send", {"text": "記得我喜歡喝茶"})
    bot.app.tasks.wait(5)
    assert vault.load_json(MEMORY_KEY, []) == before            # 巡邏記憶沒被寫
    assert runtime.of(bot.app).mother.memory() == before


def test_without_ai_it_says_how_to_set_it_up(make_bot, owner):
    bot, c = _owner_client(make_bot, owner, llm={"kind": "none"})
    c.post("/api/chat/mother/send", {"text": "在嗎"})
    bot.app.tasks.wait(5)
    assert _events(c)[-1]["text"] == NO_AI


def test_new_mother_session_starts_with_empty_chat_memory(make_bot, owner):
    bot, c = _owner_client(make_bot, owner, script=["一", "二"])
    mother = runtime.of(bot.app).mother
    mother.chat("第一句")
    assert len(mother._chat_memory) == 2
    again = MotherSession(bot.app, FakeAdapter(["x"]), mother.soul, settings=mother.settings, vault=bot.app.extras["vault"])
    assert again._chat_memory == []                              # 重開 SYNOX 會重建它
    mother.chat_reset()
    assert mother._chat_memory == []


def test_chat_history_feeds_the_next_turn_but_has_no_tools(make_bot, owner):
    seen = []

    class Spy(FakeAdapter):
        def chat(self, messages, tools=()):
            seen.append((list(messages), tuple(tools)))
            return super().chat(messages, tools)

    bot, c = _owner_client(make_bot, owner, adapter=Spy(["答一", "答二"]))
    mother = runtime.of(bot.app).mother
    mother.adapter = bot.app.extras["synox_agent"].adapter
    mother.chat("問一")
    mother.chat("問二")
    msgs, tools = seen[-1]
    assert tools == () and [m.content for m in msgs[1:]] == ["問一", "答一", "問二"]
    assert "NOTIFY: <" not in msgs[0].content                       # 聊天版提示，不是巡邏的輸出格式
