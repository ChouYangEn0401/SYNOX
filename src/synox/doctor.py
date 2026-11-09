"""
python -m synox doctor [--offline]：印出環境、設定（不印密鑰）、AI 來源與測試結果、packs、保管箱狀態。
不改任何檔案（保管箱的金鑰檔不存在時也不會產生新的）。
"""

from __future__ import annotations

import glob
import os
import platform
import sys
from typing import Callable, List

from synox import __version__
from synox.config import CONFIG_PATH, MODE_LABELS, ROOT, SynoxConfig, redacted


def _sdk_line() -> str:
    try:
        import isdtelekit
        version = isdtelekit.__version__
    except Exception as e:                      # pragma: no cover
        return f"❌ 載入不了 isdtelekit：{e}"
    vfile = os.path.join(ROOT, "vendor", "VERSION")
    extra = ""
    if os.path.exists(vfile):
        with open(vfile, encoding="ascii") as f:
            extra = "（" + "，".join(line.strip() for line in f if line.strip()) + "）"
    return f"isdtelekit {version}{extra}"


def _secret_lookup(config) -> Callable:
    """pack 的 auth.fields（Web UI「連接」填的）還缺哪些 → 一句話（沒缺／不用回 ""）。
    個人版看共用的保管箱；伺服器版看擁有者自己那一份（別人的各自在工具頁看）。保管箱的金鑰不存在就不開（不產生新的）。"""
    from synox.packs import secrets as pack_secrets
    store = None
    if config is not None and os.path.exists(os.path.join(config.data_dir, ".synox.key")):
        try:
            from synox.vault import Vault
            from synox.vault.keyring import read_key
            store = pack_secrets.PackSecrets(Vault(read_key(os.path.join(config.data_dir, ".synox.key")),
                                                   config.data_dir), server=bool(config.server))
        except Exception:
            store = None
    owner = getattr(config, "owner_id", None) if config is not None else None

    def lookup(m) -> str:
        fields = pack_secrets.managed_fields(m)
        if not fields:
            return ""
        if store is None:
            return "⚠️ 要先連接（保管箱還沒建立或打不開）：" + "、".join(f["label"] for f in fields if f["required"])
        if store.server and not owner:
            return "• 伺服器版的連接每人各自在網頁工具頁設定"
        missing = store.missing(m.name, fields, owner)
        who = "（擁有者的）" if store.server else ""
        return f"⚠️ 還沒連接{who}：缺 {'、'.join(missing)}（網頁工具頁按「連接」）" if missing else f"🔌 已連接{who}"
    return lookup


def _discord_lines(config) -> tuple:
    """每個 Discord bot 一行：名字、場合、pack 範圍、token 在不在；下面接這個 bot 會出現的 pack 與
    「設定了但不會出現」的原因（只讀 pack.json）。回 (行, 有幾個要處理的)。不連 Discord、不產生金鑰。"""
    from synox import discord
    vault = None
    key = os.path.join(config.data_dir, ".synox.key")
    if os.path.exists(key):
        try:
            from synox.vault import Vault
            from synox.vault.keyring import read_key
            vault = Vault(read_key(key), config.data_dir)
        except Exception:
            vault = None
    lines, bad = [], 0
    try:
        from synox.discord import scope
        infos = scope.from_manifests(config)
    except Exception:                               # 範圍報告出錯不該讓 doctor 整段掛掉
        scope, infos = None, {}
    for spec in discord.specs(config):
        line, wrong = _discord_bot_line(spec, vault)
        lines.append(line)
        bad += wrong
        if scope is not None:                       # PERM-4：這個 bot 會出現哪些 pack、設定了卻不會出現的原因
            lines.extend(scope.lines(spec, scope.report(spec, infos), indent="      "))
    return lines, bad


def _discord_bot_line(spec, vault) -> tuple:
    """一個 bot 的那一行（場合、pack 範圍、token 在不在）→ (行, 0 或 1)。"""
    from synox import discord
    from synox.discord.bots import CHANNEL
    packs = "全部 pack" if spec.packs == "all" else "pack：" + "、".join(spec.packs)
    where = "私訊型" if spec.surface != CHANNEL else "頻道型"
    cap = f"，上限 {spec.max_effect}" if spec.max_effect else ""
    head = f"    bot {spec.name}（{where}，{packs}{cap}，AI {'開' if spec.ai.get('enabled') else '關'}，hub {spec.hub_name}）"
    hint = "（python -m synox discord token" + (f" --bot {spec.name}" if not spec.legacy else "") + "）"
    if spec.surface == CHANNEL:
        return f"{head}：⚠️ {discord.CHANNEL_NOT_YET}", 0
    if spec.token.startswith("vault:"):
        if vault is None:
            return f"{head}：❌ 保管箱還沒建立，token 不在{hint}", 1
        try:
            has = bool((vault.secret(spec.vault_name) or "").strip())
        except Exception:
            has = False
        if not has:
            return f"{head}：❌ 保管箱裡沒有 {spec.vault_name}{hint}", 1
        return f"{head}：✅ token 在保管箱", 0
    if spec.token.startswith("env:"):
        ok = bool(os.environ.get(spec.token[4:], "").strip())
        return f"{head}：" + ("✅ token 從環境變數讀" if ok else f"❌ 環境變數 {spec.token[4:]} 是空的"), 0 if ok else 1
    return f"{head}：⚠️ token 直接寫在 config.json（建議改用保管箱：python -m synox discord token）", 0


