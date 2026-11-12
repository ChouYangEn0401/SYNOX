"""精靈不用畫面的那一半（不需要螢幕、不連網：requests 換成假的）。"""

import json
import threading

import pytest

from synox.wizard import discord_probe, logic, shortcuts, telegram_probe

TOKEN = "123456789:" + "A" * 35
DTOKEN = "D" * 30


class FakeDiscordResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        return self._body


class FakeDiscordHttp:
    def __init__(self, handler):
        self.handler = handler

    def request(self, method, url, **kw):
        return self.handler(method, url, kw)


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


class FakeHttp:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json))
        return self.handler(method, json or {})


def test_pages_module_imports():
    import synox.wizard.pages as pages
    assert callable(pages.main) and pages.Wizard


def test_token_validation():
    assert telegram_probe.valid_token(TOKEN)
    assert telegram_probe.valid_token("  " + TOKEN + " ")
    for bad in ("", "abc", "123:short", "12345678" + "A" * 35, "123456789:" + "A" * 10 + " " + "A" * 25):
        assert not telegram_probe.valid_token(bad)


def test_pairing_code():
    codes = {telegram_probe.new_pairing_code() for _ in range(50)}
    assert all(len(c) == 6 and c.isdigit() for c in codes) and len(codes) > 40


def test_get_me():
    http = FakeHttp(lambda m, p: FakeResp({"ok": True, "result": {"username": "my_test_bot"}}))
    assert telegram_probe.get_me(TOKEN, http=http) == (True, "my_test_bot")
    http = FakeHttp(lambda m, p: FakeResp({"ok": False, "error_code": 401, "description": "Unauthorized"}, 401))
    ok, msg = telegram_probe.get_me(TOKEN, http=http)
    assert not ok and "401" in msg
    assert telegram_probe.get_me("nope", http=http)[0] is False


def test_wait_for_code():
    batches = [
        [{"update_id": 5, "message": {"text": "old", "chat": {"type": "private"}, "from": {"id": 1}}}],   # backlog
        [{"update_id": 6, "message": {"text": "hello", "chat": {"type": "private"}, "from": {"id": 2}}},
         {"update_id": 7, "message": {"text": "042 917", "chat": {"type": "group"}, "from": {"id": 3}}},
         {"update_id": 8, "message": {"text": "042917", "chat": {"type": "private"},
                                      "from": {"id": 4242, "username": "friend", "first_name": "F"}}}],
    ]

    def handler(method, params):
        if method == "getUpdates" and params.get("timeout", 0) == 0 and "offset" in params and params["offset"] != -1:
            return FakeResp({"ok": True, "result": []})            # 確認掉
        if method == "getUpdates":
            return FakeResp({"ok": True, "result": batches.pop(0) if batches else []})
        return FakeResp({"ok": True, "result": {}})

    http = FakeHttp(handler)
    who = telegram_probe.wait_for_code(TOKEN, "042917", http=http, poll=1)
    assert who == {"id": 4242, "username": "friend", "first_name": "F"}
    methods = [m for m, _p in http.calls]
    assert methods[0] == "getUpdates" and http.calls[0][1]["offset"] == -1
    assert http.calls[1][1]["offset"] == 6                          # backlog 跳過
    assert ("getUpdates", {"offset": 9, "timeout": 0}) in http.calls
    assert methods[-1] == "sendMessage" and http.calls[-1][1]["chat_id"] == 4242


def test_wait_for_code_stops():
    stop = threading.Event()
    stop.set()
    http = FakeHttp(lambda m, p: FakeResp({"ok": True, "result": []}))
    assert telegram_probe.wait_for_code(TOKEN, "000000", http=http, stop=stop) is None


def test_llm_settings():
    llm, err = logic.llm_settings("friend", base_url="https://gw.example.com/v1", api_key="k", model="m")
    assert not err and llm["kind"] == "openai_compat" and llm["base_url"] == "https://gw.example.com/v1"
    assert logic.llm_settings("friend", base_url="gw", model="m")[1]
    llm, err = logic.llm_settings("own", provider="anthropic", api_key="k")
    assert llm["kind"] == "anthropic" and llm["model"]
    assert logic.llm_settings("own", provider="openai")[1]          # 沒有 key
    assert logic.llm_settings("none")[0] == {"kind": "none"}
    assert logic.llm_settings("claude_code")[0]["kind"] == "claude_code"


