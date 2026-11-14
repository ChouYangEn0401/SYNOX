"""
pack.json 的格式與檢查（docs/pack-format.md 是人看的版本）。安全管線的第 1 關（宣告檢查）就是這支檔案。

    {
      "name": "money", "title": "💰 記帳", "summary": "記一筆、看這個月、設預算",
      "version": "0.1.0", "kind": "python",
      "group": "money",                          指令群組（/money、/money_list…）；沒寫＝name
      "category": "生活",                        選填：網頁工具頁「建議放在哪個群組」（給人看的名字，24 字內；
                                                 沒寫＝「未分類」；使用者自己排的優先，見 web/toolpage.py）
      "stage": "alpha",                          選填：多穩定 test｜alpha｜beta｜stable（沒寫＝alpha；安裝時寫錯＝拒）
                                                 /help、網頁工具頁、安裝報告、doctor 顯示「🧪 alpha」這種標籤
      "access": "owner",                       owner（預設：只有你）｜member（伺服器版的成員以上；個人版＝owner）
                                                 ｜everyone（任何傳訊息給 bot 的人，伺服器版的訪客也算）
      "python": {"module": "pack"},              kind=python：資料夾裡的 pack.py，有 install(app, pack)
      "cli": {"argv": ["{python}", "./x.py"], "cwd": ".", "commands": [...]},   kind=cli
      "auth": "oauth",                           kind=connector：oauth｜token｜caldav（v2 寫成 {"type": …}）
      "requires": {"pip": [], "config": [], "env": {},  env：要有的環境變數（也是 cli 子程序唯一看得到的密鑰名）
                   "synox": ">=0.3",               synox：SYNOX 最低版本（不合＝不載入，doctor 說明）
                   "sdk": ">=0.2,<0.3"},           sdk：照哪一版 SDK 介面寫的（對 synox.sdk.author.SDK_VERSION；不合＝不裝、不載入）
      "skill": "SKILL.md",
      "storage": "vault",                        vault（pack.store 落地是密文）｜plain
      "web": {"panel": "panel.html",             選用：Web UI 工具頁的面板（pack 資料夾裡的一個 .html）
              "api": ["GET /summary"]}           面板能打的 GET /api/packs/<name>/<route>（pack 用 pack.web_route 掛）
      "health": {"check": "ping"}                選填：工具壞掉時 SYNOX 重新檢查用的唯讀指令（health_problem；docs/tool-health.md）
      "help": {"featured": ["add"],              選填：指令的白話說明與範例（/help 的卡片、網頁「💡 範例」；只給人看、不進 AI）
               "commands": {"add": {"plain": "把一筆花掉的錢記下來", "examples": [{"text": "120 午餐", "note": "…"}],
                                    "alias_suggest": ["記帳"]}}}      規則在 synox/helpui/examples.py（安裝時嚴格、載入時壞的丟掉）
    }

pack.json v2（架構 v1 §4；在上面之上加欄位，舊的 pack 照舊可讀）：

      "kind": "mcp",                             第四種：接一個 MCP 伺服器（mcp.transport=stdio 才連；只寫 url＝只登記）
      "runtime": {"python": "../.venv/Scripts/python.exe",      {python} 的另一種寫法：相對於 pack 資料夾，
                  "python_posix": "../.venv/bin/python"},      照作業系統挑一個（cli.python 有寫就用 cli.python）
                 {"python": "auto", "node": "auto"}             auto＝安裝時建 data/envs/<pack>/（packs/envs.py）；
                                                               python=auto 時 requires.pip 只能寫 名字==版本；
                                                               node=auto 時 pack 裡要有 package.json＋package-lock.json
                 {"container": {"image": "ghcr.io/x/y@sha256:…", …}}   S0：容器（packs/container.py 的第 1 關；
                                                               kind=cli／mcp stdio；image 一定帶 digest、不收 privileged…）
      "env": {"HOME_DIR": "{user_data_dir}/x"},                子程序的環境變數（跟 cli.env 合併，cli.env 優先）
      "cli": {"python": "venv", "env": {"X": "{data_dir}"},
              "commands": [{"name": "add", "effect": "WRITE", "argv": ["add", "{text}"], "summary": "記一則",
                            "fields": [{"name": "text"}, {"name": "file", "kind": "path"}]}]},
               fields[]：{"name", "ask": 問人的那句（也是 AI 的參數說明）, "help": 網頁表單的補充說明,
                          "kind", "choices", "required": true|false, "default": 沒填時用的值}
               （安裝時 strict 檢查型別：ask／help／summary 是 200 字內的一行字、required 是布林、
                default 是字串／數字／布林而且合 kind／choices）
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
MAX_CATEGORY = 24                 # category：網頁工具頁的建議群組名（給人看的字）
MAX_DOC_TEXT = 200                # commands[].summary、fields[].ask／help：一行字
# stage：這個工具多穩定（作者自己標的；/help、網頁工具頁、安裝報告、doctor 都顯示）。沒寫＝alpha。
# 標籤一律「符號＋英文字」（不只靠顏色）；說明給安裝報告與網頁的 title 用。
STAGES = ("test", "alpha", "beta", "stable")
DEFAULT_STAGE = "alpha"
STAGE_INFO = {
    "test": ("🔧", "測試中", "只給開發者試：隨時會改、可能壞掉，不要拿來放重要的資料"),
    "alpha": ("🧪", "早期版", "能用，但還沒在真的服務上長時間用過；指令與資料格式之後可能會改"),
    "beta": ("🚧", "公測版", "功能齊了、有人實際用過一陣子；可能還有小問題，資料格式不會隨便改"),
    "stable": ("⭐", "穩定版", "長時間實際使用過、有測試；不相容的改動會升主版號並寫清楚怎麼搬"),
}
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")
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
MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")              # python.module：pack 資料夾裡的 <名字>.py
# requires.synox：一個或幾個（逗號分隔）條件，例如 ">=0.3"、">=0.3,<1.0"；只寫版本＝>=
_SPEC_RE = re.compile(r"^\s*(>=|<=|==|!=|>|<)?\s*(\d+(?:\.\d+){0,2})\s*$")
# {python} 一定要是 Python 直譯器（cli.python、runtime.python／python_posix 的檔名）：python、python3、python3.12、
# pythonw、python3.13t、pypy3（可以有 .exe）。要叫別的程式就直接寫在 argv[0]（算 pack 外的程式、T2）
PYTHON_NAME_RE = re.compile(r"^(python|pypy)(\d+(\.\d+)*)?[tw]?(\.exe)?$", re.IGNORECASE)
# runtime.python 唯一收的 ..：「pack 旁邊的 venv」（跟 cli.python="venv" 一樣；金流簿 repo 的寫法）
SIBLING_VENV_RE = re.compile(r"^\.\./\.?venv/(Scripts|bin)/[^/]+$")


# 審查 C #C2：pack 寫的子程序環境變數（cli.env、最上層 env、mcp.env）不能用這些名字——它們會讓「合法的」直譯器
# 在開始跑 pack 的程式之前，先載入 pack 外、沒鎖、沒掃過的程式碼（PYTHONPATH 的 sitecustomize.py／.pth、PYTHONHOME、
# PYTHONSTARTUP、NODE_OPTIONS=--require、POSIX 的 PATH 換掉 argv[0] 找到的程式、LD_PRELOAD…）。
# 不分大小寫（Windows 的環境變數名不分大小寫）。這是黑名單：擋常見的，不保證涵蓋每一種程式的每一個變數
ENV_PYTHON_OK = ("PYTHONIOENCODING", "PYTHONUTF8", "PYTHONUNBUFFERED")
ENV_BANNED = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "NODE_OPTIONS", "NODE_PATH", "BASH_ENV", "ENV",
              "PERL5LIB", "PERL5OPT", "PERLLIB", "RUBYLIB", "RUBYOPT", "PSMODULEPATH", "PHP_INI_SCAN_DIR",
              "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "DOTNET_STARTUP_HOOKS", "LUA_PATH", "LUA_CPATH",
              "LUA_INIT", "GCONV_PATH")
ENV_BANNED_PREFIXES = ("PYTHON", "LD_", "DYLD_", "PIP_", "NPM_CONFIG_", "COR_", "CORECLR_")
# PYTHONPATH 只收 pack 自己的資料夾（或底下的子資料夾）：{pack_dir} 或 {pack_dir}/lib，不能有 ..、;、:
PYTHONPATH_OK_RE = re.compile(r"^\{pack_dir\}(/[A-Za-z0-9_.-]+)*/?$")


# 審查 C #C4：UNC／裝置路徑（\\主機\分享、//主機/分享、\\?\、\\.\、\??\）。Windows 碰到這種路徑（realpath、exists、
# isfile…）就會用目前的帳號對那台主機發 SMB 連線（NetNTLM 雜湊外洩）——而第 1、2 關在安裝者按確認之前就會跑。
# 只看字串，不碰檔案系統。一段字的開頭，或 = ; , 空白、引號後面出現 // 都算（--file=\\主機\x 也是）
# argv 裡的字：//主機/分享（要有第二個 /，所以 cscript 的 //E:jscript、//B 這種選項不算）、//?/、//./、/??/
_UNC_RE = re.compile(r"(^|[=;,\s\"'])(//[^/]+/|/\?\?/)")


def unc_like(text, strict: bool = False) -> bool:
    """這段字裡有沒有 UNC／裝置路徑（反斜線、正斜線都算）。只做字串判斷。
    strict=True（一定是路徑的欄位：cli.python、cwd、skill…）：// 開頭就算（\\\\主機 沒有分享名也一樣不碰）。"""
    plain = str(text).replace("\\", "/")
    if strict and plain.lstrip().startswith(("//", "/??/")):
        return True
    return bool(_UNC_RE.search(plain))


