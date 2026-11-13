"""Setup.bat 預設用 SYNOX 自己的 Python（runtime\\python：安裝程式附的，或下載釘死網址＋SHA256 的 python-build-standalone），
不碰這台電腦的 Conda／Store／其他 Python（docs/adr/0003 兩則附記「預設用 SYNOX 自己的 Python」）；選完語言後的「先說清楚」與
建議／自訂（安裝規格 Q8）。這台是 Linux：全部是讀檔的靜態檢查，不跑 PowerShell、不連網。"""

import glob
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import stage_installer  # noqa: E402

BOOTSTRAP = os.path.join(ROOT, "setup", "bootstrap.ps1")
LANG_PS1 = os.path.join(ROOT, "setup", "lang.ps1")
CLEAN_ENV = os.path.join(ROOT, "setup", "clean-python-env.bat")
LAUNCHERS = ("Start.bat", "Console.bat", "Open-SYNOX.bat", "Install-Pack.bat", "Connect-Apple.bat", "Stop.bat")
# 會讓 .venv 的 Python 載入別人的程式或設定的變數（Conda 的用 CONDA_ 前綴一次清）
PYTHON_NOISE = ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__")


def _text(path):
    return open(path, encoding="utf-8-sig").read()


def _function(text, name):
    """PowerShell 的 function 本體（照大括號配對；這幾個函式的字串裡沒有不成對的括號）。"""
    m = re.search(r"^function %s\b[^{]*\{" % re.escape(name), text, re.M)
    assert m, name
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.end():i - 1]


def _code(text):
    """去掉 # 註解（只看真的會跑的那幾行）。"""
    return "\n".join(line.split("#", 1)[0] if not line.lstrip().startswith("#") else "" for line in text.splitlines())


def _main(text):
    return _code(text.split("\ntry {", 1)[1])


# ── 釘死的 Python（python-build-standalone）─────────────────────────

PIN = {"version": "3.12.16", "build": "20261026",
       "sha256": "1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149"}
URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/20261026/"
       "cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz")


def test_python_is_pinned_with_sha256_from_the_official_release():
    """2026-11-13 下載實算＝那個 release 的 SHA256SUMS＝uv 0.13.6 內建的清單（docs/adr/0003 附記之二）。"""
    text = _text(BOOTSTRAP)
    for name, key in (("PythonVersion", "version"), ("PythonBuild", "build"), ("PythonSha256", "sha256")):
        m = re.search(r"^\$%s = '([^']+)'" % name, text, re.M)
        assert m and m.group(1) == PIN[key], name
    assert ('$PythonUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/$PythonBuild/'
            'cpython-$PythonVersion%2B$PythonBuild-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"' in text)
    assert stage_installer.pinned_python(BOOTSTRAP) == {**PIN, "url": URL}     # 安裝程式讀同一份：exe 與 ZIP 同一個 Python


def test_download_is_checked_before_anything_is_unpacked_or_run():
    code = _code(_function(_text(BOOTSTRAP), "Install-StandalonePython"))
    assert "Get-FileHash" in code and "SHA256" in code and "$PythonSha256" in code
    assert code.index("Invoke-WebRequest") < code.index("Get-FileHash") < code.index("$WindowsTar -xzf")
    bad = code[code.index("if ($hash -ne $PythonSha256)"):]
    bad = bad[:bad.index("}")]
    assert "Remove-Folder $work" in bad and "throw (Tr 'py_hash_bad'" in bad   # 刪掉下載的檔案、停下來
    assert code.index("$WindowsTar -xzf") < code.index("Move-Item")


def test_everything_stays_in_runtime_and_uses_windows_own_tar():
    text = _text(BOOTSTRAP)
    assert "$Runtime = Join-Path $Root 'runtime'" in text
    assert "$PythonDir = Join-Path $Runtime 'python'" in text
    assert "$WindowsTar = Join-Path $env:SystemRoot 'System32\\tar.exe'" in text   # 不用 PATH 上的 tar（Git 的 GNU tar）
    body = _code(_function(text, "Install-StandalonePython"))
    assert "$work = Join-Path $Runtime 'python.download'" in body
    assert "Push-Location -LiteralPath $work" in body and "-xzf 'python.tar.gz'" in body   # tar 只拿到相對檔名
    assert "Tr 'py_no_tar'" in body
    for word in ("Expand-Archive", "$env:PATH", "Registry", "HKCU", "HKLM", "setx"):
        assert word not in body, word


