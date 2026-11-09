"""
安全管線第 2 關：靜態掃描（架構 v1 §4）。安裝之前跑，**不執行 pack 的任何程式**——只用 `ast` 讀原始碼。

    report = scan(manifest)              # ScanReport(findings=[Finding(file, line, kind, snippet)], required_capabilities)
    problems = report.problems(manifest) # [] ＝可以裝；否則每一行一個理由（檔名:行號），拒裝

各種 kind 看什麼：

- python：每一個 .py／.pyw（和沒有副檔名、ast.parse 得過的檔，審查 C #C1）用 ast 解析，列出
    network    import／呼叫 requests、urllib、http.client、socket、ssl、ftplib、smtplib、websocket…  → 要宣告 network
    subprocess subprocess、os.system、os.popen、os.exec*、os.spawn*、app.jobs（SDK 的 JobRunner）  → subprocess
    filesystem open(…)／pathlib.Path(…)／shutil、os.remove、os.rename… ：字面路徑是絕對的或有 ..  → filesystem:any；
               其他（路徑是變數、相對路徑）→ filesystem:own（pack 自己的檔案應該用 pack.path_of(user)／pack.path() 或 pack.store）
    exec       exec、eval、compile、__import__、importlib、ctypes、pickle.loads、marshal、getattr(x, "system")… → exec；
               審查 B #B：sys.modules、dunder／frame 屬性（__class__、__subclasses__、__globals__、__dict__、__self__、
               f_globals…，寫在字串裡也算）、getattr／vars／globals／locals／eval／compile 當值取用、getattr 屬性名不是字面字、
               呼叫的對象看不出是什麼（handlers[k](…)、f()(…)、sys.modules['os'].system(…)、obj.popen(…)）→ exec。
               **是提醒不是門**：攔直呼名與常見的間接取用，不保證每一種寫法都抓得到
    env        os.environ、os.getenv：**只列出來給人看**（不算 capability，也不擋）；讀 SYNOX 自己注入的協定變數
               （SYNOX_ENV_OK：SYNOX_USER_DATA_DIR、SYNOX_CONFIRMED…，名字是字面字）不列；SYNOX_CONFIRM_TOKEN、SYNOX_SECRET_ENV 照列
    secret     pack.secret(…)：讀使用者在「連接」填的值（pack.json auth.fields）；只列出來，不算 capability
    binary     掃不到內容的檔（T2，P7；opaque_files）：.exe .dll .bat .cmd .ps1 .sh .so .dylib .node .wasm…、
               別的語言的原始碼（SOURCE_EXT：.js .mjs .ts .rb .pl .php .lua .go .rs .java .cs .psm1 .bash…）、
               __pycache__ 裡的、.pyc／.pyd、壓縮檔（.pyz .pyzw .zip .whl .egg：Python 可以直接從裡面 import／執行）、
               檔頭是 MZ+PE／ELF／Mach-O（不管副檔名）、沒有副檔名但帶執行位元或 #! 開頭、
               node_modules（整個資料夾一筆） → exec；python、cli、mcp stdio 都看。報告的 opaque 列路徑、大小、sha256
  沒宣告對應的 capability ＝拒裝（列出檔名:行號）。舊的 pack 沒寫 capabilities＝什麼都沒宣告，所以掃描結果決定。
  .py 解析不了（語法錯）也拒裝：掃不到就不能說它安全。
- cli：pack 裡附的 .py 照上面一樣掃；cli.argv 指到 pack 外的程式（git、npx、絕對路徑、{python} -m 外部模組、
  {node}／node／deno／bun／ruby／perl／php 這類直譯器——出現在 argv 任何一段都算，INTERPRETERS；{python} 解析到 pack 外的直譯器，
  envs.python_target）不擋，列一筆 external（報告的 external 有解析後的路徑）「未鎖定執行環境」；
  argv 讓直譯器直接執行一段程式碼（-c、-e、-Command、/c…，inline_code；cli.argv＋command argv 整條看）→ exec；
  {python} 要跑的 pack 內檔案不是 .py／.pyw（或含 __main__.py 的資料夾）＝拒（審查 C #C1：./run.txt、./app.pyz…
  Python 照跑、第 2 關不看；script_target_problem）；
  argv 樣板只能是字面字、單獨一段的 {欄位}、或 --k={欄位}（一段）；
  {欄位} 緊跟在一個 --旗標 後面當它的值 ＝拒（值會變成另一段，要寫成 --k={v}）；樣板裡用了沒宣告的欄位 ＝拒。
  （值本身以 - 開頭、有換行，是第 4 關在呼叫時擋。）
- data（pack.json 的 data 宣告，PERM-2；不合＝拒裝，列檔名:行號）：
    python data=user   不准裸用 pack.store（load／save／update…；要 pack.store.of(user)），pack.secret(name) 一定要給 user，
                       不准用 pack.path（全部人共用的資料夾；要 pack.path_of(user, ...)，PERM-8）
    python data=none   不准用 pack.store、pack.path（有存資料就要宣告 user 或 shared）
    cli    data=user   樣板不准 {data_dir}（只能 {user_data_dir}）；data=none 兩個都不准
- mcp（只登記，沒有 transport）：沒有程式可以掃；tools_allow 一定不能是空的。附了程式檔 ＝拒。
- mcp（transport=stdio，P4a）：pack 裡附的 .py 照 cli 一樣掃；mcp.argv／env 只能用系統代換（{python}、{pack_dir}…）；
  data 規則同 cli（樣板）；argv 指到 **pack 外面的程式**（{node}、npx、node、絕對路徑…）不擋，但列一筆 external
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
ENV_READS = ("os.getenv", "os.environ.get")       # 只有「讀」才看白名單（putenv／unsetenv 照列）
# SYNOX 自己注入給子程序的協定變數（不是密鑰）：讀這些不列 env。SYNOX_CONFIRM_TOKEN（一次性憑證）、
# SYNOX_SECRET_ENV（密鑰的變數名）不在這裡，照列
SYNOX_ENV_OK = ("SYNOX_USER_DATA_DIR", "SYNOX_TG_ID", "SYNOX_MODE", "SYNOX_PACK_DIR", "SYNOX_PACK_NAME", "SYNOX_CONFIRMED")
DANGER_ATTRS = ("system", "popen", "exec", "eval", "spawnl", "spawnv", "execv", "execl", "startfile",
                "__import__", "import_module", "loads", "Popen", "run", "call", "check_output")
# 審查 B #B：ast 掃描的單行繞法。這些一律算 exec（「是提醒不是門」：攔直呼名與常見的間接取用，不保證全部抓得到）
# dunder／frame 屬性：().__class__.__bases__[0].__subclasses__()、f.__globals__['os']、print.__self__（＝builtins）…
DUNDER_ATTRS = ("__class__", "__bases__", "__base__", "__subclasses__", "__globals__", "__mro__", "__builtins__",
                "__import__", "__dict__", "__code__", "__closure__", "__getattribute__", "__self__", "__loader__",
                "__spec__", "__reduce__", "__reduce_ex__", "__defaults__", "__kwdefaults__", "__getattr__",
                "__setattr__", "__delattr__", "__init_subclass__", "__traceback__",
                "f_globals", "f_locals", "f_builtins", "f_back", "f_code", "gi_frame", "gi_code", "tb_frame",
                "cr_frame", "ag_frame")
# 這些名字只要出現（呼叫、當成值傳、放進清單…）就算 exec；getattr／setattr／delattr 第二個參數是字面字、
# 又不是 dunder／DANGER_ATTRS 的，等於 x.attr，不算
DYNAMIC_NAMES = ("getattr", "setattr", "delattr", "vars", "globals", "locals", "eval", "exec", "compile",
                 "__import__", "breakpoint", "__builtins__", "__loader__", "__spec__")
# 拿得到任何模組／任何物件的入口
DYNAMIC_CALLS = ("sys.modules", "sys._getframe", "sys._current_frames", "inspect.currentframe", "inspect.stack",
                 "inspect.getouterframes", "inspect.trace", "gc.get_objects", "gc.get_referrers", "gc.get_referents",
                 "operator.attrgetter", "operator.methodcaller", "pydoc.locate", "types.FunctionType",
                 "types.CodeType")
# 呼叫的對象看不出是什麼模組（sys.modules['os'].system、[os][0].system、obj.system…）時，方法名是這些＝當作開程式／動態 import
DYNAMIC_ATTRS = ("system", "popen", "startfile", "Popen", "check_output", "check_call", "getoutput", "getstatusoutput",
                 "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
                 "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
                 "posix_spawn", "posix_spawnp", "fork", "forkpty", "__import__", "import_module", "load_module",
                 "exec_module", "create_subprocess_exec", "create_subprocess_shell")
BINARY_EXT = (".pyc", ".pyo", ".pyd", ".dll", ".so", ".dylib", ".exe", ".com", ".bat", ".cmd", ".ps1", ".vbs",
              ".msi", ".scr", ".jar", ".sh", ".node", ".wasm", ".class")
# 別的語言的原始碼（P7 補：擁有者 2026-11-09 決定）：第 2 關只讀得懂 .py，這些一律算「掃不到內容的檔」
# → 要宣告 exec、算 T2、安裝要輸入 publisher。要加新的語言就往這裡加（小寫、含點）。
SOURCE_EXT = (
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx", ".coffee",          # JavaScript／TypeScript
    ".rb", ".pl", ".pm", ".php", ".lua", ".tcl", ".r", ".jl", ".dart",                 # 直譯語言
    ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".groovy", ".swift",                # 編譯語言
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".m", ".cs", ".vb", ".fs", ".fsx",
    ".ex", ".exs", ".erl", ".hs", ".ml", ".clj",
    ".psm1", ".psd1", ".vbe", ".jse", ".wsf", ".wsh", ".hta", ".applescript", ".scpt",   # Windows／macOS 腳本
    ".bash", ".zsh", ".fish", ".ksh", ".csh", ".awk",                                  # shell
)
# 審查 C #C1：Python 可以直接從這些壓縮檔 import 或執行（zipapp、sys.path 放 .whl／.zip／.egg），第 2 關看不到裡面
ARCHIVE_EXT = (".pyz", ".pyzw", ".zip", ".whl", ".egg")
OPAQUE_EXT = BINARY_EXT + tuple(e for e in SOURCE_EXT if e not in BINARY_EXT) + ARCHIVE_EXT
# 第 2 關當 Python 原始碼掃的副檔名（.pyw：pythonw 跑的腳本；Windows 的 import 也會找 .pyw）
PY_SOURCE_EXT = (".py", ".pyw")
CODE_EXT = PY_SOURCE_EXT + OPAQUE_EXT
MAX_GUESS_SOURCE = 1024 * 1024          # 沒有副檔名的檔：1 MB 以內才試著當 Python 解析（審查 C #C1）
# argv 裡出現就算「叫 pack 外的程式」的直譯器（{node} 是 SYNOX 的代換，但 node 本身在 pack 外、沒有鎖）
# （argv[0] 本來就一律看；這張表是讓 cmd /c node …、env node … 這種後面才出現的也記一筆。可擴充）
INTERPRETERS = ("node", "nodejs", "npx", "npm", "deno", "bun", "bunx", "ruby", "perl", "php", "ts-node",
                "powershell", "pwsh", "wscript", "cscript", "osascript")
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
    if ext in SOURCE_EXT:
        return f"別的語言的原始碼（{ext}），第 2 關只讀得懂 .py"
    if ext in ARCHIVE_EXT:
        return f"壓縮檔（{ext}）：Python 可以直接從裡面 import 或執行（zipapp／wheel），第 2 關看不到內容"
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
        self._env_ok: set = set()               # 讀 SYNOX 協定變數的 os.environ 節點（不列 env）
        self._handled: set = set()              # visit_Call 已經判斷過的 func 節點（visit_Name／visit_Attribute 不再列一次）

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
            elif full in DYNAMIC_CALLS:
                self.add(node, "exec", f"from {module} import {a.name}（拿得到任何模組／物件）")
        self.generic_visit(node)

    def visit_Assign(self, node):
        """x = os、run = subprocess：之後 x.system(…) 照 os.system 看（只追「名字＝匯入的模組／它的屬性」這種）。"""
        if isinstance(node.value, (ast.Name, ast.Attribute)):
            value = self.dotted(node.value)
            root = node.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if value and isinstance(root, ast.Name) and root.id in self.aliases:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.aliases[target.id] = value
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
        if id(node) not in self._handled and isinstance(node.ctx, ast.Load) and node.id in DYNAMIC_NAMES \
                and node.id not in self.aliases:
            self.add(node, "exec", f"{node.id}（動態取用：可以拿到任何模組或屬性）")
        self.generic_visit(node)

    def visit_Constant(self, node):
        # "{0.__globals__[os]}".format(f)、getattr 拼字串：字串裡直接寫 dunder 屬性名也算
        if isinstance(node.value, str) and len(node.value) < 2000 and \
                any(d in node.value for d in DUNDER_ATTRS if d.startswith("__")):
            hit = next(d for d in DUNDER_ATTRS if d.startswith("__") and d in node.value)
            self.add(node, "exec", f"字串裡有 {hit}（format／getattr 可以用字串取屬性）")

    def _synox_env(self, node) -> bool:
        value = _literal_path(node) if node is not None else None
        return value in SYNOX_ENV_OK

    def visit_Subscript(self, node):
        key = getattr(node.slice, "value", node.slice) if type(node.slice).__name__ == "Index" else node.slice
        if self.dotted(node.value) == "os.environ" and self._synox_env(key):
            self._env_ok.add(id(node.value))           # os.environ["SYNOX_USER_DATA_DIR"]：協定變數，不列
        self.generic_visit(node)

    @staticmethod
    def _proc_or_exec(name: str) -> str:
        """這個完整名字是開程式／動態執行的函式嗎（拿來當值傳也算）：subprocess｜exec｜""。"""
        if name in SUBPROCESS_CALLS or name.startswith(("os.exec", "os.spawn", "os.posix_spawn")):
            return "subprocess"
        if name in EXEC_CALLS or name in DYNAMIC_CALLS:
            return "exec"
        return ""

    def visit_Attribute(self, node):
        name = self.dotted(node)
        if node.attr in DUNDER_ATTRS:
            self.add(node, "exec", f".{node.attr}（dunder／frame 屬性：可以繞到 os、builtins）")
        elif id(node) in self._handled:
            pass
        elif name == "os.environ":
            if id(node) not in self._env_ok:
                self.add(node, "env", "os.environ")
        elif name == "app.jobs" or name.endswith(".app.jobs"):
            self.add(node, "subprocess", "app.jobs（JobRunner 會開別的程式）")
        elif name and self._proc_or_exec(name):
            self.add(node, self._proc_or_exec(name), f"{name}（當成值取用）")
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

    def _dynamic_call(self, node) -> bool:
        """呼叫的對象掃描器解析不了（審查 B #B）：func 是 Subscript／Call／Lambda…（handlers[k](…)、f()(…)），
        或 func 是屬性但前面不是匯入的模組、方法名又是開程式／動態 import 的（sys.modules['os'].system(…)、
        [os][0].system(…)、obj.popen(…)）。保守地算 exec。回 True＝已經記了一筆。"""
        func = node.func
        if isinstance(func, ast.Name):
            return False
        if not isinstance(func, ast.Attribute):
            kind = type(func).__name__
            self.add(node, "exec", f"動態呼叫（呼叫的對象是 {kind}，掃描器看不出是什麼）")
            return True
        root = func
        while isinstance(root, ast.Attribute):
            root = root.value
        imported = isinstance(root, ast.Name) and root.id in self.aliases
        if func.attr in DYNAMIC_ATTRS and not imported:
            self.add(node, "exec", f".{func.attr}(…)（呼叫的對象不是看得出來的模組：可能是動態取得的 os／subprocess）")
            self._handled.add(id(func))
            return True
        return False

    def visit_Call(self, node):
        name = self.dotted(node.func)
        if isinstance(node.func, ast.Name) and name in DYNAMIC_NAMES:
            self._handled.add(id(node.func))            # 名字本身在這裡判斷（visit_Name 不再列一次）
        elif isinstance(node.func, ast.Attribute) and name:
            self._handled.add(id(node.func))
        if self._dynamic_call(node):
            pass
        elif name:
            if name in EXEC_BUILTINS and name not in self.aliases:
                self.add(node, "exec", f"{name}(…)")
            elif name in ("vars", "globals", "locals", "breakpoint") and name not in self.aliases:
                self.add(node, "exec", f"{name}(…)（拿得到模組或物件的全部屬性）")
            elif name in EXEC_CALLS or name.startswith(EXEC_PREFIXES) or name in DYNAMIC_CALLS:
                self.add(node, "exec", f"{name}(…)")
            elif name in SUBPROCESS_CALLS or name.startswith(SUBPROCESS_PREFIXES):
                self.add(node, "subprocess", f"{name}(…)")
            elif name in OPEN_CALLS or name in ("Path", "PurePath") and self.aliases.get(name, "").startswith("pathlib"):
                self.add(node, self._path_kind(node.args), f"{name}(…)")
            elif name in FS_CALLS or name.startswith(FS_PREFIXES):
                self.add(node, self._path_kind(node.args), f"{name}(…)")
            elif name in ENV_READS and node.args and self._synox_env(node.args[0]):
                if isinstance(node.func, ast.Attribute):     # os.environ.get("SYNOX_MODE")：裡面那個 os.environ 也不列
                    self._env_ok.add(id(node.func.value))
            elif name in ENV_CALLS:
                self.add(node, "env", f"{name}(…)")
            elif name == "pack.secret" or name.endswith(".pack.secret"):
                self.add(node, "secret", "pack.secret(…)")
            elif name in ("getattr", "setattr", "delattr") and name not in self.aliases:
                starred = any(isinstance(a, ast.Starred) for a in node.args) or node.keywords
                second = node.args[1] if len(node.args) >= 2 and not starred else None
                # 只收純字面字（f"{x}tem" 這種拼出來的不算字面字）
                attr = second.value if isinstance(second, ast.Constant) and isinstance(second.value, str) else None
                if attr is None or attr in DANGER_ATTRS or attr in DYNAMIC_ATTRS or \
                        attr.startswith(("exec", "spawn", "__", "f_", "gi_", "tb_", "cr_")):
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


def is_python_source(rel: str) -> bool:
    """.py／.pyw（不分大小寫）：第 2 關一定當 Python 原始碼掃（讀不了、語法錯＝拒裝）。"""
    return rel.lower().endswith(PY_SOURCE_EXT)


def guessed_python(folder: str, rel: str) -> Optional[str]:
    """沒有副檔名的檔（審查 C #C1）：1 MB 以內、UTF-8、ast.parse 得過 → 回內容（當 Python 原始碼掃）；否則 None
    （當資料：Python 的 import 不會載入沒有副檔名的檔；{python} 要跑它第 2 關另外擋，見 script_findings）。只讀不執行。"""
    name = rel.rsplit("/", 1)[-1]
    if os.path.splitext(name)[1] or PYCACHE in rel.split("/")[:-1]:
        return None
    path = os.path.join(folder, *rel.split("/"))
    try:
        if os.path.getsize(path) > MAX_GUESS_SOURCE:
            return None
        with open(path, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
        ast.parse(text, filename=rel)
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return None
    return text


def _python_texts(m: Manifest, files: List[str]):
    """第 2 關要當 Python 掃的檔：yield (rel, 內容 或 None, 讀不了的原因)。"""
    for rel in files:
        if is_python_source(rel):
            try:
                with open(os.path.join(m.folder, rel), "r", encoding="utf-8-sig") as fh:
                    yield rel, fh.read(), ""
            except (OSError, UnicodeDecodeError) as e:
                yield rel, None, str(e)
            continue
        text = guessed_python(m.folder, rel)
        if text is not None:
            yield rel, text, ""


def _scan_python_files(m: Manifest, files: List[str]) -> List[Finding]:
    out = []
    for rel, text, error in _python_texts(m, files):
        if text is None:
            out.append(Finding(rel, 0, "syntax", "", f"讀不了：{error}"))
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
    for rel, text, _error in _python_texts(m, files):
        try:
            tree = ast.parse(text, filename=rel) if text is not None else None
        except (SyntaxError, ValueError):
            tree = None
        if tree is None:
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


_SYSTEM_PROGRAMS = ("{python}",)              # {node} 不算：node 在 pack 外、沒鎖（P7 補）
# {python} 本身不算 pack 外的程式，前提是它解析到 SYNOX 自己的直譯器、SYNOX 為這個 pack 建的 venv（runtime auto）
# 或 pack 資料夾裡的；其他（cli.python 絕對路徑、"venv"＝pack 外的 .venv、runtime.python 指到外面）＝pack 外的直譯器，
# 記一筆 external（解析後的路徑）＝T2（envs.python_target，審查 B #A）

# Python 直譯器的檔名（argv 裡的 python、python3.12、pythonw、pypy3、py 啟動器；不含 .exe）
_PY_NAME = re.compile(r"^(python|pypy)(\d+(\.\d+)*)?[tw]?$|^py$")
SHELLS = ("bash", "sh", "zsh", "dash", "ksh", "fish", "csh", "tcsh", "busybox")
# 直譯器家族：看它後面的旗標是不是「直接執行一段沒被掃描的程式碼」（-c、-e、-Command、/c…，_inline_flags）
FAMILIES = {"powershell": "powershell", "pwsh": "powershell", "cmd": "cmd", "node": "node", "nodejs": "node",
            "bun": "node", "deno": "deno", "ruby": "ruby", "perl": "perl", "php": "php", "lua": "lua",
            "luajit": "lua", "osascript": "osascript", "mshta": "mshta", "wscript": "wsh", "cscript": "wsh"}


def _base(token: str) -> str:
    base = os.path.basename(token.replace("\\", "/")).lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def interpreter_of(token: str) -> str:
    """這段 argv 是不是直譯器（{node}、node、npx、deno、bun、ruby、perl、php、python3、cmd、bash…，含 .exe／完整路徑）：
    是回名字，不是回 ""。{python} 不算（它解析到哪裡另外看，envs.python_target）。"""
    if token == "{node}":
        return "node"
    if "{" in token:
        return ""
    base = _base(token)
    if base in INTERPRETERS or base in SHELLS or base in ("cmd", "mshta") or _PY_NAME.match(base):
        return base
    return ""


def family_of(token: str) -> str:
    """直譯器家族（python｜powershell｜cmd｜node｜deno｜ruby｜perl｜php｜lua｜shell｜osascript｜mshta｜wsh）；不是回 ""。"""
    if token == "{python}":
        return "python"
    if token == "{node}":
        return "node"
    if "{" in token:
        return ""
    base = _base(token)
    if _PY_NAME.match(base):
        return "python"
    if base in SHELLS:
        return "shell"
    return FAMILIES.get(base, "")


def _program_argv(m: Manifest) -> List[str]:
    if m.kind == "mcp":
        return [str(a) for a in (m.mcp or {}).get("argv") or []]
    if m.kind == "cli":
        return [str(a) for a in (m.cli or {}).get("argv") or []]
    return []


def _sequences(m: Manifest) -> List[tuple]:
    """真的會跑的整條 argv：[(在哪, argv)]。cli＝cli.argv＋每個 command 的 argv（-c 這種旗標可能寫在 command 裡）；
    mcp stdio＝mcp.argv。"""
    prefix = _program_argv(m)
    if m.kind == "cli":
        out = [(f"cli.argv＋command {c.get('name')}", prefix + [str(a) for a in c.get("argv") or []])
               for c in m.commands if isinstance(c, dict)]
        return out or [("cli.argv", prefix)]
    return [("mcp.argv", prefix)] if prefix else []


def _module_inside(m: Manifest, module: str) -> bool:
    top = module.split(".")[0]
    base = m.folder
    return bool(top) and (any(os.path.isfile(os.path.join(base, top + ext)) for ext in PY_SOURCE_EXT)
                          or os.path.isdir(os.path.join(base, top)))


def _inside_token(token: str) -> bool:
    plain = token.replace("\\", "/")
    return plain.startswith(("./", "{pack_dir}/")) and ".." not in plain.split("/")


def _pack_rel(token: str) -> str:
    """./x/y.py、{pack_dir}/x/y.py → x/y.py（呼叫前先確定 _inside_token）。"""
    plain = token.replace("\\", "/")
    rest = plain[len("{pack_dir}/"):] if plain.startswith("{pack_dir}/") else plain[2:]
    return "/".join(p for p in rest.split("/") if p not in ("", "."))


def script_target_problem(m: Manifest, token: str) -> str:
    """{python} 要跑的、在 pack 裡的那支程式（審查 C #C1）：一定要是 .py／.pyw（第 2 關當原始碼掃），
    或是裡面有 __main__.py 的資料夾。其他（./run.txt、./app.pyz、./app.zip、沒有副檔名的 ./run…）Python 照樣會執行，
    第 2 關卻不會當程式碼看 → 回一句理由（擋）；合格回 ""。只查路徑，不執行。"""
    rel = _pack_rel(token)
    path = os.path.join(m.folder, *rel.split("/")) if rel else m.folder
    if os.path.isdir(path):
        if any(os.path.isfile(os.path.join(path, "__main__" + ext)) for ext in PY_SOURCE_EXT):
            return ""
        return (f"{{python}} 要跑的 {token} 是資料夾，但裡面沒有 __main__.py"
                "（只有 .py 原始碼第 2 關看得到）")
    if is_python_source(rel):
        return ""
    return (f"{{python}} 要跑的 {token} 不是 .py：Python 不看副檔名照樣會執行（.txt、.pyz／.zip 的 zipapp、"
            "沒有副檔名的檔…），第 2 關卻不會把它當程式碼掃。請改成 .py 檔（或含 __main__.py 的資料夾）")


def _looks_like_path(token: str) -> bool:
    """argv 後面那幾段「看起來是檔案路徑」：磁碟代號（C:/…）、UNC（\\\\主機）、有兩層以上或有副檔名的 /絕對路徑、..，
    或這台真的有這個檔。/c、/k、/s 這種 Windows 旗標不算（以前會被當成絕對路徑，審查 B #A(3)）。"""
    plain = token.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", plain) or plain.startswith("//") or ".." in plain.split("/"):
        return True
    if plain.startswith(("/", "~")):
        rest = plain.lstrip("/~")
        if "/" in rest or "." in rest:
            return True
        return os.path.exists(token)
    return False


