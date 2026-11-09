"""
權限的唯一交會點（PERM-1）：decide(app, user, node, *, via, chat_id, bot=None)。

    允許 = SDK authorize（角色、owner_only、private_only、elevated、interactive）
         ∧ pack.capabilities ⊆ ceiling(role(user))        ← 這一版加的（擁有者不受限）
         ∧ node 所屬 pack ∈ bot.packs、effect ≤ bot.max_effect   ← PERM-4（bot：收到這則訊息的 Discord bot）
         ∧ 頻道：surfaces／data                               ← PERM-2 才做

- **能力上限是「可見性」，不是攔 syscall**：角色的上限裝不下 pack 宣告的 capabilities → 那個 pack 對這個角色整組不存在
  （/help、選單、網頁、AI 工具清單都沒有；打了跟 owner_only 被拒一樣）。做法有兩層：
  1. loader 定義群組時用 `group_policy_for` 把群組的最低角色拉到「上限裝得下它的最低那一級」，裝不下任何角色＝owner_only
     ——所以 SDK 的 authorize／visible 自己就擋（人打字、按鈕、選單、網頁全部同一條）。
  2. decide 再對這個人的角色檢查一次（縱深：群組被別的地方先定義、或角色上限不是單調的時候也不會漏）。
- config.json（沒寫＝預設值）：
      "policy": {"roles": {"guest": {"capabilities": []},
                           "member": {"capabilities": ["network", "filesystem:own"]},
                           "admin": {"capabilities": ["network", "filesystem:own", "subprocess"]}}}
  `exec`、`filesystem:any` 不能寫進任何角色（parse_policy 丟 ConfigError，跟 pack.json 第 1 關一樣在讀設定時就拒），
  只有擁有者天生有。上限要往上只增不減（guest ⊆ member ⊆ admin），不然拒——群組的門檻是「角色 ≥ 某一級」。
- AI：`ai_decision`（agent/loop.py）就是 `decide(via=AI)`，AI 能不能用一個節點仍只有這一個判斷。
- **bot 範圍（PERM-4）**：`bot` 是 synox/discord/bots.py 的 BotSpec（packs、max_effect、ai）。沒有直接傳的話用
  「現在這則訊息是哪個 bot 收的」（`using_bot()` 設的 contextvar：DiscordEntry 收訊時設、AI 那一輪的執行緒帶過去）；
  兩個都沒有（Telegram、終端機、網頁、排程觸發）＝不限制。
  - pack 不在 bot.packs → 對這個 bot 不存在（reason "bot_pack"）；bot 的 ai 關掉 → agent 群組不存在（"bot_ai"）。
  - effect > bot.max_effect → 拒（"bot_effect"，會說這個 bot 的上限）。agent 群組不算（AI 能做什麼由工具清單管，
    工具清單本身就照這個 bot 的範圍過濾）。內建指令（/help、/start…）不受 packs 影響，但受 max_effect。
- **接到 SDK（install）**：dispatcher、/help、選單、按鈕、網頁全部呼叫 `registry.authorize`，所以 install(app) 把
  app.registry 的 authorize 換成 `authorize_for(app)`：先跑上面 SYNOX 自己的判斷，再跑原本的 SDK authorize。
  「對這個人不存在」的（bot 範圍外的 pack、角色能力上限裝不下的 pack）一律回 reason="owner_only"，
  SDK dispatcher 就回跟不存在的指令一模一樣的「未知指令」，不洩漏它存在；打群組名（/money）也一樣（_hidden_from）。
  SDK 本身不改（vendor/ 照舊）。
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from types import SimpleNamespace
from typing import Callable, Dict, FrozenSet, Iterable, Optional

from isdtelekit.core.registry import AI, DANGER, EFFECT_LABELS, READ, WRITE, CommandRegistry, Decision, Node
from isdtelekit.users.roles import BasicRoles

ROLE_NAMES = tuple(r.name.lower() for r in sorted(set(BasicRoles)))          # guest、member、admin
OWNER_ONLY_CAPS = ("exec", "filesystem:any")                                  # 只有擁有者天生有
DEFAULT_ROLES: Dict[str, tuple] = {
    "guest": (),
    "member": ("network", "filesystem:own"),
    "admin": ("network", "filesystem:own", "subprocess"),
}
DEFAULT_SANDBOX = {"backend": "auto", "required_for": "third-party"}          # 細節與其他預設值見 synox/sandbox.py
HIDDEN_GROUPS = ("agent", "sudo")                                             # 不給 AI 當工具的內建群組
AGENT_GROUP = "agent"
EFFECT_ORDER = (READ, WRITE, DANGER)
HIDDEN_REASONS = ("capability", "bot_pack", "bot_ai")                        # 對這個人／這個 bot 當作不存在
_SDK_AUTHORIZE = "_synox_sdk_authorize"

_current_bot: "contextvars.ContextVar[object]" = contextvars.ContextVar("synox_bot", default=None)


def _error(text: str) -> Exception:
    from isdtelekit.host.config import ConfigError
    return ConfigError(text)


def parse_policy(raw) -> dict:
    """config.json 的 policy → {"roles": {名字: frozenset(能力)}, "sandbox": {...}}。不合丟 ConfigError。"""
    from synox.packs.manifest import CAPABILITIES

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise _error("config.json 的 policy 要是一個 {…} 物件。")
    roles_raw = raw.get("roles") or {}
    if not isinstance(roles_raw, dict):
        raise _error("config.json 的 policy.roles 要是一個 {…} 物件（guest／member／admin）。")
    roles: Dict[str, FrozenSet[str]] = {name: frozenset(caps) for name, caps in DEFAULT_ROLES.items()}
    for name, entry in roles_raw.items():
        key = str(name).strip().lower()
        if key == "owner":
            raise _error("config.json 的 policy.roles 不能寫 owner：擁有者本來就什麼都有，不用設。")
        if key not in ROLE_NAMES:
            raise _error(f"config.json 的 policy.roles 不認得 {name!r}（只能是 {'、'.join(ROLE_NAMES)}）。")
        caps = entry.get("capabilities") if isinstance(entry, dict) else None
        if not isinstance(entry, dict) or not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
            raise _error(f"config.json 的 policy.roles.{key} 要寫成 {{\"capabilities\": [\"network\", …]}}。")
        bad = [c for c in caps if c not in CAPABILITIES]
        if bad:
            raise _error(f"config.json 的 policy.roles.{key} 不認得能力 {'、'.join(bad)}"
                         f"（只能是 {'、'.join(c for c in CAPABILITIES if c not in OWNER_ONLY_CAPS)}）。")
        banned = [c for c in caps if c in OWNER_ONLY_CAPS]
        if banned:
            raise _error(f"config.json 的 policy.roles.{key} 不能給 {'、'.join(banned)}："
                         f"這種能力只有擁有者有，不能開給任何角色。")
        roles[key] = frozenset(caps)
    for lower, higher in zip(ROLE_NAMES, ROLE_NAMES[1:]):
        missing = sorted(roles[lower] - roles[higher])
        if missing:
            raise _error(f"config.json 的 policy.roles：{lower} 有 {'、'.join(missing)}，{higher} 卻沒有"
                         f"（上限要一級比一級寬：guest ⊆ member ⊆ admin）。")
    sandbox_raw = raw.get("sandbox") or {}
    if not isinstance(sandbox_raw, dict):
        raise _error("config.json 的 policy.sandbox 要是一個 {…} 物件。")
    from synox.sandbox import parse_settings
    try:
        sandbox = parse_settings({**DEFAULT_SANDBOX, **sandbox_raw})
    except ValueError as e:
        raise _error(f"config.json 的 {e}")
    return {"roles": roles, "sandbox": sandbox}


def roles_of(config) -> Dict[str, FrozenSet[str]]:
    """設定裡的角色上限；config 沒有 policy（測試的假設定、舊物件）＝預設值。"""
    policy = getattr(config, "policy", None) if config is not None else None
    if isinstance(policy, dict) and isinstance(policy.get("roles"), dict):
        return policy["roles"]
    return {name: frozenset(caps) for name, caps in DEFAULT_ROLES.items()}


def _role_name(role) -> str:
    name = getattr(role, "name", None)
    if name is None:
        try:
            name = BasicRoles(int(role)).name
        except (TypeError, ValueError):
            return ""
    return str(name).lower()


def ceiling(config, role) -> FrozenSet[str]:
    """這個角色能用的能力。不認得的角色＝什麼都沒有（fail closed）。"""
    return roles_of(config).get(_role_name(role), frozenset())


def fits(capabilities: Iterable[str], allowed: FrozenSet[str]) -> bool:
    return all(c in allowed for c in capabilities or ())


def min_role_for(config, roles, capabilities) -> Optional[int]:
    """上限裝得下這些能力的最低一級；哪一級都裝不下（exec、filesystem:any、或設定沒開）回 None。"""
    for role in sorted(set(roles)):
        if fits(capabilities, ceiling(config, role)):
            return role
    return None


def group_policy_for(config, roles, capabilities, policy: dict) -> dict:
    """loader 的 group_policy（access 算出來的）再套能力上限：最低角色拉高，或整組 owner_only。只會更嚴。"""
    if policy.get("owner_only"):
        return policy
    need = min_role_for(config, roles, capabilities)
    if need is None:
        return {**policy, "owner_only": True}
    current = policy.get("role")
    return {**policy, "role": need if current is None else max(current, need)}


def _as_app(app):
    """測試與舊呼叫端直接給 CommandRegistry：包成沒有 pack、預設上限的 app。"""
    if isinstance(app, CommandRegistry):
        return SimpleNamespace(registry=app, extras={}, config=None)
    return app


def config_of(app):
    extras = getattr(app, "extras", None) or {}
    return extras.get("synox_config") or getattr(app, "config", None)


def pack_of(app, node: Node):
    """這個節點屬於哪一個 pack（看最上層的群組）；內建指令回 None。"""
    top = node.path.split(".")[0] if node is not None else ""
    for pack in (getattr(app, "extras", None) or {}).get("synox_packs", []):
        if pack.manifest.group.split(".")[0] == top:
            return pack
    return None


def capability_ok(app, user, pack) -> bool:
    """這個人的角色上限裝得下這個 pack 的 capabilities 嗎（擁有者永遠可以）。"""
    if pack is None or app.registry.is_owner(user):
        return True
    return fits(pack.manifest.capabilities, ceiling(config_of(app), user.role))


# ── bot 範圍（PERM-4）────────────────────────────────────────────────

def current_bot():
    """現在這則訊息是哪個 bot 收的（沒有＝None：Telegram、終端機、網頁、排程觸發）。"""
    return _current_bot.get()


@contextlib.contextmanager
def using_bot(bot):
    """這段程式裡的權限判斷都照這個 bot 的範圍算（DiscordEntry 收訊時用）。"""
    token = _current_bot.set(bot)
    try:
        yield bot
    finally:
        _current_bot.reset(token)


def run_as(bot, fn: Callable, *args, **kw):
    """在別的執行緒跑 fn 時把 bot 帶過去（contextvar 不會自己跟到新執行緒；AI 那一輪用）。"""
    with using_bot(bot):
        return fn(*args, **kw)


def effect_rank(effect) -> int:
    e = str(effect or READ).strip().lower()
    return EFFECT_ORDER.index(e) if e in EFFECT_ORDER else len(EFFECT_ORDER)      # 不認得＝比危險還高（fail closed）


def bot_packs(bot):
    """"all" 或 pack 名字的 tuple。"""
    packs = getattr(bot, "packs", "all")
    return "all" if packs in (None, "all") else tuple(packs)


def pack_listed(bot, pack_name: str) -> bool:
    packs = bot_packs(bot)
    return packs == "all" or pack_name in packs


def effect_ok(bot, effect) -> bool:
    cap = getattr(bot, "max_effect", None)
    return cap is None or effect_rank(effect) <= effect_rank(cap)


def bot_ai_enabled(bot) -> bool:
    ai = getattr(bot, "ai", None)
    return bool(ai.get("enabled", True)) if isinstance(ai, dict) else (ai is None or bool(ai))


def effect_label(effect) -> str:
    return EFFECT_LABELS.get(str(effect or READ).strip().lower(), str(effect))


def bot_refusal(bot, node: Node) -> str:
    cap = getattr(bot, "max_effect", None)
    return (f"🔒 這個 bot 只開放「{effect_label(cap)}」以內的指令，{node.command} 是「{effect_label(node.effect)}」；"
            "要做這件事請改用其他 bot。")


def bot_scope(app, node: Node, bot) -> Optional[Decision]:
    """bot 範圍擋下來就回 Decision；放行回 None。bot=None＝不限制。"""
    if bot is None or node is None:
        return None
    if node.path.split(".")[0] == AGENT_GROUP:
        return None if bot_ai_enabled(bot) else Decision(False, "bot_ai")
    pack = pack_of(app, node)
    if pack is not None and not pack_listed(bot, pack.name):
        return Decision(False, "bot_pack")
    if not node.is_group and not effect_ok(bot, node.effect):
        return Decision(False, "bot_effect", bot_refusal(bot, node))
    return None


def hidden(app, user, node: Node, bot=None) -> bool:
    """這個節點（或整個群組）對這個人、在這個 bot 上當作不存在嗎（bot 範圍外的 pack、AI 關掉的 bot 上的 agent、
    角色能力上限裝不下的 pack）。bot 沒給＝current_bot()。"""
    app = _as_app(app)
    blocked = bot_scope(app, node, current_bot() if bot is None else bot)
    if blocked is not None and blocked.reason in HIDDEN_REASONS:
        return True
    return not capability_ok(app, user, pack_of(app, node))


def _sdk_authorize(registry):
    """原本的 SDK authorize（install 換掉 registry.authorize 之前那一個）。"""
    return getattr(registry, _SDK_AUTHORIZE, None) or registry.authorize


def decide(app, user, node: Node, *, via: str, chat_id: Optional[int] = None, bot=None) -> Decision:
    """唯一的權限判斷。via＝SDK 的 TYPED／BUTTON／ROUTINE／SCHEDULE／AI。
    via=AI 另外：群組、interactive、ai=False、agent／sudo 群組、訪客（最低一級）一律不給（reason="ai"）。
    bot：BotSpec（packs、max_effect、ai）；沒給＝current_bot()（這則訊息是哪個 bot 收的），也沒有＝不限制。
    reason 除了 SDK 的那幾個，還有 "capability"、"bot_pack"、"bot_ai"（這三個＝當作不存在）與 "bot_effect"。"""
    app = _as_app(app)
    registry = app.registry
    bot = current_bot() if bot is None else bot
    if via == AI:
        if node.is_group or node.interactive or not node.ai:
            return Decision(False, "ai")
        if node.path.split(".")[0] in HIDDEN_GROUPS:
            return Decision(False, "ai")
        if not registry.is_owner(user) and user.role <= registry.lowest_role:
            return Decision(False, "ai")              # 訪客沒有 AI 工具：伺服器版的 AI 從成員開始
    blocked = bot_scope(app, node, bot)
    if blocked is not None:
        return blocked
    if not capability_ok(app, user, pack_of(app, node)):
        return Decision(False, "capability")
    return _sdk_authorize(registry)(user, node, via, chat_id)


def authorize_for(app):
    """給 SDK 用的 authorize（跟 registry.authorize 同簽名）：decide 的結果，「當作不存在」的換成 owner_only，
    SDK dispatcher 就回「未知指令」（跟真的沒有這個指令一模一樣），/help、visible 也看不到。真正的原因只進 debug log。"""

    def authorize(user, node, via, chat_id=None):
        d = decide(app, user, node, via=via, chat_id=chat_id)
        if not d.allowed and d.reason in HIDDEN_REASONS:
            logging.debug("[POLICY] %s hidden from %s (%s)", node.path, getattr(user, "tg_id", "?"), d.reason)
            return Decision(False, "owner_only")
        return d
    return authorize


def install(app) -> None:
    """把 SYNOX 的判斷接到 SDK（SDK 本身不改）：registry.authorize（打字、按鈕、/help、選單、網頁、排程建立都走它）
    與 dispatcher 的群組隱形判斷（打群組名）。重複呼叫不會包兩層。"""
    registry = app.registry
    if getattr(registry, _SDK_AUTHORIZE, None) is None:
        setattr(registry, _SDK_AUTHORIZE, registry.authorize)
        registry.authorize = authorize_for(app)
    dispatcher = getattr(app, "dispatcher", None)
    if dispatcher is not None and not getattr(dispatcher, "_synox_hidden", False):
        original = dispatcher._hidden_from
        dispatcher._hidden_from = lambda user, node: original(user, node) or hidden(app, user, node)
        dispatcher._synox_hidden = True
