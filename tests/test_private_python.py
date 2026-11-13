"""Setup.bat 預設用 SYNOX 自己的 Python（uv 裝在 runtime\\ 裡），不碰這台電腦的 Conda／Store／其他 Python
（docs/adr/0003 附記「預設用 SYNOX 自己的 Python」）。這台是 Linux：全部是讀檔的靜態檢查，不跑 PowerShell、不連網。"""

import glob
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOTSTRAP = os.path.join(ROOT, "setup", "bootstrap.ps1")
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


# ── 釘死的 uv ─────────────────────────────────────────────────────

def test_uv_is_pinned_with_sha256_from_the_official_release():
    text = _text(BOOTSTRAP)
    version = re.search(r"^\$UvVersion = '(\d+\.\d+\.\d+)'", text, re.M)
    sha = re.search(r"^\$UvSha256 = '([0-9a-f]{64})'", text, re.M)
    assert version and sha
    assert version.group(1) == "0.13.6"
    assert sha.group(1) == "a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f"
    assert ('$UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip"'
            in text)
    body = _function(text, "Install-Uv")
    assert "Get-FileHash" in body and "SHA256" in body and "$UvSha256" in body
    assert body.index("Get-FileHash") < body.index("Expand-Archive")          # 先驗再解開


def test_uv_only_uses_its_own_python_inside_the_synox_folder():
    text = _text(BOOTSTRAP)
    assert "$Runtime = Join-Path $Root 'runtime'" in text
    assert "$UvPythonDir = Join-Path $Runtime 'python-uv'" in text
    assert "$UvCache = Join-Path $Runtime 'uv-cache'" in text
    env = _function(text, "Set-UvEnv")
    for line in ("$env:UV_PYTHON_INSTALL_DIR = $UvPythonDir", "$env:UV_CACHE_DIR = $UvCache",
                 "$env:UV_PYTHON_PREFERENCE = 'only-managed'", "$env:UV_NO_CONFIG = '1'"):
        assert line in env, line
    body = _function(text, "Install-UvPython")
    install = next(line for line in body.splitlines() if "python install" in line)
    for flag in ("--python-preference only-managed", "--no-bin", "--no-registry"):   # 不寫 ~\.local\bin、不寫登錄檔
        assert flag in install, flag
    assert "Set-UvEnv" in body and "$UvPythonDir" in body


# ── 預設與進階 ────────────────────────────────────────────────────

def test_default_path_never_uses_winget_or_the_users_python():
    text = _text(BOOTSTRAP)
    private = _code(_function(text, "Get-PrivatePython"))
    assert "winget" not in private.lower()
    for other in ("Get-Command", "'py'", "Programs\\Python", "Find-SystemPython"):
        assert other not in private, other
    assert private.index("runtime\\python\\python.exe") < private.index("Install-UvPython") < private.index("Install-Embedded")
    # winget 只在 -UseSystemPython 的那條路上
    callers = [m.start() for m in re.finditer(r"Install-WithWinget", _code(text))]
    system = _code(_function(text, "Get-SystemPython"))
    assert "Install-WithWinget" in system
    assert len(callers) == 2                                                  # 定義＋Get-SystemPython 裡那一次
    main = _code(text.split("\ntry {", 1)[1])
    assert re.search(r"if \(\$UseSystemPython\) \{[^}]*Get-SystemPython", main)
    assert "Get-PrivatePython" in main


def test_use_system_python_is_a_switch_and_setup_bat_passes_it_through():
    text = _text(BOOTSTRAP)
    assert re.search(r"^param\(.*\[switch\]\$UseSystemPython.*\)", text, re.M)
    bat = open(os.path.join(ROOT, "Setup.bat"), "rb").read().decode("ascii")
    assert re.search(r'setup\\bootstrap\.ps1" %\*', bat)                       # 參數原樣交給 bootstrap
    assert "-UseSystemPython" in bat                                         # 註解說得出這個選項