def _script_problem(token: str) -> str:
    """直譯器要跑的那支程式（第一個不是旗標的字）：""＝在 pack 裡或看不出來（相對路徑）；
    "field"＝由使用者填的欄位決定；"outside"＝pack 外（絕對路徑、..、{data_dir}／{user_data_dir} 底下）。"""
    if _inside_token(token):
        return ""
    names = _PLACEHOLDER.findall(token)
    if any(n not in RESERVED_PLACEHOLDERS for n in names):
        return "field"
    if names or _looks_like_path(token):
        return "outside"
    return ""


_PY_NOARG = set("bBdEhIOPqRsSuvVx")       # 不吃值的旗標
_PY_VALUE = set("WXQ")                    # 吃一個值（同一段剩下的，或下一段）


def _python_args(args: Sequence[str]):
    """python 直譯器後面的旗標：一個一個 yield (種類, 字)；種類 inline｜module｜script｜odd。"""
    i = 0
    while i < len(args):
        t = args[i]
        if t == "--":
            if i + 1 < len(args):
                yield "script", args[i + 1]
            return
        if t in ("--version", "--help", "-?"):
            i += 1
            continue
        if t.startswith("--check-hash-based-pycs"):
            i += 1 if "=" in t else 2
            continue
        if t.startswith("--"):
            yield "odd", t
            return
        if t == "-":
            yield "inline", "-（從 stdin 讀程式碼）"
            return
        if t.startswith("-"):
            j = 1
            while j < len(t):
                ch = t[j]
                if ch == "c":
                    yield "inline", t
                    return
                if ch == "i":
                    yield "inline", f"{t}（互動模式：會執行 stdin 送進來的程式碼）"
                    return
                if ch == "m":
                    yield "module", t[j + 1:] or (args[i + 1] if i + 1 < len(args) else "")
                    return
                if ch in _PY_VALUE:
                    if not t[j + 1:]:
                        i += 1
                    break
                if ch not in _PY_NOARG:
                    yield "odd", t
                    return
                j += 1
            i += 1
            continue
        yield "script", t
        return
    yield "inline", "（沒有指定程式：python 會從 stdin 讀程式碼）"


