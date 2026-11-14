"""
掃 packs/*/pack.json（＋config.json 的 packs.dirs），一個資料夾一個 pack，裝進 app。
SYNOX 出廠不帶任何工具（packs/ 只有說明；工具在 SYNOX_Libs）：以前的 connectors/ 2026-11-12 也搬走了（docs/legacy/connectors.md）。

  kind=python     import 資料夾裡的 pack.py，呼叫 install(app, pack)
  kind=cli        pack.json 的 cli.argv＋cli.commands → isdtelekit.packs.service.install（會印 JSON 的命令列程式）
  kind=connector  只登記：一個群組、一個葉節點，說「還沒接上」（v0 不連外）
  kind=mcp        mcp.transport=stdio：packs/mcp.py（每個 (pack, 使用者) 一個長駐 MCP 子程序，tools_allow 的工具＝葉節點，
                  effect 只看 pack.json）；mcp.transport=http：遠端 MCP（packs/mcp_http.py，同一套工具→葉節點）；
                  沒寫 transport（只有 url）＝同 connector，只登記

安全管線（架構 v1 §4）在載入時做的是第 3 關：packs.lock 有記的 pack 每個檔重算 sha256，不符＝不載入
（tampered）、通知擁有者一次；沒鎖的照舊載入（報告標 unlocked）。第 1、2 關在安裝時（packs/admin.py）。
kind=cli 的 argv／env／cwd 樣板代換 {python}、{node}、{pack_dir}、{data_dir}、{user_data_dir}、{tg_id}（每次呼叫照下令的人）；
子程序另外拿到 SYNOX_USER_DATA_DIR／SYNOX_TG_ID／SYNOX_MODE／SYNOX_PACK_DIR／SYNOX_PACK_NAME／SYNOX_SECRET_ENV（context_env，給 synox_sdk）。
runtime.python／node = "auto" 的環境在安裝時建（packs/envs.py）；沒建好＝status missing、detail 說怎麼重建。
每次叫 cli 子程序都先過 synox/sandbox.py（PERM-7）：grants 從宣告算、後端包一層 argv（none＝原樣）；
pack 有 runtime.container、擁有者選了容器、這台找得到引擎 → sandbox.box_for 給容器後端，代換改用容器裡的路徑（view_for）；
伺服器版 policy.sandbox.required_for 命中又沒有真隔離 → 那個 cli pack 整組 owner_only（detail 寫原因）。
伺服器版 kind=python 的信任（PERM-8）：出廠的（BUNDLED，現在是空的）＝core；有鎖看 packs.lock 的 trust；沒鎖（手動放的）＝third-party。
third-party 的 python pack 整組 owner_only（成員打了跟不存在一樣、AI 工具清單也沒有；detail 寫原因）。
伺服器版沒鎖、不是出廠的 pack 載入前補跑一次第 2 關（scan.gate2），沒過＝status rejected、不載入。

群組（/help 的一頁）由 loader 依 pack.json 定義（title、summary、access），pack 只往裡面掛葉節點；
access=owner（預設）＝整組只有機器擁有者看得到、用得到（別人打了跟不存在一樣）；
access=member＝伺服器版給「成員」以上（擁有者用 /user_role 升級），個人版等於 owner；
access=everyone＝任何傳訊息給 bot 的人（伺服器版的訪客 GUEST 只看得到這種）。
再套角色的能力上限（config.json policy.roles，synox/policy.py）：pack.json 的 capabilities 裝不下某一級的上限，
那一級（以下）整組看不到；exec、filesystem:any 只有擁有者（pack_group_policy）。
一個 pack 壞掉（pack.json 不合、install 丟例外）只跳過那一個，記在 LoadReport，doctor 會印出來。
pack 拿到的 Pack 物件：.manifest、.store（storage=vault → 密文 data/<name>.json.enc；plain → data/<name>.json）、
.path(...)（data/packs/<name>/... 全部人共用的檔案；伺服器版 data=user 的 pack 呼叫會丟 PackPathError）、
.path_of(user, ...)（這個人自己的檔案：伺服器版 data/users/<id>/<name>/files/，個人版 data/<name>/files/；擋 .. 逃逸）、
.group（指令群組的 Group handle）。
**每個人自己的資料用 pack.store.of(user)**：個人版回同一份共用檔；伺服器版回這個人自己的
data/users/<tg_id>/<name>.json(.enc)（vault 的金鑰由主金鑰＋id 用 HKDF 衍生，別人的檔解不開）。
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from isdtelekit.core import jsonstore
from isdtelekit.core.registry import DANGER, READ, WRITE, Field

from synox import health, policy, sandbox
from synox.config import ROOT
from synox.packs import envs, kit, render
from synox.packs import confirm as tool_confirm
from synox.packs import secrets as pack_secrets
from synox.packs import lock as pack_lock
from synox.packs.manifest import (Manifest, ManifestError, default_text, missing_requirements, read, safe_env,
                                  scenario_of, secret_env_names, synox_problem)
from synox.vault.vault import USERS_DIR

# SYNOX 自己的 pack 資料夾＝使用者裝的工具的落點（PACK_DIRS[0]）。2026-11-12 以前還有 connectors/（出廠的 4 個 connector），
# 搬到 SYNOX_Libs 之後不掃了：從舊版解壓縮蓋過去、留在磁碟上的舊 connectors/ 也不會被載入（docs/legacy/connectors.md）。
PACK_DIRS = (os.path.join(ROOT, "packs"),)
EFFECTS = {"read": READ, "write": WRITE, "danger": DANGER}


def help_title(m: Manifest) -> str:
    """/help 那一頁（SDK 的群組標題）：pack 的 title＋穩定度標籤，例如「💰 記帳（🧪 alpha）」。"""
    return f"{m.title}（{m.stage_label}）"


class PackStore:
    """pack 的資料：load/save 一份 JSON。storage=vault 時落地是密文（Vault），否則 SDK 的 jsonstore。

    per_user=True（伺服器版）：of(user) 給每個人一份自己的 store；False（個人版）：of(user) 就是自己。"""

    def __init__(self, name: str, data_dir: str, vault=None, *, per_user: bool = False):
        self.name = name
        self._data_dir = data_dir
        self._vault = vault
        self.per_user = per_user
        self.lock = threading.RLock()           # 讀改寫同一份資料時用（update() 已經包好）
        self._scoped: Dict[int, "PackStore"] = {}

    def of(self, user) -> "PackStore":
        """這個人的資料（user：有 tg_id 的使用者物件，或直接給 int）。個人版回共用的那一份。"""
        if not self.per_user:
            return self
        tg_id = user if isinstance(user, int) and not isinstance(user, bool) else getattr(user, "tg_id", None)
        if not isinstance(tg_id, int) or isinstance(tg_id, bool):
            raise ValueError("pack.store.of(user) needs a user with an integer tg_id")
        with self.lock:
            found = self._scoped.get(tg_id)
            if found is None:
                folder = os.path.join(self._data_dir, USERS_DIR, str(tg_id))
                vault = self._vault.for_user(tg_id) if self._vault is not None else None
                found = self._scoped[tg_id] = PackStore(self.name, folder, vault)
            return found

    @property
    def encrypted(self) -> bool:
        return self._vault is not None

    def _key(self, key: Optional[str]) -> str:
        return self.name if not key else f"{self.name}.{key}"

    def file(self, key: Optional[str] = None) -> str:
        if self._vault is not None:
            return self._vault.path(self._key(key))
        return os.path.join(self._data_dir, self._key(key) + ".json")

    def load(self, default: Any = None, key: Optional[str] = None) -> Any:
        if self._vault is not None:
            return self._vault.load_json(self._key(key), default)
        return jsonstore.load_json(self.file(key), default)

    def save(self, data: Any, key: Optional[str] = None) -> None:
        if self._vault is not None:
            self._vault.save_json(self._key(key), data)
        else:
            jsonstore.save_json(self.file(key), data)

    def update(self, fn: Callable[[Any], Any], default: Any, key: Optional[str] = None) -> Any:
        """讀 → fn(data) 原地改 → 存；回 fn 的回傳值。整段持鎖。"""
        with self.lock:
            data = self.load(default, key)
            result = fn(data)
            self.save(data, key)
            return result


@dataclass
class Pack:
    manifest: Manifest
    store: PackStore
    app: Any = field(repr=False, default=None)
    data_dir: str = ""
    web_routes: Dict[str, Callable] = field(default_factory=dict, repr=False)
    config: Any = field(repr=False, default=None)
    locked_files: Dict[str, str] = field(default_factory=dict, repr=False)   # packs.lock 記的 sha256（有鎖時）
    cli_bridge: Any = field(repr=False, default=None)                       # kind=cli：ServiceBridge（測試用 wait()）
    secret_fields: List[dict] = field(default_factory=list, repr=False)     # auth.fields（SYNOX 收的那些；見 packs/secrets.py）
    secrets: Any = field(repr=False, default=None)                          # PackSecrets（保管箱的 pack_secrets）
    live: Any = field(repr=False, default=None)                             # lock.LiveCheck（有鎖時；每次叫 cli 前再對一次）
    # 工具服務（ADR 0024；SDK 0.2.3）：pack.json web.app 宣告的讀、動作、匯出各掛哪個函式（重新載入時是新的 Pack，自然清空）
    app_reads: Dict[str, Callable] = field(default_factory=dict, repr=False)
    app_actions: Dict[str, Callable] = field(default_factory=dict, repr=False)
    app_describe: Dict[str, Callable] = field(default_factory=dict, repr=False)
    app_exports: Dict[str, Callable] = field(default_factory=dict, repr=False)

    def tampered_since_load(self) -> List[str]:
        """載入之後檔案被改過嗎（審查 B #D）：有鎖的 pack 每次叫 cli／開 mcp stdio 子程序之前問；[]＝對得上（或沒鎖）。"""
        if self.live is None:
            return []
        try:
            return self.live.changes()
        except Exception as e:                   # 對不了就不能說它沒被改
            return [f"檢查失敗：{type(e).__name__}: {e}"]

    def secret(self, name: str, user=None) -> Optional[str]:
        """使用者在 Web UI「連接」填的值（pack.json auth.fields 的 name）；沒填回 None。
        伺服器版每人一份：一定要給 user（下令的人），不給丟 SecretError（不會拿別人的）。
        沒宣告的名字丟 KeyError。值只給程式用：不要印出來、不要放進回覆或 log。"""
        if not any(f["name"] == name for f in self.secret_fields):
            raise KeyError(f"{self.name}: auth.fields 沒有宣告 {name!r}")
        if self.secrets is None:
            raise pack_secrets.SecretError("保管箱沒有打開，讀不到 secret。")
        return self.secrets.get(self.name, name, user)

    def report_status(self, state: str, message: str = "", tag: str = "") -> bool:
        """回報這個 pack 的狀態給 runtime（任務 pack.<name>，主控面板與常駐助理看得到；docs/adr/0001 §2）。
        state：ok｜running｜failed｜idle（其他的忽略、回 False）；message 最多 200 字、像密鑰的會被遮掉。
        tag：選填的短標籤（小寫英數字與 . _ -，32 字內），讓連動規則分得出是哪一件事做完了（例如 "diary-image"）。"""
        from synox import runtime
        return runtime.report(self.app, self.name, state, message, title=self.manifest.title, tag=tag)

    def on_event(self, on: str, rule_id: str, do: Callable, *, state="ok", from_state=(), tag: Optional[str] = None,
                 when: Optional[Callable] = None, emits=(), timing: str = "now", cooldown_s: int = 0,
                 max_per_hour: int = 30, name: str = ""):
        """連動規則（docs/adr/0004）：任務 on 變成 state（可加 from_state、tag、when(event)）→ 呼叫 do(event)。
        規則 id 會是 pack.<name>.<rule_id>。do 拿到的 event 有 task、state、prev、tag、at、chain、depth；
        message 只有自己的任務才有（別人的是 ""，跟 peer_status 一樣）。do 裡回報的狀態會接在同一串連動上（防循環）。
        do 會讓哪個任務有新狀態，寫在 emits（例如 ["pack.<name>#asked"]），登記時就能擋掉會繞回自己的規則。
        形狀錯丟 RuleError；會繞回自己＝不收（主控面板看得到原因）、回 None。"""
        from synox import runtime
        from synox.runtime.activator import Rule
        rule = Rule(id=f"pack.{self.name}.{rule_id}", on=on, states=state, from_states=from_state, tag=tag, do=do,
                    when=when, emits=tuple(emits), timing=timing, cooldown_s=cooldown_s, max_per_hour=max_per_hour,
                    owner=self.name, name=name or f"{self.manifest.title}：{rule_id}")
        return runtime.add_rule(self.app, rule)

    def peer_status(self) -> Dict[str, dict]:
        """別的任務／pack 的狀態：{任務 id: {"state", "at"}}（只有狀態與時間，沒有訊息）。"""
        from synox import runtime
        return runtime.peer_status(self.app)

    def web_route(self, route: str, fn: Callable) -> None:
        """Web UI 面板的資料：GET /api/packs/<name>/<route> → fn(user) 回可以轉 JSON 的東西。
        route 一定要寫在 pack.json 的 web.api 裡（"GET /<route>"），沒寫的掛了也打不到。"""
        if route not in self.manifest.web.get("api", []):
            raise ValueError(f"{self.name}: web route {route!r} is not declared in pack.json web.api")
        self.web_routes[route] = fn

    def _app_decl(self, kind: str) -> list:
        app = (self.manifest.web or {}).get("app") or {}
        return list(app.get(kind) or [])

    def app_read(self, name: str, fn: Callable) -> None:
        """工具畫面的讀：GET /api/read/<name> → fn(user, params) 回可以轉 JSON 的東西。name 要寫在 web.app.reads。"""
        if name not in self._app_decl("reads"):
            raise ValueError(f"{self.name}: app read {name!r} is not declared in pack.json web.app.reads")
        self.app_reads[name] = fn

    def app_action(self, name: str, fn: Callable, *, describe: Optional[Callable] = None) -> None:
        """工具畫面的動作：POST /api/do/<name> → fn(user, values) 回 dict。name 要寫在 web.app.actions，
        而且要有同名的指令（群組.名字），危險程度一樣——一個動作＝一個指令（ADR 0024 §2）。
        describe(user, values) -> str：危險動作確認框的那一句（選填）。"""
        if name not in self._app_decl("actions"):
            raise ValueError(f"{self.name}: app action {name!r} is not declared in pack.json web.app.actions")
        self.app_actions[name] = fn
        if describe is not None:
            self.app_describe[name] = describe

    def app_export(self, name: str, fn: Callable) -> None:
        """工具畫面的匯出：POST /api/export/<name> → fn(user, params) 回 kit.Download。name 要寫在 web.app.exports。"""
        if name not in self._app_decl("exports"):
            raise ValueError(f"{self.name}: app export {name!r} is not declared in pack.json web.app.exports")
        self.app_exports[name] = fn

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def group(self):
        return self.app.registry.group(self.manifest.group)

    @property
    def server(self) -> bool:
        return getattr(self.config if self.config is not None else getattr(self.app, "config", None),
                       "mode", "personal") == "server"

    def path(self, *parts: str) -> str:
        """data/packs/<name>/...：**全部人共用**的檔案（data=shared／none 的 pack 用）。
        伺服器版 data=user 的 pack 呼叫會丟 PackPathError（那是跨戶的同一個資料夾）——改用 path_of(user, ...)。
        個人版照舊可以用（相容）。"""
        if self.server and getattr(self.manifest, "data", "none") == "user":
            raise PackPathError(
                f"{self.name}：data 是 user 的 pack 在伺服器版不能用 pack.path()（data/packs/{self.name}/ 是全部人共用的，"
                f"會讀到別人的檔案）。改用 pack.path_of(user, ...)：每個人自己的 data/users/<id>/{self.name}/files/。")
        folder = os.path.join(self.data_dir, "packs", self.manifest.name)
        os.makedirs(folder, exist_ok=True)
        return _inside(folder, parts, "pack.path")

    def path_of(self, user, *parts: str) -> str:
        """這個人自己的檔案：伺服器版 data/users/<tg_id>/<name>/files/...；個人版 data/<name>/files/...。
        資料夾會先建好；parts 是相對路徑（不准絕對路徑、不准用 .. 跑出這個資料夾，丟 PackPathError）。
        user：有 tg_id 的使用者物件或 int；伺服器版一定要給（不給丟 PackPathError，不會拿到別人的）。"""
        tg_id = user if isinstance(user, int) and not isinstance(user, bool) else getattr(user, "tg_id", None)
        if isinstance(tg_id, bool) or not isinstance(tg_id, int):
            if self.server:
                raise PackPathError(f"{self.name}：pack.path_of(user, ...) 要給下令的人（有整數 tg_id 的使用者）")
            tg_id = None
        if self.server:
            base = os.path.join(self.data_dir, USERS_DIR, str(tg_id))
        else:
            base = self.data_dir
        folder = os.path.join(base, self.manifest.name, "files")
        os.makedirs(folder, exist_ok=True)
        return _inside(folder, parts, "pack.path_of")


