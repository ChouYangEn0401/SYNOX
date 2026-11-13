"""安裝精靈／Setup.bat／Uninstall.bat 的多語言：字串表齊不齊、退回規則、lang.txt、每個語言畫得出來。"""

import importlib
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from synox.wizard import i18n, logic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDER = re.compile(r"\{(\w*)\}")


@pytest.fixture(autouse=True)
def _restore_lang(monkeypatch):
    monkeypatch.setattr(i18n, "_current", i18n.DEFAULT)      # 測完換回預設，不影響別的測試


def _module(code):
    return importlib.import_module("synox.wizard.lang." + code.replace("-", "_"))


def test_every_language_has_every_key_and_the_same_placeholders():
    source = _module("zh-TW").STRINGS
    assert len(i18n.LANGS) == 12 and i18n.LANGS[0] == i18n.DEFAULT == "zh-TW"
    for code in i18n.LANGS:
        table = _module(code).STRINGS
        assert set(table) == set(source), (code, set(table) ^ set(source))
        for key, text in source.items():
            assert sorted(PLACEHOLDER.findall(table[key])) == sorted(PLACEHOLDER.findall(text)), (code, key)
            assert table[key].strip(), (code, key)
        if code != "zh-TW":
            assert "NATIVE-SPEAKER REVIEW" in (_module(code).__doc__ or ""), code
        assert code in i18n.LANG_NAMES and code in i18n.LATIN_NAMES and code in i18n.FONTS


def test_lookup_and_fallback(monkeypatch):
    assert i18n.t("step", n=1, total=4) == "第 1 步，共 4 步"
    i18n.set_lang("en")
    assert i18n.t("step", n=2, total=4) == "Step 2 of 4"
    i18n.set_lang("ja")
    ja = dict(i18n.table("ja"))
    del ja["close"]
    monkeypatch.setitem(i18n._tables, "ja", ja)
    assert i18n.t("close") == "Close"                        # 缺的先退回英文
    en = dict(i18n.table("en"))
    del en["close"]
    monkeypatch.setitem(i18n._tables, "en", en)
    assert i18n.t("close") == "關閉"                          # 英文也缺 → 原文
    assert i18n.t("no-such-key") == "no-such-key"
    i18n.set_lang("zh-TW")
    zh = dict(i18n.table("zh-TW"))
    del zh["close"]
    monkeypatch.setitem(i18n._tables, "zh-TW", zh)
    assert i18n.t("close") == "close"                         # 原文不往英文退


def test_normalize():
    assert i18n.normalize("EN") == "en" and i18n.normalize("en-US") == "en" and i18n.normalize("english") == "en"
    assert i18n.normalize("zh_tw") == "zh-TW" and i18n.normalize("zh") == "zh-TW"
    assert i18n.normalize("zh-cn") == "zh-CN" and i18n.normalize("pt") == "pt-BR" and i18n.normalize("pt_br") == "pt-BR"
    assert i18n.normalize("ar-EG") == "ar" and i18n.normalize("Russian") == "ru"
    assert i18n.normalize("") is None and i18n.normalize("xx") is None and i18n.normalize(None) is None
    assert i18n.set_lang("klingon") == "zh-TW"
    assert i18n.is_rtl("ar") and not i18n.is_rtl("en")


def test_font_choice():
    assert i18n.font_family(["Segoe UI", "Meiryo UI"], lang="ja") == "Meiryo UI"
    assert i18n.font_family(["Nirmala UI"], lang="hi") == "Nirmala UI"
    assert i18n.font_family(["Courier"], lang="ko") == "TkDefaultFont"
    assert i18n.font_family(lang="zh-CN") == "Microsoft YaHei UI"


def test_lang_file_read_write(tmp_path):
    path = i18n.lang_path(str(tmp_path))
    assert path.endswith("lang.txt") and i18n.read_lang(path) is None
    assert i18n.write_lang(path, "pt_br") == "pt-BR"
    assert open(path, "rb").read() == b"pt-BR\n" and i18n.read_lang(path) == "pt-BR"
    open(path, "wb").write(b"\xef\xbb\xbfen\r\n")                # PowerShell 寫的也讀得懂
    assert i18n.read_lang(path) == "en"
    open(path, "w").write("garbage")
    assert i18n.read_lang(path) is None


