"""PERM-3 多 bot Gateway：全部假傳輸（假 Gateway 連線、假 HTTP），不連 Discord、不開埠。"""

import json
import threading

import pytest

from isdtelekit.host.config import ConfigError
from isdtelekit.testing import OWNER_ID, FakeChannel

from synox import discord as dc
from synox.app import build
from synox.config import SynoxConfig
from synox.discord import bots as bot_specs
from synox.discord.gateway import Gateway
from synox.identity import BASE
from synox.llm.fake import FakeAdapter
from synox.vault import Vault

from test_discord import Clock, FakeHTTP, FakeWS, dm, hello

TOK_A, TOK_B, TOK_C = "token.alpha", "token.bravo", "token.charlie"


def two_bots(**extra_bots):
    return {"bots": {"alpha": {"token": "vault:discord_bot_token:alpha", "surface": "dm", "packs": "all", "ai": True},
                     "bravo": {"surface": "dm", "packs": ["notes"]}, **extra_bots}}


def make_app(tmp_path, discord, *, secrets=None, owner_discord="777"):
    data = tmp_path / "data"
    discord = dict(discord)
    if owner_discord:
        discord["owner_user_id"] = owner_discord
    raw = {"data_dir": str(data), "vault": {"mode": "file"}, "llm": {"kind": "fake"},
           "channels": {"discord": discord}}
    config = SynoxConfig.from_dict(raw, require_token=False, root=str(tmp_path))
    vault = Vault(b"k" * 32, str(data))
    for k, v in (secrets if secrets is not None else {"discord_bot_token:alpha": TOK_A,
                                                         "discord_bot_token:bravo": TOK_B}).items():
        vault.set_secret(k, v)
    home = FakeChannel()
    app = build(config, home=home, adapter=FakeAdapter(None), vault=vault)
    http = FakeHTTP()
    for ch in app.extras.get("discord_bots").channels.values():
        ch.http = http                                  # 同一個假 HTTP：看 Authorization 分得出是哪個 bot
    return app, http, home


def auth_by_channel(http):
    """POST /channels/<cid>/messages → 用的 token。"""
    out = {}
    for m, u, kw in http.calls:
        if m == "POST" and u.endswith("/messages"):
            cid = u.split("/channels/")[1].split("/")[0]
            out.setdefault(cid, set()).add(kw["headers"]["Authorization"])
    return out


# ── 設定解析 ─────────────────────────────────────────────────────────

def test_legacy_config_is_default_bot():
    specs = bot_specs.parse({"enabled": True, "bot_token": "vault:discord_bot_token"})
    assert len(specs) == 1
    s = specs[0]
    assert s.name == "default" and s.surface == "dm" and s.packs == "all" and s.legacy
    assert s.hub_name == "discord" and s.vault_name == "discord_bot_token" and s.ai["enabled"]
    assert bot_specs.active({"enabled": False, "bot_token": "x"}) == []
    assert bot_specs.active({}) == []


def test_bots_config_fields_and_defaults():
    d = two_bots(lookup={"token": "vault:discord_bot_token:lookup", "surface": "channel",
                         "guilds": {"1": {"channels": ["2"], "role_map": {"3": "member"}}}, "trigger": "mention",
                         "packs": ["dict", "weather"], "ai": {"enabled": True, "pool_usd_month": 5}, "persona": "p"})
    a, b, c = bot_specs.parse(d)
    assert (a.name, a.hub_name, a.vault_name, a.max_effect) == ("alpha", "discord:alpha", "discord_bot_token:alpha", None)
    assert b.token == "vault:discord_bot_token:bravo" and b.packs == ("notes",)       # 沒寫 token：照名字
    assert c.surface == "channel" and c.max_effect == "read" and c.packs == ("dict", "weather")
    assert c.ai["enabled"] and c.ai["pool_usd_month"] == 5.0 and c.guilds["1"]["channels"] == ["2"]
    assert c.ai_persona == "p" and c.ai_history_turns == 6 and c.ai_rate_per_minute == 2   # PERM-6 的預設
    named_default = bot_specs.parse({"bots": {"default": {}}})[0]
    assert named_default.token == "vault:discord_bot_token" and not named_default.legacy
    assert bot_specs.find([a, b, c], None) is a and bot_specs.find([c, b], None) is b
    off = bot_specs.active({"bots": {"x": {"enabled": False}, "y": {}}})
    assert [s.name for s in off] == ["y"]


