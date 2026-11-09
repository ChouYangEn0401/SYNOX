# -*- coding: utf-8 -*-
"""審查 C 後半段（C5～C8）的修補。**只組判斷、絕不執行**：樣本都是字串，第 2 關只用 ast 解析；
subprocess／os.system 換成會丟錯的假貨；pip／npm 用假 JobRunner，不真的跑；lock 檔是假字串。"""
import os
import subprocess

import pytest

from synox.packs import scan as pack_scan


@pytest.fixture(autouse=True)
def _no_exec(monkeypatch):
    def boom(*a, **k):
        raise AssertionError(f"不准執行：{a[:1]}")
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(os, "system", boom)


def _kinds(src, context=None):
    return {f.kind for f in pack_scan.scan_source("t.py", src, context)}


# ── C5 (a)：底線私有模組與平台別名 ─────────────────────────────────────

@pytest.mark.parametrize("src, kind", [
    ("import nt\nnt.system('x')\n", "subprocess"),
    ("import posix\nposix.fork()\n", "subprocess"),
    ("import _winapi\n_winapi.CreateProcess(None, 'x', None, None, 0, 0, None, None, None)\n", "subprocess"),
    ("from _posixsubprocess import fork_exec\n", "subprocess"),
    ("import _socket\n", "network"),
    ("import _ssl\n", "network"),
    ("from pip._vendor import requests\n", "exec"),
    ("import pip._vendor.requests\n", "network"),
    ("import _pickle\n_pickle.loads(b'')\n", "exec"),
    ("import _ctypes\n_ctypes.LoadLibrary('C:/x.dll')\n", "exec"),
    ("import pkgutil\n", "exec"),
    ("import logging.config\n", "exec"),
    ("from logging import config\n", "exec"),
    ("import runpy\n", "exec"),
    ("import zipimport\n", "exec"),
    ("import code\n", "exec"),
    ("import codeop\n", "exec"),
    ("import marshal\n", "exec"),
    ("import pickle\n", "exec"),
    ("import shelve\n", "exec"),
    ("import ctypes\n", "exec"),
    ("import _imp\n", "exec"),
    ("import webbrowser\n", "subprocess"),
    ("from concurrent.futures import ProcessPoolExecutor\n", "subprocess"),
])
def test_c5a_private_and_platform_modules(src, kind):
    assert kind in _kinds(src)


def test_c5a_ntpath_and_posixpath_are_not_confused_with_nt_posix():
    assert _kinds("import ntpath, posixpath\nntpath.join('a', 'b')\n") == set()


# ── C5 (b)：from X import * ──────────────────────────────────────────

@pytest.mark.parametrize("module", ["os", "sys", "builtins", "subprocess", "socket", "ctypes", "nt", "shutil"])
def test_c5b_star_import_from_risky_module_is_exec(module):
    findings = pack_scan.scan_source("t.py", f"from {module} import *\nsystem('x')\n")
    assert any(f.kind == "exec" and "import *" in f.detail for f in findings)


def test_c5b_star_import_from_harmless_module_is_fine():
    assert _kinds("from typing import *\nfrom math import *\n") == set()


# ── C5 (c)：連網也看呼叫 ─────────────────────────────────────────────

@pytest.mark.parametrize("src", [
    "import asyncio\nasyncio.open_connection('h', 1)\n",
    "import asyncio\nasyncio.start_server(None, 'h', 1)\n",
    "import asyncio\nasync def f():\n    loop = asyncio.get_running_loop()\n    await loop.create_connection(None, 'h', 1)\n",
    "import asyncio\nf = asyncio.open_connection\n",                        # 當成值取用
    "def f(loop):\n    return loop.create_datagram_endpoint(None)\n",
    "def f(mod):\n    return mod.urlopen('https://x')\n",
])
def test_c5c_network_calls(src):
    assert "network" in _kinds(src)


