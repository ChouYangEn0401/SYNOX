# -*- coding: utf-8 -*-
"""發佈物的版面（docs/adr/0003）：zip 旁邊附 tools/、安裝程式的 stage。只複製檔案；不執行任何 Python、不 pip、不打包 exe。
假的 Python（python-build-standalone 的 .tar.gz）只是幾個位元組的檔案（不會被執行）。"""
import os
import sys
import zipfile

import pytest

from test_clean_room import make_tools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import make_zip  # noqa: E402
import stage_installer  # noqa: E402


def test_zip_ships_tools_next_to_synox(tmp_path):
    tools = make_tools(tmp_path / "libs-dist", ("notes", "money"))
    assert make_zip.main(["--out", str(tmp_path / "out"), "--tools", tools]) == 0
    (target,) = list((tmp_path / "out").iterdir())
    with zipfile.ZipFile(target) as z:
        names = set(z.namelist())
    assert "SYNOX/tools/index.json" in names
    assert sum(n.startswith("SYNOX/tools/") and n.endswith(".synoxpack") for n in names) == 2
    assert "SYNOX/Setup.bat" in names and "SYNOX/src/synox/config.py" in names
    assert not any(n.startswith(("SYNOX/data/", "SYNOX/.venv/")) or n.endswith("/config.json") for n in names)


def test_zip_refuses_tampered_or_unbuilt_tools(tmp_path, capsys):
    bad = make_tools(tmp_path / "bad", ("notes",), tamper="notes")
    assert make_zip.main(["--out", str(tmp_path / "out"), "--tools", bad]) == 2
    assert "雜湊" in capsys.readouterr().out
    src = tmp_path / "SYNOX_Libs"
    (src / "packs").mkdir(parents=True)
    (src / "scripts").mkdir()
    assert make_zip.main(["--out", str(tmp_path / "out"), "--tools", str(src)]) == 2
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir())


def test_repo_level_tools_and_wheelhouse_are_not_taken_from_git():
    assert make_zip.excluded("tools/index.json") and make_zip.excluded("wheelhouse/x.whl")
    assert not make_zip.excluded("src/synox/wizard/tools.py") and not make_zip.excluded("src/synox/runtime/loop.py")


def test_eval_set_is_not_shipped():
    """評測題目與劇本（evals/）是開發用的，不發給一般使用者；程式碼 src/synox/evals 照常發。"""
    assert make_zip.excluded("evals/assistant/cases/note-01.json")
    assert make_zip.excluded("evals/assistant/README.md")
    assert not make_zip.excluded("src/synox/evals/cases.py")


def fake_wheels(folder, names=("pip-24.0-py3-none-any.whl", "setuptools-70.0-py3-none-any.whl",
                               "requests-2.0-py3-none-any.whl")):
    os.makedirs(folder)
    for n in names:
        with open(os.path.join(folder, n), "wb") as f:
            f.write(b"wheel " + n.encode())
    return str(folder)


PY_FILES = ("python/python.exe", "python/pythonw.exe", "python/python3.dll", "python/python312.dll",
            "python/DLLs/_tkinter.pyd", "python/DLLs/tcl86t.dll", "python/Lib/venv/__init__.py",
            "python/Lib/tkinter/__init__.py", "python/tcl/tcl8.6/init.tcl")


def fake_standalone(path, files=PY_FILES, extra=()):
    """A tiny stand-in for python-build-standalone's Windows install_only .tar.gz (bytes only, never run).
    Returns (path, sha256, pin) with the pin pointing at this file."""
    import hashlib
    import io
    import tarfile
    with tarfile.open(path, "w:gz", format=tarfile.GNU_FORMAT) as tar:
        for name in files:
            data = b"not a real program: " + name.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra:
            tar.addfile(info, io.BytesIO(b"x" * info.size) if info.isfile() else None)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    pin = {"version": "3.12.16", "build": "20261026", "sha256": digest, "url": path.as_uri()}
    return str(path), digest, pin


