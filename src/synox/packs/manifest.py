"""
pack.json 的格式與檢查（docs/pack-format.md 是人看的版本）。安全管線的第 1 關（宣告檢查）就是這支檔案。

    {
      "name": "money", "title": "💰 記帳", "summary": "記一筆、看這個月、設預算",
      "version": "0.1.0", "kind": "python",
      "group": "money",                          指令群組（/money、/money_list…）；沒寫＝name
      "access": "owner",                         owner（預設：只有你）｜member（伺服器版的成員以上；個人版＝owner）
                                                 ｜everyone（任何傳訊息給 bot 的人，伺服器版的訪客也算）
      "python": {"module": "pack"},              kind=python：資料夾裡的 pack.py，有 install(app, pack)
      "cli": {"argv": ["{python}", "./x.py"], "cwd": ".", "commands": [...]},   kind=cli
      "auth": "oauth",                           kind=connector：oauth｜token｜caldav（v2 寫成 {"type": …}）
      "requires": {"pip": [], "config": [], "env": {},  env：要有的環境變數（也是 cli 子程序唯一看得到的密鑰名）
                   "synox": ">=0.3"},              synox：SYNOX 最低版本（不合＝不載入，doctor 說明）
      "skill": "SKILL.md",
      "storage": "vault",                        vault（pack.store 落地是密文）｜plain
      "web": {"panel": "panel.html",             選用：Web UI 工具頁的面板（pack 資料夾裡的一個 .html）
              "api": ["GET /summary"]}           面板能打的 GET /api/packs/<name>/<route>（pack 用 pack.web_route 掛）
    }

pack.json v2（架構 v1 §4；在上面之上加欄位，舊的 pack 照舊可讀）：

      "kind": "mcp",                             第四種：接一個 MCP 伺服器（mcp.transport=stdio 才連；只寫 url＝只登記）
      "runtime": {"python": "../.venv/Scripts/python.exe",      {python} 的另一種寫法：相對於 pack 資料夾，
                  "python_posix": "../.venv/bin/python"},      照作業系統挑一個（cli.python 有寫就用 cli.python）
                 {"python": "auto", "node": "auto"}             auto＝安裝時建 data/envs/<pack>/（packs/envs.py）；
                                                               python=auto 時 requires.pip 只能寫 名字==版本；
                                                               node=auto 時 pack 裡要有 package.json＋package-lock.json
      "env": {"HOME_DIR": "{user_data_dir}/x"},                子程序的環境變數（跟 cli.env 合併，cli.env 優先）
      "cli": {"python": "venv", "env": {"X": "{data_dir}"},
              "commands": [{"name": "add", "effect": "WRITE", "argv": ["add", "{text}"],
                            "fields": [{"name": "text"}, {"name": "file", "kind": "path"}]}]},
      "capabilities": ["network", "subprocess", "filesystem:own", "filesystem:any", "exec"],
      "publisher": "…",
      "integrity": {"sha256": {"pack.py": "<64 hex>", …}},      打包時算（scripts/pack_zip.py）；有寫就要對得上
      "auth": {"type": "none|token|oauth|caldav|file", "fields": [...]},
               fields[]：{"name", "label", "secret": true, "env": "X_API_KEY", "kind": "text|file", "required"}；
               token／file 的由 SYNOX 收（Web UI「連接」→ 保管箱；見 packs/secrets.py），"managed": "synox"|"pack" 可以強制
      "mcp": {"url": "…", "tools_allow": ["search"], "effects": {"search": "READ"}}        只登記（不連）
      "mcp": {"transport": "stdio", "argv": ["{python}", "./server.py"],                 真的連（P4a，packs/mcp.py）：
              "env": {…}, "cwd": ".", "timeout": 60, "start_timeout": 20,                代換同 cli；每個（pack, 使用者）
              "tools_allow": ["search"], "effects": {"search": "READ"}}                  一個長駐子程序；要宣告 subprocess
      "mcp": {"transport": "http", "url": "https://…/mcp", "timeout": 60,                遠端 MCP（P4b，packs/mcp_http.py）：
              "bearer": "token", "tools_allow": […], "effects": {…}}                     url 一定 https；要宣告 network；
                                                 auth.type=token 的 secret 欄位當 Authorization: Bearer；
                                                 auth.type=oauth＋auth.oauth＝貼回網址的授權碼流程（packs/oauth.py）
              "schema_tools": ["add-tasks"]                                              （stdio／http 都可以）schema 模式：
                                                 這些工具的巢狀參數照 inputSchema 給 AI（只給 AI；packs/mcp_schema.py）；
                                                 一定要是 tools_allow 裡的工具

權限宣告（PERM-2；舊 pack 沒寫照舊相容，見 _check_scope）：

      "surfaces": ["dm"] | ["dm", "channel"]     在哪裡能用；沒寫＝["dm"]（只能私訊：loader 加 private_only）
      "data": "none" | "user" | "shared"          資料屬於誰；沒寫：python 有寫 storage＝user、沒寫＝none；
                                                 cli 樣板用了 {user_data_dir}＝user、只用 {data_dir}＝shared、都沒有＝none；
                                                 mcp stdio 照 mcp.argv／env／cwd 的樣板推（同 cli）；
                                                 connector、只登記的 mcp＝none。第 2 關（scan.py）照它檢查程式；
                                                 shared 的 WRITE／DANGER 指令在伺服器版只有管理員（loader）
      trust（core｜third-party）不在 pack.json：安裝時擁有者在報告上選，寫進 packs.lock（lock.py）

validate(raw, folder, strict=True) 是安裝時用的嚴格版（cli 的每個 command 一定要寫 effect）；
載入時 strict=False：舊的 pack（沒寫 effect＝READ）照舊能用。v2 的 pack（有任何 v2 欄位）一律嚴格。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

KINDS = ("python", "cli", "connector", "mcp")
AUTHS = ("oauth", "token", "caldav")                       # v0 的 auth 字串（connector）
AUTH_TYPES = ("none", "token", "oauth", "caldav", "file")  # v2 的 auth.type
CAPABILITIES = ("network", "subprocess", "filesystem:own", "filesystem:any", "exec")
EFFECT_NAMES = ("READ", "WRITE", "DANGER")
FIELD_KINDS = ("text", "int", "number", "bool", "path", "choice")
MAX_CHOICES = 50
# cli 的 argv／env 樣板裡 loader 會代換的名字（欄位不能取這些名字）
RESERVED_PLACEHOLDERS = ("python", "node", "pack_dir", "data_dir", "user_data_dir", "tg_id")
V2_KEYS = ("capabilities", "publisher", "integrity", "mcp", "commands", "runtime", "env")
ACCESS = ("owner", "member", "everyone")
SURFACES = ("dm", "channel")
DATA_SCOPES = ("none", "user", "shared")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
GROUP_RE = re.compile(r"^[a-z][a-z0-9]{0,15}$")
WEB_ROUTE_RE = re.compile(r"^GET /([a-z0-9][a-z0-9_-]{0,31})$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMAND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# requires.synox：一個或幾個（逗號分隔）條件，例如 ">=0.3"、">=0.3,<1.0"；只寫版本＝>=
_SPEC_RE = re.compile(r"^\s*(>=|<=|==|!=|>|<)?\s*(\d+(?:\.\d+){0,2})\s*$")
# {python} 一定要是 Python 直譯器（cli.python、runtime.python／python_posix 的檔名）：python、python3、python3.12、
# pythonw、python3.13t、pypy3（可以有 .exe）。要叫別的程式就直接寫在 argv[0]（算 pack 外的程式、T2）
PYTHON_NAME_RE = re.compile(r"^(python|pypy)(\d+(\.\d+)*)?[tw]?(\.exe)?$", re.IGNORECASE)
# runtime.python 唯一收的 ..：「pack 旁邊的 venv」（跟 cli.python="venv" 一樣；金流簿 repo 的寫法）
SIBLING_VENV_RE = re.compile(r"^\.\./\.?venv/(Scripts|bin)/[^/]+$")


def python_path_problems(label: str, value, *, relative_ok: bool) -> List[str]:
    """cli.python／runtime.python 的值：一定是 Python 直譯器的檔名、不准 ..（runtime 只收 ../.venv/…）。
    relative_ok=False（cli.python）：一定要絕對路徑或 "venv"。"""
    if not isinstance(value, str) or not value.strip():
        return []                                         # 型別錯另外講
    if value == "venv" and not relative_ok:
        return []
    if relative_ok and value == "auto":
        return []
    plain = value.replace("\\", "/")
    out = []
    if not relative_ok and not os.path.isabs(value):
        return ['cli.python 只能是絕對路徑或 "venv"（沒寫＝SYNOX 自己的 Python）']
    if ".." in plain.split("/") and not (relative_ok and SIBLING_VENV_RE.match(plain)):
        out.append(f"{label} 不能用 .. 跑出 pack 資料夾（{value!r}；"
                   "只收 ../.venv/Scripts/python.exe 這種「pack 旁邊的 venv」，會算 pack 外的程式、T2）")
    if not PYTHON_NAME_RE.match(plain.rsplit("/", 1)[-1]):
        out.append(f"{label} 要指到 Python 直譯器（檔名是 python…／pypy…，現在是 {value!r}）；"
                   "要叫別的程式請直接寫在 argv 的第一段（會算 pack 外的程式、T2，要輸入 publisher 才裝）")
    return out


class ManifestError(ValueError):
    pass


@dataclass
class Manifest:
    name: str
    title: str
    summary: str
    version: str
    kind: str
    folder: str
    group: str = ""
    access: str = "owner"
    skill: str = "SKILL.md"
    storage: str = "plain"
    python: dict = field(default_factory=dict)
    cli: dict = field(default_factory=dict)
    auth: str = ""
    requires: dict = field(default_factory=dict)
    web: dict = field(default_factory=dict)       # {"panel": "panel.html"|"", "api": ["summary", …]}（已檢查）
    raw: dict = field(default_factory=dict, repr=False)
    # ── v2 ──
    v2: bool = False
    capabilities: List[str] = field(default_factory=list)    # 沒寫＝[]（什麼都沒宣告，交給第 2 關的掃描決定）
    capabilities_declared: bool = False
    publisher: str = ""
    integrity: Dict[str, str] = field(default_factory=dict)  # 檔名（/ 分隔）→ sha256
    auth_info: dict = field(default_factory=dict)            # {"type": …, "fields": …}（v0 的字串也轉成這個）
    mcp: dict = field(default_factory=dict)
    runtime: dict = field(default_factory=dict)              # {"python": 相對路徑, "python_posix": …}
    # ── 權限宣告（PERM-2） ──
    surfaces: List[str] = field(default_factory=lambda: ["dm"])   # ["dm"]｜["dm", "channel"]
    surfaces_declared: bool = False
    data: str = "none"                                        # none｜user｜shared（沒寫照 default_data 推）
    data_declared: bool = False

    @property
    def channel_ok(self) -> bool:
        """宣告可以在頻道（群組）裡用。"""
        return "channel" in self.surfaces

    @property
    def skill_path(self) -> str:
        return os.path.join(self.folder, self.skill)

    @property
    def panel_path(self) -> str:
        return os.path.join(self.folder, self.web["panel"]) if self.web.get("panel") else ""

    @property
    def commands(self) -> List[dict]:
        return list(self.cli.get("commands") or [])

    @property
    def mcp_stdio(self) -> bool:
        """kind=mcp 而且 mcp.transport=stdio：真的會連（packs/mcp.py）。"""
        return self.kind == "mcp" and (self.mcp or {}).get("transport") == "stdio"

    @property
    def mcp_http(self) -> bool:
        """kind=mcp 而且 mcp.transport=http：遠端 MCP，真的會連（packs/mcp_http.py，P4b）。"""
        return self.kind == "mcp" and (self.mcp or {}).get("transport") == "http"

    @property
    def mcp_connected(self) -> bool:
        """kind=mcp 而且真的會連（stdio 或 http）。"""
        return self.mcp_stdio or self.mcp_http

    @property
    def registered_only(self) -> bool:
        """只登記、不連的：connector，與沒有 transport 的 mcp（只寫 url）。"""
        return self.kind == "connector" or (self.kind == "mcp" and not self.mcp_connected)

    def allows(self, capability: str) -> bool:
        """宣告了這個能力嗎（filesystem:any 包含 filesystem:own）。"""
        if capability in self.capabilities:
            return True
        return capability == "filesystem:own" and "filesystem:any" in self.capabilities


def _inside(folder: str, rel: str) -> bool:
    base = os.path.realpath(folder)
    target = os.path.realpath(os.path.join(folder, rel))
    try:
        return os.path.commonpath([base, target]) == base and target != base
    except ValueError:                           # 不同磁碟機
        return False


def parse_web(raw, folder: str, problems: List[str]) -> dict:
    """pack.json 的 web → {"panel": 相對路徑或 "", "api": [route…]}；不合的寫進 problems。"""
    if raw in (None, {}):
        return {"panel": "", "api": []}
    if not isinstance(raw, dict):
        problems.append("web 要是物件")
        return {"panel": "", "api": []}
    panel = raw.get("panel") or ""
    if panel:
        if not isinstance(panel, str) or not panel.lower().endswith(".html") or os.path.isabs(panel) \
                or ".." in panel.replace("\\", "/").split("/") or not _inside(folder, panel):
            problems.append("web.panel 要是 pack 資料夾裡的一個 .html（不能用 .. 或絕對路徑）")
            panel = ""
        elif not os.path.isfile(os.path.join(folder, panel)):
            problems.append(f"找不到 web.panel 檔 {panel}")
            panel = ""
    routes = []
    api = raw.get("api") or []
    if not isinstance(api, list):
        problems.append("web.api 要是清單，例如 [\"GET /summary\"]")
        api = []
    for item in api:
        m = WEB_ROUTE_RE.match(str(item).strip()) if isinstance(item, str) else None
        if m is None:
            problems.append(f"web.api 的 {item!r} 要寫成 \"GET /名字\"（小寫英數字、-、_；只支援 GET）")
        else:
            routes.append(m.group(1))
    return {"panel": panel, "api": routes}


def norm_effect(value) -> str:
    """"write"／"WRITE" → "WRITE"；不認得回 ""。"""
    value = str(value or "").strip().upper()
    return value if value in EFFECT_NAMES else ""


def _check_commands(commands, strict: bool, problems: List[str]) -> List[dict]:
    """cli 的 commands：名字、argv、effect、fields。回整理過的清單（effect 一律大寫）。"""
    out = []
    seen = set()
    for i, c in enumerate(commands):
        where = f"commands[{i}]"
        if not isinstance(c, dict):
            problems.append(f"{where} 要是物件")
            continue
        name = c.get("name")
        if not isinstance(name, str) or not COMMAND_RE.match(name):
            problems.append(f"{where}.name 要是小寫英數字、_（32 字內）")
            continue
        where = f"command {name}"
        if name in seen:
            problems.append(f"{where} 重複了")
        seen.add(name)
        argv = c.get("argv")
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            problems.append(f"{where} 的 argv 要是字串清單")
        effect = norm_effect(c.get("effect"))
        if c.get("effect") is not None and not effect:
            problems.append(f"{where} 的 effect 只能是 READ、WRITE 或 DANGER")
        elif not effect and strict:
            problems.append(f"{where} 沒寫 effect（READ、WRITE 或 DANGER，一定要寫）")
        for flag in ("ai", "confirm"):                    # ai: false＝不給 AI；confirm: true＝AI 呼叫前先送確認卡
            if flag in c and not isinstance(c[flag], bool):
                problems.append(f"{where} 的 {flag} 要是 true 或 false")
        fields = c.get("fields") or []
        if not isinstance(fields, list):
            problems.append(f"{where} 的 fields 要是清單")
            fields = []
        for f in fields:
            fname = f.get("name") if isinstance(f, dict) else None
            if not isinstance(fname, str) or not FIELD_RE.match(fname):
                problems.append(f"{where} 有欄位名字不對（小寫英數字、_）")
                continue
            if fname in RESERVED_PLACEHOLDERS:
                problems.append(f"{where} 的欄位不能叫 {fname}（保留給 {{{fname}}} 代換）")
            fkind = f.get("kind", "text")
            if fkind not in FIELD_KINDS:
                problems.append(f"{where} 的欄位 {fname} 的 kind 只能是 {'、'.join(FIELD_KINDS)}")
            choices = f.get("choices")
            if choices is not None and (not isinstance(choices, list) or not choices or len(choices) > MAX_CHOICES
                                        or not all(isinstance(x, str) and x.strip() for x in choices)):
                problems.append(f"{where} 的欄位 {fname} 的 choices 要是不空的字串清單（最多 {MAX_CHOICES} 個）")
            elif fkind == "choice" and not choices:
                problems.append(f"{where} 的欄位 {fname} 是 kind=choice，要寫 choices（可以選的值，字串清單）")
        out.append({**c, "effect": effect or "READ"})
    return out


def _cli_routes(web_raw: dict, api: List[str], commands: List[dict], problems: List[str]) -> Dict[str, str]:
    """kind=cli 的面板資料：web.api 的每個 route 由一個 READ、沒有必填欄位的 command 回答
    （web.routes 可以指定 {route: command}，沒寫＝同名）。"""
    mapping = web_raw.get("routes") or {}
    if not isinstance(mapping, dict):
        problems.append("web.routes 要是 {route: command}")
        mapping = {}
    by_name = {c.get("name"): c for c in commands if isinstance(c, dict)}
    out = {}
    for route in api:
        target = mapping.get(route, route)
        c = by_name.get(target)
        if c is None:
            problems.append(f"web.api 的 {route} 沒有對應的 command（cli pack 用同名的 command 或 web.routes 指定）")
        elif norm_effect(c.get("effect")) not in ("", "READ") or \
                any(isinstance(f, dict) and f.get("required") for f in c.get("fields") or []):
            problems.append(f"web.api 的 {route} 對應的 command {target} 要是 READ、而且沒有必填欄位")
        else:
            out[route] = target
    return out


def _check_auth_fields(auth: dict, problems: List[str]) -> None:
    """auth.fields[]：字串（欄位名）或 {"name", "label", "secret", "env", "kind": text|file, "required"}；
    auth.managed：synox｜pack（沒寫＝SYNOX 自己判斷，見 packs/secrets.py）。"""
    managed = auth.get("managed")
    if managed is not None and managed not in ("synox", "pack"):
        problems.append('auth.managed 只能是 "synox" 或 "pack"')
    fields = auth.get("fields")
    if fields is None:
        return
    if not isinstance(fields, list):
        problems.append("auth.fields 要是清單")
        return
    seen, envs = set(), set()
    for i, f in enumerate(fields):
        if isinstance(f, str):
            f = {"name": f}
        if not isinstance(f, dict) or not isinstance(f.get("name"), str) or not FIELD_RE.match(f["name"]):
            problems.append(f"auth.fields[{i}] 的 name 要是小寫英數字、_（32 字內）")
            continue
        name = f["name"]
        if name in seen:
            problems.append(f"auth.fields 的 {name} 重複了")
        seen.add(name)
        env = f.get("env")
        if env is not None:
            if not isinstance(env, str) or not ENV_NAME_RE.match(env):
                problems.append(f"auth.fields 的 {name}.env 要是環境變數名字（英數字、_）")
            elif env.upper() in envs:
                problems.append(f"auth.fields 的 env {env} 重複了")
            else:
                envs.add(env.upper())
        if f.get("kind") is not None and f.get("kind") not in ("text", "file"):
            problems.append(f"auth.fields 的 {name}.kind 只能是 text 或 file")
        for flag in ("secret", "required"):
            if f.get(flag) is not None and not isinstance(f.get(flag), bool):
                problems.append(f"auth.fields 的 {name}.{flag} 要是 true 或 false")
        for text in ("label", "ask", "help"):
            if f.get(text) is not None and (not isinstance(f.get(text), str) or len(f[text]) > 200):
                problems.append(f"auth.fields 的 {name}.{text} 要是 200 字內的字串")


MCP_TRANSPORTS = ("stdio", "http")
OAUTH_RECEIVERS = ("paste", "loopback")


def check_https_url(url, label: str, problems: List[str]) -> str:
    """遠端 MCP 用的網址：一定是 https、有主機、不帶帳密（user:pass@）、不帶 #、沒有 {樣板}。回主機（小寫，含埠）。"""
    from urllib.parse import urlsplit
    if not isinstance(url, str) or not url.strip():
        problems.append(f"{label} 要是網址（https://…）")
        return ""
    if any(c in url for c in "{} \t\r\n"):
        problems.append(f"{label} 不能有空白或 {{樣板}}（要寫死一個網址）")
        return ""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        problems.append(f"{label} 看不懂：{url[:80]}")
        return ""
    if parts.scheme != "https":
        problems.append(f"{label} 一定要是 https://（現在是 {parts.scheme or '沒寫'}://；不收明文 http，token 會被看到）")
        return ""
    if not parts.hostname:
        problems.append(f"{label} 沒有主機名稱")
        return ""
    if parts.username is not None or parts.password is not None:
        problems.append(f"{label} 不能把帳號密碼寫在網址裡（user:pass@）；token 用 auth.fields，SYNOX 會放在 Authorization 標頭")
        return ""
    if parts.fragment:
        problems.append(f"{label} 不能有 #…")
        return ""
    return parts.hostname.lower() + (f":{port}" if port else "")


