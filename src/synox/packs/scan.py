"""
安全管線第 2 關：靜態掃描（架構 v1 §4）。安裝之前跑，**不執行 pack 的任何程式**——只用 `ast` 讀原始碼。

    report = scan(manifest)              # ScanReport(findings=[Finding(file, line, kind, snippet)], required_capabilities)
    problems = report.problems(manifest) # [] ＝可以裝；否則每一行一個理由（檔名:行號），拒裝

各種 kind 看什麼：

- python：每一個 .py 用 ast 解析，列出
    network    import／呼叫 requests、urllib、http.client、socket、ssl、ftplib、smtplib、websocket…  → 要宣告 network
    subprocess subprocess、os.system、os.popen、os.exec*、os.spawn*、app.jobs（SDK 的 JobRunner）  → subprocess
    filesystem open(…)／pathlib.Path(…)／shutil、os.remove、os.rename… ：字面路徑是絕對的或有 ..  → filesystem:any；
               其他（路徑是變數、相對路徑）→ filesystem:own（pack 自己的檔案應該用 pack.path_of(user)／pack.path() 或 pack.store）
    exec       exec、eval、compile、__import__、importlib、ctypes、pickle.loads、marshal、getattr(x, "system")… → exec
    env        os.environ、os.getenv：**只列出來給人看**（不算 capability，也不擋）
    secret     pack.secret(…)：讀使用者在「連接」填的值（pack.json auth.fields）；只列出來，不算 capability
    binary     掃不到內容的檔（T2，P7；opaque_files）：.exe .dll .bat .cmd .ps1 .sh .so .dylib .node .wasm…、
               __pycache__ 裡的、.pyc／.pyd、檔頭是 MZ+PE／ELF／Mach-O（不管副檔名）、沒有副檔名但帶執行位元或 #! 開頭、
               node_modules（整個資料夾一筆） → exec；python、cli、mcp stdio 都看。報告的 opaque 列路徑、大小、sha256
  沒宣告對應的 capability ＝拒裝（列出檔名:行號）。舊的 pack 沒寫 capabilities＝什麼都沒宣告，所以掃描結果決定。
  .py 解析不了（語法錯）也拒裝：掃不到就不能說它安全。
- cli：pack 裡附的 .py 照上面一樣掃；cli.argv 指到 pack 外的程式（git、npx、絕對路徑、{python} -m 外部模組）
  不擋，列一筆 external（報告的 external 有解析後的路徑）「未鎖定執行環境」；argv 樣板只能是字面字、單獨一段的 {欄位}、或 --k={欄位}（一段）；
  {欄位} 緊跟在一個 --旗標 後面當它的值 ＝拒（值會變成另一段，要寫成 --k={v}）；樣板裡用了沒宣告的欄位 ＝拒。
  （值本身以 - 開頭、有換行，是第 4 關在呼叫時擋。）
- data（pack.json 的 data 宣告，PERM-2；不合＝拒裝，列檔名:行號）：
    python data=user   不准裸用 pack.store（load／save／update…；要 pack.store.of(user)），pack.secret(name) 一定要給 user，
                       不准用 pack.path（全部人共用的資料夾；要 pack.path_of(user, ...)，PERM-8）
    python data=none   不准用 pack.store、pack.path（有存資料就要宣告 user 或 shared）
    cli    data=user   樣板不准 {data_dir}（只能 {user_data_dir}）；data=none 兩個都不准
- mcp（只登記，沒有 transport）：沒有程式可以掃；tools_allow 一定不能是空的。附了程式檔 ＝拒。
- mcp（transport=stdio，P4a）：pack 裡附的 .py 照 cli 一樣掃；mcp.argv／env 只能用系統代換（{python}、{pack_dir}…）；
  data 規則同 cli（樣板）；argv 指到 **pack 外面的程式**（npx、node、絕對路徑…）不擋，但列一筆 external
  「未鎖定執行環境」：packs.lock 只鎖 pack 資料夾裡的檔，外面那支程式被換掉 SYNOX 不會發現。
- mcp（transport=http，P4b）：遠端 MCP，這台不跑它的程式：同「只登記」，**只能是宣告**（附了程式檔＝拒）。
  信任等級 T0（只有宣告）：安裝報告逐一列 tools_allow 與每個工具的 effect 給安裝者確認（admin.mcp_report）；
  沒寫 effect 的工具第 1 關就拒；url 一定 https（第 1 關）。
- connector：只能是宣告，不准有任何程式檔（.py 或執行檔）。

**這一關看得到的只有 pack 自己的原始碼**：它 import 的第三方套件做什麼、cli 叫的那支程式做什麼，掃不到。
所以它是「擋明顯的、逼作者宣告」，不是沙盒——最後一道是第 5 關的核准卡（結構）。
"""

