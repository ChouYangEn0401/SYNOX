"""
config.json 的 channels.discord → 一串 BotSpec（純函式，不連網；設定錯丟 ConfigError，訊息給人看）。

新寫法（多個 bot；名字只能小寫英數、- 和 _）：
    "channels": {"discord": {"bots": {
        "synox":  {"token": "vault:discord_bot_token:synox", "surface": "dm", "packs": "all", "ai": true},
        "lookup": {"token": "vault:discord_bot_token:lookup", "surface": "channel", "packs": ["dict"],
                   "max_effect": "read", "guilds": {...}, "trigger": "mention", "ai": {"enabled": true, "pool_usd_month": 5}}}}}
舊寫法（一個 bot）：{"enabled": true, "bot_token": "vault:discord_bot_token"} ＝ bots.default = {surface: dm, packs: all}。

- token：只收 "vault:<名字>" 或 "env:<名字>"（新寫法不准把 token 直接寫在檔案裡）；沒寫 → default 用
  vault:discord_bot_token，其他用 vault:discord_bot_token:<名字>（`python -m synox discord token --bot <名字>` 存的地方）。
- surface：dm（私訊，預設）｜channel（伺服器頻道，PERM-5：只收 guilds 列出的頻道、trigger 命中的訊息）。
- packs："all" 或 pack 名字清單；max_effect：read｜write｜danger（沒寫：dm 不設上限、channel 是 read；channel 設 danger 一律拒）。
  synox/policy.py 的 decide 用它們擋（PERM-4）：清單外的 pack 對這個 bot 不存在，超過 max_effect 的指令被拒。
- 頻道型才有的（PERM-5）：
    guilds：{"<伺服器 id>": {"channels": ["<頻道 id>", …], "role_map": {"<Discord 身分組 id>": "member"}}}
            role_map 的值只能是 guest 或 member（頻道裡的有效角色上限是 member；管理員只能用 /user_role 給）。
    trigger："mention"（被 @ 才處理，預設）｜"/"（訊息以 / 開頭才處理）。
    rate_per_minute：同一個人在同一個頻道每分鐘最多幾則（預設 5，超過的靜默略過）。
    room_rate_per_minute：同一個頻道（所有人加起來）每分鐘最多幾則（預設 20，PERM-6）。
- ai：true／false 或 {"enabled": …, "pool_usd_month": …}。關掉＝這個 bot 上沒有 AI（agent 群組不存在、打字不交給 AI）。
  私訊型沒寫＝開；pool_usd_month 對私訊型不用（照個人額度）。
- 頻道 AI（PERM-6，只有頻道型）：ai = {"enabled": true, "pool_usd_month": 5, "persona": "…",
  "history_turns": 6, "rate_per_minute": 2}。頻道型沒寫 ai＝關。pool_usd_month 是整個 bot 每月一池（美元，> 0）；
  enabled 是 true 卻沒有 pool＝設定錯誤，頻道 AI 不啟用（channel_ai_problem 說原因，doctor／/bot_status 列出來）。
  history_turns：頻道共用的對話記憶留幾輪（預設 6）；rate_per_minute：AI 每人每分鐘幾次（預設 2，比指令嚴）。
  persona：附加進公開頻道版系統提示的角色設定（沒寫就用 bot 的 persona 欄位）。
- 兩個 bot 不能用同一個 token（同一個 bot 開兩條 Gateway 會互搶事件）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from isdtelekit.host.config import ConfigError

DM, CHANNEL = "dm", "channel"
SURFACES = (DM, CHANNEL)
EFFECTS = ("read", "write", "danger")
DEFAULT = "default"
VAULT_BASE = "discord_bot_token"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
BOT_KEYS = {"token", "surface", "packs", "max_effect", "ai", "guilds", "trigger", "persona", "enabled",
            "rate_per_minute", "room_rate_per_minute"}
AI_KEYS = {"enabled", "pool_usd_month", "persona", "history_turns", "rate_per_minute"}
TRIGGERS = ("mention", "/")
ROLE_MAP_ROLES = ("guest", "member")             # 頻道裡 role_map 給得出的角色（上限 member）
DEFAULT_RATE = 5
DEFAULT_ROOM_RATE = 20                           # 頻道（所有人）每分鐘
DEFAULT_AI_RATE = 2                              # 頻道 AI：每人每分鐘
DEFAULT_AI_HISTORY = 6                           # 頻道 AI：共用記憶幾輪
ID_RE = re.compile(r"^[0-9]{1,25}$")


@dataclass(frozen=True)
class BotSpec:
    name: str
    token: str                                   # "vault:…" 或 "env:…"（舊寫法也可能是直接寫的 token）
    surface: str = DM
    packs: Union[str, Tuple[str, ...]] = "all"
    max_effect: Optional[str] = None             # None＝不設上限
    ai: dict = field(default_factory=lambda: {"enabled": True, "pool_usd_month": None})
    guilds: dict = field(default_factory=dict)
    trigger: str = "mention"
    persona: str = ""
    enabled: bool = True
    legacy: bool = False                         # 舊寫法來的（hub 名字維持 "discord"，狀態頁、指令照舊）
    rate_per_minute: int = DEFAULT_RATE          # 頻道型：（頻道, 人）每分鐘幾則
    room_rate_per_minute: int = DEFAULT_ROOM_RATE   # 頻道型：（頻道）每分鐘幾則

    @property
    def is_channel(self) -> bool:
        return self.surface == CHANNEL

    @property
    def ai_persona(self) -> str:
        return str(self.ai.get("persona") or self.persona or "").strip()

    @property
    def ai_history_turns(self) -> int:
        return int(self.ai.get("history_turns") or DEFAULT_AI_HISTORY)

    @property
    def ai_rate_per_minute(self) -> int:
        return int(self.ai.get("rate_per_minute") or DEFAULT_AI_RATE)

    @property
    def pool_usd_month(self) -> Optional[float]:
        return self.ai.get("pool_usd_month")

    def guild(self, guild_id) -> Optional[dict]:
        """這個伺服器的設定（{"channels": [...], "role_map": {...}}）；沒列＝None。"""
        g = self.guilds.get(str(guild_id or ""))
        return g if isinstance(g, dict) else None

    def allows(self, guild_id, channel_id) -> bool:
        g = self.guild(guild_id)
        return g is not None and str(channel_id or "") in g.get("channels", ())

    def channel_count(self) -> int:
        return sum(len(g.get("channels", ())) for g in self.guilds.values())

    def role_map_count(self) -> int:
        return sum(len(g.get("role_map", {})) for g in self.guilds.values())

    @property
    def hub_name(self) -> str:
        return "discord" if self.legacy else f"discord:{self.name}"

    @property
    def vault_name(self) -> Optional[str]:
        return self.token[len("vault:"):] if self.token.startswith("vault:") else None


def default_vault_name(name: str) -> str:
    return VAULT_BASE if name == DEFAULT else f"{VAULT_BASE}:{name}"


def _err(name: str, msg: str) -> ConfigError:
    return ConfigError(f"config.json 的 channels.discord.bots.{name}：{msg}")


def _packs(name: str, value) -> Union[str, Tuple[str, ...]]:
    if value is None or value == "all":
        return "all"
    if isinstance(value, list) and all(isinstance(p, str) and p.strip() for p in value):
        return tuple(p.strip() for p in value)
    raise _err(name, 'packs 要寫 "all" 或 pack 名字的清單（例如 ["dict", "weather"]）。')


def _small_int(name: str, where: str, value, default: int, top: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= top:
        raise _err(name, f"{where} 要是 1 到 {top} 的整數（現在是 {value!r}）。")
    return value


def _ai(name: str, value, channel: bool = False) -> dict:
    """頻道型沒寫 ai＝關（頻道 AI 要明講、而且要有 pool）；私訊型沒寫＝開。"""
    if value is None or isinstance(value, bool):
        return {"enabled": (not channel) if value is None else value, "pool_usd_month": None}
    if not isinstance(value, dict):
        raise _err(name, 'ai 要寫 true／false 或 {"enabled": true, "pool_usd_month": 5}。')
    unknown = sorted(set(value) - AI_KEYS)
    if unknown:
        raise _err(name, f"ai 裡不認得的欄位 {'、'.join(unknown)}（可以用：{'、'.join(sorted(AI_KEYS))}）。")
    pool = value.get("pool_usd_month")
    if pool is not None:
        if isinstance(pool, bool):
            raise _err(name, "ai.pool_usd_month 要是數字（美元）。")
        try:
            pool = float(pool)
        except (TypeError, ValueError):
            raise _err(name, "ai.pool_usd_month 要是數字（美元）。")
        if pool < 0:
            raise _err(name, "ai.pool_usd_month 不能是負的。")
    persona = value.get("persona") or ""
    if not isinstance(persona, str):
        raise _err(name, "ai.persona 要是文字。")
    return {"enabled": bool(value.get("enabled", True)), "pool_usd_month": pool, "persona": persona.strip(),
            "history_turns": _small_int(name, "ai.history_turns", value.get("history_turns"), DEFAULT_AI_HISTORY, 50),
            "rate_per_minute": _small_int(name, "ai.rate_per_minute", value.get("rate_per_minute"),
                                          DEFAULT_AI_RATE, 60)}


def channel_ai_problem(spec: BotSpec) -> str:
    """頻道型 bot 想開頻道 AI 但設定不對的原因（""＝沒問題，或根本沒想開）。有原因＝頻道 AI 不啟用。"""
    if spec.surface != CHANNEL or not spec.ai.get("enabled"):
        return ""
    pool = spec.pool_usd_month
    if pool is None:
        return ("ai.enabled 是 true 但沒有設 ai.pool_usd_month（整個 bot 每月的 AI 額度，美元），"
                "頻道 AI 不會啟用；例如 \"ai\": {\"enabled\": true, \"pool_usd_month\": 5}")
    if pool <= 0:
        return "ai.pool_usd_month 是 0，頻道 AI 不會啟用（要開請設大於 0 的美元數）"
    return ""


def channel_ai_on(spec: BotSpec) -> bool:
    """頻道型 bot 的頻道 AI 開著嗎：ai.enabled 而且有大於 0 的 pool。"""
    return spec.surface == CHANNEL and bool(spec.ai.get("enabled")) and not channel_ai_problem(spec)


def _ids(name: str, where: str, value) -> List[str]:
    if not isinstance(value, list) or not value:
        raise _err(name, f"{where} 要是至少一個頻道 id 的清單（例如 [\"123456789012345678\"]）。")
    out = []
    for v in value:
        s = str(v).strip() if isinstance(v, (str, int)) and not isinstance(v, bool) else ""
        if not ID_RE.match(s):
            raise _err(name, f"{where} 裡的 {v!r} 不是 Discord 的 id（一串數字；開發者模式下右鍵頻道「複製頻道 ID」）。")
        out.append(s)
    return out


def _guilds(name: str, raw) -> dict:
    """guilds → {伺服器 id: {"channels": (頻道 id…), "role_map": {身分組 id: "guest"|"member"}}}。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _err(name, 'guilds 要是 {"<伺服器 id>": {"channels": [...]}} 這樣的物件。')
    out = {}
    for gid, g in raw.items():
        gid = str(gid).strip()
        if not ID_RE.match(gid):
            raise _err(name, f"guilds 的 {gid!r} 不是 Discord 伺服器的 id（一串數字；右鍵伺服器圖示「複製伺服器 ID」）。")
        if not isinstance(g, dict):
            raise _err(name, f'guilds.{gid} 要寫成 {{"channels": ["<頻道 id>"]}}。')
        extra = sorted(set(g) - {"channels", "role_map"})
        if extra:
            raise _err(name, f"guilds.{gid} 不認得的欄位 {'、'.join(extra)}（只能有 channels、role_map）。")
        channels = _ids(name, f"guilds.{gid}.channels", g.get("channels"))
        role_map_raw = g.get("role_map") or {}
        if not isinstance(role_map_raw, dict):
            raise _err(name, f'guilds.{gid}.role_map 要寫成 {{"<身分組 id>": "member"}}。')
        role_map = {}
        for rid, role in role_map_raw.items():
            rid = str(rid).strip()
            if not ID_RE.match(rid):
                raise _err(name, f"guilds.{gid}.role_map 的 {rid!r} 不是 Discord 身分組的 id（伺服器設定 → 身分組 → 右鍵「複製身分組 ID」）。")
            r = str(role or "").strip().lower()
            if r not in ROLE_MAP_ROLES:
                raise _err(name, f"guilds.{gid}.role_map.{rid} 只能是 guest 或 member（現在是 {role!r}）："
                                 "頻道裡靠 Discord 身分組最多拿到 member；管理員只能用 /user_role 給。")
            role_map[rid] = r
        out[gid] = {"channels": channels, "role_map": role_map}
    return out


