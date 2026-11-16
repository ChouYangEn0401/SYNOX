"""多檔的 python 工具（pack.json `"python": {"module": "pack", "package": true}`，ADR 0027、packs/pkgload.py）。

全部在 tmp 裡手放假工具、記憶體裡的 bot；不開埠、不開子程序。"""

import importlib.machinery
import importlib.util
import json
import os
import py_compile
import sys

import pytest

from synox.packs import admin, lock, loader, pkgload
from synox.packs import scan as pack_scan
from synox.packs.manifest import ManifestError, read, validate

pytestmark = pytest.mark.usefixtures("no_sockets")

NAMES = ("pkga", "pkgb", "pkgsolo", "pkgbad")


@pytest.fixture(autouse=True)
def _clean_modules():
    for n in NAMES:
        pkgload.forget(n)
    yield
    for n in NAMES:
        pkgload.forget(n)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _manifest(folder, name, package=True, **over):
    raw = {"name": name, "title": name, "summary": "s", "version": "0.1.0", "kind": "python", "skill": "SKILL.md",
           "group": name, "python": {"module": "pack", **({"package": package} if package is not None else {})}}
    raw.update(over)
    _write(os.path.join(folder, "pack.json"), json.dumps(raw))
    _write(os.path.join(folder, "SKILL.md"), f"---\nname: {name}\ndescription: d\n---\nbody\n")
    return raw


PACK_PY = (
    "from .engine import db\n"
    "from .engine.util import shout\n"
    "from .bridge import table\n"
    "\n"
    "def lazy():\n"
    "    from .engine import late\n"
    "    return late.VALUE\n"
    "\n"
    "def install(app, pack):\n"
    "    pack.group.leaf('hi', lambda api, c, u, a: api.send_message(c, shout(db.WHO) + table.MARK), 'hi')\n"
)


def _multi(base, name, who="a"):
    """一個多檔工具：engine/（有 __init__）、bridge/（沒有 __init__）、子模組之間互相相對 import。"""
    folder = os.path.join(str(base), name)
    _manifest(folder, name)
    _write(os.path.join(folder, "pack.py"), PACK_PY)
    _write(os.path.join(folder, "engine", "__init__.py"), "")
    _write(os.path.join(folder, "engine", "db.py"), f"from . import util\nWHO = util.tag({who!r})\n")
    _write(os.path.join(folder, "engine", "util.py"), "def tag(s):\n    return 'engine-' + s\n\n"
                                                       "def shout(s):\n    return s.upper()\n")
    _write(os.path.join(folder, "engine", "late.py"), "VALUE = 'late-ok'\n")
    _write(os.path.join(folder, "bridge", "table.py"), "from ..engine import util\nMARK = '!' if util else '?'\n")
    return folder


def _status(report):
    return {i.name: (i.status, i.detail) for i in report.items}


def _mods(name):
    top = pkgload.module_name(name)
    return sorted(k for k in sys.modules if k == top or k.startswith(top + "."))


# ── 1. 載得起來、相對 import 可用 ───────────────────────────────────────

def test_multi_file_pack_loads_with_relative_imports(make_bot, tmp_path):
    base = tmp_path / "packs"
    _multi(base, "pkga")
    bot = make_bot(pack_dirs=(str(base),))
    assert _status(bot.app.extras["synox_pack_report"])["pkga"][0] == "loaded"
    bot.say(100, "/pkga_hi")
    assert bot.last(100) == "ENGINE-A!"
    module = sys.modules["synox_pack_pkga"]
    assert module.__path__ == []                                   # 空的：標準的 PathFinder 找不到任何東西
    assert module.lazy() == "late-ok"                             # 函式裡延後 import 也走同一個載入器
    assert set(_mods("pkga")) >= {"synox_pack_pkga", "synox_pack_pkga.engine", "synox_pack_pkga.engine.db",
                                  "synox_pack_pkga.engine.util", "synox_pack_pkga.bridge",
                                  "synox_pack_pkga.bridge.table", "synox_pack_pkga.engine.late"}
    assert not any(os.path.normcase(str(base)) in os.path.normcase(p) for p in sys.path)   # 不加 sys.path


def test_absolute_import_of_own_module_name_does_not_find_folder(make_bot, tmp_path):
    """`import engine`（絕對）找不到：工具資料夾不在 sys.path。"""
    base = tmp_path / "packs"
    folder = _multi(base, "pkga")
    _write(os.path.join(folder, "pack.py"), "import engine\n\ndef install(app, pack):\n    pass\n")
    bot = make_bot(pack_dirs=(str(base),))
    status, detail = _status(bot.app.extras["synox_pack_report"])["pkga"]
    assert status == "error" and "ModuleNotFoundError" in detail
    assert _mods("pkga") == []                                    # 安裝失敗：不留半套模組