from __future__ import annotations

import ast
import json
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
              ".msi", ".scr", ".jar", ".sh", ".node", ".wasm", ".class")
CODE_EXT = (".py",) + BINARY_EXT
# 檔頭（不看副檔名）：ELF、Mach-O（含 universal）；MZ 另外要對到 PE 簽名才算（避免文字檔剛好 MZ 開頭）
_MAGIC = ((b"\x7fELF", "ELF 執行檔"), (b"\xfe\xed\xfa\xce", "Mach-O 執行檔"), (b"\xfe\xed\xfa\xcf", "Mach-O 執行檔"),
          (b"\xce\xfa\xed\xfe", "Mach-O 執行檔"), (b"\xcf\xfa\xed\xfe", "Mach-O 執行檔"),
          (b"\xca\xfe\xba\xbe", "Mach-O／Java 編譯檔"))
NODE_MODULES = "node_modules"
PYCACHE = "__pycache__"

# kind → 要宣告的 capability（"" ＝只列給人看、不擋）
CAPABILITY_OF = {"network": "network", "subprocess": "subprocess", "filesystem:own": "filesystem:own",
                 "filesystem:any": "filesystem:any", "exec": "exec", "binary": "exec", "env": "", "secret": "",
                 "external": ""}
LABELS = {"network": "連網", "subprocess": "開別的程式", "filesystem:own": "讀寫檔案",
          "filesystem:any": "讀寫 pack 以外的檔案", "exec": "動態執行程式碼", "binary": "掃不到的執行檔",
          "env": "讀環境變數（可能是密鑰）", "secret": "讀使用者在「連接」填的 secret", "argv": "argv 樣板不合規則", "code": "不該有程式檔",
          "syntax": "程式解析不了", "mcp": "MCP 設定", "data": "資料歸屬（data）不合",
          "external": "未鎖定執行環境（pack 外的程式）"}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_FLAG_VALUE = re.compile(r"^--?[A-Za-z0-9][A-Za-z0-9_-]*=\{(\w+)\}$")


@dataclass
class Finding:
    file: str
    line: int
    kind: str                   # network｜subprocess｜filesystem:own｜filesystem:any｜exec｜binary｜env｜argv｜code｜syntax｜mcp｜data
    snippet: str
    detail: str = ""

    @property
    def capability(self) -> str:
        return CAPABILITY_OF.get(self.kind, "")

    @property
    def blocking(self) -> bool:
        """不管宣告了什麼都擋（樣板不合、connector 有程式、解析不了）。"""
        return self.kind in ("argv", "code", "syntax", "mcp", "data")

    def where(self) -> str:
        return f"{self.file}:{self.line}" if self.line else self.file

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "kind": self.kind, "snippet": self.snippet,
                "detail": self.detail, "capability": self.capability, "label": LABELS.get(self.kind, self.kind)}


