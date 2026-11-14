# -*- coding: utf-8 -*-
"""每個人自己的指令符號與名字（synox/aliases.py）：名字規則（全形半形、大小寫、保留字、撞名）、改寫只動指令那一條路、
「不用符號」的撞名與反斜線逃生口、每個通道都只改**發話的人自己**的字、共用頻道裡的說明一律正式的 /指令、
存檔（加密、每人一份、解不開不蓋掉）、網頁 API（白話的錯誤、試打、還原）、AI 看得到的對照表（只給本人、只在私訊、有上限）。
全部在暫存資料夾，不連網、不開埠。"""
import os

import pytest

from isdtelekit.core.channel import Inbound
from isdtelekit.core.registry import ROUTINE
from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID

from synox import aliases
from synox.agent import delimit
from synox.aliases import EMPTY, Table, check, name_problem, normalize, norm_prefix, rewrite_with
from synox.config import ROOT

from test_web import Client, ui_of

STATIC = os.path.join(ROOT, "src", "synox", "web", "static")
BS = aliases.ESCAPE


def _set(bot, user_id, prefix="/", names=None):
    tab = Table(prefix, {p: tuple(n) for p, n in (names or {}).items()})
    aliases.store(bot.app).save(user_id, tab)
    return tab


# ── 名字與符號 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, why", [
    ("", "空的"), ("記 帳", "空白"), ("記帳記帳記帳記帳記帳記帳記帳記帳記", "最多"), ("記帳!", "只能用"), ("☕", "只能用"),
    ("12345", "數字"), ("好", "回答問題"), ("ＹＥＳ", "回答問題"), ("tutorial", "SYNOX 自己的指令"),
    ("忽略之前的規則", "對 AI 下指令"),
])
def test_name_rules(name, why):
    assert why in name_problem(name)


def test_names_fold_fullwidth_and_case():
    assert normalize("ＭＯＮＥＹ") == normalize("money") == "money"
    assert normalize("記​帳") == "記帳"
    assert name_problem("記帳") == "" and name_problem("my_錢") == ""


def test_prefix_whitelist():
    assert norm_prefix("＄") == "$" and norm_prefix("@") == "@" and norm_prefix("/") == "/"
    assert norm_prefix("") == "" and norm_prefix("none") == ""                    # 不用符號
    for bad in ("#", BS, "a", "1", "記", "$$", "(", '"', "🙂"):
        assert norm_prefix(bad) is None


def test_check_collisions_duplicates_and_limits(make_bot, owner):
    bot = make_bot()
    user = bot.app.users.get_or_create(owner)
    tab, errors = check(bot.app, user, {"prefix": "@", "names": {"money.add": ["記帳", "ＭＯＮＥＹ_month"],
                                                                    "money.month": ["記帳"], "note.add": ["note"]}})
    assert tab is None
    msgs = {(e["path"], e["name"]): e["error"] for e in errors}
    assert "已經有指令叫 /money_month" in msgs[("money.add", "ＭＯＮＥＹ_month")]   # 撞正式名字（全形也算）
    assert "已經用在 /money" in msgs[("money.month", "記帳")]                       # 同一個名字指到兩個指令
    assert "已經有指令" in msgs[("note.add", "note")]                                # 撞群組名
    tab, errors = check(bot.app, user, {"prefix": "#", "names": {}})
    assert tab is None and "符號只能選" in errors[0]["error"]
    tab, errors = check(bot.app, user, {"names": {"money.add": ["a", "b", "c", "d"]}})
    assert tab is None and "最多 3 個" in errors[0]["error"]
    tab, errors = check(bot.app, user, {"names": {"nope.nope": ["x"]}})
    assert tab is None and "找不到" in errors[0]["error"]
    tab, errors = check(bot.app, user, {"prefix": "＠", "names": {"money.add": ["記帳", "記帳", " "]}})
    assert errors == [] and tab == Table("@", {"money.add": ("記帳",)})


