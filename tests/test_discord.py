"""Discord 通道：全部假傳輸（假 Gateway 連線、假 HTTP），不連 Discord、不開埠。"""

import json
import queue
import threading

import pytest

from isdtelekit.testing import OWNER_ID, FakeChannel

from synox import discord as dc
from synox.app import build
from synox.config import SynoxConfig
from synox.discord.events import parse_event, pairing_sender
from synox.discord.gateway import Closed, Gateway, GatewayFatal
from synox.discord.rest import DiscordChannel, chunks, components
from synox.identity import BASE, Identities, IdentityError
from synox.llm.fake import FakeAdapter
from synox.vault import Vault

TOKEN = "fake.discord.token"


# ── 假 HTTP ─────────────────────────────────────────────────────────

class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        return self._body


class FakeHTTP:
    def __init__(self):
        self.calls = []
        self.next_id = 9000
        self.queue = []                 # 預先排好的回應（用完就照預設）

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if self.queue:
            return self.queue.pop(0)
        if url.endswith("/users/@me/channels"):
            return Resp(200, {"id": "dm-" + kw["json"]["recipient_id"]})
        if method == "POST" and url.endswith("/messages"):
            self.next_id += 1
            return Resp(200, {"id": str(self.next_id)})
        return Resp(204)

    def posted(self):
        return [kw.get("json") for m, u, kw in self.calls if m == "POST" and u.endswith("/messages")]


# ── 假 Gateway 連線 ──────────────────────────────────────────────────

class FakeWS:
    """script：要依序收到的訊息（dict＝JSON、Closed＝關閉、None＝逾時一次）。送出的都記在 sent。"""

    def __init__(self, script, clock):
        self.script = list(script)
        self.sent = []
        self.closed = False
        self.clock = clock

    def recv(self, timeout):
        if self.closed:
            raise Closed(1000)
        if not self.script:
            self.clock.t += timeout
            raise Closed(1001)
        item = self.script.pop(0)
        if isinstance(item, Closed):
            raise item
        if item is None:
            self.clock.t += timeout
            return None
        return json.dumps(item)

    def send(self, text):
        self.sent.append(json.loads(text))

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def hello(ms=1000):
    return {"op": 10, "d": {"heartbeat_interval": ms}}


def dm(uid="111", text="/help", channel="dm-111", **extra):
    return {"op": 0, "t": "MESSAGE_CREATE", "s": extra.pop("s", 1),
            "d": {"id": "5", "channel_id": channel, "content": text, "timestamp": "2026-11-09T08:00:00+00:00",
                  "author": {"id": uid, "username": "alice"}, **extra}}


def make_gateway(scripts, on_dispatch=None, **kw):
    clock = Clock()
    conns = []

    def connect(url):
        ws = FakeWS(scripts.pop(0) if scripts else [], clock)
        ws.url = url
        conns.append(ws)
        return ws
    events = []
    gw = Gateway(TOKEN, on_dispatch or (lambda e, d: events.append((e, d))), connect=connect, clock=clock,
                 rand=lambda: 0.0, **kw)
    gw._stop.wait = lambda t=None: gw._stop.is_set()        # 退避不真的睡
    return gw, conns, events


# ── 身分對應 ─────────────────────────────────────────────────────────

def test_identities_reserved_range_and_persist(tmp_path):
    path = str(tmp_path / "identities.json")
    ids = Identities(path)
    a = ids.resolve("discord", "111")
    b = ids.resolve("discord", "222")
    assert a == BASE + 1 and b == BASE + 2                # BASE 保留給擁有者（只用 Discord 時的 owner_id）
    assert ids.resolve("discord", "111") == a
    assert ids.external("discord", b) == "222"
    again = Identities(path)
    assert again.lookup("discord", "222") == b
    assert again.resolve("discord", "333") == BASE + 3


def test_identities_never_reuse_numbers(tmp_path):
    ids = Identities(str(tmp_path / "i.json"))
    a = ids.resolve("discord", "111")
    assert ids.unbind("discord", "111")
    assert ids.resolve("discord", "999") != a           # 陌生人不會繼承舊號碼的資料
    assert Identities(str(tmp_path / "i.json")).resolve("discord", "888") == a + 2


