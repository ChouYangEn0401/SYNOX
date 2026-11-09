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