def test_main_module_cannot_be_imported_again_and_case_must_match(tmp_path):
    folder = _multi(tmp_path, "pkga")
    path = os.path.join(folder, "pack.py")
    module = pkgload.load("pkga", folder, "pack", path, open(path, "rb").read(), {})
    with pytest.raises(ImportError, match="主模組"):
        exec("from . import pack", {"__name__": "synox_pack_pkga.x", "__package__": module.__name__})
    with pytest.raises(ImportError):                               # 檔名是 db.py，DB 不算（Windows 的檔案系統不分大小寫）
        exec("from .engine import DB", {"__name__": "synox_pack_pkga.x", "__package__": module.__name__})
    _write(os.path.join(folder, "engine", "data.pyw"), "X = 1\n")
    with pytest.raises(ImportError):                               # 只收 .py
        exec("from .engine import data", {"__name__": "synox_pack_pkga.x", "__package__": module.__name__})


# ── 2. 有鎖：子模組被改過＝拒載 ─────────────────────────────────────────

def test_locked_submodule_changed_after_load_is_refused(make_bot, tmp_path):
    base = tmp_path / "packs"
    folder = _multi(base, "pkga")
    lock.approve(str(tmp_path / "data"), read(folder), None, 100, via="test")
    bot = make_bot(pack_dirs=(str(base),))
    report = bot.app.extras["synox_pack_report"]
    assert _status(report)["pkga"][0] == "loaded"
    assert [i.lock for i in report.items if i.name == "pkga"] == ["locked"]
    _write(os.path.join(folder, "engine", "late.py"), "VALUE = 'swapped'\n")      # 第 3 關驗完之後才被換
    with pytest.raises(ImportError, match="packs.lock"):
        sys.modules["synox_pack_pkga"].lazy()
    assert "synox_pack_pkga.engine.late" not in sys.modules


def test_locked_submodule_changed_before_import_is_refused(tmp_path):
    """第 3 關對完、pack.py import 子模組之前被換掉：編譯前那一份 bytes 對不上鎖。"""
    folder = _multi(tmp_path, "pkga")
    locked = lock.hash_files(folder)
    _write(os.path.join(folder, "engine", "db.py"), "WHO = 'evil'\n")
    path = os.path.join(folder, "pack.py")
    with pytest.raises(ImportError, match=r"engine/db\.py 跟 packs\.lock"):
        pkgload.load("pkga", folder, "pack", path, open(path, "rb").read(), locked)
    assert _mods("pkga") == [] and not pkgload.registered("pkga")


def test_locked_pack_refuses_file_not_in_lock(tmp_path):
    folder = _multi(tmp_path, "pkga")
    locked = lock.hash_files(folder)
    path = os.path.join(folder, "pack.py")
    module = pkgload.load("pkga", folder, "pack", path, open(path, "rb").read(), locked)
    _write(os.path.join(folder, "engine", "extra.py"), "X = 1\n")
    with pytest.raises(ImportError, match="不在 packs.lock"):
        exec("from .engine import extra", {"__name__": "synox_pack_pkga.x", "__package__": module.__name__})


def test_tampered_submodule_at_load_time_is_not_loaded(make_bot, tmp_path):
    base = tmp_path / "packs"
    folder = _multi(base, "pkga")
    lock.approve(str(tmp_path / "data"), read(folder), None, 100, via="test")
    _write(os.path.join(folder, "engine", "util.py"), "def tag(s):\n    return s\n\ndef shout(s):\n    return s\n")
    bot = make_bot(pack_dirs=(str(base),))
    status, detail = _status(bot.app.extras["synox_pack_report"])["pkga"]
    assert status == "tampered" and "engine/util.py" in detail
    assert _mods("pkga") == []


# ── 3. __pycache__ 裡的假 .pyc 不會被用 ─────────────────────────────────

