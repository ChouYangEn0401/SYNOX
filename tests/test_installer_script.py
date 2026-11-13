# -*- coding: utf-8 -*-
"""The .exe installer as the owner decided it (2026-11-13, docs/installer/spec.html section 8): language first,
welcome page without an "I agree" page, Recommended | Custom, optional Claude Code, uninstall that keeps the data
unless asked twice. Inno Setup cannot run here, so these are static checks of setup/installer/synox.iss and its
lang/*.isl texts (scripts/installer_ci.py check-iss), plus the setup wizard's side of the hand-over."""
import argparse
import json
import os
import re
import shutil
import sys

import pytest

from synox.wizard import i18n, logic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALLER = os.path.join(ROOT, "setup", "installer")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import installer_ci  # noqa: E402


def _iss():
    with open(os.path.join(INSTALLER, "synox.iss"), "r", encoding="ascii") as f:
        return f.read()


def _copy(tmp_path):
    folder = tmp_path / "installer"
    shutil.copytree(INSTALLER, folder)
    return folder


# ── static checks ─────────────────────────────────────────────────────────────────────────────

def test_installer_script_passes_the_static_check():
    assert installer_ci.check_iss() == []
    assert installer_ci.main(["check-iss"]) == 0


def test_installer_languages_are_the_wizards_languages():
    assert installer_ci.INSTALLER_LANGS == i18n.LANGS
    assert set(installer_ci.INNO_OFFICIAL) | set(installer_ci.INNO_UNOFFICIAL) | {"en"} == set(i18n.LANGS)
    for code in i18n.LANGS:
        table = installer_ci.read_isl(os.path.join(INSTALLER, "lang", code + ".isl"))
        assert table["CustomMessages"]["SynoxLangCode"] == code
        if code != "en":                                    # native name first, Latin name in brackets
            name = table["LangOptions"]["LanguageName"]
            assert name.startswith(i18n.LANG_NAMES[code]) and i18n.LATIN_NAMES[code].split(" (")[0] in name, code


def test_owner_decisions_are_in_the_script():
    text = _iss()
    assert not re.search(r"^LicenseFile=", text, re.M)       # Q4: no "I agree" page
    for line in ("ShowLanguageDialog=yes", "LanguageDetectionMethod=uilanguage", "DisableWelcomePage=no",
                 "DisableReadyPage=yes", "PrivilegesRequired=lowest"):
        assert re.search(rf"^{re.escape(line)}$", text, re.M), line
    assert "PrivilegesRequiredOverridesAllowed" not in text   # no "for all users?" dialog before the language
    assert re.search(r'^Name: "autostart"; Description: "\{cm:TaskAutostart\}"$', text, re.M)        # Q1: on
    assert re.search(r'^Name: "alltools";.*Flags: unchecked$', text, re.M)                             # Q3: off
    assert 'Source: "{#StageDir}\\LICENSING.md"' in text and 'Source: "{#StageDir}\\*"' in text      # still installed
    assert "Excludes: \"STAGE-MANIFEST.txt\"" in text and "packs" not in text.split("Excludes:")[1].split("\n")[0]
    en = installer_ci.read_isl(os.path.join(INSTALLER, "lang", "en.isl"))["CustomMessages"]
    zh = installer_ci.read_isl(os.path.join(INSTALLER, "lang", "zh-TW.isl"))
    assert zh["Messages"]["WelcomeLabel1"] == "歡迎使用 SYNOX，用得開心。"
    assert "個人使用免費。要拿去做商業用途，請看" in zh["CustomMessages"]["LicenseLine"]
    assert zh["Messages"]["WelcomeLabel2"].count("•") in (2, 3, 4)                  # 2-4 short bullets
    assert zh["CustomMessages"]["LicenseFile"] == "LICENSING.md" and en["LicenseFile"] == "LICENSE"
    assert "不建議" in zh["CustomMessages"]["TaskAllTools"] and "教學" in zh["CustomMessages"]["TaskAllTools"]
    assert "需要上網" in zh["CustomMessages"]["TaskClaude"] and "使用者資料夾" in zh["CustomMessages"]["TaskClaude"]
    assert zh["CustomMessages"]["UninstallDeleteData"] == "連我的資料也一起刪除"


