# -*- coding: utf-8 -*-
"""審查 B（pack 供應鏈／工具執行）#A：{python} 只能是 SYNOX 自己的直譯器、runtime auto 的 venv 或 pack 裡的；
其他＝pack 外的直譯器（T2）；argv 裡「直譯器直接執行一段程式碼」（-c、-Command、/c、-e…）＝要宣告 exec、T2。
**只組判斷、絕不執行**：subprocess／os.system 換成會丟錯的假貨，powershell 的路徑只當字串比對。"""
import json
import os
import subprocess

import pytest

from conftest import OWNER_ID

from synox.packs import admin, envs, lock, loader, scan as pack_scan, tier
from synox.packs.manifest import ManifestError, read

from test_t2_trust import PUB, _raw, _write

POWERSHELL = "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture(autouse=True)
def _no_exec(monkeypatch):
    """誰開程序就讓測試失敗（掃描、tier、loader 的代換都只能查路徑）。"""
    def boom(*a, **k):
        raise AssertionError(f"不准執行：{a[:1]}")
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(os, "system", boom)


def _cli(tmp_path, tag, argv, commands=None, caps=(), publisher=PUB, files=None, **over):
    raw = _raw(caps=caps, publisher=publisher, argv=argv, **over)
    if commands is not None:
        raw["cli"]["commands"] = commands
    return _write(str(tmp_path / tag), raw, files)


# ── 主審重現：cli.python 指到 powershell ───────────────────────────────

def test_repro_cli_python_powershell_is_refused_at_gate1(tmp_path):
    folder = _cli(tmp_path, "a", ["{python}", "-NoProfile", "-Command", "echo PWNED"])
    with open(os.path.join(folder, "pack.json"), encoding="utf-8") as f:
        raw = json.load(f)
    raw["cli"]["python"] = POWERSHELL
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f)
    with pytest.raises(ManifestError, match="Python 直譯器"):
        read(folder, strict=True)
    with pytest.raises(ManifestError, match="Python 直譯器"):     # 載入時（非嚴格）也一樣擋
        read(folder)
    with pytest.raises(admin.PackAdminError, match="第 1 關"):
        admin.run_gates(folder)


@pytest.mark.parametrize("key", ["python", "python_posix"])
def test_runtime_python_must_be_a_python(tmp_path, key):
    folder = _cli(tmp_path, "a", ["{python}", "./tool.py"], runtime={key: POWERSHELL})
    with pytest.raises(ManifestError, match="Python 直譯器"):
        read(folder, strict=True)
    folder = _cli(tmp_path, "b", ["{python}", "./tool.py"], runtime={key: "../../../Windows/x/python.exe"})
    with pytest.raises(ManifestError, match=r"\.\."):
        read(folder, strict=True)


def test_mcp_stdio_cli_python_is_checked_too(tmp_path):
    raw = {"name": "mx", "title": "M", "summary": "s", "version": "0.1.0", "kind": "mcp", "skill": "SKILL.md",
           "capabilities": ["subprocess"], "cli": {"python": POWERSHELL},
           "mcp": {"transport": "stdio", "argv": ["{python}", "./tool.py"], "tools_allow": ["a"],
                   "effects": {"a": "READ"}}}
    with pytest.raises(ManifestError, match="cli.python"):
        read(_write(str(tmp_path / "m"), raw), strict=True)


def test_repro_powershell_in_argv0_is_t2_and_needs_exec(tmp_path):
    """直接把 powershell 寫在 argv[0]（明確走外部程式）：外部程式＋-Command＝直接執行程式碼 → 要宣告 exec、T2、要 publisher。"""
    folder = _cli(tmp_path, "a", [POWERSHELL, "-NoProfile", "-Command", "echo PWNED"])
    m = read(folder, strict=True)
    report = pack_scan.scan(m)
    problems = report.problems(m)
    assert problems and any("exec" in p and "-Command" in p for p in problems)
    info = tier.assess(m, report)
    assert info["tier"] == tier.T2 and info["needs_publisher"]
    assert POWERSHELL in info["runs"] and any(e.get("inline") for e in info["external"])
    assert any("argv 直接執行程式碼" in line for line in tier.warning_lines(info))
    ok = read(_cli(tmp_path, "b", [POWERSHELL, "-NoProfile", "-Command", "echo PWNED"], caps=("exec",)), strict=True)
    assert pack_scan.scan(ok).problems(ok) == [] and tier.assess(ok)["needs_publisher"]


