"""SYNOX 的終端機門面（src/synox/brand.py）：歡迎畫面什麼時候印、印成什麼樣子，`synox open`／`about`／`tips`。
全部用假的終端機、假的瀏覽器與假的啟動：不開瀏覽器、不開 SYNOX、不開埠。"""

import argparse
import io
import os
import random
import re
import sys
from datetime import datetime

import pytest

import synox.__main__ as cli
from synox import brand
from synox.wizard import logic

NOON = datetime(2026, 11, 12, 13, 0)
TTY_ENV = {"TERM": "xterm-256color"}          # 乾淨的環境：不吃跑測試那台機器的 NO_COLOR／CI／WT_SESSION


class FakeTerminal(io.StringIO):
    """假的終端機：isatty 可以設；encoding 可以設成 cp950 這類（寫不出去的字照真的 stream 一樣丟 UnicodeEncodeError）。"""

    def __init__(self, tty=True, encoding="utf-8"):
        super().__init__()
        self._tty, self._encoding = tty, encoding

    @property
    def encoding(self):
        return self._encoding

    def isatty(self):
        return self._tty

    def write(self, text):
        text.encode(self._encoding)               # strict：跟沒設 errors=replace 的主控台一樣
        return super().write(text)


def plain(text):
    return re.sub(r"\[[0-9;]*m", "", text)


def show(stream, command=None, env=None, **kw):
    kw.setdefault("codepage", 65001)
    kw.setdefault("enable_vt", lambda s: True)
    return brand.show_banner(command, stream=stream, env=TTY_ENV if env is None else env, now=NOON,
                             rng=random.Random(1), **kw)


# ---------------------------------------------------------------- 什麼時候印

def test_full_banner_on_an_interactive_terminal():
    out = FakeTerminal()
    text = show(out, None)
    assert text and out.getvalue() == text
    assert "Welcome to SYNOX" in text and f"v{brand.version()}" in text
    assert "███████╗" in plain(text)                            # UTF-8 終端機：方塊字 logo
    assert "\x1b[" in text                                      # 有上色
    assert "open" in text and "doctor" in text and "--help" in text
    assert "午安" in text                                       # 照 ISDPCS 的時段問候


@pytest.mark.parametrize("env", [{"SYNOX_NO_BANNER": "1"}, {"CI": "true"}])
def test_banner_is_off_when_asked_or_in_ci(env):
    out = FakeTerminal()
    assert show(out, "run", env={**TTY_ENV, **env}) == "" and out.getvalue() == ""


def test_banner_is_off_with_quiet():
    out = FakeTerminal()
    assert show(out, "run", quiet=True) == "" and out.getvalue() == ""


def test_banner_is_off_when_output_is_not_a_terminal():
    out = FakeTerminal(tty=False)                               # 管線、重導向
    assert show(out, None) == "" and out.getvalue() == ""


def test_dumb_terminal_gets_one_plain_line():
    out = FakeTerminal()
    text = show(out, "open", env={"TERM": "dumb"})
    assert text.count("\n") == 1 and "Welcome to SYNOX" in text and "\x1b[" not in text


def test_no_color_keeps_the_layout_but_drops_ansi():
    out = FakeTerminal()
    text = show(out, None, env={**TTY_ENV, "NO_COLOR": "1"})
    assert "Welcome to SYNOX" in text and "███████╗" in text and "\x1b[" not in text


def test_no_color_when_the_console_cannot_do_ansi():
    out = FakeTerminal()
    text = show(out, None, enable_vt=lambda s: False)
    assert "Welcome to SYNOX" in text and "\x1b[" not in text


def test_banner_never_breaks_the_command():
    class Broken(FakeTerminal):
        def write(self, text):
            raise OSError("console went away")
    assert show(Broken(), None) == ""


# ---------------------------------------------------------------- cp950、ASCII

def test_cp950_console_codepage_falls_back_to_ascii():
    out = FakeTerminal()                                        # stream 是 UTF-8，但主控台 code page 是 950
    text = show(out, None, codepage=950)
    assert "Welcome to SYNOX" in text and "(O,O)" in text
    assert "█" not in text and "🌞" not in text and "─" not in text


def test_cp950_stream_does_not_crash_and_uses_ascii():
    out = FakeTerminal(encoding="cp950")                        # 沒有 reconfigure 成 UTF-8 的 cp950 主控台
    text = show(out, None, codepage=None)
    assert text and "Welcome to SYNOX" in out.getvalue() and "█" not in text