def test_ai_page_helpers():
    assert logic.CLAUDE_TITLE.startswith("預設：Claude")
    assert list(logic.KEY_PROVIDERS) == ["openai", "anthropic", "gemini", "openai_compat"]
    assert logic.provider_labels()[-1].startswith("相容端點")
    assert logic.provider_by_label("Gemini") == "gemini" and logic.provider_by_label("???") == "openai"
    assert logic.default_model("gemini") and logic.default_model("openai") and logic.default_model("x") == ""
    assert logic.needs_base_url("openai_compat") and not logic.needs_base_url("anthropic")
    found, text = logic.claude_status(lambda: "/usr/local/bin/claude")
    assert found and "/usr/local/bin/claude" in text and logic.default_choice(found) == "claude_code"
    found, text = logic.claude_status(lambda: None)
    assert not found and "找不到" in text and logic.default_choice(found) == "keys"


def test_ai_page_settings_per_provider():
    llm, err = logic.llm_settings("keys", provider="gemini", api_key="g")
    assert not err and llm == {"kind": "gemini", "api_key": "g", "model": logic.default_model("gemini")}
    llm, err = logic.llm_settings("keys", provider="openai_compat", base_url="http://localhost:11434/v1",
                                  model="qwen2.5")
    assert not err and llm["kind"] == "openai_compat" and llm["api_key"] == "" and llm["tools"] is True
    assert "網址" in logic.llm_settings("keys", provider="openai_compat", base_url="localhost", model="m")[1]
    assert "模型" in logic.llm_settings("keys", provider="openai_compat", base_url="http://x/v1")[1]
    assert "API key" in logic.llm_settings("keys", provider="anthropic")[1]
    assert logic.llm_settings("keys", provider="openai", api_key="k", model=" my-model ")[0]["model"] == "my-model"


def test_probe_llm_uses_adapter_probe():
    class A:
        def __init__(self, err):
            self.err = err

        def probe(self):
            return self.err

    assert logic.probe_llm({"kind": "none"}) is None
    assert logic.probe_llm({"kind": "openai"}, make=lambda c: A(None)) is None
    assert logic.probe_llm({"kind": "openai"}, make=lambda c: A("金鑰不對（401）")) == "金鑰不對（401）"
    assert logic.probe_llm({"kind": "x"}, make=lambda c: None) == "不認得的 AI 來源。"

    def boom(c):
        from synox.llm.base import LLMError
        raise LLMError("還沒安裝 ntu_easy_llm：…")
    assert logic.probe_llm({"kind": "openai"}, make=boom).startswith("還沒安裝 ntu_easy_llm")
    # 真的 make_adapter：相容端點沒填網址 → 中文錯誤，不丟例外
    assert "網址" in logic.probe_llm({"kind": "openai_compat", "model": "m", "base_url": ""})


def test_mode_page_and_build_config():
    assert list(logic.MODE_CHOICES) == ["personal", "server"]
    title, one, two = logic.mode_lines("server")
    assert "伺服器版" in title and one and two
    assert "config.json" in logic.ENGINEER_HINT and "config.example.json" in logic.ENGINEER_HINT
    cfg = logic.build_config(TOKEN, 1, {"kind": "none"}, mode="server")
    assert cfg["mode"] == "server"
    assert logic.build_config(TOKEN, 1, {"kind": "none"}, existing={"mode": "server"})["mode"] == "server"
    assert logic.build_config(TOKEN, 1, {"kind": "none"})["mode"] == "personal"
    with pytest.raises(ValueError):
        logic.build_config(TOKEN, 1, {"kind": "none"}, mode="cloud")


def test_save_config_moves_key_to_vault(tmp_path):
    stored = {}

    class V:
        def set_secret(self, name, value):
            stored[name] = value

    llm, _ = logic.llm_settings("own", provider="openai", api_key="sk-secret", model="m")
    cfg = logic.build_config(TOKEN, 4242, llm, existing={"packs": {"enabled": "all", "disabled": ["x"]}})
    path = tmp_path / "config.json"
    logic.save(str(path), cfg, vault_opener=lambda c: V())
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["llm"]["api_key"] == "vault:llm_api_key" and stored == {"llm_api_key": "sk-secret"}
    assert "sk-secret" not in path.read_text(encoding="utf-8")
    assert data["owner_id"] == 4242 and data["packs"]["disabled"] == ["x"] and data["llm"]["max_steps"] == 6
    from synox.config import SynoxConfig
    assert SynoxConfig.load(str(path)).llm["kind"] == "openai" and data["mode"] == "personal"


def test_save_config_real_vault(tmp_path):
    from synox.llm.factory import resolve_secret
    from synox.config import SynoxConfig
    from synox.vault import open_vault
    llm, _ = logic.llm_settings("friend", base_url="https://gw.example.com/v1", api_key="k-1", model="m")
    cfg = logic.build_config(TOKEN, 1, llm)
    cfg["vault"] = {"mode": "file"}
    logic.save(str(tmp_path / "config.json"), cfg)
    config = SynoxConfig.load(str(tmp_path / "config.json"))
    assert resolve_secret(config.llm["api_key"], open_vault(config)) == "k-1"