def _check_mcp_http(mcp: dict, caps: List[str], auth: dict, problems: List[str]) -> None:
    """transport=http（P4b，packs/mcp_http.py）：url 一定 https；capabilities 要有 network；沒有程式、沒有 argv。
    auth.type=token：auth.fields 的一個 secret 欄位當 Bearer（mcp.bearer 指定，沒寫＝第一個 secret 欄位）；
    auth.type=oauth：auth.oauth 的授權碼流程（貼回網址，預設 receiver=paste；loopback 只有介面，執行時拒）。"""
    check_https_url(mcp.get("url"), "mcp.url", problems)
    for key in ("argv", "env", "cwd", "start_timeout"):
        if key in mcp:
            problems.append(f"mcp.transport 是 http 就不要寫 mcp.{key}（遠端 MCP 沒有子程序）")
    if "headers" in mcp:
        problems.append("mcp.headers 不收：遠端 MCP 只送 SYNOX 自己的標頭，token 用 auth.fields")
    value = mcp.get("timeout")
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 3600):
        problems.append("mcp.timeout 要是 1～3600 的秒數")
    if "network" not in caps:
        problems.append("mcp.transport 是 http：SYNOX 會連到 mcp.url，capabilities 一定要宣告 network")
    if "subprocess" in caps or "exec" in caps or "filesystem:any" in caps:
        problems.append("mcp.transport 是 http 沒有程式在這台跑：capabilities 只要 network（不要 subprocess、exec、filesystem:any）")
    kind = auth.get("type", "none")
    if kind not in ("none", "token", "oauth"):
        problems.append("mcp.transport 是 http：auth.type 只能是 none、token 或 oauth")
    secret_names = [f.get("name") if isinstance(f, dict) else f for f in auth.get("fields") or []
                    if (isinstance(f, dict) and f.get("secret")) or isinstance(f, str)]
    bearer = mcp.get("bearer")
    if bearer is not None and kind != "token":
        problems.append("mcp.bearer 只給 auth.type=token 用")
    if kind == "token":
        if not secret_names:
            problems.append("auth.type 是 token：auth.fields 要有一個 secret 欄位（它的值會當 Authorization: Bearer 送出）")
        elif bearer is not None and bearer not in secret_names:
            problems.append(f"mcp.bearer 要是 auth.fields 裡的一個 secret 欄位（{'、'.join(map(str, secret_names))}）")
    oauth = auth.get("oauth")
    if kind == "oauth":
        if not isinstance(oauth, dict):
            problems.append('auth.type 是 oauth：要寫 auth.oauth（{"authorize_url", "token_url", "client_id", "scope"}）')
            return
        for key in ("authorize_url", "token_url"):
            check_https_url(oauth.get(key), f"auth.oauth.{key}", problems)
        if not isinstance(oauth.get("client_id"), str) or not oauth["client_id"].strip():
            problems.append("auth.oauth.client_id 要寫（事先在服務那邊登記的 public client）")
        if oauth.get("scope") is not None and not isinstance(oauth.get("scope"), str):
            problems.append("auth.oauth.scope 要是字串（空白分隔）")
        if oauth.get("receiver", "paste") not in OAUTH_RECEIVERS:
            problems.append(f"auth.oauth.receiver 只能是 {'、'.join(OAUTH_RECEIVERS)}（沒寫＝paste：使用者把網址列貼回來）")
        redirect = oauth.get("redirect_uri")
        if redirect is not None and (not isinstance(redirect, str) or
                                     not re.match(r"^http://(127\.0\.0\.1|localhost)(:\d{1,5})?/", redirect)):
            problems.append("auth.oauth.redirect_uri 只能是 http://127.0.0.1:<埠>/…（SYNOX 不開埠；瀏覽器轉過去打不開，使用者把網址貼回來）")
    elif oauth is not None:
        problems.append("auth.oauth 只給 auth.type=oauth 用")