def _rate(name: str, value) -> int:
    if value is None:
        return DEFAULT_RATE
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 120:
        raise _err(name, f"rate_per_minute 要是 1 到 120 的整數（現在是 {value!r}）。")
    return value


def _one(name: str, raw) -> BotSpec:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ConfigError(f"config.json 的 channels.discord.bots 裡的名字 {name!r} 不行：只能用小寫英文、數字、- 和 _（最多 32 字）。")
    if not isinstance(raw, dict):
        raise _err(name, "要是一個 {…} 物件。")
    unknown = sorted(set(raw) - BOT_KEYS)
    if unknown:
        raise _err(name, f"不認得的欄位 {'、'.join(unknown)}（可以用：{'、'.join(sorted(BOT_KEYS))}）。")
    token = raw.get("token")
    if token in (None, ""):
        token = f"vault:{default_vault_name(name)}"
    if not isinstance(token, str) or not (token.startswith("vault:") or token.startswith("env:")) \
            or not token.split(":", 1)[1].strip():
        raise _err(name, 'token 只能寫保管箱的名字（"vault:discord_bot_token:<名字>"）或 "env:<環境變數>"，'
                         "不要把 token 直接寫進 config.json（用 python -m synox discord token --bot <名字> 存）。")
    surface = str(raw.get("surface") or DM).strip().lower()
    if surface not in SURFACES:
        raise _err(name, f"surface 只能是 dm（私訊）或 channel（伺服器頻道）（現在是 {raw.get('surface')!r}）。")
    max_effect = raw.get("max_effect")
    if max_effect is not None:
        max_effect = str(max_effect).strip().lower()
        if max_effect not in EFFECTS:
            raise _err(name, f"max_effect 只能是 read、write 或 danger（現在是 {raw.get('max_effect')!r}）。")
    if surface == CHANNEL:
        max_effect = max_effect or "read"
        if max_effect == "danger":
            raise _err(name, "頻道型 bot 的 max_effect 不能是 danger（危險動作只能在私訊做）；最多 write。")
    if surface != CHANNEL:
        for key in ("guilds", "trigger", "rate_per_minute", "room_rate_per_minute"):
            if raw.get(key):
                raise _err(name, f"{key} 只有 surface 是 channel 的 bot 才能寫。")
    guilds = _guilds(name, raw.get("guilds"))
    trigger = raw.get("trigger") or "mention"
    persona = raw.get("persona") or ""
    if not isinstance(trigger, str) or not isinstance(persona, str):
        raise _err(name, "trigger、persona 要是文字。")
    trigger = trigger.strip().lower()
    if trigger not in TRIGGERS:
        raise _err(name, f'trigger 只能是 "mention"（被 @ 才回）或 "/"（訊息以 / 開頭才回）（現在是 {raw.get("trigger")!r}）。')
    return BotSpec(name=name, token=token, surface=surface, packs=_packs(name, raw.get("packs")),
                   max_effect=max_effect, ai=_ai(name, raw.get("ai"), surface == CHANNEL), guilds=guilds,
                   trigger=trigger, persona=persona, enabled=bool(raw.get("enabled", True)),
                   rate_per_minute=_rate(name, raw.get("rate_per_minute")),
                   room_rate_per_minute=_small_int(name, "room_rate_per_minute", raw.get("room_rate_per_minute"),
                                                   DEFAULT_ROOM_RATE, 600))