class PackPathError(ValueError):
    """pack.path()／pack.path_of() 用錯：伺服器版 data=user 用了共用資料夾，或路徑想跑出 pack 自己的資料夾。"""


def _inside(folder: str, parts, what: str) -> str:
    """folder／parts…，但一定還在 folder 裡面（絕對路徑、..、磁碟機代號、連結跑出去都擋）。"""
    for part in parts:
        if not isinstance(part, str):
            raise PackPathError(f"{what}：路徑每一段都要是字串（拿到 {type(part).__name__}）")
        if os.path.isabs(part) or os.path.splitdrive(part)[0] or part.startswith(("/", "\\")):
            raise PackPathError(f"{what}：不能用絕對路徑（{part!r}）")
    target = os.path.normpath(os.path.join(folder, *parts))
    root_real = os.path.realpath(folder)
    target_real = os.path.realpath(target)
    try:
        inside = os.path.commonpath([os.path.normcase(root_real), os.path.normcase(target_real)]) == \
            os.path.normcase(root_real)
    except ValueError:                      # 不同磁碟機
        inside = False
    if not inside:
        raise PackPathError(f"{what}：路徑跑出 pack 自己的資料夾了（{os.path.join(*parts) if parts else ''!r}）")
    return target


@dataclass
class PackStatus:
    name: str
    folder: str
    status: str                 # loaded｜connector｜disabled｜invalid｜missing｜incompatible｜error｜tampered｜rejected
    detail: str = ""
    kind: str = ""
    version: str = ""
    lock: str = ""              # locked｜unlocked｜tampered（packs.lock，第 3 關）
    scan: str = ""              # 伺服器版沒鎖的 pack 載入時補跑第 2 關：passed｜failed（""＝沒掃，PERM-8）


