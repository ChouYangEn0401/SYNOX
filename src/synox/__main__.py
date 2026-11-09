"""
python -m synox <指令>

  run       開 bot、收 Telegram（Start.bat）；Ctrl+C 或 Stop.bat 停
  console   不連 Telegram，在終端機用擁有者的身分跟 bot 講話（Console.bat）；沒有 config.json 時用示範設定
  wizard    安裝精靈（tkinter 視窗；Setup.bat 最後一步）
  doctor    健康檢查（--offline 不實際打 AI）
  stop      停掉正在跑的 bot（Stop.bat）
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys

from isdtelekit.host.config import ConfigError

from synox.config import CONFIG_PATH, SynoxConfig

DEMO_CONFIG = {"owner_id": 1, "llm": {"kind": "fake"}}


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cmd_run(args) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = SynoxConfig.load(args.config)
    except ConfigError as e:
        print(f"❌ {e}")
        return 2
    from synox.app import build
    app = build(config, config_path=os.path.abspath(args.config or CONFIG_PATH))
    print("✅ SYNOX 開始收訊息了。這個視窗可以縮小，但不要關；要停就按 Ctrl+C 或雙擊 Stop.bat。")
    if config.web.get("enabled", True):
        print(f"🌐 網頁介面：http://127.0.0.1:{config.web.get('port')}/ （在 Telegram 打 /web 拿登入連結）")
    app.run()
    return 0


def cmd_console(args) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    path = args.config or CONFIG_PATH
    if os.path.exists(path):
        try:
            config = SynoxConfig.load(path, require_token=False)
        except ConfigError as e:
            print(f"❌ {e}")
            return 2
    else:
        print("（沒有 config.json：用示範設定，AI 是不連網的假 AI）")
        config = SynoxConfig.from_dict(DEMO_CONFIG, require_token=False)
    if args.llm:
        config.llm = {**config.llm, "kind": args.llm}
    from isdtelekit.core.jsonstore import load_json
    from synox.app import build
    app = build(config)
    held = load_json(config.path("host.lock"), {})
    if isinstance(held, dict) and held.get("pid"):
        print(f"⚠️ data/host.lock 記著另一支 bot（pid {held.get('pid')}）；如果它還開著，兩邊會同時改同一份資料。")
    app.run_console(args.as_user)
    return 0


def cmd_wizard(args) -> int:
    from synox.wizard import pages
    return pages.main(config_path=args.config or CONFIG_PATH)


def cmd_doctor(args) -> int:
    from synox import doctor
    return doctor.run(offline=args.offline, config_path=args.config or "")


def cmd_stop(args) -> int:
    from isdtelekit.core.jsonstore import load_json
    try:
        config = SynoxConfig.load(args.config, require_token=False)
        lock = config.path("host.lock")
    except ConfigError:
        from synox.config import ROOT
        lock = os.path.join(ROOT, "data", "host.lock")
    held = load_json(lock, {})
    pid = held.get("pid") if isinstance(held, dict) else None
    if not pid:
        print("SYNOX 沒有在跑。")
        return 0
    from isdtelekit.host.lock import _alive
    if not _alive(int(pid), held.get("created")):
        print("SYNOX 沒有在跑（留下的鎖檔是舊的，已清掉）。")
        os.remove(lock)
        return 0
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:  # pragma: no cover
        os.kill(int(pid), 15)
    try:
        os.remove(lock)
    except OSError:
        pass
    print(f"🛑 SYNOX 停了（pid {pid}）。")
    return 0


def main(argv=None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(prog="python -m synox", description="SYNOX：你自己電腦上的 Telegram 小助手")
    parser.add_argument("--config", default="", help="config.json 的位置（預設在 SYNOX 資料夾）")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="開 bot、收 Telegram")
    p = sub.add_parser("console", help="在終端機試（不連 Telegram）")
    p.add_argument("--as", dest="as_user", type=int, default=None, help="用這個使用者 id 講話（預設擁有者）")
    p.add_argument("--llm", choices=["fake", "none"], default=None, help="這次改用假 AI 或不用 AI")
    sub.add_parser("wizard", help="安裝精靈")
    p = sub.add_parser("doctor", help="健康檢查")
    p.add_argument("--offline", action="store_true", help="不實際打 AI")
    sub.add_parser("stop", help="停掉正在跑的 bot")
    args = parser.parse_args(argv)
    handlers = {"run": cmd_run, "console": cmd_console, "wizard": cmd_wizard, "doctor": cmd_doctor, "stop": cmd_stop}
    if args.cmd not in handlers:
        parser.print_help()
        return 1
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
