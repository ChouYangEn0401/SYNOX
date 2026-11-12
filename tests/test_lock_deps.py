# -*- coding: utf-8 -*-
"""鎖定的相依清單（scripts/lock_deps.py）與 bootstrap 的安裝順序（docs/adr/0003）。不連網、不真的 pip install。"""
import hashlib
import importlib.metadata as md
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import lock_deps  # noqa: E402


class FakeDist:
    def __init__(self, name, version, requires=()):
        self.metadata = {"Name": name}
        self.version = version
        self.requires = list(requires)


def test_lock_closure_and_render(tmp_path):
    dists = {"requests": FakeDist("requests", "2.0", ["idna<4,>=2.5", "PySocks!=1.5.7; extra == \"socks\""]),
             "idna": FakeDist("idna", "3.1"),
             "cryptography": FakeDist("cryptography", "40.0", ["cffi>=1.12; platform_python_implementation != 'PyPy'",
                                                               "winonly; sys_platform == 'never'"]),
             "cffi": FakeDist("cffi", "1.0")}

    def find(name):
        if name.lower() not in dists:
            raise md.PackageNotFoundError(name)
        return dists[name.lower()]

    pins = lock_deps.closure(["requests", "cryptography"], find=find)
    assert pins == {"requests": ("requests", "2.0"), "idna": ("idna", "3.1"), "cryptography": ("cryptography", "40.0"),
                    "cffi": ("cffi", "1.0")}
    with pytest.raises(LookupError):
        lock_deps.closure(["missing"], find=find)
    wheel = tmp_path / "idna-3.1-py3-none-any.whl"
    wheel.write_bytes(b"fake wheel")
    text = lock_deps.render(pins, lock_deps.wheel_hashes(str(tmp_path)), today="2026-11-12")
    text.encode("ascii")
    assert "idna==3.1 \\\n    --hash=sha256:" + hashlib.sha256(b"fake wheel").hexdigest() in text
    lock = tmp_path / "requirements.lock"
    lock.write_text(text, encoding="ascii")
    assert lock_deps.stale(str(lock), ["requests", "cryptography"]) == []
    assert lock_deps.stale(str(lock), ["websocket-client"]) == ["websocket-client is in pyproject.toml but not pinned"]
    assert lock_deps.stale(str(tmp_path / "none.lock"), ["x"])


def test_lock_reads_pyproject():
    assert {"requests", "cryptography", "websocket-client"} <= set(lock_deps.top_level())


def test_bootstrap_prefers_offline_wheelhouse_then_lock():
    text = open(os.path.join(ROOT, "setup", "bootstrap.ps1"), encoding="utf-8-sig").read()
    assert "--no-index" in text and "wheelhouse" in text and "requirements.lock" in text
    assert text.index("'wheelhouse'") < text.index("elseif (Test-Path -LiteralPath $lock)")
    assert "synox init" in text and "import tkinter" in text
