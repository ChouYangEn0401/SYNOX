"""Pack SYNOX into a zip to hand to someone: dist/SYNOX-<version>.zip.

    .venv\\Scripts\\python.exe scripts\\make_zip.py [--out dist]

Takes the files git tracks (so nothing you did not commit sneaks in) and always leaves out
.venv/, data/, config.json, runtime/, dist/ and caches -- the zip never contains a token, a key or your data.
Falls back to walking the folder when git is not available.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDED_DIRS = {".venv", "data", "runtime", "dist", ".git", "__pycache__", ".pytest_cache"}
EXCLUDED_FILES = {"config.json"}


def excluded(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    return (any(p in EXCLUDED_DIRS or p.endswith(".egg-info") for p in parts[:-1])
            or parts[-1] in EXCLUDED_FILES or parts[-1].endswith((".pyc", ".tmp")))


def tracked_files() -> list:
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, timeout=60)
        if out.returncode == 0:
            return [f for f in out.stdout.decode("utf-8").split("\0") if f]
    except (OSError, subprocess.SubprocessError):
        pass
    found = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.endswith(".egg-info")]
        found += [os.path.relpath(os.path.join(folder, f), ROOT) for f in files]
    return found


def version() -> str:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from synox import __version__
    return __version__


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    target = os.path.join(args.out, f"SYNOX-{version()}.zip")
    files = sorted(f for f in tracked_files() if not excluded(f) and os.path.isfile(os.path.join(ROOT, f)))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(os.path.join(ROOT, rel), os.path.join("SYNOX", rel))
    print(f"{target}  ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