_PS_VALUE = ("executionpolicy", "inputformat", "outputformat", "windowstyle", "configurationname", "workingdirectory",
             "version", "psconsolefile", "settingsfile", "custompipename", "encodedarguments")


def _powershell_args(args: Sequence[str]):
    """powershell／pwsh：-Command／-c／-EncodedCommand／-e／-ec、或任何不是旗標的字（Windows PowerShell 5.1 會把它當指令）
    ＝直接執行；只有 -File <檔> 是跑檔案。參數名照 PowerShell 的規則可以縮寫、不分大小寫，/ 開頭也收。"""
    i = 0
    while i < len(args):
        t = args[i]
        if t[:1] in ("-", "/") and len(t) > 1:
            name = t[1:].split(":", 1)[0].lower()
            if name.startswith("ex"):                       # -ExecutionPolicy Bypass
                i += 2
                continue
            if "command".startswith(name) or "encodedcommand".startswith(name) or name in ("ec", "enc"):
                yield "inline", t
                return
            if "file".startswith(name):
                if i + 1 < len(args):
                    yield "script", args[i + 1]
                    return
                yield "inline", t
                return
            if len(name) >= 2 and any(v.startswith(name) for v in _PS_VALUE):
                i += 2
                continue
            i += 1
            continue
        yield "inline", f"{t}（不是旗標的字：PowerShell 會當成指令執行）"
        return
    yield "inline", "（沒有 -File：PowerShell 會執行 stdin 送進來的指令）"


