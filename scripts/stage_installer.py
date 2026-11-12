"""Lay out everything the Windows installer ships, ready for Inno Setup (docs/adr/0002, setup/installer/synox.iss).

    <python> scripts\\stage_installer.py --python-embed <extracted python-3.12.x-embed-amd64>
                                        --wheelhouse <wheels> --tools <SYNOX_Libs>\\dist
                                        [--tk-from <installed CPython 3.12.x of the SAME version>] [--out dist\\installer-stage]
    ISCC.exe /DAppVersion=<version> /DStageDir=<out>\\SYNOX setup\\installer\\synox.iss

Copy only: it never downloads, never runs the Python it copies, never runs pip. Run it on the release build
machine (not the owner's daily machine). Inputs are folders already on disk:

- --python-embed  the official "Windows embeddable package (64-bit)" zip, extracted. Copied to runtime\\python\\ and
                  its python3XX._pth gets "import site" (same as setup/bootstrap.ps1 does) -- bootstrap finds it there.
- --wheelhouse    every wheel of requirements.lock + pip + virtualenv + setuptools (scripts/lock_deps.py tells how);
                  bootstrap installs offline from it (no network on the user's machine).
- --tools         the built tool library (SYNOX_Libs scripts/build.py -> dist/), shipped as tools\\ (not installed).
- --tk-from       optional: an installed CPython of the same X.Y version; its tkinter files are copied so the
                  window wizard can open. Without it Setup falls back to the text `synox init` (still works).

The stage gets a STAGE-MANIFEST.txt with relative paths and sha256 only (no build-machine paths or user names).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_zip  # noqa: E402

ROOT = make_zip.ROOT
PTH_RE = re.compile(r"^python(3)(\d+)\._pth$")
TK_FILES = ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll")


class StageError(ValueError):
    pass


def embed_version(folder: str) -> tuple:
    """(3, minor) from the python3XX._pth file name of an extracted embeddable package."""
    if not os.path.isdir(folder):
        raise StageError(f"--python-embed folder not found: {folder}")
    for name in os.listdir(folder):
        m = PTH_RE.match(name)
        if m:
            return int(m.group(1)), int(m.group(2))
    raise StageError(f"{folder} is not an extracted embeddable Python (no python3XX._pth)")


def enable_site(pth_path: str, extra_lines=()) -> None:
    with open(pth_path, "r", encoding="ascii") as f:
        lines = f.read().splitlines()
    lines = ["import site" if re.match(r"^#\s*import site", x) else x for x in lines]
    for extra in extra_lines:
        if extra not in lines:
            lines.insert(0, extra)
    with open(pth_path, "w", encoding="ascii", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def copy_tk(tk_from: str, dest_python: str, minor: int) -> list:
    """tkinter from an installed CPython of the same minor version -> runtime\\python. Returns what was copied."""
    if not os.path.isfile(os.path.join(tk_from, f"python3{minor}.dll")):
        raise StageError(f"--tk-from must be an installed CPython 3.{minor} (no python3{minor}.dll in {tk_from})")
    copied = []
    for name in TK_FILES:
        src = os.path.join(tk_from, "DLLs", name)
        if not os.path.isfile(src):
            raise StageError(f"--tk-from has no DLLs\\{name} (install Python with the tcl/tk option)")
        shutil.copy2(src, os.path.join(dest_python, name))
        copied.append(name)
    for sub in (("Lib", "tkinter"), ("tcl",)):
        src = os.path.join(tk_from, *sub)
        if not os.path.isdir(src):
            raise StageError(f"--tk-from has no {os.path.join(*sub)}")
        shutil.copytree(src, os.path.join(dest_python, *sub), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "test", "tests", "idle_test"))
        copied.append(os.path.join(*sub))
    return copied


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(out: str, *, python_embed: str, wheelhouse: str, tools: str = "", tk_from: str = "") -> dict:
    major, minor = embed_version(python_embed)
    if (major, minor) < (3, 11):
        raise StageError(f"SYNOX needs Python 3.11+ (the embeddable package is 3.{minor})")
    try:
        files = make_zip.release_files(tools, wheelhouse)
    except ValueError as e:
        raise StageError(str(e))
    names = {os.path.basename(src) for src, rel in files if rel.startswith("wheelhouse/")}
    missing = [w for w in ("pip", "virtualenv", "setuptools") if not any(n.lower().startswith(w + "-") for n in names)]
    if missing:
        raise StageError(f"wheelhouse is missing {', '.join(missing)} (needed to build .venv offline)")
    target = os.path.join(os.path.abspath(out), "SYNOX")
    if os.path.exists(target):
        shutil.rmtree(target)
    for src, rel in files:
        dest = os.path.join(target, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
    py = os.path.join(target, "runtime", "python")
    shutil.copytree(python_embed, py)
    tk = copy_tk(tk_from, py, minor) if tk_from else []
    enable_site(os.path.join(py, f"python3{minor}._pth"), extra_lines=("Lib",) if tk else ())
    manifest = [f"SYNOX {make_zip.version()} installer stage; Python 3.{minor} embeddable"
                + ("; tkinter copied" if tk else "; no tkinter (Setup uses the text synox init)"),
                f"lock: {'requirements.lock' if os.path.isfile(os.path.join(ROOT, 'requirements.lock')) else 'MISSING'}"]
    for src, rel in files:
        if rel.startswith(("tools/", "wheelhouse/")):
            manifest.append(f"{sha256(src)}  {rel}")
    with open(os.path.join(target, "STAGE-MANIFEST.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(manifest) + "\n")
    return {"folder": target, "files": len(files), "tk": bool(tk), "python": f"3.{minor}",
            "lock": os.path.isfile(os.path.join(ROOT, "requirements.lock"))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python-embed", required=True)
    parser.add_argument("--wheelhouse", required=True)
    parser.add_argument("--tools", default="")
    parser.add_argument("--tk-from", default="")
    parser.add_argument("--out", default=os.path.join(ROOT, "dist", "installer-stage"))
    args = parser.parse_args(argv)
    try:
        result = stage(args.out, python_embed=args.python_embed, wheelhouse=args.wheelhouse, tools=args.tools,
                       tk_from=args.tk_from)
    except StageError as e:
        print(f"[X] {e}")
        return 2
    print(f"staged {result['files']} files + Python {result['python']} -> {result['folder']}")
    if not result["lock"]:
        print("[!] requirements.lock is missing: run scripts/lock_deps.py first so every install gets the same versions")
    if not result["tk"]:
        print("[!] no tkinter: the installed SYNOX will use the text setup (synox init) instead of the window wizard")
    print(f'next: ISCC.exe /DAppVersion={make_zip.version()} /DStageDir="{result["folder"]}" setup\\installer\\synox.iss')
    return 0


if __name__ == "__main__":
    sys.exit(main())