@dataclass
class LoadReport:
    items: List[PackStatus] = field(default_factory=list)

    def by_status(self, status: str) -> List[PackStatus]:
        return [i for i in self.items if i.status == status]

    @property
    def ok(self) -> bool:
        return not any(i.status in ("invalid", "error", "tampered", "rejected") for i in self.items)


def group_policy(app, access: str, server: bool) -> dict:
    """pack.json 的 access → define_group 的權限。member 在個人版等於 owner（個人版沒有成員）。"""
    if access == "owner" or (access == "member" and not server):
        return {"owner_only": True}
    if access == "member":
        from isdtelekit.users.roles import next_up
        roles = app.users.roles
        return {"role": next_up(roles, min(roles)) or max(roles)}
    return {}


def pack_group_policy(app, config, m: Manifest, server: bool) -> dict:
    """group_policy（access）再套角色能力上限（synox/policy.py，PERM-1）：pack.json 的 capabilities 裝不下某個角色的上限
    → 這一組對那個角色整組不可見（群組的最低角色拉到裝得下的那一級；哪一級都裝不下＝owner_only）。擁有者全部可見。
    SDK 的 authorize／visible 因此自己就擋：/help、選單、網頁、人打字、AI 工具清單都是同一條。"""
    return policy.group_policy_for(config, app.users.roles, m.capabilities, group_policy(app, m.access, server))


# ── 權限宣告（PERM-2）：surfaces、data=shared ───────────────────────────

def surface_policy(m: Manifest) -> dict:
    """pack.json 的 surfaces 沒有 channel（預設 ["dm"]）→ 整組 private_only：SDK authorize 自己擋群組／頻道。"""
    return {} if "channel" in (getattr(m, "surfaces", None) or ["dm"]) else {"private_only": True}


def shared_write_admin(app, m: Manifest, server: bool) -> int:
    """data=shared 的 pack 在伺服器版：WRITE／DANGER 的葉節點最低角色拉到管理員（角色階梯最高那一級）。
    群組定義、葉節點都掛好之後呼叫。回改了幾個節點。個人版、data 不是 shared 不動。"""
    if not server or getattr(m, "data", "none") != "shared":
        return 0
    group = app.registry.node(m.group)
    if group is None:
        return 0
    admin = max(app.registry.roles)
    n = 0
    for node in group.walk():
        if not node.is_group and node.effect in (WRITE, DANGER) and node.own.role < admin:
            node.own = dataclasses.replace(node.own, role=admin)
            n += 1
    return n


# ── 伺服器版 python pack 的信任（PERM-8） ─────────────────────────────────

# 出廠的 pack（在 PACK_DIRS 裡、名字在這張表上）＝core，不看 packs.lock。
# 2026-11-12 起 SYNOX 出廠不帶任何工具：money、notes、remind（docs/legacy/builtin-packs.md）與 4 個 connector
# （docs/legacy/connectors.md）都搬到 SYNOX_Libs，這張表是空的。**不要再把工具加回出廠**：新工具放 SYNOX_Libs、走安裝流程。
# 機制留著（is_bundled 的位置＋名字判斷、審查 A #5 的「有鎖以鎖為準」），測試用 monkeypatch 填名字來測。
BUNDLED: tuple = ()


