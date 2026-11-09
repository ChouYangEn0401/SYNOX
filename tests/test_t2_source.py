# -*- coding: utf-8 -*-
"""P7 補（2026-11-09 擁有者決定）：別的語言的原始碼一律算「掃不到內容的檔」（T2）、{node}／node／deno… 這類直譯器
算 pack 外的程式；synox-sdk check 印信任層級與「安裝一定會被擋」的問題；讀 SYNOX 自己注入的協定變數不再標「可能是密鑰」。
**絕不執行**任何東西：直譯器只用（換掉的）shutil.which 查路徑，subprocess 被換成會丟錯的假貨。"""
import json
import os
import subprocess

import pytest

from synox.packs import admin, scan as pack_scan, tier
from synox.packs.manifest import read
from synox.packs.scan import opaque_files, scan, scan_source
from synox.sdk import Pack
from synox.sdk import main as sdk_main

from test_t2_trust import PUB, _raw, _stage, _write

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
JS = "// SPDX-License-Identifier: Apache-2.0\nconsole.log('hi');\n"


@pytest.fixture(autouse=True)
def _no_exec(monkeypatch):
    """掃描與 check 只能查路徑：誰開程序就讓測試失敗。"""
    def boom(*a, **k):
        raise AssertionError(f"不准執行：{a[:1]}")
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(os, "system", boom)


@pytest.fixture
def fake_which(monkeypatch):
    found = {"node": r"C:\fake\nodejs\node.exe", "deno": "/opt/deno", "bun": "/opt/bun", "ruby": "/usr/bin/ruby",
             "perl": "/usr/bin/perl", "php": "/usr/bin/php", "npx": "/usr/bin/npx"}
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: found.get(name))
    return found


# ── 別的語言的原始碼＝掃不到內容的檔 ───────────────────────────────────

@pytest.mark.parametrize("name", ["server.js", "a.mjs", "a.cjs", "a.ts", "ui/App.tsx", "ui/App.jsx", "x.rb", "x.pl",
                                  "x.php", "x.lua", "main.go", "lib.rs", "Main.java", "Main.kt", "Prog.cs", "x.vbs",
                                  "x.ps1", "Mod.psm1", "x.bat", "x.cmd", "x.sh", "x.bash", "x.zsh", "SERVER.JS"])
def test_other_language_source_is_opaque(tmp_path, name):
    folder = _write(str(tmp_path / "p"), _raw(), {name: JS})
    opaque = opaque_files(folder)
    assert [o["path"] for o in opaque] == [name] and len(opaque[0]["sha256"]) == 64


def test_source_ext_list_is_extensible_and_all_counted():
    assert set(pack_scan.SOURCE_EXT) <= set(pack_scan.OPAQUE_EXT) <= set(pack_scan.CODE_EXT)
    assert all(e.startswith(".") and e == e.lower() for e in pack_scan.SOURCE_EXT)
    assert ".py" not in pack_scan.OPAQUE_EXT


def test_data_files_stay_t1(tmp_path):
    folder = _write(str(tmp_path / "p"), _raw(publisher=None),
                    {"README.md": "x", "data.json": "{}", "notes.txt": "console.log()", "panel.html": "<p>hi</p>"})
    assert opaque_files(folder) == []
    m = read(folder, strict=True)
    assert tier.assess(m, scan(m))["tier"] == tier.T1


def test_js_without_exec_is_refused(tmp_path):
    with pytest.raises(admin.GateRefused) as e:
        _stage(tmp_path, "a", _raw(), {"tool.js": JS})
    assert "exec" in str(e.value) and "tool.js" in str(e.value)
    assert "別的語言的原始碼" in admin.format_summary(e.value.summary)