def test_c5c_plain_asyncio_is_not_network():
    assert _kinds("import asyncio\nasyncio.run(None)\nasyncio.sleep(1)\n") == set()


# ── C5 (d)：動態屬性／呼叫名單、from X import eval ────────────────────

@pytest.mark.parametrize("src", [
    "import inspect\ninspect.getmodule(len).eval('1')\n",
    "def f(m):\n    m.exec('x')\n",
    "def f(m):\n    m.compile('x')\n",
    "def f(m):\n    m.loads(b'')\n",
    "def f(k):\n    k.LoadLibrary('C:/x.dll')\n",
    "def f(w):\n    w.CreateProcess(None, 'x')\n",
    "def f(p):\n    p.fork_exec([])\n",
    "def f(loop):\n    loop.subprocess_exec(None, 'x')\n",
    "import pkgutil\nf = pkgutil.resolve_name('os:system')\nf('x')\n",
])
def test_c5d_dynamic_attrs(src):
    assert "exec" in _kinds(src)


@pytest.mark.parametrize("src", [
    "from mypkg import eval\neval('1')\n",
    "from helpers import compile as c\n",
    "from helpers import getattr\ngetattr(object, 'x')\n",
    "from .helpers import exec\nexec('x')\n",
])
def test_c5d_importing_a_dynamic_name_is_tracked(src):
    findings = pack_scan.scan_source("t.py", src, pack_scan.ImportContext(pip=["mypkg", "helpers"]))
    assert any(f.kind == "exec" for f in findings)


def test_c5d_from_mypkg_import_eval_flags_the_call_too():
    findings = pack_scan.scan_source("t.py", "from mypkg import eval\n\n\neval('1')\n",
                                     pack_scan.ImportContext(pip=["mypkg"]))
    assert {f.line for f in findings if f.kind == "exec"} >= {1, 4}


def test_c5d_stdlib_alias_is_not_the_builtin():
    """from re import compile 是 re.compile，不是內建的 compile。"""
    assert _kinds("from re import compile\ncompile(r'x')\n") == set()
    assert _kinds("import json\njson.loads('1')\n") == set()


# ── C5 (e)：來源不明的模組 ────────────────────────────────────────────

def test_c5e_unknown_module_is_exec(tmp_path):
    ctx = pack_scan.ImportContext(str(tmp_path), [])
    findings = pack_scan.scan_source("t.py", "import sys\nsys.path.insert(0, 'C:/evil')\nimport evilmod\n", ctx)
    assert any(f.kind == "exec" and "evilmod" in f.detail for f in findings)
    assert any(f.kind == "exec" and "sys.path.insert" in f.detail for f in findings)


