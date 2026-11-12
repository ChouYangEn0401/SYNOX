"""
SYNOX 的設定：SDK 的 BotConfig 欄位（bot_token、owner_id、data_dir、時效…）＋ SYNOX 自己多的幾塊。

    {
      "mode": "personal",                      personal（只有我，預設）｜server（一群人：帳號、角色、每人自己的資料）
      "bot_token": "123456:AAH…", "owner_id": 123456789,
      "llm":   {"kind": "openai_compat", "base_url": "https://…/v1", "api_key": "vault:llm_api_key",
                "model": "…", "tools": true, "max_steps": 6, "max_tokens": 1024},
      "vault": {"mode": "dpapi"},              dpapi（Windows 預設）｜file（金鑰明文存在 data/.synox.key）
      "packs": {"enabled": "all", "disabled": [], "dirs": [], "library": ""},   library：工具庫（SYNOX_Libs）在哪
                                               （資料夾或網址；只拿來提示「去哪裡裝」，packs/library.py）
      "web":   {"enabled": true, "port": 8830, "public_url": ""},   本機網頁介面（只綁 127.0.0.1）
      "ai_member_monthly_usd": 2.0,            伺服器版：每個成員每月的 AI 額度（美元）
      "channels": {"discord": {"enabled": true, "bot_token": "vault:discord_bot_token"}},  Discord 私訊（docs/discord.md）
      "policy": {"roles": {"member": {"capabilities": ["network", "filesystem:own"]}, …}}  角色能力上限（synox/policy.py；
                                               沒寫＝預設；exec、filesystem:any 不能給任何角色）
      "runtime": {"heartbeat": {"enabled": true, "interval_min": 45, …}, "mother": {…}}   常駐助理與心跳
                                               （synox/runtime/settings.py；docs/adr/0001）
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

from synox.policy import parse_policy
from synox.runtime import settings as runtime_settings

ROOT = os.environ.get("SYNOX_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(ROOT, "config.json")

LLM_KINDS = ("openai", "anthropic", "gemini", "openai_compat", "claude_code", "fake", "none")
DEFAULT_LLM = {"kind": "none", "max_steps": 6, "max_tokens": 1024}
DEFAULT_VAULT = {"mode": "dpapi" if os.name == "nt" else "file"}
DEFAULT_PACKS = {"enabled": "all", "disabled": []}
DEFAULT_WEB = {"enabled": True, "port": 8830, "public_url": ""}
DEFAULT_MEMBER_USD = 2.0
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
        try:
            member_usd = float(raw.get("ai_member_monthly_usd", DEFAULT_MEMBER_USD))
        except (TypeError, ValueError):
            raise ConfigError("config.json 的 ai_member_monthly_usd 要是數字（美元，例如 2.0）。")
        policy = parse_policy(raw.get("policy"))      # exec／filesystem:any 寫進任何角色＝拒（第 1 關式檢查）
        try:
            runtime = runtime_settings.parse(raw.get("runtime"))
        except runtime_settings.RuntimeConfigError as e:
            raise ConfigError(f"config.json：{e}")
        return cls(bot_token=base.bot_token, owner_id=base.owner_id,
                   poll_interval_seconds=base.poll_interval_seconds, data_dir=data_dir,
                   stepup_minutes=base.stepup_minutes, raw=dict(raw), llm=llm, vault=vault, packs=packs, mode=mode,
                   root=root, web=web, ai_member_monthly_usd=max(0.0, member_usd), policy=policy,
                   runtime=runtime)

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


MODE_LABELS = {"personal": "只有我（個人版）", "server": "一群人（伺服器版）"}


def redacted(raw: dict) -> dict:
    """doctor 印設定用：拿掉 token、金鑰（只說有沒有）。"""
    out = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            out[key] = redacted(value)
        elif any(s in key.lower() for s in ("token", "key", "secret", "password")):
            out[key] = "（有填）" if value else "（空）"
        else:
            out[key] = value
    return out