def test_claude_code_step_uses_the_official_one_liner_and_never_blocks():
    with open(os.path.join(INSTALLER, "claude-code.ps1"), "rb") as f:
        script = f.read().decode("ascii")                     # PowerShell 5.1: no BOM -> must be ASCII
    assert logic.CLAUDE_INSTALL_PS in script
    assert "Wait-Job" in script and "-Timeout" in script      # a hang cannot hold the installer forever
    assert "Find-Claude" in script and "exit 0" in script      # only when missing
    code = _iss().split("[Code]", 1)[1]
    assert "procedure InstallClaudeCode" in code and "ClaudeResult := 'skipped'" in code
    step = code.split("procedure CurStepChanged", 1)[1].split("end;\n\n", 1)[0]
    assert step.index("SaveLanguage;") < step.index("InstallClaudeCode;") < step.index("SaveChoices;")


def test_installer_choices_file_matches_what_the_wizard_reads():
    code = _iss().split("[Code]", 1)[1]
    assert logic.INSTALLER_CHOICES in code and i18n.LANG_FILE in code
    for key in ("source", "language", "install_type", "desktop", "start_menu", "file_type", "autostart",
                "claude_code", "all_tools"):
        assert f'\'  "{key}": ' in code, key
    assert '"source": "exe-installer"' in code


def test_uninstall_keeps_data_by_default_and_asks_twice():
    text = _iss()
    code = text.split("[Code]", 1)[1].split("[UninstallDelete]")[0]
    assert "DataCheck.Checked := False" in code
    assert "MsgBox(CustomMessage('UninstallConfirmData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2)" in code
    assert "(CurUninstallStep = usPostUninstall) and DeleteUserData" in code
    assert "if UninstallSilent then\n    Result := True" in code                 # silent uninstall keeps the data
    for target in ("config.json", "data", "packs"):
        assert f'"{{app}}\\{target}"' not in text.split("[UninstallDelete]")[1]


@pytest.mark.parametrize("mutate,expect", [
    (lambda t: t.replace("DisableReadyPage=yes", "DisableReadyPage=yes\nLicenseFile=x"), "LicenseFile"),
    (lambda t: t.replace('Name: "alltools"; Description: "{cm:TaskAllTools}"; Flags: unchecked',
                         'Name: "alltools"; Description: "{cm:TaskAllTools}"'), "[Tasks]"),
    (lambda t: t.replace('Name: "ko"; MessagesFile: "compiler:Languages\\Korean.isl,lang\\en.isl,lang\\ko.isl"\n', ""),
     "[Languages]"),
    (lambda t: t.replace("compiler:Languages\\French.isl,lang\\en.isl,lang\\fr.isl",
                         "compiler:Languages\\French.isl,lang\\fr.isl"), "English fallback"),
    (lambda t: t.replace("ShowLanguageDialog=yes", "ShowLanguageDialog=auto"), "ShowLanguageDialog"),
    (lambda t: t.replace("{cm:TaskStartMenu}", "{cm:NoSuchMessage}"), "NoSuchMessage"),
    (lambda t: t.replace('Type: files; Name: "{app}\\lang.txt"', 'Type: files; Name: "{app}\\config.json"'),
     "config.json"),
])
def test_static_check_catches_broken_scripts(tmp_path, mutate, expect):
    folder = _copy(tmp_path)
    path = folder / "synox.iss"
    path.write_text(mutate(path.read_text(encoding="ascii")), encoding="ascii")
    problems = installer_ci.check_iss(str(folder))
    assert any(expect in p for p in problems), problems


