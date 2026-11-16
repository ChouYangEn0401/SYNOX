"""python -m synox.remindwin --data <data 資料夾> [--demo]：電腦提醒視窗程式（主程式／哨兵要跳提醒時自己開）。"""

from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m synox.remindwin", description="SYNOX 電腦提醒視窗")
    parser.add_argument("--data", required=True, help="SYNOX 的 data 資料夾")
    parser.add_argument("--demo", action="store_true", help="示範：按了就收掉（不用提醒引擎）")
    args = parser.parse_args(argv)
    from synox.remindwin import window
    return window.run(args.data, demo=args.demo)


if __name__ == "__main__":
    sys.exit(main())