def test_js_with_exec_is_t2_and_needs_publisher(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, summary = _stage(tmp_path, "a", _raw(caps=("subprocess", "exec")), {"tool.rb": JS})
    assert summary["tier"]["tier"] == "T2" and summary["tier"]["runs"] == ["tool.rb"]
    with pytest.raises(admin.PackAdminError):
        admin.install_staged(token, data, packs)                                 # 沒輸入 publisher
    admin.install_staged(token, data, packs, trust_publisher=PUB)


def test_js_t2_without_publisher_cannot_install(tmp_path):
    token, _summary = _stage(tmp_path, "a", _raw(caps=("subprocess", "exec"), publisher=None), {"tool.ts": JS})
    with pytest.raises(admin.PackAdminError) as e:
        admin.install_staged(token, str(tmp_path / "data"), str(tmp_path / "packs"), trust_publisher="x")
    assert "publisher" in str(e.value)


def test_registered_only_mcp_with_js_is_refused(tmp_path):
    raw = {"name": "reg", "title": "R", "summary": "s", "version": "0.1.0", "kind": "mcp", "skill": "SKILL.md",
           "capabilities": ["network"], "mcp": {"url": "https://example.com/mcp", "tools_allow": ["a"],
                                                 "effects": {"a": "READ"}}}
    folder = _write(str(tmp_path / "p"), raw, {"x.js": JS})
    m = read(folder, strict=True)
    assert any(f.kind == "code" and f.file == "x.js" for f in scan(m).findings)


# ── 直譯器在 argv：pack 外的程式（只查路徑） ───────────────────────────

def test_node_placeholder_is_external_with_resolved_path(tmp_path, fake_which):
    folder = _write(str(tmp_path / "p"), _raw(caps=("subprocess", "exec"), argv=["{node}", "./tool.js"]),
                    {"tool.js": JS})
    m = read(folder, strict=True)
    report = scan(m)
    assert [(e["program"], e.get("interpreter")) for e in report.external] == [("{node}", "node")]
    assert report.external[0]["resolved"].startswith(fake_which["node"])
    assert report.external[0]["note"] == "未鎖定執行環境"
    info = tier.assess(m, report)
    assert info["tier"] == tier.T2 and "{node}" in info["runs"] and "tool.js" in info["runs"]
    assert any("直譯器 node" in line for line in tier.warning_lines(info))


@pytest.mark.parametrize("prog", ["node", "npx", "deno", "bun", "ruby", "perl", "php"])
def test_interpreter_as_program_is_external(tmp_path, fake_which, prog):
    folder = _write(str(tmp_path / "p"), _raw(caps=("subprocess",), argv=[prog, "--version"]))
    m = read(folder, strict=True)
    ext = scan(m).external
    assert [e["program"] for e in ext] == [prog] and ext[0]["interpreter"] == prog
    assert ext[0]["resolved"].startswith(fake_which[prog])
    assert tier.assess(m)["tier"] == tier.T2


def test_interpreter_later_in_argv_is_recorded(tmp_path, fake_which):
    folder = _write(str(tmp_path / "p"), _raw(caps=("subprocess",), argv=["env", "node.exe", "x"]))
    m = read(folder, strict=True)
    ext = scan(m).external
    assert [e["program"] for e in ext] == ["env", "node.exe"] and ext[1]["interpreter"] == "node"
    assert "interpreter" not in ext[0]


def test_mcp_stdio_node_is_external(tmp_path, fake_which):
    raw = {"name": "nm", "title": "N", "summary": "s", "version": "0.1.0", "kind": "mcp", "skill": "SKILL.md",
           "publisher": PUB, "capabilities": ["subprocess", "exec"],
           "mcp": {"transport": "stdio", "argv": ["{node}", "./server.js"], "tools_allow": ["a"],
                   "effects": {"a": "READ"}}}
    folder = _write(str(tmp_path / "p"), raw, {"server.js": JS})
    m = read(folder, strict=True)
    report = scan(m)
    assert [e["where"] for e in report.external] == ["mcp.argv"] and report.problems(m) == []
    assert tier.assess(m, report)["tier"] == tier.T2


def test_python_is_still_not_external(tmp_path):
    folder = _write(str(tmp_path / "p"), _raw(publisher=None))
    assert scan(read(folder, strict=True)).external == []


# ── 範例：node-mcp-tool 是 T2；遠端 MCP 是 T0 ─────────────────────────

def test_node_example_is_t2(fake_which):
    check = Pack.load(os.path.join(EXAMPLES, "node-mcp-tool"))
    info = check.tier
    assert info["tier"] == tier.T2 and [o["path"] for o in info["opaque"]] == ["server.js"]
    assert info["external"][0]["program"] == "{node}" and check.ok


def test_remote_mcp_example_is_t0():
    assert Pack.load(os.path.join(EXAMPLES, "mcp-remote-notion")).tier["tier"] == tier.T0


# ── synox-sdk check：輸出與結束碼 ─────────────────────────────────────

def _check(folder, capsys):
    code = sdk_main(["check", folder])
    return code, capsys.readouterr().out


def test_check_t2_without_publisher_exits_nonzero(tmp_path, capsys, fake_which):
    folder = _write(str(tmp_path / "p"), _raw(caps=("subprocess", "exec"), publisher=None), {"tool.js": JS})
    code, out = _check(folder, capsys)
    assert code != 0
    assert "信任層級：T2" in out and "tool.js" in out and "掃不到內容的檔案（1 個" in out
    assert "⚠️ T2 沒寫 publisher" in out and "安裝一定會被擋" in out


def test_check_t2_with_publisher_ok(tmp_path, capsys):
    folder = _write(str(tmp_path / "p"), _raw(caps=("subprocess", "exec")), {"tool.js": JS})
    code, out = _check(folder, capsys)
    assert code == 0 and f"publisher：{PUB}" in out and "✅ 可以裝（T2" in out


def test_check_undeclared_exec_exits_nonzero(tmp_path, capsys):
    folder = _write(str(tmp_path / "p"), _raw(), {"tool.go": JS})
    code, out = _check(folder, capsys)
    assert code != 0 and "安裝一定會被擋" in out and "exec" in out


def test_check_t1_lists_nothing_opaque(tmp_path, capsys):
    folder = _write(str(tmp_path / "p"), _raw(publisher=None))
    code, out = _check(folder, capsys)
    assert code == 0 and "信任層級：T1" in out and "掃不到內容的檔案：（沒有）" in out and "requires.pip：（沒寫）" in out


def test_check_mcp_lists_tools_and_effects(capsys, fake_which):
    code, out = _check(os.path.join(EXAMPLES, "node-mcp-tool"), capsys)
    assert code == 0 and "count_words（READ）" in out and "roll_dice（READ）" in out and "直譯器 node" in out
    code, out = _check(os.path.join(EXAMPLES, "mcp-remote-notion"), capsys)
    assert code == 0 and "信任層級：T0" in out and "update-page（DANGER）" in out


def test_check_pip_pinned_and_unpinned(tmp_path, capsys):
    loose = _write(str(tmp_path / "loose"), _raw(publisher=None, requires={"pip": ["requests>=2"]}))
    code, out = _check(loose, capsys)
    assert code == 0 and "requires.pip 沒釘死" in out and "requests>=2" in out and "不是 auto" in out
    pinned = _write(str(tmp_path / "pinned"), _raw(requires={"pip": ["idna==3.7"]}, runtime={"python": "auto"}))
    code, out = _check(pinned, capsys)
    assert code == 0 and "requires.pip：都釘死了（idna==3.7）" in out and "信任層級：T2" in out


# ── 第 2 關：SYNOX 自己注入的協定變數不算「可能是密鑰」 ─────────────────

def _env_findings(src):
    return [f for f in scan_source("t.py", src) if f.kind == "env"]


@pytest.mark.parametrize("name", ["SYNOX_USER_DATA_DIR", "SYNOX_TG_ID", "SYNOX_MODE", "SYNOX_PACK_DIR",
                                  "SYNOX_PACK_NAME", "SYNOX_CONFIRMED"])
def test_protocol_env_not_flagged(name):
    src = f"import os\na = os.environ.get('{name}', '')\nb = os.getenv('{name}')\nc = os.environ['{name}']\n"
    assert _env_findings(src) == []
    # from os import getenv 那一行照舊列（只看 import 看不出讀哪個）；呼叫本身讀協定變數不列
    assert [f.line for f in _env_findings(f"from os import getenv\nd = getenv('{name}')\n")] == [1]


@pytest.mark.parametrize("name", ["SYNOX_CONFIRM_TOKEN", "SYNOX_SECRET_ENV", "API_KEY", "SYNOX_SOMETHING_ELSE"])
def test_other_env_still_flagged(name):
    assert len(_env_findings(f"import os\na = os.environ.get('{name}')\n")) >= 1
    assert len(_env_findings(f"import os\na = os.environ['{name}']\n")) == 1
    assert len(_env_findings(f"import os\na = os.getenv('{name}')\n")) == 1


def test_env_by_variable_and_whole_environ_still_flagged():
    assert _env_findings("import os\nn = 'SYNOX_MODE'\na = os.environ.get(n)\n")
    assert _env_findings("import os\nall_env = dict(os.environ)\n")


def test_any_language_cli_example_only_flags_confirm_token():
    m = read(os.path.join(EXAMPLES, "any-language-cli"), strict=True)
    env = [f for f in scan(m).findings if f.kind == "env"]
    assert env and all("SYNOX_CONFIRM_TOKEN" in f.snippet for f in env)
    with open(os.path.join(EXAMPLES, "any-language-cli", "tool.py"), "r", encoding="utf-8") as f:
        assert json.dumps("SYNOX_USER_DATA_DIR")[1:-1] in f.read()            # 範例真的有讀協定變數（而且沒被列）