def test_no_uv_and_no_python_org_fallback_left():
    code = _code(_text(BOOTSTRAP)).lower()
    for word in ("uv.exe", "uv python", "$uv", "python-uv", "uv_", "embed-amd64", "get-pip", "bootstrap.pypa.io",
                 "www.python.org", "virtualenv", "install-embedded"):
        assert word not in code, word
    for name in ("Setup.bat", "Uninstall.bat", os.path.join("setup", "clean-python-env.bat")):
        bat = _text(os.path.join(ROOT, name)).lower()
        assert not re.search(r"\buv\b", bat), name


def test_venv_is_plain_python_m_venv():
    main = _main(_text(BOOTSTRAP))
    assert "& $py.Exe @($py.Pre) -m venv $Venv" in main
    assert "virtualenv" not in main


def test_old_embeddable_python_is_replaced_not_reused():
    text = _text(BOOTSTRAP)
    assert "python*._pth" in _function(text, "Test-OldEmbedded")
    private = _code(_function(text, "Get-PrivatePython"))
    assert "Test-OldEmbedded $PythonDir" in private and "Tr 'py_old_embedded'" in private
    assert "Test-OldEmbedded $PythonDir" in _code(_function(text, "Find-SystemPython"))


# ── 預設與進階 ────────────────────────────────────────────────────

def test_default_path_never_uses_winget_or_the_users_python():
    text = _text(BOOTSTRAP)
    private = _code(_function(text, "Get-PrivatePython"))
    assert "winget" not in private.lower()
    for other in ("Get-Command", "'py'", "Programs\\Python", "Find-SystemPython"):
        assert other not in private, other
    assert private.index("Join-Path $PythonDir 'python.exe'") < private.index("Install-StandalonePython")
    # winget 只在 -UseSystemPython 的那條路上
    callers = [m.start() for m in re.finditer(r"Install-WithWinget", _code(text))]
    system = _code(_function(text, "Get-SystemPython"))
    assert "Install-WithWinget" in system
    assert len(callers) == 2                                                  # 定義＋Get-SystemPython 裡那一次
    assert system.index("Install-WithWinget") < system.index("Install-StandalonePython")   # 最後退到 SYNOX 自己的
    main = _main(text)
    assert re.search(r"if \(\$UseSystemPython\) \{[^}]*Get-SystemPython", main)
    assert "Get-PrivatePython" in main


def test_use_system_python_and_custom_are_switches_and_setup_bat_passes_them_through():
    text = _text(BOOTSTRAP)
    assert re.search(r"^param\(.*\[switch\]\$UseSystemPython.*\)", text, re.M)
    assert re.search(r"^param\(.*\[switch\]\$Custom.*\)", text, re.M)
    bat = open(os.path.join(ROOT, "Setup.bat"), "rb").read().decode("ascii")
    assert re.search(r'setup\\bootstrap\.ps1" %\*', bat)                       # 參數原樣交給 bootstrap
    assert "-UseSystemPython" in bat and "-Custom" in bat                    # 註解說得出這兩個選項


def test_system_python_never_picks_the_store_alias():
    text = _text(BOOTSTRAP)
    find = _code(_function(text, "Find-SystemPython"))
    assert "Test-StoreAlias" in find
    alias = _function(text, "Test-StoreAlias")
    assert "\\WindowsApps\\" in alias
    assert "Join-Path $PythonDir 'python.exe'" in find                        # 舊的順序：SYNOX 自己的還是第一個


def test_failures_are_said_plainly():
    text = _text(BOOTSTRAP)
    body = _code(_function(text, "Install-StandalonePython"))
    for key in ("py_download", "py_download_failed", "py_hash_bad", "py_extract", "py_extract_failed", "py_no_tar",
                "py_in_use"):
        assert "Tr '%s'" % key in body, key
    assert "Tr 'py_does_not_run'" in _function(text, "Get-PrivatePython")
    assert "Tr 'cannot_install_python'" in _main(text)


def test_notes_about_conda_store_and_other_pythons_before_cleaning():
    text = _text(BOOTSTRAP)
    find = _function(text, "Find-OtherPythons")
    for clue in ("CONDA_PREFIX", "CONDA_EXE", "conda", "Microsoft\\WindowsApps\\python.exe"):
        assert clue in find, clue
    for key in ("found_conda", "found_store_alias", "found_other_python"):
        assert "Tr '%s'" % key in find, key
    main = _main(text)
    assert main.index("Find-OtherPythons") < main.index("Clear-PythonEnv")   # 先看線索、再清
    assert "Tr 'env_note'" in main


def test_bootstrap_clears_python_and_conda_variables_for_its_own_process():
    body = _function(_text(BOOTSTRAP), "Clear-PythonEnv")
    for name in PYTHON_NOISE:
        assert "'%s'" % name in body, name
    assert "'CONDA_*'" in body and "Env:" in body


