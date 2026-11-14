"""Pack SYNOX into a zip to hand to someone: dist/SYNOX-<version>.zip.

    .venv\\Scripts\\python.exe scripts\\make_zip.py [--out dist] [--tools <SYNOX_Libs>\\dist] [--wheelhouse <folder>]

Takes the files git tracks (so nothing you did not commit sneaks in) and always leaves out
.venv/, data/, config.json, runtime/, dist/ and caches -- the zip never contains a token, a key or your data.
What only people working ON SYNOX use (INTERNAL: tests/, evals/, docs/lab/, CI, ...) is left out too: the zip and
the installer (stage_installer.py uses this same list) carry what a user needs to run and update SYNOX; `git clone`
has everything. GitHub's own "Download ZIP" leaves out the same paths (export-ignore in .gitattributes), and an update
by the installer deletes them from an older install (synox.iss [InstallDelete]); tests/test_release_layout.py keeps
the three lists equal.
Falls back to walking the folder when git is not available.

--tools: also put the tool library next to SYNOX as SYNOX/tools/ (index.json + every .synoxpack it lists, sha256
checked first). SYNOX finds it there without any setting (packs.library defaults to the "tools" folder, relative
to the SYNOX folder) and `synox init` lists it; nothing is installed until the user picks (docs/adr/0003, QL4).
--wheelhouse: also put downloaded wheels as SYNOX/wheelhouse/ so Setup.bat installs offline (scripts/lock_deps.py).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDED_DIRS = {".venv", "data", "dist", ".git", "__pycache__", ".pytest_cache"}
ROOT_ONLY_DIRS = {"runtime", "tools", "wheelhouse"}   # 只看 SYNOX 資料夾最上層的（執行時的狀態、另外附的東西）；
#                                                       src/synox/runtime 是程式碼
EXCLUDED_FILES = {"config.json"}
# 只給在 SYNOX 上開發的人（git clone 才有）：發佈 ZIP、安裝程式都不帶，執行、更新 SYNOX 都用不到（擁有者 2026-11-14 決定 D2）。
# 結尾有 / 的是資料夾，只比 SYNOX 資料夾最上層（src/synox/evals 是程式碼，照發）。改這份清單要一起改 .gitattributes 的
# export-ignore（GitHub 的 Download ZIP）與 setup/installer/synox.iss 的 [InstallDelete]（舊版裝過的人更新時刪掉）。
INTERNAL = ("tests/", "evals/", "docs/lab/", "docs/artifacts/", "docs/artifacts.json", "docs/QuestionToUser.md",
            "docs/ui/", "docs/installer/", ".github/workflows/", ".github/ISSUE_TEMPLATE/",
            ".github/pull_request_template.md", ".devcontainer/")


def internal(rel: str) -> bool:
    """Only for people working on SYNOX (INTERNAL): not in the zip, not in the installer."""
    rel = rel.replace("\\", "/")
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in INTERNAL)


def never(rel: str) -> bool:
    """.venv、data、config.json、caches…: not even in a developer's copy (clean_room_check.py)."""
    parts = rel.replace("\\", "/").split("/")
    return (any(p in EXCLUDED_DIRS or p.endswith(".egg-info") for p in parts[:-1])
            or (len(parts) > 1 and parts[0] in ROOT_ONLY_DIRS)
            or parts[-1] in EXCLUDED_FILES or parts[-1].endswith((".pyc", ".tmp")))


def excluded(rel: str) -> bool:
    return never(rel) or internal(rel)


def tracked_files() -> list:
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, timeout=60)
        if out.returncode == 0:
            return [f for f in out.stdout.decode("utf-8").split("\0") if f]
    except (OSError, subprocess.SubprocessError):
        pass
    found = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.endswith(".egg-info")
                   and not (folder == ROOT and d in ROOT_ONLY_DIRS)]
        found += [os.path.relpath(os.path.join(folder, f), ROOT) for f in files]
    return found


def version() -> str:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from synox import __version__
    return __version__


def tool_files(folder: str) -> list:
    """A built tool library (SYNOX_Libs dist/) -> [(source path, name inside tools/)]: index.json and every
    .synoxpack it lists, sha256 checked. ValueError (readable) when it is not a built library."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from synox.wizard import tools as library
    try:
        lib = library.read(os.path.abspath(folder))
        packs = [(library.file_of(lib, e), e.file) for e in lib.entries]
    except library.LibraryError as e:
        raise ValueError(str(e))
    return [(os.path.join(lib.folder, library.INDEX), library.INDEX)] + packs


def wheel_files(folder: str) -> list:
    if not os.path.isdir(folder):
        raise ValueError(f"wheelhouse folder not found: {folder}")
    names = sorted(n for n in os.listdir(folder) if n.endswith(".whl"))
    if not names:
        raise ValueError(f"no .whl files in {folder}")
    return [(os.path.join(folder, n), n) for n in names]


def release_files(tools: str = "", wheelhouse: str = "", *, also: tuple = ()) -> list:
    """[(source path, path inside the SYNOX folder, with /)] for everything that ships; stage_installer.py uses it too.
    also: INTERNAL folders to take anyway (clean_room_check.py runs tests/ inside its copy); never for a release."""
    def wanted(rel: str) -> bool:
        rel = rel.replace("\\", "/")
        return not excluded(rel) or (bool(also) and not never(rel) and rel.startswith(tuple(also)))

    files = sorted(f for f in tracked_files() if wanted(f) and os.path.isfile(os.path.join(ROOT, f)))
    out = [(os.path.join(ROOT, rel), rel.replace(os.sep, "/")) for rel in files]
    if tools:
        out += [(src, "tools/" + name) for src, name in tool_files(tools)]
    if wheelhouse:
        out += [(src, "wheelhouse/" + name) for src, name in wheel_files(wheelhouse)]
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--tools", default="", help="built tool library (SYNOX_Libs dist/: *.synoxpack + index.json)")
    parser.add_argument("--wheelhouse", default="", help="folder of wheels for an offline install")
    args = parser.parse_args(argv)
    try:
        files = release_files(args.tools, args.wheelhouse)
    except ValueError as e:
        print(f"[X] {e}")
        return 2
    os.makedirs(args.out, exist_ok=True)
    target = os.path.join(args.out, f"SYNOX-{version()}.zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for src, rel in files:
            z.write(src, "SYNOX/" + rel)
    print(f"{target}  ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
