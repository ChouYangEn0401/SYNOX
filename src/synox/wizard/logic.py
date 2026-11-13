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
# 找不到 Claude Code 時，精靈與網頁設定頁的按鈕帶使用者去裝。要的是終端機的 `claude`（CLI），不是 Claude Desktop；
# 這頁是官方安裝說明（Windows：irm https://claude.ai/install.ps1 | iex）。
CLAUDE_DOWNLOAD_URL = "https://code.claude.com/docs/en/setup"
# 一鍵安裝：開一個 PowerShell 視窗跑官方的安裝指令（跟網頁設定頁「複製」的是同一行）。裝在使用者自己的資料夾，
# 不需要系統管理員；裝完同一個視窗接著打 claude 登入。
CLAUDE_INSTALL_PS = "irm https://claude.ai/install.ps1 | iex"


def claude_install_args(after: str) -> list:
    """PowerShell 的參數：跑官方安裝指令，跑完印一句接下來怎麼做，視窗留著（-NoExit）讓使用者看結果、接著登入。"""
    note = after.replace("'", "''")                  # PowerShell 單引號字串裡的 ' 要寫兩次
    return ["powershell", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            f"{CLAUDE_INSTALL_PS}; Write-Host ''; Write-Host '{note}' -ForegroundColor Cyan"]

# 其他金鑰來源：代號 → (下拉選單上的字, config 的 llm.kind, 預填的模型, 要不要填網址)
# 模型名稱只是預填，使用者可以改，「測一下」會驗。
KEY_PROVIDERS = OrderedDict([
    ("openai", ("OpenAI", "openai", "gpt-4.1-mini", False)),
    ("anthropic", ("Anthropic API", "anthropic", "claude-sonnet-4-5", False)),
    ("gemini", ("Gemini", "gemini", "gemini-2.5-flash", False)),
    ("openai_compat", ("相容端點（公司閘道、Ollama）", "openai_compat", "llama3.1", True)),
])
PROVIDERS = KEY_PROVIDERS                       # 舊名
CHOICES = ("claude_code", "keys", "local", "none")

# 本地模型（llm.kind = "local"，docs/adr/0007）：SYNOX 內建，沒有金鑰。伺服器代號 → 下拉選單上的字
LOCAL_SERVERS = OrderedDict([("ollama", "Ollama"), ("vllm", "vLLM"), ("lmstudio", "LM Studio"),
                             ("other", "其他 OpenAI 相容伺服器")])
LOCAL_TITLE = "本地模型（Ollama 等，在這台或家裡網路的電腦上跑）"


def local_defaults(server: str = "ollama") -> dict:
    from synox.llm.local import DEFAULT_MAX_TOTAL, DEFAULT_TIMEOUT, DEFAULT_URLS
    return {"server": server, "base_url": DEFAULT_URLS.get(server, DEFAULT_URLS["ollama"]),
            "timeout": int(DEFAULT_TIMEOUT), "max_total_timeout": int(DEFAULT_MAX_TOTAL)}


def local_advice(server: str = "ollama", base_url: str = "", model: str = "", *, prompt_chars=None,
                 max_tokens: int = 1024, opener=None, ram=None) -> dict:
    """context-size 建議（唯讀探測＋這台的記憶體；連不上退回靜態表）。精靈、文字版 init、網頁設定頁共用。"""
    from synox.llm.local import SERVERS, LocalAdapter
    server = server if server in SERVERS else "ollama"
    adapter = LocalAdapter(model, server=server, base_url=base_url, max_tokens=max_tokens, opener=opener)
    return adapter.advice(prompt_chars=prompt_chars, ram=ram)


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


# 選 Claude Code 時可以挑的模型（`claude --model` 吃的別名；空字串＝不指定，讓 Claude Code 自己用預設）。
CLAUDE_MODELS = [("", "預設（讓 Claude Code 自己選）"), ("sonnet", "Sonnet（平衡）"),
                 ("opus", "Opus（最強、較慢）"), ("haiku", "Haiku（最快、最省）")]


def default_choice(claude_found: bool) -> str:
    return "claude_code" if claude_found else "keys"


