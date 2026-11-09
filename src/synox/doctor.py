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


def run(offline: bool = False, config_path: str = "", out: Callable[[str], None] = print) -> int:
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
            problems += 0 if config.has_token else 1
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

    # packs
    from synox.packs.loader import PACK_DIRS, discover
    from synox.packs.manifest import ManifestError, read
    lines: List[str] = []
    for folder in discover(PACK_DIRS):
        rel = os.path.relpath(folder, ROOT)
        try:
            m = read(folder)
            enabled = config.pack_enabled(m.name) if config else True
            state = "connector（只登記）" if m.kind == "connector" else ("✅" if enabled else "⏸ 停用")
            lines.append(f"  {state} {m.name} {m.version}（{m.kind}，/{m.group}）  {rel}")
        except ManifestError as e:
            lines.append(f"  ❌ {rel}：{e}")
            problems += 1
    out(f"• packs：{len(lines)} 個")
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
