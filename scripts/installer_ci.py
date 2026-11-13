"""Small, testable helpers for the installer build workflow (.github/workflows/build-installer.yml, docs/release-build.md).

    <python> scripts/installer_ci.py version [--tag v0.2.0]           print the version (pyproject == synox.__version__;
                                                                       with --tag also == the tag without "v")
    <python> scripts/installer_ci.py fetch URL --sha256 HEX --out FILE download, then keep the file only if its sha256
                                                                       matches the pinned value (https:// or file:// only)
    <python> scripts/installer_ci.py extract ZIP --out DIR             unzip, refusing absolute paths and ".." entries

Standard library only. It never runs anything it downloads or extracts. Exit code: 0 ok, 1 check failed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import tempfile
import tomllib
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEX64 = re.compile(r"^[0-9a-f]{64}$")
INIT_VERSION = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.M)
USER_AGENT = "synox-installer-build"


class CheckError(ValueError):
    pass


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def project_version(root: str = ROOT) -> str:
    """pyproject.toml [project].version; CheckError when src/synox/__init__.py says something else."""
    with open(os.path.join(root, "pyproject.toml"), "rb") as f:
        version = tomllib.load(f)["project"]["version"]
    with open(os.path.join(root, "src", "synox", "__init__.py"), "r", encoding="utf-8") as f:
        m = INIT_VERSION.search(f.read())
    if not m:
        raise CheckError("src/synox/__init__.py has no __version__")
    if m.group(1) != version:
        raise CheckError(f"pyproject.toml says {version} but synox.__version__ is {m.group(1)}")
    return version


def check_tag(version: str, tag: str) -> None:
    if tag and tag != f"v{version}":
        raise CheckError(f"tag {tag} does not match the project version {version} (expected v{version})")


def fetch(url: str, expected: str, out: str) -> str:
    """Download url to out and verify its sha256. The file only appears at out when the hash matches."""
    expected = expected.strip().lower()
    if not HEX64.match(expected):
        raise CheckError(f"pinned sha256 is not 64 hex characters: {expected!r}")
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("https", "file"):
        raise CheckError(f"only https:// (or file:// for tests) is allowed, not {scheme or 'a bare path'}")
    folder = os.path.dirname(os.path.abspath(out))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with os.fdopen(fd, "wb") as f, urllib.request.urlopen(req, timeout=300) as resp:
            shutil.copyfileobj(resp, f)
        actual = sha256_file(tmp)
        if actual != expected:
            raise CheckError(f"sha256 mismatch for {url}: expected {expected}, got {actual}")
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out


def safe_extract(zip_path: str, out: str) -> list:
    """Extract every entry under out; CheckError (and nothing written) on absolute paths, drive letters or '..'."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        for name in names:
            parts = name.replace("\\", "/").split("/")
            if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name) or ".." in parts:
                raise CheckError(f"unsafe path in {os.path.basename(zip_path)}: {name}")
        os.makedirs(out, exist_ok=True)
        z.extractall(out)
    return names


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("version", help="print the project version (checks pyproject == synox.__version__)")
    p.add_argument("--tag", default="", help="a release tag such as v0.2.0; must match the version")
    p = sub.add_parser("fetch", help="download a file and verify its pinned sha256")
    p.add_argument("url")
    p.add_argument("--sha256", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("extract", help="unzip without allowing paths outside the target folder")
    p.add_argument("zip")
    p.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "version":
            version = project_version()
            check_tag(version, args.tag)
            print(version)
        elif args.cmd == "fetch":
            fetch(args.url, args.sha256, args.out)
            print(f"ok  sha256 {args.sha256.lower()}  {os.path.basename(args.out)}")
        else:
            names = safe_extract(args.zip, args.out)
            print(f"extracted {len(names)} entries from {os.path.basename(args.zip)}")
    except (CheckError, OSError, zipfile.BadZipFile) as e:
        print(f"[X] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
