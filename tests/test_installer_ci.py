# -*- coding: utf-8 -*-
"""安裝程式的自動建置（.github/workflows/build-installer.yml、scripts/installer_ci.py、docs/release-build.md）。
不連網：下載只用 file:// 網址；workflow 只讀文字（有 PyYAML 時再多解析一次），不會真的跑。"""
import hashlib
import os
import re
import shutil
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import installer_ci  # noqa: E402

WORKFLOW = os.path.join(ROOT, ".github", "workflows", "build-installer.yml")


def _text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _env(name):
    m = re.search(rf'^  {name}: "([^"]*)"', _text(WORKFLOW), re.M)
    assert m, f"{name} is not pinned in the workflow env"
    return m.group(1)


# ---- scripts/installer_ci.py -------------------------------------------------------------------

def test_version_matches_pyproject_and_package():
    version = installer_ci.project_version()
    assert re.match(r"^\d+\.\d+\.\d+", version)
    installer_ci.check_tag(version, f"v{version}")
    installer_ci.check_tag(version, "")
    with pytest.raises(installer_ci.CheckError):
        installer_ci.check_tag(version, "v0.0.0-not-this")


def test_version_mismatch_is_refused(tmp_path):
    (tmp_path / "src" / "synox").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "synox"\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "src" / "synox" / "__init__.py").write_text('__version__ = "1.2.4"\n', encoding="utf-8")
    with pytest.raises(installer_ci.CheckError, match="1.2.4"):
        installer_ci.project_version(str(tmp_path))


def test_version_cli_rejects_wrong_tag(capsys):
    assert installer_ci.main(["version", "--tag", "v999.0.0"]) == 1
    assert "does not match" in capsys.readouterr().err
    assert installer_ci.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == installer_ci.project_version()


def test_fetch_keeps_the_file_only_when_sha256_matches(tmp_path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"a downloaded file, pretend")
    good = hashlib.sha256(src.read_bytes()).hexdigest()
    out = tmp_path / "dl" / "out.bin"
    assert installer_ci.main(["fetch", src.as_uri(), "--sha256", good.upper(), "--out", str(out)]) == 0
    assert out.read_bytes() == src.read_bytes()
    out.unlink()
    with pytest.raises(installer_ci.CheckError, match="mismatch"):
        installer_ci.fetch(src.as_uri(), "0" * 64, str(out))
    assert not out.exists()
    assert os.listdir(tmp_path / "dl") == []           # no .part left behind


def test_fetch_refuses_bad_pins_and_plain_http(tmp_path):
    with pytest.raises(installer_ci.CheckError, match="64 hex"):
        installer_ci.fetch("https://example.com/x", "abc", str(tmp_path / "x"))
    with pytest.raises(installer_ci.CheckError, match="https"):
        installer_ci.fetch("http://example.com/x", "0" * 64, str(tmp_path / "x"))
    assert installer_ci.main(["fetch", (tmp_path / "missing").as_uri(), "--sha256", "0" * 64,
                              "--out", str(tmp_path / "y")]) == 1