def parse(d) -> List[BotSpec]:
    """channels.discord → BotSpec 清單（照 config 的順序；含 enabled=false 的）。沒寫 Discord → []。"""
    if not d:
        return []
    if not isinstance(d, dict):
        raise ConfigError("config.json 的 channels.discord 要是一個 {…} 物件。")
    if "bots" not in d:
        token = d.get("bot_token") or f"vault:{VAULT_BASE}"
        if not isinstance(token, str):
            raise ConfigError("config.json 的 channels.discord.bot_token 要是文字（例如 \"vault:discord_bot_token\"）。")
        return [BotSpec(name=DEFAULT, token=token, legacy=True)]
    if d.get("bot_token"):
        raise ConfigError("config.json 的 channels.discord 同時寫了 bot_token 和 bots：兩種寫法擇一"
                          "（多個 bot 時把 bot_token 搬進 bots.<名字>.token）。")
    bots = d.get("bots")
    if not isinstance(bots, dict) or not bots:
        raise ConfigError("config.json 的 channels.discord.bots 要是至少有一個 bot 的物件，例如 "
                          '{"synox": {"surface": "dm"}}。')
    specs = [_one(name, raw) for name, raw in bots.items()]
    seen = {}
    for s in specs:
        if s.token in seen:
            raise ConfigError(f"config.json 的 channels.discord.bots.{seen[s.token]} 和 {s.name} 用同一個 token（{s.token}）："
                              "一個 bot 只能有一條連線，每個 bot 要各自的 token。")
        seen[s.token] = s.name
    return specs


def active(d) -> List[BotSpec]:
    """要開的 bot（channels.discord.enabled 沒關、各自 enabled 沒關）。"""
    if not isinstance(d, dict) or not d:
        return []
    specs = parse(d)
    if specs and specs[0].legacy:
        return specs if bool(d.get("enabled", bool(d.get("bot_token")))) else []
    if not bool(d.get("enabled", True)):
        return []
    return [s for s in specs if s.enabled]


def find(specs: List[BotSpec], name: Optional[str]) -> Optional[BotSpec]:
    """依名字找；name 沒給 → default（舊寫法的那一個），沒有 default 就第一個私訊型。"""
    if name:
        return next((s for s in specs if s.name == name), None)
    return (next((s for s in specs if s.name == DEFAULT), None)
            or next((s for s in specs if s.surface == DM), None))
