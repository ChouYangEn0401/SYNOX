# -*- coding: utf-8 -*-
"""PERM-5 Discord 頻道收訊：頻道型 bot 只收 allowlist 頻道裡 trigger 命中的訊息、chat_id 是負號、
頻道裡只有 surfaces∋channel 且 data≠user 的 pack、role_map 上限成員且不寫回、max_effect／DANGER、節流、按鈕只給發話者。
全部假傳輸（假 HTTP、直接餵 Gateway 事件、假 WebSocket），不連 Discord、不開埠。"""

import json
import logging

import pytest

from isdtelekit.core.registry import DANGER, TYPED
from isdtelekit.host.config import ConfigError

from synox import discord as dc
from synox import policy
from synox.app import build
from synox.config import SynoxConfig
from synox.discord import bots as bot_specs
from synox.discord.bots import BotSpec
from synox.discord.events import DISCORD_ROOM, parse_room_event, strip_mention
from synox.discord.gateway import CHANNEL_INTENTS, Gateway
from synox.identity import BASE, Identities
from synox.llm.fake import FakeAdapter
from synox.vault import Vault

from conftest import trust_core
from test_discord import Clock, FakeHTTP, FakeWS, dm, hello
from test_security import _write_pack

TOK_DM, TOK_CH = "token.dm", "token.channel"
BOT_ID = "999"
GUILD, ROOM, OTHER_ROOM = "100", "200", "201"
ROLE_MEMBER, ROLE_ADMINISH = "300", "301"

PY = ("from isdtelekit.core.registry import DANGER, READ, WRITE\n"
      "def install(app, pack):\n"
      "    n = pack.name\n"
      "    pack.group.leaf('look', lambda api, c, u, a: api.send_message(c, n + ' look'), 'look', effect=READ)\n"
      "    pack.group.leaf('put', lambda api, c, u, a: api.send_message(c, n + ' put'), 'put', effect=WRITE)\n"
      "    pack.group.leaf('wipe', lambda api, c, u, a: api.send_message(c, n + ' wipe'), 'wipe', effect=DANGER)\n")


def _pack(base, name, **over):
    return _write_pack(str(base / name), {"name": name, "group": name, "access": "everyone", **over}, {"pack.py": PY})


def make(tmp_path, *, mode="server", **lookup_over):
    """一個私訊型 bot（synox）＋一個頻道型 bot（lookup）。測試用 pack：
    dict（頻道可用、data=none）、board（頻道可用、data=shared）、club（頻道可用、access=member）、
    diary（只能私訊）；出廠的 money 是 data=user、只能私訊。"""
    base = tmp_path / "extra"
    folders = [_pack(base, "dict", surfaces=["dm", "channel"], data="none"),
               _pack(base, "board", surfaces=["dm", "channel"], data="shared"),
               _pack(base, "club", surfaces=["dm", "channel"], data="none", access="member"),
               _pack(base, "diary", data="none")]
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    trust_core(str(data), *folders)
    lookup = {"surface": "channel", "packs": ["dict", "board", "club", "diary", "money"],
              "guilds": {GUILD: {"channels": [ROOM], "role_map": {ROLE_MEMBER: "member", ROLE_ADMINISH: "member"}}},
              "trigger": "mention", **lookup_over}
    raw = {"mode": mode, "data_dir": str(data), "vault": {"mode": "file"}, "llm": {"kind": "fake"},
           "packs": {"dirs": [str(base)]},
           "channels": {"discord": {"owner_user_id": "777",
                                    "bots": {"synox": {"surface": "dm"}, "lookup": lookup}}}}
    config = SynoxConfig.from_dict(raw, require_token=False, root=str(tmp_path))
    vault = Vault(b"k" * 32, str(data))
    vault.set_secret("discord_bot_token:synox", TOK_DM)
    vault.set_secret("discord_bot_token:lookup", TOK_CH)
    app = build(config, home=None, adapter=FakeAdapter(None), vault=vault)
    http = FakeHTTP()
    for entry in app.extras["discord_entries"].values():
        entry.channel.http = http
    room = app.extras["discord_entries"]["lookup"]
    room.on_ready({"id": BOT_ID, "username": "lookup"})
    return app, http, room


