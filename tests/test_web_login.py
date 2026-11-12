"""沒接 Telegram 的擁有者回到網頁介面的路：`python -m synox web-login`（Open-SYNOX.bat、桌面捷徑），
以及只跑網頁時 `synox run` 什麼時候打開瀏覽器、網頁開不起來時要停下來。"""

import argparse
import os

from synox.config import SynoxConfig
from synox.web.tokens import LoginTokens
from synox.wizard import logic, shortcuts

import synox.__main__ as cli


def write_skip_config(tmp_path, **web):
    cfg = logic.build_config("", logic.local_owner_id(), {"kind": "none"})
    cfg["vault"] = {"mode": "file"}
    cfg["web"] = {"enabled": True, "port": 8842, **web}
    path = tmp_path / "config.json"
    logic.write_config(str(path), cfg)
    return str(path)


def args_for(path):
    return argparse.Namespace(config=path)


def test_web_login_issues_an_owner_link_when_synox_is_running(tmp_path):
    path = write_skip_config(tmp_path)
    opened, started = [], []
    rc = cli.cmd_web_login(args_for(path), is_up=lambda port: port == 8842, running=lambda c: True,
                           start=started.append, open_url=opened.append, sleep=lambda s: None)
    assert rc == 0 and not started and len(opened) == 1
    assert opened[0].startswith("http://127.0.0.1:8842/login?t=")
    token = opened[0].split("t=", 1)[1]
    assert LoginTokens(str(tmp_path / "data" / "web_tokens.json")).peek(token) == logic.local_owner_id()


def test_web_login_starts_synox_first_and_waits_for_the_web_ui(tmp_path, monkeypatch):
    path = write_skip_config(tmp_path)
    monkeypatch.setattr(cli, "CONFIG_PATH", path)               # 預設那份 config 才幫忙開 Start.bat
    state = {"up": False, "polls": 0}
    started, opened = [], []

    def start(root):
        started.append(root)

    def sleep(_s):
        state["polls"] += 1
        state["up"] = state["polls"] >= 3 and bool(started)

    rc = cli.cmd_web_login(args_for(path), is_up=lambda port: state["up"], running=lambda c: state["up"],
                           start=start, open_url=opened.append, sleep=sleep)
    assert rc == 0 and len(started) == 1 and len(opened) == 1


def test_web_login_gives_up_without_opening_a_link_to_nowhere(tmp_path):
    path = write_skip_config(tmp_path)
    opened = []
    rc = cli.cmd_web_login(args_for(path), is_up=lambda port: False, running=lambda c: True,
                           start=lambda root: None, open_url=opened.append, sleep=lambda s: None)
    assert rc == 2 and not opened


def test_web_login_refuses_when_web_is_off(tmp_path):
    path = write_skip_config(tmp_path, enabled=False)
    assert cli.cmd_web_login(args_for(path), is_up=lambda p: True, running=lambda c: True,
                             open_url=lambda u: None, sleep=lambda s: None) == 2


def test_web_login_is_a_cli_command(capsys):
    import pytest
    with pytest.raises(SystemExit) as e:
        cli.main(["web-login", "--help"])
    assert e.value.code == 0 and "web-login" in capsys.readouterr().out


def test_wants_browser_respects_flag_and_env(monkeypatch):
    monkeypatch.delenv("SYNOX_NO_BROWSER", raising=False)
    assert cli._wants_browser(argparse.Namespace(no_browser=False))
    assert not cli._wants_browser(argparse.Namespace(no_browser=True))
    monkeypatch.setenv("SYNOX_NO_BROWSER", "1")
    assert not cli._wants_browser(argparse.Namespace(no_browser=False))


class FakeUI:
    def __init__(self, running, error=""):
        self.running, self.error = running, error
        self.issued = []

    def login_link(self, tg_id):
        self.issued.append(tg_id)
        return f"http://127.0.0.1:8842/login?t=x{tg_id}"


class FakeApp:
    def __init__(self, ui):
        self.extras = {"synox_web": ui}
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_web_only_stops_when_the_web_ui_did_not_start(tmp_path, capsys):
    config = SynoxConfig.load(write_skip_config(tmp_path), require_token=False)
    app, failed = FakeApp(FakeUI(False, "網頁介面開不起來：127.0.0.1:8842 不能用")), []
    cli._web_only_started(app, config, failed)
    assert failed and app.stopped and not app.extras["synox_web"].issued
    assert "8842" in capsys.readouterr().out


def test_web_only_opens_the_owner_link_only_when_asked(tmp_path, monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    config = SynoxConfig.load(write_skip_config(tmp_path), require_token=False)
    ui = FakeUI(True)
    cli._web_only_started(FakeApp(ui), config, [], open_browser=False)
    assert not ui.issued
    cli._web_only_started(FakeApp(ui), config, [], open_browser=True)
    assert ui.issued == [logic.local_owner_id()]


def test_desktop_shortcut_target_runs_web_login():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.exists(os.path.join(root, shortcuts.OPEN_BAT))
    bat = open(os.path.join(root, shortcuts.OPEN_BAT), "rb").read()
    bat.decode("ascii")
    assert b"\r\n" in bat and b"-m synox web-login" in bat