def test_logic_texts_follow_language():
    assert "伺服器版" in logic.mode_lines("server")[0]
    i18n.set_lang("en")
    assert logic.mode_lines("server")[0] == "A group (server)"
    assert logic.claude_status(lambda: None)[1].startswith("❌ Claude Code")
    assert "API key" in logic.llm_settings("keys", provider="anthropic")[1]
    assert logic.llm_settings("keys", provider="openai_compat", base_url="x", model="m")[1].startswith("The URL")
    label = logic.provider_labels()[-1]
    assert label.startswith("Compatible endpoint") and logic.provider_by_label(label) == "openai_compat"
    assert logic.provider_by_label("相容端點（公司閘道、Ollama）") == "openai_compat"
    assert logic.finish_status([], launched=False, has_token=False).endswith("You can close this window.")
    with pytest.raises(KeyError):
        logic.mode_lines("nope")


def test_config_keeps_language_key(tmp_path):
    from synox.config import SynoxConfig
    cfg = logic.build_config("", logic.local_owner_id(), {"kind": "none"}, language="en")
    assert cfg["language"] == "en"
    assert "language" not in logic.build_config("", 1, {"kind": "none"})
    path = tmp_path / "config.json"
    logic.write_config(str(path), cfg)
    config = SynoxConfig.load(str(path), require_token=False)            # 不認得的 key 不會擋
    assert config.owner_id == logic.local_owner_id()
    assert json.loads(path.read_text(encoding="utf-8"))["language"] == "en"


# ── 精靈畫面（隱藏的 Tk 視窗）────────────────────────────────────────

@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


def _fakes(monkeypatch, pages, calls):
    monkeypatch.setattr(pages.logic, "save", lambda path, cfg, *a, **k: calls["saved"].append(cfg) or cfg)
    monkeypatch.setattr(pages.logic, "claude_status", lambda: (False, i18n.t("claude_missing")))
    monkeypatch.setattr(pages.logic, "web_login_link", lambda path: "")
    monkeypatch.setattr(pages.shortcuts, "create_desktop_shortcut", lambda root_: None)
    monkeypatch.setattr(pages.shortcuts, "enable_autostart", lambda root_: "x")
    monkeypatch.setattr(pages.shortcuts, "disable_autostart", lambda: None)
    monkeypatch.setattr(pages.shortcuts, "register_synoxpack", lambda root_: None)
    monkeypatch.setattr(pages.shortcuts, "unregister_synoxpack", lambda: None)
    monkeypatch.setattr(pages.subprocess, "Popen", lambda *a, **k: calls["popen"].append(a))
    monkeypatch.setattr(pages.webbrowser, "open", lambda link: calls["browser"].append(link))


def _texts(widget):
    out = []
    for w in widget.winfo_children():
        try:
            out.append(str(w.cget("text")))
        except Exception:
            pass
        out.extend(_texts(w))
    return out


def _too_wide(wiz):
    """畫面上比視窗還寬的元件（字被切掉）。"""
    wiz.root.update_idletasks()
    limit = wiz.wrap + 40
    bad = []

    def walk(widget):
        for w in widget.winfo_children():
            if w.winfo_class() in ("TLabel", "TCheckbutton", "TRadiobutton", "TButton") and w.winfo_reqwidth() > limit:
                bad.append((w.cget("text"), w.winfo_reqwidth()))
            walk(w)

    walk(wiz.body)
    return bad


