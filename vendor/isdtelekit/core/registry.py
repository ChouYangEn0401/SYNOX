"""
指令樹與唯一的權限檢查點。

每個指令是樹上的一個葉節點（例如 shop.status），群組是中間節點（shop）。樹的形狀（群組與權限下限）
在 bot 自己的 layout 裡一次定義好；各功能模組只負責把葉節點掛到對應的群組下：

    registry = CommandRegistry(owner_id=123, roles=Role)
    registry.define_group("remind", "📒 筆記", "隨手記、查、刪", role=Role.USER)
    g = registry.group("remind")
    g.leaf("add", add_note, "記一筆", default=True, usage="<內容>", effect=WRITE)   # /remind
    g.leaf("list", list_notes, "列出筆記")                                          # /remind_list

權限（Policy）沿著樹往下只能收緊、不能放寬：
  role          最低角色（角色階梯是建構參數，見 users/roles.py）
  owner_only    只有機器擁有者：會動到擁有者的電腦、錢、或別人資料的東西
  private_only  只能在私訊用（輸出含網址、密碼、IP 之類）
  elevated      要先 /sudo（手機驗證器）解鎖：Telegram 帳號被盜時的第二道門，見 security/stepup.py
葉節點的有效權限 = 自己與所有祖先取最嚴。機器擁有者略過 role（被降級測試時仍能用擁有者指令），
但不略過 private_only。

另外每個葉節點宣告：
  effect        read（只看）/ write（改 bot 裡的資料）/ danger（對外、不可逆、或影響別人）
  interactive   會開多輪對話；不能排程、不給 AI 呼叫
  usage         參數說明，給 /help、排程檢查和 AI 用
  fields        表單指令的欄位（core/forms.py）
  ai            False：不給 AI 當工具（給之後接 AI 工具橋用；放寬安全的開關只給人按）

指令名不是自己取的，是從路徑產生的（Node.command）：
  remind.list → /remind_list      群組名_葉節點名，看名字就知道在哪一組、要什麼權限
  remind.add（default=True）→ /remind   一個群組最多一個主要動作，直接用群組名
  help（根下）→ /help              bare 群組底下（custom.hello）→ /hello
改名前的舊名稱放在 legacy，照樣能打、能排程；參數形狀變了的舊名稱用 registry.legacy() 帶改寫函式。
名稱一律符合 Telegram 的規則（小寫英數字與底線、最多 32 字），不合就在啟動時報錯。

所有入口——打字、按鈕、排程、AI——都經過 authorize()。按鈕要綁在某個節點上
（bind_callback），按鈕的權限就是那個節點的權限。handler 裡不要再檢查權限。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from isdtelekit.core.channel import CallbackInfo  # noqa: F401  按鈕 handler 的參數型別，從這裡匯出
from isdtelekit.users.roles import BasicRoles

READ, WRITE, DANGER = "read", "write", "danger"
EFFECT_LABELS = {READ: "唯讀", WRITE: "寫入", DANGER: "危險"}

# 誰在呼叫：typed（使用者打字）/ button / routine（排程觸發）/ schedule（建立排程時）/ ai
TYPED, BUTTON, ROUTINE, SCHEDULE, AI = "typed", "button", "routine", "schedule", "ai"

REFUSED = "❌ 你沒有執行此指令的權限。"
PRIVATE_ONLY = "🔒 這個指令只能在跟 bot 的私訊裡用。"
# 🔐 被擋下時的話由 stepup 物件提供（security/stepup.py 的 StepUp.need_message／unset_message，
# 會說怎麼解鎖、怎麼設定）；沒接 stepup 的 bot 才用這兩句。registry 不 import 驗證器。
STEPUP_NEEDED = "🔐 這個指令要先解鎖。"
STEPUP_UNSET = "🔐 這個指令要先解鎖，但這裡還沒有設定驗證器，所以一律拒絕。"

# Telegram 的指令名規則：1–32 個小寫英文字母、數字或底線
COMMAND_RE = re.compile(r"^/[a-z0-9_]{1,32}$")

# 舊名稱的參數改寫：old args → new args（例：/deluser 123 → /user_role 123 guest）
Rewrite = Callable[[List[str]], List[str]]


@dataclass(frozen=True)
class Policy:
    role: int = 0
    owner_only: bool = False
    private_only: bool = False
    elevated: bool = False

    def tighten(self, other: "Policy") -> "Policy":
        return Policy(max(self.role, other.role),
                      self.owner_only or other.owner_only,
                      self.private_only or other.private_only,
                      self.elevated or other.elevated)


@dataclass(frozen=True)
class Field:
    """表單指令的一個欄位（見 core/forms.py）。ask 是問人的那句話，也是 AI 看到的欄位說明。"""
    name: str
    ask: str
    required: bool = False
    choices: Tuple[str, ...] = ()
    default: str = ""
    check: Optional[Callable[[str], Optional[str]]] = field(default=None, compare=False)  # 回錯誤訊息或 None
    # 「手機驗證器上現在的 6 位數」這種：問答時永遠最後問、收到就驗就送出，等的時間只有 code_prompt 秒
    # （碼大約 1 分鐘就失效，先存起來、最後才驗，等於一定失敗；core/timing.py）
    fresh_code: bool = False
    factor: str = "A"             # 驗哪一組驗證器（security/stepup.py：A＝平常那支，B＝第二組）
    # 只有某些情況才要的驗證碼欄位（例如風險高才要第二組）：needed(values) 回 True 才算必填。
    # values 是其他欄位填完、補上預設值之後的樣子；問答時在問驗證碼之前才判斷。
    needed: Optional[Callable[[Dict[str, str]], bool]] = field(default=None, compare=False)


def codes_needed(fields: Sequence[Field], values: Dict[str, str]) -> List[Field]:
    """這次要哪幾個驗證碼欄位（required 的，加上 needed(values) 說要的）。"""
    filled = {f.name: f.default for f in fields if f.default}
    filled.update(values)
    out = []
    for f in fields:
        if not f.fresh_code:
            continue
        if f.required:
            out.append(f)
        elif f.needed is not None:
            try:
                if f.needed(filled):
                    out.append(f)
            except Exception:
                out.append(f)              # 判斷出錯就當作要（fail closed）
    return out


def field_pattern(fields: Sequence[Field]) -> "re.Pattern":
    names = "|".join(sorted((re.escape(f.name) for f in fields), key=len, reverse=True))
    return re.compile(rf"(?:^|(?<=\s))({names})=", re.IGNORECASE)


def parse_fields(fields: Sequence[Field], text: str) -> Tuple[Dict[str, str], List[Field], List[str]]:
    """'https://x title=教學 影片 category=剪輯' → ({url, title, category}, 缺的必填, 錯誤)。

    第一個 key= 之前的文字給第一個欄位（所以 /clip <網址> 照舊）；值可以有空白和換行，
    一直到下一個認得的 key=。「每行 key=value」也是同一種格式。"""
    values: Dict[str, str] = {}
    if fields:
        pattern = field_pattern(fields)
        marks = list(pattern.finditer(text))
        head = text[:marks[0].start()] if marks else text
        if head.strip():
            values[fields[0].name] = head.strip()
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            values[m.group(1).lower()] = text[m.end():end].strip()
    errors = []
    for f in fields:
        value = values.get(f.name, "")
        if not value:
            values.pop(f.name, None)
            continue
        if f.choices and value.lower() not in f.choices:
            errors.append(f"{f.name} 只能是 {'/'.join(f.choices)}")
        elif f.check and f.check(value):
            errors.append(f"{f.name}：{f.check(value)}")
    missing = [f for f in fields if f.required and f.name not in values]
    return values, missing, errors


@dataclass
class Node:
    name: str
    title: str
    summary: str = ""
    fn: Optional[Callable] = None
    own: Policy = field(default_factory=Policy)
    effect: str = READ
    interactive: bool = False
    usage: str = ""
    default: bool = False         # 群組的主要動作：打 /<群組> 就是它
    legacy: Tuple[str, ...] = ()  # 改名前的名稱，照樣能用
    quota_exempt: bool = False    # 超過每日訊息上限時仍放行（申請解除配額用）
    bare: bool = False            # 群組：底下的葉節點直接用自己的名字（custom.hello → /hello）
    fields: Tuple[Field, ...] = ()  # 表單指令的欄位（core/forms.py）；AI 看到的是具名參數
    # 送出（或開核准卡）之前的檢查：precheck(values, via_ai, channel) 回錯誤訊息或 None。
    # 在問驗證碼之前跑，免得碼打了才說不行（core/forms.py）。
    precheck: Optional[Callable[[Dict[str, str], bool, str], Optional[str]]] = field(default=None, repr=False)
    ai: bool = True               # False：不給 AI 當工具
    # 之後會替你執行另一個指令的節點（例如排程）：wraps(args) 回 (那個指令的節點, 它的參數)，看不懂回 None。
    # 危險程度要連裡面那個一起算（effect_of）——不然把危險指令排進排程，觸發時不會再問人，等於繞過確認。
    wraps: Optional[Callable[[List[str]], Optional[Tuple["Node", List[str]]]]] = field(default=None, repr=False)
    parent: Optional["Node"] = field(default=None, repr=False)
    children: Dict[str, "Node"] = field(default_factory=dict, repr=False)

    @property
    def is_group(self) -> bool:
        return self.fn is None

    def inner(self, args: Sequence[str]) -> Optional[Tuple["Node", List[str]]]:
        """包著的那個指令（沒有 wraps、或參數看不懂就是 None）。"""
        if self.wraps is None:
            return None
        found = self.wraps(list(args))
        return None if found is None or found[0].is_group else found

    def effect_of(self, args: Sequence[str] = ()) -> str:
        """這一次呼叫實際的效果。包著別的指令的，裡面那個危險、要 /sudo、或要當場驗證碼，這一筆就算危險：
        觸發時不會再問人，建立的這一刻就是那道門。只會比 effect 更嚴，不會放寬。"""
        if self.wraps is None:
            return self.effect
        try:
            found = self.inner(args)
        except Exception:
            return DANGER                  # 看不懂就當危險（fail closed）
        if found is None:
            return self.effect
        node, inner_args = found
        if node.policy.elevated or any(f.fresh_code for f in node.fields) or node.effect_of(inner_args) == DANGER:
            return DANGER
        return self.effect

    @property
    def path(self) -> str:
        parts, node = [], self
        while node is not None and node.parent is not None:
            parts.append(node.name)
            node = node.parent
        return ".".join(reversed(parts))

    @property
    def policy(self) -> Policy:
        policy, node = self.own, self.parent
        while node is not None:
            policy = policy.tighten(node.own)
            node = node.parent
        return policy

    @property
    def command(self) -> str:
        """What a person types, derived from the path so names cannot drift (see module doc)."""
        parent = self.parent
        if parent is not None and parent.bare:
            return "/" + self.name
        if self.default:
            return "/" + parent.path.replace(".", "_")
        return "/" + self.path.replace(".", "_")

    @property
    def names(self) -> Tuple[str, ...]:
        return (self.command,) + self.legacy

    def walk(self) -> Iterator["Node"]:
        for child in self.children.values():
            yield child
            yield from child.walk()


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""          # "", "owner_only", "role", "private", "interactive", "stepup", "stepup_unset"
    text: str = ""            # 給人看的那句話；空的就照 reason 用預設（authorize 會替 🔐 的兩種填好）

    @property
    def message(self) -> str:
        return self.text or {"private": PRIVATE_ONLY, "stepup": STEPUP_NEEDED, "stepup_unset": STEPUP_UNSET}.get(
            self.reason, REFUSED)

    @property
    def needs_sudo(self) -> bool:
        """Everything else would pass: the caller may use it once they /sudo (or set it up)."""
        return self.reason in ("stepup", "stepup_unset")


class Group:
    """Handle for hanging leaves under a group node."""

    def __init__(self, registry: "CommandRegistry", node: Node):
        self._registry = registry
        self.node = node

    def leaf(self, name: str, fn: Callable, summary: str, *, legacy: Union[str, Sequence[str]] = (),
             default: bool = False, usage: str = "", effect: str = READ,
             interactive: bool = False, quota_exempt: bool = False, role: Optional[int] = None,
             owner_only: bool = False, private_only: bool = False, elevated: bool = False,
             ai: bool = True) -> Node:
        """fn(api, chat_id, user, args)。legacy：改名前的舊名稱，照樣能打、能排程。ai=False：不給 AI。
        role 沒給＝角色階梯最低的那一級（實際下限還是取祖先群組裡最嚴的）。"""
        role = self._registry.lowest_role if role is None else role
        if name in self.node.children:
            raise ValueError(f"duplicate command {self.node.path}.{name}")
        if default and (self.node.parent is None or any(c.default for c in self.node.children.values())):
            raise ValueError(f"{self.node.path or '(root)'}.{name}: a group has at most one default leaf")
        old = [legacy] if isinstance(legacy, str) else list(legacy)
        node = Node(name=name, title=summary, summary=summary, fn=fn,
                    own=Policy(role, owner_only, private_only, elevated), effect=effect,
                    interactive=interactive, usage=usage, default=default, quota_exempt=quota_exempt,
                    ai=ai, parent=self.node)
        node.legacy = tuple(dict.fromkeys(n.lower() for n in old if n.lower() != node.command))
        self._registry._index(node)
        self.node.children[name] = node
        return node

    def group(self, name: str) -> "Group":
        return Group(self._registry, self.node.children[name])


class CommandRegistry:

    def __init__(self, owner_id: Optional[int] = None, stepup=None, roles=BasicRoles):
        self.owner_id = owner_id
        # security.stepup.StepUp；None 時 elevated 節點一律拒絕（fail closed）
        self.stepup = stepup
        # 角色階梯：一個 IntEnum，數字越大權限越高（users/roles.py）。權限比較只用 >=。
        self.roles = roles
        self.lowest_role = min(roles)
        self.root = Node(name="", title="", own=Policy(self.lowest_role))
        # 每個能打的名稱（正式名與舊名）→ (節點, 舊名的參數改寫)
        self._names: Dict[str, Tuple[Node, Optional[Rewrite]]] = {}
        self._callbacks: List[Tuple[str, Node, Callable]] = []
        # 指令選單（Telegram 輸入框旁）塞不下時先收起來的群組，越前面越先收；bot 的 layout 宣告。
        # 空的就照群組定義順序倒過來收（telegram/menu.py）。
        self.menu_collapse_order: Tuple[str, ...] = ()

    # ── building the tree ──────────────────────────────────────────────

    def define_group(self, path: str, title: str, summary: str = "", *, role: Optional[int] = None,
                     owner_only: bool = False, private_only: bool = False, elevated: bool = False,
                     bare: bool = False) -> Group:
        role = self.lowest_role if role is None else role
        parent_path, _, name = path.rpartition(".")
        parent = self.node(parent_path) if parent_path else self.root
        if parent is None or name in parent.children:
            raise ValueError(f"cannot define group {path}")
        node = Node(name=name, title=title, summary=summary,
                    own=Policy(role, owner_only, private_only, elevated), bare=bare, parent=parent)
        parent.children[name] = node
        return Group(self, node)

    def ensure_group(self, path: str, title: str, summary: str = "", **policy) -> Group:
        """已經定義過就直接回傳（layout 決定的權限優先）；沒有才用這裡給的定義。packs/ 用它：
        bot 自己的 layout 先定義就照 layout，沒定義也能用。"""
        node = self.node(path)
        if node is not None:
            if not node.is_group:
                raise ValueError(f"{path} is a command, not a group")
            return Group(self, node)
        return self.define_group(path, title, summary, **policy)

    def group(self, path: str) -> Group:
        node = self.node(path)
        if node is None or not node.is_group:
            raise KeyError(f"no group {path!r}; define it first (define_group / ensure_group)")
        return Group(self, node)

    def root_leaf(self, name: str, fn: Callable, summary: str, **kw) -> Node:
        return Group(self, self.root).leaf(name, fn, summary, **kw)

    def legacy(self, name: str, path: str, rewrite: Rewrite) -> None:
        """An old name whose arguments changed shape: typing it runs the node at path with
        rewrite(args). Example: legacy("/deluser", "user.role", lambda a: a[:1] + ["guest"])."""
        node = self.node(path)
        if node is None or node.is_group:
            raise KeyError(path)
        self._add_name(name.lower(), node, rewrite)
        node.legacy += (name.lower(),)

    def remove(self, path: str) -> bool:
        node = self.node(path)
        if node is None or node.parent is None:
            return False
        del node.parent.children[node.name]
        for name in [n for n, (target, _rw) in self._names.items() if target is node]:
            del self._names[name]
        return True

    def _index(self, node: Node) -> None:
        for name in node.names:
            self._add_name(name, node, None)

    def _add_name(self, name: str, node: Node, rewrite: Optional[Rewrite]) -> None:
        if not COMMAND_RE.match(name):
            raise ValueError(f"{name!r} ({node.path}) is not a valid Telegram command name")
        # 跟群組同名只准那個群組自己的葉節點用（/remind 是 remind.add），不然會蓋掉別人的群組選單
        group = self.root.children.get(name[1:])
        if name in self._names or (group is not None and group is not node.parent):
            raise ValueError(f"command name {name!r} ({node.path}) is already taken")
        self._names[name] = (node, rewrite)

    def bind_callback(self, prefix: str, path: str, handler: Callable) -> None:
        """Inline buttons whose callback_data starts with prefix act as the node at path:
        the clicker must pass authorize() for that node. handler(api, cb: CallbackInfo)."""
        node = self.node(path)
        if node is None:
            raise KeyError(path)
        if any(p == prefix for p, _n, _h in self._callbacks):
            raise ValueError(f"callback prefix {prefix!r} is already bound")
        self._callbacks.append((prefix, node, handler))
        self._callbacks.sort(key=lambda item: -len(item[0]))

    # ── lookup ─────────────────────────────────────────────────────────

    def node(self, path: str) -> Optional[Node]:
        node = self.root
        for part in path.split(".") if path else []:
            node = node.children.get(part)
            if node is None:
                return None
        return node

    def is_known(self, word: str) -> bool:
        """Is this name (with or without the leading /) already a command or a group?"""
        word = "/" + word.lower().split("@", 1)[0].lstrip("/")
        return word in self._names or word[1:] in self.root.children

    def resolve(self, text: str) -> Tuple[Optional[Node], List[str]]:
        """'/shop_status' 或 '/shop status' → (node, 剩下的參數)。

        先比對名稱（正式名與舊名）：'/remind list x' 是 /remind 加上文字 "list x"；
        舊名稱若有參數改寫就在這裡套用。不是名稱時才照群組往下走；停在群組上時回傳群組本身
        （呼叫端顯示選單）。'/help@MyBot' 的 @ 後面不算。
        """
        parts = text.strip().split()
        if not parts or not parts[0].startswith("/"):
            return None, []
        head = parts[0].lower().split("@", 1)[0]
        args = parts[1:]
        if head in self._names:
            node, rewrite = self._names[head]
            return node, (rewrite(args) if rewrite else args)
        node = self.root.children.get(head[1:])
        if node is None:
            return None, args
        while node.is_group and args and args[0].lower() in node.children:
            node = node.children[args.pop(0).lower()]
        return node, args

    def callback_for(self, data: str) -> Optional[Tuple[Node, Callable]]:
        for prefix, node, handler in self._callbacks:
            if data.startswith(prefix):
                return node, handler
        return None

    def leaves(self) -> List[Node]:
        return [n for n in self.root.walk() if not n.is_group]

    # ── the one permission check ───────────────────────────────────────

    def is_owner(self, user) -> bool:
        return self.owner_id is not None and user.tg_id == self.owner_id

    def authorize(self, user, node: Node, via: str, chat_id: Optional[int] = None) -> Decision:
        policy = node.policy
        owner = self.is_owner(user)
        if policy.owner_only and not owner:
            return Decision(False, "owner_only")
        if not owner and not user.role >= policy.role:
            return Decision(False, "role")
        if policy.private_only and chat_id is not None and chat_id != user.tg_id:
            return Decision(False, "private")
        if via in (ROUTINE, SCHEDULE, AI) and node.interactive:
            return Decision(False, "interactive")
        # 排程觸發不問：建立排程（SCHEDULE）時已經驗過，排程本來就是要在人不在時跑
        if policy.elevated and via != ROUTINE and not self.is_elevated(user):
            configured = self.stepup is not None and self.stepup.configured
            reason = "stepup" if configured else "stepup_unset"
            text = getattr(self.stepup, "need_message" if configured else "unset_message", "")
            return Decision(False, reason, text)
        return Decision(True)

    def is_elevated(self, user) -> bool:
        return self.stepup is not None and self.stepup.is_elevated(user.tg_id)

    def visible(self, user, node: Node) -> bool:
        """For menus: can this user use the node at all (ignoring where they are chatting).
        Nodes that only need /sudo are shown: the menu marks them 🔐."""
        if node.is_group:
            return any(self.visible(user, c) for c in node.children.values())
        decision = self.authorize(user, node, TYPED)
        return decision.allowed or decision.needs_sudo