def is_bundled(m: Manifest) -> bool:
    """出廠的：名字在 BUNDLED，而且資料夾就在內建的 PACK_DIRS 底下（packs.dirs 另外放的不算）。現在 BUNDLED 是空的＝永遠 False。
    只看名字和位置，所以**只在沒有 packs.lock 那一筆時**拿來決定信任（python_trust、sandbox.trust_of）：
    經安裝／升級流程進來的同名 pack 一定有鎖，以鎖記的 trust 為準（審查 A #5）。"""
    if m.name not in BUNDLED:
        return False
    parent = os.path.normcase(os.path.realpath(os.path.dirname(os.path.abspath(m.folder))))
    return parent in {os.path.normcase(os.path.realpath(d)) for d in PACK_DIRS}


def python_trust(config, m: Manifest) -> str:
    """kind=python 在伺服器版的信任：有鎖＝packs.lock 的 trust（擁有者安裝時選的；舊鎖沒寫＝third-party）；
    沒有鎖：出廠的＝core，其他（手動放進 packs/ 或 packs.dirs 的）＝third-party。
    以前出廠的名字優先——第三方作者把 pack 取名 notes、經升級裝進 packs/，就被當成 core。"""
    locked = pack_lock.trust_of(getattr(config, "data_dir", "") or "", m.name)
    if locked is not None:
        return locked
    return pack_lock.CORE if is_bundled(m) else pack_lock.THIRD_PARTY


def trust_reason(config, m: Manifest) -> str:
    """伺服器版、kind=python、trust=third-party → 一句話說為什麼只給擁有者（""＝不受影響；個人版永遠 ""）。"""
    if getattr(config, "mode", "personal") != "server" or m.kind != "python":
        return ""
    if python_trust(config, m) != pack_lock.THIRD_PARTY:
        return ""
    locked = pack_lock.entry(getattr(config, "data_dir", "") or "", m.name) is not None
    why = "安裝時信任選的是第三方（third-party）" if locked else "沒有 packs.lock（手動放進來的），當作第三方（third-party）"
    return (f"只對擁有者開放：{why}；python pack 在 SYNOX 程序裡跑、沒有沙盒，伺服器版不給成員用"
            f"（信得過就跑 python -m synox packs lock --approve {m.name} --trust core）")


def unlocked_scan(config, m: Manifest, lock_state: str) -> "Optional[List[str]]":
    """伺服器版沒有鎖、又不是出廠的 pack：載入前補跑一次第 2 關靜態掃描（安裝流程沒掃過它）。
    回 None＝不用掃；[]＝過了；否則是拒絕的理由（不載入）。"""
    if getattr(config, "mode", "personal") != "server" or lock_state != pack_lock.UNLOCKED or is_bundled(m):
        return None
    from synox.packs import scan as pack_scan
    try:
        return pack_scan.gate2(m).problems(m)
    except Exception as e:                   # 掃不了就不能說它安全
        return [f"掃描失敗：{type(e).__name__}: {e}"]


def discover(dirs=PACK_DIRS) -> List[str]:
    """dirs 的每一項：裝很多 pack 的資料夾（底下每個有 pack.json 的子資料夾算一個），或本身就是一個 pack（直接有 pack.json）。
    同一個 pack 資料夾只算一次（config `packs.dirs` 跟內建的重複時）。"""
    folders: List[str] = []
    seen = set()

    def add(folder: str) -> None:
        key = os.path.normcase(os.path.realpath(folder))
        if key not in seen:
            seen.add(key)
            folders.append(folder)

    for base in dirs:
        if not os.path.isdir(base):
            continue
        if os.path.isfile(os.path.join(base, "pack.json")):
            add(base)
            continue
        for name in sorted(os.listdir(base)):
            folder = os.path.join(base, name)
            if os.path.isfile(os.path.join(folder, "pack.json")):
                add(folder)
    return folders


def _order(folder: str) -> tuple:
    try:
        m = read(folder)
        return (0 if m.kind not in ("connector", "mcp") else 1, int(m.raw.get("order", 100)), m.name)
    except (ManifestError, ValueError, TypeError):
        return (2, 0, folder)


def apply_scope(app, m: Manifest) -> None:
    """pack.json 的 callers／stepup 掛到門禁核心的對照表（ADR 0025 §3）。先清掉這個群組舊的（重新載入不會殘留）。
    對不到指令的那一條當作沒寫（記 log）；危險的指令列了 remote：拿掉 remote（只會更緊）。"""
    from isdtelekit.core.registry import DANGER
    from synox import guard
    g = guard.of(app)
    if g is None or g.scope is None:
        return
    g.scope.clear_prefix(m.group)
    for name in sorted(set(m.callers) | set(m.stepup)):
        node = app.registry.node(f"{m.group}.{name}")
        if node is None or node.is_group:
            logging.warning("[PACKS] %s: callers/stepup names %s, which is not one of its commands; ignored",
                            m.name, name)
            continue
        callers = m.callers.get(name)
        if callers and node.effect == DANGER and "remote" in callers:
            callers = [c for c in callers if c != "remote"] or ["human"]
            logging.warning("[PACKS] %s.%s is dangerous; remote dropped from callers", m.name, name)
        g.scope.restrict(node.path, callers=callers, stepup=name in m.stepup)


def _drop_group(registry, group: str) -> None:
    node = registry.node(group)
    if node is None:
        return
    for leaf in [n for n in node.walk() if not n.is_group]:
        registry.remove(leaf.path)
    registry.remove(group)