def _dash_cluster(t: str, letters: str) -> bool:
    """單一個 - 開頭、只有英文字母、含 letters 其中一個（bash -lc、ruby -e、perl -E…）。"""
    return len(t) > 1 and t[0] == "-" and t[1] != "-" and t[1:].isalpha() and any(ch in t[1:] for ch in letters)


def _generic_args(args: Sequence[str], family: str):
    """其他直譯器：旗標裡有「直接執行一段程式碼」的那一種＝inline；第一個不是旗標的字＝script；什麼都沒有＝讀 stdin。"""
    eval_flags = {"node": ("-e", "--eval", "-p", "--print", "-pe", "-ep", "-i", "--interactive", "-r", "--require",
                           "--import", "--loader", "--experimental-loader"),
                  "php": ("-r", "-R", "-B", "-E", "-F", "-a")}.get(family, ())
    letters = {"shell": "cs", "ruby": "e", "perl": "eE", "lua": "e", "osascript": "e"}.get(family, "")
    for i, t in enumerate(args):
        if family == "cmd" and t.lower().startswith(("/c", "/k", "/r")):
            yield "inline", t
            return
        if family == "wsh" and t.lower().startswith(("//e:", "/e:")):
            yield "inline", f"{t}（指定腳本引擎：任何副檔名的檔都會被當程式跑）"
            return
        if family == "deno" and not t.startswith("-"):
            if t in ("eval", "repl"):
                yield "inline", t
                return
            if t in ("run", "serve", "test", "task", "x"):
                continue
        if t == "-":
            yield "inline", "-（從 stdin 讀程式碼）"
            return
        if t in eval_flags or any(t.startswith(f + "=") for f in eval_flags if f.startswith("--")):
            yield "inline", t
            return
        if letters and _dash_cluster(t, letters):
            yield "inline", t
            return
        if t.startswith("-"):
            continue
        if family in ("cmd", "mshta"):
            continue
        yield "script", t
        return
    if family in ("cmd", "mshta"):
        yield "inline", "（cmd／mshta 會直接執行後面的指令字串）"
        return
    if family not in ("wsh", "deno"):
        yield "inline", "（沒有指定程式：會從 stdin 讀程式碼）"