def _unc_strings(raw: dict):
    """pack.json 裡第 1、2 關會拿去當路徑用的字串：yield (在哪, 值, strict)。strict＝這個欄位一定是路徑
    （cli.python、runtime、cwd、skill、python.module、web.panel、integrity 的檔名）；argv、env 的值是「一段字」。"""
    def items(label, value, strict):
        if isinstance(value, str):
            yield label, value, strict
        elif isinstance(value, list):
            for i, v in enumerate(value):
                yield from items(f"{label}[{i}]", v, strict)
        elif isinstance(value, dict):
            for k, v in value.items():
                yield from items(f"{label}.{k}", v, strict)

    def obj(value) -> dict:
        return value if isinstance(value, dict) else {}

    cli, mcp, runtime = obj(raw.get("cli")), obj(raw.get("mcp")), obj(raw.get("runtime"))
    yield from items("skill", raw.get("skill"), True)
    yield from items("python.module", obj(raw.get("python")).get("module"), True)
    yield from items("cli.python", cli.get("python"), True)
    yield from items("cli.cwd", cli.get("cwd"), True)
    yield from items("mcp.cwd", mcp.get("cwd"), True)
    for key in ("python", "python_posix", "node"):
        yield from items(f"runtime.{key}", runtime.get(key), True)
    yield from items("runtime.container.dockerfile", obj(runtime.get("container")).get("dockerfile"), True)
    yield from items("web.panel", obj(raw.get("web")).get("panel"), True)
    for k in obj(obj(raw.get("integrity")).get("sha256")):
        yield "integrity.sha256", str(k), True
    yield from items("cli.argv", cli.get("argv"), False)
    for i, c in enumerate(cli.get("commands") or raw.get("commands") or []):
        if isinstance(c, dict):
            yield from items(f"commands[{i}].argv", c.get("argv"), False)
    yield from items("mcp.argv", mcp.get("argv"), False)
    for label, env in (("env", raw.get("env")), ("cli.env", cli.get("env")), ("mcp.env", mcp.get("env"))):
        yield from items(label, env, False)


