"""
python -m synox <指令>

  run       開 bot、收 Telegram（Start.bat）；Ctrl+C 或 Stop.bat 停
  console   不連 Telegram，在終端機用擁有者的身分跟 bot 講話（Console.bat）；沒有 config.json 時用示範設定
  wizard    安裝精靈（tkinter 視窗；Setup.bat 最後一步）
  doctor    健康檢查（--offline 不實際打 AI）
  stop      停掉正在跑的 bot（Stop.bat）
  install   裝一個 .synoxpack：安全管線第 1–3 關（--yes 在終端機直接核准；沒有 --yes 就開網頁設定頁給你按）
            同名已經裝了＝升級：先印「改了什麼」，版本要比較新（--allow-downgrade 才能降級／重裝同版）
  packs     packs status（每個 pack 的鎖定狀態）｜packs lock --approve <name>（工程師：重跑 1、2 關、寫 packs.lock）
            ｜packs rollback <name>（_removed 裡最近一份舊版搬回、鎖改回）
            ｜packs env rebuild <name>（重建 runtime.python／node = auto 的環境，data/envs/<name>/）
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
    elif app.extras.get("discord_errors"):
        for name, err in app.extras["discord_errors"].items():
            print(f"⚠️ Discord bot {name} 沒有開：{err}")
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


def _job_runner(data_dir: str):
    from isdtelekit.jobs.runner import JobRunner
    return JobRunner(log_root=os.path.join(data_dir, "job_logs"))


def _build_env_now(name: str, data_dir: str, packs_dir: str, jobs=None, what: str = "裝好了") -> bool:
    """終端機：建 runtime.python／node = auto 的環境並等它結束（最多 10 分鐘）。不用建回 True；建失敗回 False
    （pack 已經裝好／升級好，doctor 會標「環境沒建好」）。what：失敗訊息裡 pack 的狀態（裝好了｜升級好了）。"""
    import threading

    from synox.packs import admin
    box = []
    done = threading.Event()

    def finish(result):
        box.append(result)
        done.set()

    try:
        started = admin.build_env(name, data_dir, packs_dir, jobs or _job_runner(data_dir), finish)
    except admin.PackAdminError as e:
        print(f"❌ {e}")
        return False
    if not started:
        return True
    print("🧱 開始建環境（要網路，最多 10 分鐘）…")
    if not done.wait(660) or not box:
        print(f"❌ 建環境超過時間還沒結束。pack 已經{what}；之後跑 python -m synox packs env rebuild " + name)
        return False
    result = box[0]
    if result.ok:
        print(f"✅ {name} 的環境建好了（data/envs/{name}/）。")
        return True
    print(f"⚠️ pack {what}，但環境沒建好：{result.detail}")
    return False


def cmd_install(args, *, is_up=web_is_up, open_url=None, jobs=None) -> int:
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
    packs_dir = args.packs_dir or PACK_DIRS[0]
    trust = getattr(args, "trust", None) or None                         # PERM-2：core｜third-party（寫進 packs.lock）
    upg = _staged_upgrade(token, data_dir, packs_dir, trust)             # 同名已經裝了＝升級：「改了什麼」
    # 升級時「要不要建環境」看升級報告那一段（跟舊版比過），安裝摘要的那一段就不印，免得兩段說法不一樣
    print(admin.format_summary(summary if upg is None else {**summary, "env": {}}))
    if upg is not None:
        from synox.packs import upgrade as pack_upgrade
        print(pack_upgrade.format_upgrade(upg))
    if upg is not None and not upg["version_ok"] and not (getattr(args, "allow_downgrade", False)
                                                          and upg["can_force"]):
        print("❌ 不升級（版本要比裝著的新；真的要降級／重裝同一版，加 --allow-downgrade）")
        return 2
    if args.yes and upg is not None:
        return _upgrade_now(token, data_dir, packs_dir, config, args, jobs=jobs)
    if args.yes:
        who = getattr(config, "owner_id", None) or "console"
        try:
            name = admin.install_staged(token, data_dir, args.packs_dir or PACK_DIRS[0], approved_by=who,
                                        via="console", trust=trust,          # 第 3 關：packs.lock
                                        trust_publisher=getattr(args, "trust_publisher", None) or None,
                                        runtime=getattr(args, "runtime", None) or None)
        except admin.PackAdminError as e:
            print(f"❌ {e}")
            return 2
        from synox.packs import lock as pack_lock
        mode = pack_lock.runtime_mode(data_dir, name)
        runtime_text = {"container": "，用容器", "host": "，不用容器"}.get(mode or "", "")
        print(f"✅ 裝好了：{name}（已寫進 packs.lock，信任 {trust or 'third-party'}{runtime_text}）。"
              "SYNOX 開著的話到網頁設定頁按「重新載入全部」，或重開 SYNOX。")
        _build_env_now(name, data_dir, args.packs_dir or PACK_DIRS[0], jobs)
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
    tier = summary.get("tier") or {}
    extra = f' --trust-publisher "{tier.get("publisher")}"' if tier.get("needs_publisher") and tier.get("publisher") else ""
    print(f'   • 在這裡核准：python -m synox install "{args.file}" --yes{extra}')
    print("   • 或開 SYNOX 之後，在網頁設定頁「裝一個 .synoxpack」選這個檔")
    return 1


def _staged_upgrade(token: str, data_dir: str, packs_dir: str, trust=None):
    from synox.packs import admin, upgrade
    try:
        return upgrade.staged_upgrade(token, data_dir, packs_dir, trust=trust)
    except admin.PackAdminError:
        return None


def _upgrade_now(token: str, data_dir: str, packs_dir: str, config, args, jobs=None) -> int:
    from synox.packs import admin, upgrade
    who = getattr(config, "owner_id", None) or "console"
    try:
        done = upgrade.upgrade_staged(token, data_dir, packs_dir, approved_by=who, via="console",
                                      allow_downgrade=getattr(args, "allow_downgrade", False),
                                      trust=getattr(args, "trust", None) or None,
                                      trust_publisher=getattr(args, "trust_publisher", None) or None,
                                      runtime=getattr(args, "runtime", None) or None)
    except admin.PackAdminError as e:
        print(f"❌ {e}")
        return 2
    print(f"✅ 升級好了：{done['name']} {done['from']} → {done['to']}（已寫進 packs.lock；"
          f"舊的在 {done['backup']}，要退回：python -m synox packs rollback {done['name']}）。"
          "SYNOX 開著的話到網頁設定頁按「重新載入全部」，或重開 SYNOX。")
    if (done.get("env") or {}).get("needed"):                            # 跟全新安裝一樣：等它建完；失敗不退回升級
        _build_env_now(done["name"], data_dir, packs_dir, jobs, what="升級好了")
    return 0


def cmd_rollback(args, data_dir: str, config) -> int:
    from synox.packs import admin, upgrade
    from synox.packs.loader import PACK_DIRS
    packs_dir = args.packs_dir or PACK_DIRS[0]
    try:
        done = upgrade.rollback(args.name, packs_dir, data_dir)
    except admin.PackAdminError as e:
        print(f"❌ {e}")
        return 2
    lock_note = {"restored": "packs.lock 改回當時核准的那一筆",
                 "unlocked": "當時就沒有鎖（未鎖定）；要鎖：python -m synox packs lock --approve " + done["name"],
                 "mismatch": "⚠️ 檔案跟當時的鎖對不上，沒有鎖；檢查過再 python -m synox packs lock --approve "
                             + done["name"]}[done["lock"]]
    print(f"↩️ 退回了：{done['name']} 現在是 {done['version']}（{lock_note}）。")
    if done.get("env"):                                                  # 舊版要的環境對不上：只提示，不自動建
        print(f"   ⚠️ 舊版的環境：{done['env']}")
    if done["archived"]:
        print(f"   原本裝著的那份搬到 {done['archived']}")
    print("   資料（data/、使用者資料夾）沒有動。SYNOX 開著的話到網頁設定頁按「重新載入全部」，或重開 SYNOX。")
    return 0


def cmd_packs(args, *, jobs=None) -> int:
    from synox.packs import admin
    from synox.packs import lock as pack_lock
    from synox.packs.loader import PACK_DIRS, discover
    from synox.packs.manifest import ManifestError, read
    config = _config_quiet(args.config)
    data_dir = _data_dir(config)
    if args.packs_cmd == "rollback":
        return cmd_rollback(args, data_dir, config)
    found = {}
    default_dirs = config.pack_dirs() if config is not None and hasattr(config, "pack_dirs") else PACK_DIRS
    for folder in discover(args.dirs or default_dirs):          # 內建的＋config.json 的 packs.dirs
        try:
            found[read(folder).name] = folder
        except ManifestError:
            found.setdefault(os.path.basename(folder), folder)
    if args.packs_cmd == "env":
        name = args.name
        if name not in found:
            print(f"❌ 找不到叫 {name} 的 pack（有：{'、'.join(sorted(found)) or '沒有'}）")
            return 2
        from synox.packs import envs
        try:
            m = read(found[name])
        except ManifestError as e:
            print(f"❌ pack.json 不合：{e}")
            return 2
        if not envs.needs_env(m):
            print(f"ℹ️ {name} 不用建環境（pack.json 的 runtime.python／runtime.node 沒有寫 auto）。")
            return 0
        print(envs.builder(data_dir).plan(m).text())
        ok = _build_env_now(name, data_dir, os.path.dirname(found[name]), jobs)
        if ok:
            print("SYNOX 開著的話到網頁設定頁按「重新載入全部」，或重開 SYNOX。")
        return 0 if ok else 2
    if args.packs_cmd == "lock":
        name = args.approve
        if name not in found:
            print(f"❌ 找不到叫 {name} 的 pack（有：{'、'.join(sorted(found)) or '沒有'}）")
            return 2
        try:
            m, report, problems = admin.approve_installed(found[name], data_dir,
                                                          approved_by=getattr(config, "owner_id", None) or "cli",
                                                          trust=getattr(args, "trust", None) or None,
                                                          trust_publisher=getattr(args, "trust_publisher", None) or None,
                                                          runtime=getattr(args, "runtime", None) or None)
        except admin.PackAdminError as e:
            print(f"❌ {e}")
            return 2
        print(report.format(m))
        if problems:
            print("❌ 沒有鎖定（先修好上面的問題）")
            return 2
        print(f"🔒 {name} 已鎖定（data/packs.lock）。之後檔案被改過就不會載入。")
        return 0
    if args.packs_cmd == "runtime":
        return cmd_packs_runtime(args, found, data_dir, config)
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
        if config is not None and not changes:          # PERM-8：伺服器版第三方 python pack、沒鎖的補掃
            from synox.packs import loader as pack_loader
            try:
                m = read(folder)
            except ManifestError:
                continue
            scan_problems = pack_loader.unlocked_scan(config, m, state)
            if scan_problems:
                print(f"    ❌ 沒有 packs.lock、第 2 關掃描沒過，不會載入：{'；'.join(scan_problems[:3])}")
            elif scan_problems is not None:
                print("    🔍 沒有 packs.lock：載入時補跑的第 2 關掃描過了")
            reason = "" if scan_problems else pack_loader.trust_reason(config, m)
            if reason:
                print(f"    🔐 {reason}")
            from synox import sandbox
            note = sandbox.runtime_note(config, m)               # S2：用容器／不用、引擎找不找得到
            if note:
                print(f"    {note}")
    return 0


def cmd_packs_runtime(args, found: dict, data_dir: str, config) -> int:
    """`packs runtime <name> container|host`：只改 packs.lock 的 runtime（擁有者在這台電腦上跑才改得了）。"""
    from synox import sandbox
    from synox.packs import admin
    from synox.packs import lock as pack_lock
    from synox.packs.manifest import ManifestError, read
    name = args.name
    if name not in found:
        print(f"❌ 找不到叫 {name} 的 pack（有：{'、'.join(sorted(found)) or '沒有'}）")
        return 2
    try:
        m = read(found[name])
        mode = admin.check_runtime(m, args.mode)
    except ManifestError as e:
        print(f"❌ pack.json 不合：{e}")
        return 2
    except admin.PackAdminError as e:
        print(f"❌ {e}")
        return 2
    state, _changes = pack_lock.verify(data_dir, name, found[name])
    if state != pack_lock.LOCKED:
        print(f"❌ {name} 沒有鎖（或檔案被改過）：先 python -m synox packs lock --approve {name}")
        return 2
    pack_lock.set_runtime(data_dir, m, mode, getattr(config, "owner_id", None) or "cli")
    print(f"🧱 {name}：{'用容器' if mode == 'container' else '不用容器'}（已寫進 packs.lock）。"
          "SYNOX 開著的話到網頁設定頁按「重新載入全部」，或重開 SYNOX。")
    note = sandbox.runtime_note(config, m) if config is not None else ""
    if note:
        print(f"   {note}")
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
    """discord token：把 bot token 存進保管箱（getpass，不經聊天）；加 --clear＝從保管箱刪掉｜
    discord pair：私訊配對碼，把你的 Discord 帳號接到擁有者。"""
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
    from synox.discord import bots as bot_specs
    name = (getattr(args, "bot", None) or "").strip() or None
    try:
        if args.discord_cmd == "token":
            if name and not bot_specs.NAME_RE.match(name):
                print(f"❌ bot 名字 {name!r} 不行：只能用小寫英文、數字、- 和 _。")
                return 2
            spec = discord.find_spec(config, name or bot_specs.DEFAULT)
            if spec is None and not name and "bots" in discord.settings(config):
                print("❌ config.json 用的是多個 bot 的寫法（channels.discord.bots）：加 --bot <名字> 指定存哪一個。")
                return 2
            if spec is not None and spec.legacy and spec.vault_name is None:
                spec = None                       # 舊寫法把 token 直接寫在 config：照舊存到 discord_bot_token
            if spec is not None and spec.vault_name is None:
                print(f"❌ config.json 裡 bot {spec.name} 的 token 寫的是 {spec.token.split(':', 1)[0]}:…，不是保管箱；"
                      "要改用保管箱就把它改成 \"vault:<名字>\" 再跑一次。")
                return 2
            vault_name = spec.vault_name if spec is not None else bot_specs.default_vault_name(name or bot_specs.DEFAULT)
            label = f"bot {name} 的" if name else ""
            if getattr(args, "clear", False):
                if not vault.delete_secret(vault_name):
                    print(f"（保管箱裡本來就沒有 Discord {label}bot token（{vault_name}），沒有動任何東西）")
                    return 0
                print(f"🗑 已從保管箱刪掉 Discord {label}bot token（{vault_name}）。\n"
                      "⚠️ 這只是這台電腦不再存它，舊 token 本身還能用：要真正作廢，到 Discord Developer Portal → "
                      "你的應用程式 → Bot → 按 Reset Token。")
                if spec is not None:
                    print(f"config.json 還指著 \"vault:{vault_name}\"：在重新存一個 token（python -m synox discord token"
                          f"{' --bot ' + name if name else ''}）或從 config.json 拿掉之前，這個 bot 開不起來。")
                return 0
            token = getpass.getpass(f"貼上 Discord {label}bot token（畫面不會顯示）：").strip()
            if not token:
                print("（沒有輸入，沒有存）")
                return 1
            vault.set_secret(vault_name, token)
            if spec is not None:
                print(f"✅ 存進保管箱了（{vault_name}），config.json 已經指到這裡。")
            elif name and name != bot_specs.DEFAULT:
                print(f"✅ 存進保管箱了。config.json 的 channels.discord.bots 加上 "
                      f"\"{name}\": {{\"token\": \"vault:{vault_name}\", \"surface\": \"dm\"}}。")
            else:
                print(f"✅ 存進保管箱了。config.json 的 channels.discord.bot_token 寫 \"vault:{vault_name}\"。")
            return 0
        if args.discord_cmd == "pair":
            if getattr(args, "clear", False):
                print("❌ --clear 只給 discord token 用（刪掉存的 bot token）。")
                return 2
            return discord.pair_owner(config, vault, bot=name)
    except (KeyboardInterrupt, EOFError):
        print("\n（取消了）")
        return 1
    print("用法：python -m synox discord token [--bot 名字] [--clear]｜python -m synox discord pair [--bot 名字]")
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
    p.add_argument("--yes", action="store_true", help="看完報告直接在終端機核准（同名已裝＝升級）")
    p.add_argument("--allow-downgrade", action="store_true",
                   help="升級時新版本不比裝著的新（一樣或比較舊）也照換")
    p.add_argument("--trust", choices=["core", "third-party"], default=None,
                   help="信任：core（跟出廠的一樣）｜third-party（預設；升級沒給＝沿用裝著那一份的）")
    p.add_argument("--trust-publisher", default=None, metavar="NAME",
                   help="T2 pack（有掃不到內容的執行檔／外部相依）：明確輸入 pack.json 的 publisher 才裝")
    p.add_argument("--runtime", choices=["container", "host"], default=None,
                   help="用容器（pack 有提供 runtime.container 時的預設）｜host（不用容器；升級沒給＝沿用）")
    p.add_argument("--packs-dir", default="", help=argparse.SUPPRESS)
    p = sub.add_parser("packs", help="pack 的鎖定狀態、重新核准、退回上一版")
    psub = p.add_subparsers(dest="packs_cmd")
    psub.add_parser("status", help="每個 pack 鎖了沒、有沒有被改過")
    q = psub.add_parser("lock", help="重跑宣告檢查與靜態掃描，過了就寫 packs.lock")
    q.add_argument("--approve", required=True, metavar="NAME", help="pack 的名字")
    q.add_argument("--trust", choices=["core", "third-party"], default=None,
                   help="信任（沒給＝沿用舊鎖的，沒有舊鎖＝third-party）")
    q.add_argument("--trust-publisher", default=None, metavar="NAME",
                   help="T2 pack：明確輸入 pack.json 的 publisher（舊鎖確認過同一個、沒變多就不用）")
    q.add_argument("--runtime", choices=["container", "host"], default=None,
                   help="用容器｜不用（沒給＝沿用舊鎖的）")
    q = psub.add_parser("runtime", help="改用容器／不用容器跑（只改 packs.lock 的 runtime）")
    q.add_argument("name", help="pack 的名字")
    q.add_argument("mode", choices=["container", "host"])
    q = psub.add_parser("rollback", help="把 packs/_removed/ 裡最近一份舊版搬回來、packs.lock 改回當時的")
    q.add_argument("name", help="pack 的名字")
    p.set_defaults(dirs=None, packs_dir="")
    q = psub.add_parser("env", help="pack 的環境（runtime.python／node = auto）")
    esub = q.add_subparsers(dest="env_cmd", required=True)
    e = esub.add_parser("rebuild", help="重建 data/envs/<name>/（要網路，最多 10 分鐘）")
    e.add_argument("name", help="pack 的名字")

    p = sub.add_parser("connect", help="在這台電腦上設定一個 pack 的帳號（存進保管箱，密碼不經聊天）")
    p.add_argument("pack", help="pack 的名字，例如 apple-reminders")
    p.add_argument("--user", type=int, default=None, help="伺服器版：替哪個 Telegram id 設定（預設擁有者）")
    p.add_argument("--clear", action="store_true", help="清掉存的帳號")
    p = sub.add_parser("discord", help="Discord 通道：token（存 bot token 進保管箱）｜pair（擁有者配對）")
    p.add_argument("discord_cmd", choices=["token", "pair"])
    p.add_argument("--bot", default="", metavar="NAME",
                   help="哪個 bot（config.json 的 channels.discord.bots.<名字>）；不寫＝default（舊的單一 bot 寫法）")
    p.add_argument("--clear", action="store_true",
                   help="discord token --clear：從保管箱刪掉這個 bot 的 token（要作廢舊 token 還是要到 Developer Portal 按 Reset Token）")
    args = parser.parse_args(argv)
    handlers = {"run": cmd_run, "console": cmd_console, "wizard": cmd_wizard, "doctor": cmd_doctor, "stop": cmd_stop,
                "install": cmd_install, "packs": cmd_packs, "connect": cmd_connect, "discord": cmd_discord}
    if args.cmd not in handlers:
        parser.print_help()
        return 1
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