def test_ascii_stream_still_prints_something():
    out = FakeTerminal(encoding="ascii")                        # 連中文都編不了：用 ? 代替，不丟例外
    text = show(out, None)
    assert "Welcome to SYNOX" in out.getvalue() and text


def test_synox_ascii_env_forces_ascii():
    assert not brand.supports_unicode(FakeTerminal(), env={"SYNOX_ASCII": "1"}, codepage=65001)
    assert brand.supports_unicode(FakeTerminal(), env={"WT_SESSION": "x"}, codepage=950)   # Windows Terminal


def test_ascii_logo_is_pure_ascii_and_aligned():
    lines = brand.logo_lines(unicode=False)
    assert all(line.isascii() for line in lines) and len(lines) == 4
    assert len(brand.logo_lines(unicode=True)) == 6


# ---------------------------------------------------------------- 內容

def test_greeting_follows_isdpcs_time_slots():
    assert brand.greeting(3)[1] == "深夜了"
    assert brand.greeting(8)[1] == "早安"
    assert brand.greeting(12)[1] == "午安"
    assert brand.greeting(15)[1] == "午後好"
    assert brand.greeting(20)[1] == "晚上好"
    assert brand.greeting(23)[1] == "夜深了"


def test_prog_name_follows_how_synox_was_started():
    assert brand.prog_name(r"C:\SYNOX\.venv\Scripts\synox.exe") == "synox"
    assert brand.prog_name("/usr/bin/synox") == "synox"
    assert brand.prog_name(r"C:\SYNOX\src\synox\__main__.py") == "python -m synox"


def test_command_banner_says_what_is_starting():
    text = brand.render_banner("run", unicode=False, now=NOON, prog="synox")
    assert "正在啟動 SYNOX" in text and "下一步" not in text


def test_about_says_where_the_project_and_the_latest_version_are(tmp_path):
    text = brand.about_text(str(tmp_path / "config.json"), root=str(tmp_path))
    assert brand.version() in text and "AGPL-3.0-or-later" in text and "Apache-2.0" in text
    assert "https://github.com/ChouYangEn0401/SYNOX" in text and "還沒公開" not in text
    assert brand.RELEASES_URL == brand.PROJECT_URL + "/releases" and brand.RELEASES_URL in text
    assert "有沒有新版" in text and "不會自己連網" in text
    assert [u for u in re.findall(r"https?://\S+", text) if not u.startswith(brand.PROJECT_URL)] == []   # 只有官方網址
    assert "還沒有" in text                                     # 沒有 config.json 時告訴你怎麼做


def test_doctor_points_to_the_releases_page(tmp_path):
    from synox import doctor
    lines = []
    doctor.run(offline=True, config_path=str(tmp_path / "config.json"), out=lines.append)
    assert lines[0].startswith("🩺 SYNOX ") and lines[1] == f"• 有沒有新版：{brand.latest_hint()}"


def test_release_script_uses_the_same_official_url():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    import release
    assert release.REPO_URL == brand.PROJECT_URL and release.RELEASES_URL == brand.RELEASES_URL


# ---------------------------------------------------------------- CLI

def test_existing_commands_print_exactly_what_they_did_when_not_a_terminal(capsys, tmp_path):
    """capsys 不是終端機：歡迎畫面不能多出任何一個字（既有的輸出、exit code 都不變）。"""
    assert cli.main([]) == 1
    out = capsys.readouterr().out
    assert "Welcome to SYNOX" not in out and out.startswith("usage:")
    cfg = tmp_path / "config.json"
    cfg.write_text('{"owner_id": 1, "data_dir": "%s", "llm": {"kind": "fake"}, "vault": {"mode": "file"}}'
                   % str(tmp_path / "data").replace("\\", "/"), encoding="utf-8")
    assert cli.main(["--config", str(cfg), "doctor", "--offline"]) == 1
    out = capsys.readouterr().out
    assert "Welcome to SYNOX" not in out and "\x1b[" not in out


def test_main_prints_the_banner_on_a_terminal_and_quiet_turns_it_off(monkeypatch):
    seen = []
    monkeypatch.setattr(brand, "show_banner", lambda cmd, quiet=False, **kw: seen.append((cmd, quiet)) or "")
    monkeypatch.setattr(cli, "cmd_about", lambda args: 0)
    assert cli.main([]) == 1
    assert cli.main(["about"]) == 0
    assert cli.main(["--quiet", "about"]) == 0
    assert cli.main(["about", "-q"]) == 0
    assert seen == [(None, False), ("about", False), ("about", True), ("about", True)]