def gm(text, uid="555", channel=ROOM, guild=GUILD, roles=(), mid="m1", **extra):
    """伺服器頻道裡的一則訊息（MESSAGE_CREATE 的 d）。"""
    return {"id": mid, "channel_id": channel, "guild_id": guild, "content": text,
            "author": {"id": uid, "username": f"u{uid}"},
            "member": {"roles": list(roles)}, **extra}


def posted_in(http, channel=ROOM, since=0):
    return [(kw["json"], kw["headers"]["Authorization"]) for m, u, kw in http.calls[since:]
            if m == "POST" and u.endswith(f"/channels/{channel}/messages")]


def say(app, http, room, text, **kw):
    before = len(http.calls)
    room.on_dispatch("MESSAGE_CREATE", gm(text, **kw))
    app.tasks.wait(5)
    return [j.get("content", "") for j, _ in posted_in(http, kw.get("channel", ROOM), before)]


def dm_say(app, http, text, uid="777"):
    before = len(http.calls)
    app.extras["discord_entries"]["synox"].on_dispatch("MESSAGE_CREATE", dm(uid=uid, text=text, channel=f"dm-{uid}")["d"])
    app.tasks.wait(5)
    return [j.get("content", "") for j, _ in posted_in(http, f"dm-{uid}", before)]


def unknown(cmd):
    return [f"未知指令：{cmd}，輸入 /help 查看可用指令。"]


OWNER = "777"


# ── 身分：頻道是負號 ──────────────────────────────────────────────────

def test_room_ids_are_negative_monotonic_and_persist(tmp_path):
    path = str(tmp_path / "i.json")
    ids = Identities(path)
    person = ids.resolve("discord", "1")
    a = ids.resolve_room(DISCORD_ROOM, "200")
    b = ids.resolve_room(DISCORD_ROOM, "201")
    assert person == BASE + 1 and a == -BASE and b == -(BASE + 1)                # BASE 保留給擁有者
    assert ids.resolve_room(DISCORD_ROOM, "200") == a and ids.external(DISCORD_ROOM, b) == "201"
    assert ids.unbind(DISCORD_ROOM, "201")
    again = Identities(path)
    assert again.resolve_room(DISCORD_ROOM, "202") == -(BASE + 2)                 # 只增不減、不重用
    assert again.resolve("discord", "2") == BASE + 2                              # 人的號段不受影響


# ── 事件解析 ─────────────────────────────────────────────────────────

SPEC = BotSpec(name="lookup", token="vault:x", surface="channel", max_effect="read",
               guilds={GUILD: {"channels": [ROOM], "role_map": {}}}, trigger="mention")


def _parse(d, spec=SPEC, bot_id=BOT_ID, event="MESSAGE_CREATE"):
    return parse_room_event(event, d, spec=spec, bot_id=bot_id, resolve=lambda ext: BASE + int(ext),
                            resolve_room=lambda cid: -(BASE + int(cid)))


def test_mention_trigger_strips_mention_and_chat_id_negative():
    ev = _parse(gm(f"<@{BOT_ID}>  /dict_look  hello", roles=["300"]))
    assert ev.inbound.text == "/dict_look hello" and ev.inbound.chat_id < 0
    assert ev.inbound.user_id == BASE + 555 and ev.inbound.chat_id != ev.inbound.user_id
    assert ev.channel_id == ROOM and ev.guild_id == GUILD and ev.roles == ["300"] and ev.message_id == "m1"
    assert _parse(gm(f"/x <@!{BOT_ID}>")).inbound.text == "/x"
    assert strip_mention("<@123> hi", BOT_ID) is None and strip_mention("hi", None) is None