def _interpreter_hits(m: Manifest, token: str, args: Sequence[str]):
    """一個直譯器（token）跟它後面的字 → yield ("inline", 標籤, 說明)｜("external", 程式, "")。"""
    family = family_of(token)
    name = os.path.basename(token.replace("\\", "/")) or token
    gen = _python_args(args) if family == "python" else \
        _powershell_args(args) if family == "powershell" else _generic_args(args, family)
    for kind, value in gen:
        if kind in ("inline", "odd"):
            why = "看不懂的旗標（可能直接執行程式碼）" if kind == "odd" else "直接執行一段沒被第 2 關掃描的程式碼"
            yield "inline", f"{name} {value.split('（')[0].strip() or value}".strip(), f"{name} {value}：{why}"
        elif kind == "module":
            if not value or _PLACEHOLDER.search(value):
                yield "inline", f"{name} -m {value}".strip(), f"{name} -m {value}：要跑的模組由欄位決定（掃不到）"
            elif not _module_inside(m, value):
                yield "external", f"-m {value}", ""
        elif kind == "script":
            problem = _script_problem(value)
            if problem == "" and _inside_token(value) and _PLACEHOLDER.search(_pack_rel(value)):
                problem = "field"                  # ./{欄位}.py：要跑哪個檔由使用者決定（值可以帶 ..）
            if problem == "field":
                yield "inline", f"{name} {value}", f"{name} {value}：要跑哪支程式由使用者填的欄位決定（掃不到）"
            elif problem == "outside":
                yield "external", value, ""
            elif family == "python" and _inside_token(value):
                why = script_target_problem(m, value)
                if why:
                    yield "blocked", value, why


