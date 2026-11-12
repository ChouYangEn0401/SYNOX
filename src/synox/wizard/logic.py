"""
精靈不用畫面的那一半：把使用者在四頁裡選的東西變成 config.json（可以單獨測試）。

    mode = "personal"                                          第 1 頁：這台給誰用（personal｜server）
    llm, err = llm_settings("keys", provider="openai", api_key="sk-…")     第 4 頁：AI
    cfg = build_config(token, owner_id, llm, mode=mode)
    save(path, cfg)                   # 金鑰進保管箱（data/secrets.json.enc），config.json 只寫 "vault:llm_api_key"

AI 頁的三種選擇：claude_code（預設：這台電腦登入的 Claude Code）｜keys（其他金鑰來源：OpenAI、Anthropic、
Gemini、相容端點）｜none（先不用 AI）。舊的 friend／own 仍然收（= keys）。
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from typing import Callable, Optional, Tuple

from synox.llm.factory import VAULT_PREFIX
from synox.wizard.i18n import t

SECRET_NAME = "llm_api_key"

# ── 第 1 頁：這台給誰用 ─────────────────────────────────────────────

MODE_CHOICES = OrderedDict([
    ("personal", ("只有我（個人版）",
                  "只有你一個人用：只有配對的那個 Telegram 帳號用得到指令。",
                  "資料都在這台電腦，筆記、記帳加密存一份。")),
    ("server", ("一群人（伺服器版）",
                "家人、同事、社團一起用：陌生人傳訊息會變成訪客，你（或你指定的管理員）決定誰能用什麼。",
                "每個人的筆記、記帳各自加密存一份，別人看不到。")),
])
ENGINEER_HINT = "工程師？直接改 config.json（範例 config.example.json），不用精靈。"


def mode_lines(mode: str) -> Tuple[str, str, str]:
    """(標題, 說明一, 說明二)，用精靈選的語言（i18n）。"""
    MODE_CHOICES[mode]                              # 不認得的 mode 一樣丟 KeyError
    return t(f"mode.{mode}.title"), t(f"mode.{mode}.one"), t(f"mode.{mode}.two")


# ── 第 4 頁：AI ─────────────────────────────────────────────────────

CLAUDE_TITLE = "預設：Claude（這台電腦登入的 Claude Code）"
CLAUDE_DOWNLOAD_URL = "https://claude.com/product/claude-code"      # 找不到 Claude Code 時，精靈的按鈕帶使用者去下載

# 其他金鑰來源：代號 → (下拉選單上的字, config 的 llm.kind, 預填的模型, 要不要填網址)
# 模型名稱只是預填，使用者可以改，「測一下」會驗。
KEY_PROVIDERS = OrderedDict([
    ("openai", ("OpenAI", "openai", "gpt-4.1-mini", False)),
    ("anthropic", ("Anthropic API", "anthropic", "claude-sonnet-4-5", False)),
    ("gemini", ("Gemini", "gemini", "gemini-2.5-flash", False)),
    ("openai_compat", ("相容端點（公司閘道、Ollama）", "openai_compat", "llama3.1", True)),
])
PROVIDERS = KEY_PROVIDERS                       # 舊名
CHOICES = ("claude_code", "keys", "none")


def _label(code: str) -> str:
    return t("provider_compat") if code == "openai_compat" else KEY_PROVIDERS[code][0]


def provider_labels() -> list:
    """下拉選單上的字（用精靈選的語言）。"""
    return [_label(code) for code in KEY_PROVIDERS]


def provider_by_label(label: str) -> str:
    for code, v in KEY_PROVIDERS.items():
        if label in (v[0], _label(code)):
            return code
    return label if label in KEY_PROVIDERS else "openai"


def default_model(provider: str) -> str:
    return KEY_PROVIDERS[provider][2] if provider in KEY_PROVIDERS else ""


def needs_base_url(provider: str) -> bool:
    return bool(KEY_PROVIDERS.get(provider, ("", "", "", False))[3])


def claude_status(which: Optional[Callable[[], Optional[str]]] = None) -> Tuple[bool, str]:
    """(找到了沒, 一句給畫面的狀態)。"""
    if which is None:
        from synox.llm.claude_code import find_claude
        which = find_claude
    path = which()
    if path:
        return True, t("claude_found", path=path)
    return False, t("claude_missing")


def default_choice(claude_found: bool) -> str:
    return "claude_code" if claude_found else "keys"


def llm_settings(choice: str, *, base_url: str = "", api_key: str = "", model: str = "",
                 provider: str = "openai") -> Tuple[dict, str]:
    """回 (config 的 llm 那一塊（金鑰先放明文，save() 會換成 vault: 參照）, 錯誤或空字串)。"""
    if choice == "none":
        return {"kind": "none"}, ""
    if choice == "claude_code":
        return {"kind": "claude_code", "model": model.strip()}, ""
    if choice == "friend":                         # 舊選項：朋友／公司給的網址＝相容端點
        choice, provider = "keys", "openai_compat"
    if choice == "own":
        choice = "keys"
    if choice != "keys":
        return {}, t("err_unknown_choice", choice=choice)
    if provider not in KEY_PROVIDERS:
        return {}, t("err_unknown_provider", provider=provider)
    _label, kind, suggested, wants_url = KEY_PROVIDERS[provider]
    out = {"kind": kind, "api_key": api_key.strip(), "model": model.strip() or suggested}
    if wants_url:
        if not base_url.strip().startswith(("http://", "https://")):
            return {}, t("err_url")
        if not model.strip():
            return {}, t("err_model")
        out["base_url"], out["tools"] = base_url.strip(), True
    elif not api_key.strip():
        return {}, t("err_api_key")
    return out, ""


def probe_llm(llm: dict, make=None) -> Optional[str]:
    """「測一下」：照 llm 那一塊做出 adapter，真的打一句。None＝通了，否則一句人話。"""
    if (llm or {}).get("kind", "none") == "none":
        return None
    if make is None:
        from synox.llm import make_adapter as make
    try:
        adapter = make({"llm": llm})
    except Exception as e:                         # LLMError（設定不完整、沒裝 ntu_easy_llm）
        return str(e)
    if adapter is None:
        return t("err_unknown_source")
    try:
        return adapter.probe()
    except Exception as e:
        return t("err_test_failed", e=e)


def build_config(token: str, owner_id: int, llm: dict, *, existing: Optional[dict] = None,
                 mode: Optional[str] = None, language: Optional[str] = None) -> dict:
    """language＝精靈用的語言（"zh-TW"、"en"…），寫進 config.json 的 "language"（只是記著；SynoxConfig 不讀它）。"""
    cfg = dict(existing or {})
    if language:
        cfg["language"] = language
    if mode is not None:
        if mode not in MODE_CHOICES:
            raise ValueError(f"mode must be one of {tuple(MODE_CHOICES)}")
        cfg["mode"] = mode
    cfg.setdefault("mode", "personal")
    cfg.update({"bot_token": token.strip(), "owner_id": int(owner_id)})
    cfg["llm"] = {"max_steps": 6, "max_tokens": 1024, **{k: v for k, v in llm.items()}}
    cfg.setdefault("vault", {"mode": "dpapi" if os.name == "nt" else "file"})
    cfg.setdefault("packs", {"enabled": "all", "disabled": []})
    from synox.runtime import settings as runtime_settings
    cfg.setdefault("runtime", runtime_settings.defaults())   # 心跳每 45 分鐘、常駐助理（docs/adr/0001）；已經有的不動
    return cfg


def write_config(path: str, cfg: dict) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def read_existing(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path: str, cfg: dict, vault_opener=None) -> dict:
    """寫 config.json。llm.api_key 是明文時先存進保管箱，config 裡換成 "vault:llm_api_key"。回寫進去的那份。"""
    cfg = json.loads(json.dumps(cfg))
    key = (cfg.get("llm") or {}).get("api_key", "")
    if key and not str(key).startswith(VAULT_PREFIX):
        if vault_opener is None:
            from synox.config import SynoxConfig
            from synox.vault import open_vault

            def vault_opener(c):
                return open_vault(SynoxConfig.from_dict(c, require_token=False,
                                                        root=os.path.dirname(os.path.abspath(path))))
        vault_opener(cfg).set_secret(SECRET_NAME, key)
        cfg["llm"]["api_key"] = VAULT_PREFIX + SECRET_NAME
    write_config(path, cfg)
    return cfg


def local_owner_id() -> int:
    """沒接 Telegram 的擁有者 id（保留號段第一號）：網頁介面、Discord 配對都認這個人；之後補 Telegram 會換成真的 id。"""
    from synox.identity import BASE
    return BASE


def discord_owner_sentinel() -> int:
    """Discord-only 擁有者的 owner_id：保留號段的第一號（跟 config.py 的說明、pair-discord 一致）。"""
    from synox.identity import BASE
    return BASE


def save_discord_token(config_path: str, cfg: dict, token: str, vault_opener=None) -> dict:
    """把 Discord bot token 存進保管箱，cfg 開 channels.discord.enabled，寫回 config.json。回寫進去的那份。"""
    from synox.discord import VAULT_NAME
    cfg = json.loads(json.dumps(cfg))
    channels = dict(cfg.get("channels") or {})
    old = channels.get("discord") if isinstance(channels.get("discord"), dict) else {}
    if "bots" in old:        # 多 bot 寫法跟 bot_token 不能並存（synox.discord.bots.parse）；不替使用者改
        # 先檢查再動保管箱：bots 的 default bot 也用 discord_bot_token 這個名字，不能被蓋掉
        raise ValueError("config.json 的 channels.discord 已經用 bots 寫法（多個 bot）：請直接改 config.json，精靈不動它。")
    if vault_opener is None:
        from synox.config import SynoxConfig
        from synox.vault import open_vault

        def vault_opener(c):
            return open_vault(SynoxConfig.from_dict(c, require_token=False,
                                                    root=os.path.dirname(os.path.abspath(config_path))))
    vault_opener(cfg).set_secret(VAULT_NAME, token.strip())
    channels["discord"] = {**old, "enabled": True, "bot_token": f"vault:{VAULT_NAME}"}   # 重跑精靈不洗掉其他設定
    cfg["channels"] = channels
    write_config(config_path, cfg)
    return cfg


def bind_discord_owner(config_path: str, cfg: dict, external_id) -> None:
    """配對成功後：把那個 Discord 帳號接到 cfg 裡的 owner_id（identities.json）。"""
    from synox.config import SynoxConfig
    from synox.identity import Identities
    config = SynoxConfig.from_dict(cfg, require_token=False, root=os.path.dirname(os.path.abspath(config_path)))
    Identities(config.path("identities.json")).bind("discord", external_id, config.owner_id)


def finish_status(notes: list, *, launched: bool, has_token: bool) -> str:
    """完成頁最後的狀態文字。launched＝勾了「完成後立刻開啟 SYNOX」（Start.bat 已經開了）；
    沒勾就只存了設定，告訴使用者之後怎麼開。has_token＝接了 Telegram／Discord。"""
    lines = list(notes)
    if not launched:
        head = t("status_saved_head")
        lines.append(t("status_how_to_open"))
        if not has_token:
            lines.append(t("status_add_channel_later"))
    elif has_token:
        head = t("status_bot_head")
    else:
        head = t("status_web_head")
        lines.append(t("status_add_channel_later"))
    return "\n".join([head] + lines + [t("status_can_close")])


def web_login_link(config_path: str) -> str:
    """完成頁用：擁有者的網頁介面一次性登入連結（web.enabled=false 或設定讀不了 → ""）。"""
    try:
        from synox.config import SynoxConfig
        from synox.web import issue_owner_link
        config = SynoxConfig.load(config_path, require_token=False)
        if not config.web.get("enabled", True) or not config.owner_id:
            return ""
        return issue_owner_link(config)
    except Exception:
        return ""
