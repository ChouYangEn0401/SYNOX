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
from synox.brand import latest_hint
from synox.config import CONFIG_PATH, MODE_LABELS, ROOT, ROOT_SOURCE, SynoxConfig, redacted


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
    from synox.identity import Identities, IdentityFileError
    try:                                            # 只讀：舊檔也不遷移（doctor 不改檔）
        problem = discord.owner_problem(config, Identities(config.path("identities.json"), readonly=True))
    except IdentityFileError as e:
        problem = str(e)
    if problem:
        lines.append(f"    ❌ 身分：{problem}")
        bad += 1
    try:
        from synox.discord import scope
        infos = scope.from_manifests(config)
    except Exception:                               # 範圍報告出錯不該讓 doctor 整段掛掉
        scope, infos = None, {}
    for spec in discord.specs(config):
        line, wrong = _discord_bot_line(spec, vault)
        lines.append(line)
        bad += wrong
        from synox.discord.bots import channel_ai_problem
        if channel_ai_problem(spec):                # PERM-6：頻道 AI 開了卻沒有 pool（下面 scope.lines 列原因）
            bad += 1
            if scope is None:
                lines.append(f"      ❌ 頻道 AI 沒有開：{channel_ai_problem(spec)}")
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
    from synox.discord.scope import ai_word
    head = f"    bot {spec.name}（{where}，{packs}{cap}，{ai_word(spec)}，hub {spec.hub_name}）"
    hint = "（python -m synox discord token" + (f" --bot {spec.name}" if not spec.legacy else "") + "）"
    if spec.surface == CHANNEL and not spec.channel_count():
        return f"{head}：❌ {discord.NO_GUILDS}", 1
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


def _heartbeat_line(config) -> str:
    """心跳（docs/adr/0001）：開關、間隔、安靜時段＋data/runtime/state.json 記的上一次（沒有個人資料的那份；不改檔）。"""
    from synox.runtime.loop import STATE_FILE, iso
    hb = (getattr(config, "runtime", None) or {}).get("heartbeat") or {}
    if not hb.get("enabled", True):
        head = "  心跳：關（runtime.heartbeat.enabled=false）"
    else:
        quiet = hb.get("quiet_hours") or "沒有"
        head = f"  心跳：開，每 {hb.get('interval_min', 45)} 分鐘（安靜時段 {quiet}；網頁主控面板可以改）"
    try:
        import json
        with open(os.path.join(config.data_dir, STATE_FILE), "r", encoding="utf-8") as f:
            saved = json.load(f)
        task = (saved.get("tasks") or {}).get("system.heartbeat") or {}
        last = task.get("last_run_at")
        result = (saved.get("heartbeat") or {}).get("last_result") or ""
    except (OSError, ValueError, AttributeError):
        last, result = None, ""
    if isinstance(last, (int, float)):
        return head + f"\n    上一次：{iso(last)}　{result}".rstrip()
    return head + "\n    上一次：還沒巡過（SYNOX 跑起來之後才會巡）"


def _local_lines(adapter, offline: bool, out) -> int:
    """本地模型（docs/adr/0007）：設定、網址提醒；不是 --offline 時唯讀探測（/api/tags、/api/show，不載入模型）
    ＋context 建議。回問題數。"""
    from synox.llm.local import report_lines, url_warning
    out(f"• AI：{adapter.name}　{adapter.root}　context_size {adapter.context_size or '0（伺服器預設）'}　"
        f"無進展逾時 {int(adapter.timeout)} 秒（還在回就不砍）、總上限 {int(adapter.max_total)} 秒"
        + ("" if adapter.supports_tools else "　文字協定（tools=false）"))
    if url_warning(adapter.base_url):
        out("  " + url_warning(adapter.base_url))
    if offline:
        out("  （--offline：沒有探測伺服器）")
        return 0
    report = adapter.inspect()
    for line in report_lines(report):
        out("  " + line)
    if report.get("reachable") and report.get("model_found"):
        from synox.llm import local_advice
        advice = local_advice.from_report(report, max_tokens=adapter.max_tokens, server=adapter.server)
        out(f"  context 建議（估算；沒量到這台實際的提示，用 {advice['prompt_tokens']} tokens 估）："
            + "／".join(local_advice.option_label(r) for r in advice["options"]))
        if adapter.server == "ollama" and adapter.context_size and advice["options"] and \
                adapter.context_size < advice["min_context"]:
            out(f"  ❌ context_size {adapter.context_size} 小於 {advice['min_context']}：SYNOX 的提示會被截斷")
            return 1 + len(report["problems"])
    return len(report["problems"])


