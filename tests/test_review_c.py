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


# ── C3：{python} -m X ＋ cwd 在使用者資料夾 ─────────────────────────────

@pytest.mark.parametrize("cwd", ["{user_data_dir}", "{data_dir}/x", "{user_data_dir}/moneybook", "C:/Users/Public",
                                 "..", "{pack_dir}/..", "{pack_dir}x"])
def test_c3_repro_dash_m_with_cwd_outside_pack_is_refused(tmp_path, cwd):
    """修之前：T1、零 finding；python -m tool 的 sys.path[0] 是 cwd，使用者資料夾裡的 tool.py 會先被載入。"""
    raw = _raw(caps=(), publisher=PUB, argv=["{python}", "-m", "tool"])
    raw["cli"]["cwd"] = cwd
    raw["data"] = "shared" if "{data_dir}" in cwd else "user" if "{user_data_dir}" in cwd else "none"
    m = read(_write(str(tmp_path / "a"), raw), strict=True)
    report = pack_scan.scan(m)
    assert any(f.kind == "argv" and "-m" in f.detail for f in report.findings), report.findings
    assert report.problems(m)
    with pytest.raises(ManifestError, match="cwd"):
        loader.refuse_blocked_argv(m)


@pytest.mark.parametrize("cwd", [None, ".", "./sub", "{pack_dir}", "{pack_dir}/sub"])
def test_c3_dash_m_with_cwd_in_pack_is_fine(tmp_path, cwd):
    raw = _raw(caps=(), publisher=PUB, argv=["{python}", "-m", "tool"])
    if cwd is not None:
        raw["cli"]["cwd"] = cwd
    m = read(_write(str(tmp_path / "a"), raw, {"sub/x.txt": "x"}), strict=True)
    assert not [f for f in pack_scan.scan(m).findings if f.kind == "argv"]
    loader.refuse_blocked_argv(m)


def test_c3_script_mode_with_cwd_in_user_folder_is_still_fine(tmp_path):
    """{python} ./tool.py：sys.path[0] 是腳本所在的資料夾（pack 裡），cwd 在哪都不影響 import。"""
    raw = _raw(caps=(), publisher=PUB, argv=["{python}", "./tool.py"], data="user")
    raw["cli"]["cwd"] = "{user_data_dir}"
    m = read(_write(str(tmp_path / "a"), raw), strict=True)
    assert pack_scan.scan(m).problems(m) == []


def test_c3_mcp_stdio_dash_m_cwd(tmp_path):
    raw = {"name": "mx", "title": "M", "summary": "s", "version": "0.1.0", "kind": "mcp", "skill": "SKILL.md",
           "capabilities": ["subprocess"], "publisher": PUB, "data": "user",
           "mcp": {"transport": "stdio", "argv": ["{python}", "-m", "tool"], "cwd": "{user_data_dir}",
                   "tools_allow": ["a"], "effects": {"a": "READ"}}}
    m = read(_write(str(tmp_path / "m"), raw), strict=True)
    assert any(f.kind == "argv" for f in pack_scan.scan(m).findings)


def test_c3_moneybook_convention_unchanged(tmp_path):
    """金流簿：{python} -m moneybook、cwd "."（pack 資料夾）→ 照舊（T2，因為 ../.venv 在 pack 外），沒有新的擋。"""
    here = os.path.dirname(os.path.abspath(__file__))
    m = read(os.path.join(here, "fixtures", "moneybook_pack"), strict=True)
    assert pack_scan.argv_blocked(m) == []
    loader.refuse_blocked_argv(m)


# ── C4：UNC／裝置路徑在安裝者按確認之前就被碰 ─────────────────────────────

UNC = [r"\\attacker\share\python.exe", "//attacker/share/python.exe", r"\\?\C:\x\python.exe",
       r"\\.\pipe\python.exe", r"\??\UNC\attacker\s\python.exe", r"\/attacker/share/python.exe"]


@pytest.fixture
def no_network_paths(monkeypatch):
    """碰到 UNC 路徑的 realpath／exists／isfile／isdir／stat 一律讓測試失敗（真的不連網：只是攔下來）。"""
    from synox.packs.manifest import unc_like
    for mod, name in ((os.path, "realpath"), (os.path, "exists"), (os.path, "isfile"), (os.path, "isdir"),
                      (os, "stat")):
        real = getattr(mod, name)

        def guard(p, *a, _real=real, _name=name, **k):
            if isinstance(p, str) and unc_like(p):
                raise AssertionError(f"{_name} 碰了網路路徑：{p}")
            return _real(p, *a, **k)
        monkeypatch.setattr(mod, name, guard)


