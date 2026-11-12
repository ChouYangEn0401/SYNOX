# -*- coding: utf-8 -*-
"""發佈物的版面（docs/adr/0002）：zip 旁邊附 tools/、安裝程式的 stage。只複製檔案；不執行任何 Python、不 pip、不打包 exe。
假的可攜版 Python 只是幾個位元組的檔案（不會被執行）。"""
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


def fake_embed(folder, minor=12):
    os.makedirs(folder)
    with open(os.path.join(folder, f"python3{minor}._pth"), "w", encoding="ascii") as f:
        f.write(f"python3{minor}.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n")
    for name in ("python.exe", f"python3{minor}.dll"):
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"not a real program")
    return str(folder)


def fake_wheels(folder, names=("pip-24.0-py3-none-any.whl", "virtualenv-20.0-py3-none-any.whl",
                               "setuptools-70.0-py3-none-any.whl", "requests-2.0-py3-none-any.whl")):
    os.makedirs(folder)
    for n in names:
        with open(os.path.join(folder, n), "wb") as f:
            f.write(b"wheel " + n.encode())
    return str(folder)


def fake_full_python(folder, minor=12):
    os.makedirs(os.path.join(folder, "DLLs"))
    os.makedirs(os.path.join(folder, "Lib", "tkinter", "test"))
    os.makedirs(os.path.join(folder, "tcl", "tcl8.6"))
    for name in stage_installer.TK_FILES:
        with open(os.path.join(folder, "DLLs", name), "wb") as f:
            f.write(b"x")
    for rel in (f"python3{minor}.dll", os.path.join("Lib", "tkinter", "__init__.py"),
                os.path.join("Lib", "tkinter", "test", "t.py"), os.path.join("tcl", "tcl8.6", "init.tcl")):
        with open(os.path.join(folder, rel), "wb") as f:
            f.write(b"x")
    return str(folder)


def test_stage_installer_layout(tmp_path):
    result = stage_installer.stage(str(tmp_path / "stage"), python_embed=fake_embed(tmp_path / "embed"),
                                   wheelhouse=fake_wheels(tmp_path / "wheels"),
                                   tools=make_tools(tmp_path / "libs-dist", ("notes",)),
                                   tk_from=fake_full_python(tmp_path / "cpython"))
    synox = tmp_path / "stage" / "SYNOX"
    assert result["tk"] and result["python"] == "3.12"
    for rel in ("Setup.bat", "tools/index.json", "wheelhouse/pip-24.0-py3-none-any.whl", "runtime/python/python.exe",
                "runtime/python/_tkinter.pyd", "runtime/python/Lib/tkinter/__init__.py",
                "runtime/python/tcl/tcl8.6/init.tcl", "STAGE-MANIFEST.txt", "setup/installer/synox.iss"):
        assert (synox / rel).is_file(), rel
    assert not (synox / "runtime" / "python" / "Lib" / "tkinter" / "test").exists()
    pth = (synox / "runtime" / "python" / "python312._pth").read_text(encoding="ascii").splitlines()
    assert "import site" in pth and "#import site" not in pth and pth[0] == "Lib"
    manifest = (synox / "STAGE-MANIFEST.txt").read_text(encoding="utf-8")
    assert str(tmp_path) not in manifest and "tools/index.json" in manifest      # 沒有發佈機的路徑
    assert not (synox / "data").exists() and not (synox / "config.json").exists()


def test_stage_installer_refuses_incomplete_inputs(tmp_path):
    embed = fake_embed(tmp_path / "embed")
    with pytest.raises(stage_installer.StageError, match="virtualenv"):
        stage_installer.stage(str(tmp_path / "s1"), python_embed=embed,
                              wheelhouse=fake_wheels(tmp_path / "w1", ("pip-24.0-py3-none-any.whl",)))
    with pytest.raises(stage_installer.StageError, match="3.11"):
        stage_installer.stage(str(tmp_path / "s2"), python_embed=fake_embed(tmp_path / "old", minor=10),
                              wheelhouse=fake_wheels(tmp_path / "w2"))
    with pytest.raises(stage_installer.StageError, match="embeddable"):
        stage_installer.stage(str(tmp_path / "s3"), python_embed=str(tmp_path), wheelhouse=fake_wheels(tmp_path / "w3"))
    with pytest.raises(stage_installer.StageError, match="3.12"):
        stage_installer.stage(str(tmp_path / "s4"), python_embed=embed, wheelhouse=fake_wheels(tmp_path / "w4"),
                              tk_from=fake_full_python(tmp_path / "py311", minor=11))


def test_inno_script_is_per_user_and_keeps_user_data():
    raw = open(os.path.join(ROOT, "setup", "installer", "synox.iss"), "rb").read()
    raw.decode("ascii")
    text = raw.decode("ascii")
    assert "PrivilegesRequired=lowest" in text and "{localappdata}\\Programs\\SYNOX" in text
    assert "-Mode shortcuts" in text and "data" not in text.split("[UninstallDelete]")[1]
    assert "Setup.bat" in text.split("[Run]")[1]