def test_commands_without_a_banner_do_not_call_it(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(brand, "show_banner", lambda *a, **kw: seen.append(a) or "")
    assert cli.main(["tips"]) == 0
    assert seen == []


def write_config(tmp_path):
    cfg = logic.build_config("", logic.local_owner_id(), {"kind": "none"})
    cfg["vault"] = {"mode": "file"}
    cfg["web"] = {"enabled": True, "port": 8843}
    path = tmp_path / "config.json"
    logic.write_config(str(path), cfg)
    return str(path)


def test_open_opens_the_owner_link_with_a_fake_browser(tmp_path):
    path = write_config(tmp_path)
    opened, started = [], []
    rc = cli.cmd_open(argparse.Namespace(config=path), is_up=lambda port: port == 8843, running=lambda c: True,
                      start=started.append, open_url=opened.append, sleep=lambda s: None)
    assert rc == 0 and not started and len(opened) == 1
    assert opened[0].startswith("http://127.0.0.1:8843/login?t=")


def test_open_starts_synox_first_when_it_is_not_running(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setattr(cli, "CONFIG_PATH", path)
    state = {"up": False}
    started, opened = [], []

    def start(root):
        started.append(root)
        state["up"] = True

    rc = cli.cmd_open(argparse.Namespace(config=path), is_up=lambda p: state["up"], running=lambda c: state["up"],
                      start=start, open_url=opened.append, sleep=lambda s: None)
    assert rc == 0 and len(started) == 1 and len(opened) == 1


def test_open_and_web_login_both_route_through_main(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "cmd_web_login", lambda args, **kw: calls.append("web-login") or 0)
    monkeypatch.setattr(brand, "show_banner", lambda *a, **kw: "")
    assert cli.main(["open"]) == 0                              # cmd_open → cmd_web_login（假的）
    assert calls == ["web-login"]
    monkeypatch.setattr(cli, "cmd_open", lambda args, **kw: calls.append("open") or 0)
    assert cli.main(["open"]) == 0 and calls[-1] == "open"


@pytest.mark.parametrize("name", ["open", "web-login", "about", "tips"])
def test_new_commands_have_help(name, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([name, "--help"])
    assert e.value.code == 0 and name in capsys.readouterr().out


def test_top_level_help_lists_the_new_commands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for name in ("open", "about", "tips", "--quiet"):
        assert name in out


def test_tips_prints_one_tip(capsys):
    assert cli.cmd_tips(argparse.Namespace(all=False), rng=random.Random(3)) == 0
    out = capsys.readouterr().out
    assert out.startswith("小提示：") and out.count("\n") == 1


def test_tips_all_lists_every_tip(capsys):
    assert cli.main(["tips", "--all"]) == 0
    assert capsys.readouterr().out.count("\n") == len(brand.TIPS)


def test_tips_only_mention_commands_that_exist():
    parser_cmds = {"open", "doctor", "console", "stop", "install", "packs", "about"}
    for text in brand.all_tips(prog="synox"):
        if text.startswith("synox "):
            assert re.match(r"synox ([a-z-]+)", text).group(1) in parser_cmds, text


def test_about_command(capsys, tmp_path):
    assert cli.main(["--config", str(tmp_path / "config.json"), "about"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"SYNOX v{brand.version()}") and "LICENSING.md" in out


def test_preview_file_matches_the_ascii_banner():
    """docs/ui/cli-welcome.txt 是給人看的預覽：跟程式產生的一樣（改了版面就重產：scripts/make_cli_welcome.py）。"""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "docs", "ui", "cli-welcome.txt")
    sys.path.insert(0, os.path.join(root, "scripts"))
    try:
        import make_cli_welcome
    finally:
        sys.path.pop(0)
    with open(path, encoding="utf-8") as f:
        assert f.read() == make_cli_welcome.render()


def test_no_console_at_all_is_fine(monkeypatch):
    """pythonw（精靈視窗、開機自動啟動）沒有 stdout：不印、不丟例外。"""
    monkeypatch.setattr(sys, "stdout", None)
    assert brand.show_banner("wizard", env=TTY_ENV) == ""