@pytest.mark.parametrize("d", [
    gm(f"<@{BOT_ID}> /help", channel=OTHER_ROOM),                       # 不在 allowlist 的頻道
    gm(f"<@{BOT_ID}> /help", guild="101"),                              # 沒列的伺服器
    {**gm(f"<@{BOT_ID}> /help"), "guild_id": None},                     # 私訊（頻道型 bot 不收私訊）
    gm("/help"),                                                        # 沒 @（trigger=mention）
    gm("<@12345> /help"),                                               # @ 的是別人
    gm(f"<@{BOT_ID}>"),                                                 # 只有 @、沒有字
    gm("", attachments=[{"id": "a"}]),                                  # 只有附件
    {**gm(f"<@{BOT_ID}> /help"), "author": {"id": "8", "bot": True}},   # 別的 bot
    {**gm(f"<@{BOT_ID}> /help"), "author": {"id": BOT_ID}},             # 自己
    {**gm(f"<@{BOT_ID}> /help"), "webhook_id": "w"},                    # webhook
])
def test_room_parse_ignores(d):
    assert _parse(d) is None


def test_room_parse_ignores_edits_and_before_ready():
    assert _parse(gm(f"<@{BOT_ID}> /help"), event="MESSAGE_UPDATE") is None
    assert _parse(gm(f"<@{BOT_ID}> /help"), bot_id=None) is None         # 還不知道自己的 id：不認 @


def test_slash_prefix_trigger():
    spec = BotSpec(name="l", token="vault:x", surface="channel", guilds=SPEC.guilds, trigger="/", max_effect="read")
    assert _parse(gm("/dict_look"), spec=spec).inbound.text == "/dict_look"
    assert _parse(gm("hello /dict_look"), spec=spec) is None
    assert _parse(gm(f"<@{BOT_ID}> hi"), spec=spec) is None


# ── 設定 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bot, words", [
    ({"surface": "channel", "guilds": {GUILD: {"channels": [ROOM], "role_map": {"3": "admin"}}}}, "/user_role"),
    ({"surface": "channel", "max_effect": "danger"}, "danger"),
    ({"surface": "channel", "guilds": {GUILD: {"channels": []}}}, "頻道 id"),
    ({"surface": "channel", "guilds": {"abc": {"channels": [ROOM]}}}, "伺服器的 id"),
    ({"surface": "channel", "guilds": {GUILD: {"channels": ["x"]}}}, "Discord 的 id"),
    ({"surface": "channel", "trigger": "always"}, "trigger"),
    ({"surface": "channel", "rate_per_minute": 0}, "rate_per_minute"),
    ({"surface": "dm", "trigger": "/"}, "channel"),
])
def test_channel_bot_config_errors(tmp_path, bot, words):
    with pytest.raises(ConfigError) as e:
        SynoxConfig.from_dict({"channels": {"discord": {"bots": {"lookup": bot}}}}, require_token=False,
                              root=str(tmp_path))
    assert words in str(e.value)


def test_channel_bot_defaults():
    s = bot_specs.parse({"bots": {"l": {"surface": "channel", "guilds": {GUILD: {"channels": [ROOM, 201]}}}}})[0]
    assert s.max_effect == "read" and s.trigger == "mention" and s.rate_per_minute == 5
    assert s.allows(GUILD, ROOM) and s.allows(GUILD, "201") and not s.allows(GUILD, "202") and s.channel_count() == 2


# ── 整支 SYNOX：頻道進來、回到頻道 ─────────────────────────────────────

def test_channel_reply_goes_to_that_channel_with_channel_bot_and_quotes_speaker(tmp_path):
    app, http, room = make(tmp_path)
    before = len(http.calls)
    room.on_dispatch("MESSAGE_CREATE", gm(f"<@{BOT_ID}> /dict_look", uid=OWNER))
    app.tasks.wait(5)
    out = posted_in(http, ROOM, before)
    assert [j["content"] for j, _ in out] == ["dict look"]
    body, auth = out[0]
    assert auth == f"Bot {TOK_CH}"                                               # 收到訊息的那個 bot
    assert body["message_reference"]["message_id"] == "m1"                       # 引用發話者那則
    assert body["allowed_mentions"] == {"parse": [], "replied_user": True}       # 提及他，其他 @ 不解析
    rid = app.extras["identities"].lookup(DISCORD_ROOM, ROOM)
    assert rid is not None and rid <= -BASE
    assert not any(u.endswith("/users/@me/channels") for _, u, _ in http.calls)  # 沒開私訊