def test_identities_first_stranger_never_gets_base(tmp_path):
    """審查 A #1：只用 Discord 時擁有者＝BASE；舊版第一個陌生人也拿到 BASE＝擁有者。"""
    ids = Identities(str(tmp_path / "i.json"))
    assert ids.resolve("discord", "666") != BASE
    assert ids.resolve_room("discord-channel", "c1") == -BASE              # 頻道是負號，跟任何人都不相等
    ids.bind("discord", "777", BASE)                                         # 配對：擁有者
    assert ids.resolve("discord", "888") not in (BASE, ids.lookup("discord", "666"))


def test_identities_legacy_base_is_marked_suspect(tmp_path):
    path = tmp_path / "i.json"
    path.write_text(json.dumps({"next": BASE + 2, "links": {"discord:666": BASE, "discord:667": BASE + 1}}),
                    encoding="utf-8")
    ids = Identities(str(path))
    assert ids.is_suspect("discord", "666") and not ids.is_suspect("discord", "667")
    assert not ids.owner_bound("discord", BASE)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["version"] == 2 and saved["suspect"] == ["discord:666"]       # 遷移寫回（之後不再重標）
    assert Identities(str(path)).is_suspect("discord", "666")
    ids.bind("discord", "666", BASE)                                         # 擁有者重新配對＝確認
    assert ids.owner_bound("discord", BASE) and not Identities(str(path)).is_suspect("discord", "666")
    ro = tmp_path / "ro.json"
    ro.write_text(json.dumps({"links": {"discord:1": BASE}}), encoding="utf-8")
    assert Identities(str(ro), readonly=True).is_suspect("discord", "1")
    assert "version" not in json.loads(ro.read_text(encoding="utf-8"))     # readonly（doctor）不改檔


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '{"links": {"discord:1": "x"}}'])
def test_identities_corrupt_file_refuses(tmp_path, content):
    """審查 A #10：壞掉的檔不當成空的重新發號（下一個陌生人會拿到別人的舊號碼）。"""
    path = tmp_path / "i.json"
    path.write_text(content, encoding="utf-8")
    from synox.identity import IdentityFileError
    with pytest.raises(IdentityFileError):
        Identities(str(path))
    assert path.read_text(encoding="utf-8") == content                     # 原檔留著、沒被改名或蓋掉


def test_identities_bind_owner_and_conflict(tmp_path):
    ids = Identities(str(tmp_path / "i.json"))
    ids.bind("discord", "777", OWNER_ID)
    assert ids.lookup("discord", "777") == OWNER_ID
    assert ids.external("discord", OWNER_ID) == "777"
    with pytest.raises(IdentityError):
        ids.bind("discord", "778", OWNER_ID)
    assert ids.resolve("discord", "1") >= BASE           # 新人一律保留號段，不會是 Telegram id


# ── 事件 → Inbound ───────────────────────────────────────────────────

def test_parse_dm_message():
    inbound, channel = parse_event("MESSAGE_CREATE", dm()["d"], lambda ext: BASE + int(ext))
    assert inbound.channel == "discord" and inbound.user_id == inbound.chat_id == BASE + 111
    assert inbound.text == "/help" and inbound.username == "alice" and channel == "dm-111"
    assert inbound.sent_at and not inbound.edited


@pytest.mark.parametrize("d", [
    {**dm()["d"], "guild_id": "g1"},                                  # 伺服器頻道：不收
    {**dm()["d"], "author": {"id": "1", "bot": True}},                # bot
    {**dm()["d"], "content": "   "},                                  # 沒文字
    {**dm()["d"], "author": {}},
])
def test_parse_ignores(d):
    assert parse_event("MESSAGE_CREATE", d, lambda ext: 1) is None


def test_parse_button():
    d = {"type": 3, "id": "i1", "token": "tok", "channel_id": "dm-111", "user": {"id": "111", "username": "a"},
         "data": {"custom_id": "job_ok:1"}, "message": {"id": "9001", "content": "要嗎？",
                                                         "timestamp": "2026-11-09T08:00:00+00:00"}}
    inbound, channel = parse_event("INTERACTION_CREATE", d, lambda ext: 42)
    assert inbound.button.data == "job_ok:1" and inbound.button.cq_id == "i1:tok"
    assert inbound.button.message_id == 9001 and inbound.button.clicker_id == 42 and channel == "dm-111"