def _check_mcp_transport(mcp: dict, caps: List[str], problems: List[str], auth: Optional[dict] = None) -> None:
    """mcp.transport：沒寫＝只登記（舊的寫法，只收 url）；"stdio"＝SYNOX 開一個子程序講 MCP（packs/mcp.py）；
    "http"＝遠端 MCP（Streamable HTTP，packs/mcp_http.py，_check_mcp_http）。
    stdio 要 argv（字串清單，代換同 cli）、capabilities 要有 subprocess；env／cwd／timeout／start_timeout 選填。"""
    transport = mcp.get("transport")
    if transport is None:
        return
    if transport not in MCP_TRANSPORTS:
        problems.append(f"mcp.transport 只能是 {'、'.join(MCP_TRANSPORTS)}（沒寫＝只登記、不連）")
        return
    if transport == "http":
        _check_mcp_http(mcp, caps, auth or {}, problems)
        return
    argv = mcp.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        problems.append("mcp.transport 是 stdio 要寫 mcp.argv（啟動 MCP 伺服器的命令列，字串清單，例如 [\"{python}\", \"./server.py\"]）")
    if mcp.get("url"):
        problems.append("mcp.transport 是 stdio 就不要寫 mcp.url（兩種連法只能選一種）")
    env = mcp.get("env")
    if env is not None and (not isinstance(env, dict) or
                            not all(isinstance(k, str) and ENV_NAME_RE.match(k) and isinstance(v, str)
                                    for k, v in env.items())):
        problems.append("mcp.env 要是 {環境變數名字: 字串}")
    if mcp.get("cwd") is not None and not isinstance(mcp.get("cwd"), str):
        problems.append("mcp.cwd 要是字串（相對於 pack 資料夾）")
    for key in ("timeout", "start_timeout"):
        value = mcp.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 3600):
            problems.append(f"mcp.{key} 要是 1～3600 的秒數")
    if "subprocess" not in caps:
        problems.append("mcp.transport 是 stdio：SYNOX 會開一個子程序跑 MCP 伺服器，capabilities 一定要宣告 subprocess")