def unc_problems(raw: dict) -> List[str]:
    """第 1 關最先跑（任何碰檔案系統的檢查之前）：pack.json 裡有 UNC／裝置路徑 → 每個一句理由。"""
    return [f"{where} 不能用網路路徑或裝置路徑（\\\\主機\\…、//主機/…、\\\\?\\、\\\\.\\）：{value[:80]!r}"
            "——光是檢查這種路徑，Windows 就會連到那台主機（審查 C #C4）"
            for where, value, strict in _unc_strings(raw) if unc_like(value, strict=strict)]


def env_name_problem(name, value=None) -> str:
    """pack 寫的環境變數名（與值）能不能給子程序：""＝可以；否則一句理由（審查 C #C2）。"""
    if not isinstance(name, str) or not ENV_NAME_RE.match(name):
        return f"環境變數名字 {name!r} 只能用英數字和 _（不能以數字開頭）"
    upper = name.upper()
    if upper == "PYTHONPATH":
        text = str(value or "").replace("\\", "/")
        if PYTHONPATH_OK_RE.match(text) and ".." not in text.split("/"):
            return ""
        return ("PYTHONPATH 只能指到 pack 自己的資料夾（{pack_dir} 或 {pack_dir}/子資料夾）："
                "指到別處，Python 啟動時會先載入那裡沒鎖、沒掃過的程式（sitecustomize.py、.pth）")
    if upper in ENV_PYTHON_OK:
        return ""
    if upper in ENV_BANNED or upper.startswith(ENV_BANNED_PREFIXES):
        return (f"環境變數 {name} 不能由 pack 設定：它會讓 Python／Node／系統在跑 pack 的程式之前，"
                "先載入 pack 外、沒鎖、沒掃過的程式（或換掉要跑的程式）")
    return ""