def test_pairing_sender():
    assert pairing_sender("MESSAGE_CREATE", dm(text="04 29 17")["d"], "042917")["id"] == "111"
    assert pairing_sender("MESSAGE_CREATE", dm(text="000000")["d"], "042917") is None
    assert pairing_sender("MESSAGE_CREATE", {**dm(text="042917")["d"], "guild_id": "g"}, "042917") is None


# ── REST 回覆 ────────────────────────────────────────────────────────

def test_components_and_chunks():
    rows = components({"inline_keyboard": [[{"text": "好", "callback_data": "ok:1"},
                                            {"text": "網站", "url": "https://x"}]]})
    assert rows[0]["components"][0]["custom_id"] == "ok:1" and rows[0]["components"][1]["style"] == 5
    parts = chunks("a" * 4500)
    assert len(parts) == 3 and all(len(p) <= 2000 for p in parts)


def test_send_opens_dm_and_buttons_on_last_chunk(tmp_path):
    ids = Identities(str(tmp_path / "i.json"))
    uid = ids.resolve("discord", "111")
    http = FakeHTTP()
    api = DiscordChannel(TOKEN, ids, http=http)
    out = api.send_message(uid, "x" * 2500, reply_markup={"inline_keyboard": [[{"text": "ok", "callback_data": "a"}]]})
    assert out["ok"] and out["result"]["message_id"] == 9002
    assert http.calls[0][1].endswith("/users/@me/channels")
    posted = http.posted()
    assert "components" not in posted[0] and posted[1]["components"]
    assert all(kw["headers"]["Authorization"] == f"Bot {TOKEN}" for _, _, kw in http.calls)
    assert api.send_message(123, "給只有 Telegram 的人")["ok"] is False      # 找不到 Discord 帳號：不送


def test_rate_limit_retry_and_errors(tmp_path):
    ids = Identities(str(tmp_path / "i.json"))
    http = FakeHTTP()
    api = DiscordChannel(TOKEN, ids, http=http, sleep=lambda s: None)
    api.remember_dm(5, "c5")
    http.queue = [Resp(429, {"retry_after": 0.2})]
    assert api.send_message(5, "hi")["ok"]
    http.queue = [Resp(403, {"message": "Missing Access"})]
    assert api.send_message(5, "hi")["ok"] is False


def test_answer_callback(tmp_path):
    http = FakeHTTP()
    api = DiscordChannel(TOKEN, Identities(str(tmp_path / "i.json")), http=http)
    api.answer_callback_query("i1:tok", "好了")
    api.answer_callback_query("i2:tok2")
    assert http.calls[0][1].endswith("/interactions/i1/tok/callback")
    assert http.calls[0][2]["json"] == {"type": 4, "data": {"content": "好了", "flags": 64}}
    assert http.calls[1][2]["json"] == {"type": 6}


# ── Gateway 迴圈 ─────────────────────────────────────────────────────

def test_gateway_identify_heartbeat_dispatch():
    ready = {"op": 0, "t": "READY", "s": 1, "d": {"session_id": "S", "resume_gateway_url": "wss://resume.x",
                                                  "user": {"username": "bot"}}}
    gw, conns, events = make_gateway([[hello(), ready, {"op": 11}, dm(s=2), None, {"op": 11}, None]])
    orig = gw._connect

    def connect(url):                       # 第一條連線腳本收完會斷；要開第二條時就停
        if len(conns) >= 1:
            gw.stop()
        return orig(url)
    gw._connect = connect
    t = threading.Thread(target=gw.run_forever)
    t.start()
    t.join(5)
    assert not t.is_alive()
    ws = conns[0]
    assert ws.sent[0]["op"] == 2 and ws.sent[0]["d"]["token"] == TOKEN
    assert ws.sent[0]["d"]["intents"] == (1 << 12) | (1 << 15)
    assert any(m["op"] == 1 for m in ws.sent)                       # 有心跳
    assert events and events[0][0] == "MESSAGE_CREATE"
    assert gw.session_id == "S" and gw.seq == 2