def test_extract_refuses_paths_outside_the_target(tmp_path):
    ok = tmp_path / "ok.zip"
    with zipfile.ZipFile(ok, "w") as z:
        z.writestr("tools/index.json", "{}")
    assert installer_ci.main(["extract", str(ok), "--out", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "tools" / "index.json").read_text() == "{}"
    for evil in ("../evil.txt", "tools/../../evil.txt", "/abs.txt", "C:/win.txt"):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("fine.txt", "x")
            z.writestr(evil, "x")
        target = tmp_path / "bad-out"
        shutil.rmtree(target, ignore_errors=True)
        assert installer_ci.main(["extract", str(bad), "--out", str(target)]) == 1, evil
        assert not target.exists(), evil


# ---- .github/workflows/build-installer.yml -----------------------------------------------------

def test_every_action_is_pinned_to_a_full_commit_sha():
    uses = re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)(.*)$", _text(WORKFLOW), re.M)
    assert uses, "the workflow uses no actions?"
    for ref, comment in uses:
        assert re.match(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$", ref), ref
        assert re.search(r"#\s*v\d", comment), f"{ref}: add the human-readable tag as a comment"


def test_downloads_are_pinned_with_sha256():
    for name in ("LIBS_TOOLS_SHA256", "INNO_SHA256"):
        assert re.match(r"^[0-9a-f]{64}$", _env(name)), name
    assert re.match(r"^\d+\.\d+\.\d+$", _env("PYTHON_VERSION"))
    assert re.match(r"^6\.\d+\.\d+$", _env("INNO_VERSION")), "synox.iss is written for Inno Setup 6"
    assert _env("INNO_TAG") == "is-" + _env("INNO_VERSION").replace(".", "_")
    for name in ("PIP_VERSION", "SETUPTOOLS_VERSION"):
        assert re.match(r"^\d+(\.\d+)+$", _env(name)), name
    text = _text(WORKFLOW)
    assert text.count("installer_ci.py fetch") == 2        # tools zip, Inno Setup: both verified
    assert "'--fetch-python'" in text                      # the shipped Python: pinned in setup/bootstrap.ps1, sha256 checked
    for gone in ("PYTHON_EMBED_SHA256", "embed-amd64", "--python-embed", "--tk-from", "virtualenv", "WITH_TK"):
        assert gone not in text, gone


def test_least_privilege_and_draft_only_release():
    text = _text(WORKFLOW)
    assert re.search(r"^permissions:\n  contents: read$", text, re.M)
    assert text.count("contents: write") == 1
    release = text[text.index("\n  draft-release:"):]
    assert "contents: write" in release and "contents: write" not in text[:text.index("\n  draft-release:")]
    assert "if: github.ref_type == 'tag'" in release
    assert "--draft" in release and "isDraft" in release
    create = [line for line in release.splitlines() if "gh release create" in line]
    assert create and all("--draft" in line for line in create)
    assert "gh release edit" not in text and "--draft=false" not in text
    assert "secrets." not in text                          # public repo, unsigned build: no secrets at all
    assert "persist-credentials: false" in text
    assert "pull_request_target" not in text


def test_workflow_matches_the_installer_script_and_stage_tool():
    text = _text(WORKFLOW)
    iss = _text(os.path.join(ROOT, "setup", "installer", "synox.iss"))
    for macro in ("AppVersion", "StageDir"):
        assert f"#ifndef {macro}" in iss and f"/D{macro}=" in text
    assert "setup\\installer\\synox.iss" in text
    for flag in ("--fetch-python", "--wheelhouse", "--tools"):
        assert flag in text
        assert flag in _text(os.path.join(ROOT, "scripts", "stage_installer.py"))
    smoke = text[text.index("Offline smoke test of the stage"):]
    assert "& $rt -m venv" in smoke and "import tkinter" in smoke    # same as bootstrap: python -m venv, tkinter must load
    assert "windows-latest" in text
    assert "workflow_dispatch" in text and '"v*"' in text


def test_build_python_minor_version_matches_the_shipped_python():
    """The wheelhouse is built with setup-python's X.Y; the shipped Python (pinned in bootstrap.ps1) must be the same X.Y."""
    m = re.search(r"^\$PythonVersion = '(\d+\.\d+)\.\d+'", _text(os.path.join(ROOT, "setup", "bootstrap.ps1")), re.M)
    assert m, "setup/bootstrap.ps1 has no $PythonVersion"
    assert _env("PYTHON_VERSION").rsplit(".", 1)[0] == m.group(1)


def test_workflow_parses_as_yaml():
    yaml = pytest.importorskip("yaml")
    with open(WORKFLOW, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    on = data.get("on", data.get(True))
    assert set(on) == {"workflow_dispatch", "push"} and on["push"]["tags"] == ["v*"]
    assert data["permissions"] == {"contents": "read"}
    assert data["jobs"]["build"]["runs-on"] == "windows-latest"
    assert data["jobs"]["build"]["permissions"] == {"contents": "read"}
    assert data["jobs"]["draft-release"]["permissions"] == {"contents": "write"}
    assert data["jobs"]["draft-release"]["needs"] == "build"


def test_release_build_doc_exists_and_links_the_clean_machine_test():
    doc = _text(os.path.join(ROOT, "docs", "release-build.md"))
    assert "handoff/clean-machine-test.md" in doc and "SmartScreen" in doc
    for name in ("LIBS_TOOLS_SHA256", "INNO_SHA256"):
        assert _env(name) in doc, f"{name} in the doc is out of date"
    sha = re.search(r"^\$PythonSha256 = '([0-9a-f]{64})'", _text(os.path.join(ROOT, "setup", "bootstrap.ps1")), re.M)
    assert sha and sha.group(1) in doc, "the shipped Python's sha256 in the doc is out of date"