# ── 直譯器直接執行程式碼的旗標 ─────────────────────────────────────────

@pytest.mark.parametrize("argv,cmd_argv", [
    (["{python}", "-c", "import os"], []),
    (["{python}", "-Ic", "import os"], []),
    (["{python}", "-i"], []),
    (["{python}", "-X", "utf8", "-c", "x"], []),
    (["{python}"], []),                                   # 沒指定程式：讀 stdin
    (["{python}"], ["-c", "x"]),                          # -c 寫在 command 裡
    (["{python}", "-NoProfile", "-Command", "x"], []),   # 看不懂的旗標
    (["{python}", "{script}"], []),                      # 要跑哪支由欄位決定
    (["cmd", "/c", "echo hi"], []),
    (["C:/Windows/System32/cmd.exe", "/K", "x"], []),
    (["powershell", "-enc", "AAAA"], []),
    (["pwsh", "-c", "x"], []),
    (["powershell.exe", "Write-Host hi"], []),
    (["powershell", "/Command", "x"], []),
    (["node", "-e", "x"], []),
    (["{node}", "--eval=x"], []),
    (["bun", "-p", "1"], []),
    (["deno", "eval", "x"], []),
    (["bash", "-lc", "x"], []),
    (["sh", "-c", "x"], []),
    (["ruby", "-e", "x"], []),
    (["perl", "-E", "x"], []),
    (["php", "-r", "x"], []),
    (["osascript", "-e", "x"], []),
    (["cscript", "//E:jscript", "notes.txt"], []),
    (["env", "python3", "-c", "x"], []),
    (["git", "--version"], ["&&", "sh", "-c", "x"]),
])
def test_inline_code_is_detected(tmp_path, argv, cmd_argv):
    fields = [{"name": "script"}] if any("{script}" in a for a in argv) else []
    folder = _cli(tmp_path, "p", argv, commands=[{"name": "run", "effect": "READ", "argv": cmd_argv, "fields": fields}])
    m = read(folder, strict=True)
    assert pack_scan.inline_code(m), argv
    report = pack_scan.scan(m)
    assert any(f.kind == "exec" and f.file == "pack.json" for f in report.findings)
    assert report.problems(m)                                    # 沒宣告 exec＝拒裝
    assert tier.assess(m, report)["tier"] == tier.T2


@pytest.mark.parametrize("argv,cmd_argv", [
    (["{python}", "./tool.py"], ["-c", "x"]),             # -c 在程式後面＝程式自己的參數
    (["{python}", "-u", "-B", "./tool.py"], ["run"]),
    (["{python}", "-m", "tool"], ["-e", "x"]),             # pack 裡的模組
    (["{python}", "{pack_dir}/tool.py"], ["run"]),
    (["{node}", "./server.js"], ["-e", "x"]),
    (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "./x.ps1"], ["run"]),
    (["git", "log"], ["/c", "/k"]),
])
def test_ordinary_argv_is_not_inline(tmp_path, argv, cmd_argv):
    folder = _cli(tmp_path, "p", argv, commands=[{"name": "run", "effect": "READ", "argv": cmd_argv}],
                  files={"server.js": "1", "x.ps1": "1"})
    assert pack_scan.inline_code(read(folder, strict=True)) == []


# ── {python} 解析到 pack 外：記解析後的路徑、T2、進鎖的 t2.external ─────────

