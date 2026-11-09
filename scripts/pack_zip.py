"""
pack 資料夾 → dist/<name>-<version>.synoxpack（zip，pack.json 在最上層，算好 integrity.sha256）。

    .venv\\Scripts\\python.exe scripts\\pack_zip.py packs\\money            → dist\\money-0.1.0.synoxpack
    .venv\\Scripts\\python.exe scripts\\pack_zip.py <資料夾> --out <資料夾>

先跑安裝時的宣告檢查與靜態掃描（第 1、2 關），沒過不打包。等於 `synox-sdk zip`。
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")]

from synox.sdk import zip_pack  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="pack 資料夾 → .synoxpack")
    parser.add_argument("folder")
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = parser.parse_args(argv)
    try:
        path = zip_pack(args.folder, args.out)
    except ValueError as e:
        print(f"❌ {e}")
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