@dataclass
class ScanReport:
    findings: List[Finding] = field(default_factory=list)
    files: int = 0
    # 掃不到內容的檔案（T2）：[{"path", "size", "sha256", "why"}]；node_modules 整個資料夾算一筆（path 以 / 結尾）
    opaque: List[dict] = field(default_factory=list)
    # pack 外的程式（未鎖定執行環境）：[{"program", "resolved", "where", "note"}]；不進 packs.lock 的雜湊
    external: List[dict] = field(default_factory=list)

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
               "required_capabilities": self.required_capabilities,
               "opaque": [dict(o) for o in self.opaque], "external": [dict(e) for e in self.external]}
        if m is not None:
            out["declared_capabilities"] = list(m.capabilities)
            out["undeclared"] = sorted({f.capability for f in self.undeclared(m)})
            out["problems"] = self.problems(m)
            out["ok"] = not out["problems"]
        return out

    def summary(self, m: Manifest) -> dict:
        """packs.lock 裡記的那一小段。"""
        return {"files": self.files, "findings": len(self.findings), "required": self.required_capabilities,
                "declared": list(m.capabilities), "opaque": len(self.opaque), "external": len(self.external)}

    def format(self, m: Manifest) -> str:
        """給終端機看的報告。"""
        lines = [f"🔍 靜態掃描：{m.name} {m.version}（{m.kind}），{self.files} 個檔"]
        lines.append("  宣告的能力：" + ("、".join(m.capabilities) or "（沒有）"))
        lines.append("  需要的能力：" + ("、".join(self.required_capabilities) or "（沒有）"))
        for f in self.findings:
            mark = "❌" if f.blocking or (f.capability and not m.allows(f.capability)) else ("⚠️" if not f.capability else "✅")
            text = f.detail if f.blocking or not f.snippet else f"{f.detail}　｜ {f.snippet}"
            lines.append(f"  {mark} {f.where()}  {LABELS.get(f.kind, f.kind)}  {text}")
        if self.opaque:
            lines.append(f"  掃不到內容的檔案（{len(self.opaque)} 個；T2，要宣告 exec）：")
            lines += [f"    · {o['path']}  {o['size']} bytes  sha256 {o['sha256'][:16]}…  {o['why']}" for o in self.opaque]
        if self.external:
            lines.append("  pack 外的程式（未鎖定執行環境，不在 packs.lock 的雜湊裡）：")
            lines += [f"    · {e['program']} → {e['resolved']}" for e in self.external]
        problems = self.problems(m)
        lines.append("結論：" + ("✅ 這一關過了" if not problems else f"❌ 拒裝（{len(problems)} 個問題）"))
        return "\n".join(lines)


def pack_files(folder: str, include_cache: bool = False) -> List[str]:
    """pack 資料夾裡的全部檔案（相對路徑，/ 分隔，排序）。include_cache=False 跳過 __pycache__（舊的鎖這樣算）；
    T2（P7）之後的鎖、掃不到內容的清單都用 include_cache=True：子程序的 python 會 import 那裡的 .pyc。"""
    out = []
    for base, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if include_cache or d != PYCACHE)
        for name in files:
            rel = os.path.relpath(os.path.join(base, name), folder).replace(os.sep, "/")
            out.append(rel)
    return sorted(out)


# ── 掃不到內容的檔案（T2，SDK P7） ─────────────────────────────────────

def _sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _magic_of(path: str) -> str:
    """看檔頭（只讀前面幾個 byte，不執行）：PE（MZ＋PE 簽名）、ELF、Mach-O → 說明；不是回 ""。"""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
            if head[:2] == b"MZ":
                if len(head) >= 64:
                    offset = int.from_bytes(head[60:64], "little")
                    if 0 < offset < 16 * 1024 * 1024:
                        f.seek(offset)
                        if f.read(4) == b"PE\x00\x00":
                            return "Windows 執行檔（MZ／PE 標頭）"
                return ""
            for magic, why in _MAGIC:
                if head.startswith(magic):
                    return why
            return ""
    except OSError:
        return ""