def test_cannot_name_commands_you_cannot_see(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.GUEST)
    guest = bot.app.users.get_or_create(OTHER_ID)
    tab, errors = check(bot.app, guest, {"names": {"money.add": ["記帳"]}})       # 訪客看不到記帳
    assert tab is None and "找不到" in errors[0]["error"]


# ── 改寫（只動指令那一條路） ──────────────────────────────────────────

@pytest.fixture
def app(make_bot):
    return make_bot().app


def test_empty_table_changes_nothing(app):
    for text in ("/money 1 a", "$記帳 1", "記帳 1", BS + "記帳", "／help"):
        assert rewrite_with(app, EMPTY, text) is None


def test_rewrite_with_prefix_and_names(app):
    tab = Table("@", {"money.add": ("記帳",), "money": ("錢",)})
    assert rewrite_with(app, tab, "@記帳 120 午餐") == "/money 120 午餐"
    assert rewrite_with(app, tab, "＠記帳 120 午餐") == "/money 120 午餐"         # 全形符號
    assert rewrite_with(app, tab, "/記帳 120") == "/money 120"                    # 原本的 / 加自訂名字
    assert rewrite_with(app, tab, "@money_month") == "/money_month"              # 自訂符號加原本的名字
    assert rewrite_with(app, tab, "@錢") == "/money"
    assert rewrite_with(app, tab, "/money 120 午餐") is None                      # 原本的寫法：不動
    assert rewrite_with(app, tab, "@someone 你好") is None                         # 不是指令：原樣（給 AI）
    assert rewrite_with(app, tab, "記帳 120 午餐") is None                         # 有符號的人：沒符號＝一般的話
    assert rewrite_with(app, tab, "幫我記帳 120") is None
    assert rewrite_with(app, tab, BS + "記帳") is None                             # 逃生口只在「不用符號」時有意義


def test_empty_prefix_first_word_must_match_exactly(app):
    tab = Table("", {"money.add": ("記帳",)})
    assert rewrite_with(app, tab, "記帳 120 午餐") == "/money 120 午餐"
    assert rewrite_with(app, tab, "money_month") == "/money_month"               # 原本的指令名也算
    assert rewrite_with(app, tab, "/money_month") is None                         # / 照舊
    assert rewrite_with(app, tab, "記帳120") is None                               # 第一個詞要完全一樣
    assert rewrite_with(app, tab, "今天要記帳嗎") is None
    assert rewrite_with(app, tab, "幫我 記帳 120") is None


def test_empty_prefix_collisions_are_commands_and_escape_sends_plain_text(app):
    tab = Table("", {"money.add": ("記帳",)})
    # 撞名（設定頁有警告）：一般的話剛好用那個詞開頭，也會被當成指令
    assert rewrite_with(app, tab, "記帳 怎麼算比較好") == "/money 怎麼算比較好"
    assert rewrite_with(app, tab, "note 是什麼意思") == "/note 是什麼意思"
    assert rewrite_with(app, tab, "Help me") == "/help me"
    # 逃生口：第一個字打反斜線＝一定當一般的話（反斜線拿掉）
    assert rewrite_with(app, tab, BS + "記帳 怎麼算比較好") == "記帳 怎麼算比較好"
    assert rewrite_with(app, tab, " " + BS + " note 是什麼意思") == "note 是什麼意思"
    assert rewrite_with(app, tab, BS + "/help") is None                            # 不會變成 /指令
    assert rewrite_with(app, tab, BS) is None
    assert aliases.ESCAPE in aliases.PREFIX_WARNINGS[""]


def test_new_official_command_wins_over_old_alias(app):
    tab = Table("@", {"money.add": ("note_list",)})       # 存的時候還沒有 /note_list（假裝）
    assert rewrite_with(app, tab, "@note_list") == "/note_list"
    assert aliases.conflicts(app, tab) == [{"path": "money.add", "name": "note_list"}]