@pytest.mark.parametrize("code", i18n.LANGS)
def test_wizard_pages_render_in_every_language(code, tk_root, tmp_path, monkeypatch):
    from synox.wizard import pages
    calls = {"popen": [], "browser": [], "saved": []}
    _fakes(monkeypatch, pages, calls)
    wiz = pages.Wizard(tk_root, config_path=str(tmp_path / "config.json"), lang=code)
    assert i18n.get_lang() == code and not wiz.ask_lang
    assert i18n.read_lang(str(tmp_path / "lang.txt")) == code              # 帶進來的語言也記下來
    assert tk_root.title() == i18n.t("title")
    assert i18n.t("mode_title") in _texts(wiz.body)                        # 沒問語言，直接第 1 頁
    for page, key in ((wiz.page_mode, "mode_title"), (wiz.page_token, "token_title"),
                      (wiz.page_llm, "llm_title"), (wiz.page_finish, "finish_title")):
        page()
        assert i18n.t(key) in _texts(wiz.body), (code, key)
        assert not _too_wide(wiz), (code, key, _too_wide(wiz))
    assert wiz.next_btn.cget("text") == i18n.t("finish_go")
    wiz.next_btn.invoke()
    assert calls["saved"][-1]["language"] == code
    assert wiz.next_btn.cget("text") == i18n.t("close")
    assert wiz.next_btn.winfo_manager() == "pack"
    assert wiz.next_btn.pack_info()["side"] == ("left" if code == "ar" else "right")


def test_wizard_english_texts(tk_root, tmp_path, monkeypatch):
    from synox.wizard import pages
    calls = {"popen": [], "browser": [], "saved": []}
    _fakes(monkeypatch, pages, calls)
    wiz = pages.Wizard(tk_root, config_path=str(tmp_path / "config.json"), lang="en")
    assert "Just me (personal)" in _texts(wiz.body)
    wiz.page_token()
    assert any(s.startswith("How to get a Telegram bot token") for s in _texts(wiz.body))
    wiz.page_llm()
    assert "No AI for now (commands and buttons only)" in _texts(wiz.body)
    wiz.page_finish()
    assert "Open SYNOX when finished" in _texts(wiz.body)
    wiz.next_btn.invoke()
    assert "SYNOX is running" in _texts(wiz.body)[-1]


def test_wizard_asks_language_when_none_given(tk_root, tmp_path, monkeypatch):
    from synox.wizard import pages
    _fakes(monkeypatch, pages, {"popen": [], "browser": [], "saved": []})
    (tmp_path / "lang.txt").write_text("ja\n", encoding="ascii")
    wiz = pages.Wizard(tk_root, config_path=str(tmp_path / "config.json"))
    assert wiz.ask_lang and i18n.get_lang() == "ja"                       # 預選存過的
    combo = [w for w in wiz.body.winfo_children() if w.winfo_class() == "TCombobox"][0]
    assert combo.get().startswith("日本語")
    combo.set([v for v in combo.cget("values") if v.startswith("Русский")][0])
    combo.event_generate("<<ComboboxSelected>>")
    assert i18n.get_lang() == "ru" and wiz.next_btn.cget("text") == i18n.t("next")
    assert i18n.read_lang(str(tmp_path / "lang.txt")) == "ja"            # 按下一步才存
    wiz.next_btn.invoke()
    assert i18n.read_lang(str(tmp_path / "lang.txt")) == "ru"
    assert i18n.t("mode_title") in _texts(wiz.body)


def test_wizard_default_language_without_file(tk_root, tmp_path, monkeypatch):
    from synox.wizard import pages
    _fakes(monkeypatch, pages, {"popen": [], "browser": [], "saved": []})
    (tmp_path / "config.json").write_text('{"language": "ko"}', encoding="utf-8")
    pages.Wizard(tk_root, config_path=str(tmp_path / "config.json"))
    assert i18n.get_lang() == "ko"                                          # 沒有 lang.txt：用 config.json 記的
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    pages.Wizard(tk_root, config_path=str(tmp_path / "config.json"))
    assert i18n.get_lang() == "zh-TW"


def test_cli_wizard_lang_flag(monkeypatch):
    from synox import __main__ as cli
    from synox.wizard import pages
    seen = {}
    monkeypatch.setattr(pages, "main", lambda config_path, lang=None: seen.update(lang=lang) or 0)
    monkeypatch.delenv("SYNOX_LANG", raising=False)
    assert cli.main(["wizard", "--lang", "en"]) == 0 and seen["lang"] == "en"
    monkeypatch.setenv("SYNOX_LANG", "ja")
    assert cli.main(["wizard"]) == 0 and seen["lang"] == "ja"


# ── PowerShell（Setup.bat／Uninstall.bat）────────────────────────────

PSD1_LINE = re.compile(r"^\s*([\w-]+)\s*=\s*'((?:[^']|'')*)'\s*$")