def test_stage_installer_ships_the_pinned_standalone_python(tmp_path):
    archive, digest, pin = fake_standalone(tmp_path / "py.tar.gz")
    result = stage_installer.stage(str(tmp_path / "stage"), python_archive=archive, pin=pin,
                                   wheelhouse=fake_wheels(tmp_path / "wheels"),
                                   tools=make_tools(tmp_path / "libs-dist", ("notes",)))
    synox = tmp_path / "stage" / "SYNOX"
    assert result["python"] == "3.12.16"
    for rel in ("Setup.bat", "tools/index.json", "wheelhouse/pip-24.0-py3-none-any.whl", "runtime/python/python.exe",
                "runtime/python/DLLs/_tkinter.pyd", "runtime/python/Lib/tkinter/__init__.py",
                "runtime/python/tcl/tcl8.6/init.tcl", "STAGE-MANIFEST.txt", "setup/installer/synox.iss"):
        assert (synox / rel).is_file(), rel
    assert (synox / "runtime" / "python" / "python.exe").read_bytes() == b"not a real program: python/python.exe"
    assert not list((synox / "runtime" / "python").glob("*._pth"))            # 不是可攜版：沒有 ._pth
    assert sorted(p.name for p in (synox / "runtime").iterdir()) == ["python"]  # 沒有留下 .tmp
    manifest = (synox / "STAGE-MANIFEST.txt").read_text(encoding="utf-8")
    assert digest in manifest.splitlines()[0] and "3.12.16" in manifest.splitlines()[0]
    assert str(tmp_path) not in manifest and "tools/index.json" in manifest      # 沒有發佈機的路徑
    assert not (synox / "data").exists() and not (synox / "config.json").exists()


def test_stage_installer_can_fetch_the_pinned_file(tmp_path):
    archive, digest, pin = fake_standalone(tmp_path / "py.tar.gz")
    stage_installer.stage(str(tmp_path / "stage"), fetch=True, pin=pin, wheelhouse=fake_wheels(tmp_path / "w"))
    assert (tmp_path / "stage" / "SYNOX" / "runtime" / "python" / "python.exe").is_file()
    assert (tmp_path / "stage" / "downloads" / "py.tar.gz").is_file()          # 下載的檔案在 stage 外面，不會被打包


def test_stage_installer_reads_the_same_pin_as_bootstrap():
    pin = stage_installer.pinned_python()
    text = open(os.path.join(ROOT, "setup", "bootstrap.ps1"), encoding="utf-8-sig").read()
    assert f"$PythonSha256 = '{pin['sha256']}'" in text and f"$PythonVersion = '{pin['version']}'" in text
    assert pin["url"].startswith("https://github.com/astral-sh/python-build-standalone/releases/download/")
    assert pin["url"].endswith("-x86_64-pc-windows-msvc-install_only_stripped.tar.gz") and "$" not in pin["url"]


def test_stage_installer_refuses_bad_or_incomplete_inputs(tmp_path):
    import tarfile
    archive, digest, pin = fake_standalone(tmp_path / "py.tar.gz")
    with pytest.raises(stage_installer.StageError, match="setuptools"):
        stage_installer.stage(str(tmp_path / "s1"), python_archive=archive, pin=pin,
                              wheelhouse=fake_wheels(tmp_path / "w1", ("pip-24.0-py3-none-any.whl",)))
    with pytest.raises(stage_installer.StageError, match="sha256"):
        stage_installer.stage(str(tmp_path / "s2"), python_archive=archive, pin={**pin, "sha256": "0" * 64},
                              wheelhouse=fake_wheels(tmp_path / "w2"))
    assert not (tmp_path / "s2" / "SYNOX").exists()
    with pytest.raises(stage_installer.StageError, match="exactly one"):
        stage_installer.stage(str(tmp_path / "s3"), python_archive=archive, fetch=True, pin=pin,
                              wheelhouse=fake_wheels(tmp_path / "w3"))
    evil = tarfile.TarInfo("python/../../evil.txt")
    evil.size = 1
    link = tarfile.TarInfo("python/Lib/link")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    for i, (extra, files) in enumerate((((evil,), PY_FILES), ((link,), PY_FILES),
                                        ((), [f for f in PY_FILES if "tkinter" not in f]),
                                        ((), [f.replace("312", "311") for f in PY_FILES]))):
        bad, _, bad_pin = fake_standalone(tmp_path / f"bad{i}.tar.gz", files=files, extra=extra)
        with pytest.raises(stage_installer.StageError):
            stage_installer.stage(str(tmp_path / f"b{i}"), python_archive=bad, pin=bad_pin,
                                  wheelhouse=fake_wheels(tmp_path / f"wb{i}"))
        assert not (tmp_path / "evil.txt").exists() and not (tmp_path / f"b{i}" / "evil.txt").exists()


def test_inno_script_is_per_user_and_keeps_user_data():
    raw = open(os.path.join(ROOT, "setup", "installer", "synox.iss"), "rb").read()
    raw.decode("ascii")
    text = raw.decode("ascii")
    assert "PrivilegesRequired=lowest" in text and "{localappdata}\\Programs\\SYNOX" in text
    assert "-Mode shortcuts" in text and "data" not in text.split("[UninstallDelete]")[1]
    assert "Setup.bat" in text.split("[Run]")[1]