def run(offline: bool = False,config_path: str = "", out: Callable[[str], None] = print) -> int:
    problems = 0
    out(f"🩺 SYNOX {__version__} 健康檢查")
    out(f"• Python：{platform.python_version()}（{sys.executable}）")
    out(f"• SDK：{_sdk_line()}")
    out(f"• 資料夾：{ROOT}")

    path = config_path or CONFIG_PATH
    config = None
    if not os.path.exists(path):
        out(f"• 設定：⚠️ 還沒有 {os.path.basename(path)}（雙擊 Setup.bat 跑精靈）；以下用預設值檢查")
        out(f"  模式：personal（{MODE_LABELS['personal']}，預設）")
    else:
        try:
            config = SynoxConfig.load(path, require_token=False)
            r = redacted(config.raw)
            out(f"• 設定：✅ {os.path.basename(path)}　bot_token {'格式正確' if config.has_token else '❌ 不是有效的 token'}"
                f"　owner_id {'有填' if config.owner_id else '❌ 沒填'}")
            out(f"  模式：{config.mode}（{MODE_LABELS[config.mode]}）"
                + ("　陌生人是訪客、vault 的資料每人一份 data/users/<id>/" if config.server else ""))
            out(f"  llm：{r.get('llm', {'kind': 'none'})}")
            out(f"  packs：{config.packs}　vault：{config.vault}")
            web = config.web
            out("  網頁介面：" + (f"開，http://127.0.0.1:{web.get('port')}/（/web 拿登入連結）"
                                + (f"　對外網址 {web.get('public_url')}" if web.get("public_url") else "")
                                if web.get("enabled", True) else "關（web.enabled=false）"))
            if config.discord_enabled:
                bot_lines, bad = _discord_lines(config)
                from synox import discord as _dc
                out(f"  Discord：開（{len(_dc.specs(config))} 個 bot；token 放保管箱，見 docs/discord.md；"
                    "啟動後 /bot_status 看各 bot 實際的 pack）")
                for line in bot_lines:
                    out(line)
                problems += bad
            problems += 0 if (config.has_token or config.discord_enabled) else 1
        except Exception as e:
            out(f"• 設定：❌ {e}")
            problems += 1

    # AI 來源
    llm = (config.llm if config else {"kind": "none"})
    kind = llm.get("kind", "none")
    if kind == "none":
        out("• AI：沒有設定（只用指令和按鈕）")
    else:
        vault = None
        if config is not None and os.path.exists(os.path.join(config.data_dir, ".synox.key")):
            try:
                from synox.vault import open_vault
                vault = open_vault(config)
            except Exception:
                vault = None
        try:
            from synox.llm import make_adapter
            adapter = make_adapter(config, vault)
            if adapter is None:
                out(f"• AI：❌ 不認得的 kind {kind}")
                problems += 1
            elif offline:
                out(f"• AI：{adapter.name}（--offline：沒有實際測試）")
            else:
                err = adapter.probe()
                out(f"• AI：{adapter.name}　" + ("✅ 測試通過" if err is None else f"❌ {err}"))
                problems += 0 if err is None else 1
        except Exception as e:
            out(f"• AI：❌ {e}")
            problems += 1

    # 沙盒（synox/sandbox.py）：目前的後端、算不算真隔離
    from synox import sandbox
    box = sandbox.sandbox_for(config)
    sandbox_text, bad = sandbox.doctor_line(config)
    for line in sandbox_text.splitlines():
        out(line)
    problems += bad

    # packs
    from synox.packs import envs
    from synox.packs import lock as pack_lock
    from synox.packs import loader
    from synox.packs.loader import PACK_DIRS, discover
    from synox.packs.manifest import ManifestError, read, synox_problem
    lines: List[str] = []
    lock_dir = config.data_dir if config else os.path.join(ROOT, "data")
    locked = 0
    dirs = config.pack_dirs() if config else PACK_DIRS
    secret_lookup = _secret_lookup(config)
    for extra in dirs[len(PACK_DIRS):]:
        if not os.path.isdir(extra):
            lines.append(f"  ⚠️ packs.dirs 列的資料夾不存在：{extra}")
            problems += 1
    for folder in discover(dirs):
        try:
            rel = os.path.relpath(folder, ROOT)
        except ValueError:                       # 不同磁碟機
            rel = folder
        try:
            m = read(folder)
            enabled = config.pack_enabled(m.name) if config else True
            lock_state, changes = pack_lock.verify(lock_dir, m.name, folder)    # 第 3 關（packs.lock）
            if lock_state == pack_lock.TAMPERED:
                lines.append(f"  ❌ {m.name} {m.version}：檔案跟核准時不一樣，不會載入（{'、'.join(changes[:6])}）  {rel}")
                problems += 1
                continue
            locked += lock_state == pack_lock.LOCKED
            too_old = synox_problem(m)               # requires.synox
            if too_old and enabled:
                lines.append(f"  ⛔ {m.name} {m.version}：不會載入。{too_old}  {rel}")
                problems += 1
                continue
            no_env = envs.env_problem(m, lock_dir) if enabled else None    # runtime.python／node = auto、沒有 node
            if no_env:
                lines.append(f"  ⚠️ {m.name} {m.version}：{no_env}  {rel}")
                problems += 1
                continue
            state = "connector（只登記）" if m.registered_only else ("✅" if enabled else "⏸ 停用")
            lock_mark = "🔒" if lock_state == pack_lock.LOCKED else "未鎖定"
            lines.append(f"  {state} {m.name} {m.version}（{m.kind}，/{m.group}，{lock_mark}）  {rel}")
            if enabled:
                note = secret_lookup(m)
                if note:
                    lines.append(f"     {note}")
                if m.mcp_stdio:                              # P4a：pack 外的程式、不支援的欄位、伺服器沒列的工具
                    from synox.packs import mcp as pack_mcp
                    for mcp_note in pack_mcp.doctor_notes(m, lock_dir):
                        lines.append(f"     {mcp_note}")
                boxed_out = sandbox.restricted_reason(config, m, box) if config is not None else ""
                if boxed_out:
                    lines.append(f"     🔐 {boxed_out}")
                t2_note = sandbox.t2_personal_note(config, m) if config is not None else ""
                if t2_note:                                  # SDK P7：個人版的 T2 照用，只提醒
                    lines.append(f"     ⚠️ {t2_note}")
                if config is not None:                       # PERM-8：伺服器版第三方 python pack、沒鎖的補掃
                    scan_problems = loader.unlocked_scan(config, m, lock_state)
                    if scan_problems:
                        lines.append(f"     ❌ 沒有 packs.lock、第 2 關掃描沒過，不會載入：{'；'.join(scan_problems[:3])}")
                        problems += 1
                    elif scan_problems is not None:
                        lines.append("     🔍 沒有 packs.lock：載入時補跑的第 2 關掃描過了")
                    trusted_out = "" if scan_problems else loader.trust_reason(config, m)
                    if trusted_out:
                        lines.append(f"     🔐 {trusted_out}")
        except ManifestError as e:
            lines.append(f"  ❌ {rel}：{e}")
            problems += 1
    out(f"• packs：{len(lines)} 個（packs.lock 鎖定 {locked} 個；python -m synox packs status 看細節）")
    for line in lines:
        out(line)

    # 保管箱
    data_dir = config.data_dir if config else os.path.join(ROOT, "data")
    key = os.path.join(data_dir, ".synox.key")
    encs = sorted(glob.glob(os.path.join(data_dir, "*.json.enc")))
    user_encs = sorted(glob.glob(os.path.join(data_dir, "users", "*", "*.json.enc")))
    if not os.path.exists(key):
        out(f"• 保管箱：還沒建立（第一次啟動時產生金鑰）；加密檔 {len(encs) + len(user_encs)} 個"
            + ("　❌ 有加密檔卻沒有金鑰！" if encs or user_encs else ""))
        problems += 1 if encs or user_encs else 0
    else:
        from synox.vault.keyring import key_mode
        try:
            from synox.vault import Vault
            from synox.vault.keyring import read_key
            vault = Vault(read_key(key), data_dir)
            bad = []
            for p in encs:
                try:
                    vault.load_json(os.path.basename(p)[:-len(".json.enc")])
                except Exception:
                    bad.append(os.path.basename(p))
            for p in user_encs:                        # 伺服器版：每人一個保管箱（HKDF 衍生的金鑰）
                uid = os.path.basename(os.path.dirname(p))
                try:
                    vault.for_user(int(uid)).load_json(os.path.basename(p)[:-len(".json.enc")])
                except Exception:
                    bad.append(f"users/{uid}/{os.path.basename(p)}")
            people = len({os.path.dirname(p) for p in user_encs})
            status = "✅ 全部解得開" if not bad else f"❌ 解不開：{'、'.join(bad)}"
            extra = f"（另有 {people} 個人的個人資料 {len(user_encs)} 個）" if user_encs else ""
            out(f"• 保管箱：金鑰 {key_mode(key)}，加密檔 {len(encs)} 個{extra}，{status}")
            problems += 1 if bad else 0
        except Exception as e:
            out(f"• 保管箱：❌ {e}")
            problems += 1
    out("結論：" + ("✅ 沒有發現問題" if not problems else f"⚠️ {problems} 個地方要看一下"))
    return 0 if not problems else 1