def mcp_templates(mcp: dict) -> List[tuple]:
    """kind=mcp stdio 會被代換的樣板：[(在哪, 字串)…]（mcp.argv、mcp.env、mcp.cwd）。"""
    out: List[tuple] = []
    if not isinstance(mcp, dict):
        return out
    for i, token in enumerate(mcp.get("argv") or []):
        out.append((f"mcp.argv[{i}]", str(token)))
    env = mcp.get("env") or {}
    if isinstance(env, dict):
        out += [(f"mcp.env.{k}", str(v)) for k, v in env.items()]
    if isinstance(mcp.get("cwd"), str):
        out.append(("mcp.cwd", mcp["cwd"]))
    return out


def _check_v2(raw: dict, kind, problems: List[str]) -> dict:
    """v2 的欄位：capabilities、publisher、integrity、auth、mcp。回整理過的值。"""
    caps_raw = raw.get("capabilities")
    caps: List[str] = []
    if caps_raw is not None:
        if not isinstance(caps_raw, list) or not all(isinstance(c, str) for c in caps_raw):
            problems.append("capabilities 要是字串清單")
        else:
            bad = [c for c in caps_raw if c not in CAPABILITIES]
            if bad:
                problems.append(f"capabilities 不認得 {'、'.join(bad)}（只能是 {'、'.join(CAPABILITIES)}）")
            caps = [c for c in caps_raw if c in CAPABILITIES]
    publisher = raw.get("publisher", "")
    if not isinstance(publisher, str) or len(publisher) > 100:
        problems.append("publisher 要是 100 字內的字串")
        publisher = ""
    integrity: Dict[str, str] = {}
    integ = raw.get("integrity")
    if integ is not None:
        sha = integ.get("sha256") if isinstance(integ, dict) else None
        if not isinstance(sha, dict):
            problems.append('integrity 要寫成 {"sha256": {"檔名": "64 個 16 進位字"}}')
        else:
            for k, v in sha.items():
                rel = str(k).replace("\\", "/")
                if os.path.isabs(rel) or rel.startswith("/") or ".." in rel.split("/") or \
                        not SHA256_RE.match(str(v).lower()):
                    problems.append(f"integrity.sha256 的 {k!r} 不對（檔名不能有 .. 或絕對路徑；值要 64 個 16 進位字）")
                else:
                    integrity[rel] = str(v).lower()
    auth = raw.get("auth")
    if isinstance(auth, dict):
        auth_info = dict(auth)
        auth_info.setdefault("type", "none")
        if auth_info["type"] not in AUTH_TYPES:
            problems.append(f"auth.type 只能是 {'、'.join(AUTH_TYPES)}")
        _check_auth_fields(auth_info, problems)
    elif isinstance(auth, str) and auth:
        auth_info = {"type": auth}
    else:
        auth_info = {"type": "none"}
    if kind == "connector" and auth_info.get("type") not in AUTHS + ("file",):
        problems.append(f"kind=connector 要寫 auth（{'、'.join(AUTHS)}；v2 的 auth.type 也可以是 file）")
    mcp = raw.get("mcp") or {}
    if kind == "mcp" or mcp:
        if not isinstance(mcp, dict):
            problems.append("mcp 要是物件")
            mcp = {}
        allow = mcp.get("tools_allow")
        if not isinstance(allow, list) or not allow or not all(isinstance(t, str) and t for t in allow):
            problems.append("mcp.tools_allow 要是不空的工具名清單（只允許清單上的工具）")
            allow = []
        effects = mcp.get("effects") or {}
        if not isinstance(effects, dict):
            problems.append("mcp.effects 要是物件（工具名 → READ／WRITE／DANGER）")
            effects = {}
        missing = [t for t in allow if not norm_effect(effects.get(t))]
        if missing:
            problems.append(f"mcp.effects 沒寫這些工具的 effect：{'、'.join(missing)}（每個允許的工具都要寫）")
        mcp = {**mcp, "tools_allow": list(allow), "effects": {t: norm_effect(effects.get(t)) for t in allow}}
        nested = mcp.get("schema_tools")
        if nested is not None:
            if not isinstance(nested, list) or not all(isinstance(t, str) and t for t in nested):
                problems.append("mcp.schema_tools 要是工具名清單（這些工具的巢狀參數照 inputSchema 給 AI）")
            else:
                outside = [t for t in nested if t not in allow]
                if outside:
                    problems.append(f"mcp.schema_tools 只能列 tools_allow 裡的工具（{'、'.join(outside)} 不在裡面）")
                mcp["schema_tools"] = [t for t in dict.fromkeys(nested) if t in allow]
        _check_mcp_transport(mcp, caps, problems, auth_info)
    return {"capabilities": caps, "capabilities_declared": caps_raw is not None, "publisher": publisher,
            "integrity": integrity, "auth_info": auth_info, "mcp": mcp}