# ── 先說清楚、建議／自訂（安裝規格 Q8）─────────────────────────────

def test_language_enter_default_is_the_windows_display_language():
    text = _text(LANG_PS1)
    ask = _code(_function(text, "Ask-SynoxLang"))
    assert "$default = Get-SynoxDisplayLang" in ask and "return $default" in ask
    assert "'zh-TW'" not in ask                                               # 不再寫死繁體中文
    assert "Get-UICulture" in _function(text, "Get-SynoxDisplayLang")
    ui = _code(_function(text, "ConvertTo-SynoxUiLang"))
    assert "zh-(tw|hk|mo|hant)" in ui and "return 'en'" in ui                  # 香港／澳門＝繁中；不支援的語言＝英文


def test_after_the_language_it_says_things_plainly_then_asks_one_question():
    text = _text(BOOTSTRAP)
    head = text.split("\ntry {", 1)[0]
    assert head.index("Resolve-SynoxLang") < head.index("function Show-SetupIntro")
    main = _main(text)
    assert main.index("Show-SetupIntro") < main.index("Read-SetupPlan $Custom.IsPresent") < main.index("Get-PrivatePython")
    intro = _function(text, "Show-SetupIntro")
    for key in ("intro_title", "intro_1", "intro_2", "intro_3"):
        assert key in intro, key
    plan = _code(_function(text, "Read-SetupPlan"))
    # 建議＝只準備環境（＋教學），開機自動啟動；Claude Code、全部工具預設都不裝
    assert "$plan = @{ Custom = $false; Autostart = $true; ClaudeCode = $false; AllTools = $false }" in plan
    assert "if (-not (Test-Interactive)) { return $plan }" in plan           # 沒有人在看：照建議、不卡住
    assert "'^[cC]'" in plan                                                  # 只有 C 進自訂；Enter／其他＝照建議
    for key in ("plan_recommended", "plan_custom", "plan_question", "custom_title", "custom_autostart",
                "custom_claude", "custom_all_tools", "custom_prompt"):
        assert "Tr '%s'" % key in plan, key


def test_plan_hooks_claude_code_autostart_and_todos():
    text = _text(BOOTSTRAP)
    run = _function(text, "Invoke-SetupPlan")
    assert "$env:SYNOX_SETUP_AUTOSTART" in run and "Install-ClaudeCode" in run
    assert "TODO(工具庫／教學包)" in run and "TODO(教學包)" in run              # 還沒做的兩件事有標記
    assert "Tr 'all_tools_later'" in run
    from synox.wizard import logic
    assert "$ClaudeInstallPs = '%s'" % logic.CLAUDE_INSTALL_PS in text      # 跟精靈的一鍵安裝同一行官方指令
    claude = _code(_function(text, "Install-ClaudeCode"))
    assert claude.index("find_claude") < claude.index("Start-Process")       # 已經有就不裝
    main = _main(text)
    assert main.index("Install-Packages") < main.index("Invoke-SetupPlan $plan") < main.index("Start-Process")
    assert "if ($rc -eq 0 -and $plan.Autostart) { Enable-Autostart }" in main   # 文字版沒有完成頁可以勾


@pytest.mark.parametrize("value,expect", [("1", "enable"), ("0", "disable"), (None, "disable")])
def test_wizard_autostart_default_follows_the_setup_plan(value, expect, tmp_path, monkeypatch):
    from test_wizard import _finish_page
    if value is None:
        monkeypatch.delenv("SYNOX_SETUP_AUTOSTART", raising=False)
    else:
        monkeypatch.setenv("SYNOX_SETUP_AUTOSTART", value)
    from synox.wizard import pages
    seen = []
    root, wiz, calls, widgets = _finish_page(tmp_path, monkeypatch)     # 完成頁照環境變數決定預設勾不勾
    try:
        monkeypatch.setattr(pages.shortcuts, "enable_autostart", lambda root_: seen.append("enable"))
        monkeypatch.setattr(pages.shortcuts, "disable_autostart", lambda: seen.append("disable"))
        wiz.next_btn.invoke()
        assert seen == [expect]
    finally:
        root.destroy()


# ── 啟動器 ────────────────────────────────────────────────────────

def test_clean_env_helper_clears_python_and_conda_variables():
    raw = open(CLEAN_ENV, "rb").read()
    raw.decode("ascii")
    assert b"\r\n" in raw
    text = raw.decode("ascii")
    for name in PYTHON_NOISE:
        assert 'set "%s="' % name in text, name
    assert re.search(r"set CONDA_ 2\^>nul", text)                             # 每一個 CONDA_* 都清
    code = [line for line in text.lower().splitlines() if not line.startswith("rem ")]
    assert not any("setlocal" in line for line in code)                       # 要改到呼叫它的那個視窗
    listed = re.findall(r"'([\w]+)'", _function(_text(BOOTSTRAP), "Clear-PythonEnv").split("Get-ChildItem")[0])
    for name in listed:                                                       # 跟 Clear-PythonEnv 同一份清單
        assert 'set "%s="' % name in text, name