def test_gateway_resumes_after_reconnect():
    first = [hello(), {"op": 0, "t": "READY", "s": 1, "d": {"session_id": "S", "resume_gateway_url": "wss://r.x"}},
             {"op": 7}]
    second = [hello(), {"op": 0, "t": "RESUMED", "s": 2, "d": {}}]
    gw, conns, _ = make_gateway([first, second])
    orig = gw._connect

    def connect(url):
        if len(conns) >= 2:
            gw.stop()
        return orig(url)
    gw._connect = connect
    gw.run_forever()
    assert conns[1].sent[0]["op"] == 6 and conns[1].sent[0]["d"]["session_id"] == "S"
    assert conns[1].url.startswith("wss://r.x")


def test_gateway_invalid_session_reidentifies():
    first = [hello(), {"op": 0, "t": "READY", "s": 1, "d": {"session_id": "S"}}, {"op": 9, "d": False}]
    second = [hello()]
    gw, conns, _ = make_gateway([first, second])
    orig = gw._connect

    def connect(url):
        if len(conns) >= 2:
            gw.stop()
        return orig(url)
    gw._connect = connect
    gw.run_forever()
    assert conns[1].sent[0]["op"] == 2                              # 重新 Identify


def test_gateway_zombie_connection_reconnects():
    # 送了心跳卻一直沒 ACK → 下一次該心跳時斷線
    script = [hello(1000)] + [None] * 5
    gw, conns, _ = make_gateway([script, [hello()]])
    orig = gw._connect

    def connect(url):
        if len(conns) >= 2:
            gw.stop()
        return orig(url)
    gw._connect = connect
    gw.run_forever()
    assert len(conns) >= 2 and conns[0].closed
    assert [m["op"] for m in conns[0].sent] == [2, 1]          # Identify、一次心跳，沒 ACK 就斷
    assert conns[1].sent[0]["op"] == 2                          # 還沒拿到 session：重新 Identify


def test_gateway_fatal_close():
    gw, conns, _ = make_gateway([[hello(), Closed(4014)]])
    with pytest.raises(GatewayFatal) as e:
        gw.run_forever()
    assert "Message Content" in str(e.value)


# ── 整支 SYNOX：Discord 私訊進來、回到 Discord ───────────────────────────

def make_discord_bot(tmp_path, *, owner_discord=None, telegram=False):
    data = tmp_path / "data"
    raw = {"data_dir": str(data), "vault": {"mode": "file"}, "llm": {"kind": "fake"},
           "channels": {"discord": {"enabled": True, "bot_token": "vault:discord_bot_token",
                                    **({"owner_user_id": owner_discord} if owner_discord else {})}}}
    if telegram:
        raw["owner_id"] = OWNER_ID
    config = SynoxConfig.from_dict(raw, require_token=False, root=str(tmp_path))
    vault = Vault(b"k" * 32, str(data))
    vault.set_secret("discord_bot_token", TOKEN)
    home = FakeChannel()
    app = build(config, home=home, adapter=FakeAdapter(None), vault=vault)
    http = FakeHTTP()
    app.extras["discord"].http = http
    return app, http, home


def test_discord_only_config_owner_defaults_to_reserved(tmp_path):
    app, _, _ = make_discord_bot(tmp_path)
    assert app.config.owner_id == BASE
    from synox.__main__ import run_channels
    assert run_channels(app.config) == ()


def test_no_channel_runs_web_only_and_errors_when_web_is_off_too(tmp_path):
    from isdtelekit.host.config import ConfigError
    from synox.__main__ import run_channels
    config = SynoxConfig.from_dict({"owner_id": 1}, require_token=False, root=str(tmp_path))
    assert run_channels(config) == ()
    off = SynoxConfig.from_dict({"owner_id": 1, "web": {"enabled": False}}, require_token=False, root=str(tmp_path))
    with pytest.raises(ConfigError):
        run_channels(off)


def test_owner_dm_roundtrip(tmp_path):
    app, http, _ = make_discord_bot(tmp_path, owner_discord="777")
    entry = app.extras["discord_entry"]
    entry.on_dispatch("MESSAGE_CREATE", dm(uid="777", text="/help", channel="dm-777")["d"])
    app.tasks.wait(5)
    posted = [u for m, u, kw in http.calls if m == "POST" and u.endswith("/messages")]
    assert posted and all("/channels/dm-777/" in u for u in posted)
    assert not any(u.endswith("/users/@me/channels") for _, u, _ in http.calls)   # 用收訊時記下的私訊頻道