def parse_spec(spec) -> List[tuple]:
    """requires.synox 的字串 → [(運算子, (主, 次, 修))…]；寫錯丟 ValueError。"""
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("requires.synox 要是版本條件字串，例如 \">=0.3\"")
    out = []
    for part in spec.split(","):
        m = _SPEC_RE.match(part)
        if m is None:
            raise ValueError(f"requires.synox 的 {part.strip()!r} 看不懂（寫成 >=0.3、<1.0 這樣，可以用逗號接好幾個）")
        nums = [int(x) for x in m.group(2).split(".")]
        out.append((m.group(1) or ">=", tuple(nums + [0] * (3 - len(nums)))))
    return out


def _version_tuple(text: str) -> tuple:
    nums = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text or "0"))
    return tuple(int(x or 0) for x in nums.groups()) if nums else (0, 0, 0)


_OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b,
        "<": lambda a, b: a < b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


def synox_problem(m: "Manifest", current: Optional[str] = None) -> Optional[str]:
    """requires.synox 跟這台的 SYNOX 版本合不合；不合回一句給人看的話，合（或沒寫）回 None。"""
    spec = (m.requires or {}).get("synox")
    if not spec:
        return None
    if current is None:
        from synox import __version__ as current
    have = _version_tuple(current)
    try:
        clauses = parse_spec(spec)
    except ValueError as e:
        return str(e)
    if all(_OPS[op](have, want) for op, want in clauses):
        return None
    too_old = any(op in (">=", ">", "==") and have < want for op, want in clauses)
    hint = "先更新 SYNOX（重跑 Setup.bat 或 git pull）再用這個 pack" if too_old else         "這個 pack 還沒支援這一版的 SYNOX，請向 pack 的作者要新版"
    return f"這個 pack 要 SYNOX {spec.strip()}，這台是 {current}：{hint}"