def env_problems(label: str, env) -> List[str]:
    """{名字: 字串} 的每一個鍵都過 env_name_problem；回不合的說明。"""
    if not isinstance(env, dict):
        return []
    out = []
    for k, v in env.items():
        why = env_name_problem(k, v)
        if why:
            out.append(f"{label}.{k}：{why}")
    return out


def safe_env(env: Dict[str, str]) -> Dict[str, str]:
    """防禦深度（loader／mcp 開子程序前）：pack 寫的環境變數裡 env_name_problem 不收的一律拿掉。"""
    return {k: v for k, v in (env or {}).items() if not env_name_problem(k, v)}


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
    # 網頁工具頁的建議群組（沒寫＝""，畫面上是「未分類」；使用者自己排的優先）
    category: str = ""
    # 穩定度（test｜alpha｜beta｜stable；沒寫＝alpha，stage_declared=False）
    stage: str = DEFAULT_STAGE
    stage_declared: bool = False
    # 工具健康的自我檢查（選填；{"check": "<這個 pack 的一個唯讀指令名>"}，docs/tool-health.md）
    health: dict = field(default_factory=dict)
    # 指令的白話說明與範例（選填；最上層的 help 區塊＋cli 的 commands[].plain／examples，synox/helpui/examples.py）
    help: dict = field(default_factory=dict)

    @property
    def stage_label(self) -> str:
        return stage_label(self.stage)

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


def one_line_problem(value, label: str, limit: int = MAX_DOC_TEXT) -> str:
    """給人看的一行字（summary、ask、help、category）：要是字串、不空、limit 字內、沒有換行與控制字元。"""
    if not isinstance(value, str) or not value.strip():
        return f"{label} 要是不空的字串"
    if len(value) > limit:
        return f"{label} 太長了（最多 {limit} 字）"
    if _CONTROL_RE.search(value):
        return f"{label} 不能有換行、控制字元或雙向文字控制字元"
    return ""


def clean_category(value) -> str:
    """category 的值能用就回去掉前後空白的字，不能用回 ""（載入時寬鬆：壞的當作沒寫）。"""
    return value.strip() if not one_line_problem(value, "category", MAX_CATEGORY) else ""


def stage_problem(value) -> str:
    """pack.json 的 stage 寫得對不對（""＝對）。只收 test、alpha、beta、stable 四個小寫字。"""
    if isinstance(value, str) and value in STAGES:
        return ""
    return (f"stage 只能是 {'、'.join(STAGES)}（現在是 {value!r}；沒寫＝{DEFAULT_STAGE}）")


def stage_label(stage: str, long: bool = False) -> str:
    """給人看的標籤：「🧪 alpha」；long=True：「🧪 alpha（早期版）」。不認得的當 alpha。"""
    stage = stage if stage in STAGE_INFO else DEFAULT_STAGE
    icon, word, _text = STAGE_INFO[stage]
    return f"{icon} {stage}（{word}）" if long else f"{icon} {stage}"


def stage_text(stage: str) -> str:
    """這個 stage 的意思（一句話）。"""
    return STAGE_INFO.get(stage, STAGE_INFO[DEFAULT_STAGE])[2]


