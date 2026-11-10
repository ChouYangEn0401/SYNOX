# -*- coding: utf-8 -*-
"""審查 B #B：第 2 關 ast 掃描的單行繞法（sys.modules、dunder 鏈、__globals__、getattr 當值傳、動態呼叫…）。
樣本**只用 ast 解析字串**（scan.scan_source），絕不 import、不執行。"""
import os

import pytest

from synox.packs import admin
from synox.packs.manifest import read
from synox.packs.scan import scan, scan_source

from test_t2_trust import _write


def _kinds(src):
    return {f.kind for f in scan_source("x.py", src)}


@pytest.mark.parametrize("src", [
    "import sys\nsys.modules['os'].system('calc')\n",
    "import sys\nm = sys.modules\n",
    "from sys import modules\n",
    "x = ().__class__.__bases__[0].__subclasses__()\n",
    "def f():\n    pass\nos = f.__globals__['os']\n",
    "b = print.__self__\n",
    "g = getattr\n",
    "import os\nf = getattr(*[os, 'system'])\n",
    "import os\nf = getattr(os, f\"{'sys'}tem\")\n",
    "import os\nf = getattr(os, 'popen')\n",
    "d = vars(object)\n",
    "g = globals()['x']\n",
    "l = locals()\n",
    "e = [eval][0]\n",
    "c = compile\n",
    "handlers = {}\nhandlers['a']()\n",
    "(lambda: 0)()\n",
    "def mk():\n    return len\nmk()('x')\n",
    "import os\n[os][0].system('calc')\n",
    "obj = None\nobj.popen('x')\n",
    "import operator, os\noperator.attrgetter('system')(os)\n",
    "s = '{0.__globals__}'.format(len)\n",
    "import inspect\nf = inspect.currentframe().f_back.f_globals\n",
    "__import__('os')\n",
    "import importlib\nimportlib.import_module('os')\n",
    "b = __builtins__\n",
])
def test_bypass_one_liners_are_exec(src):
    assert "exec" in _kinds(src), src


@pytest.mark.parametrize("src,kind", [
    ("import os\nx = os\nx.system('calc')\n", "subprocess"),          # 指派別名照追
    ("import os\nrun = os.system\nrun('calc')\n", "subprocess"),       # 當成值取用
    ("import pickle\nload = pickle.loads\n", "exec"),
])
def test_aliases_and_references_are_tracked(src, kind):
    assert kind in _kinds(src)


@pytest.mark.parametrize("src", [
    "x = getattr(object, 'name', None)\n",
    "import platform\np = platform.system()\n",
    "import re\nr = re.compile('a')\n",
    "def f(values):\n    return values['a'].strip()\n",
    "def f(pack, user):\n    return pack.store.of(user).load({})\n",
    "s = ''.join(['a'])\n",
    "class A:\n    def name(self):\n        return type(self).__name__\n",
    "ok = hasattr(object, 'x')\n",
    "d = {}\nd.setdefault('k', []).append(1)\n",
])
def test_ordinary_code_is_not_exec(src):
    assert "exec" not in _kinds(src), [f for f in scan_source("x.py", src)]


def test_findings_point_at_the_line():
    found = [f for f in scan_source("x.py", "import sys\n\nsys.modules['os'].system('calc')\n") if f.kind == "exec"]
    assert found and all(f.line == 3 for f in found)


def test_python_pack_with_bypass_is_refused(tmp_path):
    raw = {"name": "sneak", "title": "S", "summary": "s", "version": "0.1.0", "kind": "python", "skill": "SKILL.md",
           "capabilities": []}
    folder = _write(str(tmp_path / "p"), raw, {"pack.py": "import sys\n\ndef install(app, pack):\n"
                                                          "    sys.modules['os'].system('calc')\n"})
    m = read(folder, strict=True)
    problems = scan(m).problems(m)
    assert problems and any("exec" in p and "pack.py:4" in p for p in problems)


def test_python_install_report_says_scan_is_a_reminder(tmp_path):
    raw = {"name": "plain", "title": "P", "summary": "s", "version": "0.1.0", "kind": "python", "skill": "SKILL.md"}
    folder = _write(str(tmp_path / "p"), raw, {"pack.py": "def install(app, pack):\n    pass\n"})
    warnings = admin.warnings_for(read(folder, strict=True))
    assert admin.PYTHON_SCAN_NOTE in warnings
    assert "提醒、不是門" in admin.PYTHON_SCAN_NOTE and "個人版沒有任何隔離" in admin.PYTHON_SCAN_NOTE


def test_sdk_single_file_still_needs_no_capability():
    from synox import sdk
    findings = scan_source("synox_sdk.py", sdk.single_file_source())
    assert not [f for f in findings if f.blocking or f.capability], findings
    assert os.path.basename(sdk.author.__file__) == "author.py"