def _keep_awake_line(config) -> str:
    """保持清醒（docs/adr/0006）：開關、熄螢幕設定、這個系統有沒有作用。"""
    from synox.runtime.keepawake import MS_NOTE, NOTICE, TAGLINE, WinPower
    ka = (getattr(config, "runtime", None) or {}).get("keep_awake") or {}
    if not ka.get("enabled", False):
        return ("  保持清醒：關（預設）。" + TAGLINE + "要打開：網頁設定頁「保持清醒」或 runtime.keep_awake.enabled=true。"
                f"\n    ℹ️ {NOTICE}")
    if sys.platform != "win32":
        return "  保持清醒：開，但只有 Windows 有作用，這個系統什麼都不會做"
    minutes = ka.get("screen_off_after_min", 0)
    screen = f"閒置 {minutes} 分鐘後請 Windows 關螢幕" if minutes else "螢幕照 Windows 電源計畫（動滑鼠或鍵盤就亮）"
    line = f"  保持清醒：開，電腦不會自己睡著；{screen}\n    ℹ️ {NOTICE}"
    if WinPower().modern_standby():
        line += f"\n    ⚠️ {MS_NOTE}"
    return line


def _activator_line(config) -> str:
    """連動（docs/adr/0004）：開關、config.json 的規則數＋state.json 記的暫停中的規則、全部暫停、待處理（不改檔）。"""
    from synox.runtime.loop import STATE_FILE
    act = (getattr(config, "runtime", None) or {}).get("activator") or {}
    if not act.get("enabled", True):
        return "  連動：關（runtime.activator.enabled=false）"
    head = f"  連動：開（config.json 裡 {len(act.get('rules') or [])} 條規則；工具自己的規則 SYNOX 跑起來才登記）"
    try:
        import json
        with open(os.path.join(config.data_dir, STATE_FILE), "r", encoding="utf-8") as f:
            saved = json.load(f).get("activator") or {}
        tripped = sorted(k for k, v in (saved.get("rules") or {}).items() if isinstance(v, dict) and v.get("tripped"))
        paused = (saved.get("paused") or {}).get("reason") if isinstance(saved.get("paused"), dict) else None
        pending = len(saved.get("pending") or [])
    except (OSError, ValueError, AttributeError):
        return head
    lines = [head]
    if paused:
        lines.append(f"    ⏸ 全部暫停中：{paused}（網頁主控面板按「恢復」）")
    if tripped:
        lines.append(f"    ⏸ 暫停中的規則：{'、'.join(tripped[:10])}（網頁主控面板看原因、按「重設」）")
    if pending:
        lines.append(f"    等心跳處理：{pending} 件")
    return "\n".join(lines)


HEALTH_MARKS = {"broken": "⏸", "needs_action": "🛠", "quarantined": "⛔"}


def _stepup_line(config) -> str:
    """手機驗證器（ADR 0025）：擁有者設定了沒、危險的動作有沒有開保護。保管箱還沒建（沒有金鑰檔）就不去開它。"""
    from synox.guard.cli import doctor_line
    from synox.vault.keyring import key_path
    if not os.path.exists(key_path(config.data_dir)):        # 還沒建保管箱＝一定沒設定（doctor 不替人建金鑰）
        return doctor_line(None)
    try:
        from synox.guard.store import VaultStore
        from synox.vault import open_vault
        store = VaultStore(open_vault(config), getattr(config, "mode", "personal") == "server")
        return doctor_line(store.load(int(config.owner_id or 0)))
    except Exception:
        return "  手機驗證器：（保管箱打不開，看不到；先處理保管箱的問題）"


def health_lines(config, default_data: str) -> tuple:
    """工具健康（docs/tool-health.md）：每個不正常的工具一行（狀態、類別碼、原因、下次檢查時間）。
    只讀 data/health/tools.json.enc（保管箱金鑰不在＝不開、不產生）。回 (行, 要看一下的個數)。"""
    from synox.health import store as health_store
    from synox.health.failure import CODES
    from synox.health.state import HEALTHY, STATE_LABELS
    from synox.runtime.loop import iso
    settings = getattr(config, "health", None) or {}
    if settings and not settings.get("enabled", True):
        return ["• 工具健康：關（health.enabled=false；每個工具都當成正常）"], 0
    data_dir = config.data_dir if config is not None else default_data
    entries, problem = health_store.read_only(data_dir)
    if entries is None:
        return [f"• 工具健康：⚠️ {problem}"], 1
    bad = sorted((e for e in entries.values() if e.state != HEALTHY), key=lambda e: (e.tool, e.user or 0))
    if not bad:
        return ["• 工具健康：✅ 沒有被暫停或隔離的工具"], 0
    lines = [f"• 工具健康：{len(bad)} 個不正常（網頁工具頁看得到原因；擁有者可以按「重新檢查」「解除隔離」）"]
    for e in bad:
        who = f"（只對 {e.user}）" if e.user is not None else ""
        label = CODES[e.code].label if e.code in CODES else e.code
        when = f"　下次檢查 {iso(e.next_check)}" if e.next_check else ("　試用中" if e.trial else "")
        lines.append(f"  {HEALTH_MARKS.get(e.state, '⚠️')} {e.tool}{who} {STATE_LABELS.get(e.state, e.state)}："
                     f"{e.code}（{label}）　{e.reason}{when}")
    return lines, len(bad)


