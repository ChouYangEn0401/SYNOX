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


# ── C2：pack 寫的環境變數讓合法的直譯器先載入 pack 外的程式 ─────────────

BAD_ENV = [("PYTHONPATH", "C:/Users/Public/x"), ("PYTHONPATH", "{data_dir}/x"), ("PYTHONPATH", "{user_data_dir}/x"),
           ("PYTHONPATH", "{pack_dir}/../x"), ("PYTHONPATH", "{pack_dir}/lib;C:/x"), ("PYTHONHOME", "C:/x"),
           ("PYTHONUSERBASE", "{user_data_dir}"), ("PYTHONSTARTUP", "{pack_dir}/x.py"), ("PythonPath", "C:/x"),
           ("NODE_OPTIONS", "--require C:/x.js"), ("NODE_PATH", "C:/x"), ("PATH", "{user_data_dir}/bin"),
           ("Path", "C:/x"), ("PATHEXT", ".PY"), ("COMSPEC", "C:/x.exe"), ("SYSTEMROOT", "C:/x"),
           ("LD_PRELOAD", "/tmp/x.so"), ("DYLD_INSERT_LIBRARIES", "/tmp/x.dylib"), ("PIP_INDEX_URL", "https://evil"),
           ("npm_config_registry", "https://evil"), ("PERL5OPT", "-Mx"), ("BASH_ENV", "/tmp/x"),
           ("A=B", "x")]


@pytest.mark.parametrize("key, value", BAD_ENV)
@pytest.mark.parametrize("where", ["cli.env", "env"])
def test_c2_repro_banned_env_names_refused_at_gate1(tmp_path, key, value, where):
    """修之前：這些都 T1、零 finding（Python 啟動時會先 import PYTHONPATH 裡的 sitecustomize.py…）。"""
    raw = _raw(caps=(), publisher=PUB)
    if where == "cli.env":
        raw["cli"]["env"] = {key: value}
    else:
        raw["env"] = {key: value}
    folder = _write(str(tmp_path / "a"), raw)
    with pytest.raises(ManifestError):
        read(folder, strict=True)
    with pytest.raises(ManifestError):                     # 載入時（非嚴格）也一樣：已經裝好的舊 pack 不載入
        read(folder)


@pytest.mark.parametrize("key, value", BAD_ENV[:12])
def test_c2_banned_env_names_in_mcp_env(tmp_path, key, value):
    raw = {"name": "mx", "title": "M", "summary": "s", "version": "0.1.0", "kind": "mcp", "skill": "SKILL.md",
           "capabilities": ["subprocess"], "publisher": PUB,
           "mcp": {"transport": "stdio", "argv": ["{python}", "./tool.py"], "env": {key: value},
                   "tools_allow": ["a"], "effects": {"a": "READ"}}}
    with pytest.raises(ManifestError):
        read(_write(str(tmp_path / "m"), raw), strict=True)


def test_c2_banned_env_name_in_auth_fields(tmp_path):
    raw = _raw(caps=(), publisher=PUB, auth={"type": "token", "fields": [{"name": "k", "secret": True,
                                                                           "env": "PYTHONPATH"}]})
    with pytest.raises(ManifestError, match="PYTHONPATH"):
        read(_write(str(tmp_path / "a"), raw), strict=True)


@pytest.mark.parametrize("key, value", [("PYTHONIOENCODING", "utf-8"), ("PYTHONUTF8", "1"), ("PYTHONUNBUFFERED", "1"),
                                        ("PYTHONPATH", "{pack_dir}"), ("PYTHONPATH", "{pack_dir}/lib"),
                                        ("MONEYBOOK_HOME", "{user_data_dir}/moneybook"), ("HOME_DIR", "{data_dir}/x")])
def test_c2_harmless_env_names_still_fine(tmp_path, key, value):
    raw = _raw(caps=(), publisher=PUB)
    raw["cli"]["env"] = {key: value}
    m = read(_write(str(tmp_path / "a"), raw), strict=True)
    assert key in loader.cli_env(m, loader.placeholders(m, _Config(str(tmp_path / "data"))))


class _Config:
    def __init__(self, data_dir):
        self.data_dir, self.mode, self.owner_id = data_dir, "personal", 1


def test_c2_loader_filters_banned_env_even_if_gate1_was_skipped(tmp_path):
    """防禦深度：就算 manifest 被繞過（例如舊版寫的物件），cli_env 也不把 PYTHONPATH（pack 外）、NODE_OPTIONS 交給子程序。"""
    m = read(_write(str(tmp_path / "a"), _raw(caps=(), publisher=PUB)), strict=True)
    m.cli["env"] = {"PYTHONPATH": "C:/Users/Public/x", "NODE_OPTIONS": "--require x", "OK_NAME": "1"}
    env = loader.cli_env(m, loader.placeholders(m, _Config(str(tmp_path / "data"))))
    assert "PYTHONPATH" not in env and "NODE_OPTIONS" not in env and env["OK_NAME"] == "1"


def test_c2_children_do_not_read_user_site(tmp_path):
    m = read(_write(str(tmp_path / "a"), _raw(caps=(), publisher=PUB)), strict=True)
    config = _Config(str(tmp_path / "data"))
    env = loader.context_env(m, config, loader.placeholders(m, config))
    assert env["PYTHONNOUSERSITE"] == "1" and env["PYTHONDONTWRITEBYTECODE"] == "1"
