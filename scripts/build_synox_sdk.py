# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ChouYangEn and the SYNOX Team
"""從正本 src/synox/sdk/author.py 產生單檔版 synox_sdk.py（作者可以直接複製進自己的 repo，零相依）。

    .venv\\Scripts\\python.exe scripts\\build_synox_sdk.py            寫 sdk/synox_sdk.py 與 examples/hello/synox_sdk.py
    .venv\\Scripts\\python.exe scripts\\build_synox_sdk.py --check    只比對，不一樣就結束碼 1（tests/test_sdk_author.py 也會比）

改 SDK 一律改 author.py，再跑這支；不要直接改產生出來的檔。
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")]

from synox.sdk import single_file_source  # noqa: E402

TARGETS = (os.path.join("sdk", "synox_sdk.py"), os.path.join("examples", "hello", "synox_sdk.py"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="產生單檔版 synox_sdk.py")
    parser.add_argument("--check", action="store_true", help="只比對，不寫")
    args = parser.parse_args(argv)
    text = single_file_source()
    stale = []
    for rel in TARGETS:
        path = os.path.join(ROOT, rel)
        try:
            with open(path, "r", encoding="utf-8", newline="") as f:
                current = f.read()
        except OSError:
            current = None
        if current == text:
            continue
        stale.append(rel)
        if not args.check:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    if args.check:
        print("過期：" + "、".join(stale) if stale else "一致")
        return 1 if stale else 0
    print("寫了：" + "、".join(stale) if stale else "都已經是最新的")
    return 0


if __name__ == "__main__":
    sys.exit(main())
