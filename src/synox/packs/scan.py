"""
安全管線第 2 關：靜態掃描（架構 v1 §4）。安裝之前跑，**不執行 pack 的任何程式**——只用 `ast` 讀原始碼。

    report = scan(manifest)              # ScanReport(findings=[Finding(file, line, kind, snippet)], required_capabilities)
    problems = report.problems(manifest) # [] ＝可以裝；否則每一行一個理由（檔名:行號），拒裝

各種 kind 看什麼：

- python：每一個 .py 用 ast 解析，列出
    network    import／呼叫 requests、urllib、http.client、socket、ssl、ftplib、smtplib、websocket…  → 要宣告 network
    subprocess subprocess、os.system、os.popen、os.exec*、os.spawn*、app.jobs（SDK 的 JobRunner）  → subprocess
    filesystem open(…)／pathlib.Path(…)／shutil、os.remove、os.rename… ：字面路徑是絕對的或有 ..  → filesystem:any；
               其他（路徑是變數、相對路徑）→ filesystem:own（pack 自己的檔案應該用 pack.path() 或 pack.store）
    exec       exec、eval、compile、__import__、importlib、ctypes、pickle.loads、marshal、getattr(x, "system")… → exec
    env        os.environ、os.getenv：**只列出來給人看**（不算 capability，也不擋）
    binary     .pyc、.pyd、.dll、.exe… 掃不到的東西 → exec
  沒宣告對應的 capability ＝拒裝（列出檔名:行號）。舊的 pack 沒寫 capabilities＝什麼都沒宣告，所以掃描結果決定。
  .py 解析不了（語法錯）也拒裝：掃不到就不能說它安全。
- cli：pack 裡附的 .py 照上面一樣掃；argv 樣板只能是字面字、單獨一段的 {欄位}、或 --k={欄位}（一段）；
  {欄位} 緊跟在一個 --旗標 後面當它的值 ＝拒（值會變成另一段，要寫成 --k={v}）；樣板裡用了沒宣告的欄位 ＝拒。
  （值本身以 - 開頭、有換行，是第 4 關在呼叫時擋。）
- mcp：沒有程式可以掃；tools_allow 一定不能是空的。附了程式檔 ＝拒。
- connector：只能是宣告，不准有任何程式檔（.py 或執行檔）。

**這一關看得到的只有 pack 自己的原始碼**：它 import 的第三方套件做什麼、cli 叫的那支程式做什麼，掃不到。
所以它是「擋明顯的、逼作者宣告」，不是沙盒——最後一道是第 5 關的核准卡（結構）。
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from synox.packs.manifest import RESERVED_PLACEHOLDERS, Manifest

NETWORK_MODULES = ("requests", "urllib", "urllib2", "urllib3", "http", "httpx", "aiohttp", "socket", "ssl",
                   "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "websocket", "websockets", "xmlrpc",
                   "asyncio.open_connection", "socketserver", "paramiko", "grpc")
SUBPROCESS_MODULES = ("subprocess", "pty", "multiprocessing", "isdtelekit.jobs", "asyncio.subprocess")
EXEC_MODULES = ("ctypes", "cffi", "marshal", "importlib", "builtins", "runpy", "code", "codeop", "imp")
SUBPROCESS_CALLS = ("os.system", "os.popen", "os.startfile", "os.fork", "os.forkpty", "asyncio.create_subprocess_exec",
                    "asyncio.create_subprocess_shell")
SUBPROCESS_PREFIXES = ("os.exec", "os.spawn", "os.posix_spawn", "subprocess.", "pty.", "multiprocessing.")
EXEC_BUILTINS = ("exec", "eval", "compile", "__import__")
EXEC_CALLS = ("pickle.loads", "pickle.load", "pickle.Unpickler", "marshal.loads", "marshal.load", "shelve.open",
              "dill.loads", "dill.load")
EXEC_PREFIXES = ("importlib.", "ctypes.", "builtins.", "runpy.", "marshal.", "cffi.")
OPEN_CALLS = ("open", "io.open", "os.open", "codecs.open", "pathlib.Path", "pathlib.PurePath", "pathlib.WindowsPath",
              "pathlib.PosixPath")
FS_CALLS = ("os.remove", "os.unlink", "os.rename", "os.renames", "os.replace", "os.rmdir", "os.removedirs",
            "os.makedirs", "os.mkdir", "os.chmod", "os.chown", "os.link", "os.symlink", "os.truncate")
FS_PREFIXES = ("shutil.",)
ENV_CALLS = ("os.getenv", "os.putenv", "os.unsetenv", "os.environ.get")
DANGER_ATTRS = ("system", "popen", "exec", "eval", "spawnl", "spawnv", "execv", "execl", "startfile",
                "__import__", "import_module", "loads", "Popen", "run", "call", "check_output")
BINARY_EXT = (".pyc", ".pyo", ".pyd", ".dll", ".so", ".dylib", ".exe", ".com", ".bat", ".cmd", ".ps1", ".vbs",
              ".msi", ".scr", ".jar", ".sh")
CODE_EXT = (".py",) + BINARY_EXT

# kind → 要宣告的 capability（"" ＝只列給人看、不擋）
CAPABILITY_OF = {"network": "network", "subprocess": "subprocess", "filesystem:own": "filesystem:own",
                 "filesystem:any": "filesystem:any", "exec": "exec", "binary": "exec", "env": ""}
LABELS = {"network": "連網", "subprocess": "開別的程式", "filesystem:own": "讀寫檔案",
          "filesystem:any": "讀寫 pack 以外的檔案", "exec": "動態執行程式碼", "binary": "掃不到的執行檔",
          "env": "讀環境變數（可能是密鑰）", "argv": "argv 樣板不合規則", "code": "不該有程式檔",
          "syntax": "程式解析不了", "mcp": "MCP 設定"}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_FLAG_VALUE = re.compile(r"^--?[A-Za-z0-9][A-Za-z0-9_-]*=\{(\w+)\}$")


@dataclass
class Finding:
    file: str
    line: int
    kind: str                   # network｜subprocess｜filesystem:own｜filesystem:any｜exec｜binary｜env｜argv｜code｜syntax｜mcp
    snippet: str
    detail: str = ""

    @property
    def capability(self) -> str:
        return CAPABILITY_OF.get(self.kind, "")

    @property
    def blocking(self) -> bool:
        """不管宣告了什麼都擋（樣板不合、connector 有程式、解析不了）。"""
        return self.kind in ("argv", "code", "syntax", "mcp")

    def where(self) -> str:
        return f"{self.file}:{self.line}" if self.line else self.file

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "kind": self.kind, "snippet": self.snippet,
                "detail": self.detail, "capability": self.capability, "label": LABELS.get(self.kind, self.kind)}


@dataclass
class ScanReport:
    findings: List[Finding] = field(default_factory=list)
    files: int = 0

    @property
    def required_capabilities(self) -> List[str]:
        return sorted({f.capability for f in self.findings if f.capability})

    def undeclared(self, m: Manifest) -> List[Finding]:
        return [f for f in self.findings if f.capability and not m.allows(f.capability)]

    def problems(self, m: Manifest) -> List[str]:
        """拒裝的理由（空＝這一關過了）。"""
        out = [f"{f.where()} {LABELS.get(f.kind, f.kind)}：{f.detail or f.snippet}" for f in self.findings if f.blocking]
        out += [f"{f.where()} {LABELS.get(f.kind, f.kind)}但 capabilities 沒宣告 {f.capability}：{f.snippet}"
                for f in self.undeclared(m)]
        return out

    def to_dict(self, m: Optional[Manifest] = None) -> dict:
        out = {"files": self.files, "findings": [f.to_dict() for f in self.findings],
               "required_capabilities": self.required_capabilities}
        if m is not None:
            out["declared_capabilities"] = list(m.capabilities)
            out["undeclared"] = sorted({f.capability for f in self.undeclared(m)})
            out["problems"] = self.problems(m)
            out["ok"] = not out["problems"]
        return out

    def summary(self, m: Manifest) -> dict:
        """packs.lock 裡記的那一小段。"""
        return {"files": self.files, "findings": len(self.findings), "required": self.required_capabilities,
                "declared": list(m.capabilities)}

    def format(self, m: Manifest) -> str:
        """給終端機看的報告。"""
        lines = [f"🔍 靜態掃描：{m.name} {m.version}（{m.kind}），{self.files} 個檔"]
        lines.append("  宣告的能力：" + ("、".join(m.capabilities) or "（沒有）"))
        lines.append("  需要的能力：" + ("、".join(self.required_capabilities) or "（沒有）"))
        for f in self.findings:
            mark = "❌" if f.blocking or (f.capability and not m.allows(f.capability)) else ("⚠️" if not f.capability else "✅")
            lines.append(f"  {mark} {f.where()}  {LABELS.get(f.kind, f.kind)}  {f.detail or f.snippet}")
        problems = self.problems(m)
        lines.append("結論：" + ("✅ 這一關過了" if not problems else f"❌ 拒裝（{len(problems)} 個問題）"))
        return "\n".join(lines)


def pack_files(folder: str) -> List[str]:
    """pack 資料夾裡的全部檔案（相對路徑，/ 分隔，排序）；跳過 __pycache__（loader 不從那裡載入）。"""
    out = []
    for base, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in files:
            rel = os.path.relpath(os.path.join(base, name), folder).replace(os.sep, "/")
            out.append(rel)
    return sorted(out)


# ── python 原始碼 ───────────────────────────────────────────────────────

def _literal_path(node) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
        value = node.value.decode("utf-8", "replace") if isinstance(node.value, bytes) else node.value
        return value
    if isinstance(node, ast.JoinedStr):           # f"…"：取字面部分
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return None


def _escapes(path: str) -> bool:
    p = path.replace("\\", "/")
    return p.startswith("/") or p.startswith("~") or bool(re.match(r"^[A-Za-z]:", p)) or ".." in p.split("/")


class _Visitor(ast.NodeVisitor):

    def __init__(self, rel: str, lines: Sequence[str]):
        self.rel = rel
        self.lines = lines
        self.aliases: Dict[str, str] = {}
        self.findings: List[Finding] = []

    def add(self, node, kind: str, detail: str = "") -> None:
        line = getattr(node, "lineno", 0)
        snippet = self.lines[line - 1].strip()[:120] if 0 < line <= len(self.lines) else ""
        self.findings.append(Finding(self.rel, line, kind, snippet, detail))

    def _module_kind(self, module: str) -> Optional[str]:
        for kind, mods in (("network", NETWORK_MODULES), ("subprocess", SUBPROCESS_MODULES), ("exec", EXEC_MODULES)):
            if any(module == m or module.startswith(m + ".") for m in mods):
                return kind
        return None

    def visit_Import(self, node):
        for a in node.names:
            self.aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
            kind = self._module_kind(a.name)
            if kind:
                self.add(node, kind, f"import {a.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = "." * node.level + (node.module or "")
        for a in node.names:
            full = f"{module}.{a.name}" if module else a.name
            self.aliases[a.asname or a.name] = full
            kind = self._module_kind(module) or self._module_kind(full)
            if kind:
                self.add(node, kind, f"from {module} import {a.name}")
            elif module == "os" and a.name in ("system", "popen", "startfile") or \
                    module == "os" and a.name.startswith(("exec", "spawn", "posix_spawn")):
                self.add(node, "subprocess", f"from os import {a.name}")
            elif module == "os" and a.name in ("environ", "getenv"):
                self.add(node, "env", f"from os import {a.name}")
            elif module == "pickle" and a.name in ("loads", "load", "Unpickler"):
                self.add(node, "exec", f"from pickle import {a.name}")
        self.generic_visit(node)

    def dotted(self, node) -> str:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return ""
        base = self.aliases.get(node.id, node.id)
        return ".".join([base] + list(reversed(parts)))

    def visit_Name(self, node):
        if node.id == "__builtins__":
            self.add(node, "exec", "__builtins__")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        name = self.dotted(node)
        if name == "os.environ":
            self.add(node, "env", "os.environ")
        elif name == "app.jobs" or name.endswith(".app.jobs"):
            self.add(node, "subprocess", "app.jobs（JobRunner 會開別的程式）")
        self.generic_visit(node)

    def _path_kind(self, args) -> str:
        literal = _literal_path(args[0]) if args else None
        if literal is not None and _escapes(literal):
            return "filesystem:any"
        for a in args[1:2]:                          # rename(src, dst)、copy(src, dst) 的第二個也看
            second = _literal_path(a)
            if second is not None and _escapes(second):
                return "filesystem:any"
        return "filesystem:own"

    def visit_Call(self, node):
        name = self.dotted(node.func)
        if name:
            if name in EXEC_BUILTINS and name not in self.aliases:
                self.add(node, "exec", f"{name}(…)")
            elif name in EXEC_CALLS or name.startswith(EXEC_PREFIXES):
                self.add(node, "exec", f"{name}(…)")
            elif name in SUBPROCESS_CALLS or name.startswith(SUBPROCESS_PREFIXES):
                self.add(node, "subprocess", f"{name}(…)")
            elif name in OPEN_CALLS or name in ("Path", "PurePath") and self.aliases.get(name, "").startswith("pathlib"):
                self.add(node, self._path_kind(node.args), f"{name}(…)")
            elif name in FS_CALLS or name.startswith(FS_PREFIXES):
                self.add(node, self._path_kind(node.args), f"{name}(…)")
            elif name in ENV_CALLS:
                self.add(node, "env", f"{name}(…)")
            elif name in ("getattr", "setattr", "delattr") and name not in self.aliases and len(node.args) >= 2:
                attr = _literal_path(node.args[1])
                if attr is None or attr in DANGER_ATTRS or attr.startswith(("exec", "spawn", "__")):
                    self.add(node, "exec", f"{name}(…, {attr!r})" if attr is not None else f"{name}(…, 變數)")
        self.generic_visit(node)


def scan_source(rel: str, text: str) -> List[Finding]:
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as e:
        return [Finding(rel, e.lineno or 0, "syntax", (e.text or "").strip()[:120], f"語法錯誤：{e.msg}")]
    v = _Visitor(rel, text.splitlines())
    v.visit(tree)
    seen = set()
    out = []
    for f in v.findings:                              # 同一行同一種只留一筆
        key = (f.line, f.kind, f.detail)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _scan_python_files(m: Manifest, files: List[str]) -> List[Finding]:
    out = []
    for rel in files:
        if rel.lower().endswith(".py"):
            try:
                with open(os.path.join(m.folder, rel), "r", encoding="utf-8-sig") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError) as e:
                out.append(Finding(rel, 0, "syntax", "", f"讀不了：{e}"))
                continue
            out += scan_source(rel, text)
    return out


# ── cli 樣板 ───────────────────────────────────────────────────────────

def _check_prefix(m: Manifest) -> List[Finding]:
    out = []
    for i, token in enumerate(m.cli.get("argv") or []):
        bad = [n for n in _PLACEHOLDER.findall(token) if n not in RESERVED_PLACEHOLDERS]
        if bad or _PLACEHOLDER.sub("", token).count("{") or _PLACEHOLDER.sub("", token).count("}"):
            out.append(Finding("pack.json", 0, "argv", f"cli.argv[{i}] {token!r}",
                               f"cli.argv 只能用字面字和 {{python}}、{{pack_dir}} 這類系統代換（{token!r}）"))
    for k, v in (m.cli.get("env") or {}).items():
        bad = [n for n in _PLACEHOLDER.findall(v) if n not in RESERVED_PLACEHOLDERS]
        if bad:
            out.append(Finding("pack.json", 0, "argv", f"cli.env.{k}", f"cli.env.{k} 只能用系統代換（{v!r}）"))
    return out


def _check_command(c: dict) -> List[Finding]:
    out = []
    fields = {f.get("name") for f in c.get("fields") or [] if isinstance(f, dict)}
    argv = c.get("argv") or []
    name = c.get("name")
    for i, token in enumerate(argv):
        where = f"command {name} argv[{i}] {token!r}"
        names = _PLACEHOLDER.findall(token)
        rest = _PLACEHOLDER.sub("", token)
        if "{" in rest or "}" in rest:
            out.append(Finding("pack.json", 0, "argv", where, f"{where}：大括號只能用來寫 {{欄位}}"))
            continue
        unknown = [n for n in names if n not in fields and n not in RESERVED_PLACEHOLDERS]
        if unknown:
            out.append(Finding("pack.json", 0, "argv", where, f"{where}：用了沒宣告的欄位 {'、'.join(unknown)}"))
            continue
        field_names = [n for n in names if n in fields]
        if not field_names:
            continue
        if token == "{" + field_names[0] + "}" and len(names) == 1:
            prev = argv[i - 1] if i else ""
            if prev.startswith("-") and "=" not in prev and not _PLACEHOLDER.search(prev):
                out.append(Finding("pack.json", 0, "argv", where,
                                   f"command {name}：旗標的值要寫成一段 {prev}={{{field_names[0]}}}，不要分成兩段"))
            continue
        if _FLAG_VALUE.match(token) and len(names) == 1:
            continue
        out.append(Finding("pack.json", 0, "argv", where,
                           f"{where}：欄位只能單獨一段（{{x}}）或寫成 --k={{x}}"))
    return out


def scan(m: Manifest) -> ScanReport:
    files = pack_files(m.folder)
    report = ScanReport(files=len(files))
    code = [f for f in files if f.lower().endswith(CODE_EXT)]
    if m.kind in ("connector", "mcp"):
        report.findings += [Finding(f, 0, "code", f, f"kind={m.kind} 只能是宣告，不能附程式檔") for f in code]
        if m.kind == "mcp" and not (m.mcp.get("tools_allow") or []):
            report.findings.append(Finding("pack.json", 0, "mcp", "mcp.tools_allow", "mcp.tools_allow 不能是空的"))
        return report
    if m.kind == "python":
        report.findings += [Finding(f, 0, "binary", f, "掃不到的執行檔／編譯過的程式") for f in files
                            if f.lower().endswith(BINARY_EXT)]
    report.findings += _scan_python_files(m, files)
    if m.kind == "cli":
        report.findings += _check_prefix(m)
        for c in m.commands:
            report.findings += _check_command(c)
    return report


def gate2(m: Manifest) -> ScanReport:
    """scan() 的別名（讀起來像管線）。"""
    return scan(m)
