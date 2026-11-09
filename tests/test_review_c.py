# -*- coding: utf-8 -*-
"""審查 C（獨立驗證審查）的修補：每一項先重現原本的繞法，再確認修好之後被擋或升級成 T2。
**只組判斷、絕不執行**：subprocess／os.system 換成會丟錯的假貨；「惡意」樣本只是寫進暫存資料夾的字串，
第 2 關只用 ast 解析它們；UNC 路徑只做字串判斷，不碰檔案系統、不連網。"""
import os
import subprocess

import pytest

from synox.packs import loader, scan as pack_scan, tier
from synox.packs.manifest import ManifestError, read

from test_t2_trust import PUB, _raw, _write

EVIL_PY = "import os\nos.system('calc')\n"          # 只當字串寫進檔案；從來不執行


@pytest.fixture(autouse=True)
def _no_exec(monkeypatch):
    def boom(*a, **k):
        raise AssertionError(f"不准執行：{a[:1]}")
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(os, "system", boom)


def _cli(tmp_path, tag, argv, caps=(), files=None, commands=None, **over):
    raw = _raw(caps=caps, publisher=PUB, argv=argv, **over)
    if commands is not None:
        raw["cli"]["commands"] = commands
    return _write(str(tmp_path / tag), raw, files)


def _gate(folder):
    m = read(folder, strict=True)
    report = pack_scan.scan(m)
    return m, report, report.problems(m), tier.assess(m, report)


# ── C1：{python} 後面接的不是 .py ───────────────────────────────────────

@pytest.mark.parametrize("script, files", [
    ("./run.txt", {"run.txt": EVIL_PY}),
    ("./app.pyz", {"app.pyz": b"PK\x05\x06" + b"\x00" * 18}),     # 空 zip 的檔尾（只是位元組）
    ("./app.zip", {"app.zip": b"PK\x05\x06" + b"\x00" * 18}),
    ("./run", {"run": EVIL_PY}),
    ("{pack_dir}/run.txt", {"run.txt": EVIL_PY}),
    ("./app", {"app/notes.txt": "x"}),                             # 資料夾但沒有 __main__.py
])
def test_c1_repro_python_running_a_non_py_file_is_refused(tmp_path, script, files):
    """修之前：五種寫法都是 T1、零 finding、零 opaque、不用 publisher。修之後：第 2 關一定擋（argv）。"""
    m, report, problems, _info = _gate(_cli(tmp_path, "a", ["{python}", script], files=files))
    blocking = [f for f in report.findings if f.kind == "argv"]
    assert blocking and ("不是 .py" in blocking[0].detail or "__main__.py" in blocking[0].detail)
    assert problems
    with pytest.raises(ManifestError):                     # 已經裝好的舊 pack：載入時也拒
        loader.refuse_blocked_argv(m)


def test_c1_pyw_is_scanned_as_python(tmp_path):
    m, report, problems, info = _gate(_cli(tmp_path, "a", ["{python}", "./run.pyw"], files={"run.pyw": EVIL_PY}))
    assert any(f.kind == "subprocess" and f.file == "run.pyw" for f in report.findings)
    assert any("subprocess" in p for p in problems)        # 沒宣告就拒裝
    m, report, problems, info = _gate(_cli(tmp_path, "b", ["{python}", "./run.pyw"],
                                           files={"run.pyw": "print('hi')\n"}))
    assert problems == [] and info["tier"] == tier.T1


def test_c1_folder_with_main_py_is_fine(tmp_path):
    m, report, problems, info = _gate(_cli(tmp_path, "a", ["{python}", "./app"],
                                           files={"app/__main__.py": "print('hi')\n"}))
    assert problems == [] and info["tier"] == tier.T1
    loader.refuse_blocked_argv(m)                          # 不丟


@pytest.mark.parametrize("name", ["lib.whl", "inner.zip", "app.pyz", "x.egg", "y.pyzw"])
def test_c1_archives_are_opaque(tmp_path, name):
    """修之前：zip／wheel 放在 pack 裡不算掃不到的檔（搭配 sys.path.insert(0, 'lib.whl') 就能 import 裡面的程式）。"""
    m, report, problems, info = _gate(_cli(tmp_path, "a", ["{python}", "./tool.py"],
                                           files={name: b"PK\x05\x06" + b"\x00" * 18}))
    assert [o["path"] for o in report.opaque] == [name]
    assert info["tier"] == tier.T2 and any("exec" in p for p in problems)


def test_c1_extensionless_python_is_scanned_but_plain_text_is_data(tmp_path):
    m, report, problems, info = _gate(_cli(tmp_path, "a", ["{python}", "./tool.py"],
                                           files={"helper": "import socket\n", "LICENSE": "MIT License\n\nCopyright (c) x\n"}))
    assert any(f.kind == "network" and f.file == "helper" for f in report.findings)
    assert not any(f.file == "LICENSE" for f in report.findings) and report.opaque == []


def test_c1_script_chosen_by_a_field_counts_as_inline(tmp_path):
    """./{script}.py：要跑哪個檔由使用者填（值可以帶 ..）→ 掃不到，要宣告 exec、T2。"""
    commands = [{"name": "run", "effect": "READ", "argv": ["./{script}.py"], "fields": [{"name": "script"}]}]
    m, report, problems, info = _gate(_cli(tmp_path, "a", ["{python}"], commands=commands))
    assert any(f.kind == "exec" for f in report.findings) and info["tier"] == tier.T2


def test_c1_mcp_stdio_script_must_be_py(tmp_path):
    raw = {"name": "mx", "title": "M", "summary": "s", "version": "0.1.0", "kind": "mcp", "skill": "SKILL.md",
           "capabilities": ["subprocess"], "publisher": PUB,
           "mcp": {"transport": "stdio", "argv": ["{python}", "./server.txt"], "tools_allow": ["a"],
                   "effects": {"a": "READ"}}}
    m = read(_write(str(tmp_path / "m"), raw, {"server.txt": EVIL_PY}), strict=True)
    assert any(f.kind == "argv" for f in pack_scan.scan(m).findings)
    with pytest.raises(ManifestError):
        loader.refuse_blocked_argv(m)


def test_c1_existing_examples_still_t1(tmp_path):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    m, report, problems, info = _gate(os.path.join(here, "examples", "hello"))
    assert problems == [] and info["tier"] == tier.T1