@pytest.mark.parametrize("discord, words", [
    ({"bots": {"Bad Name": {}}}, "名字"),
    ({"bots": {"a": {"token": "123.plain.token"}}}, "不要把 token 直接寫"),
    ({"bots": {"a": {"surface": "group"}}}, "surface"),
    ({"bots": {"a": {"surface": "channel", "max_effect": "danger"}}}, "danger"),
    ({"bots": {"a": {"max_effect": "admin"}}}, "max_effect"),
    ({"bots": {"a": {"packs": "dict"}}}, "packs"),
    ({"bots": {"a": {"ai": {"pool_usd_month": -1}}}}, "負"),
    ({"bots": {"a": {"guilds": {"1": {}}}}}, "guilds"),
    ({"bots": {"a": {"tokn": "vault:x"}}}, "不認得"),
    ({"bots": {"a": {"token": "vault:same"}, "b": {"token": "vault:same"}}}, "同一個 token"),
    ({"bot_token": "vault:discord_bot_token", "bots": {"a": {}}}, "擇一"),
    ({"bots": {}}, "至少"),
])
def test_bad_bot_config_is_clear_error(tmp_path, discord, words):
    with pytest.raises(ConfigError) as e:
        SynoxConfig.from_dict({"channels": {"discord": discord}}, require_token=False, root=str(tmp_path))
    assert words in str(e.value)


# ── 兩個 bot 同時收私訊、各自回覆 ─────────────────────────────────────

