"""設定頁的「聊天通道」：擁有者在網頁補 Telegram／Discord 的 token（假的 probe，不連網）。"""

import json
import logging

from isdtelekit.users.roles import BasicRoles

from synox.__main__ import run_channels
from synox.config import SynoxConfig
from synox.identity import BASE
from synox.wizard import discord_probe, telegram_probe

from conftest import OTHER_ID
from test_web import Client, ui_of

TG_TOKEN = "123456789:" + "S" * 35
DC_TOKEN = "Dsecret" + "q" * 40
BOT_ID = "424242424242"


class FakeTelegram:
    valid_token = staticmethod(telegram_probe.valid_token)
    calls = []

    @classmethod
    def get_me(cls, token):
        cls.calls.append(token)
        if not cls.valid_token(token):
            return False, "這看起來不是 token（長得像 123456789:AAH…，中間有冒號）。"
        if token != TG_TOKEN:
            return False, "token 不對（Telegram 說 401）：再到 @BotFather 複製一次。"
        return True, "my_synox_bot"


class FakeDiscord:
    valid_token = staticmethod(discord_probe.valid_token)
    invite_url = staticmethod(discord_probe.invite_url)
    calls = []

    @classmethod
    def get_me(cls, token):
        cls.calls.append(token)
        if token != DC_TOKEN:
            return False, f"token 不對（Discord 說 401）：{token}"     # 故意把 token 放進錯誤：要被遮掉
        return True, "SynoxDiscord"

    @classmethod
    def bot_id(cls, token):
        return BOT_ID if token == DC_TOKEN else None


def _setup(make_bot, tmp_path, owner_id, extra=None, mode="personal"):
    """寫一份真的 config.json（像精靈寫的）並用同一個 owner 開 bot；回 (bot, 擁有者的 Client, config.json 路徑)。"""
    path = tmp_path / "config.json"
    raw = {"mode": mode, "bot_token": "", "owner_id": owner_id, "data_dir": str(tmp_path / "data"),
           "vault": {"mode": "file"}, "llm": {"kind": "fake"}, **(extra or {})}
    path.write_text(json.dumps(raw), encoding="utf-8")
    bot = make_bot(raw={k: v for k, v in raw.items() if k not in ("data_dir", "llm", "vault")})
    ui = ui_of(bot)
    FakeTelegram.calls, FakeDiscord.calls = [], []
    ui.channel_probes = (FakeTelegram, FakeDiscord)
    c = Client(ui)
    c.login(owner_id)
    return bot, c, path


def _raw_post(c, path, data):
    status, _h, body = c.raw("POST", path, json.dumps(data).encode("utf-8"))
    return status, body.decode("utf-8")


def test_channels_are_owner_only(make_bot, tmp_path, owner):
    bot, _c, path = _setup(make_bot, tmp_path, owner, mode="server")
    before = path.read_text(encoding="utf-8")
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui_of(bot))
    m.login(OTHER_ID)
    assert m.get("/api/settings/channels")[0] == 403
    assert m.post("/api/settings/channels/telegram", {"token": TG_TOKEN})[0] == 403
    assert m.post("/api/settings/channels/discord", {"token": DC_TOKEN})[0] == 403
    assert FakeTelegram.calls == [] and FakeDiscord.calls == []
    assert path.read_text(encoding="utf-8") == before
    no_csrf = Client(ui_of(bot))                       # 擁有者也要帶 CSRF
    no_csrf.login(owner)
    no_csrf.csrf = ""
    assert no_csrf.post("/api/settings/channels/telegram", {"token": TG_TOKEN})[0] == 403


def test_telegram_invalid_token_is_rejected(make_bot, tmp_path, owner):
    _bot, c, path = _setup(make_bot, tmp_path, owner)
    before = path.read_text(encoding="utf-8")
    status, data = c.post("/api/settings/channels/telegram", {"token": "not-a-token"})
    assert status == 400 and "不是 token" in data["error"]
    status, data = c.post("/api/settings/channels/telegram", {"token": "123456789:" + "W" * 35})
    assert status == 400 and "401" in data["error"]
    assert c.post("/api/settings/channels/telegram", {"token": ""})[0] == 400
    assert path.read_text(encoding="utf-8") == before