def test_cli_python_venv_outside_pack_is_external_and_locked(tmp_path):
    base = tmp_path / "packs"
    raw = _raw(caps=("subprocess",), argv=["{python}", "./tool.py"])
    raw["cli"]["python"] = "venv"
    folder = _write(str(base / "bin"), raw)
    m = read(folder, strict=True)
    venv = os.path.normpath(os.path.join(str(base), ".venv", "Scripts" if os.name == "nt" else "bin"))
    assert envs.python_target(m)[1] == envs.PY_OUTSIDE and loader.cli_python(m).startswith(venv)
    report = pack_scan.scan(m)
    py = [e for e in report.external if e["program"] == "{python}"]
    assert len(py) == 1 and py[0]["resolved"].startswith(venv) and py[0]["where"] == "cli.python"
    assert py[0]["note"] == "未鎖定執行環境" and report.problems(m) == []
    info = tier.assess(m, report)
    assert info["tier"] == tier.T2 and "{python}" in info["runs"]
    data = str(tmp_path / "data")
    assert admin.approve_installed(folder, data, approved_by=OWNER_ID)[2]            # T2：要輸入 publisher
    assert admin.approve_installed(folder, data, approved_by=OWNER_ID, trust_publisher=PUB)[2] == []
    rec = lock.entry(data, "bin")
    assert rec["tier"] == "T2" and rec["t2"]["external"][0]["resolved"].startswith(venv)


def test_runtime_python_sibling_venv_ok_but_external(tmp_path):
    folder = _cli(tmp_path, "a", ["{python}", "./tool.py"],
                  runtime={"python": "../.venv/Scripts/python.exe", "python_posix": "../.venv/bin/python"})
    m = read(folder, strict=True)
    assert [e["program"] for e in pack_scan.externals(m)] == ["{python}"]
    assert tier.assess(m)["tier"] == tier.T2


def test_python_inside_pack_or_synox_is_not_external(tmp_path):
    inside = read(_cli(tmp_path, "a", ["{python}", "./tool.py"],
                       runtime={"python": "venv/Scripts/python.exe", "python_posix": "venv/bin/python"}), strict=True)
    assert envs.python_target(inside)[1] == envs.PY_PACK and pack_scan.python_external(inside) is None
    default = read(_cli(tmp_path, "b", ["{python}", "./tool.py"]), strict=True)
    assert envs.python_target(default)[1] == envs.PY_SYNOX and pack_scan.externals(default) == []
    auto = read(_cli(tmp_path, "c", ["{python}", "./tool.py"], runtime={"python": "auto", "python_posix": "auto"}),
                strict=True)
    assert envs.python_target(auto, str(tmp_path / "data"))[1] == envs.PY_AUTO and pack_scan.python_external(auto) is None


def test_moneybook_fixture_still_passes_but_records_its_python(tmp_path):
    m, report, _h, problems = admin.run_gates(os.path.join(FIXTURES, "moneybook_pack"))
    assert problems == [] and m.capabilities == ["subprocess"]
    programs = [e["program"] for e in report.external]
    assert programs == ["{python}", "-m moneybook"] and report.external[0]["where"].startswith("runtime.python")


@pytest.mark.parametrize("script", ["{data_dir}/x.py", "C:/evil/x.py", "{pack_dir}/../x.py"])
def test_script_outside_pack_is_external(tmp_path, script):
    m = read(_cli(tmp_path, "a", ["{python}", script]), strict=True)
    assert script in pack_scan.external_programs(m)


# ── 以前的誤判：/c、/k 這種 Windows 旗標不是絕對路徑 ─────────────────────

def test_windows_flags_are_not_paths(tmp_path):
    m = read(_cli(tmp_path, "a", ["git", "/c", "/k", "/s"]), strict=True)
    assert pack_scan.external_programs(m) == ["git"]
    m = read(_cli(tmp_path, "b", ["git", "C:/tools/x.js", "/usr/local/bin/tool"]), strict=True)
    assert pack_scan.external_programs(m) == ["git", "C:/tools/x.js", "/usr/local/bin/tool"]