def _shebang(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"#!"
    except OSError:
        return False


def _exec_bit(path: str) -> bool:
    if os.name == "nt":                          # Windows 的 st_mode 執行位元是照副檔名猜的，不可信
        return False
    try:
        return bool(os.stat(path).st_mode & 0o111)
    except OSError:
        return False


def opaque_reason(folder: str, rel: str, exec_bits: Sequence[str] = ()) -> str:
    """這個檔掃不掃得到內容；掃不到回一句原因（""＝是原始碼或資料，第 2 關看得到或不會被執行）。"""
    path = os.path.join(folder, *rel.split("/"))
    parts = rel.split("/")
    name = parts[-1]
    ext = os.path.splitext(name)[1].lower()
    if PYCACHE in parts[:-1]:
        # 對得到同一層 .py 原始碼的快取（本機跑過產生的）不算：原始碼第 2 關掃過了。上傳的 zip 裡的 __pycache__
        # admin.stage 根本不解出來；對不到原始碼的 .pyc＝Python 照樣會 import，掃不到
        parent = parts[:parts.index(PYCACHE)]
        source = os.path.join(folder, *(parent + [name.split(".")[0] + ".py"]))
        if ext in (".pyc", ".pyo") and os.path.isfile(source):
            return ""
        return "__pycache__ 裡對不到原始碼的編譯檔，看不到內容"
    if ext in (".pyc", ".pyo", ".pyd"):
        return "編譯過的 Python（.pyc／.pyd），看不到原始碼"
    if ext in BINARY_EXT:
        return f"執行檔／腳本（{ext}），第 2 關只看 .py"
    magic = _magic_of(path)
    if magic:
        return f"{magic}（副檔名是 {ext or '沒有'}）"
    if not ext and (rel in set(exec_bits) or _exec_bit(path)):
        return "沒有副檔名、帶執行位元的檔"
    if not ext and _shebang(path):
        return "沒有副檔名、#! 開頭的腳本"
    return ""


def opaque_files(folder: str, exec_bits: Sequence[str] = ()) -> List[dict]:
    """pack 資料夾裡掃不到內容的東西：[{"path", "size", "sha256", "why"}]（只讀檔頭與算雜湊，不執行任何東西）。
    node_modules 整個資料夾算一筆：path 以 / 結尾、size＝總和、sha256＝「相對路徑 雜湊」逐行排序後再算一次、
    why 寫有幾個檔。exec_bits：zip 裡帶執行位元的檔（admin.stage 記的；Windows 解壓縮後看不到）。"""
    import hashlib
    out: List[dict] = []
    groups: Dict[str, List[str]] = {}
    for rel in pack_files(folder, include_cache=True):
        parts = rel.split("/")
        if NODE_MODULES in parts[:-1]:
            root = "/".join(parts[:parts.index(NODE_MODULES) + 1]) + "/"
            groups.setdefault(root, []).append(rel)
            continue
        why = opaque_reason(folder, rel, exec_bits)
        if why:
            path = os.path.join(folder, *parts)
            out.append({"path": rel, "size": os.path.getsize(path), "sha256": _sha256(path), "why": why})
    for root, rels in groups.items():
        listing, size = [], 0
        for rel in sorted(rels):
            path = os.path.join(folder, *rel.split("/"))
            size += os.path.getsize(path)
            listing.append(f"{rel} {_sha256(path)}")
        digest = hashlib.sha256("\n".join(listing).encode("utf-8")).hexdigest()
        out.append({"path": root, "size": size, "sha256": digest,
                    "why": f"node_modules（{len(rels)} 個檔：npm 套件，第 2 關不看）"})
    return sorted(out, key=lambda o: o["path"])


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
            elif name == "pack.secret" or name.endswith(".pack.secret"):
                self.add(node, "secret", "pack.secret(…)")
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


# ── data 宣告（PERM-2） ─────────────────────────────────────────────────

STORE_OK_ATTRS = ("of", "encrypted", "per_user", "name")   # pack.store.<這些> 不算裸用


def _is_pack_attr(dotted: str, attr: str) -> bool:
    return dotted == f"pack.{attr}" or dotted.endswith(f".pack.{attr}")


class _DataVisitor(ast.NodeVisitor):
    """data=user／none 的 python pack：找 pack.store、pack.path、pack.secret 的用法（只讀 ast）。"""

    def __init__(self, rel: str, lines: Sequence[str], data: str):
        self.rel, self.lines, self.data = rel, lines, data
        self.findings: List[Finding] = []
        self._ok_store: set = set()         # pack.store.of(…) 那種的 pack.store 節點（不算裸用）

    def add(self, node, detail: str) -> None:
        line = getattr(node, "lineno", 0)
        snippet = self.lines[line - 1].strip()[:120] if 0 < line <= len(self.lines) else ""
        self.findings.append(Finding(self.rel, line, "data", snippet, detail))

    @staticmethod
    def dotted(node) -> str:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return ""
        return ".".join([node.id] + list(reversed(parts)))

    def visit_Attribute(self, node):
        inner = node.value
        if node.attr in STORE_OK_ATTRS and isinstance(inner, ast.Attribute) and \
                _is_pack_attr(self.dotted(inner), "store") and (self.data != "none" or node.attr != "of"):
            self._ok_store.add(id(inner))       # data=none：只有 encrypted 這種看屬性的不算（of 也是存資料）
        bare = _is_pack_attr(self.dotted(node), "store") and id(node) not in self._ok_store
        if bare and self.data == "none":
            self.add(node, 'data 是 none 卻用了 pack.store（有存資料就要宣告 "data": "user" 或 "shared"）')
        elif bare:
            self.add(node, "data 是 user：不能直接用 pack.store（load／save／update 是全部人共用的那一份），"
                           "要用 pack.store.of(user)")
        elif self.data == "none" and (_is_pack_attr(self.dotted(node), "path") or
                                      _is_pack_attr(self.dotted(node), "path_of")):
            self.add(node, f'data 是 none 卻用了 pack.{node.attr}（有存檔案就要宣告 "data": "user" 或 "shared"）')
        elif self.data == "user" and _is_pack_attr(self.dotted(node), "path"):
            self.add(node, "data 是 user：不能用 pack.path()（data/packs/<name>/ 是全部人共用的；伺服器版呼叫會丟錯），"
                           "要用 pack.path_of(user, ...)（每個人自己的資料夾）")
        self.generic_visit(node)

    def visit_Call(self, node):
        if self.data == "user" and _is_pack_attr(self.dotted(node.func), "secret"):
            if len(node.args) < 2 and not any(k.arg == "user" for k in node.keywords):
                self.add(node, "data 是 user：pack.secret(name) 一定要給 user（pack.secret(name, user)），不然拿到的不是這個人的")
        self.generic_visit(node)


def _check_data_python(m: Manifest, files: List[str]) -> List[Finding]:
    if m.data not in ("user", "none"):
        return []
    out: List[Finding] = []
    for rel in files:
        if not rel.lower().endswith(".py"):
            continue
        try:
            with open(os.path.join(m.folder, rel), "r", encoding="utf-8-sig") as fh:
                text = fh.read()
            tree = ast.parse(text, filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue                                  # 讀不了／語法錯，_scan_python_files 已經擋了
        v = _DataVisitor(rel, text.splitlines(), m.data)
        v.visit(tree)
        seen = set()
        for f in v.findings:
            if (f.line, f.detail) not in seen:
                seen.add((f.line, f.detail))
                out.append(f)
    return out


def _json_line(lines: Sequence[str], text: str, needle: str) -> int:
    """pack.json 裡這段樣板在第幾行（找不到回 0）。"""
    escaped = json.dumps(text, ensure_ascii=False)[1:-1]
    for i, line in enumerate(lines, 1):
        if escaped in line and needle in line:
            return i
    for i, line in enumerate(lines, 1):
        if needle in line:
            return i
    return 0


def _check_data_cli(m: Manifest) -> List[Finding]:
    from synox.packs.manifest import cli_templates, mcp_templates
    templates = mcp_templates(m.mcp) if m.kind == "mcp" else cli_templates(m.cli)
    banned = {"user": ("{data_dir}",), "none": ("{data_dir}", "{user_data_dir}")}.get(m.data, ())
    if not banned:
        return []
    try:
        with open(os.path.join(m.folder, "pack.json"), "r", encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    out = []
    for where, text in templates:
        for needle in banned:
            if needle not in text:
                continue
            if m.data == "user":
                detail = (f"{where} 用了 {{data_dir}}，但 data 是 user：每個人的資料要放 {{user_data_dir}}"
                          "（{data_dir} 是全部人共用的；真的是共用資料就寫 \"data\": \"shared\"）")
            else:
                detail = f'{where} 用了 {needle}，但 data 是 none（有存資料就要宣告 "data": "user" 或 "shared"）'
            out.append(Finding("pack.json", _json_line(lines, text, needle), "data", text[:120], detail))
    return out


_SYSTEM_PROGRAMS = ("{python}", "{node}")


def _program_argv(m: Manifest) -> List[str]:
    if m.kind == "mcp":
        return [str(a) for a in (m.mcp or {}).get("argv") or []]
    if m.kind == "cli":
        return [str(a) for a in (m.cli or {}).get("argv") or []]
    return []


def _module_inside(m: Manifest, module: str) -> bool:
    top = module.split(".")[0]
    base = m.folder
    return os.path.isfile(os.path.join(base, top + ".py")) or os.path.isdir(os.path.join(base, top))


def external_programs(m: Manifest) -> List[str]:
    """kind=cli 的 cli.argv、kind=mcp stdio 的 mcp.argv 裡指到 pack 外面的程式（樣板原文）：argv[0] 不是 {python}／{node}、
    不是 ./ 開頭的 pack 內檔案（npx、node、git、uvx、絕對路徑…）；後面任何一段絕對路徑或 {pack_dir} 以外的 .. 路徑；
    {python} -m <模組> 而那個模組不在 pack 資料夾裡（記成 "-m 模組"）。"""
    out: List[str] = []
    argv = _program_argv(m)
    for i, token in enumerate(argv):
        plain = token.replace("\\", "/")
        inside = plain.startswith(("./", "{pack_dir}/")) and ".." not in plain.split("/")
        if i == 0:
            if token in _SYSTEM_PROGRAMS or inside:
                continue
            out.append(token)
        elif token == "-m" and i == 1 and argv[0] == "{python}" and len(argv) > 2:
            if not _module_inside(m, argv[2]):
                out.append(f"-m {argv[2]}")
        elif not inside and (os.path.isabs(token) or re.match(r"^[A-Za-z]:", token) or ".." in plain.split("/")):
            out.append(token)
    return out


def resolve_program(token: str, m: Optional[Manifest] = None) -> str:
    """pack 外的程式解析到這台的哪裡（只查路徑，不執行）：絕對路徑原樣；"-m 模組"＝SYNOX 這支 Python 的 sys.path
    找得到的位置（不 import）；其他照 PATH 找（shutil.which）。找不到回一句話。"""
    import shutil
    if token.startswith("-m "):
        module = token[3:].strip()
        try:
            from importlib.machinery import PathFinder
            spec = PathFinder.find_spec(module.split(".")[0])
        except (ImportError, ValueError):
            spec = None
        where = (spec.origin or (list(spec.submodule_search_locations or [])[:1] or [""])[0]) if spec else ""
        return (f"{where}（照 SYNOX 這支 Python 的 sys.path；runtime 指到別的 Python 時以那支為準）" if where
                else f"這台 SYNOX 的 Python 找不到模組 {module}")
    if os.path.isabs(token) or re.match(r"^[A-Za-z]:", token):
        return token if os.path.exists(token) else f"{token}（這台不存在）"
    if "{" in token:
        return f"{token}（樣板，執行時才代換）"
    found = shutil.which(token)
    if not found:
        return f"這台的 PATH 找不到 {token}"
    note = "（npx 會在執行時從網路抓套件，版本沒有鎖住）" if os.path.basename(token).lower().startswith("npx") else ""
    return found + note


def externals(m: Manifest) -> List[dict]:
    """[{"program", "resolved", "where", "note"}]：pack 外的程式＋解析後的路徑；不進 packs.lock 的雜湊。"""
    where = "mcp.argv" if m.kind == "mcp" else "cli.argv"
    return [{"program": t, "resolved": resolve_program(t, m), "where": where, "note": "未鎖定執行環境"}
            for t in external_programs(m)]


def _check_mcp_stdio(m: Manifest) -> List[Finding]:
    out = []
    for i, token in enumerate((m.mcp or {}).get("argv") or []):
        token = str(token)
        bad = [n for n in _PLACEHOLDER.findall(token) if n not in RESERVED_PLACEHOLDERS]
        rest = _PLACEHOLDER.sub("", token)
        if bad or "{" in rest or "}" in rest:
            out.append(Finding("pack.json", 0, "argv", f"mcp.argv[{i}] {token!r}",
                               f"mcp.argv 只能用字面字和 {{python}}、{{pack_dir}} 這類系統代換（{token!r}）"))
    for k, v in ((m.mcp or {}).get("env") or {}).items():
        if [n for n in _PLACEHOLDER.findall(str(v)) if n not in RESERVED_PLACEHOLDERS]:
            out.append(Finding("pack.json", 0, "argv", f"mcp.env.{k}", f"mcp.env.{k} 只能用系統代換（{v!r}）"))
    for token in external_programs(m):
        out.append(Finding("pack.json", 0, "external", token,
                           f"argv 用了 pack 外的程式 {token}：packs.lock 只鎖 pack 資料夾裡的檔，這支被換掉不會發現"
                           "（未鎖定執行環境）"))
    return out


def _binary_findings(opaque: List[dict]) -> List[Finding]:
    return [Finding(o["path"], 0, "binary", o["path"], f"掃不到內容：{o['why']}（{o['size']} bytes）") for o in opaque]


def scan(m: Manifest, exec_bits: Sequence[str] = ()) -> ScanReport:
    """exec_bits：zip 裡帶執行位元的檔（admin.stage 記的）；沒給＝只看檔案本身。"""
    files = pack_files(m.folder)
    report = ScanReport(files=len(pack_files(m.folder, include_cache=True)))
    report.opaque = opaque_files(m.folder, exec_bits)
    report.external = externals(m)
    if m.kind == "mcp" and m.mcp_stdio:
        report.findings += _binary_findings(report.opaque)
        report.findings += _scan_python_files(m, files)
        report.findings += _check_mcp_stdio(m)
        report.findings += _check_data_cli(m)
        return report
    if m.kind in ("connector", "mcp"):
        opaque = {o["path"] for o in report.opaque}
        code = sorted({f for f in files if f.lower().endswith(CODE_EXT)} | opaque)
        report.findings += [Finding(f, 0, "code", f, f"kind={m.kind} 只能是宣告，不能附程式檔") for f in code]
        if m.kind == "mcp" and not (m.mcp.get("tools_allow") or []):
            report.findings.append(Finding("pack.json", 0, "mcp", "mcp.tools_allow", "mcp.tools_allow 不能是空的"))
        return report
    report.findings += _binary_findings(report.opaque)
    report.findings += _scan_python_files(m, files)
    if m.kind == "python":
        report.findings += _check_data_python(m, files)
    if m.kind == "cli":
        report.findings += _check_prefix(m)
        for c in m.commands:
            report.findings += _check_command(c)
        report.findings += _check_data_cli(m)
        report.findings += [Finding("pack.json", 0, "external", e["program"],
                                    f"cli.argv 用了 pack 外的程式 {e['program']}（→ {e['resolved']}）：packs.lock 只鎖 pack "
                                    "資料夾裡的檔，這支被換掉不會發現（未鎖定執行環境）") for e in report.external]
    return report


def gate2(m: Manifest) -> ScanReport:
    """scan() 的別名（讀起來像管線）。"""
    return scan(m)