def _psd1(code):
    raw = open(os.path.join(ROOT, "setup", "lang", f"{code}.psd1"), "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf"), code                          # PowerShell 5.1 沒 BOM 會讀錯
    out = {}
    for line in raw[3:].decode("utf-8").splitlines():
        m = PSD1_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2).replace("''", "'")
    return out


def test_powershell_tables_complete():
    source = _psd1("zh-TW")
    assert len(source) > 30
    for code in i18n.LANGS:
        table = _psd1(code)
        assert set(table) == set(source), (code, set(table) ^ set(source))
        for key, text in source.items():
            assert PLACEHOLDER.findall(table[key]) == PLACEHOLDER.findall(text), (code, key)
        assert "DELETE" in table["delete_prompt"], code
    lang_ps1 = open(os.path.join(ROOT, "setup", "lang.ps1"), encoding="utf-8-sig").read()
    listed = re.search(r"\$SynoxLangs = @\(([^)]*)\)", lang_ps1).group(1)
    assert tuple(re.findall(r"'([\w-]+)'", listed)) == i18n.LANGS                 # 選單順序跟精靈一樣


def test_setup_scripts_encoding():
    for name in ("Setup.bat", "Uninstall.bat"):
        bat = open(os.path.join(ROOT, name), "rb").read()
        bat.decode("ascii")
        assert b"\r\n" in bat
    for name in ("bootstrap.ps1", "uninstall.ps1", "lang.ps1"):
        assert open(os.path.join(ROOT, "setup", name), "rb").read().startswith(b"\xef\xbb\xbf"), name


def _powershell():
    if sys.platform != "win32" or not shutil.which("powershell"):
        pytest.skip("Windows PowerShell only")
    return shutil.which("powershell")


def test_powershell_scripts_parse():
    ps = _powershell()
    script = ("$bad = 0; foreach ($f in @('bootstrap.ps1','uninstall.ps1','lang.ps1')) { $e = $null; "
              "[void][System.Management.Automation.Language.Parser]::ParseFile((Join-Path '%s' $f), [ref]$null, [ref]$e); "
              "$bad += $e.Count }; exit $bad" % os.path.join(ROOT, "setup"))
    assert subprocess.run([ps, "-NoProfile", "-Command", script], timeout=60).returncode == 0


@pytest.mark.parametrize("code,expect", [("en", "Desktop shortcut"), ("ja", "デスクトップ"), ("zh-TW", "桌面捷徑")])
def test_uninstall_check_in_language(code, expect, tmp_path):
    """解除安裝 -Mode check 在暫存沙盒裡跑（SYNOX_UNINSTALL_SANDBOX：不碰真的桌面／啟動資料夾／登錄檔）。"""
    ps = _powershell()
    shutil.copytree(os.path.join(ROOT, "setup"), str(tmp_path / "setup"))
    env = {**os.environ, "SYNOX_UNINSTALL_SANDBOX": str(tmp_path / "sandbox")}
    env.pop("SYNOX_LANG", None)
    out = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          str(tmp_path / "setup" / "uninstall.ps1"), "-Mode", "check", "-Lang", code],
                         capture_output=True, timeout=120, env=env, stdin=subprocess.DEVNULL)
    text = out.stdout.decode("utf-8", "replace")
    assert out.returncode == 0, text + out.stderr.decode("utf-8", "replace")
    assert expect in text and "config.json" in text
    assert not (tmp_path / "lang.txt").exists()                             # -Lang 只管這次，不存


def test_uninstall_reads_saved_language(tmp_path):
    ps = _powershell()
    shutil.copytree(os.path.join(ROOT, "setup"), str(tmp_path / "setup"))
    (tmp_path / "lang.txt").write_text("de\n", encoding="ascii")
    env = {**os.environ, "SYNOX_UNINSTALL_SANDBOX": str(tmp_path / "sandbox")}
    env.pop("SYNOX_LANG", None)
    out = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          str(tmp_path / "setup" / "uninstall.ps1"), "-Mode", "check"],
                         capture_output=True, timeout=120, env=env, stdin=subprocess.DEVNULL)
    text = out.stdout.decode("utf-8", "replace")
    assert out.returncode == 0 and _psd1("de")["row_shortcut"] in text, text