def secret_env_names(m: "Manifest") -> List[str]:
    """要讓 cli 子程序看得到的環境變數名字（requires.env＋auth.fields[].env）。
    JsonCli 預設把 *_TOKEN、*_API_KEY 這類名字從子程序環境拿掉，只有這裡列的會放行。"""
    names: List[str] = []
    env = (m.requires or {}).get("env") or {}
    names += [k for k in (env if isinstance(env, (dict, list)) else []) if isinstance(k, str)]
    for f in (m.auth_info or {}).get("fields") or []:
        if isinstance(f, dict) and isinstance(f.get("env"), str):
            names.append(f["env"])
    out: List[str] = []
    for n in names:
        if ENV_NAME_RE.match(n) and n not in out:
            out.append(n)
    return out


def _check_requires(requires: dict, problems: List[str]) -> None:
    env = requires.get("env")
    if env is not None:
        names = list(env) if isinstance(env, (dict, list)) else None
        if names is None or not all(isinstance(n, str) and ENV_NAME_RE.match(n) for n in names):
            problems.append("requires.env 要是環境變數名字的清單或物件（英數字、_）")
    if "synox" in requires:
        try:
            parse_spec(requires["synox"])
        except ValueError as e:
            problems.append(str(e))


# ── 權限宣告：surfaces、data（PERM-2） ─────────────────────────────────

