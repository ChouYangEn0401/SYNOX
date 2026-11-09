"""精靈不用畫面的那一半（不需要螢幕、不連網：requests 換成假的）。"""

import json
import threading

import pytest

from synox.wizard import logic, shortcuts, telegram_probe

TOKEN = "123456789:" + "A" * 35


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
    assert SynoxConfig.load(str(path)).llm["kind"] == "openai_compat"


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
