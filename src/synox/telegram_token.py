"""
Telegram bot token 放保管箱，不放 config.json（跟 Discord、LLM 金鑰同一套）。

    config.json：  "bot_token": "vault:telegram_bot_token"     真正的 token 在 data/secrets.json.enc
                   "bot_token": "env:SYNOX_TG_TOKEN"            從環境變數讀（部署用；本身不是 token）
                   "bot_token": "123456:AAH…"                   舊寫法（明文）：啟動、重跑精靈時自動搬進保管箱

- resolve(value, vault=…)：參照 → 真正的 token；明文照原樣。讀不到丟 TokenUnavailable（訊息不含 token）。
- store(cfg, token, vault)：存進保管箱、cfg 改寫成參照（精靈、init、網頁設定頁都走這裡）。
- migrate(config_path)：config.json 裡是明文 → 搬進保管箱、原子地改寫成參照、旁邊 config.json.* 的殘檔裡的明文也換掉。
  重複叫沒關係；保管箱打不開＝config 不動、log 一句白話警告（不印 token）。
- mask(token)：給畫面看的「…AB12」（只留最後 4 個字）。
- remember(token)：已知的 token 值登記到 log 遮罩（任何 log 行出現這串都換成 ***；SDK 連線錯誤會把網址印出來）。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Callable, Optional

VAULT_NAME = "telegram_bot_token"
VAULT_PREFIX = "vault:"
ENV_PREFIX = "env:"
REF = VAULT_PREFIX + VAULT_NAME

MIGRATED, UNCHANGED, FAILED = "migrated", "unchanged", "failed"


class TokenUnavailable(Exception):
    """參照讀不到（保管箱打不開、裡面沒有、環境變數沒設）。訊息是給人看的，不含 token。"""


def is_reference(value) -> bool:
    return isinstance(value, str) and value.strip().startswith((VAULT_PREFIX, ENV_PREFIX))


def is_plaintext(value) -> bool:
    """config.json 裡寫的是 token 本身（要搬進保管箱的那種）。"""
    return isinstance(value, str) and bool(value.strip()) and not is_reference(value)


def resolve(value, vault=None, *, opener: Optional[Callable[[], object]] = None) -> str:
    """config 的 bot_token 欄位 → 真正的 token（空字串＝沒填）。vault 沒給、要用時才叫 opener() 打開。"""
    value = str(value or "").strip()
    if value.startswith(ENV_PREFIX):
        name = value[len(ENV_PREFIX):]
        found = os.environ.get(name, "").strip()
        if not found:
            raise TokenUnavailable(f"config.json 的 bot_token 要從環境變數 {name} 讀，但這個環境變數沒有設。")
        return found
    if not value.startswith(VAULT_PREFIX):
        return value
    name = value[len(VAULT_PREFIX):]
    try:
        if vault is None:
            if opener is None:
                raise TokenUnavailable("Telegram bot token 放在保管箱，但保管箱沒有打開。")
            vault = opener()
        found = vault.secret(name)
    except TokenUnavailable:
        raise
    except Exception as e:                    # KeyringError／VaultError：訊息本身不含任何 secret
        raise TokenUnavailable(f"Telegram bot token 放在保管箱，但保管箱打不開（{type(e).__name__}：{e}）。")
    found = str(found or "").strip()
    if not found:
        raise TokenUnavailable(f"保管箱裡找不到 {name}：重跑 Setup.bat 或到網頁的設定 → 聊天通道，再貼一次 Telegram token。")
    return found


def mask(token) -> str:
    """畫面上只給看最後 4 個字：「…AB12」。沒有就空字串；太短的全部遮。"""
    token = str(token or "").strip()
    if not token:
        return ""
    return "…" + token[-4:] if len(token) > 12 else "…"


def store(cfg: dict, token: str, vault) -> dict:
    """token 存進保管箱、cfg["bot_token"] 換成參照。回改過的 cfg（同一個物件）。空 token 不動保管箱、寫空字串。"""
    token = str(token or "").strip()
    if not token:
        cfg["bot_token"] = ""
        return cfg
    vault.set_secret(VAULT_NAME, token)
    cfg["bot_token"] = REF
    remember(token)
    return cfg


def remember(token) -> None:
    """把這串 token 登記到 log 遮罩（packs/kit.py）：之後任何 log 行出現它都換成 ***。"""
    token = str(token or "").strip()
    if len(token) < 8:
        return
    try:
        from synox.packs import kit
        kit.mask_in_logs(token)
    except Exception:                          # 遮罩裝不上不該讓程式起不來
        logging.warning("[CONFIG] could not install the log mask for the Telegram token")


def default_opener(config_path: str, raw: dict) -> Callable[[], object]:
    """照 config.json 的 data_dir、vault.mode 打開保管箱（跟精靈存 LLM 金鑰同一個）。"""
    def opener():
        from synox.config import vault_settings
        from synox.vault import open_vault
        return open_vault(vault_settings(raw, os.path.dirname(os.path.abspath(config_path))))
    return opener


def _read(path: str):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _write(path: str, cfg: dict) -> None:
    from synox.wizard.logic import write_config                # tmp＋os.replace：寫到一半當掉也不會留半份
    write_config(path, cfg)


def scrub_siblings(config_path: str, token: str) -> list:
    """config.json 旁邊的 config.json.*（.tmp、.bak、手動備份…）若含明文 token，把那串換成參照。回改過的檔名。"""
    token = str(token or "").strip()
    folder = os.path.dirname(os.path.abspath(config_path))
    base = os.path.basename(config_path)
    changed = []
    if len(token) < 8 or not os.path.isdir(folder):
        return changed
    for name in sorted(os.listdir(folder)):
        if not name.startswith(base + ".") or name == base:
            continue
        path = os.path.join(folder, name)
        try:
            if not os.path.isfile(path) or os.path.getsize(path) > 4 * 1024 * 1024:
                continue
            with open(path, "rb") as f:
                blob = f.read()
            needle = token.encode("utf-8")
            if needle not in blob:
                continue
            tmp = path + ".scrub"
            with open(tmp, "wb") as f:
                f.write(blob.replace(needle, REF.encode("utf-8")))
            os.replace(tmp, path)
            changed.append(name)
        except OSError:
            logging.warning("[CONFIG] could not scrub the Telegram token from %s; delete that file by hand", name)
    return changed


def migrate(config_path: str, vault_opener: Optional[Callable[[dict], object]] = None, *,
            log: Optional[logging.Logger] = None) -> str:
    """config.json 的 bot_token 是明文 → 存進保管箱、改寫成 "vault:telegram_bot_token"。
    回 MIGRATED／UNCHANGED（本來就是參照、沒填、沒有 config.json）／FAILED（保管箱打不開或寫不了：config 不動）。"""
    log = log or logging.getLogger()
    path = os.path.abspath(config_path)
    if not os.path.exists(path):
        return UNCHANGED
    try:
        raw = _read(path)
    except (OSError, ValueError):
        return UNCHANGED                       # 壞掉的 JSON：讓 SynoxConfig.load 去講清楚
    if not isinstance(raw, dict) or not is_plaintext(raw.get("bot_token")):
        return UNCHANGED
    token = str(raw["bot_token"]).strip()
    remember(token)                            # 就算搬不成，這串也不准出現在 log
    try:
        vault = vault_opener(raw) if vault_opener is not None else default_opener(path, raw)()
        vault.set_secret(VAULT_NAME, token)
        if str(vault.secret(VAULT_NAME) or "").strip() != token:
            raise RuntimeError("read-back mismatch")
    except Exception as e:
        log.warning("[CONFIG] Telegram bot token 還是明文寫在 config.json：保管箱打不開或寫不了（%s），這次不搬；"
                    "config.json 沒有改。", type(e).__name__)
        return FAILED
    try:
        _write(path, {**raw, "bot_token": REF})
    except OSError as e:
        log.warning("[CONFIG] Telegram bot token 已存進保管箱，但 config.json 寫不回去（%s）；config.json 沒有改。",
                    type(e).__name__)
        return FAILED
    scrubbed = scrub_siblings(path, token)
    log.info("[CONFIG] Telegram bot token 搬進保管箱了：config.json 的 bot_token 改寫成 \"%s\"%s。", REF,
             f"（另外清掉了 {'、'.join(scrubbed)} 裡的明文）" if scrubbed else "")
    return MIGRATED


__all__ = ["ENV_PREFIX", "FAILED", "MIGRATED", "REF", "TokenUnavailable", "UNCHANGED", "VAULT_NAME", "VAULT_PREFIX",
           "default_opener", "is_plaintext", "is_reference", "mask", "migrate", "remember", "resolve",
           "scrub_siblings", "store"]
