"""Copy ISDTeleKitSDK's package into vendor/isdtelekit and record which version it was.

    .venv\\Scripts\\python.exe scripts\\vendor_sdk.py [--sdk C:\\path\\to\\ISDTeleKitSDK]

vendor/ is a verbatim copy: never edit files under vendor/isdtelekit. If SYNOX needs different behaviour,
write an adapter inside src/synox and note it in docs/AGENT.md. When the SDK is published (GitHub / PyPI),
replace vendor/ with a normal dependency.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SDK = os.path.join(os.path.dirname(ROOT), "ISDTeleKitSDK")


def sdk_version(package_dir: str) -> str:
    with open(os.path.join(package_dir, "__init__.py"), encoding="utf-8") as f:
        m = re.search(r'^__version__\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
    return m.group(1) if m else "unknown"


def sdk_commit(sdk_root: str) -> str:
    try:
        out = subprocess.run(["git", "-C", sdk_root, "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=30)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sdk", default=DEFAULT_SDK, help="ISDTeleKitSDK checkout (default: next to SYNOX)")
    args = parser.parse_args(argv)
    src = os.path.join(os.path.abspath(args.sdk), "src", "isdtelekit")
    if not os.path.isfile(os.path.join(src, "__init__.py")):
        print(f"[X] SDK package not found: {src}")
        return 1
    dest = os.path.join(ROOT, "vendor", "isdtelekit")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    version, commit = sdk_version(src), sdk_commit(os.path.abspath(args.sdk))
    with open(os.path.join(ROOT, "vendor", "VERSION"), "w", encoding="ascii", newline="\n") as f:
        f.write(f"isdtelekit {version}\ncommit {commit}\nvendored {datetime.date.today().isoformat()}\n")
    print(f"vendored isdtelekit {version} ({commit}) -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