def cli_templates(cli: dict) -> List[tuple]:
    """kind=cli 會被代換的每一段樣板：[(在哪, 字串)…]（cli.argv、cli.env（已含最上層 env）、cli.cwd、
    commands[].argv、commands[].stdin）。"""
    out: List[tuple] = []
    for i, token in enumerate(cli.get("argv") or []):
        out.append((f"cli.argv[{i}]", str(token)))
    env = cli.get("env") or {}
    if isinstance(env, dict):
        out += [(f"env.{k}", str(v)) for k, v in env.items()]
    if isinstance(cli.get("cwd"), str):
        out.append(("cli.cwd", cli["cwd"]))
    for c in cli.get("commands") or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        out += [(f"command {name} argv[{i}]", str(t)) for i, t in enumerate(c.get("argv") or [])]
        if isinstance(c.get("stdin"), str):
            out.append((f"command {name} stdin", c["stdin"]))
    return out


def default_data(raw: dict, kind, cli: dict) -> str:
    """沒寫 data 時的預設：python 有寫 storage＝user（沒寫＝none）；cli 樣板用了 {user_data_dir}＝user、
    只用 {data_dir}＝shared、都沒有＝none（兩個都用＝user，第 2 關會要作者明寫 shared）；其他＝none。"""
    if kind == "python":
        return "user" if "storage" in raw else "none"
    if kind in ("cli", "mcp"):
        texts = [t for _w, t in (cli_templates(cli) if kind == "cli" else mcp_templates(raw.get("mcp") or {}))]
        if any("{user_data_dir}" in t for t in texts):
            return "user"
        if any("{data_dir}" in t for t in texts):
            return "shared"
    return "none"


def _check_scope(raw: dict, kind, cli: dict, problems: List[str]) -> dict:
    """surfaces（["dm"]｜["dm", "channel"]，沒寫＝["dm"]）、data（none｜user｜shared，沒寫照 default_data）。"""
    surfaces_raw = raw.get("surfaces")
    surfaces = ["dm"]
    if surfaces_raw is not None:
        if not isinstance(surfaces_raw, list) or not surfaces_raw or \
                not all(isinstance(s, str) for s in surfaces_raw):
            problems.append('surfaces 要是清單：["dm"] 或 ["dm", "channel"]')
        else:
            bad = [s for s in surfaces_raw if s not in SURFACES]
            if bad:
                problems.append(f"surfaces 不認得 {'、'.join(bad)}（只能是 dm、channel）")
            elif "dm" not in surfaces_raw:
                problems.append('surfaces 一定要有 "dm"（["dm"] 或 ["dm", "channel"]）')
            elif len(set(surfaces_raw)) != len(surfaces_raw):
                problems.append("surfaces 有重複")
            else:
                surfaces = [s for s in SURFACES if s in surfaces_raw]
    data_raw = raw.get("data")
    if data_raw is None:
        data = default_data(raw, kind, cli)
    elif data_raw not in DATA_SCOPES:
        problems.append("data 只能是 none、user 或 shared")
        data = "none"
    else:
        data = data_raw
    if "channel" in surfaces and data == "user":
        hint = "" if data_raw is not None else f"（沒寫 data，照預設推成 user：{_data_hint(kind)}）"
        problems.append('surfaces 有 "channel" 但 data 是 user：每個人自己的資料不能在頻道裡用'
                        f'（要嘛拿掉 channel，要嘛資料不是個人的就寫 "data": "shared" 或 "none"）{hint}')
    return {"surfaces": surfaces, "surfaces_declared": surfaces_raw is not None,
            "data": data, "data_declared": data_raw is not None}


def _data_hint(kind) -> str:
    return {"python": "python pack 寫了 storage", "cli": "cli 樣板用了 {user_data_dir}",
            "mcp": "mcp 樣板用了 {user_data_dir}"}.get(kind, "")