def test_stranger_does_not_get_owner(tmp_path):
    app, http, _ = make_discord_bot(tmp_path, owner_discord="777")
    entry = app.extras["discord_entry"]
    entry.on_dispatch("MESSAGE_CREATE", dm(uid="666", text="/help", channel="dm-666")["d"])
    app.tasks.wait(5)
    ids = app.extras["identities"]
    uid = ids.lookup("discord", "666")
    assert uid >= BASE and uid != app.config.owner_id and uid != ids.lookup("discord", "777")
    # 個人版：陌生人被擋（不會看到擁有者的指令選單）
    texts = [(j or {}).get("content", "") for j in http.posted()]
    assert texts and not any("/notes" in t for t in texts)


def test_discord_only_unpaired_stranger_first_is_not_owner(tmp_path):
    """審查 A #1：沒 owner_user_id、沒配對、陌生人先來 → 不是擁有者（私訊一律不收、不發號碼）。"""
    app, http, _ = make_discord_bot(tmp_path)
    assert app.config.owner_id == BASE
    entry = app.extras["discord_entry"]
    entry.on_dispatch("MESSAGE_CREATE", dm(uid="666", text="/notes", channel="dm-666")["d"])
    entry.on_dispatch("MESSAGE_CREATE", dm(uid="666", text="/help", channel="dm-666")["d"])
    app.tasks.wait(5)
    ids = app.extras["identities"]
    assert ids.lookup("discord", "666") is None                             # 沒發號碼、沒進 dispatcher
    texts = [(j or {}).get("content", "") for j in http.posted()]
    assert texts == [dc.UNPAIRED]                                           # 只回一次「還沒配對」
    assert not any("/notes" in t for t in texts)
    d = {"type": 3, "id": "i1", "token": "t1", "channel_id": "dm-666", "user": {"id": "666"},
         "data": {"custom_id": "agent_ok:go:x"}, "message": {"id": "1", "content": ""}}
    entry.on_dispatch("INTERACTION_CREATE", d)
    assert any(kw.get("json", {}).get("data", {}).get("content") == dc.UNPAIRED for _, u, kw in http.calls
               if "/interactions/i1/t1/callback" in u)
    assert "還沒接上" in dc.owner_problem(app.config, ids)
    assert "擁有者還沒接上" in dc.scope.status_text(app, app.config)
    # 擁有者在別的程序配對好（discord pair 寫檔）：開著的 bot 重讀，擁有者可以用、陌生人拿新號碼（不是 BASE）
    Identities(app.config.path("identities.json")).bind("discord", "777", BASE)
    entry.on_dispatch("MESSAGE_CREATE", dm(uid="777", text="/help", channel="dm-777")["d"])
    entry.on_dispatch("MESSAGE_CREATE", dm(uid="666", text="/help", channel="dm-666")["d"])
    app.tasks.wait(5)
    assert ids.lookup("discord", "777") == BASE
    assert ids.lookup("discord", "666") not in (None, BASE)
    assert dc.owner_problem(app.config, ids) == ""


def test_discord_only_legacy_base_held_by_stranger(tmp_path):
    """舊版的 identities.json：BASE 已經發給某個 Discord 帳號 → 標待確認、私訊不收；config 的 owner_user_id 指別人 → 移開。"""
    data = tmp_path / "data"
    data.mkdir()
    (data / "identities.json").write_text(json.dumps({"next": BASE + 1, "links": {"discord:666": BASE}}),
                                          encoding="utf-8")
    app, http, _ = make_discord_bot(tmp_path)
    ids = app.extras["identities"]
    assert "666" in dc.owner_problem(app.config, ids)
    app.extras["discord_entry"].on_dispatch("MESSAGE_CREATE", dm(uid="666", text="/notes", channel="dm-666")["d"])
    app.tasks.wait(5)
    assert [(j or {}).get("content", "") for j in http.posted()] == [dc.UNPAIRED]

    other = tmp_path / "other"
    (other / "data").mkdir(parents=True)
    (other / "data" / "identities.json").write_text(
        json.dumps({"next": BASE + 1, "links": {"discord:666": BASE}}), encoding="utf-8")
    app2, _, _ = make_discord_bot(other, owner_discord="777")
    ids2 = app2.extras["identities"]
    assert ids2.lookup("discord", "777") == BASE and ids2.lookup("discord", "666") is None
    assert any("666" in n for n in app2.extras["discord_identity_notes"])
    assert dc.owner_problem(app2.config, ids2) == ""