def test_c5e_stdlib_pack_local_and_synox_are_known(tmp_path):
    (tmp_path / "helper.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "lib").mkdir()
    ctx = pack_scan.ImportContext(str(tmp_path), [])
    src = "import json, re\nimport helper\nfrom lib import x\nfrom synox_sdk import tool\nimport synox.packs\n"
    assert pack_scan.scan_source("t.py", src, ctx) == []


def test_c5e_requires_pip_packages_pass(tmp_path):
    ctx = pack_scan.ImportContext(str(tmp_path), ["PyYAML", "beautifulsoup4", "python-dateutil", "Some-Pkg"])
    src = "import yaml\nfrom bs4 import BeautifulSoup\nimport dateutil.parser\nimport some_pkg\n"
    assert pack_scan.scan_source("t.py", src, ctx) == []
    assert "exec" in _kinds("import yaml\n", pack_scan.ImportContext(str(tmp_path), []))


def test_c5e_pip_names_are_read_from_manifest(tmp_path):
    class M:
        requires = {"pip": ["requests==2.32.3 --hash=sha256:" + "a" * 64, "PyYAML==6.0.1"]}
    assert pack_scan.pip_names(M()) == ["requests", "PyYAML"]


@pytest.mark.parametrize("src", [
    "import sys\nsys.path.append('x')\n",
    "import sys\nsys.path += ['x']\n",
    "import sys\nsys.path[:0] = ['x']\n",
    "import sys\nsys.meta_path.insert(0, object())\n",
])
def test_c5e_editing_sys_path_is_exec(src):
    assert "exec" in _kinds(src)


# ── C5 (f)：拼出名字再取屬性 ─────────────────────────────────────────

@pytest.mark.parametrize("src", [
    "import os\nname = 'sys' + 'tem'\n",
    "x = ''.join(['sy', 'st', 'em'])\n",
    "x = '%s%s' % ('sys', 'tem')\n",
    "x = '{}{}'.format('sys', 'tem')\n",
    "x = f\"{'sys'}tem\"\n",
    "x = 'metsys'[::-1]\n",
    "x = ''.join(reversed('metsys'))\n",
    "x = chr(101) + 'val'\n",
    "x = ('{0.__cl' + 'ass__}').format(1)\n",
    "x = '__cl' + 'ass__'\n",
    "x = b'sys'.decode() + 'tem'\n",
    "x = ('{0.' + y + '}').format(1)\n",                  # 樣板有一段是變數：看不出會取什麼
])
def test_c5f_constructed_names_are_dynamic(src):
    assert "exec" in _kinds(src)


def test_c5f_getattr_with_constructed_name_is_exec():
    findings = pack_scan.scan_source("t.py", "import os\ngetattr(os, 'sys' + 'tem')('x')\n")
    assert any(f.kind == "exec" for f in findings)


def test_c5f_ordinary_string_building_is_fine():
    src = ("a = 'hello ' + 'world'\nb = ', '.join(['x', 'y'])\nc = 'n=%d' % 3\n"
           "d = 'Hi {name}'.format(name='x')\ne = ('Hi {} ' + 'there').format('x')\nf = f'{a}-{b}'\n")
    assert _kinds(src) == set()


# ── C6：zip 裡超長路徑、看不見的字元 ──────────────────────────────────

def _staged_left(tmp_path):
    root = os.path.join(str(tmp_path / "data"), "web_uploads")
    return os.path.isdir(root) and os.listdir(root)


@pytest.mark.parametrize("name", [
    "/".join(["d" * 40] * 8) + "/x.txt",          # 很深的路徑（以前 Windows 丟 FileNotFoundError → 網頁 500）
    "a" * 101 + ".txt",                           # 一段太長
])
def test_c6_long_paths_are_refused_cleanly(tmp_path, name):
    from synox.packs import admin
    from test_review_b_supply import _zip_with
    with pytest.raises(admin.PackAdminError) as e:
        admin.stage(_zip_with(name), str(tmp_path / "data"))
    assert "太長" in str(e.value)
    assert not _staged_left(tmp_path)


@pytest.mark.parametrize("name", ["\u202eyp.a", "a\u202d.py", "lib/\u2066x.py", "x\u2069.txt", "to\u200bol.py",
                                  "\u200cx.py", "x\u200d.txt", "\ufeffx.py", "a\u202a.txt", "a\u202c.txt",
                                  "\u2067a.txt", "\u2068a.txt", "a\u202b.txt"])
def test_c6_bidi_and_zero_width_names_are_refused(tmp_path, name):
    from synox.packs import admin
    from test_review_b_supply import _zip_with
    with pytest.raises(admin.PackAdminError) as e:
        admin.stage(_zip_with(name), str(tmp_path / "data"))
    assert "看不見的字元" in str(e.value)
    assert not _staged_left(tmp_path)


def test_c6_os_error_while_extracting_becomes_a_clean_refusal(tmp_path, monkeypatch):
    from synox.packs import admin
    from test_review_b_supply import _zip_with
    real_open = open

    def fake_open(path, mode="r", *a, **k):
        if "wb" in mode and str(path).endswith("deep.txt"):
            raise FileNotFoundError(2, "No such file or directory")
        return real_open(path, mode, *a, **k)
    monkeypatch.setattr("builtins.open", fake_open)
    with pytest.raises(admin.PackAdminError) as e:
        admin.stage(_zip_with("lib/deep.txt"), str(tmp_path / "data"))
    assert "解不開" in str(e.value)
    assert not _staged_left(tmp_path)


def test_c6_ordinary_unicode_names_still_ok(tmp_path):
    from synox.packs import admin
    from test_review_b_supply import _zip_with
    token, _summary = admin.stage(_zip_with("說明/讀我.txt"), str(tmp_path / "data"))
    assert token


# ── C7：pip 不讀任何設定檔（PIP_CONFIG_FILE＝os.devnull） ─────────────────

def test_c7_build_env_points_pip_config_at_devnull():
    from synox.packs import envs
    env = envs.build_env({"PIP_CONFIG_FILE": "C:/ProgramData/evil/pip.ini", "PIP_EXTRA_INDEX_URL": "https://evil.invalid",
                          "PATH": "C:/Windows"})
    assert env["PIP_CONFIG_FILE"] == os.devnull
    assert "PIP_EXTRA_INDEX_URL" not in env and env["PATH"] == "C:/Windows"


def test_c7_pip_step_gets_devnull_config_from_fake_jobrunner(tmp_path, monkeypatch):
    """假 JobRunner 只記 argv／env，不跑 pip。"""
    from synox.packs import envs
    from synox.packs.manifest import validate
    from test_envs import _raw as env_raw, _write_pack
    from test_review_b_supply import RecordingJobs
    monkeypatch.setenv("PIP_CONFIG_FILE", "C:/evil/pip.ini")
    envs.set_factory(lambda d: envs.VenvBuilder(d, python="PYTHON-EXE", which=lambda n: None))
    try:
        m = validate(env_raw(), _write_pack(str(tmp_path / "p")), strict=True)
        jobs = RecordingJobs(tmp_path)
        assert envs.builder(str(tmp_path / "data")).build_wait(m, jobs).ok
    finally:
        envs.set_factory(None)
    pip_calls = [c for c in jobs.calls if "pip" in c["argv"]]
    assert pip_calls and all(c["env"]["PIP_CONFIG_FILE"] == os.devnull for c in pip_calls)
    assert "--isolated" in pip_calls[0]["argv"]


# ── C8：package-lock 的 resolved 只收 https://registry.npmjs.org/ ─────────

def _lock(packages=None, v1=None):
    import json
    if v1 is not None:
        return json.dumps({"name": "tool", "lockfileVersion": 1, "dependencies": v1})
    return json.dumps({"name": "tool", "lockfileVersion": 3, "packages": {"": {"name": "tool"}, **(packages or {})}})


def _node_pack(tmp_path, tag, lock_text):
    from test_envs import _write_pack
    folder = _write_pack(str(tmp_path / tag), node=True)
    with open(os.path.join(folder, "package-lock.json"), "w", encoding="utf-8") as f:
        f.write(lock_text)
    return folder


GOOD = {"node_modules/left-pad": {"version": "1.3.0",
                                  "resolved": "https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz"},
        "node_modules/@scope/x": {"version": "1.0.0",
                                  "resolved": "https://registry.npmjs.org/@scope/x/-/x-1.0.0.tgz"},
        "node_modules/y": {"version": "2.0.0"}}            # 沒寫 resolved：npm 照 --registry 找（固定官方）


@pytest.mark.parametrize("resolved", [
    "http://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz",          # 明文
    "https://registry.npmjs.org.evil.invalid/left-pad-1.3.0.tgz",       # 長得像
    "https://registry.npmjs.org@evil.invalid/x.tgz",
    "https://registry.npmjs.org:8443/x.tgz",
    "https://registry.yarnpkg.com/left-pad/-/left-pad-1.3.0.tgz",       # 別的 registry 也不收
    "https://evil.invalid/left-pad-1.3.0.tgz",
    "file:../evil.tgz",
    "git+ssh://git@github.com/evil/x.git#abc",
    "../local-folder",
])
def test_c8_non_registry_sources_are_found(tmp_path, resolved):
    from synox.packs import envs
    folder = _node_pack(tmp_path, "p", _lock({**GOOD, "node_modules/bad": {"version": "1.0.0", "resolved": resolved}}))
    assert envs.npm_bad_sources(folder) == [("bad", resolved)]


def test_c8_registry_sources_pass(tmp_path):
    from synox.packs import envs
    assert envs.npm_bad_sources(_node_pack(tmp_path, "p", _lock(GOOD))) == []


def test_c8_lockfile_v1_nested_and_git_versions(tmp_path):
    from synox.packs import envs
    v1 = {"a": {"version": "1.0.0", "resolved": "https://registry.npmjs.org/a/-/a-1.0.0.tgz",
                "dependencies": {"b": {"version": "1.0.0", "resolved": "https://evil.invalid/b.tgz"}}},
          "c": {"version": "github:evil/c#abc"}}
    bad = envs.npm_bad_sources(_node_pack(tmp_path, "p", _lock(v1=v1)))
    assert ("b", "https://evil.invalid/b.tgz") in bad and ("c", "github:evil/c#abc") in bad and len(bad) == 2


def test_c8_bad_source_is_refused_at_install_with_red_line(tmp_path):
    from synox.packs import admin, tier
    from test_envs import _node_raw, _write_pack, _zip
    folder = _write_pack(str(tmp_path / "src"), _node_raw(), node=True)
    with open(os.path.join(folder, "package-lock.json"), "w", encoding="utf-8") as f:
        f.write(_lock({"node_modules/left-pad": {"version": "1.3.0", "resolved": "https://evil.invalid/lp.tgz"}}))
    with pytest.raises(admin.GateRefused) as e:
        admin.stage(_zip(folder), str(tmp_path / "data"))
    assert "registry.npmjs.org" in str(e.value) and "evil.invalid" in str(e.value)
    red = e.value.summary["tier"]["warning_lines"]
    assert any("不是從官方 registry" in line and "left-pad → https://evil.invalid/lp.tgz" in line for line in red)
    assert tier.assess(admin.read(folder))["npm_bad_sources"] == [{"name": "left-pad",
                                                                   "source": "https://evil.invalid/lp.tgz"}]


def test_c8_rebuild_of_an_installed_pack_also_refuses(tmp_path):
    """已經裝好的舊 pack 重建環境：plan 就擋，假 JobRunner 一次都不會被叫到（npm 不會跑）。"""
    from synox.packs import envs
    from synox.packs.manifest import validate
    from test_envs import FakeJobs, _node_raw, which_all
    folder = _node_pack(tmp_path, "p", _lock({"node_modules/x": {"version": "1.0.0", "resolved": "file:../x.tgz"}}))
    m = validate(_node_raw(), folder, strict=True)
    builder = envs.VenvBuilder(str(tmp_path / "data"), python="PYTHON-EXE", which=which_all)
    jobs = FakeJobs(tmp_path)
    result = builder.build_wait(m, jobs)
    assert not result.ok and "registry.npmjs.org" in result.detail and jobs.calls == []


def test_c8_npm_argv_pins_the_registry(tmp_path):
    from synox.packs import envs
    from synox.packs.manifest import validate
    from test_envs import _node_raw, which_all
    m = validate(_node_raw(), _node_pack(tmp_path, "p", _lock(GOOD)), strict=True)
    plan = envs.VenvBuilder(str(tmp_path / "data"), python="PYTHON-EXE", which=which_all).plan(m)
    assert plan.problems == []
    assert "--registry=https://registry.npmjs.org/" in plan.steps[-1].argv