# SYNOX 資料夾是怎麼決定的（config.default_root）：原始碼版面不多說，其他兩種要讓人知道
ROOT_NOTES = {"SYNOX_HOME": "（來自環境變數 SYNOX_HOME；不是你要的就把它刪掉）",
              "cwd": "（⚠️ 不是原始碼的版面，用的是目前所在的資料夾；要固定就設環境變數 SYNOX_HOME）"}


def run(offline: bool = False,config_path: str = "", out: Callable[[str], None] = print) -> int:
    problems = 0
    out(f"🩺 SYNOX {__version__} 健康檢查")
    out(f"• 有沒有新版：{latest_hint()}")
    out(f"• Python：{platform.python_version()}（{sys.executable}）")
    out(f"• SDK：{_sdk_line()}")
    out(f"• 資料夾：{ROOT}" + ROOT_NOTES.get(ROOT_SOURCE, ""))

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
            if config.server:                                  # 架構限制（只說明，不算問題）
                from synox.discord.scope import GUEST_CARD_LIMIT
                out(f"  ℹ️ {GUEST_CARD_LIMIT}")
            out(f"  llm：{r.get('llm', {'kind': 'none'})}")
            out(f"  packs：{config.packs}　vault：{config.vault}")
            web = config.web
            out("  網頁介面：" + (f"開，http://127.0.0.1:{web.get('port')}/（/web 拿登入連結）"
                                + (f"　對外網址 {web.get('public_url')}" if web.get("public_url") else "")
                                if web.get("enabled", True) else "關（web.enabled=false）"))
            out(_heartbeat_line(config))
            out(_keep_awake_line(config))
            out(_activator_line(config))
            out(_stepup_line(config))
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
            elif kind == "local":
                problems += _local_lines(adapter, offline, out)
            elif offline:
                out(f"• AI：{adapter.name}（--offline：沒有實際測試）")
            else:
                err = adapter.probe()
                out(f"• AI：{adapter.name}　" + ("✅ 測試通過" if err is None else f"❌ {err}"))
                problems += 0 if err is None else 1
            if adapter is not None:                         # 完成宣稱檢查、停止詞（docs/adr/0008、0010）
                from synox.agent.claims import doctor_line
                out("  " + doctor_line(llm, adapter))
                from synox.agent.auto import doctor_line as harness_line          # docs/adr/0014～0017
                out("  " + harness_line(llm, adapter))
                from synox.llm.vision import summary as vision_line             # docs/adr/0021（不連網、不載入模型）
                out("  " + vision_line(llm, adapter))
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
    tools: List[str] = []
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
            if enabled and not loader.is_bundled(m):
                tools.append(m.name)                 # 使用者自己裝的工具（出廠的不算；loader.BUNDLED 現在是空的）
            lock_mark = "🔒" if lock_state == pack_lock.LOCKED else "未鎖定"
            lines.append(f"  {state} {m.name} {m.version} {m.stage_label}（{m.kind}，/{m.group}，{lock_mark}）  {rel}")
            if enabled:
                note = secret_lookup(m)
                if note:
                    lines.append(f"     {note}")
                if m.mcp_connected:                          # P4a／P4b：pack 外的程式、不支援的欄位、伺服器沒列的工具
                    from synox.packs import mcp as pack_mcp
                    for mcp_note in pack_mcp.doctor_notes(m, lock_dir):
                        lines.append(f"     {mcp_note}")
                boxed_out = sandbox.restricted_reason(config, m, box) if config is not None else ""
                if boxed_out:
                    lines.append(f"     🔐 {boxed_out}")
                runtime_note = sandbox.runtime_note(config, m) if config is not None else ""
                if runtime_note:                             # S2：用容器／不用、引擎找不找得到（只用 which）
                    lines.append(f"     {runtime_note}")
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
    from synox.packs import library                  # SYNOX 出廠不帶工具：裝了幾個、工具庫在哪裡
    for line in library.doctor_lines(config, tools):
        out(line)
        problems += "⚠️" in line
    health_text, bad = health_lines(config, os.path.join(ROOT, "data"))
    for line in health_text:
        out(line)
    problems += bad

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