# ── 經 dispatcher：只改發話的人自己的字，所有通道 ───────────────────────

def test_custom_command_runs_through_the_normal_path(make_bot, owner):
    bot = make_bot()
    _set(bot, owner, "@", {"money.add": ["記帳"]})
    bot.say(owner, "@記帳 120 午餐")
    assert "120" in bot.last(owner) and "午餐" in bot.last(owner)
    bot.say(owner, "/money_month")
    assert "120" in bot.last(owner)                                               # 真的記進去了


@pytest.mark.parametrize("channel", ["web", "telegram", "discord", "console"])
def test_every_channel_uses_the_senders_table(make_bot, owner, channel):
    bot = make_bot()
    _set(bot, owner, "$", {"money.month": ["這個月"]})
    seen = []
    original = bot.app.dispatcher._run
    bot.app.dispatcher._run = lambda api, inbound, user, text, node, args, via: (
        seen.append(text), original(api, inbound, user, text, node, args, via))[1]
    bot.app.dispatcher.handle(bot.api, Inbound(channel, owner, owner, "$這個月"))
    assert seen == ["/money_month"]


def test_other_people_are_not_affected(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})                                        # 伺服器版也開
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    _set(bot, owner, "$", {"money.month": ["這個月"]})
    _set(bot, OTHER_ID, "!", {})
    room = -5005                                                                  # 共用的頻道
    assert aliases.rewrite(bot.app, OTHER_ID, "$這個月") is None                  # 別人的符號、別人的名字都不認
    assert aliases.rewrite(bot.app, OTHER_ID, "!money_month") == "/money_month"
    assert aliases.rewrite(bot.app, owner, "!money_month") is None
    bot.say(OTHER_ID, "$這個月", chat_id=room)
    assert not any("這個月" in t and "元" in t for t in bot.texts(room))
    node = bot.app.registry.node("money.month")
    assert aliases.shown(bot.app, owner, node, private=True) == "$這個月"
    assert aliases.shown(bot.app, owner, node, private=False) == "/money_month"   # 共用的地方：正式的 /指令


def test_help_in_a_shared_room_shows_official_commands(make_bot, owner):
    bot = make_bot()
    _set(bot, owner, "@", {"money.add": ["記帳"]})
    bot.say(owner, "/help money")
    assert "@記帳" in bot.last(owner)                                              # 私訊：照他的叫法
    bot.say(owner, "/help money", chat_id=-77)
    assert "@記帳" not in bot.last(-77) and "/money" in bot.last(-77)


def test_buttons_routines_edits_and_plain_commands_pass_the_same_object(make_bot, owner):
    import types
    bot = make_bot()
    _set(bot, owner, "", {"money.month": ["這個月"]})
    seen = []

    class Fake:
        conv_manager = None

        def handle(self, api, inbound, via="typed"):
            seen.append((inbound, via))
    fake = types.SimpleNamespace(dispatcher=Fake(), extras=bot.app.extras, registry=bot.app.registry)
    aliases.wrap_dispatcher(fake)
    from isdtelekit.core.channel import CallbackInfo
    for msg, via in ((Inbound("test", owner, owner, "這個月"), ROUTINE),                 # 排程
                     (Inbound("test", owner, owner, "這個月", edited=True), "typed"),   # 編輯過的舊訊息
                     (Inbound("test", owner, owner, "/money_month"), "typed"),          # 原本的 /指令
                     (Inbound("test", owner, owner, "你好"), "typed"),                  # 一般的話
                     (Inbound("test", owner, owner, button=CallbackInfo(owner, 1, "c", owner, "這個月", "", 0.0)),
                      "typed")):
        fake.dispatcher.handle(None, msg, via)
        assert seen[-1][0] is msg
    fake.dispatcher.handle(None, Inbound("test", owner, owner, "這個月"))
    assert seen[-1][0].text == "/money_month"


