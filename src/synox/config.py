"""
SYNOX 的設定：SDK 的 BotConfig 欄位（bot_token、owner_id、data_dir、時效…）＋ SYNOX 自己多的幾塊。

    {
      "mode": "personal",                      personal（只有我，預設）｜server（一群人：帳號、角色、每人自己的資料）
      "bot_token": "123456:AAH…", "owner_id": 123456789,
      "llm":   {"kind": "openai_compat", "base_url": "https://…/v1", "api_key": "vault:llm_api_key",
                "model": "…", "tools": true, "max_steps": 6, "max_tokens": 1024},
               本地模型（docs/adr/0007）：{"kind": "local", "server": "ollama", "base_url": "http://127.0.0.1:11434",
                "model": "qwen3.5:9b", "context_size": 8192, "timeout": 450, "max_total_timeout": 1800, "tools": true}
      "vault": {"mode": "dpapi"},              dpapi（Windows 預設）｜file（金鑰明文存在 data/.synox.key）
      "packs": {"enabled": "all", "disabled": [], "dirs": [], "library": ""},   library：工具庫（SYNOX_Libs）在哪
                                               （資料夾或網址；沒寫＝SYNOX 資料夾旁的 tools/，有 index.json 才算；
                                               packs/library.py、wizard/tools.py）
      "web":   {"enabled": true, "port": 8830, "public_url": ""},   本機網頁介面（只綁 127.0.0.1）
      "ai_member_monthly_usd": 2.0,            伺服器版：每個成員每月的 AI 額度（美元）
      "channels": {"discord": {"enabled": true, "bot_token": "vault:discord_bot_token"}},  Discord 私訊（docs/discord.md）
      "policy": {"roles": {"member": {"capabilities": ["network", "filesystem:own"]}, …}}  角色能力上限（synox/policy.py；
                                               沒寫＝預設；exec、filesystem:any 不能給任何角色）
      "runtime": {"heartbeat": {"enabled": true, "interval_min": 45, …}, "mother": {…}}   常駐助理與心跳
                                               （synox/runtime/settings.py；docs/adr/0001）
      "presentation": {"enabled": false}       AI 回覆先經呈現層（Markdown → 各通道的格式）再送；預設關＝原樣送
                                               （synox/present；docs/presentation.md）
      "health": {"enabled": true, "consecutive": 3, …}    工具健康：門檻、冷卻、試用次數（選填；synox/health/settings.py、
                                               docs/tool-health.md）
    }
- 多個 Discord bot：channels.discord.bots.<名字> = {"token": "vault:…", "surface": "dm", "packs": "all", "ai": true}
  （synox/discord/bots.py 解析與檢查；舊寫法＝bots.default）。
- 只用 Discord 時 bot_token、owner_id 可以不填（owner_id 預設保留號段 10^15，`discord pair` 把你的 Discord 帳號接上；
  接上之前私訊型 bot 誰的私訊都不收，陌生人的號碼從 10^15+1 起，見 identity.py）。

- 路徑一律相對於 SYNOX 資料夾（不管從哪裡啟動）：data_dir 沒寫就是 <SYNOX>/data。
- api_key 可以直接寫，也可以寫 "vault:<名字>"：真正的值放在 data/secrets.json.enc（精靈就是這樣存的）。
- 換 LLM 只改 llm 這一塊（invariant 2）。
- mode：personal＝一個擁有者，資料是共用的一份；server＝陌生人傳訊息自動登記成訪客（GUEST），只看得到
  pack.json access 允許的；擁有者／管理員用 /user_role 升級；vault 的 pack 資料每人一份（data/users/<id>/）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from isdtelekit.host.config import BotConfig, ConfigError

from synox.health import settings as health_settings
from synox.policy import parse_policy
from synox.runtime import settings as runtime_settings

def default_root(environ=None, package_file: Optional[str] = None, cwd: Optional[str] = None) -> tuple:
    """SYNOX 資料夾（config.json、data/、packs/、tools/ 的位置）→ (路徑, 從哪裡決定的)。不寫死任何一台電腦的路徑：
    1. 環境變數 SYNOX_HOME（相對路徑以目前資料夾為準）——工程師把資料放別處、測試、Libs 的腳本用；
    2. 原始碼的版面（git clone、zip、安裝程式都是這種）：<SYNOX>/src/synox/config.py → <SYNOX>；
    3. 其他（`pip install` 進 site-packages、沒有 src/ 這一層）：目前所在的資料夾（doctor 會印出來，要換就設 SYNOX_HOME）。"""
    environ = os.environ if environ is None else environ
    home = (environ.get("SYNOX_HOME") or "").strip()
    if home:
        return os.path.abspath(os.path.join(cwd or os.getcwd(), home)), "SYNOX_HOME"
    package = os.path.dirname(os.path.abspath(package_file or __file__))          # …/src/synox
    src = os.path.dirname(package)
    if os.path.basename(package) == "synox" and os.path.basename(src).lower() == "src":
        return os.path.dirname(src), "source"
    return os.path.abspath(cwd or os.getcwd()), "cwd"


ROOT, ROOT_SOURCE = default_root()
CONFIG_PATH = os.path.join(ROOT, "config.json")

LLM_KINDS = ("openai", "anthropic", "gemini", "openai_compat", "claude_code", "local", "fake", "none")
DEFAULT_LLM = {"kind": "none", "max_steps": 6, "max_tokens": 1024, "completion_guard": "auto", "verify_retries": 2,
               "summarize_on_limit": "auto"}
DEFAULT_VAULT = {"mode": "dpapi" if os.name == "nt" else "file"}
DEFAULT_PACKS = {"enabled": "all", "disabled": []}
DEFAULT_WEB = {"enabled": True, "port": 8830, "public_url": ""}
DEFAULT_STEPUP_MINUTES = 15                 # 手機驗證器解鎖幾分鐘（ADR 0025；SDK 預設 30）
# 工具服務（ADR 0024、計畫 C1）：enabled 是 true 也不會自己開任何服務，只是允許擁有者開。綁在哪裡不由設定決定（web/apps/listen.py）
DEFAULT_APPS = {"enabled": True, "port_first": 8841, "port_count": 16, "max_running": 3,
                "idle_suggest_min": 30, "idle_close_min": 120}


def parse_apps(raw, web_port: int) -> dict:
    """web.apps → 檢查過的設定（不合丟 ConfigError，一句白話）。"""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("config.json 的 web.apps 要是一個 {…} 物件。")
    out = {**DEFAULT_APPS, **raw}
    unknown = sorted(k for k in raw if k not in DEFAULT_APPS)
    if unknown:
        raise ConfigError(f"config.json 的 web.apps 不認得 {'、'.join(unknown)}（只能是 {'、'.join(DEFAULT_APPS)}）。")
    out["enabled"] = bool(out["enabled"])

    def number(key, low, high):
        value = out[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigError(f"config.json 的 web.apps.{key} 要是 {low}–{high} 的整數。")
        return value
    first = number("port_first", 1024, 65000)
    count = number("port_count", 1, 40)
    if first <= int(web_port or 0) < first + count and "port_first" not in raw:
        # 使用者把網頁介面的埠設在預設的工具服務範圍裡（舊設定沒有 web.apps）：預設範圍往後挪，不讓舊設定開不起來
        first = out["port_first"] = int(web_port) + 1
    if first <= int(web_port or 0) < first + count:
        raise ConfigError(f"config.json 的 web.apps 的埠範圍（{first}–{first + count - 1}）不能包含網頁介面的 web.port。")
    number("max_running", 1, count)
    suggest = number("idle_suggest_min", 0, 1440)
    close = number("idle_close_min", 0, 1440)
    if suggest and close and close <= suggest:
        raise ConfigError("config.json 的 web.apps.idle_close_min 要大於 idle_suggest_min（或寫 0＝不自動關）。")
    return out


# 手機入口（ADR 0026、計畫 K7）：預設關。綁在哪裡不由設定決定（閘門也只綁 127.0.0.2，web/apps/listen.py）
DEFAULT_REMOTE = {"enabled": False, "minutes": 30, "max_minutes": 120, "idle_min": 10, "gate_port": 8861,
                  "tunnel": {"kind": "cloudflared", "path": ""}}
TUNNEL_KINDS = ("cloudflared",)


def parse_remote(raw, web_port: int, apps: dict) -> dict:
    """web.remote → 檢查過的設定（不合丟 ConfigError，一句白話）。"""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("config.json 的 web.remote 要是一個 {…} 物件。")
    unknown = sorted(k for k in raw if k not in DEFAULT_REMOTE)
    if unknown:
        raise ConfigError(f"config.json 的 web.remote 不認得 {'、'.join(unknown)}（只能是 {'、'.join(DEFAULT_REMOTE)}）。")
    out = {**DEFAULT_REMOTE, **raw}
    out["enabled"] = bool(out["enabled"])

    def number(key, low, high):
        value = out[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigError(f"config.json 的 web.remote.{key} 要是 {low}–{high} 的整數。")
        return value
    top = number("max_minutes", 5, 240)
    number("minutes", 5, top)
    number("idle_min", 1, 120)
    port = number("gate_port", 1024, 65000)
    first, count = int(apps.get("port_first", 0)), int(apps.get("port_count", 0))
    if (port == int(web_port or 0) or first <= port < first + count) and "gate_port" not in raw:
        port = out["gate_port"] = max(first + count, int(web_port or 0) + 1)       # 舊設定：預設的閘門埠往後挪
    if port == int(web_port or 0) or first <= port < first + count:
        raise ConfigError("config.json 的 web.remote.gate_port 不能跟網頁介面或工具服務的埠重疊。")
    tunnel = out.get("tunnel")
    if not isinstance(tunnel, dict) or set(tunnel) - {"kind", "path"}:
        raise ConfigError('config.json 的 web.remote.tunnel 要寫成 {"kind": "cloudflared", "path": ""}。')
    tunnel = {"kind": "cloudflared", "path": "", **tunnel}
    if tunnel["kind"] not in TUNNEL_KINDS or not isinstance(tunnel["path"], str):
        raise ConfigError("config.json 的 web.remote.tunnel.kind 只能是 cloudflared；path 是通道程式的路徑（可以空著）。")
    out["tunnel"] = tunnel
    return out


DEFAULT_MEMBER_USD = 2.0
DEFAULT_PRESENTATION = {"enabled": False}
MODES = ("personal", "server")


@dataclass
class SynoxConfig(BotConfig):
    llm: dict = field(default_factory=lambda: dict(DEFAULT_LLM))
    vault: dict = field(default_factory=lambda: dict(DEFAULT_VAULT))
    packs: dict = field(default_factory=lambda: dict(DEFAULT_PACKS))
    mode: str = "personal"
    root: str = ROOT
    web: dict = field(default_factory=lambda: dict(DEFAULT_WEB))
    ai_member_monthly_usd: float = DEFAULT_MEMBER_USD
    policy: dict = field(default_factory=lambda: parse_policy(None))     # 角色能力上限（synox/policy.py）
    runtime: dict = field(default_factory=runtime_settings.defaults)    # 心跳、常駐助理（synox/runtime/settings.py）
    presentation: dict = field(default_factory=lambda: dict(DEFAULT_PRESENTATION))   # 呈現層（synox/present）
    health: dict = field(default_factory=health_settings.defaults)      # 工具健康：門檻、冷卻（synox/health/settings.py）

    @property
    def server(self) -> bool:
        return self.mode == "server"

    @property
    def discord_enabled(self) -> bool:
        from synox.discord import enabled
        return enabled(self)

    @classmethod
    def from_dict(cls, raw: dict, *, require_token: bool = True, root: Optional[str] = None) -> "SynoxConfig":
        discord = (raw.get("channels") or {}).get("discord") if isinstance(raw.get("channels"), dict) else None
        if discord and raw.get("owner_id", raw.get("machine_owner_id")) in (None, ""):
            # 只用 Discord、沒有 Telegram id：擁有者用保留號段的第一號（BASE，identity.py 不會發給陌生人），
            # 之後 discord pair／owner_user_id 把 Discord 帳號接上來；接上之前私訊型 bot 不收任何私訊
            from synox.identity import BASE
            raw = {**raw, "owner_id": BASE}
        from synox.discord.bots import parse as parse_discord_bots
        parse_discord_bots(discord)                   # 設定錯在這裡就講清楚（ConfigError）
        base = BotConfig.from_dict(raw, require_token=require_token)
        root = os.path.abspath(root or ROOT)
        data_dir = base.data_dir if os.path.isabs(base.data_dir) else os.path.join(root, base.data_dir)
        llm = {**DEFAULT_LLM, **(raw.get("llm") or {})}
        if llm.get("kind") not in LLM_KINDS:
            raise ConfigError(f"config.json 的 llm.kind 只能是 {'、'.join(LLM_KINDS)}（現在是 {llm.get('kind')!r}）。")
        llm = parse_llm_extras(llm)
        vault = {**DEFAULT_VAULT, **(raw.get("vault") or {})}
        if vault.get("mode") not in ("dpapi", "file"):
            raise ConfigError("config.json 的 vault.mode 只能是 dpapi 或 file。")
        packs = {**DEFAULT_PACKS, **(raw.get("packs") or {})}
        mode = parse_mode(raw.get("mode"))
        web = {**DEFAULT_WEB, **(raw.get("web") or {})}
        try:
            web["port"] = int(web.get("port") or 0)
        except (TypeError, ValueError):
            raise ConfigError("config.json 的 web.port 要是數字（例如 8830）。")
        if not 0 <= web["port"] <= 65535:
            raise ConfigError("config.json 的 web.port 要在 0–65535 之間。")
        web["enabled"] = bool(web.get("enabled", True))
        web["apps"] = parse_apps(web.get("apps"), web["port"])
        web["remote"] = parse_remote(web.get("remote"), web["port"], web["apps"])
        try:
            member_usd = float(raw.get("ai_member_monthly_usd", DEFAULT_MEMBER_USD))
        except (TypeError, ValueError):
            raise ConfigError("config.json 的 ai_member_monthly_usd 要是數字（美元，例如 2.0）。")
        policy = parse_policy(raw.get("policy"))      # exec／filesystem:any 寫進任何角色＝拒（第 1 關式檢查）
        try:
            runtime = runtime_settings.parse(raw.get("runtime"))
        except runtime_settings.RuntimeConfigError as e:
            raise ConfigError(f"config.json：{e}")
        try:
            stepup_minutes = int(raw.get("stepup_minutes", DEFAULT_STEPUP_MINUTES))
        except (TypeError, ValueError):
            raise ConfigError("config.json 的 stepup_minutes 要是數字（解鎖幾分鐘，1–120）。")
        if not 1 <= stepup_minutes <= 120:
            raise ConfigError("config.json 的 stepup_minutes 要在 1–120 之間（解鎖幾分鐘）。")
        presentation = parse_presentation(raw.get("presentation"))
        try:
            health = health_settings.parse(raw.get("health"))
        except health_settings.HealthConfigError as e:
            raise ConfigError(f"config.json：{e}")
        return cls(bot_token=base.bot_token, owner_id=base.owner_id,
                   poll_interval_seconds=base.poll_interval_seconds, data_dir=data_dir,
                   stepup_minutes=stepup_minutes, raw=dict(raw), llm=llm, vault=vault, packs=packs, mode=mode,
                   root=root, web=web, ai_member_monthly_usd=max(0.0, member_usd), policy=policy,
                   runtime=runtime, presentation=presentation, health=health)

    @classmethod
    def load(cls, path: Optional[str] = None, *, require_token: bool = True,
             root: Optional[str] = None) -> "SynoxConfig":
        path = path or CONFIG_PATH
        if not os.path.exists(path):
            raise ConfigError(f"找不到 {path}：先雙擊 Setup.bat 跑安裝精靈（或複製 config.example.json 成 config.json）。")
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
        except ValueError as e:
            raise ConfigError(f"{path} 不是合法的 JSON：{e}")
        if not isinstance(raw, dict):
            raise ConfigError(f"{path} 最外層要是一個 {{…}} 物件。")
        return cls.from_dict(raw, require_token=require_token, root=root or os.path.dirname(os.path.abspath(path)))

    def pack_enabled(self, name: str) -> bool:
        enabled = self.packs.get("enabled", "all")
        if name in (self.packs.get("disabled") or []):
            return False
        return enabled == "all" or name in (enabled or [])

    def pack_dirs(self) -> tuple:
        """要掃哪些資料夾找 pack：SYNOX 自己的 packs/（安裝的落點），再加 config.json `packs.dirs` 列的。
        `packs.dirs` 的每一項可以是「裡面有很多 pack 的資料夾」，也可以直接是「一個 pack 的資料夾」（裡面就有 pack.json）——
        後者是為了把別的 repo 裡的 pack 原地接進來（例如金流簿的 `<記帳專案>/synox-pack`，它的 {python} 要指向那個 repo 的 .venv，
        所以不能複製進 packs/）。相對路徑以 SYNOX 資料夾為準；不存在的資料夾略過（doctor 會提）。"""
        extra = []
        for item in (self.packs.get("dirs") or []):
            if not isinstance(item, str) or not item.strip():
                continue
            path = item if os.path.isabs(item) else os.path.join(self.root, item)
            extra.append(os.path.normpath(path))
        from synox.packs.loader import PACK_DIRS      # 延後 import：loader 也 import config
        return tuple(PACK_DIRS) + tuple(extra)


def parse_mode(value) -> str:
    """config.json 的 mode：沒寫＝personal；大小寫、前後空白不計較；其他值丟 ConfigError。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return "personal"
    mode = str(value).strip().lower()
    if mode not in MODES:
        raise ConfigError(f"config.json 的 mode 只能是 personal（只有我）或 server（一群人）（現在是 {value!r}）。")
    return mode


