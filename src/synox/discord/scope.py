"""
bot 範圍報告（PERM-4）：每個 Discord bot 實際會出現哪些 pack，「設定了但不會出現」的又是為什麼。
/bot_status（管理員以上；個人版＝擁有者）和 `python -m synox doctor` 都用這裡（純函式，不連網）。

    infos = from_app(app)          # 已載入的 pack 與各指令的 effect（/bot_status）
    infos = from_manifests(config) # 只讀 pack.json（doctor；python pack 的指令要載入後才知道 effect）
    rep = report(spec, infos)      # {"effective": [(名字, 備註)], "hidden": [(名字, 原因)], "not_opened": [名字]}
    lines(spec, rep)               # 給人看的幾行

原因是一串可以加的檢查（REASONS：(spec, info) → 原因或 None，第一個說話的算）：
pack 清單（沒載入／不是指令型）、頻道型 bot 的 surfaces／data（PERM-5：surfaces 沒有 channel、data=user 不進頻道）、
max_effect（指令全部超過上限；頻道型另外 DANGER 永遠不行、WRITE 只限 data=shared）。
這裡只算「bot」這一層；每個人實際看得到什麼還要再看他的角色（/help 看自己的）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from synox import policy
from synox.discord.bots import CHANNEL, BotSpec, channel_ai_problem


@dataclass(frozen=True)
class PackInfo:
    name: str
    effects: Optional[Tuple[str, ...]] = None    # 每個指令的 effect（小寫）；None＝還不知道（doctor 看 python pack）
    loaded: bool = True                          # False：有裝但這次不會載入（停用、太舊、環境沒建好…）
    problem: str = ""                            # loaded=False 的原因
    surfaces: Tuple[str, ...] = ("dm",)          # pack.json 的 surfaces（PERM-2）
    data: str = "none"                           # pack.json 的 data（none｜user｜shared）


def _decl(m) -> dict:
    return {"surfaces": tuple(getattr(m, "surfaces", None) or ("dm",)), "data": getattr(m, "data", "none") or "none"}


def from_app(app) -> Dict[str, PackInfo]:
    registry = app.registry
    out: Dict[str, PackInfo] = {}
    for pack in app.extras.get("synox_packs", []):
        group = registry.node(pack.manifest.group) if pack.manifest.group else None
        effects = tuple(n.effect.lower() for n in group.walk() if not n.is_group) if group is not None else ()
        out[pack.name] = PackInfo(pack.name, effects, **_decl(pack.manifest))
    return out


def _manifest_effects(m) -> Optional[Tuple[str, ...]]:
    if m.kind == "cli":
        return tuple((c.get("effect") or "READ").lower() for c in m.commands)
    if m.kind == "mcp":
        return tuple((e or "READ").lower() for e in (m.mcp.get("effects") or {}).values())
    return None                                   # python：指令在程式裡掛，要載入後才知道


def from_manifests(config) -> Dict[str, PackInfo]:
    """doctor 用：只讀 pack.json，不載入程式。"""
    from synox.packs.loader import PACK_DIRS, discover
    from synox.packs.manifest import ManifestError, read, synox_problem
    out: Dict[str, PackInfo] = {}
    dirs = config.pack_dirs() if hasattr(config, "pack_dirs") else PACK_DIRS
    for folder in discover(dirs):
        try:
            m = read(folder)
        except ManifestError:
            continue
        if not config.pack_enabled(m.name):
            out[m.name] = PackInfo(m.name, loaded=False, problem="config.json 的 packs 把它停用了", **_decl(m))
            continue
        too_old = synox_problem(m)
        if too_old:
            out[m.name] = PackInfo(m.name, loaded=False, problem=too_old, **_decl(m))
            continue
        out[m.name] = PackInfo(m.name, _manifest_effects(m), **_decl(m))
    return out


def _effect_ok(spec: BotSpec, effect: str, info: Optional[PackInfo]) -> bool:
    """這個 bot 上這個 effect 的指令會不會出現（頻道型另看 DANGER／WRITE 的頻道規則）。"""
    if policy.is_channel_bot(spec):
        return policy.channel_effect_ok(spec, effect, info.data if info is not None else "none")
    return policy.effect_ok(spec, effect)


# ── 不會出現的原因（依序檢查，第一個說話的算）────────────────────────

def _not_loaded(spec: BotSpec, name: str, info: Optional[PackInfo]) -> Optional[str]:
    if info is None:
        return "沒有載入（沒裝、名字打錯、或載入失敗；python -m synox doctor 看）"
    if not info.loaded:
        return f"不會載入：{info.problem}"
    return None


def _no_commands(spec: BotSpec, name: str, info: Optional[PackInfo]) -> Optional[str]:
    if info is not None and info.effects is not None and not info.effects:
        return "沒有任何指令（connector 只登記，給別的 pack 用）"
    return None


def _not_for_channel(spec: BotSpec, name: str, info: Optional[PackInfo]) -> Optional[str]:
    """頻道型 bot（PERM-5）：pack.json 的 surfaces 沒有 channel、或 data=user → 頻道裡不存在。"""
    if info is None or not policy.is_channel_bot(spec):
        return None
    if "channel" not in info.surfaces:
        return 'pack.json 的 surfaces 沒有 "channel"（只能私訊用），頻道裡不會出現'
    if info.data == "user":
        return "資料是每個人自己的（data=user），不進頻道"
    return None


def _over_max_effect(spec: BotSpec, name: str, info: Optional[PackInfo]) -> Optional[str]:
    if info is None or not info.effects or spec.max_effect is None:
        return None
    if any(_effect_ok(spec, e, info) for e in info.effects):
        return None
    worst = min(info.effects, key=policy.effect_rank)
    if policy.is_channel_bot(spec) and policy.effect_ok(spec, worst):
        return (f"指令都會改資料（最低也是「{policy.effect_label(worst)}」），頻道裡只有 data=shared 的 pack 能寫、"
                "危險動作一律要到私訊")
    return (f"指令全部超過這個 bot 的上限「{policy.effect_label(spec.max_effect)}」"
            f"（最低也是「{policy.effect_label(worst)}」）")


REASONS: List[Callable[[BotSpec, str, Optional[PackInfo]], Optional[str]]] = [
    _not_loaded, _no_commands, _not_for_channel, _over_max_effect,
]


def report(spec: BotSpec, infos: Dict[str, PackInfo]) -> dict:
    listed = policy.bot_packs(spec)
    names = list(infos) if listed == "all" else list(listed)
    effective: List[Tuple[str, str]] = []
    hidden: List[Tuple[str, str]] = []
    for name in names:
        info = infos.get(name)
        reason = next((r for r in (check(spec, name, info) for check in REASONS) if r), None)
        if reason:
            hidden.append((name, reason))
            continue
        note = ""
        if info is not None and info.effects is None and spec.max_effect is not None:
            note = "指令的效果要載入後才知道（/bot_status 看）"
        elif info is not None and info.effects:
            over = sum(1 for e in info.effects if not _effect_ok(spec, e, info))
            if over and policy.is_channel_bot(spec):
                note = f"{over} 個指令在頻道裡不會出現（超過上限「{policy.effect_label(spec.max_effect)}」或要到私訊做）"
            elif over:
                note = f"{over} 個指令超過上限「{policy.effect_label(spec.max_effect)}」，不會出現"
        effective.append((name, note))
    not_opened = [] if listed == "all" else [n for n in infos if n not in listed]
    return {"effective": effective, "hidden": hidden, "not_opened": not_opened}


def head(spec: BotSpec) -> str:
    where = "頻道型" if spec.surface == CHANNEL else "私訊型"
    cap = f"上限「{policy.effect_label(spec.max_effect)}」" if spec.max_effect else "不設上限"
    packs = "全部 pack" if policy.bot_packs(spec) == "all" else "pack 清單"
    return f"bot {spec.name}（{where}，{packs}，{cap}，{ai_word(spec)}）"


def ai_word(spec: BotSpec) -> str:
    if spec.surface != CHANNEL:
        return "AI 開" if policy.bot_ai_enabled(spec) else "AI 關"
    if policy.channel_ai_enabled(spec):
        return f"頻道 AI 開（整個 bot 每月 US${spec.pool_usd_month:.2f}）"
    return "頻道 AI 設定錯誤" if channel_ai_problem(spec) else "AI 關"


def channel_line(spec: BotSpec) -> str:
    """頻道型 bot 的收訊設定（不含 token）。"""
    trigger = "被 @ 才回" if spec.trigger == "mention" else "訊息以 / 開頭才回"
    line = (f"{len(spec.guilds)} 個伺服器、{spec.channel_count()} 個頻道；觸發：{trigger}；"
            f"role_map {spec.role_map_count()} 筆（最多給到成員）；每人每頻道每分鐘 {spec.rate_per_minute} 則、"
            f"每頻道每分鐘 {spec.room_rate_per_minute} 則")
    if policy.channel_ai_enabled(spec):
        line += f"；頻道 AI 每人每分鐘 {spec.ai_rate_per_minute} 次、共用記憶 {spec.ai_history_turns} 輪"
    return line


def lines(spec: BotSpec, rep: dict, indent: str = "  ") -> List[str]:
    out = []
    if spec.surface == CHANNEL:
        out.append(f"{indent}收訊：{channel_line(spec)}")
        problem = channel_ai_problem(spec)
        if problem:
            out.append(f"{indent}❌ 頻道 AI 沒有開：{problem}")
    eff = rep["effective"]
    shown = "、".join(n + (f"（{note}）" if note else "") for n, note in eff) if eff else "（沒有）"
    out.append(f"{indent}會出現：{shown}")
    if rep["hidden"]:
        out.append(f"{indent}設定了但不會出現：")
        out += [f"{indent}  • {n}：{why}" for n, why in rep["hidden"]]
    if rep["not_opened"]:
        out.append(f"{indent}沒開給這個 bot：{'、'.join(rep['not_opened'])}")
    return out


def status_text(app, config) -> str:
    from synox import discord
    specs = discord.all_specs(config)
    if not specs:
        return "config.json 沒有設定 Discord bot（channels.discord）。看 docs/discord.md。"
    infos = from_app(app)
    errors = app.extras.get("discord_errors") or {}
    running = app.extras.get("discord_entries") or {}
    active = {s.name for s in discord.specs(config)}
    out = ["🤖 Discord bot 的範圍（只算 bot 這一層；每個人還要看自己的角色，/help 看自己能用的）"]
    for spec in specs:
        state = ("✅ 收訊中" if spec.name in running else
                 f"⚠️ {errors[spec.name]}" if spec.name in errors else
                 "⏸ 關著（enabled=false）" if spec.name not in active else "⚠️ 沒有開成")
        out += ["", f"{head(spec)}：{state}"] + lines(spec, report(spec, infos))
        agent = (app.extras.get("discord_room_ai") or {}).get(spec.name)
        if agent is not None:                       # PERM-6：bot 一池的用量
            out.append(f"  {agent.pool.line()}")
    notes = list(app.extras.get("discord_identity_notes") or [])
    identities = app.extras.get("identities")
    problem = discord.owner_problem(config, identities) if identities is not None else ""
    if problem:                                     # 即時算（開著的時候跑了 discord pair 也對）
        notes.insert(0, problem)
    if notes:
        out += ["", "身分："] + [f"  ⚠️ {n}" for n in notes]
    return "\n".join(out)


def install(app, config) -> None:
    """有設定 Discord 才掛 /bot_status：伺服器版管理員以上，個人版只有擁有者。"""
    from synox import discord
    if not discord.all_specs(config) or app.registry.node("bot_status") is not None:
        return
    server = getattr(config, "mode", "personal") == "server"

    def cmd(api, chat_id, user, args):
        api.send_message(chat_id, status_text(app, config))

    app.registry.root_leaf("bot_status", cmd, "每個 Discord bot 開了哪些 pack、哪些設定了卻不會出現",
                           role=app.users.top_role, owner_only=not server, ai=False)