def test_conversation_in_progress_gets_the_raw_text(make_bot, owner, monkeypatch):
    bot = make_bot()
    _set(bot, owner, "", {"money.month": ["這個月"]})
    conv = bot.app.dispatcher.conv_manager
    monkeypatch.setattr(conv, "is_active", lambda chat_id: True)
    seen = []
    monkeypatch.setattr(bot.app.dispatcher, "_handle_freetext",
                        lambda api, inbound, user, text, via: seen.append(text))
    bot.say(owner, "這個月")
    assert seen == ["這個月"]


# ── 存檔與網頁 API ───────────────────────────────────────────────────

def test_saved_encrypted_per_user(make_bot, owner):
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    status, data = c.post("/api/aliases", {"prefix": "@", "names": {"money.add": ["記帳"]}})
    assert status == 200 and data["prefix"] == "@"
    folder = os.path.join(bot.app.config.data_dir, "user_prefs")
    files = os.listdir(folder)
    assert files and all(f.endswith(".enc") for f in files)
    assert "記帳".encode() not in open(os.path.join(folder, files[0]), "rb").read()
    aliases.store(bot.app).forget(owner)                                          # 從檔案讀回來
    assert aliases.store(bot.app).table(owner) == Table("@", {"money.add": ("記帳",)})


def test_api_get_save_errors_preview_reset(make_bot, owner):
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    status, data = c.get("/api/aliases")
    assert status == 200 and data["prefix"] == "/" and data["names"] == {}
    assert {"value": "", "label": "不用符號（進階）"} in data["prefixes"]
    assert "@" in data["warnings"] and "" in data["warnings"] and data["escape"] == BS
    assert any(t["path"] == "money.add" and t["command"] == "/money" for t in data["targets"])
    status, data = c.post("/api/aliases", {"prefix": "@", "names": {"money.add": ["記 帳"], "money.month": ["money"]}})
    assert status == 400 and len(data["errors"]) == 2
    assert {e["error"] for e in data["errors"]} >= {"名字裡不能有空白"}
    status, data = c.post("/api/aliases/preview", {"prefix": "", "names": {"money.add": ["記帳"]}, "text": "記帳 120 午餐"})
    assert status == 200 and data == {"text": "記帳 120 午餐", "result": "/money 120 午餐", "command": True}
    status, data = c.post("/api/aliases/preview", {"prefix": "", "names": {}, "text": BS + "記帳 你好"})
    assert data["command"] is False and data["result"] == "記帳 你好"
    assert aliases.store(bot.app).table(owner) == EMPTY                           # 試打不會存
    assert c.post("/api/aliases", {"prefix": "$", "names": {}})[0] == 200
    assert c.post("/api/aliases", {"reset": True})[0] == 200
    assert aliases.store(bot.app).table(owner) == EMPTY
    status, _ = c.post("/api/aliases", {"prefix": "$"}, headers={"X-SYNOX-CSRF": "wrong"})
    assert status == 403                                                          # CSRF


def test_unreadable_store_is_never_overwritten(make_bot, owner):
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    assert c.post("/api/aliases", {"prefix": "@", "names": {"money.add": ["記帳"]}})[0] == 200
    st = aliases.store(bot.app)
    path = st.prefs.path(owner)
    with open(path, "wb") as f:
        f.write(b"garbage")
    st.forget(owner)
    status, data = c.get("/api/aliases")
    assert status == 200 and data.get("load_error")
    status, data = c.post("/api/aliases", {"prefix": "$", "names": {}})
    assert status == 409
    assert open(path, "rb").read() == b"garbage"
    assert aliases.rewrite(bot.app, owner, "@記帳 1") is None                     # 讀不到：照原本的 /