def test_fake_pyc_in_pycache_is_ignored(make_bot, tmp_path):
    base = tmp_path / "packs"
    folder = _multi(base, "pkga")
    db = os.path.join(folder, "engine", "db.py")
    evil_src = tmp_path / "evil" / "db.py"
    _write(str(evil_src), "WHO = 'from-pyc'\n")
    cfile = importlib.util.cache_from_source(db)
    py_compile.compile(str(evil_src), cfile=cfile, doraise=True,
                       invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    # 對照：標準的載入器真的會用這個 .pyc（所以下面拿到原始碼的值才有意義）
    std = importlib.machinery.SourceFileLoader("_pyc_probe", db)
    probe = {}
    exec(std.get_code("_pyc_probe"), probe)
    assert probe["WHO"] == "from-pyc"
    bot = make_bot(pack_dirs=(str(base),))
    assert _status(bot.app.extras["synox_pack_report"])["pkga"][0] == "loaded"
    bot.say(100, "/pkga_hi")
    assert bot.last(100) == "ENGINE-A!"
    assert sys.modules["synox_pack_pkga.engine.db"].WHO == "engine-a"


# ── 4. 兩個工具各有 engine/，互不干擾 ───────────────────────────────────

def test_two_packs_with_same_submodule_names_do_not_interfere(make_bot, tmp_path):
    base = tmp_path / "packs"
    _multi(base, "pkga", who="a")
    _multi(base, "pkgb", who="b")
    bot = make_bot(pack_dirs=(str(base),))
    status = _status(bot.app.extras["synox_pack_report"])
    assert status["pkga"][0] == status["pkgb"][0] == "loaded"
    bot.say(100, "/pkga_hi")
    assert bot.last(100) == "ENGINE-A!"
    bot.say(100, "/pkgb_hi")
    assert bot.last(100) == "ENGINE-B!"
    a, b = sys.modules["synox_pack_pkga.engine.db"], sys.modules["synox_pack_pkgb.engine.db"]
    assert a is not b and a.WHO == "engine-a" and b.WHO == "engine-b"
    assert "engine" not in sys.modules and "engine.db" not in sys.modules


# ── 5. 重新載入／移除後 sys.modules 乾淨 ────────────────────────────────

def test_reload_and_remove_clean_sys_modules(make_bot, tmp_path):
    packs_dir = tmp_path / "packs"
    folder = _multi(packs_dir, "pkga")
    bot = make_bot(pack_dirs=(str(packs_dir),))
    sys.modules["synox_pack_pkga"].lazy()
    before = _mods("pkga")
    assert "synox_pack_pkga.engine.late" in before
    report = admin.reload(bot.app, bot.app.config, None, (str(packs_dir),))
    assert _status(report)["pkga"][0] == "loaded"
    assert "synox_pack_pkga.engine.late" not in sys.modules       # 舊的那一套全部清掉，重新載入的才在
    assert "synox_pack_pkga.engine.db" in sys.modules
    admin.remove("pkga", str(packs_dir), data_dir=bot.app.config.data_dir)
    assert not os.path.isdir(folder)
    report = admin.reload(bot.app, bot.app.config, None, (str(packs_dir),))
    assert "pkga" not in _status(report)
    assert _mods("pkga") == [] and not pkgload.registered("pkga")


def test_failed_install_cleans_modules(make_bot, tmp_path):
    base = tmp_path / "packs"
    folder = _multi(base, "pkgbad")
    _write(os.path.join(folder, "pack.py"), "from .engine import db\n\ndef install(app, pack):\n    raise RuntimeError('no')\n")
    bot = make_bot(pack_dirs=(str(base),))
    assert _status(bot.app.extras["synox_pack_report"])["pkgbad"][0] == "error"
    assert _mods("pkgbad") == [] and not pkgload.registered("pkgbad")


# ── 路徑不准跑出工具資料夾 ─────────────────────────────────────────────

def test_symlink_out_of_pack_folder_is_refused(tmp_path):
    folder = _multi(tmp_path / "packs", "pkga")
    outside = tmp_path / "outside"
    _write(str(outside / "__init__.py"), "")
    _write(str(outside / "spy.py"), "X = 'outside'\n")
    link = os.path.join(folder, "ext")
    try:
        os.symlink(str(outside), link, target_is_directory=True)
    except (OSError, NotImplementedError):
        try:                                                       # Windows 沒有開發人員模式：改用 junction
            import _winapi
            _winapi.CreateJunction(str(outside), link)
        except (ImportError, OSError, AttributeError):
            pytest.skip("這台不能建符號連結或 junction")
    path = os.path.join(folder, "pack.py")
    module = pkgload.load("pkga", folder, "pack", path, open(path, "rb").read(), {})
    with pytest.raises(ImportError, match="外面"):
        exec("from .ext import spy", {"__name__": "synox_pack_pkga.x", "__package__": module.__name__})
    assert "synox_pack_pkga.ext.spy" not in sys.modules


# ── 6. 沒寫 package 的舊工具行為不變 ────────────────────────────────────

def test_single_file_pack_unchanged(make_bot, tmp_path):
    base = tmp_path / "packs"
    folder = os.path.join(str(base), "pkgsolo")
    _manifest(folder, "pkgsolo", package=None)
    _write(os.path.join(folder, "pack.py"),
           "def install(app, pack):\n    pack.group.leaf('hi', lambda api, c, u, a: api.send_message(c, 'solo'), 'hi')\n")
    _write(os.path.join(folder, "helper.py"), "X = 1\n")
    bot = make_bot(pack_dirs=(str(base),))
    assert _status(bot.app.extras["synox_pack_report"])["pkgsolo"][0] == "loaded"
    bot.say(100, "/pkgsolo_hi")
    assert bot.last(100) == "solo"
    module = sys.modules["synox_pack_pkgsolo"]
    assert not hasattr(module, "__path__")                          # 不是套件（跟以前一樣）
    assert not pkgload.registered("pkgsolo")
    with pytest.raises(ImportError):                                # 單檔工具沒有子模組可以 import
        exec("from . import helper", {"__name__": "synox_pack_pkgsolo.x", "__package__": "synox_pack_pkgsolo"})


def test_switching_from_package_to_single_file_cleans_up(make_bot, tmp_path):
    base = tmp_path / "packs"
    folder = _multi(base, "pkga")
    bot = make_bot(pack_dirs=(str(base),))
    assert "synox_pack_pkga.engine.db" in sys.modules
    _manifest(folder, "pkga", package=None)                        # 改回單檔
    _write(os.path.join(folder, "pack.py"), "def install(app, pack):\n    pass\n")
    # 改過的檔要重新核准一次，不然就是「被改過」不載入（ADR 0028 §4）：當作重新經過安裝頁
    lock.approve(str(tmp_path / "data"), read(folder), None, 100, via="test")
    report = admin.reload(bot.app, bot.app.config, None, (str(base),))
    assert _status(report)["pkga"][0] == "loaded"
    assert _mods("pkga") == ["synox_pack_pkga"] and not pkgload.registered("pkga")
    assert not hasattr(sys.modules["synox_pack_pkga"], "__path__")


# ── pack.json：python.package 的型別 ───────────────────────────────────

def test_manifest_package_flag(tmp_path):
    folder = str(tmp_path / "p")
    raw = _manifest(folder, "pkga")
    _write(os.path.join(folder, "pack.py"), "def install(app, pack):\n    pass\n")
    assert validate(raw, folder, strict=True).python == {"module": "pack", "package": True}
    raw["python"]["package"] = False
    validate(raw, folder, strict=True)
    raw["python"].pop("package")
    assert validate(raw, folder, strict=True).python == {"module": "pack"}    # 沒寫＝單檔，跟以前一樣
    for bad in ("yes", 1, None, ["x"]):
        raw["python"]["package"] = bad
        with pytest.raises(ManifestError, match="python.package"):
            validate(raw, folder, strict=True)
        with pytest.raises(ManifestError, match="python.package"):
            validate(raw, folder)


def test_manifest_package_only_for_python(tmp_path):
    folder = str(tmp_path / "p")
    raw = _manifest(folder, "pkga", kind="cli",
                    cli={"argv": ["{python}", "./t.py"], "commands": [{"name": "go", "argv": ["go"], "summary": "s"}]})
    _write(os.path.join(folder, "t.py"), "print(1)\n")
    with pytest.raises(ManifestError, match="python.package 只給 kind=python"):
        validate(raw, folder, strict=True)


# ── 第 2 關：每個 .py 都掃、相對 import 不算 exec、import 別的工具＝拒 ──────

def _scan(folder):
    m = read(folder)
    report = pack_scan.scan(m)
    return m, report


def test_scan_covers_every_submodule_and_relative_imports_are_free(tmp_path):
    folder = _multi(tmp_path, "pkga")
    _write(os.path.join(folder, "engine", "deep", "__init__.py"), "")
    _write(os.path.join(folder, "engine", "deep", "net.py"), "import socket\n")
    m, report = _scan(folder)
    assert report.files >= 8
    assert [(f.file, f.kind) for f in report.findings] == [("engine/deep/net.py", "network")]   # 子資料夾裡的也掃到
    os.remove(os.path.join(folder, "engine", "deep", "net.py"))
    m, report = _scan(folder)
    assert report.findings == [] and report.problems(m) == []      # 相對 import 不用多宣告能力


@pytest.mark.parametrize("src", [
    "import synox_pack_other\n",
    "import synox_pack_other.engine.db as db\n",
    "from synox_pack_other.engine import db\n",
    "from synox_pack_other import engine\n",
])
def test_scan_refuses_absolute_import_of_another_pack(tmp_path, src):
    folder = _multi(tmp_path, "pkga")
    _write(os.path.join(folder, "engine", "peek.py"), src)
    m, report = _scan(folder)
    kinds = [(f.file, f.kind) for f in report.findings]
    assert ("engine/peek.py", "import") in kinds
    assert any("另一個工具" in p for p in report.problems(m))
    m.capabilities.extend(["exec", "network", "subprocess", "filesystem:any"])   # 宣告什麼都沒用
    assert report.problems(m)


def test_scan_allows_absolute_import_of_own_package(tmp_path):
    folder = _multi(tmp_path, "pkga")
    _write(os.path.join(folder, "engine", "self_ref.py"), "from synox_pack_pkga.engine import util\n")
    m, report = _scan(folder)
    assert report.findings == [] and report.problems(m) == []