def default_text(value) -> str:
    """fields[].default（JSON 的字串／數字／布林）→ 交給程式的字串：布林寫成 true／false（不是 Python 的 True）。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _field_doc_problems(where: str, f: dict) -> List[str]:
    """安裝時（strict）才檢查的欄位說明：網頁工具頁的表單、AI 的參數說明都靠這些（舊 pack 載入時不擋）。"""
    out = []
    fname = f["name"]
    for key in ("ask", "help"):
        if key in f:
            problem = one_line_problem(f[key], f"{where} 的欄位 {fname} 的 {key}")
            if problem:
                out.append(problem)
    if "required" in f and not isinstance(f["required"], bool):
        out.append(f"{where} 的欄位 {fname} 的 required 要是 true 或 false（\"false\" 這種字串會被當成必填）")
    if "default" in f and f["default"] != "":                 # "" ＝沒有預設值
        value = f["default"]
        if not isinstance(value, (str, int, float, bool)) or (isinstance(value, str) and
                                                              one_line_problem(value, "default", MAX_DOC_TEXT)):
            out.append(f"{where} 的欄位 {fname} 的 default 要是一行字串、數字或 true／false（200 字內）")
        else:
            from synox.agent.validate import kind_problem
            kind = f.get("kind", "text")
            if kind in FIELD_KINDS and kind_problem(kind, default_text(value), tuple(f.get("choices") or ())):
                out.append(f"{where} 的欄位 {fname} 的 default {value!r} 不合 kind={kind}"
                           + (f"（只能是 {'／'.join(map(str, f.get('choices') or []))}）" if kind == "choice" else ""))
    return out


SCENARIO_MAX = 120
# scenario 是給 AI 看的字（進工具說明）：不准夾網址、信箱、像在對 AI 下指令或要跳過確認的字、分隔符（規則跟 runtime/ledger.py 的
# risk_flags 同一套，只取這幾類；「提到寄送／執行」不算——工具本來就是做這些事的）
SCENARIO_RISKS = ("有網址或網域", "有電子郵件", "像在對 AI 下指令（忽略／改掉規則）", "要跳過確認或核准", "夾了標記或分隔符")


def scenario_problem(value) -> str:
    """commands[].ai.scenario 寫得對不對（""＝對）：一行、120 字內、不像指令。"""
    problem = one_line_problem(value, "scenario", SCENARIO_MAX)
    if problem:
        return problem
    from synox.runtime.ledger import risk_flags
    bad = [flag for flag in risk_flags(value) if flag in SCENARIO_RISKS]
    if bad:
        return f"scenario 不能{'、'.join(bad)}（這段字會直接給 AI 看）"
    return ""


def scenario_of(command: dict) -> str:
    """commands[].ai.scenario（沒寫或不合＝""；載入時寬鬆，壞的當作沒寫）。"""
    ai = command.get("ai") if isinstance(command, dict) else None
    value = ai.get("scenario") if isinstance(ai, dict) else None
    return value.strip() if isinstance(value, str) and not scenario_problem(value) else ""


def ai_problems(value, where: str) -> List[str]:
    """commands[].ai 不是布林時：只能是 {"scenario": "一句話"}。"""
    if not isinstance(value, dict):
        return [f"{where} 的 ai 要是 true 或 false，或 {{\"scenario\": \"什麼時候用（一句話）\"}}"]
    out = []
    unknown = sorted(set(value) - {"scenario"})
    if unknown:
        out.append(f"{where} 的 ai 只收 scenario（不認得 {'、'.join(map(str, unknown))}）")
    if "scenario" in value:
        problem = scenario_problem(value["scenario"])
        if problem:
            out.append(f"{where} 的 ai.{problem}")
    return out


def _check_commands(commands, strict: bool, problems: List[str], install: bool = False) -> List[dict]:
    """cli 的 commands：名字、argv、effect、fields。回整理過的清單（effect 一律大寫）。
    install=True（安裝時的 strict）：另外檢查給人看的說明（summary、fields 的 ask／help／required／default 的型別）。"""
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
        # ai: false＝不給 AI；ai: {"scenario": "…"}＝給 AI，附一句使用情境（docs/adr/0013）；confirm: true＝AI 呼叫前先送確認卡
        if "ai" in c and not isinstance(c["ai"], bool):
            problems += ai_problems(c["ai"], where)
        if "confirm" in c and not isinstance(c["confirm"], bool):
            problems.append(f"{where} 的 confirm 要是 true 或 false")
        if install and "summary" in c:
            problem = one_line_problem(c["summary"], f"{where} 的 summary")
            if problem:
                problems.append(problem)
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
            elif install:
                problems += _field_doc_problems(where, f)
        out.append({**c, "effect": effect or "READ"})
    return out


def health_problem(raw: dict, kind, cli: dict) -> "tuple[dict, str]":
    """pack.json 的 health（選填）：{"check": "<指令名>"}——工具壞掉、冷卻到了，SYNOX 用它重新檢查（不叫 AI）。
    指到的一定要是這個 pack 裡**唯讀**、不用填參數的指令：kind=cli 是 cli.commands 裡 effect=READ、沒有沒預設值的必填欄位、
    不是 background、沒有 confirm；kind=mcp 是 tools_allow 裡 mcp.effects 寫 READ 的工具；kind=python 的指令名在載入後才知道，
    這裡只查名字的格式（執行時 health.check_node 再確認是 READ）。回 (整理過的 health, 問題)；沒寫＝({}, "")。"""
    if "health" not in raw:
        return {}, ""
    value = raw.get("health")
    if not isinstance(value, dict) or set(value) - {"check"}:
        return {}, 'health 要是 {"check": "<這個 pack 的一個唯讀指令名>"}'
    check = value.get("check")
    if not isinstance(check, str) or not check.strip():
        return {}, "health.check 要寫這個 pack 的一個唯讀指令名（自我檢查用）"
    if kind == "cli":
        cmd = next((c for c in cli.get("commands") or [] if isinstance(c, dict) and c.get("name") == check), None)
        if cmd is None:
            return {}, f"health.check 指到的 {check!r} 不是 cli.commands 裡的指令"
        if norm_effect(cmd.get("effect")) != "READ":
            return {}, f"health.check 指到的 {check} 不是唯讀的（effect 要是 READ）"
        if cmd.get("background") or cmd.get("confirm") is True:
            return {}, f"health.check 指到的 {check} 不能是 background 或要確認的指令"
        if any(isinstance(f, dict) and f.get("required") and f.get("default") in (None, "")
               for f in cmd.get("fields") or []):
            return {}, f"health.check 指到的 {check} 有沒預設值的必填欄位（自我檢查不帶參數）"
    elif kind == "mcp":
        mcp = raw.get("mcp") if isinstance(raw.get("mcp"), dict) else {}
        if check not in (mcp.get("tools_allow") or []):
            return {}, f"health.check 指到的 {check!r} 不在 mcp.tools_allow 裡"
        if norm_effect((mcp.get("effects") or {}).get(check)) != "READ":
            return {}, f"health.check 指到的 {check} 不是唯讀的（mcp.effects 要寫 READ）"
    elif kind == "python":
        if not COMMAND_RE.match(check):
            return {}, "health.check 要是指令名（小寫英數字、_，32 字內）"
    else:
        return {}, f"kind={kind} 的 pack 沒有指令可以當自我檢查（拿掉 health）"
    return {"check": check}, ""


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
            elif env_name_problem(env, "x"):
                problems.append(f"auth.fields 的 {name}.env：{env_name_problem(env, 'x')}")
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
    else:
        problems += env_problems("mcp.env", env)
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


def parse_spec(spec, key: str = "synox") -> List[tuple]:
    """requires.synox／requires.sdk 的字串 → [(運算子, (主, 次, 修))…]；寫錯丟 ValueError。"""
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError(f"requires.{key} 要是版本條件字串，例如 \">=0.3\"")
    out = []
    for part in spec.split(","):
        m = _SPEC_RE.match(part)
        if m is None:
            raise ValueError(f"requires.{key} 的 {part.strip()!r} 看不懂（寫成 >=0.3、<1.0 這樣，可以用逗號接好幾個）")
        nums = [int(x) for x in m.group(2).split(".")]
        out.append((m.group(1) or ">=", tuple(nums + [0] * (3 - len(nums)))))
    return out


def _version_tuple(text: str) -> tuple:
    nums = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text or "0"))
    return tuple(int(x or 0) for x in nums.groups()) if nums else (0, 0, 0)


_OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b,
        "<": lambda a, b: a < b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


def synox_problem(m: "Manifest", current: Optional[str] = None, sdk: Optional[str] = None) -> Optional[str]:
    """requires.synox（SYNOX 本體的版本）與 requires.sdk（SYNOX 給工具的介面合約 SDK_VERSION，ADR：SYNOX_Libs
    docs/adr/0001）跟這台合不合；不合回一句給人看的話，都合（或沒寫）回 None。安裝（第 1、2 關）、載入、doctor 都用這個。"""
    spec = (m.requires or {}).get("synox")
    if spec:
        if current is None:
            from synox import __version__ as current
        problem = _range_problem(spec, current, "synox")
        if problem:
            return problem
    return sdk_problem(m, sdk)


def sdk_problem(m: "Manifest", current: Optional[str] = None) -> Optional[str]:
    """requires.sdk 跟這台的 SDK_VERSION 合不合（沒寫＝不限）。"""
    spec = (m.requires or {}).get("sdk")
    if not spec:
        return None
    if current is None:
        from synox.sdk.author import SDK_VERSION as current
    return _range_problem(spec, current, "sdk")


def _range_problem(spec: str, current: str, key: str) -> Optional[str]:
    have = _version_tuple(current)
    try:
        clauses = parse_spec(spec, key)
    except ValueError as e:
        return str(e)
    if all(_OPS[op](have, want) for op, want in clauses):
        return None
    too_old = any(op in (">=", ">", "==") and have < want for op, want in clauses)
    hint = "先更新 SYNOX（重跑 Setup.bat 或 git pull）再用這個 pack" if too_old else \
        "這個 pack 還沒支援這一版的 SYNOX，請向 pack 的作者要新版"
    what = "SYNOX" if key == "synox" else "SYNOX SDK"
    return f"這個 pack 要 {what} {spec.strip()}，這台是 {current}：{hint}"


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
    for key in ("synox", "sdk"):
        if key in requires:
            try:
                parse_spec(requires[key], key)
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
    unc = unc_problems(raw)                    # 審查 C #C4：在任何 isfile／realpath 之前
    if unc:
        raise ManifestError("；".join(unc[:5]))
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
    category = clean_category(raw.get("category"))
    if strict and "category" in raw and not category:      # 新欄位：安裝時說清楚；載入時壞的當作沒寫
        problems.append(one_line_problem(raw.get("category"), "category", MAX_CATEGORY)
                        + "（網頁工具頁建議放的群組名，例如 \"生活\"）")
    stage, stage_declared = DEFAULT_STAGE, False
    if "stage" in raw:                                      # 安裝時寫錯＝拒；載入時寫錯＝當作 alpha（比較保守的那一邊）
        if stage_problem(raw.get("stage")):
            if strict:
                problems.append(stage_problem(raw.get("stage")))
        else:
            stage, stage_declared = raw["stage"], True
    access = raw.get("access", "owner")
    if access not in ACCESS:
        problems.append("access 只能是 owner、member 或 everyone")
    storage = raw.get("storage", "plain")
    if storage not in ("vault", "plain"):
        problems.append("storage 只能是 vault 或 plain")
    skill = raw.get("skill", "SKILL.md")
    if not isinstance(skill, str) or os.path.isabs(skill) or re.match(r"^[A-Za-z]:", skill) or \
            ".." in skill.replace("\\", "/").split("/"):
        problems.append(f"skill 要是 pack 資料夾裡的檔（相對路徑、不能有 ..）：{skill!r}")
    elif not os.path.isfile(os.path.join(folder, skill)):
        problems.append(f"找不到 skill 檔 {skill}")
    if kind == "python":
        module = (raw.get("python") or {}).get("module", "pack")
        if not isinstance(module, str) or not MODULE_RE.match(module):
            # 審查 C：以前 "../x" 會讓 loader 執行 pack 外的 x.py（第 2 關沒掃、鎖裡沒有）
            problems.append(f"python.module 要是 pack 資料夾裡的模組名字（英數字、_；不能有路徑）：{module!r}")
        elif not os.path.isfile(os.path.join(folder, f"{module}.py")):
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
            cli["commands"] = _check_commands(cli["commands"], strict or v2, problems, install=strict)
        env = cli.get("env") or {}
        top_env = raw.get("env") or {}
        for label, value in (("cli.env", env), ("env", top_env)):
            if not isinstance(value, dict) or \
                    not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                problems.append(f"{label} 要是 {{名字: 字串}}")
            else:
                problems += env_problems(label, value)          # 審查 C #C2：PYTHONPATH、NODE_OPTIONS、PATH…
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
    container = None
    if "container" in runtime:                 # S0：runtime.container（packs/container.py；第 1 關）
        from synox.packs import container as pack_container
        container, why = pack_container.check(
            runtime.get("container"), kind=kind, capabilities=extra["capabilities"], folder=folder,
            mcp_stdio=kind == "mcp" and (extra.get("mcp") or {}).get("transport") == "stdio",
            secret_names=_declared_secret_names(raw))
        problems += why
    requires = raw.get("requires") or {}
    if not isinstance(requires, dict):
        problems.append("requires 要是物件")
        requires = {}
    _check_requires(requires, problems)
    web = parse_web(raw.get("web"), folder, problems)
    if kind == "cli" and web["api"] and isinstance(cli.get("commands"), list):
        web["routes"] = _cli_routes(raw.get("web") or {}, web["api"], cli["commands"], problems)
    health, health_bad = health_problem(raw, kind, cli)
    if health_bad and strict:                  # 新欄位：安裝時說清楚；載入時壞的當作沒寫（只是少了自我檢查）
        problems.append(health_bad)
    from synox.helpui import examples as help_examples
    help_block, help_bad = help_examples.from_manifest(
        raw, kind, cli.get("commands") if kind == "cli" and isinstance(cli.get("commands"), list) else [], strict)
    if strict:                                 # 安裝時說清楚；載入時壞的那一條丟掉（只是少了範例）
        problems += help_bad
    if problems:
        raise ManifestError("；".join(problems))
    auth_type = extra["auth_info"].get("type", "none")
    return Manifest(name=name, title=raw["title"], summary=raw["summary"], version=version, kind=kind,
                    folder=folder, group=group, access=access, skill=skill, storage=storage,
                    python=dict(raw.get("python") or {}), cli=cli, auth="" if auth_type == "none" else auth_type,
                    requires=dict(requires), web=web, raw=dict(raw), v2=v2, category=category,
                    stage=stage, stage_declared=stage_declared, health=health, help=help_block,
                    runtime={**{k: v for k, v in runtime.items() if k in ("python", "python_posix", "node")},
                             **({"container": container} if container else {})}, **extra)


def doc_warnings(m: Manifest) -> List[str]:
    """說明不齊的地方（提醒、不擋）：網頁工具頁與 AI 都靠它們，缺了照樣能裝、能用，只是畫面上只剩名字。
    - SKILL.md 開頭沒有 frontmatter 的 name／description：AI 的系統提示看不到這個 pack（agent/skills.py）。
    - cli 的 command 沒寫 summary、欄位沒寫 ask：工具頁與 AI 只看得到英文名字。"""
    out = []
    try:
        from synox.agent.skills import parse, read_text
        meta, _body = parse(read_text(m.skill_path))
    except (OSError, UnicodeDecodeError):
        meta = {}
    missing = [k for k in ("name", "description") if not meta.get(k)]
    if missing:
        out.append(f"{m.skill} 開頭的 frontmatter 少了 {'、'.join(missing)}：AI 不會知道什麼時候用這個 pack，"
                   "網頁工具頁的「說明」也只剩 summary（格式見 docs/pack-format.md「SKILL.md」）")
    no_summary = [c["name"] for c in m.commands if isinstance(c, dict) and not str(c.get("summary") or "").strip()]
    if no_summary:
        out.append(f"這些 command 沒寫 summary（工具頁與 /help 只看得到名字）：{'、'.join(no_summary)}")
    no_ask = [f"{c['name']}.{f['name']}" for c in m.commands if isinstance(c, dict)
              for f in c.get("fields") or [] if isinstance(f, dict) and not str(f.get("ask") or "").strip()]
    if no_ask:
        out.append(f"這些欄位沒寫 ask（表單上只看得到英文欄位名）：{'、'.join(no_ask)}")
    from synox.helpui.examples import lint_warnings
    out += lint_warnings(m.help or {})           # 白話檢查：只擋明顯的術語（提醒、不擋安裝）
    return out


def _declared_secret_names(raw: dict) -> List[str]:
    """requires.env＋auth.fields[].env 的名字（還沒有 Manifest 時用；跟 secret_env_names 同一份規則）。"""
    names: List[str] = []
    requires = raw.get("requires") if isinstance(raw.get("requires"), dict) else {}
    env = requires.get("env") or {}
    names += [k for k in (env if isinstance(env, (dict, list)) else []) if isinstance(k, str)]
    auth = raw.get("auth") if isinstance(raw.get("auth"), dict) else {}
    for f in auth.get("fields") or []:
        if isinstance(f, dict) and isinstance(f.get("env"), str):
            names.append(f["env"])
    return [n for n in dict.fromkeys(names) if ENV_NAME_RE.match(n)]


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