def _argv_hits(m: Manifest) -> List[tuple]:
    """全部 argv 的分析：[(kind, program, detail, where)]，kind＝external（pack 外的程式）｜inline（直接執行程式碼）；
    同一個 program 只留第一筆。"""
    out: List[tuple] = []
    seen = set()

    def add(kind, program, detail, where):
        if (kind, program) not in seen:
            seen.add((kind, program))
            out.append((kind, program, detail, where))

    for where, argv in _sequences(m):
        for i, token in enumerate(argv):
            inside = _inside_token(token)
            if i == 0 and token not in _SYSTEM_PROGRAMS and not inside:
                add("external", token, "", where)
            elif i > 0 and interpreter_of(token) and not inside:
                add("external", token, "", where)
            elif i > 0 and not inside and _looks_like_path(token) and not _PLACEHOLDER.search(token):
                add("external", token, "", where)
            if family_of(token):                           # 直譯器（任何位置：env python -c …、cmd /c node …）
                for hit in _interpreter_hits(m, token, argv[i + 1:]):
                    add(hit[0], hit[1], hit[2], where)
                if family_of(token) != "cmd":              # cmd /c 後面是另一條命令列：照樣往下看（cmd /c node …）
                    break                                  # 後面的字是這個直譯器的參數，分析過了
    return out


