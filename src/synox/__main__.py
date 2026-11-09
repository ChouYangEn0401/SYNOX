"""
python -m synox <指令>

  run       開 bot、收 Telegram（Start.bat）；Ctrl+C 或 Stop.bat 停
  console   不連 Telegram，在終端機用擁有者的身分跟 bot 講話（Console.bat）；沒有 config.json 時用示範設定
  wizard    安裝精靈（tkinter 視窗；Setup.bat 最後一步）
  doctor    健康檢查（--offline 不實際打 AI）
  stop      停掉正在跑的 bot（Stop.bat）
  install   裝一個 .synoxpack：安全管線第 1–3 關（--yes 在終端機直接核准；沒有 --yes 就開網頁設定頁給你按）
  packs     packs status（每個 pack 的鎖定狀態）｜packs lock --approve <name>（工程師：重跑 1、2 關、寫 packs.lock）
  connect   connect <pack> [--user ID] [--clear]：把 pack 要的帳號存進保管箱（密碼用 getpass，不經聊天）
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
        config = SynoxConfig.load(args.config or None, require_token=False)
        channels = run_channels(config)
    except ConfigError as e:
        print(f"❌ {e}")
        return 2
    from synox.app import build
    app = build(config, config_path=os.path.abspath(args.config or CONFIG_PATH))
    if config.discord_enabled and "discord" not in app.extras:
        print(f"⚠️ Discord 沒有開成：{app.extras.get('discord_error', '原因看 log')}")
        if not channels:
            return 2
    print("✅ SYNOX 開始收訊息了。這個視窗可以縮小，但不要關；要停就按 Ctrl+C 或雙擊 Stop.bat。")
    if config.web.get("enabled", True):
        print(f"🌐 網頁介面：http://127.0.0.1:{config.web.get('port')}/ （在聊天裡打 /web 拿登入連結）")
    app.run(channels)
    return 0


def run_channels(config) -> tuple:
    """要開哪些「SDK 自己管」的通道：有 Telegram token 就 telegram；Discord 由 synox.discord 在 on_start 自己登記。
    兩個都沒有 → ConfigError（給人看的訊息）。"""
    if config.has_token:
        return ("telegram",)
    if config.discord_enabled:
        return ()
    raise ConfigError("config.json 的 bot_token 還不是真的 Telegram token，也沒有開 Discord（channels.discord）。"
                      "至少要有一個；只想在終端機試的話用 Console.bat。")


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


def _config_quiet(path: str):
    """install／packs 用：有 config.json 就讀（不要 token），沒有就 None（用預設的 data/）。"""
    path = path or CONFIG_PATH
    try:
        return SynoxConfig.load(path, require_token=False) if os.path.exists(path) else None
    except ConfigError:
        return None


def _data_dir(config) -> str:
    from synox.config import ROOT
    return config.data_dir if config is not None else os.path.join(ROOT, "data")


def web_is_up(port: int) -> bool:
    """本機的 SYNOX 網頁介面有沒有在聽（只「連」127.0.0.1，不開埠）。"""
    import socket
    if not port:
        return False
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def _open_browser(url: str) -> None:
    import webbrowser
    webbrowser.open(url)


def cmd_install(args, *, is_up=web_is_up, open_url=None) -> int:
    from synox.packs import admin
    from synox.packs.loader import PACK_DIRS
    config = _config_quiet(args.config)
    data_dir = _data_dir(config)
    try:
        token, summary = admin.stage_file(args.file, data_dir)            # 第 1、2 關
    except admin.GateRefused as e:
        if e.summary:
            print(admin.format_summary(e.summary))
        print(f"❌ {e}")
        return 2
    except admin.PackAdminError as e:
        print(f"❌ {e}")
        return 2
    print(admin.format_summary(summary))
    if args.yes:
        who = getattr(config, "owner_id", None) or "console"
        try:
            name = admin.install_staged(token, data_dir, args.packs_dir or PACK_DIRS[0], approved_by=who,
                                        via="console")                       # 第 3 關：packs.lock
        except admin.PackAdminError as e:
            print(f"❌ {e}")
            return 2
        print(f"✅ 裝好了：{name}（已寫進 packs.lock）。SYNOX 開著的話到網頁設定頁按「重新載入全部」，或重開 SYNOX。")
        return 0
    web = (getattr(config, "web", None) or {}) if config is not None else {}
    port = int(web.get("port") or 0)
    if config is not None and web.get("enabled", True) and is_up(port):
        url = f"http://127.0.0.1:{port}/?pack={token}#settings"
        (open_url or _open_browser)(url)
        print("🌐 已經打開網頁設定頁：看完報告，按「確認安裝」才會裝。")
        print(f"   {url}")
        print("   （網頁要先登入：在 Telegram 打 /web 拿登入連結。）")
        return 0
    print("ℹ️ 還沒裝。SYNOX 沒開（或網頁介面關著）：")
    print(f'   • 在這裡核准：python -m synox install "{args.file}" --yes')
    print("   • 或開 SYNOX 之後，在網頁設定頁「裝一個 .synoxpack」選這個檔")
    return 1


def cmd_packs(args) -> int:
    from synox.packs import admin
    from synox.packs import lock as pack_lock
    from synox.packs.loader import PACK_DIRS, discover
    from synox.packs.manifest import ManifestError, read
    config = _config_quiet(args.config)
    data_dir = _data_dir(config)
    found = {}
    for folder in discover(args.dirs or PACK_DIRS):
        try:
            found[read(folder).name] = folder
        except ManifestError:
            found.setdefault(os.path.basename(folder), folder)
    if args.packs_cmd == "lock":
        name = args.approve
        if name not in found:
            print(f"❌ 找不到叫 {name} 的 pack（有：{'、'.join(sorted(found)) or '沒有'}）")
            return 2
        try:
            m, report, problems = admin.approve_installed(found[name], data_dir,
                                                          approved_by=getattr(config, "owner_id", None) or "cli")
        except admin.PackAdminError as e:
            print(f"❌ {e}")
            return 2
        print(report.format(m))
        if problems:
            print("❌ 沒有鎖定（先修好上面的問題）")
            return 2
        print(f"🔒 {name} 已鎖定（data/packs.lock）。之後檔案被改過就不會載入。")
        return 0
    marks = {pack_lock.LOCKED: "🔒 鎖定", pack_lock.UNLOCKED: "· 未鎖定", pack_lock.TAMPERED: "⚠️ 被改過"}
    from synox.packs.manifest import synox_problem
    for name, folder in sorted(found.items()):
        state, changes = pack_lock.verify(data_dir, name, folder)
        print(f"{marks[state]}  {name}  {folder}")
        if changes:
            print("    " + "、".join(changes))
        try:
            too_old = synox_problem(read(folder))
        except ManifestError:
            too_old = None
        if too_old:
            print(f"    ⛔ 不會載入：{too_old}")
    return 0


def cmd_connect(args) -> int:
    """把一個 pack 要的帳號（pack.json 的 auth.fields）存進保管箱；密碼用 getpass，不經聊天、不進 log。"""
    from synox import connect
    from synox.vault import KeyringError, VaultError, open_vault
    try:
        config = SynoxConfig.load(args.config or None, require_token=False)
    except ConfigError as e:
        print(f"❌ {e}")
        return 2
    try:
        vault = open_vault(config)
        return connect.run(args.pack, config, vault, user=args.user, clear=args.clear)
    except (KeyringError, VaultError) as e:
        print(f"❌ 保管箱打不開：{e}")
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\n（取消了，沒有存）")
        return 1


def cmd_discord(args) -> int:
    """discord token：把 bot token 存進保管箱（getpass，不經聊天）｜discord pair：私訊配對碼，把你的 Discord 帳號接到擁有者。"""
    import getpass

    from synox import discord
    from synox.vault import KeyringError, VaultError, open_vault
    try:
        config = SynoxConfig.load(args.config or None, require_token=False)
        vault = open_vault(config)
    except ConfigError as e:
        print(f"❌ {e}")
        return 2
    except (KeyringError, VaultError) as e:
        print(f"❌ 保管箱打不開：{e}")
        return 2
    try:
        if args.discord_cmd == "token":
            token = getpass.getpass("貼上 Discord bot token（畫面不會顯示）：").strip()
            if not token:
                print("（沒有輸入，沒有存）")
                return 1
            vault.set_secret(discord.VAULT_NAME, token)
            print(f"✅ 存進保管箱了。config.json 的 channels.discord.bot_token 寫 \"vault:{discord.VAULT_NAME}\"。")
            return 0
        if args.discord_cmd == "pair":
            return discord.pair_owner(config, vault)
    except (KeyboardInterrupt, EOFError):
        print("\n（取消了）")
        return 1
    print("用法：python -m synox discord token｜python -m synox discord pair")
    return 1


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
    p = sub.add_parser("install", help="裝一個 .synoxpack（安全檢查 → 核准 → 裝）")
    p.add_argument("file", help=".synoxpack 檔")
    p.add_argument("--yes", action="store_true", help="看完報告直接在終端機核准")
    p.add_argument("--packs-dir", default="", help=argparse.SUPPRESS)
    p = sub.add_parser("packs", help="pack 的鎖定狀態、重新核准")
    psub = p.add_subparsers(dest="packs_cmd")
    psub.add_parser("status", help="每個 pack 鎖了沒、有沒有被改過")
    q = psub.add_parser("lock", help="重跑宣告檢查與靜態掃描，過了就寫 packs.lock")
    q.add_argument("--approve", required=True, metavar="NAME", help="pack 的名字")
    p.set_defaults(dirs=None)
    p = sub.add_parser("connect", help="在這台電腦上設定一個 pack 的帳號（存進保管箱，密碼不經聊天）")
    p.add_argument("pack", help="pack 的名字，例如 apple-reminders")
    p.add_argument("--user", type=int, default=None, help="伺服器版：替哪個 Telegram id 設定（預設擁有者）")
    p.add_argument("--clear", action="store_true", help="清掉存的帳號")
    p = sub.add_parser("discord", help="Discord 通道：token（存 bot token 進保管箱）｜pair（擁有者配對）")
    p.add_argument("discord_cmd", choices=["token", "pair"])
    args = parser.parse_args(argv)
    handlers = {"run": cmd_run, "console": cmd_console, "wizard": cmd_wizard, "doctor": cmd_doctor, "stop": cmd_stop,
                "install": cmd_install, "packs": cmd_packs, "connect": cmd_connect, "discord": cmd_discord}
    if args.cmd not in handlers:
        parser.print_help()
        return 1
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