def validate(raw: dict, folder: str, strict: bool = False) -> Manifest:
    """raw（pack.json 的內容）→ Manifest；不合就丟 ManifestError（訊息說哪裡不對）。

    strict=True（安裝時）：cli 的每個 command 一定要寫 effect。strict=False（載入時）：舊 pack 照舊能用。"""
    problems: List[str] = []
    if not isinstance(raw, dict):
        raise ManifestError("pack.json 最外層要是 {…} 物件")
    for key in ("name", "title", "summary", "version", "kind"):
        if not isinstance(raw.get(key), str) or not raw.get(key).strip():
            problems.append(f"少了 {key}")
    name = str(raw.get("name", ""))
    if name and not NAME_RE.match(name):
        problems.append(f"name {name!r} 只能用小寫英數字、-、_（32 字內）")
    version = str(raw.get("version", ""))
    if version and not VERSION_RE.match(version):
        problems.append(f"version {version!r} 要像 0.1.0")
    kind = raw.get("kind")
    if kind and kind not in KINDS:
        problems.append(f"kind 只能是 {'、'.join(KINDS)}（現在是 {kind!r}）")
    group = str(raw.get("group") or name.replace("-", "").replace("_", ""))
    if group and not GROUP_RE.match(group):
        problems.append(f"group {group!r} 只能用小寫英數字（16 字內）")
    access = raw.get("access", "owner")
    if access not in ACCESS:
        problems.append("access 只能是 owner、member 或 everyone")
    storage = raw.get("storage", "plain")
    if storage not in ("vault", "plain"):
        problems.append("storage 只能是 vault 或 plain")
    skill = raw.get("skill", "SKILL.md")
    if not isinstance(skill, str) or not os.path.isfile(os.path.join(folder, skill)):
        problems.append(f"找不到 skill 檔 {skill}")
    if kind == "python":
        module = (raw.get("python") or {}).get("module", "pack")
        if not os.path.isfile(os.path.join(folder, f"{module}.py")):
            problems.append(f"kind=python 但找不到 {module}.py")
    v2 = any(k in raw for k in V2_KEYS) or isinstance(raw.get("auth"), dict)
    cli = raw.get("cli") or {}
    if not isinstance(cli, dict):
        problems.append("cli 要是物件")
        cli = {}
    cli = dict(cli)
    if kind == "cli":
        if not cli.get("commands") and isinstance(raw.get("commands"), list):
            cli["commands"] = raw["commands"]           # v2 寫法：commands 放最上層
        if not isinstance(cli.get("argv"), list) or not cli.get("argv") or \
                not all(isinstance(a, str) for a in cli["argv"]):
            problems.append("kind=cli 要有 cli.argv（命令列程式的前幾段，字串清單）")
        if not isinstance(cli.get("commands"), list) or not cli.get("commands"):
            problems.append("kind=cli 要有 cli.commands（至少一個子指令）")
        else:
            cli["commands"] = _check_commands(cli["commands"], strict or v2, problems)
        env = cli.get("env") or {}
        top_env = raw.get("env") or {}
        for label, value in (("cli.env", env), ("env", top_env)):
            if not isinstance(value, dict) or \
                    not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                problems.append(f"{label} 要是 {{名字: 字串}}")
        if isinstance(env, dict) and isinstance(top_env, dict):
            cli["env"] = {**top_env, **env}             # 最上層的 env（金流簿的寫法）＋ cli.env，cli.env 優先
    # cli.python 不管 kind 都檢查：loader 代換 {python} 時 mcp stdio 也讀它（envs.python_target）
    python = cli.get("python")
    if python is not None and (not isinstance(python, str) or
                               not (python == "venv" or os.path.isabs(python))):
        problems.append('cli.python 只能是絕對路徑或 "venv"（沒寫＝SYNOX 自己的 Python）')
    elif python is not None:
        problems += python_path_problems("cli.python", python, relative_ok=False)
    runtime = raw.get("runtime") or {}
    if not isinstance(runtime, dict):
        problems.append("runtime 要是物件")
        runtime = {}
    for key in ("python", "python_posix", "node"):
        if key in runtime and (not isinstance(runtime[key], str) or not runtime[key].strip()):
            problems.append(f"runtime.{key} 要是路徑（相對於 pack 資料夾，或絕對路徑）或 \"auto\"")
        elif key in runtime and key != "node":
            problems += python_path_problems(f"runtime.{key}", runtime[key], relative_ok=True)
    auto_py = any(runtime.get(k) == "auto" for k in ("python", "python_posix"))
    if (auto_py or "node" in runtime) and kind != "cli":
        problems.append("runtime.python=auto 和 runtime.node 只給 kind=cli 用")
    if auto_py:
        if cli.get("python"):
            problems.append("runtime.python 是 auto 時不要再寫 cli.python（兩個都決定 {python}）")
        from synox.packs.envs import pin_problems
        problems += pin_problems((raw.get("requires") or {}).get("pip") if isinstance(raw.get("requires"), dict)
                                 else None)
    if runtime.get("node") == "auto":
        missing = [f for f in ("package.json", "package-lock.json") if not os.path.isfile(os.path.join(folder, f))]
        if missing:
            problems.append("runtime.node 是 auto，pack 裡要有 " + "、".join(missing)
                            + "（用 npm ci 照 package-lock.json 裝，版本固定）")
    extra = _check_v2(raw, kind, problems)
    extra.update(_check_scope(raw, kind, cli, problems))
    requires = raw.get("requires") or {}
    if not isinstance(requires, dict):
        problems.append("requires 要是物件")
        requires = {}
    _check_requires(requires, problems)
    web = parse_web(raw.get("web"), folder, problems)
    if kind == "cli" and web["api"] and isinstance(cli.get("commands"), list):
        web["routes"] = _cli_routes(raw.get("web") or {}, web["api"], cli["commands"], problems)
    if problems:
        raise ManifestError("；".join(problems))
    auth_type = extra["auth_info"].get("type", "none")
    return Manifest(name=name, title=raw["title"], summary=raw["summary"], version=version, kind=kind,
                    folder=folder, group=group, access=access, skill=skill, storage=storage,
                    python=dict(raw.get("python") or {}), cli=cli, auth="" if auth_type == "none" else auth_type,
                    requires=dict(requires), web=web, raw=dict(raw), v2=v2,
                    runtime={k: v for k, v in runtime.items() if k in ("python", "python_posix", "node")}, **extra)


def read(folder: str, strict: bool = False) -> Manifest:
    path = os.path.join(folder, "pack.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except OSError as e:
        raise ManifestError(f"讀不到 pack.json：{e}")
    except ValueError as e:
        raise ManifestError(f"pack.json 不是合法的 JSON：{e}")
    return validate(raw, folder, strict=strict)


def missing_requirements(m: Manifest, config) -> Optional[str]:
    """requires.config（config.json 要有的欄位）、requires.env（環境變數）缺了哪些；沒缺回 None。"""
    missing = [k for k in (m.requires.get("config") or []) if not config.get(k)]
    env = m.requires.get("env") or {}
    missing += [f"環境變數 {k}" for k in (env if isinstance(env, (dict, list)) else []) if not os.environ.get(k)]
    return "、".join(missing) if missing else None