def external_programs(m: Manifest) -> List[str]:
    """kind=cli（cli.argv＋每個 command 的 argv）、kind=mcp stdio（mcp.argv）裡指到 pack 外面的程式（樣板原文）：
    argv[0] 不是 {python}、不是 ./ 開頭的 pack 內檔案（{node}、npx、node、git、uvx、絕對路徑…）；後面任何一段是直譯器
    （INTERPRETERS：cmd /c node … 這種）、看起來是檔案路徑（_looks_like_path：C:/…、/usr/bin/x、..；/c 這種旗標不算）；
    直譯器要跑的程式在 pack 外（{data_dir}/x.py、C:/x.py）；{python} -m <模組> 而那個模組不在 pack 資料夾裡（記成 "-m 模組"）。
    {python} 本身解析到 pack 外（envs.python_target）另外記，見 externals()。"""
    return [p for kind, p, _d, _w in _argv_hits(m) if kind == "external"]


def inline_code(m: Manifest) -> List[tuple]:
    """argv 裡「直譯器直接執行一段程式碼」：[(標籤, 說明, 在哪)]（{python} -c、powershell -Command、cmd /c、node -e、
    bash -c…、要跑的程式由欄位決定）。這段程式碼第 2 關掃不到 → 要宣告 exec、算 T2。"""
    return [(p, d, w) for kind, p, d, w in _argv_hits(m) if kind == "inline"]