def test_startup_cmd_text():
    text = shortcuts.startup_cmd_text(r"C:\Apps\SYNOX")
    text.encode("ascii")
    assert text.count("\r\n") == 4 and "\n" not in text.replace("\r\n", "")
    assert 'call "C:\\Apps\\SYNOX\\Start.bat"' in text
    with pytest.raises(ValueError):
        shortcuts.startup_cmd_text("C:\\使用者\\SYNOX")


def test_enable_autostart_writes_cmd(tmp_path):
    path = shortcuts.enable_autostart(r"C:\Apps\SYNOX", folder=str(tmp_path))
    assert path.endswith("SYNOX.cmd") and open(path, "rb").read().startswith(b"@echo off\r\n")
    shortcuts.disable_autostart(folder=str(tmp_path))
    assert not (tmp_path / "SYNOX.cmd").exists()


def test_shortcut_script():
    script = shortcuts.shortcut_script(r"C:\Users\x\Desktop\SYNOX.lnk", r"C:\it's\Start.bat", r"C:\it's")
    assert "WScript.Shell" in script and "'C:\\it''s\\Start.bat'" in script and "$s.Save()" in script


def test_skip_channel_builds_config_without_token_or_owner(tmp_path):
    """精靈「先跳過」：沒有 bot_token、owner_id 預設 0，不會丟例外，也不會開 Start.bat（由畫面層的 self.token 判斷）。"""
    cfg = logic.build_config("", 0, {"kind": "none"})
    path = tmp_path / "config.json"
    logic.save(str(path), cfg)
    from synox.config import SynoxConfig
    config = SynoxConfig.load(str(path), require_token=False)
    assert config.owner_id == 0 and not config.has_token and not config.discord_enabled


def test_discord_token_validation():
    assert discord_probe.valid_token(DTOKEN)
    assert discord_probe.valid_token("  " + DTOKEN + " ")
    for bad in ("", "short", "with space " * 3):
        assert not discord_probe.valid_token(bad)


def test_discord_get_me_and_bot_id():
    http = FakeDiscordHttp(lambda m, u, kw: FakeDiscordResp(200, {"id": "999", "username": "my_discord_bot"}))
    assert discord_probe.get_me(DTOKEN, http=http) == (True, "my_discord_bot")
    assert discord_probe.bot_id(DTOKEN, http=http) == "999"
    http = FakeDiscordHttp(lambda m, u, kw: FakeDiscordResp(401, {"message": "Unauthorized"}))
    ok, msg = discord_probe.get_me(DTOKEN, http=http)
    assert not ok and "401" in msg
    assert discord_probe.get_me("nope")[0] is False


def test_discord_invite_url():
    assert discord_probe.invite_url("123") == (
        "https://discord.com/oauth2/authorize?client_id=123&scope=bot&permissions=2048")


def test_save_discord_token_and_bind_owner(tmp_path):
    from synox.config import SynoxConfig
    from synox.identity import BASE
    from synox.vault import open_vault
    path = tmp_path / "config.json"
    owner_id = logic.discord_owner_sentinel()
    assert owner_id == BASE
    cfg = logic.build_config("", owner_id, {"kind": "none"})
    cfg = logic.save(str(path), cfg)
    cfg = logic.save_discord_token(str(path), cfg, "  " + DTOKEN + "  ")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["channels"]["discord"] == {"enabled": True, "bot_token": "vault:discord_bot_token"}
    assert DTOKEN not in path.read_text(encoding="utf-8")
    config = SynoxConfig.load(str(path), require_token=False)
    assert open_vault(config).secret("discord_bot_token") == DTOKEN
    assert config.discord_enabled and not config.has_token

    logic.bind_discord_owner(str(path), cfg, "80351110224678912")
    from synox.identity import Identities
    ids = Identities(config.path("identities.json"))
    assert ids.lookup("discord", "80351110224678912") == owner_id


def test_finish_page_web_link(tmp_path):
    from synox.web.tokens import LoginTokens
    path = tmp_path / "config.json"
    logic.write_config(str(path), {"owner_id": 42, "llm": {"kind": "none"}, "vault": {"mode": "file"}})
    link = logic.web_login_link(str(path))
    assert link.startswith("http://127.0.0.1:8830/login?t=")
    token = link.split("t=", 1)[1]
    assert LoginTokens(str(tmp_path / "data" / "web_tokens.json")).redeem(token) == 42
    logic.write_config(str(path), {"owner_id": 42, "web": {"enabled": False}})
    assert logic.web_login_link(str(path)) == ""