def _install_python(app, pack: Pack) -> None:
    """從原始碼編譯、執行 pack.py（不讀 __pycache__ 的 .pyc：那裡的檔不在 packs.lock 的雜湊裡）。
    有鎖時，編譯的那一份 bytes 再對一次雜湊（檢查完到執行之間被換掉也抓得到）。"""
    m = pack.manifest
    module_name = m.python.get("module", "pack")
    path = os.path.join(m.folder, f"{module_name}.py")
    with open(path, "rb") as f:
        source = f.read()
    expected = pack.locked_files.get(f"{module_name}.py")
    if expected and hashlib.sha256(source).hexdigest() != expected:
        raise ManifestError(f"{module_name}.py 跟 packs.lock 記的不一樣（剛剛被改過？）")
    spec = importlib.util.spec_from_file_location(f"synox_pack_{m.name.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(source, path, "exec"), module.__dict__)
    if not callable(getattr(module, "install", None)):
        raise ManifestError(f"{module_name}.py 沒有 install(app, pack)")
    module.install(app, pack)


# ── kind=cli：樣板代換（{python}、{node}、{pack_dir}、{data_dir}、{user_data_dir}、{tg_id}） ─────────

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def cli_python(m: Manifest, data_dir: Optional[str] = None) -> str:
    """{python} 換成什麼，照順序：
    1. cli.python：絕對路徑｜"venv"（<pack 資料夾>/../.venv 的 python）
    2. runtime.python（Windows）／runtime.python_posix（其他）："auto"＝data/envs/<pack>/venv（安裝時建，packs/envs.py）；
       其他＝相對於 pack 資料夾（或絕對路徑）
    3. 都沒寫＝SYNOX 自己的 Python
    （envs.python_target：第 2 關用同一份規則判斷它在不在 pack 外；pack 外的＝未鎖定執行環境、T2）"""
    return envs.python_target(m, data_dir)[0]


def user_data_dir(config, tg_id) -> str:
    """伺服器版：data/users/<tg_id>；個人版：data。"""
    if getattr(config, "mode", "personal") == "server" and tg_id is not None:
        return os.path.join(config.data_dir, USERS_DIR, str(tg_id))
    return config.data_dir


def placeholders(m: Manifest, config, user=None) -> Dict[str, str]:
    tg_id = getattr(user, "tg_id", None) if user is not None else None
    if tg_id is None:
        tg_id = getattr(config, "owner_id", None)
    return {"python": cli_python(m, config.data_dir), "node": envs.node_of(m, config.data_dir),
            "pack_dir": m.folder, "data_dir": config.data_dir,
            "user_data_dir": user_data_dir(config, tg_id), "tg_id": "" if tg_id is None else str(tg_id)}


def substitute(text: str, values: Dict[str, str]) -> str:
    """{名字} → values[名字]（只換 values 有的；一次換完，換進來的字不會再被換）。"""
    return _PLACEHOLDER.sub(lambda mm: values.get(mm.group(1), mm.group(0)), str(text))


def build_argv(template, values: Dict[str, str]) -> List[str]:
    """樣板 → argv。{x} 換成值；值是空的那一段拿掉——只有「單獨一段的 {x}」才連前面那個字面的 --旗標 一起拿掉。

    不用 SDK 的 service.build_argv：它看的是「已經換好的前一段」是不是 - 開頭，所以
    ["--amount={amount}", "--date={date}"] 在 date 沒填時會把已經填好的 --amount=120 一起丟掉（金流簿的 add 就會壞）。"""
    out: List[str] = []
    literal_flag = False                       # out 的最後一段是樣板裡字面的 --旗標（不是換出來的）
    for token in template:
        token = str(token)
        names = _PLACEHOLDER.findall(token)
        if names and any(not str(values.get(n, "") or "").strip() for n in names):
            if token == "{" + names[0] + "}" and len(names) == 1 and literal_flag:
                out.pop()
            literal_flag = False
            continue
        if names:
            out.append(_PLACEHOLDER.sub(lambda mm: str(values.get(mm.group(1), "")).strip(), token))
            literal_flag = False
        else:
            out.append(token)
            literal_flag = token.startswith("-") and "=" not in token
    return out


def pack_path(m: Manifest, values: Dict[str, str], rel: str) -> str:
    """argv 裡 ./x 的完整路徑：values 的 pack_dir（容器裡＝/pack，用 / 接）；沒有就 pack 資料夾。"""
    base = values.get("pack_dir") or m.folder
    if base.startswith("/") and os.name == "nt":            # Windows 上的容器路徑（Docker Desktop）：一律 /
        return base.rstrip("/") + "/" + rel.replace("\\", "/")
    return os.path.join(base, rel)


def cli_prefix(m: Manifest, values: Dict[str, str]) -> List[str]:
    out = []
    for part in m.cli["argv"]:
        part = str(part)
        if part.startswith("./") or part.startswith(".\\"):
            part = pack_path(m, values, part[2:])
        out.append(substitute(part, values))
    return out


def cli_env(m: Manifest, values: Dict[str, str]) -> Dict[str, str]:
    """cli.env（代換過）；runtime.node=auto 再加 NODE_PATH＝data/envs/<pack>/node_modules（pack 自己寫的優先）。"""
    out = envs.node_env(m, values.get("data_dir") or None)
    # 審查 C #C2：PYTHONPATH（pack 外）、NODE_OPTIONS、PATH… 第 1 關就拒；這裡再濾一次（防禦深度）
    out.update({k: substitute(v, values) for k, v in safe_env(m.cli.get("env") or {}).items()})
    return out


def _caller_kind() -> str:
    from synox.guard import origin
    return origin.current().kind


def context_env(m: Manifest, config, values: Dict[str, str], secret_fields=()) -> Dict[str, str]:
    """synox_sdk 的 context()／secret() 讀的環境變數（每次呼叫照下令的人；蓋過 pack 自己寫的同名變數）：
    SYNOX_USER_DATA_DIR、SYNOX_TG_ID、SYNOX_MODE（personal｜server）、SYNOX_PACK_DIR、SYNOX_PACK_NAME，
    SYNOX_SECRET_ENV＝「auth 欄位名=環境變數名」逗號接起來（只有名字，值照舊只在那個環境變數裡）。"""
    out = {"SYNOX_USER_DATA_DIR": values.get("user_data_dir", ""), "SYNOX_TG_ID": values.get("tg_id", ""),
           "SYNOX_MODE": str(getattr(config, "mode", "personal") or "personal"),
           "SYNOX_PACK_DIR": values.get("pack_dir") or m.folder, "SYNOX_PACK_NAME": m.name,
           # 誰叫的（ADR 0025 §2；synox_sdk 的 caller()／require_human() 讀）：只有種類，看得到、改不了
           "SYNOX_CALLER": _caller_kind(),
           # P7：packs.lock 鎖每一個檔（含 __pycache__）；子程序的 python 不准在 pack 資料夾裡寫 .pyc
           "PYTHONDONTWRITEBYTECODE": "1",
           # 審查 C #C2：子程序的 python 不讀使用者層的 site-packages（%APPDATA%\Python、~/.local 裡的 .pth 會在
           # 啟動時執行，不在鎖裡）；SYNOX／runtime auto 的 venv 本來就不讀，這裡讓系統 Python 也一樣
           "PYTHONNOUSERSITE": "1"}
    pairs = [f"{f['name']}={f['env']}" for f in secret_fields or () if f.get("env")]
    if pairs:
        out["SYNOX_SECRET_ENV"] = ",".join(pairs)
    return out


def refuse_blocked_argv(m: Manifest) -> None:
    """載入時再看一次 argv（審查 C）：第 2 關一定擋的寫法（{python} 跑 pack 裡不是 .py 的檔…，scan.argv_blocked）
    → 丟 ManifestError、不載入。已經裝好、鎖住的舊 pack 不會重跑第 2 關，這裡補上。只查路徑，不執行。"""
    from synox.packs import scan as pack_scan
    blocked = pack_scan.argv_blocked(m)
    if blocked:
        raise ManifestError("；".join(f"{at}：{detail}" for _p, detail, at in blocked[:3]))


def _install_cli(app, pack: Pack) -> None:
    """每個 command 一個表單指令（SDK Forms）。不直接用 SDK service.install：argv 的開頭、env、cwd 要照
    「這一次是誰」代換（{tg_id}、{user_data_dir}），service.install 的 JsonCli 是裝的時候就固定的。
    其他行為照 service.install：值以 - 開頭拒絕、一般指令丟 app.tasks、background 先回「開始了」。
    例外：經 AI 呼叫（api.via_ai）的一般指令同步跑完，結果交回 AI（不然 AI 拿到空的、結果直接跑去給使用者）。
    工具回 needs_confirm（SDK P3）：不顯示結果，出核准卡；按 ✅ 用同一組參數重跑，子程序這次才拿到
    SYNOX_CONFIRMED=1／SYNOX_CONFIRM_TOKEN（packs/confirm.py；其他時候一律明寫 0／空）。
    fields[].kind（int｜number｜bool｜choice）在 Field.check 檢查、交給程式前 normalize；
    requires.env 列的名字當 keep_env 給 JsonCli（其他看起來像密鑰的環境變數照樣拿掉）。"""
    from isdtelekit.jobs.cli import JsonCli
    from isdtelekit.packs import service

    from synox import runtime
    from synox.agent import validate as gate4

    m = pack.manifest
    refuse_blocked_argv(m)
    config = pack.config if pack.config is not None else app.config
    bridge = service.ServiceBridge()
    pack.cli_bridge = bridge

    # 子程序只看得到 requires.env／auth.fields[].env 列的密鑰名（其他照 JsonCli 拿掉）；
    # SYNOX_CONFIRM_TOKEN 名字像密鑰，但值是 SYNOX 自己每次明寫的（packs/confirm.py），要留著
    keep_env = list(secret_env_names(m)) + list(tool_confirm.ENV_NAMES)
    by_name = {c["name"]: c for c in m.commands}
    grants = tool_confirm.grants_of(app)
    nodes: Dict[str, Any] = {}           # 指令名 → 節點（needs_confirm 出卡要用；節點在 submit 之後才掛）

    def boxed(ph: Dict[str, str]):
        """這一次的後端與代換用的值（選了容器＝容器裡的路徑，sandbox.view_for）。"""
        box = sandbox.box_for(config, m)
        return box, sandbox.view_for(box, ph)

    def make_cli(ph: Dict[str, str], user=None, confirmed: Optional[str] = None, box_view=None) -> "JsonCli":
        # 運行空間（synox/sandbox.py，PERM-7；選了容器＝ContainerSandbox，S1）：照宣告算範圍，交給後端包一層（none＝原樣）
        box, view = box_view or boxed(ph)
        cwd = os.path.normpath(os.path.join(m.folder, substitute(m.cli.get("cwd") or ".", ph)))   # 本機的（引擎用戶端也在這裡跑）
        env = cli_env(m, view)
        env.update(context_env(m, config, view, pack.secret_fields))
        env.update(tool_confirm.env_for(confirmed))      # 「已確認」只有這裡給（蓋過 cli.env）
        env.update(runtime.peer_env(app))                # SYNOX_PEER_STATUS：別人的狀態（只有 state 與時間）
        if pack.secret_fields and pack.secrets is not None:
            # auth.fields 有寫 env 的 secret：只走子程序環境（keep_env 放行這個名字），永遠不進 argv
            env.update(pack.secrets.env_for(m.name, pack.secret_fields, user))
        grants = sandbox.grants_for(m, config, ph, pass_env=keep_env)          # 本機的路徑（要掛哪些資料夾）
        if box.name != "none":
            for folder in grants.write:            # 要掛進去的可寫資料夾得先存在
                os.makedirs(folder, exist_ok=True)
        prefix, env = box.wrap(cli_prefix(m, view), env, cwd, grants)
        return JsonCli(app.jobs, prefix, cwd=cwd, name=m.name,
                       timeout=float(m.cli.get("timeout", 120)), json_flag=m.cli.get("json_flag", "--json"),
                       env_extra=env or None, keep_env=keep_env)

    def not_connected(user) -> str:
        """必填的 secret 還沒填：回一句話（空字串＝可以跑）。"""
        if not pack.secret_fields:
            return ""
        if pack.secrets is None or not pack.secrets.available:
            return f"🔌 {m.title} 要先連接，但保管箱沒有打開（python -m synox doctor 看原因）。"
        missing = pack.secrets.missing(m.name, pack.secret_fields, user)
        if not missing:
            return ""
        return (f"🔌 {m.title} 還沒連接：缺 {'、'.join(missing)}。"
                f"到網頁介面的工具頁，按這個 pack 的「連接」填（/web 拿登入連結；為了安全，不在聊天裡收）。")

    def say(api, chat_id, text):
        try:
            api.send_message(chat_id, text)
        except Exception:
            logging.exception("[PACKS] reply to %s failed", chat_id)

    def changed_files() -> str:
        """載入之後 pack 的檔案被換過（跟 packs.lock 對不上）：回一句人話、通知擁有者一次（空字串＝可以跑）。"""
        changes = pack.tampered_since_load()
        if not changes:
            return ""
        logging.error("[PACKS] %s changed after load, refusing to run: %s", m.name, changes)
        _tamper_notice(app, config, m, changes)
        return tampered_text(m, changes)

    def make_submit(cmd: "service.ServiceCommand", stdin_template: Optional[str] = None):
        """stdin_template：pack.json commands[].stdin，例如 "{answers}"——這個欄位的內容走 stdin 給程式，
        不進 argv（日記正文、長文字；不會出現在程序清單與 log 的 argv 那一行）。"""
        kinds_of = {f["name"]: f.get("kind", "text") for f in by_name.get(cmd.name, {}).get("fields") or []}
        choices_of = {f["name"]: tuple(f.get("choices") or ()) for f in by_name.get(cmd.name, {}).get("fields") or []}
        via_stdin = set(_PLACEHOLDER.findall(stdin_template or ""))

        def ask_confirm(api, chat_id, user, raw_values, values, envelope, again: bool) -> None:
            """工具回 needs_confirm：出核准卡（why＝工具的 summary），按 ✅ 用同一組參數帶一次性憑證重跑。"""
            if again:                                   # 已經確認過的重跑又要確認：不再出卡（不會無限來回）
                say(api, chat_id, tool_confirm.AGAIN.format(name=cmd.name))
                return
            desk = app.extras.get("synox_approval_desk")
            node = nodes.get(cmd.name)
            if desk is None or node is None:
                say(api, chat_id, tool_confirm.NO_DESK.format(name=cmd.name))
                return
            gid = grants.issue(m.name, cmd.name, values, getattr(user, "tg_id", None),
                               tool_confirm.tool_token(envelope), app.timing.confirm_ttl)
            shown = [f"{k}={str(v)[:60]}" for k, v in raw_values.items() if k not in via_stdin and str(v).strip()]

            def rerun(api2, chat2, clicker, grant):
                submit(api2, chat2, clicker, raw_values, _grant=grant)

            try:
                desk.request(api, chat_id, user, node, shown, tool_confirm.summary_of(envelope), grant=gid,
                             rerun=rerun, header="⚠️ 要你確認才會做")
            except Exception:
                grants.discard(gid)
                raise
            mark = getattr(type(api), "mark_carded", None)     # 經 AI（CaptureApi）：這一輪停在這裡
            if callable(mark):
                mark(api)

        def submit(api, chat_id, user, values, _grant: str = ""):
            """_grant：只有核准卡按 ✅ 的重跑會給（kit.command、Forms、AI 都只傳四個參數，造不出來）。"""
            blocked = not_connected(user) or changed_files()
            if blocked:
                if _grant:
                    grants.discard(_grant)
                say(api, chat_id, blocked)
                return
            tool_path = nodes[cmd.name].path if cmd.name in nodes else f"{m.group}.{cmd.name}"
            if getattr(api, "via_ai", False) is not True:
                warning = health.manual_warning(app, tool_path, user)     # 人自己打：照常執行，前面多一行警告
                if warning:
                    say(api, chat_id, warning)
            raw_values = dict(values)
            ph = placeholders(m, config, user)
            if getattr(config, "mode", "personal") == "server":
                os.makedirs(ph["user_data_dir"], exist_ok=True)
            values = {k: gate4.normalize(kinds_of.get(k, "text"), v, choices_of.get(k, ())) for k, v in values.items()}
            user_id = getattr(user, "tg_id", None)
            for k, v in values.items():
                # kind: path：人打字也要在這個人的資料夾裡（AI 那條第 4 關本來就查；typed_check 不知道是誰）
                if kinds_of.get(k) == "path" and str(v or "").strip():
                    _full, problem = gate4.inside(ph["user_data_dir"], str(v).strip())
                    if problem:
                        if _grant:
                            grants.discard(_grant)
                        say(api, chat_id, f"❌ {cmd.name}：{k} 的路徑{problem}。")
                        return
            confirmed: Optional[str] = None
            if _grant:
                confirmed = grants.redeem(_grant, m.name, cmd.name, values, user_id)
                if confirmed is None:                   # 過期、用過、參數或人對不上：不執行
                    say(api, chat_id, tool_confirm.EXPIRED)
                    return
            box_view = boxed(ph)
            cli = make_cli(ph, user, confirmed, box_view)
            view = box_view[1]                          # 容器裡跑：{user_data_dir} 這些是容器裡的路徑
            argv = build_argv(cmd.argv, {**values, **view})
            timeout = {"timeout": cmd.timeout} if cmd.timeout else {}
            if stdin_template:
                timeout["stdin"] = substitute(stdin_template, {**values, **view})
            done = bridge._started()

            def finish(reply):
                try:
                    runtime.ingest_envelope(app, m.name, reply.data, title=m.title)   # 信封的 status（選填）
                    if not reply.ok:
                        # 失敗信封 v1（health/failure.py）：正規化、截長、遮密鑰；記進隔離清單，經 AI 的改回 AI 一行 FAIL
                        failure = health.failures.from_cli_reply(reply)
                        health.observe_failure(app, api, tool=tool_path, pack=m.name, failure=failure, user=user,
                                               tool_version=m.version)
                        say(api, chat_id, health.failures.user_text(failure, cmd.name))
                        return
                    health.observe_success(app, api, tool_path, user)
                    if tool_confirm.is_needs_confirm(reply.data):
                        ask_confirm(api, chat_id, user, raw_values, values, reply.data, again=confirmed is not None)
                        return
                    try:
                        text = render.render(reply.data)         # SYNOX 自己攤平 JSON（SDK 的只會印「N 筆」）
                    except Exception as e:
                        text = f"⚠️ 服務回了結果，但顯示的時候出錯：{e}"
                    if text:
                        say(api, chat_id, text)
                finally:
                    done.set()

            if cmd.background:
                say(api, chat_id, f"⏳ {cmd.name} 開始了，做完通知你。")
                cli.start(*argv, on_done=finish, **timeout)
                return
            if getattr(api, "via_ai", False) is True:
                # 經 AI 呼叫（agent 的 CaptureApi）：同步跑完，回覆被攔下來當工具結果交回 AI
                # （loop 再包 nonce 分隔符）。AI 那一輪本來就在 app.tasks 上，不會卡住收訊。
                finish(cli.call(*argv, **timeout))
                return
            typing = getattr(api, "typing", None)
            if callable(typing):
                typing(chat_id)
            app.tasks.run(lambda: finish(cli.call(*argv, **timeout)), name=f"pack-{m.name}-{cmd.name}")
        return submit

    def panel_route(c: dict):
        def fn(user):                          # Web UI 面板的 GET：在網頁的請求執行緒上跑（等它結束）
            blocked = not_connected(user) or changed_files()
            if blocked:
                return {"ok": False, "error": blocked}
            ph = placeholders(m, config, user)
            box_view = boxed(ph)
            reply = make_cli(ph, user, None, box_view).call(*build_argv(c.get("argv") or [], box_view[1]))
            return reply.data if reply.ok else {"ok": False, "error": reply.error}
        return fn

    for route, target in (m.web.get("routes") or {}).items():
        pack.web_route(route, panel_route(by_name[target]))

    meta = app.extras.setdefault("synox_tool_meta", {})
    for c in m.commands:
        kinds = {f["name"]: f.get("kind", "text") for f in c.get("fields") or []}
        fields = [Field(f["name"], f.get("ask", f["name"]), required=bool(f.get("required")),
                        default=default_text(f.get("default")), choices=tuple(f.get("choices") or ()),
                        check=gate4.typed_check(kinds.get(f["name"], "text"), tuple(f.get("choices") or ())))
                  for f in c.get("fields") or []]
        cmd = service.ServiceCommand(c["name"], c["argv"], c.get("summary", c["name"]), fields=fields,
                                     effect=EFFECTS.get(str(c.get("effect", "read")).lower(), READ),
                                     background=bool(c.get("background")), default=bool(c.get("default")),
                                     timeout=c.get("timeout"))
        safe_fields = [service._no_dash(f) for f in fields]
        stdin_template = c.get("stdin") if isinstance(c.get("stdin"), str) else None
        if any(f.fresh_code for f in fields):
            # 要驗證碼的走 SDK Forms（碼永遠最後問、收到就驗）
            node = app.forms.leaf(pack.group, cmd.name, make_submit(cmd, stdin_template), cmd.summary,
                                  fields=safe_fields, effect=cmd.effect, default=cmd.default, ai=c.get("ai") is not False)
        else:
            # 其他的跟內建 pack 一樣「照位置填、key=value 補、選填不追問」：/moneybook 120 午餐 直接存
            # （SDK Forms 會停下來問「要補充這些嗎？」，手機上多一輪、下一句指令還會把它打斷）。
            # 照位置填幾個：pack.json 的 commands[].positional；沒寫＝必填的個數。
            n_required = sum(1 for f in fields if f.required)
            try:
                n_pos = int(c.get("positional", n_required))
            except (TypeError, ValueError):
                n_pos = n_required
            submit = make_submit(cmd, stdin_template)
            node = kit.command(pack.group, cmd.name, lambda api, chat_id, user, values, _s=submit: _s(api, chat_id, user, values),
                               cmd.summary, fields=safe_fields, positional=max(0, min(n_pos, len(safe_fields))),
                               effect=cmd.effect, default=cmd.default, ai=c.get("ai") is not False)
        nodes[cmd.name] = node
        positional = [n for n in kinds if f"{{{n}}}" in c.get("argv", [])]
        # commands[].confirm：AI 呼叫前先送確認卡（effect 照寫的算；agent/loop.py 看這個）
        meta[node.path] = {"argv": True, "positional": positional, "kinds": kinds, "confirm": c.get("confirm") is True,
                           # commands[].ai.scenario：給 AI 的使用情境（agent/tools.description；docs/adr/0013）
                           "scenario": scenario_of(c),
                           # 網頁工具頁的表單說明（pack.json fields[].help；只給人看，不進 AI 的 schema）
                           "help": {f["name"]: f["help"] for f in c.get("fields") or []
                                    if isinstance(f.get("help"), str) and f["help"].strip()}}


def tampered_text(m: Manifest, changes: List[str]) -> str:
    listing = "、".join(changes[:5]) + ("…" if len(changes) > 5 else "")
    return (f"⚠️ {m.title} 的檔案在載入之後被改過了（{listing}），跟安裝時核准的不一樣，為了安全這次不執行；已經通知擁有者。"
            f"如果是擁有者自己改的，在電腦上跑 python -m synox packs lock --approve {m.name} 重新核准後重新載入。")


def _install_connector(app, pack: Pack) -> None:
    m = pack.manifest

    def status(api, chat_id, user, args):
        api.send_message(chat_id, f"🔌 {m.title} 還沒接上（SYNOX v0 只登記 connector，不連外）。\n"
                                  f"接法的設計寫在這個 pack 資料夾的 README.md（{os.path.basename(m.folder)}）。")

    pack.group.leaf("status", status, "還沒接上（打了看說明）", default=True, ai=False)


def _install_mcp(app, pack: Pack) -> None:
    """mcp.transport=stdio／http：真的連（packs/mcp.py：每個 (pack, 使用者) 一條連線——stdio 是長駐子程序、
    http 是遠端 MCP（packs/mcp_http.py）；tools_allow 的工具變成葉節點）。沒寫 transport（只有 url）：照舊只登記。"""
    m = pack.manifest
    if m.mcp_connected:
        from synox.packs import mcp
        if m.mcp_stdio:
            refuse_blocked_argv(m)
        mcp.install(app, pack)
        return
    allow = "、".join(m.mcp.get("tools_allow") or [])

    def status(api, chat_id, user, args):
        api.send_message(chat_id, f"🔌 {m.title} 是 MCP 連接器，這一版只登記、還沒接上。\n允許的工具：{allow}")

    pack.group.leaf("status", status, "還沒接上（打了看說明）", default=True, ai=False)


def _tamper_notice(app, config, m: Manifest, changes: List[str]) -> None:
    """竄改只通知擁有者一次（同一份差異）。"""
    try:
        fp = pack_lock.fingerprint(changes, pack_lock.hash_files(m.folder))
        if not pack_lock.first_notice(config.data_dir, m.name, fp):
            return
        listing = "\n".join(f"• {c}" for c in changes[:20])
        app.notify_owner(f"⚠️ pack「{m.title}」（{m.name}）的檔案跟安裝時核准的不一樣，這次沒有載入：\n{listing}\n"
                         f"如果是你自己改的，在電腦上跑 python -m synox packs lock --approve {m.name} 重新核准。")
    except Exception:
        logging.exception("[PACKS] tamper notice for %s failed", m.name)


# SYNOX 系統指令佔住的群組名 → 撞到的 pack 給人看的一句話（例如 remind＝⏰ 提醒（系統），schedule/commands.py 在載入 pack 之前登記）。
SYSTEM_GROUPS_KEY = "synox_system_groups"


def system_group_problem(app, m: Manifest) -> str:
    """pack 的群組是系統指令的名字 → 一句說明（狀態 incompatible、不載入，不算壞掉）；不是 → ""。"""
    owned = (getattr(app, "extras", None) or {}).get(SYSTEM_GROUPS_KEY) or {}
    return owned.get(m.group.split(".")[0], "")


def load_all(app, config, vault=None, dirs=PACK_DIRS) -> LoadReport:
    report = LoadReport()
    packs: List[Pack] = app.extras.setdefault("synox_packs", [])
    secret_store = pack_secrets.PackSecrets(vault, server=getattr(config, "mode", "personal") == "server")
    app.extras["synox_pack_secrets"] = secret_store
    for folder in sorted(discover(dirs), key=_order):
        try:
            m = read(folder)
        except ManifestError as e:
            report.items.append(PackStatus(os.path.basename(folder), folder, "invalid", str(e)))
            logging.error("[PACKS] %s: %s", folder, e)
            continue
        item = PackStatus(m.name, folder, "loaded", kind=m.kind, version=m.version)
        report.items.append(item)
        if not config.pack_enabled(m.name):
            item.status = "disabled"
            continue
        too_old = synox_problem(m)                 # requires.synox：版本不合就不載入
        if too_old:
            item.status, item.detail = "incompatible", too_old
            continue
        system_owned = system_group_problem(app, m)    # 例：舊的 remind 工具（提醒已經是系統指令）
        if system_owned:
            item.status, item.detail = "incompatible", system_owned
            continue
        missing = missing_requirements(m, config)
        if missing:
            item.status, item.detail = "missing", f"缺 {missing}"
            continue
        no_env = envs.env_problem(m, config.data_dir)   # runtime.python／node=auto 的環境沒建好、沒有 node
        if no_env:
            item.status, item.detail = "missing", no_env
            continue
        if app.registry.node(m.group) is not None:
            item.status, item.detail = "error", f"群組 {m.group} 已經被別的 pack 用了"
            continue
        use_vault = m.storage == "vault"
        if use_vault and vault is None:
            item.status, item.detail = "error", "這個 pack 要保管箱（storage=vault），但保管箱沒有打開"
            continue
        item.lock, changes = pack_lock.verify(config.data_dir, m.name, folder)
        if item.lock == pack_lock.TAMPERED:
            item.status, item.detail = "tampered", "檔案跟核准時不一樣：" + "、".join(changes[:10])
            logging.error("[PACKS] %s tampered: %s", m.name, changes)
            _tamper_notice(app, config, m, changes)
            continue
        problems = unlocked_scan(config, m, item.lock)    # 伺服器版沒鎖的：補第 2 關（PERM-8）
        if problems is not None:
            item.scan = "failed" if problems else "passed"
        if problems:
            item.status = "rejected"
            item.detail = "沒有 packs.lock、載入時的第 2 關掃描沒過，沒有載入：" + "；".join(problems[:5])
            logging.error("[PACKS] %s rejected by load-time scan: %s", m.name, problems)
            continue
        server = getattr(config, "mode", "personal") == "server"
        store = PackStore(m.name, config.data_dir, vault if use_vault else None, per_user=server)
        pack = Pack(m, store, app, config.data_dir, config=config,
                    secret_fields=pack_secrets.managed_fields(m), secrets=secret_store)
        if item.lock == pack_lock.LOCKED:
            record = pack_lock.entry(config.data_dir, m.name) or {}
            pack.locked_files = dict(record.get("files") or {})
            pack.live = pack_lock.live_check(record, folder)
        group_rules = {**pack_group_policy(app, config, m, server), **surface_policy(m)}
        boxed_out = sandbox.restricted_reason(config, m)   # 要沙盒卻沒有真隔離 → 只給擁有者（PERM-7）
        boxed_out = boxed_out or trust_reason(config, m)   # 伺服器版第三方 python pack → 只給擁有者（PERM-8）
        if boxed_out:
            group_rules = {**group_rules, "owner_only": True}
            item.detail = boxed_out
        # /help 的那一頁標題帶穩定度（「💰 記帳（🧪 alpha）」）；網頁、AI 用的是 manifest.title，不受影響
        app.registry.define_group(m.group, help_title(m), m.summary, **group_rules)
        try:
            {"python": _install_python, "cli": _install_cli, "connector": _install_connector,
             "mcp": _install_mcp}[m.kind](app, pack)
            shared_write_admin(app, m, server)
        except Exception as e:
            logging.exception("[PACKS] %s failed to install", m.name)
            _drop_group(app.registry, m.group)
            item.status, item.detail = "error", f"{type(e).__name__}: {e}"
            continue
        apply_scope(app, m)
        if m.registered_only:
            item.status = "connector"
        packs.append(pack)
    app.extras["synox_pack_report"] = report
    return report