def parse_llm_extras(llm: dict) -> dict:
    """kind=local：補預設、檢查（synox/llm/local.py 的 validate，docs/adr/0007）；其他 kind 的 llm.timeout 只檢查型別。
    每個 kind：完成宣稱檢查的 completion_guard（auto｜on｜off）、verify_retries（0～5）、summarize_on_limit（auto｜on｜off）
    （synox/agent/claims.py，docs/adr/0008、0012）寫錯＝ConfigError；think 只收 true／false。"""
    from synox.agent import claims
    try:
        llm = {**llm, "completion_guard": claims.parse_mode(llm.get("completion_guard")),
               "verify_retries": claims.parse_retries(llm.get("verify_retries")),
               "summarize_on_limit": claims.parse_switch(llm.get("summarize_on_limit"), "summarize_on_limit")}
    except ValueError as e:
        raise ConfigError(f"config.json：{e}")
    if "think" in llm and not isinstance(llm["think"], bool):
        raise ConfigError("config.json 的 llm.think 只能是 true 或 false。")
    llm = parse_harness_extras(llm)
    if llm.get("kind") == "local":
        from synox.llm.local import validate
        try:
            return {**llm, **validate(llm)}
        except ValueError as e:
            raise ConfigError(f"config.json：{e}")
    if llm.get("timeout") not in (None, ""):
        value = llm["timeout"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 86400:
            raise ConfigError("config.json 的 llm.timeout 要是 0～86400 的秒數（0＝自動）。")
    return llm


def parse_harness_extras(llm: dict) -> dict:
    """小模型 harness 的設定（每個 kind 都收；沒寫＝不出現、照預設）：prompt_tail（auto｜on｜off，docs/adr/0017、0018）、
    max_tools（auto｜0｜1～200，docs/adr/0014）、
    context_size（0＝不裁；kind=local 另由 llm/local.py 檢查）與 tool_result_chars（auto｜0｜字數，docs/adr/0015、0016）；
    看圖的 vision（auto｜on｜off）、vision_model、vision_limits（docs/adr/0021）。寫錯＝ConfigError。"""
    from synox.agent import auto, context, toolpick
    from synox.llm.local import parse_context
    out = dict(llm)
    try:
        if "prompt_tail" in out:
            out["prompt_tail"] = auto.parse_switch(out["prompt_tail"], "prompt_tail")
        if "max_tools" in out:
            out["max_tools"] = toolpick.parse_max_tools(out["max_tools"])
        if "tool_result_chars" in out:
            out["tool_result_chars"] = context.parse_result_chars(out["tool_result_chars"])
        if "context_size" in out and out.get("kind") != "local":
            out["context_size"] = parse_context(out["context_size"])
        from synox.llm import vision                      # 看圖（docs/adr/0021）：沒寫＝不出現、照預設
        if "vision" in out:
            out["vision"] = vision.parse_mode(out["vision"])
        if "vision_model" in out:
            out["vision_model"] = vision.parse_side_model(out["vision_model"], out)
        if "vision_limits" in out:
            out["vision_limits"] = vision.parse_limits(out["vision_limits"])
    except ValueError as e:
        raise ConfigError(f"config.json：{e}")
    return out


def parse_presentation(value) -> dict:
    """config.json 的 presentation：沒寫＝{"enabled": false}；enabled 只收 true／false（寫錯就講清楚，不猜）。"""
    if value is None:
        return dict(DEFAULT_PRESENTATION)
    if not isinstance(value, dict):
        raise ConfigError('config.json 的 presentation 要是一個物件，例如 {"enabled": false}。')
    out = {**DEFAULT_PRESENTATION, **value}
    if not isinstance(out.get("enabled"), bool):
        raise ConfigError("config.json 的 presentation.enabled 只能是 true 或 false。")
    return out


MODE_LABELS = {"personal": "只有我（個人版）", "server": "一群人（伺服器版）"}


NOT_SECRET = {"max_tokens"}             # 名字裡有 token 但不是密鑰（寧可多遮，所以只列確定的）


def redacted(raw: dict) -> dict:
    """doctor 印設定用：拿掉 token、金鑰（只說有沒有）。"""
    out = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            out[key] = redacted(value)
        elif key.lower() not in NOT_SECRET and any(s in key.lower() for s in ("token", "key", "secret", "password")):
            out[key] = "（有填）" if value else "（空）"
        else:
            out[key] = value
    return out