def test_other_channel_and_untriggered_messages_are_silent(tmp_path):
    app, http, room = make(tmp_path)
    assert say(app, http, room, f"<@{BOT_ID}> /dict_look", uid=OWNER, channel=OTHER_ROOM) == []
    assert say(app, http, room, "/dict_look", uid=OWNER) == []
    assert not http.calls


def test_dm_bot_still_only_dms(tmp_path):
    app, http, _room = make(tmp_path)
    entry = app.extras["discord_entries"]["synox"]
    entry.on_dispatch("MESSAGE_CREATE", gm(f"<@{BOT_ID}> /dict_look", uid=OWNER))
    app.tasks.wait(5)
    assert not http.calls
    assert dm_say(app, http, "/dict_look") == ["dict look"]


def test_channel_bot_not_used_for_notifications(tmp_path):
    app, http, _room = make(tmp_path)
    assert list(app.extras["discord_bots"].channels) == ["synox"]
    app.notify_owner("提醒")
    assert {kw["headers"]["Authorization"] for _, _, kw in http.calls} == {f"Bot {TOK_DM}"}


def test_data_user_and_dm_only_packs_are_unknown_in_channel(tmp_path):
    app, http, room = make(tmp_path, rate_per_minute=20)
    assert say(app, http, room, f"<@{BOT_ID}> /money_month", uid=OWNER) == unknown("/money_month")
    assert say(app, http, room, f"<@{BOT_ID}> /money", uid=OWNER) == unknown("/money")
    assert say(app, http, room, f"<@{BOT_ID}> /diary_look", uid=OWNER) == unknown("/diary_look")
    assert say(app, http, room, f"<@{BOT_ID}> /bot_status", uid=OWNER) == unknown("/bot_status")   # 內建的也收起來
    assert say(app, http, room, f"<@{BOT_ID}> /nosuch", uid=OWNER) == unknown("/nosuch")
    assert "共 0 元" in " ".join(dm_say(app, http, "/money_month"))              # 私訊照常
    help_text = " ".join(say(app, http, room, f"<@{BOT_ID}> /help all", uid=OWNER))
    assert "/dict_look" in help_text and "/money" not in help_text and "/diary" not in help_text
    assert "/dict_put" not in help_text and "/dict_wipe" not in help_text        # 唯讀 bot：會改東西的不列


def test_max_effect_read_refuses_write(tmp_path):
    app, http, room = make(tmp_path)
    out = say(app, http, room, f"<@{BOT_ID}> /board_put", uid=OWNER)
    assert len(out) == 1 and "唯讀" in out[0] and not out[0].startswith("未知指令")
    assert "board put" not in " ".join(out)
    out = say(app, http, room, f"<@{BOT_ID}> /board_wipe", uid=OWNER)
    assert len(out) == 1 and "board wipe" not in out[0] and "私訊" in out[0]


def test_write_only_for_shared_data_and_member(tmp_path):
    app, http, room = make(tmp_path, max_effect="write")
    assert say(app, http, room, f"<@{BOT_ID}> /board_put", uid=OWNER) == ["board put"]   # shared：擁有者可以
    out = say(app, http, room, f"<@{BOT_ID}> /dict_put", uid=OWNER)                       # data=none：不行
    assert len(out) == 1 and "dict put" not in out[0] and "共用資料" in out[0]
    out = say(app, http, room, f"<@{BOT_ID}> /board_put", uid="555")                      # 訪客：不行
    assert "board put" not in " ".join(out)
    out = say(app, http, room, f"<@{BOT_ID}> /board_wipe", uid=OWNER)                     # DANGER：永遠不行
    assert len(out) == 1 and "board wipe" not in out[0] and "私訊" in out[0]
    # 真的管理員（/user_role 給的）：data=shared 的寫入在伺服器版本來就要管理員（PERM-2）
    sid = app.extras["identities"].resolve("discord", "556")
    app.users.get_or_create(sid)
    app.users.set_role(sid, max(app.registry.roles))
    assert say(app, http, room, f"<@{BOT_ID}> /board_put", uid="556") == ["board put"]