def test_static_check_catches_incomplete_translations(tmp_path):
    folder = _copy(tmp_path)
    path = folder / "lang" / "ja.isl"
    raw = path.read_bytes().decode("utf-8-sig")
    raw = re.sub(r"^TaskClaude=.*\r?\n", "", raw, flags=re.M)
    raw = raw.replace("WelcomeLabel1=", "WelcomeLabel1=%1 ")
    path.write_bytes(b"\xef\xbb\xbf" + raw.encode("utf-8"))
    problems = "\n".join(installer_ci.check_iss(str(folder)))
    assert "lang/ja.isl [CustomMessages]: missing ['TaskClaude']" in problems
    assert "lang/ja.isl: WelcomeLabel1 has other placeholders" in problems
    (folder / "lang" / "ko.isl").write_bytes((folder / "lang" / "ko.isl").read_bytes()[3:])
    assert any("ko.isl: needs a UTF-8 BOM" in p for p in installer_ci.check_iss(str(folder)))


def test_release_doc_lists_installer_languages_and_smartscreen():
    with open(os.path.join(ROOT, "docs", "release-build.md"), "r", encoding="utf-8") as f:
        doc = f.read()
    for name in list(installer_ci.INNO_OFFICIAL.values()) + list(installer_ci.INNO_UNOFFICIAL.values()):
        assert name in doc, name
    assert "SHA-256" in doc and "其他資訊" in doc and "仍要執行" in doc


# ── the setup wizard's side ───────────────────────────────────────────────────────────────────