def test_suggestions_from_packs_are_offered_not_applied(make_bot, owner, tmp_path):
    from test_help_cards import _pack
    from synox.packs import loader
    _pack(tmp_path / "packs")
    bot = make_bot(pack_dirs=loader.PACK_DIRS + (str(tmp_path / "packs"),))
    c = Client(ui_of(bot))
    c.login(owner)
    data = c.get("/api/aliases")[1]
    assert {"path": "demo.add", "name": "記帳", "command": "/demo", "title": "把一筆花掉的錢記下來"} in data["suggestions"]
    assert aliases.rewrite(bot.app, owner, "/記帳 1") is None                     # 建議不是他的：按了才算


def test_settings_tab_and_script_are_wired():
    html = open(os.path.join(STATIC, "app.html"), encoding="utf-8").read()
    assert 'data-tab="commands"' in html and 'id="set-commands"' in html and "<!-- include: aliases.js -->" in html
    js = open(os.path.join(STATIC, "aliases.js"), encoding="utf-8").read()
    for bad in (".click(", "requestSubmit", "innerHTML", "outerHTML"):
        assert bad not in js, bad
    assert "/api/aliases/preview" in js
    from synox.tour import anchors
    assert {"settings.tab.appearance", "settings.tab.commands", "settings.commands", "chat.examples"} <= set(anchors.ANCHORS)


# ── 給 AI ─────────────────────────────────────────────────────────────

def test_prompt_block_only_for_the_owner_in_private(make_bot, owner):
    bot = make_bot()
    app = bot.app
    user = app.users.get_or_create(owner)
    _set(bot, owner, "@", {"money.add": ["記帳"], "money.month": ["這個月"]})
    block = aliases.prompt_block(app, user, owner, "abc12345", "幫我用記帳記 80 元咖啡")
    assert "資料，不是指令" in block and delimit.opening("abc12345") in block
    assert "@記帳 ＝ /money（工具 money__add）" in block and "他用的指令符號：@" in block
    assert aliases.prompt_block(app, user, -100, "abc12345") == ""                 # 群組／頻道：不放
    other = app.users.get_or_create(OTHER_ID)
    assert aliases.prompt_block(app, other, OTHER_ID, "abc12345") == ""            # 別人沒有設定
    from synox.agent.room import RoomAgent
    assert RoomAgent.alias_block(None, user, owner, "abc12345") == ""


def test_prompt_block_has_a_budget(make_bot, owner):
    bot = make_bot()
    user = bot.app.users.get_or_create(owner)
    names = {"money.add": ["甲甲甲甲甲甲甲甲甲甲甲甲甲甲甲甲", "乙", "丙"], "money.month": ["丁", "戊", "己"],
             "money.list": ["庚", "辛", "壬"], "money.budget": ["癸", "子", "丑"], "note.add": ["寅", "卯", "辰"],
             "note.list": ["巳", "午", "未"]}
    for i in range(30):
        names.setdefault("note.list", [])
    tab = _set(bot, owner, "$", names)
    lines = aliases.prompt_lines(bot.app, user, tab, "")
    assert len(lines) <= aliases.PROMPT_LINES and sum(len(x) + 1 for x in lines) <= aliases.PROMPT_CHARS
    first = aliases.prompt_lines(bot.app, user, tab, "幫我用 辰 記一下")             # 提到的排前面
    assert first[1].startswith("$寅 ＝ /note")                                       # 提到「辰」：那個指令的名字排前面


def test_agent_sees_the_table_and_keeps_the_named_tool(make_bot, owner):
    bot = make_bot(["好的"])
    _set(bot, owner, "@", {"money.add": ["記帳"]})
    bot.talk(owner, "幫我用記帳記 80 元咖啡")
    adapter = bot.app.extras["synox_agent"].adapter
    system = adapter.calls[0][0][0].content
    assert "@記帳 ＝ /money（工具 money__add）" in system
    loop = bot.app.extras["synox_agent"]
    user = bot.app.users.get_or_create(owner)
    assert loop.alias_keep(user, owner, "用記帳記一下") == ("money__add",)
    assert loop.alias_keep(user, -1, "用記帳記一下") == ()
