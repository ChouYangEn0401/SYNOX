"""對話紀錄：先封存（側欄消失、可還原），到「已封存」才能徹底刪除。"""
from tests.test_web import GUEST_ID, Client, ui_of


def _ids(c, path="/api/chats"):
    return [x["id"] for x in c.get(path)[1]["chats"]]


def test_archive_hides_restore_brings_back_and_delete_needs_archive_first(make_bot, owner):
    bot = make_bot(script=["好。"])
    c = Client(ui_of(bot))
    c.login(owner)
    a = c.post("/api/chats")[1]["id"]
    b = c.post("/api/chats")[1]["id"]
    c.say(a, "留著的話")
    assert c.post(f"/api/chat/{a}/delete")[0] == 409                      # 沒封存不能直接刪
    status, data = c.post(f"/api/chat/{a}/archive")
    assert status == 200 and data["archived_count"] == 1
    assert a not in _ids(c) and b in _ids(c)                              # 側欄看不到
    assert _ids(c, "/api/chats/archived") == [a]
    assert c.get("/api/chats")[1]["archived_count"] == 1
    assert c.post(f"/api/chat/{a}/archive")[0] == 409                     # 已經封存
    assert c.post(f"/api/chat/{a}/send", {"text": "還能說嗎"})[0] == 409     # 封存的不能再傳
    assert c.events(a)                                                    # 但內容還在
    assert c.post(f"/api/chat/{a}/restore")[0] == 200
    assert a in _ids(c) and _ids(c, "/api/chats/archived") == []
    assert c.post(f"/api/chat/{a}/restore")[0] == 409                     # 沒封存就不能還原


def test_delete_forever_removes_the_chat_and_the_ai_memory_of_it(make_bot, owner):
    bot = make_bot(script=["好。"])
    c = Client(ui_of(bot))
    c.login(owner)
    a = c.post("/api/chats")[1]["id"]
    c.say(a, "會被刪掉的秘密")
    loop = bot.app.extras["synox_agent"]
    assert any("會被刪掉的秘密" in m.content for h in loop.history.values() for m in h)
    c.post(f"/api/chat/{a}/archive")
    status, data = c.post(f"/api/chat/{a}/delete")
    assert status == 200 and data["archived_count"] == 0
    assert _ids(c, "/api/chats/archived") == [] and a not in _ids(c)
    assert c.get(f"/api/chat/{a}/events?since=0")[0] == 404               # 真的沒了
    assert not any("會被刪掉的秘密" in m.content for h in loop.history.values() for m in h)   # AI 也忘了這段


def test_pinned_chats_cannot_be_archived_and_others_cannot_touch_my_chats(make_bot, owner):
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    for pinned in ("tools", "mother"):
        assert c.post(f"/api/chat/{pinned}/archive")[0] == 404
        assert c.post(f"/api/chat/{pinned}/delete")[0] == 404
    mine = c.post("/api/chats")[1]["id"]
    m = Client(ui_of(bot))
    m.login(GUEST_ID)
    assert m.post(f"/api/chat/{mine}/archive")[0] == 404                  # 別人的對話看不到、動不了
    assert m.get("/api/chats/archived")[1]["chats"] == []
    c.post(f"/api/chat/{mine}/archive")
    assert m.post(f"/api/chat/{mine}/delete")[0] == 404


def test_archived_chats_are_not_squeezed_out_by_the_chat_limit(tmp_path):
    from synox.web.chats import MAX_CHATS, ChatStore
    store = ChatStore(str(tmp_path))
    keep = store.new_chat(1, "要留著的")
    store.archive(1, keep["id"])
    for _ in range(MAX_CHATS + 5):
        store.new_chat(1)
    assert [c["id"] for c in store.list_chats(1, archived=True)] == [keep["id"]]      # 封存的沒被擠掉
    assert len(store.list_chats(1)) == MAX_CHATS