def _c4_raw(**over):
    raw = _raw(caps=(), publisher=PUB)
    for k, v in over.items():
        if k.startswith("cli_"):
            raw["cli"][k[4:]] = v
        else:
            raw[k] = v
    return raw


@pytest.mark.parametrize("path", UNC)
@pytest.mark.parametrize("field", ["cli_python", "runtime", "argv0", "argv1", "flag", "env", "cwd", "skill"])
def test_c4_repro_unc_refused_at_gate1_without_touching_it(tmp_path, no_network_paths, path, field):
    """修之前：第 1 關放行，第 2 關在報告出來之前就 realpath／exists 它（Windows 會連 SMB）。"""
    raw = {"cli_python": lambda: _c4_raw(cli_python=path),
           "runtime": lambda: _c4_raw(runtime={"python": path}),
           "argv0": lambda: _c4_raw(cli_argv=[path, "x"]),
           "argv1": lambda: _c4_raw(cli_argv=["{python}", path]),
           "flag": lambda: _c4_raw(cli_argv=["{python}", "./tool.py", "--file=" + path]),
           "env": lambda: _c4_raw(env={"X_DIR": path}),
           "cwd": lambda: _c4_raw(cli_cwd=path),
           "skill": lambda: _c4_raw(skill=path)}[field]()
    folder = _write(str(tmp_path / "a"), raw)
    with pytest.raises(ManifestError, match="網路路徑"):
        read(folder, strict=True)


@pytest.mark.parametrize("path", UNC[:3])
def test_c4_unc_in_mcp_argv_and_python_module(tmp_path, no_network_paths, path):
    raw = {"name": "mx", "title": "M", "summary": "s", "version": "0.1.0", "kind": "mcp", "skill": "SKILL.md",
           "capabilities": ["subprocess"], "publisher": PUB,
           "mcp": {"transport": "stdio", "argv": [path], "tools_allow": ["a"], "effects": {"a": "READ"}}}
    with pytest.raises(ManifestError, match="網路路徑"):
        read(_write(str(tmp_path / "m"), raw), strict=True)
    raw = {"name": "py", "title": "P", "summary": "s", "version": "0.1.0", "kind": "python", "skill": "SKILL.md",
           "python": {"module": path}}
    with pytest.raises(ManifestError, match="網路路徑"):
        read(_write(str(tmp_path / "p"), raw), strict=True)


@pytest.mark.parametrize("path", UNC + [r"\\attacker\x", " //attacker/x"])
def test_c4_member_typed_path_refused_before_realpath(tmp_path, no_network_paths, path):
    from synox.agent import validate as gate4
    full, error = gate4.inside(str(tmp_path), path)
    assert full == "" and "網路路徑" in error
    full, error = gate4.inside(str(tmp_path), "notes/a.txt")           # 一般路徑照舊
    assert error is None


def test_c4_urls_are_not_unc():
    from synox.packs.manifest import unc_like
    assert not unc_like("--url=https://example.com/x") and not unc_like("https://a//b") and not unc_like("C:/x//y")
    assert unc_like(r"--file=\\h\s") and unc_like("a;//h/s") and unc_like(r"\\?\C:\x")


def test_c4_python_module_and_skill_must_stay_in_pack(tmp_path):
    """python.module "../x" 以前會讓 loader 執行 pack 外的 x.py（第 2 關沒掃、鎖裡沒有）；skill 也不能讀 pack 外的檔。"""
    raw = {"name": "py", "title": "P", "summary": "s", "version": "0.1.0", "kind": "python", "skill": "SKILL.md",
           "python": {"module": "../outside"}}
    folder = _write(str(tmp_path / "p" / "pack"), raw, {"../outside.py": "def install(app, pack): pass\n"})
    with pytest.raises(ManifestError, match="python.module"):
        read(folder, strict=True)
    raw = _c4_raw(skill="../SKILL.md")
    with pytest.raises(ManifestError, match="skill"):
        read(_write(str(tmp_path / "s"), raw), strict=True)
