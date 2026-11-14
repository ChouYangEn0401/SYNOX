# -*- coding: utf-8 -*-
"""發佈物的版面（docs/adr/0003）：zip 旁邊附 tools/、安裝程式的 stage。只複製檔案；不執行任何 Python、不 pip、不打包 exe。
假的 Python（python-build-standalone 的 .tar.gz）只是幾個位元組的檔案（不會被執行）。"""
import glob
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
    assert not any(n.startswith(("SYNOX/tests/", "SYNOX/docs/lab/", "SYNOX/.github/workflows/")) for n in names)


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


# 一般使用者執行、更新 SYNOX 要的（擁有者 2026-11-14 D2：發佈 ZIP／安裝程式只帶這些，git clone 才有開發用的）
NEEDED = ("Setup.bat", "Start.bat", "Stop.bat", "Open-SYNOX.bat", "Install-Pack.bat", "Uninstall.bat", "Console.bat",
          "README.md", "CHANGELOG.md", "LICENSE", "LICENSE-APACHE", "NOTICE", "LICENSING.md", "SECURITY.md",
          "CONTRIBUTING.md", ".github/TRADEMARK.md", ".github/GOVERNANCE.md", ".github/MAINTAINERS.md",
          "config.example.json", "pyproject.toml", "requirements.txt", "packs/README.md",
          "setup/bootstrap.ps1", "setup/clean-python-env.bat", "setup/uninstall.ps1", "setup/installer/synox.iss",
          "src/synox/__init__.py", "src/synox/assets/synox.ico", "docs/tutorials/README.md",
          "docs/tutorials/telegram/index.html", "docs/landing/index.html", "docs/versioning.md", "docs/README.md",
          "docs/legacy/connectors.md", "sdk/synox_sdk.py")


def test_release_has_what_users_need_and_nothing_internal():
    shipped = {rel for _src, rel in make_zip.release_files()}
    for rel in NEEDED:
        assert rel in shipped, rel
    assert {r for r in shipped if "/" not in r and r.endswith(".bat")} == {
        os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.bat"))}          # 每個入口都在
    assert any(r.startswith("vendor/") for r in shipped) and any(r.startswith("src/synox/evals/") for r in shipped)
    for rel in shipped:
        assert not make_zip.internal(rel), rel
    for prefix in ("tests/", "evals/", "docs/lab/", "docs/artifacts/", "docs/ui/", "docs/installer/",
                   ".github/workflows/", ".github/ISSUE_TEMPLATE/", ".devcontainer/"):
        assert not any(r.startswith(prefix) for r in shipped), prefix
    for rel in ("docs/QuestionToUser.md", "docs/artifacts.json", ".github/pull_request_template.md",
                "Connect-Apple.bat", "GOVERNANCE.md", "TRADEMARK.md", "MAINTAINERS.md"):
        assert rel not in shipped, rel
    if os.path.exists(os.path.join(ROOT, ".git")):              # git clone（不是 clean_room_check 的副本）：
        for rel in make_zip.INTERNAL:                           # 清單上的都真的存在（沒有打錯字）
            assert os.path.exists(os.path.join(ROOT, *rel.rstrip("/").split("/"))), rel


def test_clean_room_copy_takes_tests_but_never_user_data():
    names = {rel for _src, rel in make_zip.release_files(also=("tests/",))}
    assert "tests/conftest.py" in names and not any(r.startswith("docs/lab/") for r in names)
    assert make_zip.never("tests/data/x.json") and make_zip.never("tests/x/config.json")


def test_internal_list_is_the_same_for_github_zip_and_installer_updates():
    """make_zip.INTERNAL＝.gitattributes 的 export-ignore（GitHub 的 Download ZIP）＝synox.iss [InstallDelete] 會刪的。"""
    internal = {p.rstrip("/") for p in make_zip.INTERNAL}
    attrs = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read().splitlines()
    ignored = {line.split()[0].lstrip("/") for line in attrs if line.strip().endswith(" export-ignore")}
    assert ignored == internal
    removed = {p.replace("\\", "/") for p in install_delete()}
    assert internal <= removed
    assert not removed & {"config.json", "data", "packs"} and not any(r.startswith(("data/", "packs/")) for r in removed)


def install_delete():
    text = open(os.path.join(ROOT, "setup", "installer", "synox.iss"), "rb").read().decode("ascii")
    section = text.split("\r\n[InstallDelete]\r\n", 1)[1].split("\r\n[", 1)[0]
    return [line.split('Name: "{app}\\', 1)[1].split('"', 1)[0] for line in section.splitlines()
            if line.startswith("Type:")]


def test_installer_update_over_an_older_install_keeps_user_data(tmp_path):
    """舊版（帶 tests\\、docs\\lab\\、Connect-Apple.bat…）上面裝新版：照 [InstallDelete] 刪、再放新檔。
    使用者的 config.json、data\\、packs\\ 都在；舊版才有的開發用檔案不見了；新版的檔案都在。"""
    import shutil
    app = tmp_path / "SYNOX"
    for rel in ("tests/test_x.py", "docs/lab/x.md", "docs/QuestionToUser.md", "evals/a.json", "Connect-Apple.bat",
                "TRADEMARK.md", ".github/workflows/ci.yml", "config.json", "data/vault.bin", "packs/notes/pack.json",
                "docs/tutorials/README.md"):
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_text("old " + rel, encoding="utf-8")
    for name in install_delete():                                   # Inno：[InstallDelete] 在複製檔案之前
        target = app / name.replace("\\", "/")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    for src, rel in make_zip.release_files():
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, app / rel)
    for rel in ("config.json", "data/vault.bin", "packs/notes/pack.json"):
        assert (app / rel).read_text(encoding="utf-8") == "old " + rel
    for rel in ("tests", "docs/lab", "docs/QuestionToUser.md", "evals", "Connect-Apple.bat", "TRADEMARK.md",
                ".github/workflows"):
        assert not (app / rel).exists(), rel
    assert (app / ".github" / "TRADEMARK.md").is_file() and (app / "Setup.bat").is_file()
    assert (app / "docs" / "tutorials" / "README.md").read_text(encoding="utf-8") != "old docs/tutorials/README.md"


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
