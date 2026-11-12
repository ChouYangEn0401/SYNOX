"""Telegram 擁有者配對（身分對應）：網頁產生六位數字 → Telegram 私訊 bot 傳它 → 對照表多一行，資料不動、不換擁有者 id。"""
import pytest

from synox import telegram_link as tl
from synox.discord.pairing import MAX_WRONG, WebPairing
from synox.identity import Identities
from tests.test_web import GUEST_ID, Client, ui_of

REAL = 8554348386                      # 擁有者真正的 Telegram 編號
STRANGER = 777000111


class RecApi:
    """會記下「送到哪個 chat_id」的假 BotAPI（有 BotAPI 那幾個以 chat_id 開頭的方法）。"""

    def __init__(self):
        self.sent = []
        self.cbs = []
        self.next = 100

    def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.next += 1
        self.sent.append((chat_id, text))
        return {"ok": True, "result": {"message_id": self.next}}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kw):
        self.sent.append((chat_id, text))
        return {"ok": True}

    def remove_buttons(self, chat_id, message_id):
        return {"ok": True}

    def delete_message(self, chat_id, message_id):
        return {"ok": True}

    def send_photo(self, chat_id, photo, caption=""):
        return {"ok": True}

    def send_document(self, chat_id, document, caption=""):
        return {"ok": True}

    def send_media_group(self, chat_id, photo_paths, caption="", kind="photo"):
        return {"ok": True}

    def typing(self, chat_id):
        return None

    def answer_callback_query(self, cq_id, text=None):
        self.cbs.append((cq_id, text))
        return {"ok": True}


def update(uid, text, chat=None):
    return {"update_id": 1, "message": {"message_id": 5, "date": 1_800_000_000, "text": text,
                                        "chat": {"id": chat if chat is not None else uid, "type": "private"},
                                        "from": {"id": uid, "username": "u"}}}


@pytest.fixture
def rig(make_bot, tmp_path):
    bot = make_bot(script=["AI 回答", "AI 回答二"])
    owner = bot.app.config.owner_id
    ids = Identities(str(tmp_path / "ident.json"))
    pairing = WebPairing()
    link = tl.TelegramLink(ids, owner, pairing)
    api = RecApi()
    link.patch_api(api)
    entry = tl.LinkedEntry(bot.app.telegram, link)
    return bot, link, entry, api, pairing, ids, owner


def test_unpaired_everyone_is_refused_once(rig):
    bot, link, entry, api, pairing, ids, owner = rig
    entry.dispatch(api, update(STRANGER, "你好"))
    entry.dispatch(api, update(STRANGER, "你好嗎"))                       # 同一個人只回一次
    assert [c for c, _ in api.sent] == [STRANGER] and api.sent[0][1] == tl.UNPAIRED
    entry.dispatch(api, update(REAL, "/help"))                           # 自己也一樣：還沒配對
    assert api.sent[-1] == (REAL, tl.UNPAIRED)


def test_pairing_code_binds_the_sender_as_owner_and_data_id_does_not_change(rig):
    bot, link, entry, api, pairing, ids, owner = rig
    code = pairing.start()["code"]
    entry.dispatch(api, update(REAL, " " + code + " "))
    assert ids.external(tl.TELEGRAM, owner) == str(REAL)                  # 對照表多一行
    assert pairing.pending() is None and pairing.last_paired["id"] == str(REAL)
    assert api.sent[-1][0] == REAL and "配對好了" in api.sent[-1][1]
    api.sent.clear()
    entry.dispatch(api, update(REAL, "你好，請回我"))                       # 配對後：是擁有者，走 AI（對話助理）
    bot.app.tasks.wait(5)
    assert api.sent and api.sent[-1][0] == REAL and api.sent[-1][1] == "AI 回答"   # 回覆翻回他的 Telegram 編號
    assert all(c == REAL for c, _ in api.sent)
    assert ids.lookup(tl.TELEGRAM, str(REAL)) == owner


def test_after_pairing_strangers_are_treated_as_before(rig):
    bot, link, entry, api, pairing, ids, owner = rig
    tl.bind_owner(ids, REAL, owner)
    entry.dispatch(api, update(STRANGER, "你好"))
    bot.app.tasks.wait(5)
    assert not any(t == tl.UNPAIRED for _c, t in api.sent)                # 不再是「還沒配對」
    assert all(c == STRANGER for c, _ in api.sent)                        # 陌生人照舊走 guest 那一套，回給他自己


