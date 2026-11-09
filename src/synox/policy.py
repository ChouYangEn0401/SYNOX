"""
權限的唯一交會點（PERM-1）：decide(app, user, node, *, via, chat_id, bot=None)。

    允許 = SDK authorize（角色、owner_only、private_only、elevated、interactive）
         ∧ pack.capabilities ⊆ ceiling(role(user))        ← 這一版加的（擁有者不受限）
         ∧ node 所屬 pack ∈ bot.packs、effect ≤ bot.max_effect   ← PERM-4 才做（bot=None＝不限制）
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
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Dict, FrozenSet, Iterable, Optional

from isdtelekit.core.registry import AI, CommandRegistry, Decision, Node
from isdtelekit.users.roles import BasicRoles

ROLE_NAMES = tuple(r.name.lower() for r in sorted(set(BasicRoles)))          # guest、member、admin
OWNER_ONLY_CAPS = ("exec", "filesystem:any")                                  # 只有擁有者天生有
DEFAULT_ROLES: Dict[str, tuple] = {
    "guest": (),
    "member": ("network", "filesystem:own"),
    "admin": ("network", "filesystem:own", "subprocess"),
}
DEFAULT_SANDBOX = {"backend": "auto", "required_for": "third-party"}          # PERM-7 才用；這一版只保留預設值
HIDDEN_GROUPS = ("agent", "sudo")                                             # 不給 AI 當工具的內建群組


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
    return {"roles": roles, "sandbox": {**DEFAULT_SANDBOX, **sandbox_raw}}


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


def decide(app, user, node: Node, *, via: str, chat_id: Optional[int] = None, bot=None) -> Decision:
    """唯一的權限判斷。via＝SDK 的 TYPED／BUTTON／ROUTINE／SCHEDULE／AI。
    via=AI 另外：群組、interactive、ai=False、agent／sudo 群組、訪客（最低一級）一律不給（reason="ai"）。
    bot：PERM-4 才接（bot 的 pack 允許清單、max_effect）；現在只能是 None，給了別的一律拒（fail closed）。"""
    app = _as_app(app)
    registry = app.registry
    if bot is not None:
        return Decision(False, "bot")                 # PERM-4 之前沒有 bot 範圍可以算：不要當成不限制
    if via == AI:
        if node.is_group or node.interactive or not node.ai:
            return Decision(False, "ai")
        if node.path.split(".")[0] in HIDDEN_GROUPS:
            return Decision(False, "ai")
        if not registry.is_owner(user) and user.role <= registry.lowest_role:
            return Decision(False, "ai")              # 訪客沒有 AI 工具：伺服器版的 AI 從成員開始
    if not capability_ok(app, user, pack_of(app, node)):
        return Decision(False, "capability")
    return registry.authorize(user, node, via, chat_id)
