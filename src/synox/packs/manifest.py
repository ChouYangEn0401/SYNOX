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

      "kind": "mcp",                             第四種：接一個 MCP 伺服器（這一版只登記、不連）
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
      "mcp": {"url": "…", "tools_allow": ["search"], "effects": {"search": "READ"}}

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

    @property
    def skill_path(self) -> str:
        return os.path.join(self.folder, self.skill)

    @property
    def panel_path(self) -> str:
        return os.path.join(self.folder, self.web["panel"]) if self.web.get("panel") else ""

    @property
    def commands(self) -> List[dict]:
        return list(self.cli.get("commands") or [])

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
        python = cli.get("python")
        if python is not None and (not isinstance(python, str) or
                                   not (python == "venv" or os.path.isabs(python))):
            problems.append('cli.python 只能是絕對路徑或 "venv"（沒寫＝SYNOX 自己的 Python）')
        env = cli.get("env") or {}
        top_env = raw.get("env") or {}
        for label, value in (("cli.env", env), ("env", top_env)):
            if not isinstance(value, dict) or \
                    not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                problems.append(f"{label} 要是 {{名字: 字串}}")
        if isinstance(env, dict) and isinstance(top_env, dict):
            cli["env"] = {**top_env, **env}             # 最上層的 env（金流簿的寫法）＋ cli.env，cli.env 優先
    runtime = raw.get("runtime") or {}
    if not isinstance(runtime, dict):
        problems.append("runtime 要是物件")
        runtime = {}
    for key in ("python", "python_posix", "node"):
        if key in runtime and (not isinstance(runtime[key], str) or not runtime[key].strip()):
            problems.append(f"runtime.{key} 要是路徑（相對於 pack 資料夾，或絕對路徑）或 \"auto\"")
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