@pytest.mark.parametrize("name", LAUNCHERS)
def test_every_launcher_cleans_the_environment_before_running_python(name):
    text = open(os.path.join(ROOT, name), "rb").read().decode("ascii")
    assert "setlocal" in text                                                 # 只改這個視窗，不動 Windows 的設定
    call = text.index(r'call "%~dp0setup\clean-python-env.bat"')
    first_run = text.index('"%VENV_PY%" -m synox')
    assert text.index("setlocal") < call < first_run


def test_every_bat_is_ascii_with_crlf():
    files = glob.glob(os.path.join(ROOT, "*.bat")) + glob.glob(os.path.join(ROOT, "setup", "*.bat"))
    assert len(files) >= 9
    for path in files:
        raw = open(path, "rb").read()
        raw.decode("ascii")
        assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), path


# ── 解除安裝 ──────────────────────────────────────────────────────

def test_uninstall_env_removes_runtime_with_the_private_python():
    text = _text(os.path.join(ROOT, "setup", "uninstall.ps1"))
    assert "$Runtime = Join-Path $Root 'runtime'" in text
    env_block = text.split("if ($Mode -in @('env', 'all')) {", 1)[1].split("}", 1)[0]
    assert "Remove-Path $Venv" in env_block and "Remove-Runtime" in env_block
    body = _function(text, "Remove-Runtime")
    assert "ReparsePoint" in body and "Remove-Path $Runtime" in body          # 舊版留下的 junction 先拆，不跟著連結刪
    iss = open(os.path.join(ROOT, "setup", "installer", "synox.iss"), "rb").read().decode("ascii")
    assert 'Name: "{app}\\runtime"' in iss.split("[UninstallDelete]", 1)[1]
    update = iss.split("[InstallDelete]", 1)[1].split("\r\n[", 1)[0]
    assert 'Name: "{app}\\runtime\\python"' in update and 'Name: "{app}\\.venv"' in update   # 更新時換掉舊的可攜版


# ── 文件 ──────────────────────────────────────────────────────────

def test_adr_0003_explains_the_private_python_default():
    text = _text(os.path.join(ROOT, "docs", "adr", "0003-distribution-git-clone-and-installer.md"))
    addendum = text.split("## 附記（2026-11-13，之二）", 1)[1]
    for word in ("python-build-standalone", PIN["version"], PIN["build"], PIN["sha256"], URL, "tar.exe",
                 "python -m venv", "-UseSystemPython", "Conda", "待實測", "uv"):
        assert word in addendum, word
    assert "已經被下一則附記（之二）取代" in text.split("## 附記（2026-11-13）：", 1)[1]


# ── 字（每個語言都要有；齊不齊由 test_wizard_i18n.test_powershell_tables_complete 檢查）──

NEW_KEYS = ("env_note", "found_conda", "found_store_alias", "found_other_python", "private_python", "system_python",
            "system_python_warning", "venv_outside", "intro_title", "intro_1", "intro_2", "intro_3", "plan_recommended",
            "plan_custom", "plan_question", "custom_title", "custom_autostart", "custom_claude", "custom_all_tools",
            "custom_prompt", "py_download", "py_hash_bad", "py_download_failed", "py_no_tar", "py_extract",
            "py_extract_failed", "py_old_embedded", "py_does_not_run", "py_in_use", "claude_found", "claude_opening",
            "claude_failed", "all_tools_later", "autostart_on", "autostart_failed")
GONE_KEYS = ("embedded", "uv_download", "uv_hash_bad", "uv_python", "uv_failed")


def test_new_messages_exist_in_every_language_and_are_used():
    text = _text(BOOTSTRAP)
    for path in glob.glob(os.path.join(ROOT, "setup", "lang", "*.psd1")):
        body = _text(path)
        keys = set(re.findall(r"^\s*([\w-]+)\s*=\s*'", body, re.M))
        assert set(NEW_KEYS) <= keys, (path, set(NEW_KEYS) - keys)
        assert not set(GONE_KEYS) & keys, path
        assert not re.search(r"\buv\b", body), path                          # 沒有 uv 的字了
    for key in NEW_KEYS:
        assert re.search(r"Tr '%s'" % key, text) or "'%s'" % key in text, key