def test_danger_never_in_channel_even_if_spec_says_so(tmp_path):
    app, http, room = make(tmp_path)
    forced = BotSpec(name="x", token="vault:x", surface="channel", max_effect="danger", packs="all",
                     guilds={GUILD: {"channels": [ROOM], "role_map": {}}})
    owner = app.users.get_or_create(app.config.owner_id)
    d = policy.decide(app, owner, app.registry.node("board.wipe"), via=TYPED, chat_id=-BASE, bot=forced)
    assert not d.allowed and d.reason == "bot_effect" and "私訊" in d.message
    assert app.registry.node("board.wipe").effect == DANGER


def test_role_map_gives_member_capped_and_not_saved(tmp_path):
    app, http, room = make(tmp_path)
    guest = " ".join(say(app, http, room, f"<@{BOT_ID}> /club_look", uid="555"))
    assert "club look" not in guest
    assert say(app, http, room, f"<@{BOT_ID}> /club_look", uid="555", roles=[ROLE_MEMBER]) == ["club look"]
    uid = app.extras["identities"].lookup("discord", "555")
    roles = app.users.roles
    assert app.users.get(uid).role == min(roles)                                 # users.json 沒被改
    from isdtelekit.users.manager import UserManager
    reread = UserManager(app.config.path("users.json")).get(uid)                 # 檔案裡也還是訪客
    assert reread is None or reread.role == min(roles)
    assert "club look" not in " ".join(dm_say(app, http, "/club_look", uid="555"))   # 私訊：還是訪客
    # 上限成員：兩個身分組都對到也只到成員；管理員才有的內建指令照樣不存在
    out = say(app, http, room, f"<@{BOT_ID}> /user_role", uid="555", roles=[ROLE_MEMBER, ROLE_ADMINISH])
    assert out == unknown("/user_role")
    floor = policy.role_floor_from(roles, ["member", "member"])
    assert floor == policy.member_role(roles) < max(roles)
    with policy.using_role_floor(max(roles)):                                    # 就算有人塞了管理員，也封頂成員
        assert policy.effective_user(app, app.users.get(uid)).role == policy.member_role(roles)
    assert app.users.get(uid).role == min(roles)


def test_user_role_unaffected_by_role_map(tmp_path):
    app, http, room = make(tmp_path)
    say(app, http, room, f"<@{BOT_ID}> /club_look", uid="555", roles=[ROLE_MEMBER])
    uid = app.extras["identities"].lookup("discord", "555")
    app.users.set_role(uid, max(app.users.roles))                                # 擁有者用 /user_role 升管理員
    assert app.users.get(uid).role == max(app.users.roles)
    assert say(app, http, room, f"<@{BOT_ID}> /club_look", uid="555") == ["club look"]   # max(管理員, 無)＝管理員
    assert app.users.get(uid).role == max(app.users.roles)                       # 頻道沒有把它拉下來


def test_mention_without_command_gets_hint_and_no_ai(tmp_path):
    app, http, room = make(tmp_path)
    app.extras["synox_agent"].adapter = FakeAdapter(["不該被叫到"])
    assert say(app, http, room, f"<@{BOT_ID}> 你好", uid=OWNER) == [dc.CHAT_IN_DM]
    assert say(app, http, room, f"<@{BOT_ID}> /ai 你好", uid=OWNER) == unknown("/ai")
    assert app.extras["synox_agent"].adapter.calls == []