def test_wrong_guesses_void_the_code(rig):
    bot, link, entry, api, pairing, ids, owner = rig
    code = pairing.start()["code"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(MAX_WRONG):
        entry.dispatch(api, update(STRANGER, wrong))
    assert pairing.pending() is None
    entry.dispatch(api, update(STRANGER, code))
    assert ids.external(tl.TELEGRAM, owner) is None


def test_code_from_a_group_or_without_a_pending_code_does_nothing(rig):
    bot, link, entry, api, pairing, ids, owner = rig
    entry.dispatch(api, update(REAL, "123456"))                           # 沒人要配對
    assert ids.external(tl.TELEGRAM, owner) is None
    code = pairing.start()["code"]
    entry.dispatch(api, update(REAL, code, chat=-100123))                 # 群組裡傳的不算
    assert ids.external(tl.TELEGRAM, owner) is None and pairing.pending() is not None


def test_button_press_by_the_owner_is_translated(rig):
    bot, link, entry, api, pairing, ids, owner = rig
    tl.bind_owner(ids, REAL, owner)
    seen = {}

    class Spy:
        def handle(self, api_, inbound, via):
            seen["inb"] = inbound
    cb = {"update_id": 2, "callback_query": {"id": "q1", "from": {"id": REAL, "username": "u"}, "data": "x:y",
                                              "message": {"message_id": 9, "chat": {"id": REAL}, "text": "t", "date": 1}}}
    link.handle(Spy(), api, tl.parse_update(cb), "typed")
    inb = seen["inb"]
    assert inb.user_id == owner and inb.chat_id == owner and inb.button.clicker_id == owner and inb.button.chat_id == owner


def test_patched_api_translates_only_the_owner_and_only_once(rig):
    bot, link, entry, api, pairing, ids, owner = rig
    link.patch_api(api)                                                   # 再包一次也不會翻兩次
    api.send_message(owner, "給擁有者")
    assert api.sent[-1][0] == owner                                       # 還沒配對：沒有對照，原樣
    tl.bind_owner(ids, REAL, owner)
    api.send_message(owner, "給擁有者")
    api.send_message(STRANGER, "給別人")
    assert [c for c, _ in api.sent[-2:]] == [REAL, STRANGER]


def test_rebinding_replaces_the_old_account(rig):
    bot, link, entry, api, pairing, ids, owner = rig
    tl.bind_owner(ids, REAL, owner)
    notes = tl.bind_owner(ids, 999111222, owner)
    assert ids.external(tl.TELEGRAM, owner) == "999111222" and ids.lookup(tl.TELEGRAM, str(REAL)) is None and notes


def test_install_only_for_a_local_owner_with_a_token(make_bot):
    bot = make_bot()                                                      # 擁有者是真的 Telegram id、沒有 token
    before = bot.app.telegram
    assert tl.install(bot.app, bot.app.config) is None and bot.app.telegram is before


# ── 網頁 ────────────────────────────────────────────────────────────

def test_web_pair_api(make_bot, owner, tmp_path):
    bot = make_bot()
    ui = ui_of(bot)
    c = Client(ui)
    c.login(owner)
    assert c.post("/api/settings/channels/telegram/pair", {"action": "start"})[0] == 409      # 沒有 link（擁有者本來就是 Telegram）
    ids = Identities(str(tmp_path / "data" / "identities.json"))
    link = tl.TelegramLink(ids, bot.app.config.owner_id, WebPairing())
    bot.app.extras["telegram_link"] = link
    bot.app.extras["telegram_pairing"] = link.pairing
    status, data = c.post("/api/settings/channels/telegram/pair", {"action": "start"})
    assert status == 200 and len(data["code"]) == 6
    assert c.get("/api/settings/channels/telegram/pair")[1]["pairing"]["code"] == data["code"]
    assert c.post("/api/settings/channels/telegram/pair", {"action": "manual", "user_id": "12ab"})[0] == 400
    status, data = c.post("/api/settings/channels/telegram/pair", {"action": "manual", "user_id": " 8554348386 "})
    assert status == 200 and data["paired_as"] == "8554348386"
    assert c.get("/api/settings/channels/telegram/pair")[1]["paired_as"] == "8554348386"
    m = Client(ui)
    m.login(GUEST_ID)
    assert m.post("/api/settings/channels/telegram/pair", {"action": "manual", "user_id": "8554348386"})[0] == 403
    assert m.get("/api/settings/channels/telegram/pair")[0] == 403


def test_build_wires_the_link_into_a_real_botapi_without_hiding_it_from_the_host(tmp_path):
    """真的 build()：擁有者是保留號段 ＋ 有 Telegram token → 換上 LinkedEntry、BotAPI 物件原地換方法（host 仍認得它是 BotAPI）。"""
    from isdtelekit.host.app import telegram_api
    from isdtelekit.telegram.bot_api import BotAPI
    from synox.app import build
    from synox.config import SynoxConfig
    from synox.vault import Vault
    data = tmp_path / "data"
    config = SynoxConfig.from_dict({"owner_id": 10 ** 15, "bot_token": "123456789:AAFakeTokenForTestsOnly_abcdefghijklmnop",
                                    "data_dir": str(data), "vault": {"mode": "file"}, "llm": {"kind": "none"}},
                                   require_token=False, root=str(tmp_path))
    home = BotAPI(config.bot_token)
    app = build(config, home=home, vault=Vault(b"k" * 32, str(data)), adapter=None)
    assert isinstance(app.telegram, tl.LinkedEntry) and app.extras["telegram_link"].owner_id == 10 ** 15
    assert telegram_api(app.home) is home                                 # host 還認得到 BotAPI → 輪詢照常啟動
    assert getattr(home.send_message, "_linked", False)