def test_two_bots_receive_dms_at_once_and_reply_with_own_token(tmp_path):
    app, http, _ = make_app(tmp_path, two_bots())
    entries = app.extras["discord_entries"]
    assert list(entries) == ["alpha", "bravo"]
    barrier = threading.Barrier(2)
    gateways = []

    def run(name, token, channel_id):
        clock = Clock()
        conns = []

        def connect(url):
            if conns:
                gw.stop()
            ws = FakeWS([hello(), dm(uid="777", text="/help", channel=channel_id)], clock)
            conns.append(ws)
            return ws
        gw = Gateway(token, entries[name].on_dispatch, connect=connect, clock=clock, rand=lambda: 0.0)
        gw._stop.wait = lambda t=None: gw._stop.is_set()
        gateways.append((gw, conns))
        barrier.wait(5)
        gw.run_forever()

    threads = [threading.Thread(target=run, args=("alpha", TOK_A, "dmA-777")),
               threading.Thread(target=run, args=("bravo", TOK_B, "dmB-777"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not any(t.is_alive() for t in threads)
    app.tasks.wait(5)
    for gw, conns in gateways:
        assert conns[0].sent[0]["op"] == 2 and conns[0].sent[0]["d"]["token"] in (TOK_A, TOK_B)
    used = auth_by_channel(http)
    assert used["dmA-777"] == {f"Bot {TOK_A}"} and used["dmB-777"] == {f"Bot {TOK_B}"}
    ids = app.extras["identities"]
    assert ids.lookup("discord", "777") == app.config.owner_id          # 同一個 Discord 帳號、同一個內部 id


def test_on_start_registers_one_gateway_per_bot(tmp_path, monkeypatch):
    app, _, _ = make_app(tmp_path, two_bots())
    started = []
    monkeypatch.setattr("isdtelekit.host.supervisor.SupervisedChannel.start", lambda self: started.append(self.name))
    app.start(())
    assert started == ["discord:alpha", "discord:bravo"]
    gw = app.hub.get("discord:bravo")._factory()
    assert isinstance(gw, Gateway) and gw._token == TOK_B and gw.label == "discord:bravo"


def test_legacy_config_still_one_gateway_named_discord(tmp_path, monkeypatch):
    app, http, _ = make_app(tmp_path, {"enabled": True, "bot_token": "vault:discord_bot_token"},
                            secrets={"discord_bot_token": "legacy.token"})
    started = []
    monkeypatch.setattr("isdtelekit.host.supervisor.SupervisedChannel.start", lambda self: started.append(self.name))
    app.start(())
    assert started == ["discord"] and list(app.extras["discord_entries"]) == ["default"]
    app.extras["discord_entry"].on_dispatch("MESSAGE_CREATE", dm(uid="777", channel="dm-777")["d"])
    app.tasks.wait(5)
    assert auth_by_channel(http)["dm-777"] == {"Bot legacy.token"}


# ── 主動通知挑 bot ───────────────────────────────────────────────────

def test_notify_goes_to_bot_last_dmed_else_first(tmp_path):
    app, http, home = make_app(tmp_path, two_bots())
    app.notify_owner("沒私訊過")                           # 沒紀錄 → 第一個私訊型 bot（alpha）
    assert {kw["headers"]["Authorization"] for _, _, kw in http.calls} == {f"Bot {TOK_A}"}
    app.extras["discord_entries"]["bravo"].on_dispatch("MESSAGE_CREATE", dm(uid="777", text="hi", channel="dmB-777")["d"])
    app.tasks.wait(5)
    http.calls.clear()
    out = app.home.send_message(app.config.owner_id, "提醒")
    assert out["ok"] and auth_by_channel(http) == {"dmB-777": {f"Bot {TOK_B}"}}
    assert not home.sent
    # 改那則訊息：用送它的那個 bot（就算之後又私訊了 alpha）
    app.extras["discord_entries"]["alpha"].on_dispatch("MESSAGE_CREATE", dm(uid="777", text="hi", channel="dmA-777")["d"])
    app.tasks.wait(5)
    http.calls.clear()
    app.home.edit_message_text(app.config.owner_id, out["result"]["message_id"], "改過")
    assert [(m, kw["headers"]["Authorization"]) for m, u, kw in http.calls] == [("PATCH", f"Bot {TOK_B}")]
    assert "/channels/dmB-777/" in http.calls[0][1]


def test_last_dm_bot_survives_restart(tmp_path):
    app, _, _ = make_app(tmp_path, two_bots())
    app.extras["discord_entries"]["bravo"].on_dispatch("MESSAGE_CREATE", dm(uid="777", text="hi", channel="dmB-777")["d"])
    app.tasks.wait(5)
    again = dc.DiscordBots(app.config.path("discord_last_bot.json"))
    assert again.last_bot(app.config.owner_id) == "bravo"


def test_stranger_notify_in_reserved_range_uses_their_bot(tmp_path):
    app, http, _ = make_app(tmp_path, two_bots())
    app.extras["discord_entries"]["bravo"].on_dispatch("MESSAGE_CREATE", dm(uid="555", text="hi", channel="dmB-555")["d"])
    app.tasks.wait(5)
    uid = app.extras["identities"].lookup("discord", "555")
    assert uid >= BASE
    http.calls.clear()
    app.notify(uid, "嗨")
    assert set(auth_by_channel(http)) <= {"dmB-555"}
    assert all(kw["headers"]["Authorization"] == f"Bot {TOK_B}" for _, _, kw in http.calls)


# ── 頻道型 bot、缺 token ─────────────────────────────────────────────

def test_channel_bot_without_guilds_is_not_connected(tmp_path, monkeypatch):
    lookup = {"token": "vault:discord_bot_token:lookup", "surface": "channel", "packs": ["dict"]}
    app, _, _ = make_app(tmp_path, two_bots(lookup=lookup),
                         secrets={"discord_bot_token:alpha": TOK_A, "discord_bot_token:bravo": TOK_B,
                                  "discord_bot_token:lookup": TOK_C})
    started = []
    monkeypatch.setattr("isdtelekit.host.supervisor.SupervisedChannel.start", lambda self: started.append(self.name))
    app.start(())
    assert "discord:lookup" not in started and len(started) == 2
    assert "guilds" in app.extras["discord_errors"]["lookup"]           # PERM-5：沒列頻道＝收不到，說原因
    assert app.extras["discord_specs"]["lookup"].max_effect == "read"


def test_channel_only_config_reports_why(tmp_path):
    app, _, _ = make_app(tmp_path, {"bots": {"lookup": {"surface": "channel"}}}, secrets={})
    assert "discord" not in app.extras
    assert "頻道" in app.extras["discord_error"] and "lookup" in app.extras["discord_error"]


def test_missing_token_for_one_bot_keeps_others(tmp_path):
    app, http, _ = make_app(tmp_path, two_bots(), secrets={"discord_bot_token:alpha": TOK_A})
    assert list(app.extras["discord_entries"]) == ["alpha"]
    assert "discord_bot_token:bravo" in app.extras["discord_errors"]["bravo"]
    assert app.extras["discord"] is app.extras["discord_bots"].channels["alpha"]


# ── CLI、doctor ──────────────────────────────────────────────────────

def _config_file(tmp_path, discord):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"data_dir": str(tmp_path / "data"), "vault": {"mode": "file"},
                               "channels": {"discord": discord}}), encoding="utf-8")
    return str(cfg)


def _vault(tmp_path):
    from synox.vault.keyring import read_key
    return Vault(read_key(str(tmp_path / "data" / ".synox.key")), str(tmp_path / "data"))