def test_corrupt_identities_keeps_discord_off(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "identities.json").write_text("{broken", encoding="utf-8")
    raw ={"data_dir": str(data), "vault": {"mode": "file"}, "llm": {"kind": "fake"},
           "channels": {"discord": {"enabled": True, "bot_token": "vault:discord_bot_token"}}}
    config = SynoxConfig.from_dict(raw, require_token=False, root=str(tmp_path))
    vault = Vault(b"k" * 32, str(data))
    vault.set_secret("discord_bot_token", TOKEN)
    app = build(config, home=FakeChannel(), adapter=FakeAdapter(None), vault=vault)
    assert "壞掉" in app.extras["discord_error"] and app.extras.get("discord_entry") is None
    assert (data / "identities.json").read_text(encoding="utf-8") == "{broken"
    lines = []
    assert dc.pair_owner(app.config, vault, code="123456", out=lines.append,
                         connect=lambda url: FakeWS([hello(), {"op": 0, "t": "MESSAGE_CREATE", "s": 1,
                                                              "d": dm(uid="777", text="123456")["d"]}], Clock()),
                         http=FakeHTTP(), timeout=30) == 2
    assert "壞掉" in lines[-1]
    from synox import doctor
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(raw), encoding="utf-8")
    out = []
    doctor.run(offline=True, config_path=str(cfg_path), out=out.append)
    assert any("身分" in line and "壞掉" in line for line in out)


def test_button_auto_ack(tmp_path):
    app, http, _ = make_discord_bot(tmp_path, owner_discord="777")
    d = {"type": 3, "id": "i9", "token": "t9", "channel_id": "dm-777", "user": {"id": "777"},
         "data": {"custom_id": "nothing:here"}, "message": {"id": "1", "content": ""}}
    app.extras["discord_entry"].on_dispatch("INTERACTION_CREATE", d)
    acks = [u for _, u, _ in http.calls if "/interactions/i9/t9/callback" in u]
    assert len(acks) == 1


def test_notify_routes_by_identity(tmp_path, monkeypatch):
    app, http, home = make_discord_bot(tmp_path, owner_discord="777", telegram=True)
    monkeypatch.setattr(dc, "telegram_api", lambda h: h)          # 假裝原本的 home 是真的 Telegram
    app.notify(BASE + 5, "給 Discord 陌生人")       # 保留號段 → Discord（沒對應 → 不送，不丟例外）
    app.notify(OWNER_ID, "給擁有者")                  # 有 Telegram → 擁有者走 Telegram
    assert [s.text for s in home.sent] == ["給擁有者"]
    assert not http.posted()


def test_notify_discord_only_owner(tmp_path):
    app, http, home = make_discord_bot(tmp_path, owner_discord="777")
    app.notify_owner("排程提醒")
    assert any(u.endswith("/users/@me/channels") for _, u, _ in http.calls)
    assert any((j or {}).get("content") == "排程提醒" for j in http.posted())
    assert not home.sent


def test_on_start_registers_gateway_without_connecting(tmp_path, monkeypatch):
    app, _, _ = make_discord_bot(tmp_path, owner_discord="777")
    started = []
    monkeypatch.setattr("isdtelekit.host.supervisor.SupervisedChannel.start", lambda self: started.append(self.name))
    app.start(())
    assert "discord" in app.hub.names() and started == ["discord"]


def test_pair_owner_binds(tmp_path, monkeypatch):
    app, _, _ = make_discord_bot(tmp_path)
    vault = app.extras["vault"]
    ids = Identities(app.config.path("identities.json"))
    ids.resolve("discord", "777")                    # 之前當陌生人傳過訊息
    script = [hello(), {"op": 0, "t": "MESSAGE_CREATE", "s": 1, "d": dm(uid="777", text="123456")["d"]}]
    clock = Clock()
    http = FakeHTTP()
    lines = []
    rc = dc.pair_owner(app.config, vault, code="123456", out=lines.append,
                       connect=lambda url: FakeWS(list(script), clock), http=http, timeout=30)
    assert rc == 0
    assert Identities(app.config.path("identities.json")).lookup("discord", "777") == app.config.owner_id
    assert any("配對成功" in (j or {}).get("content", "") for j in http.posted())