def test_throttle_per_channel_and_person(tmp_path, caplog):
    app, http, room = make(tmp_path, rate_per_minute=2)
    clock = Clock()
    room.throttle._clock = clock
    with caplog.at_level(logging.INFO):
        replies = [say(app, http, room, f"<@{BOT_ID}> /dict_look", uid=OWNER) for _ in range(3)]
    assert replies == [["dict look"], ["dict look"], []]
    assert any("throttled" in r.getMessage() for r in caplog.records)
    assert say(app, http, room, f"<@{BOT_ID}> /dict_look", uid="555") == ["dict look"]   # 別人不受影響
    clock.t += 61
    assert say(app, http, room, f"<@{BOT_ID}> /dict_look", uid=OWNER) == ["dict look"]


def test_buttons_only_for_the_speaker(tmp_path):
    app, http, room = make(tmp_path)
    say(app, http, room, f"<@{BOT_ID}> /dict_look", uid=OWNER)                   # 記下頻道
    rid = app.extras["identities"].lookup(DISCORD_ROOM, ROOM)
    owner_uid = app.config.owner_id
    api = dc.RoomReply(room.channel, rid, "m1", owner_uid, room._record)
    sent = api.send_message(rid, "要嗎？", reply_markup={"inline_keyboard": [[{"text": "好", "callback_data": "nothing:x"}]]})
    mid = sent["result"]["message_id"]
    assert room.speaker_of(mid) == owner_uid

    def click(uid, iid):
        before = len(http.calls)
        room.on_dispatch("INTERACTION_CREATE", {
            "type": 3, "id": iid, "token": "t", "guild_id": GUILD, "channel_id": ROOM,
            "member": {"user": {"id": uid}, "roles": []}, "data": {"custom_id": "nothing:x"},
            "message": {"id": str(mid), "content": "要嗎？"}})
        return [kw["json"] for m, u, kw in http.calls[before:] if f"/interactions/{iid}/" in u]

    other = click("555", "i1")
    assert other == [{"type": 4, "data": {"content": dc.ONLY_SPEAKER, "flags": 64}}]
    mine = click(OWNER, "i2")
    assert len(mine) == 1 and dc.ONLY_SPEAKER not in json.dumps(mine, ensure_ascii=False)
    room.on_dispatch("INTERACTION_CREATE", {                                     # 不認得的訊息：也不給按
        "type": 3, "id": "i4", "token": "t", "guild_id": GUILD, "channel_id": ROOM,
        "member": {"user": {"id": OWNER}}, "data": {"custom_id": "nothing:x"}, "message": {"id": "424242"}})
    assert any(kw["json"].get("data", {}).get("content") == dc.ONLY_SPEAKER
               for m, u, kw in http.calls if "/interactions/i4/" in u)


def test_someone_elses_conversation_is_not_hijacked(tmp_path):
    app, http, room = make(tmp_path)
    say(app, http, room, f"<@{BOT_ID}> /dict_look", uid=OWNER)
    rid = app.extras["identities"].lookup(DISCORD_ROOM, ROOM)
    got = []
    app.dispatcher.conv_manager.start(rid, app.config.owner_id, "form", lambda api, c, u, t: got.append((u.tg_id, t)))
    say(app, http, room, f"<@{BOT_ID}> 插嘴", uid="555")
    assert got == []
    say(app, http, room, f"<@{BOT_ID}> 我的答案", uid=OWNER)
    assert got == [(app.config.owner_id, "我的答案")]


# ── Gateway：頻道型的 intents、READY 拿到自己的 id ─────────────────────

