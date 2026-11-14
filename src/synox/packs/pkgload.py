"""
kind=python 的多檔工具（pack.json `"python": {"module": "pack", "package": true}`）：pack.py 以套件身分載入，
工具資料夾裡的子模組（engine/、bridge/…）用相對 import 取用（`from .engine import db`）。

為什麼自己寫載入器、不把工具資料夾加進 sys.path（docs/adr/0027-multi-file-python-packs.md）：
- sys.path 是整個程序共用的：兩個工具都有 engine/ 時，先載入的那個會被另一個 import 到；
  標準的 FileFinder 也會讀 __pycache__ 裡的 .pyc（packs.lock 有鎖 .pyc，但編譯出來的東西第 2 關掃不到）。
- 這裡的載入器只管 `synox_pack_<名字>.` 開頭的模組，規則跟單檔的 pack.py 一樣：
    1. 一律從 .py 原始碼編譯（不讀 __pycache__、不收 .pyc／.pyw／.pyd／.so）；
    2. 有鎖（packs.lock）時，編譯的那一份 bytes 先對鎖裡的 sha256，不符或鎖裡沒有這個檔＝ImportError；
    3. 路徑一定在工具資料夾裡：每一段都要是 Python 識別字、檔名大小寫要跟磁碟上一樣、
       realpath 不准跑出工具資料夾（符號連結／junction 指到外面＝ImportError）；
    4. 主模組（pack.py）不能再被當子模組 import 一次。
- 套件的 __path__ 是空的清單：就算這個載入器被拿掉，標準的 PathFinder 也找不到任何東西（不會退回去讀 .pyc）。
- 重新載入／移除工具時 forget(名字)：拿掉登記、sys.modules 裡這個前綴的模組全部清掉。

找不到的子模組照常是 ModuleNotFoundError；違反規則的是 ImportError（訊息說哪一條）。
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import os
import sys
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

PREFIX = "synox_pack_"
_LOCK = threading.RLock()


def module_name(pack_name: str) -> str:
    """工具名字 → 頂層模組名（單檔、多檔都是這個名字）。"""
    return PREFIX + pack_name.replace("-", "_")


@dataclass
class _Entry:
    folder: str                                   # realpath
    main: str                                     # pack.json python.module（pack）
    locked: Dict[str, str] = field(default_factory=dict)   # packs.lock 的 {相對路徑: sha256}；空＝沒鎖


_PACKS: Dict[str, _Entry] = {}


def _inside(folder: str, path: str) -> bool:
    real = os.path.realpath(path)
    try:
        return os.path.commonpath([os.path.normcase(folder), os.path.normcase(real)]) == os.path.normcase(folder)
    except ValueError:                            # 不同磁碟機
        return False


def _exact(base: str, name: str) -> bool:
    """base 資料夾裡有沒有剛好叫 name 的項目（大小寫一樣；Windows 的 isfile 不分大小寫）。"""
    try:
        return name in os.listdir(base)
    except OSError:
        return False


class _Loader(importlib.abc.Loader):

    def __init__(self, top: str, rel: Optional[str], path: str):
        self.top = top
        self.rel = rel          # 相對路徑（engine/db.py、engine/__init__.py）；None＝沒有 __init__.py 的資料夾
        self.path = path

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        if self.rel is None:                      # 沒有 __init__.py 的資料夾：空的套件
            return
        with _LOCK:
            entry = _PACKS.get(self.top)
        if entry is None:
            raise ImportError(f"{module.__name__}：工具已經卸載", name=module.__name__)
        if not _inside(entry.folder, self.path):
            raise ImportError(f"{self.rel} 不在工具資料夾裡", name=module.__name__)
        with open(self.path, "rb") as f:
            source = f.read()
        if entry.locked:
            expected = entry.locked.get(self.rel)
            if expected is None:
                raise ImportError(f"{self.rel} 不在 packs.lock 裡（核准之後才加的檔）", name=module.__name__)
            if hashlib.sha256(source).hexdigest() != expected:
                raise ImportError(f"{self.rel} 跟 packs.lock 記的不一樣（剛剛被改過？）", name=module.__name__)
        exec(compile(source, self.path, "exec"), module.__dict__)


class _Finder(importlib.abc.MetaPathFinder):
    """只管登記過的 synox_pack_<名字>.xxx；別的名字回 None（交給下一個 finder）。"""

    def find_spec(self, fullname, path=None, target=None):
        top, dot, rest = fullname.partition(".")
        if not dot or not top.startswith(PREFIX):
            return None
        with _LOCK:
            entry = _PACKS.get(top)
        if entry is None:
            return None                           # 不是多檔工具（或已經卸載）：照標準流程（__path__ 是空的，找不到）
        parts = rest.split(".")
        if not all(p.isidentifier() for p in parts):
            raise ImportError(f"{fullname}：模組名字不對", name=fullname)
        if len(parts) == 1 and parts[0] == entry.main:
            raise ImportError(f"{fullname}：主模組 {entry.main}.py 不能再當子模組 import", name=fullname)
        base = os.path.join(entry.folder, *parts[:-1])
        last = parts[-1]
        rel_dir = "/".join(parts[:-1])
        rel_of = (lambda name: f"{rel_dir}/{name}" if rel_dir else name)
        for i, p in enumerate(parts[:-1]):        # 上一層的資料夾（父套件已經載入，這裡只是再確認一次）
            if not _exact(os.path.join(entry.folder, *parts[:i]), p):
                return None
        folder = os.path.join(base, last)
        if os.path.isdir(folder) and _exact(base, last):          # 跟 Python 一樣：同名的資料夾優先於 .py
            if not _inside(entry.folder, folder):
                raise ImportError(f"{rel_of(last)}/ 指到工具資料夾外面", name=fullname)
            init = os.path.join(folder, "__init__.py")
            has_init = os.path.isfile(init) and _exact(folder, "__init__.py")
            if has_init and not _inside(entry.folder, init):
                raise ImportError(f"{rel_of(last)}/__init__.py 指到工具資料夾外面", name=fullname)
            loader = _Loader(top, rel_of(last) + "/__init__.py" if has_init else None, init if has_init else folder)
            spec = importlib.util.spec_from_loader(fullname, loader, origin=init if has_init else folder,
                                                   is_package=True)
            spec.submodule_search_locations = []
            if has_init:
                spec.has_location = True
            return spec
        file = os.path.join(base, last + ".py")
        if not (os.path.isfile(file) and _exact(base, last + ".py")):
            return None
        if not _inside(entry.folder, file):
            raise ImportError(f"{rel_of(last + '.py')} 指到工具資料夾外面", name=fullname)
        spec = importlib.util.spec_from_loader(fullname, _Loader(top, rel_of(last + ".py"), file), origin=file)
        spec.has_location = True
        return spec


_FINDER = _Finder()


def _ensure_finder() -> None:
    if _FINDER not in sys.meta_path:
        sys.meta_path.insert(0, _FINDER)


def forget(pack_name: str) -> None:
    """拿掉這個工具的登記，sys.modules 裡 synox_pack_<名字> 與它底下的模組全部清掉（單檔工具也適用）。"""
    top = module_name(pack_name)
    with _LOCK:
        _PACKS.pop(top, None)
        for key in [k for k in sys.modules if k == top or k.startswith(top + ".")]:
            sys.modules.pop(key, None)


def load(pack_name: str, folder: str, main: str, path: str, source: bytes, locked: Dict[str, str]):
    """多檔工具的主模組：登記資料夾與鎖 → 建一個套件模組（__path__ 空的）→ 執行已經驗過雜湊的 source。
    執行失敗會 forget（不留半套模組）。回模組。"""
    top = module_name(pack_name)
    forget(pack_name)
    with _LOCK:
        _PACKS[top] = _Entry(os.path.realpath(folder), main, dict(locked or {}))
        _ensure_finder()
    # loader 也用 _Loader（importlib.reload 之類再執行一次時，一樣從原始碼編譯、對鎖）
    spec = importlib.util.spec_from_loader(top, _Loader(top, f"{main}.py", path), origin=path, is_package=True)
    spec.submodule_search_locations = []
    spec.has_location = True
    module = importlib.util.module_from_spec(spec)
    sys.modules[top] = module
    try:
        exec(compile(source, path, "exec"), module.__dict__)
    except BaseException:
        forget(pack_name)
        raise
    return module


def registered(pack_name: str) -> bool:
    with _LOCK:
        return module_name(pack_name) in _PACKS
