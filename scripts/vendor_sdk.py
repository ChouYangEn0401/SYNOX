"""Copy ISDTeleKitSDK's package into vendor/isdtelekit and record which version it was.

    .venv\\Scripts\\python.exe scripts\\vendor_sdk.py [--sdk <ISDTeleKitSDK checkout>]

Where the SDK checkout is: --sdk, else the ISDTELEKIT_SDK environment variable, else a folder named
ISDTeleKitSDK next to SYNOX (only a convenience for the maintainer; a clean machine never needs this
script, because vendor/ is committed).

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
SIBLING_SDK = os.path.join(os.path.dirname(ROOT), "ISDTeleKitSDK")   # clean-room: sibling-fallback


def default_sdk(environ=None) -> str:
    environ = os.environ if environ is None else environ
    return environ.get("ISDTELEKIT_SDK") or SIBLING_SDK


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
    parser.add_argument("--sdk", default="", help="ISDTeleKitSDK checkout (default: $ISDTELEKIT_SDK, else next to SYNOX)")
    args = parser.parse_args(argv)
    sdk = args.sdk or default_sdk()
    src = os.path.join(os.path.abspath(sdk), "src", "isdtelekit")
    if not os.path.isfile(os.path.join(src, "__init__.py")):
        print(f"[X] SDK package not found: {src}")
        print("    Pass --sdk <ISDTeleKitSDK checkout> or set ISDTELEKIT_SDK.")
        return 1
    dest = os.path.join(ROOT, "vendor", "isdtelekit")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    version, commit = sdk_version(src), sdk_commit(os.path.abspath(sdk))
    with open(os.path.join(ROOT, "vendor", "VERSION"), "w", encoding="ascii", newline="\n") as f:
        f.write(f"isdtelekit {version}\ncommit {commit}\nvendored {datetime.date.today().isoformat()}\n")
    print(f"vendored isdtelekit {version} ({commit}) -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