def llm_settings(choice: str, *, base_url: str = "", api_key: str = "", model: str = "",
                 provider: str = "openai", server: str = "ollama", context_size=0, tools: bool = True,
                 timeout=None, max_total_timeout=None) -> Tuple[dict, str]:
    """回 (config 的 llm 那一塊（金鑰先放明文，save() 會換成 vault: 參照）, 錯誤或空字串)。
    choice=local：server／base_url／model／context_size／tools（timeout、max_total_timeout 沒給＝預設 450／1800）。"""
    if choice == "none":
        return {"kind": "none"}, ""
    if choice == "claude_code":
        return {"kind": "claude_code", "model": model.strip()}, ""
    if choice == "local":
        from synox.llm.local import validate
        if not model.strip():
            return {}, t("err_local_model")
        if base_url.strip() and not base_url.strip().startswith(("http://", "https://")):
            return {}, t("err_url")
        raw = {**local_defaults(server if server in LOCAL_SERVERS else "ollama"), "model": model.strip(),
               "context_size": context_size, "tools": bool(tools)}
        if base_url.strip():
            raw["base_url"] = base_url.strip()
        if timeout not in (None, ""):
            raw["timeout"] = timeout
        if max_total_timeout not in (None, ""):
            raw["max_total_timeout"] = max_total_timeout
        try:
            out = validate(raw)
        except ValueError as e:
            return {}, str(e)
        return {k: out[k] for k in ("kind", "server", "base_url", "model", "context_size", "timeout",
                                    "max_total_timeout", "tools")}, ""
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
    """寫 config.json。llm.api_key 是明文時先存進保管箱，config 裡換成 "vault:llm_api_key"（"env:名字" 照原樣）。回寫進去的那份。"""
    cfg = json.loads(json.dumps(cfg))
    key = (cfg.get("llm") or {}).get("api_key", "")
    if key and not str(key).startswith((VAULT_PREFIX, "env:")):       # env:名字＝讀環境變數，本身不是金鑰
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
    lines.append(t("status_no_tools"))       # 出廠不帶工具：去工具庫（SYNOX_Libs）拿 .synoxpack 裝（packs/library.py）
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


# ── 從 .exe 安裝程式來的人（setup/installer/synox.iss 寫的 installer-choices.json）──────────────

# 安裝程式複製完檔案後，在 SYNOX 資料夾寫這個檔：語言、建議／自訂、桌面與開始功能表捷徑、.synoxpack、開機啟動、
# Claude Code 的結果、要不要「全部官方工具都裝」。精靈讀它：那三個勾選已經在安裝程式決定過，完成頁不再問一次。
# 沒有這個檔＝ZIP／git clone 來的（Setup.bat），完成頁照舊四個勾選。
INSTALLER_CHOICES = "installer-choices.json"


def installer_choices(root: str) -> dict:
    """SYNOX 資料夾裡安裝程式留下的選擇；沒有、讀不了、格式不對都回 {}（＝不是 .exe 裝的）。"""
    data = read_existing(os.path.join(root, INSTALLER_CHOICES))
    return data if data.get("source") == "exe-installer" else {}


def wants_all_tools(choices: dict) -> bool:
    """自訂頁勾了「全部官方工具都裝（不建議）」而且還沒裝過。"""
    return bool(choices.get("all_tools")) and not choices.get("all_tools_done")


def mark_all_tools_done(root: str, ok: bool) -> None:
    """裝過一次就記下來，重開精靈不會再裝一次（失敗也記：之後到網頁設定的工具庫自己挑）。"""
    path = os.path.join(root, INSTALLER_CHOICES)
    data = read_existing(path)
    if data:
        data["all_tools_done"] = True
        data["all_tools_ok"] = bool(ok)
        write_config(path, data)


def all_tools_args(python: str, config_path: str) -> list:
    """「全部官方工具都裝」：從 SYNOX 資料夾的 tools/（安裝程式附的工具庫，不連網）一個一個裝，照原本的安全檢查；
    需要輸入發行者名字的（T2）不會自動裝。"""
    return [python, "-m", "synox", "--config", config_path, "tools", "install", "--all", "--yes"]


# ── 第一次用：先做一次教學 ─────────────────────────────────────────

# HOOK（教學）：教學 pack 由另一個工作做，會放在 SYNOX repo 裡（每一種安裝方式都有）。接好之後把「怎麼開始」寫在這裡
# （例如在 SYNOX 打的指令，或網頁上的按鈕名稱），完成頁那一行就會帶上它；空字串＝只說「做一次教學」。
TUTORIAL_HOW = ""


def tutorial_line() -> str:
    """完成頁「做一次教學」那一行（Q3：建議安裝只裝環境＋教學，做完教學再挑工具）。"""
    line = t("finish_tutorial")
    return f"{line} {TUTORIAL_HOW}".strip() if TUTORIAL_HOW else line