def _choices(folder, **extra):
    data = {"source": "exe-installer", "version": "0.2.0", "language": "zh-TW", "install_type": "custom",
            "desktop": True, "start_menu": True, "file_type": True, "autostart": True, "claude_code": "present",
            "all_tools": False}
    data.update(extra)
    with open(os.path.join(folder, logic.INSTALLER_CHOICES), "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_installer_choices_helpers(tmp_path):
    assert logic.installer_choices(str(tmp_path)) == {}
    (tmp_path / logic.INSTALLER_CHOICES).write_text('{"source": "something-else"}', encoding="utf-8")
    assert logic.installer_choices(str(tmp_path)) == {}
    (tmp_path / logic.INSTALLER_CHOICES).write_text("not json", encoding="utf-8")
    assert logic.installer_choices(str(tmp_path)) == {}
    _choices(str(tmp_path), all_tools=True)
    choices = logic.installer_choices(str(tmp_path))
    assert logic.wants_all_tools(choices)
    logic.mark_all_tools_done(str(tmp_path), ok=False)
    again = logic.installer_choices(str(tmp_path))
    assert not logic.wants_all_tools(again) and again["all_tools_ok"] is False
    args = logic.all_tools_args("py", "C:/x/config.json")
    assert args[:3] == ["py", "-m", "synox"] and args[-4:] == ["tools", "install", "--all", "--yes"]


def test_tutorial_line_hook(monkeypatch):
    assert logic.tutorial_line() == i18n.t("finish_tutorial")
    monkeypatch.setattr(logic, "TUTORIAL_HOW", "/tutorial")
    assert logic.tutorial_line().endswith("/tutorial")


def _finish_page(tmp_path, monkeypatch, run_result=0):
    tk = pytest.importorskip("tkinter")
    from synox.wizard import pages
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    root.withdraw()
    calls = {"desktop": 0, "autostart": [], "assoc": [], "run": [], "popen": []}
    monkeypatch.setattr(pages.logic, "save", lambda path, cfg, *a, **k: cfg)
    monkeypatch.setattr(pages.logic, "web_login_link", lambda path: "")
    monkeypatch.setattr(pages.shortcuts, "create_desktop_shortcut",
                        lambda root_: calls.__setitem__("desktop", calls["desktop"] + 1))
    monkeypatch.setattr(pages.shortcuts, "enable_autostart", lambda root_: calls["autostart"].append("on"))
    monkeypatch.setattr(pages.shortcuts, "disable_autostart", lambda: calls["autostart"].append("off"))
    monkeypatch.setattr(pages.shortcuts, "register_synoxpack", lambda root_: calls["assoc"].append("register"))
    monkeypatch.setattr(pages.shortcuts, "unregister_synoxpack", lambda: calls["assoc"].append("unregister"))
    monkeypatch.setattr(pages.subprocess, "Popen", lambda *a, **k: calls["popen"].append(a))
    monkeypatch.setattr(pages.subprocess, "run",
                        lambda args, **k: calls["run"].append(args) or argparse.Namespace(returncode=run_result))
    monkeypatch.setattr(pages.webbrowser, "open", lambda link: None)
    wiz = pages.Wizard(root, config_path=str(tmp_path / "config.json"), lang="zh-TW")
    wiz.page_finish()
    boxes = {w.cget("text"): w for w in wiz.body.winfo_children() if w.winfo_class() == "TCheckbutton"}
    return root, wiz, calls, boxes


def test_finish_page_from_zip_has_autostart_on_by_default(tmp_path, monkeypatch):
    root, wiz, calls, boxes = _finish_page(tmp_path, monkeypatch)
    try:
        assert len(boxes) == 4 and i18n.t("finish_autostart") in boxes
        assert "selected" in boxes[i18n.t("finish_autostart")].state()                # owner Q1: on by default
        wiz.next_btn.invoke()
        assert calls["autostart"] == ["on"] and calls["desktop"] == 1
        texts = [w.cget("text") for w in wiz.body.winfo_children() if w.winfo_class() == "TLabel"]
        assert logic.tutorial_line() in texts                                   # "do the tutorial" is on the page
    finally:
        root.destroy()


def test_finish_page_from_the_exe_only_asks_to_open_synox(tmp_path, monkeypatch):
    _choices(str(tmp_path), file_type=False)
    root, wiz, calls, boxes = _finish_page(tmp_path, monkeypatch)
    try:
        assert list(boxes) == [i18n.t("finish_launch")]                         # the other three were decided
        wiz.next_btn.invoke()
        assert calls["desktop"] == 0 and calls["autostart"] == []               # the installer did those
        assert calls["assoc"] == ["unregister"]                                 # unticked in the installer
        assert calls["run"] == [] and len(calls["popen"]) == 1
    finally:
        root.destroy()


def test_finish_page_installs_all_tools_once_when_ticked(tmp_path, monkeypatch):
    _choices(str(tmp_path), all_tools=True)
    root, wiz, calls, boxes = _finish_page(tmp_path, monkeypatch)
    try:
        wiz.background = lambda work, done: done(work())                       # no Tk main loop in tests
        wiz.next_btn.invoke()
        assert len(calls["run"]) == 1 and calls["run"][0][-4:] == ["tools", "install", "--all", "--yes"]
        assert len(calls["popen"]) == 1                                         # SYNOX opens after the tools
        assert logic.installer_choices(str(tmp_path))["all_tools_done"] is True
        assert os.path.isfile(tmp_path / "data" / "logs" / "all-tools.log")
    finally:
        root.destroy()


def test_tools_install_all_picks_every_entry(tmp_path, monkeypatch):
    from test_clean_room import make_tools

    import synox.__main__ as cli
    make_tools(tmp_path / "tools", ("notes", "money"))
    seen = []
    monkeypatch.setattr(cli, "cmd_install", lambda ns, **k: seen.append(os.path.basename(ns.file)) or 0)
    rc = cli.main(["-q", "--config", str(tmp_path / "config.json"), "tools", "install", "--all", "--yes",
                   "--library", str(tmp_path / "tools")])
    assert rc == 0
    assert sorted(seen) == sorted(f for f in os.listdir(tmp_path / "tools") if f.endswith(".synoxpack"))