def test_channel_gateway_intents_and_ready(tmp_path, monkeypatch):
    app, _http, room = make(tmp_path)
    room.bot_id = None
    monkeypatch.setattr("isdtelekit.host.supervisor.SupervisedChannel.start", lambda self: None)
    app.start(())
    gw = app.hub.get("discord:lookup")._factory()
    assert isinstance(gw, Gateway) and gw.intents == CHANNEL_INTENTS and gw._token == TOK_CH
    assert app.hub.get("discord:synox")._factory().intents != CHANNEL_INTENTS
    clock = Clock()
    conns = []

    def connect(url):
        if conns:
            gw.stop()
        ws = FakeWS([hello(), {"op": 0, "t": "READY", "s": 1, "d": {"session_id": "S", "user": {"id": "4321"}}}], clock)
        conns.append(ws)
        return ws
    gw._connect = connect
    gw._stop.wait = lambda t=None: gw._stop.is_set()
    gw.run_forever()
    assert conns[0].sent[0]["d"]["intents"] == CHANNEL_INTENTS
    assert room.bot_id == "4321"


# ── /bot_status、doctor ─────────────────────────────────────────────

def test_bot_status_shows_channel_bot(tmp_path):
    app, http, _room = make(tmp_path)
    text = "\n".join(dm_say(app, http, "/bot_status"))
    part = text.split("bot lookup")[1]
    assert "頻道型" in part and "收訊中" in part and "上限「唯讀」" in part
    assert "1 個伺服器、1 個頻道" in part and "被 @ 才回" in part and "role_map 2 筆" in part
    assert "每分鐘 5 則" in part and "AI 關" in part
    assert "money：pack.json 的 surfaces 沒有 \"channel\"" in part
    assert "diary：pack.json 的 surfaces 沒有" in part
    assert "會出現：" in part and "dict" in part.split("會出現：")[1].split("\n")[0]
    assert TOK_CH not in text


def test_scope_reason_for_channel_is_before_max_effect():
    from synox.discord import scope
    assert scope.REASONS.index(scope._not_for_channel) < scope.REASONS.index(scope._over_max_effect)
    spec = BotSpec(name="c", token="vault:x", surface="channel", packs="all", max_effect="write",
                   guilds={GUILD: {"channels": [ROOM]}})
    infos = {"mine": scope.PackInfo("mine", ("read",), surfaces=("dm", "channel"), data="user"),
             "dmonly": scope.PackInfo("dmonly", ("read",)),
             "w": scope.PackInfo("w", ("write",), surfaces=("dm", "channel"), data="none"),
             "s": scope.PackInfo("s", ("read", "write", "danger"), surfaces=("dm", "channel"), data="shared")}
    rep = scope.report(spec, infos)
    hidden = dict(rep["hidden"])
    assert "data=user" in hidden["mine"] and "surfaces" in hidden["dmonly"] and "共用" not in hidden["dmonly"]
    assert "data=shared" in hidden["w"]
    eff = dict(rep["effective"])
    assert "1 個指令在頻道裡不會出現" in eff["s"]


def test_doctor_shows_channel_bot(tmp_path):
    from synox import doctor
    from synox.vault.keyring import write_key
    data = tmp_path / "data"
    data.mkdir()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"data_dir": str(data), "vault": {"mode": "file"}, "channels": {"discord": {"bots": {
        "synox": {"surface": "dm"},
        "lookup": {"surface": "channel", "packs": ["notes"], "trigger": "/",
                   "guilds": {GUILD: {"channels": [ROOM, OTHER_ROOM], "role_map": {ROLE_MEMBER: "member"}}}}}}}}),
        encoding="utf-8")
    write_key(str(data / ".synox.key"), b"k" * 32, "file")
    vault = Vault(b"k" * 32, str(data))
    vault.set_secret("discord_bot_token:synox", TOK_DM)
    vault.set_secret("discord_bot_token:lookup", TOK_CH)
    lines = []
    doctor.run(offline=True, config_path=str(cfg), out=lines.append)
    text = "\n".join(lines)
    lookup = text.split("bot lookup")[1]
    assert "頻道型" in lookup and "✅ token 在保管箱" in lookup
    assert "1 個伺服器、2 個頻道" in lookup and "以 / 開頭" in lookup and "role_map 1 筆" in lookup
    assert "notes：pack.json 的 surfaces 沒有" in lookup
    assert TOK_CH not in text and TOK_DM not in text
