"""Lay out everything the Windows installer ships, ready for Inno Setup (docs/adr/0003, setup/installer/synox.iss).

    <python> scripts\\stage_installer.py --fetch-python | --python-archive <cpython-...-install_only_stripped.tar.gz>
                                        --wheelhouse <wheels> --tools <SYNOX_Libs>\\dist [--out dist\\installer-stage]
    ISCC.exe /DAppVersion=<version> /DStageDir=<out>\\SYNOX setup\\installer\\synox.iss

Run it on the release build machine (not the owner's daily machine). It never runs the Python it ships and never
runs pip. Inputs:

- the Python: the SAME python-build-standalone CPython that Setup.bat downloads for the ZIP. The URL and SHA256 are
                  read from setup/bootstrap.ps1 ($PythonUrl, $PythonSha256), so the .exe and the ZIP always ship an
                  identical interpreter (python.exe, pip, venv, tkinter + Tcl/Tk: the window wizard opens).
  --fetch-python  download that pinned file (to <out>\\downloads\\, outside the stage) and check its SHA256;
  --python-archive  or use a copy you already downloaded: it must have the same SHA256, or nothing is staged.
                  Either way the archive is unpacked with path checks (no absolute paths, no "..", no links) and
                  its python\\ folder becomes runtime\\python\\. bootstrap finds it there and runs `python -m venv`.
- --wheelhouse    every wheel of requirements.lock + pip + setuptools (scripts/lock_deps.py tells how);
                  bootstrap installs offline from it (no network on the user's machine).
- --tools         the built tool library (SYNOX_Libs scripts/build.py -> dist/), shipped as tools\\ (not installed).

The stage gets a STAGE-MANIFEST.txt with relative paths and sha256 only (no build-machine paths or user names).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_zip  # noqa: E402

ROOT = make_zip.ROOT
BOOTSTRAP = os.path.join(ROOT, "setup", "bootstrap.ps1")
# What a usable Windows build of python-build-standalone (install_only / install_only_stripped) has under python/.
REQUIRED = ("python.exe", "pythonw.exe", os.path.join("Lib", "venv", "__init__.py"),
            os.path.join("Lib", "tkinter", "__init__.py"), os.path.join("DLLs", "_tkinter.pyd"))
WHEELS = ("pip", "setuptools")


class StageError(ValueError):
    pass


def pinned_python(path: str = BOOTSTRAP) -> dict:
    """{"version", "build", "sha256", "url"} of the private Python pinned in setup/bootstrap.ps1."""
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    found = {}
    for key, name in (("version", "PythonVersion"), ("build", "PythonBuild"), ("sha256", "PythonSha256")):
        m = re.search(r"^\$%s = '([^']+)'" % name, text, re.M)
        if not m:
            raise StageError(f"setup/bootstrap.ps1 has no ${name}")
        found[key] = m.group(1)
    m = re.search(r'^\$PythonUrl = "([^"]+)"', text, re.M)
    if not m:
        raise StageError("setup/bootstrap.ps1 has no $PythonUrl")
    found["url"] = (m.group(1).replace("$PythonBuild", found["build"]).replace("$PythonVersion", found["version"]))
    if "$" in found["url"] or not re.match(r"^[0-9a-f]{64}$", found["sha256"]):
        raise StageError("setup/bootstrap.ps1: $PythonUrl / $PythonSha256 are not a plain URL and a sha256")
    return found


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_python(folder: str, pin: dict) -> str:
    """Download the pinned archive into folder; installer_ci.fetch keeps it only when the sha256 matches."""
    import installer_ci
    out = os.path.join(folder, pin["url"].rsplit("/", 1)[1].replace("%2B", "+"))
    if os.path.isfile(out) and sha256(out) == pin["sha256"]:
        return out
    try:
        return installer_ci.fetch(pin["url"], pin["sha256"], out)
    except installer_ci.CheckError as e:
        raise StageError(str(e))


def extract_python(archive: str, expected_sha256: str, dest: str) -> str:
    """Check the archive's sha256, then unpack its python/ folder to dest. Returns "3.X" from python3X.dll."""
    actual = sha256(archive)
    if actual != expected_sha256.lower():
        raise StageError(f"{os.path.basename(archive)}: sha256 {actual} is not the pinned {expected_sha256} "
                         "(setup/bootstrap.ps1 $PythonSha256)")
    tmp = dest + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for m in members:
                parts = m.name.replace("\\", "/").split("/")
                if (m.name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", m.name) or ".." in parts
                        or parts[0] != "python" or not (m.isfile() or m.isdir())):
                    raise StageError(f"unsafe or unexpected entry in {os.path.basename(archive)}: {m.name}")
            os.makedirs(tmp)
            if hasattr(tarfile, "data_filter"):
                tar.extractall(tmp, members=members, filter="data")
            else:                                                   # older 3.11: the checks above already ran
                tar.extractall(tmp, members=members)
    except (tarfile.TarError, OSError, EOFError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise StageError(f"cannot unpack {os.path.basename(archive)}: {e}")
    src = os.path.join(tmp, "python")
    missing = [rel for rel in REQUIRED if not os.path.isfile(os.path.join(src, rel))]
    if missing:
        shutil.rmtree(tmp, ignore_errors=True)
        raise StageError(f"{os.path.basename(archive)} is not a Windows install_only build "
                         f"(no {', '.join(missing)} under python/)")
    dlls = [n for n in os.listdir(src) if re.match(r"^python3(\d+)\.dll$", n)]
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.replace(src, dest)
    shutil.rmtree(tmp, ignore_errors=True)
    minor = re.match(r"^python3(\d+)\.dll$", dlls[0]).group(1) if dlls else "?"
    return f"3.{minor}"


def stage(out: str, *, wheelhouse: str, tools: str = "", python_archive: str = "", fetch: bool = False,
          pin: dict = None) -> dict:
    pin = pin or pinned_python()
    if bool(python_archive) == bool(fetch):
        raise StageError("give exactly one of --python-archive <file> or --fetch-python")
    try:
        files = make_zip.release_files(tools, wheelhouse)
    except ValueError as e:
        raise StageError(str(e))
    names = {os.path.basename(src) for src, rel in files if rel.startswith("wheelhouse/")}
    missing = [w for w in WHEELS if not any(n.lower().startswith(w + "-") for n in names)]
    if missing:
        raise StageError(f"wheelhouse is missing {', '.join(missing)} (needed to build .venv offline)")
    out = os.path.abspath(out)
    if fetch:
        python_archive = fetch_python(os.path.join(out, "downloads"), pin)
    if not os.path.isfile(python_archive):
        raise StageError(f"--python-archive not found: {python_archive}")
    target = os.path.join(out, "SYNOX")
    if os.path.exists(target):
        shutil.rmtree(target)
    py = os.path.join(target, "runtime", "python")
    python = extract_python(python_archive, pin["sha256"], py)
    if python != ".".join(pin["version"].split(".")[:2]):
        raise StageError(f"the archive holds Python {python}, but setup/bootstrap.ps1 pins {pin['version']}")
    for src, rel in files:
        dest = os.path.join(target, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
    manifest = [f"SYNOX {make_zip.version()} installer stage; Python {pin['version']} "
                f"(python-build-standalone {pin['build']}, sha256 {pin['sha256']}; same file as Setup.bat downloads)",
                f"lock: {'requirements.lock' if os.path.isfile(os.path.join(ROOT, 'requirements.lock')) else 'MISSING'}"]
    for src, rel in files:
        if rel.startswith(("tools/", "wheelhouse/")):
            manifest.append(f"{sha256(src)}  {rel}")
    with open(os.path.join(target, "STAGE-MANIFEST.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(manifest) + "\n")
    return {"folder": target, "files": len(files), "python": pin["version"],
            "lock": os.path.isfile(os.path.join(ROOT, "requirements.lock"))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--fetch-python", action="store_true",
                       help="download the Python pinned in setup/bootstrap.ps1 and check its sha256")
    which.add_argument("--python-archive", default="",
                       help="an already downloaded copy of that file (must have the pinned sha256)")
    parser.add_argument("--wheelhouse", required=True)
    parser.add_argument("--tools", default="")
    parser.add_argument("--out", default=os.path.join(ROOT, "dist", "installer-stage"))
    args = parser.parse_args(argv)
    try:
        result = stage(args.out, wheelhouse=args.wheelhouse, tools=args.tools, python_archive=args.python_archive,
                       fetch=args.fetch_python)
    except StageError as e:
        print(f"[X] {e}")
        return 2
    print(f"staged {result['files']} files + Python {result['python']} -> {result['folder']}")
    if not result["lock"]:
        print("[!] requirements.lock is missing: run scripts/lock_deps.py first so every install gets the same versions")
    print(f'next: ISCC.exe /DAppVersion={make_zip.version()} /DStageDir="{result["folder"]}" setup\\installer\\synox.iss')
    return 0


if __name__ == "__main__":
    sys.exit(main())