def test_telegram_token_saved_with_placeholder_owner_still_starts(make_bot, tmp_path, caplog):
    """跳過 bot 步驟的安裝（owner_id＝本機保留號）補 Telegram token：owner_id 不動，啟動照樣過。"""
    caplog.set_level(logging.DEBUG)
    _bot, c, path = _setup(make_bot, tmp_path, BASE)
    status, body = _raw_post(c, "/api/settings/channels/telegram", {"token": "  " + TG_TOKEN + " "})
    assert status == 200, body
    data = json.loads(body)
    assert data["bot"] == "my_synox_bot" and "重新啟動" in data["message"] and "配對我的 Telegram 帳號" in data["message"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["bot_token"] == TG_TOKEN and saved["owner_id"] == BASE
    config = SynoxConfig.load(str(path), require_token=False)
    assert config.has_token and config.owner_id == BASE
    assert run_channels(config) == ("telegram",)

    status, _h, raw = c.raw("GET", "/api/settings/channels")
    body2 = raw.decode("utf-8")
    assert status == 200
    tg = json.loads(body2)["telegram"]
    assert tg["saved"] and tg["bot"] == "my_synox_bot" and not tg["owner_paired"] and tg["restart"]
    for text in (body, body2, caplog.text):
        assert TG_TOKEN not in text and "S" * 35 not in text


def test_telegram_token_with_real_owner_mentions_web_command(make_bot, tmp_path, owner):
    _bot, c, path = _setup(make_bot, tmp_path, owner)
    status, data = c.post("/api/settings/channels/telegram", {"token": TG_TOKEN})
    assert status == 200 and "/web" in data["message"]
    assert json.loads(path.read_text(encoding="utf-8"))["owner_id"] == owner


def test_discord_token_saved_to_vault_with_invite(make_bot, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    bot, c, path = _setup(make_bot, tmp_path, BASE)
    status, data = c.get("/api/settings/channels")
    assert status == 200 and data["discord"]["saved"] is False and data["telegram"]["saved"] is False
    status, body = _raw_post(c, "/api/settings/channels/discord", {"token": DC_TOKEN})
    assert status == 200, body
    data = json.loads(body)
    assert data["invite"] == discord_probe.invite_url(BOT_ID) and "discord pair" in data["message"]
    text = path.read_text(encoding="utf-8")
    assert DC_TOKEN not in text
    saved = json.loads(text)
    assert saved["channels"]["discord"] == {"enabled": True, "bot_token": "vault:discord_bot_token"}
    assert ui_of(bot).vault.secret("discord_bot_token") == DC_TOKEN
    config = SynoxConfig.load(str(path), require_token=False)
    assert config.discord_enabled and run_channels(config) == ()

    body2 = c.raw("GET", "/api/settings/channels")[2].decode()
    dc = json.loads(body2)["discord"]
    assert dc["saved"] and dc["bot"] == "SynoxDiscord" and dc["invite"].endswith(BOT_ID + "&scope=bot&permissions=2048")
    assert dc["restart"] and not dc["owner_paired"]
    for t in (body, body2, caplog.text):
        assert DC_TOKEN not in t


def test_discord_invalid_token_is_rejected_and_scrubbed(make_bot, tmp_path, owner):
    bot, c, path = _setup(make_bot, tmp_path, owner)
    before = path.read_text(encoding="utf-8")
    bad = "Wrong" + "z" * 40
    status, body = _raw_post(c, "/api/settings/channels/discord", {"token": bad})
    assert status == 400 and "401" in body and bad not in body
    assert path.read_text(encoding="utf-8") == before
    assert ui_of(bot).vault.secret("discord_bot_token") in (None, "")


def test_discord_refuses_multi_bot_config(make_bot, tmp_path, owner):
    bots = {"channels": {"discord": {"bots": {"default": {"surface": "dm", "token": "vault:discord_bot_token"}}}}}
    bot, c, path = _setup(make_bot, tmp_path, owner, extra=bots)
    vault = ui_of(bot).vault
    vault.set_secret("discord_bot_token", "the-old-default-bot-token")
    before = path.read_text(encoding="utf-8")
    status, body = _raw_post(c, "/api/settings/channels/discord", {"token": DC_TOKEN})
    assert status == 400 and "bots" in json.loads(body)["error"] and DC_TOKEN not in body
    assert FakeDiscord.calls == []                     # 先拒絕，不連 Discord
    assert path.read_text(encoding="utf-8") == before
    assert vault.secret("discord_bot_token") == "the-old-default-bot-token"
    status, data = c.get("/api/settings/channels")
    assert status == 200 and data["discord"]["multi"] is True and data["discord"]["saved"] is False