def test_cli_token_with_bot_and_legacy(tmp_path, monkeypatch, capsys):
    from synox.__main__ import main
    cfg = _config_file(tmp_path, two_bots())
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "  pasted.bravo  ")
    assert main(["--config", cfg, "discord", "token", "--bot", "bravo"]) == 0
    assert _vault(tmp_path).secret("discord_bot_token:bravo") == "pasted.bravo"
    assert main(["--config", cfg, "discord", "token"]) == 2                     # 多 bot 寫法要指定 --bot
    assert "--bot" in capsys.readouterr().out
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    cfg2 = _config_file(legacy, {"enabled": True, "bot_token": "vault:discord_bot_token"})
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "pasted.legacy")
    assert main(["--config", cfg2, "discord", "token"]) == 0
    assert _vault(legacy).secret("discord_bot_token") == "pasted.legacy"


def test_cli_token_clear(tmp_path, monkeypatch, capsys):
    from synox.__main__ import main
    cfg = _config_file(tmp_path, two_bots())
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "pasted.bravo")
    assert main(["--config", cfg, "discord", "token", "--bot", "bravo"]) == 0
    assert main(["--config", cfg, "discord", "token", "--bot", "alpha"]) == 0
    capsys.readouterr()
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("--clear 不該問 token"))
    assert main(["--config", cfg, "discord", "token", "--bot", "bravo", "--clear"]) == 0
    out = capsys.readouterr().out
    assert "刪掉" in out and "Reset Token" in out and "pasted.bravo" not in out
    assert _vault(tmp_path).secret("discord_bot_token:bravo") is None
    assert _vault(tmp_path).secret("discord_bot_token:alpha") == "pasted.bravo"     # 別的 bot 不動
    assert main(["--config", cfg, "discord", "token", "--bot", "bravo", "--clear"]) == 0
    assert "本來就沒有" in capsys.readouterr().out
    assert main(["--config", cfg, "discord", "token", "--clear"]) == 2               # 多 bot 寫法要指定 --bot
    assert main(["--config", cfg, "discord", "pair", "--clear"]) == 2
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    cfg2 = _config_file(legacy, {"enabled": True, "bot_token": "vault:discord_bot_token"})
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "pasted.legacy")
    assert main(["--config", cfg2, "discord", "token"]) == 0
    assert main(["--config", cfg2, "discord", "token", "--clear"]) == 0
    assert _vault(legacy).secret("discord_bot_token") is None


def test_pair_with_bot_uses_that_token(tmp_path):
    app, _, _ = make_app(tmp_path, two_bots(), owner_discord=None)
    seen = []
    clock = Clock()
    script = [hello(), {"op": 0, "t": "MESSAGE_CREATE", "s": 1, "d": dm(uid="888", text="123456")["d"]}]

    def connect(url):
        ws = FakeWS(list(script), clock)
        orig = ws.send
        ws.send = lambda text: (seen.append(json.loads(text)), orig(text))
        return ws
    rc = dc.pair_owner(app.config, app.extras["vault"], code="123456", out=lambda s: None, bot="bravo",
                       connect=connect, http=FakeHTTP(), timeout=30)
    assert rc == 0 and seen[0]["d"]["token"] == TOK_B
    assert app.extras["identities"].__class__(app.config.path("identities.json")).lookup("discord", "888") == \
        app.config.owner_id
    assert dc.pair_owner(app.config, app.extras["vault"], bot="nope", out=lambda s: None) == 2


def test_doctor_lists_each_bot(tmp_path):
    from synox import doctor
    lookup = {"surface": "channel", "packs": ["dict"]}
    cfg = _config_file(tmp_path, two_bots(lookup=lookup))
    data = tmp_path / "data"
    data.mkdir()
    from synox.vault.keyring import write_key
    write_key(str(data / ".synox.key"), b"k" * 32, "file")
    Vault(b"k" * 32, str(data)).set_secret("discord_bot_token:alpha", TOK_A)
    lines = []
    doctor.run(offline=True, config_path=cfg, out=lines.append)
    text = "\n".join(lines)
    assert "3 個 bot" in text
    assert any("bot alpha" in l and "✅" in l for l in lines)
    assert any("bot bravo" in l and "discord_bot_token:bravo" in l and "--bot bravo" in l for l in lines)
    assert any("bot lookup" in l and "頻道型" in l and "guilds" in l for l in lines)      # 沒列頻道
    assert TOK_A not in text