def _uses_python(m: Manifest) -> bool:
    from synox.packs.manifest import cli_templates, mcp_templates
    templates = mcp_templates(m.mcp) if m.kind == "mcp" else cli_templates(m.cli) if m.kind == "cli" else []
    return any("{python}" in text for _w, text in templates)


def python_external(m: Manifest) -> Optional[dict]:
    """{python} 解析到 pack 外的直譯器（cli.python 絕對路徑、"venv"、runtime.python 指到外面）→ 一筆 external；
    SYNOX 自己的、runtime auto 建的、pack 資料夾裡的 → None。只查路徑，不執行。"""
    if m.kind not in ("cli", "mcp") or not _uses_python(m):
        return None
    from synox.packs import envs
    path, origin, where = envs.python_target(m)
    if origin != envs.PY_OUTSIDE:
        return None
    resolved = path if os.path.exists(path) else f"{path}（這台不存在）"
    return {"program": "{python}", "resolved": resolved, "where": where, "note": "未鎖定執行環境",
            "interpreter": "python"}


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
    if token == "{node}":                          # 照 loader 代換 {node} 的規則找（envs.node_of；只查路徑，不執行）
        from synox.packs import envs
        value = ((getattr(m, "runtime", {}) or {}).get("node") or "") if m is not None else ""
        if value and value != envs.AUTO:
            found = envs.node_of(m)
            return found if os.path.exists(found) else f"{found}（這台不存在）"
        found = envs.system_node(shutil.which)
        return f"{found}（{{node}}＝這台系統的 node，版本沒有鎖住）" if found else "這台的 PATH 找不到 node（{node}）"
    if "{" in token:
        return f"{token}（樣板，執行時才代換）"
    found = shutil.which(token)
    if not found:
        return f"這台的 PATH 找不到 {token}"
    note = "（npx 會在執行時從網路抓套件，版本沒有鎖住）" if os.path.basename(token).lower().startswith("npx") else ""
    return found + note


INLINE_NOTE = "argv 直接執行程式碼（第 2 關掃不到）"


def externals(m: Manifest) -> List[dict]:
    """[{"program", "resolved", "where", "note"}]：pack 外的程式＋解析後的路徑；不進 packs.lock 的雜湊。
    {python} 解析到 pack 外的直譯器也一筆（program="{python}"，where＝決定它的欄位）；
    argv 直接執行程式碼（{python} -c、powershell -Command…）一筆 inline=True（T2；第 2 關另外要求宣告 exec）。"""
    where = "mcp.argv" if m.kind == "mcp" else "cli.argv"
    out = []
    py = python_external(m)
    if py:
        out.append(py)
    for t in external_programs(m):
        e = {"program": t, "resolved": resolve_program(t, m), "where": where, "note": "未鎖定執行環境"}
        interp = interpreter_of(t)
        if interp:                                 # 直譯器：在 pack 外、版本沒鎖；掃描只查路徑，不執行它
            e["interpreter"] = interp
        out.append(e)
    for label, detail, at in inline_code(m):
        out.append({"program": label, "resolved": detail, "where": at, "note": INLINE_NOTE, "inline": True})
    return out


def _inline_findings(m: Manifest) -> List[Finding]:
    return [Finding("pack.json", 0, "exec", label, f"{at}：{detail}（要宣告 exec；算 T2）")
            for label, detail, at in inline_code(m)]


def argv_blocked(m: Manifest) -> List[tuple]:
    """argv 不管宣告什麼都不收的寫法：[(程式, 理由, 在哪)]（{python} 跑 pack 裡不是 .py 的檔，審查 C #C1）。
    第 2 關記成 argv（擋）；loader 載入時也照這個拒（已經裝好的舊 pack）。"""
    return [(p, d, w) for kind, p, d, w in _argv_hits(m) if kind == "blocked"]


def _blocked_findings(m: Manifest) -> List[Finding]:
    return [Finding("pack.json", 0, "argv", program, f"{at}：{detail}") for program, detail, at in argv_blocked(m)]


def _external_findings(report_external: List[dict], label: str) -> List[Finding]:
    return [Finding("pack.json", 0, "external", e["program"],
                    f"{label} 用了 pack 外的程式 {e['program']}（→ {e['resolved']}）：packs.lock 只鎖 pack "
                    "資料夾裡的檔，這支被換掉不會發現（未鎖定執行環境）") for e in report_external if not e.get("inline")]


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
    out += _external_findings(externals(m), "mcp.argv")
    out += _inline_findings(m)
    out += _blocked_findings(m)
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
        report.findings += _external_findings(report.external, "cli.argv")
        report.findings += _inline_findings(m)
        report.findings += _blocked_findings(m)
    return report


def gate2(m: Manifest) -> ScanReport:
    """scan() 的別名（讀起來像管線）。"""
    return scan(m)