def test_system_python_never_picks_the_store_alias():
    text = _text(BOOTSTRAP)
    find = _code(_function(text, "Find-SystemPython"))
    assert "Test-StoreAlias" in find
    alias = _function(text, "Test-StoreAlias")
    assert "\\WindowsApps\\" in alias
    assert "runtime\\python\\python.exe" in find                              # 舊的順序：SYNOX 自己帶的還是第一個


def test_fallback_to_embeddable_zip_is_said_plainly():
    text = _text(BOOTSTRAP)
    private = _function(text, "Get-PrivatePython")
    assert "Tr 'uv_failed'" in private


def test_notes_about_conda_store_and_other_pythons_before_cleaning():
    text = _text(BOOTSTRAP)
    find = _function(text, "Find-OtherPythons")
    for clue in ("CONDA_PREFIX", "CONDA_EXE", "conda", "Microsoft\\WindowsApps\\python.exe"):
        assert clue in find, clue
    for key in ("found_conda", "found_store_alias", "found_other_python"):
        assert "Tr '%s'" % key in find, key
    main = _code(text.split("\ntry {", 1)[1])
    assert main.index("Find-OtherPythons") < main.index("Clear-PythonEnv")   # 先看線索、再清
    assert "Tr 'env_note'" in main


def test_bootstrap_clears_python_and_conda_variables_for_its_own_process():
    body = _function(_text(BOOTSTRAP), "Clear-PythonEnv")
    for name in PYTHON_NOISE:
        assert "'%s'" % name in body, name
    assert "'CONDA_*'" in body and "Env:" in body


# ── 啟動器 ────────────────────────────────────────────────────────

def test_clean_env_helper_clears_python_and_conda_variables():
    raw = open(CLEAN_ENV, "rb").read()
    raw.decode("ascii")
    assert b"\r\n" in raw
    text = raw.decode("ascii")
    for name in PYTHON_NOISE:
        assert 'set "%s="' % name in text, name
    assert re.search(r"set CONDA_ 2\^>nul", text)                             # 每一個 CONDA_* 都清
    assert "setlocal" not in text.lower()                                     # 要改到呼叫它的那個視窗


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
    assert "ReparsePoint" in body and "Remove-Path $Runtime" in body          # 先拆 junction，不跟著連結刪
    iss = open(os.path.join(ROOT, "setup", "installer", "synox.iss"), "rb").read().decode("ascii")
    assert 'Name: "{app}\\runtime"' in iss.split("[UninstallDelete]", 1)[1]


# ── 文件 ──────────────────────────────────────────────────────────

def test_adr_0003_explains_the_private_python_default():
    text = _text(os.path.join(ROOT, "docs", "adr", "0003-distribution-git-clone-and-installer.md"))
    addendum = text.split("## 附記（2026-11-13）", 1)[1]
    for word in ("uv", "0.13.6", "only-managed", "Conda", "Microsoft Store", "winget", "-UseSystemPython", "待實測"):
        assert word in addendum, word


# ── 字（每個語言都要有；齊不齊由 test_wizard_i18n.test_powershell_tables_complete 檢查）──

NEW_KEYS = ("env_note", "found_conda", "found_store_alias", "found_other_python", "private_python", "uv_download",
            "uv_hash_bad", "uv_python", "uv_failed", "system_python", "system_python_warning", "venv_outside")


def test_new_messages_exist_in_every_language_and_are_used():
    text = _text(BOOTSTRAP)
    for path in glob.glob(os.path.join(ROOT, "setup", "lang", "*.psd1")):
        keys = set(re.findall(r"^\s*([\w-]+)\s*=\s*'", _text(path), re.M))
        assert set(NEW_KEYS) <= keys, (path, set(NEW_KEYS) - keys)
    for key in NEW_KEYS:
        assert "Tr '%s'" % key in text, key
