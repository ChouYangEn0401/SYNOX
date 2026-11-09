"""
運行空間（沙盒，PERM-7）：kind=cli 的子程序在什麼範圍裡跑。

    box = sandbox_for(config)                      可替換（set_factory）；預設照 config.json policy.sandbox.backend 挑
    argv2, env2 = box.wrap(argv, env, cwd, grants)  loader 的 make_cli 每次呼叫都過這裡

**介面約定**：wrap 回來的 argv 一定「以原本的 argv 結尾」——JsonCli 會在後面接子指令與 --json，
包一層之後這些字還是交給裡面那個程式。env 是 loader 要加的那幾個變數（不是整份環境）；wrap 可以加、不能漏掉。

grants（Grants）從 pack.json 的宣告算（grants_for）：
- data=user → 可寫 <user_data_dir>/<pack>/（伺服器版＝data/users/<id>/<pack>/）；data=shared → 可寫 data/packs/<pack>/；
  data=none → 不能寫任何 SYNOX 的資料夾。PERM-2 的 data 欄位還沒合進來：沒寫 data 就用 data_scope() 推斷
  （樣板有 {user_data_dir} → user、有 {data_dir} → shared、都沒有 → none），推斷只在 data_scope 這一個函式。
- pack 資料夾、data/envs/<pack>/、Python 本身（sys.prefix）唯讀。
- capabilities 沒有 network → 斷網。mem_mb／procs 來自 policy.sandbox（預設 1024 MB、64 個程序），timeout＝cli.timeout。

後端（config.json policy.sandbox.backend）：
- none：原樣通過（個人版預設；auto 在個人版、Windows 都是 none）。**不是隔離**。
- jobobject（Windows）：只做資源限制——Job Object 的記憶體上限、程序數、launcher 結束就整組關掉。
  做法是先跑這支檔（python -I sandbox.py jobobject …），它把自己放進 Job，再叫原本的程式（子程序繼承 Job）。
  **不限制檔案與網路，所以不算真隔離**。
- bwrap（Linux，建議）：只「組出 argv」：系統資料夾唯讀、grants.read 唯讀、grants.write 可寫、其他（含別人的 data/users）
  根本不在裡面；沒有 network → --unshare-net；一律 --unshare-pid、--die-with-parent、--new-session。
  記憶體／程序數：前面接 prlimit（setrlimit 的 RLIMIT_AS／RLIMIT_NPROC；找不到 prlimit 就不限，doctor 說明）。
- systemd（Linux 替代）：組 systemd-run --pipe --wait 的 --property（MemoryMax、TasksMax、RuntimeMaxSec、PrivateNetwork、
  ProtectSystem=strict、InaccessiblePaths＝SYNOX 的 data、BindReadOnlyPaths／BindPaths 開回 grants）。
  環境變數用 --setenv=名字（只有名字，值由 systemd-run 從自己的環境拿：密鑰不進 argv）。
- appcontainer（Windows，未來）：只有介面，wrap 丟 NotImplementedError（說明見 docs/security.md）。

真隔離＝bwrap／systemd（而且這台電腦找得到那個程式）。policy.sandbox.required_for（預設 "third-party"）命中的 cli pack，
在伺服器版又沒有真隔離 → 只對擁有者可見（loader 把群組改成 owner_only，doctor 說明原因）。個人版不受影響。
這支檔只用標準函式庫（jobobject 的 launcher 用 python -I 直接跑這個檔）。
**沙盒後端的真機驗證要在 Linux 伺服器上做；寫這一版的 Windows 電腦只驗證了組出來的 argv。**
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

BACKENDS = ("auto", "none", "jobobject", "bwrap", "systemd", "appcontainer")
REAL_ISOLATION = ("bwrap", "systemd", "appcontainer")
REQUIRED_FOR = ("third-party", "all", "none")
CORE, THIRD_PARTY = "core", "third-party"
TRUSTS = (CORE, THIRD_PARTY)
DATA_SCOPES = ("none", "user", "shared")
DEFAULTS = {"backend": "auto", "required_for": "third-party", "mem_mb": 1024, "max_procs": 64}

# bwrap：放進沙盒的系統資料夾（唯讀；不存在就跳過）
SYSTEM_RO = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc/alternatives", "/etc/ld.so.cache",
             "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/localtime", "/etc/passwd", "/etc/group")
NETWORK_RO = ("/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/ssl", "/etc/ca-certificates",
              "/etc/pki")
# systemd：子程序一定要有的環境變數（--setenv=名字，值從 systemd-run 自己的環境拿）
BASE_ENV = ("PATH", "LANG", "LC_ALL", "PYTHONIOENCODING", "HOME", "TZ")


@dataclass(frozen=True)
class Grants:
    """這一次呼叫給子程序的範圍。read／write：絕對路徑；network：能不能連網；mem_mb／procs：資源上限（None＝不限）；
    timeout：秒（None＝照 JsonCli）；pass_env：systemd 後端要另外帶進去的環境變數名字（requires.env 列的密鑰名）；
    hide：要整個藏起來的資料夾（SYNOX 的 data；bwrap 本來就看不到沒掛的，systemd 用 InaccessiblePaths）。"""
    read: Tuple[str, ...] = ()
    write: Tuple[str, ...] = ()
    network: bool = False
    mem_mb: Optional[int] = None
    timeout: Optional[float] = None
    procs: Optional[int] = None
    pass_env: Tuple[str, ...] = ()
    hide: Tuple[str, ...] = ()


class Sandbox:
    """介面。name：後端名字；isolates：算不算真隔離（檔案＋網路都限制）；problem：設定了卻用不了的原因（""＝沒問題）。"""
    name = "none"
    isolates = False
    problem = ""

    def available(self) -> bool:
        return True

    def wrap(self, argv: Sequence[str], env: Optional[Dict[str, str]], cwd: str,
             grants: Grants) -> Tuple[List[str], Dict[str, str]]:   # pragma: no cover - 介面
        raise NotImplementedError

    def describe(self) -> str:
        return self.name


class NoneSandbox(Sandbox):
    """原樣通過（個人版預設）。"""
    name = "none"

    def __init__(self, problem: str = ""):
        self.problem = problem

    def wrap(self, argv, env, cwd, grants):
        return [str(a) for a in argv], dict(env or {})

    def describe(self) -> str:
        return "none（不隔離：子程序跟 SYNOX 一樣看得到整台電腦）"


class JobObjectSandbox(Sandbox):
    """Windows 的資源限制：python -I <這支檔> jobobject --mem-mb N --procs N -- <原本的 argv>。"""
    name = "jobobject"
    isolates = False

    def __init__(self, python: str = "", script: str = ""):
        self.python = python or sys.executable
        self.script = script or os.path.abspath(__file__)

    def available(self) -> bool:
        return os.name == "nt"

    def wrap(self, argv, env, cwd, grants):
        out = [self.python, "-I", self.script, "jobobject"]
        if grants.mem_mb:
            out += ["--mem-mb", str(int(grants.mem_mb))]
        if grants.procs:
            out += ["--procs", str(int(grants.procs))]
        return out + ["--"] + [str(a) for a in argv], dict(env or {})

    def describe(self) -> str:
        return "jobobject（只限制記憶體與程序數；檔案、網路不限制，不算隔離）"


class BwrapSandbox(Sandbox):
    """Linux bubblewrap：只組 argv。which 可以換（測試）；exists 決定系統資料夾用 --ro-bind-try（預設一律 -try）。"""
    name = "bwrap"
    isolates = True

    def __init__(self, which: Callable[[str], Optional[str]] = shutil.which):
        self.which = which

    def available(self) -> bool:
        return bool(self.which("bwrap"))

    def rlimit_prefix(self, grants: Grants) -> List[str]:
        """setrlimit：prlimit --as=<位元組> --nproc=<個數> --（RLIMIT_AS 算虛擬記憶體，Node 這種會先保留大量位址空間的程式要給大一點；
        RLIMIT_NPROC 算的是同一個 uid 的所有程序——SYNOX 用專用帳號跑才準）。找不到 prlimit＝不限。"""
        prlimit = self.which("prlimit")
        if not prlimit or not (grants.mem_mb or grants.procs):
            return []
        out = [prlimit]
        if grants.mem_mb:
            out.append(f"--as={int(grants.mem_mb) * 1024 * 1024}")
        if grants.procs:
            out.append(f"--nproc={int(grants.procs)}")
        return out + ["--"]

    def wrap(self, argv, env, cwd, grants):
        out = self.rlimit_prefix(grants)
        out += [self.which("bwrap") or "bwrap", "--die-with-parent", "--new-session",
                "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-cgroup-try"]
        if not grants.network:
            out.append("--unshare-net")
        for p in SYSTEM_RO + (NETWORK_RO if grants.network else ()):
            out += ["--ro-bind-try", p, p]
        out += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
        for p in grants.read:
            out += ["--ro-bind-try", p, p]
        for p in grants.write:                 # 寫的放在讀的後面：唯讀資料夾裡面的可寫子資料夾才蓋得過去
            out += ["--bind", p, p]
        out += ["--chdir", cwd, "--"]
        return out + [str(a) for a in argv], dict(env or {})

    def describe(self) -> str:
        extra = "" if self.which("prlimit") else "；找不到 prlimit，記憶體／程序數不限"
        return f"bwrap（檔案只看得到宣告的、沒宣告 network 就斷網{extra}）"


class SystemdSandbox(Sandbox):
    """systemd-run 的暫時服務：只組 argv。scope="system"（預設，SYNOX 的帳號要有權限開系統服務）｜"user"
    （使用者服務：PrivateNetwork、ProtectSystem 這些要 user namespace，舊系統可能不生效——一定要在伺服器上驗）。"""
    name = "systemd"
    isolates = True

    def __init__(self, which: Callable[[str], Optional[str]] = shutil.which, scope: str = "system"):
        self.which = which
        self.scope = scope

    def available(self) -> bool:
        return bool(self.which("systemd-run"))

    def wrap(self, argv, env, cwd, grants):
        out = [self.which("systemd-run") or "systemd-run"]
        if self.scope == "user":
            out.append("--user")
        out += ["--pipe", "--wait", "--collect", "--quiet", f"--working-directory={cwd}"]
        props = ["NoNewPrivileges=yes", "PrivateTmp=yes", "PrivateDevices=yes", "ProtectSystem=strict",
                 "ProtectHome=read-only"]
        if grants.mem_mb:
            props += [f"MemoryMax={int(grants.mem_mb)}M", "MemorySwapMax=0"]
        if grants.procs:
            props.append(f"TasksMax={int(grants.procs)}")
        if grants.timeout:
            props.append(f"RuntimeMaxSec={int(grants.timeout)}")
        if not grants.network:
            props += ["PrivateNetwork=yes", "IPAddressDeny=any"]
        if grants.hide:
            props.append("InaccessiblePaths=" + " ".join(f"-{p}" for p in grants.hide))
        if grants.read:
            props.append("BindReadOnlyPaths=" + " ".join(f"-{p}" for p in grants.read))
        if grants.write:
            props.append("BindPaths=" + " ".join(grants.write))
        for p in props:
            out += ["--property", p]
        names = []
        for name in tuple(BASE_ENV) + tuple(sorted(env or {})) + tuple(grants.pass_env):
            if name not in names:
                names.append(name)
        out += [f"--setenv={n}" for n in names]
        return out + ["--"] + [str(a) for a in argv], dict(env or {})

    def describe(self) -> str:
        return f"systemd（systemd-run {self.scope} 服務：cgroup 記憶體／程序數、唯讀系統、沒宣告 network 就斷網）"


APPCONTAINER_TODO = ("appcontainer 後端還沒做（只有介面）：Windows 上要用 CreateAppContainerProfile＋"
                     "SECURITY_CAPABILITIES 開程序、對 grants 的資料夾加 ACL，見 docs/security.md「沙盒」的未來項目。")


class AppContainerSandbox(Sandbox):
    """Windows AppContainer（未來）：只有介面。"""
    name = "appcontainer"
    isolates = True

    def available(self) -> bool:
        return False

    def wrap(self, argv, env, cwd, grants):
        raise NotImplementedError(APPCONTAINER_TODO)

    def describe(self) -> str:
        return "appcontainer（還沒做）"


# ── 設定與後端選擇 ────────────────────────────────────────────────────────

def parse_settings(raw) -> dict:
    """config.json policy.sandbox → 補好預設值的 dict。不合丟 ValueError（policy.parse_policy 轉成 ConfigError）。"""
    raw = dict(raw or {})
    out = {**DEFAULTS, **raw}
    if out["backend"] not in BACKENDS:
        raise ValueError(f"policy.sandbox.backend 只能是 {'、'.join(BACKENDS)}（現在是 {out['backend']!r}）。")
    if out["required_for"] not in REQUIRED_FOR:
        raise ValueError(f"policy.sandbox.required_for 只能是 {'、'.join(REQUIRED_FOR)}"
                         f"（現在是 {out['required_for']!r}）。")
    for key in ("mem_mb", "max_procs"):
        value = out[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"policy.sandbox.{key} 要是 0 以上的整數（0＝不限）。")
    if out.get("systemd_scope", "system") not in ("system", "user"):
        raise ValueError("policy.sandbox.systemd_scope 只能是 system 或 user。")
    return out


def settings_of(config) -> dict:
    policy = getattr(config, "policy", None) if config is not None else None
    raw = policy.get("sandbox") if isinstance(policy, dict) else None
    try:
        return parse_settings(raw)
    except ValueError:
        return dict(DEFAULTS)


def mode_of(config) -> str:
    return str(getattr(config, "mode", "personal") or "personal")


def resolve(settings: dict, mode: str = "personal", *, platform: str = sys.platform,
            which: Callable[[str], Optional[str]] = shutil.which) -> Sandbox:
    """設定 → 後端。auto：個人版、Windows＝none；Linux 伺服器版＝bwrap，沒有就 systemd，都沒有＝none。
    明寫的後端用不了（找不到 bwrap…）＝none，problem 寫原因（fail closed：真隔離＝否，第三方 pack 只給擁有者）。"""
    backend = settings.get("backend", "auto")
    linux = platform.startswith("linux")
    if backend == "auto":
        if mode != "server" or not linux:
            return NoneSandbox()
        for candidate in (BwrapSandbox(which), SystemdSandbox(which, settings.get("systemd_scope", "system"))):
            if candidate.available():
                return candidate
        return NoneSandbox("auto：這台找不到 bwrap 也找不到 systemd-run")
    if backend == "none":
        return NoneSandbox()
    if backend == "jobobject":
        box = JobObjectSandbox()
        return box if platform.startswith("win") else NoneSandbox("jobobject 只有 Windows 有")
    if backend == "appcontainer":
        return NoneSandbox(APPCONTAINER_TODO)
    box = BwrapSandbox(which) if backend == "bwrap" else SystemdSandbox(which, settings.get("systemd_scope", "system"))
    if not linux:
        return NoneSandbox(f"{backend} 只有 Linux 有")
    if not box.available():
        return NoneSandbox(f"設定了 {backend}，但這台找不到 {'bwrap' if backend == 'bwrap' else 'systemd-run'}")
    return box


def default_factory(config) -> Sandbox:
    return resolve(settings_of(config), mode_of(config))


_factory: Callable[[object], Sandbox] = default_factory


def set_factory(factory: Optional[Callable[[object], Sandbox]]) -> None:
    """換掉後端的選法（測試給假後端；None＝回到照設定挑）。factory(config) → Sandbox。"""
    global _factory
    _factory = factory or default_factory


def sandbox_for(config) -> Sandbox:
    return _factory(config)


# ── 從宣告算 grants ───────────────────────────────────────────────────────

def _templates(m) -> List[str]:
    cli = getattr(m, "cli", {}) or {}
    raw = getattr(m, "raw", {}) or {}
    out = [str(x) for x in cli.get("argv") or []]
    out.append(str(cli.get("cwd") or ""))
    out += [str(v) for v in (cli.get("env") or {}).values()]
    out += [str(v) for v in (raw.get("env") or {}).values()] if isinstance(raw.get("env"), dict) else []
    for c in cli.get("commands") or []:
        out += [str(x) for x in c.get("argv") or []]
        if isinstance(c.get("stdin"), str):
            out.append(c["stdin"])
    return out


def data_scope(m) -> str:
    """這個 pack 的資料屬於誰：none｜user｜shared。**推斷都在這裡**（PERM-2 合進來後 pack.json 的 data 欄位優先）：
    pack.json 有 data → 用它；kind=cli 看樣板：有 {user_data_dir} → user，有 {data_dir} → shared，都沒有 → none；
    kind=python：有 storage → user（spec 的預設）。"""
    declared = (getattr(m, "raw", {}) or {}).get("data")
    if declared in DATA_SCOPES:
        return declared
    if getattr(m, "kind", "") == "cli":
        text = "\n".join(_templates(m))
        if "{user_data_dir}" in text:
            return "user"
        if "{data_dir}" in text:
            return "shared"
        return "none"
    return "user" if (getattr(m, "raw", {}) or {}).get("storage") else "none"


def trust_of(data_dir: str, m) -> str:
    """core｜third-party。packs.lock 的 trust（安裝時擁有者選的；之後的階段寫）優先；
    沒寫：經安裝流程從檔案裝進來的（lock 的 via＝web／console）＝third-party；出廠的、工程師自己放的＝core。"""
    from synox.packs import lock as pack_lock
    found = pack_lock.entry(data_dir, m.name) if data_dir else None
    if not found:
        return CORE
    if found.get("trust") in TRUSTS:
        return found["trust"]
    return THIRD_PARTY if found.get("via") in ("web", "console") else CORE


def required(config, m) -> bool:
    """policy.sandbox.required_for 命中這個 pack 嗎（只看 kind=cli：python pack 在程序裡跑，沙盒管不到，見 PERM-8）。"""
    if getattr(m, "kind", "") != "cli":
        return False
    rule = settings_of(config).get("required_for", "third-party")
    if rule == "all":
        return True
    if rule == "none":
        return False
    return trust_of(getattr(config, "data_dir", ""), m) == THIRD_PARTY


def restricted_reason(config, m, box: Optional[Sandbox] = None) -> str:
    """伺服器版、required_for 命中、又沒有真隔離 → 一句話說為什麼只給擁有者（""＝不受影響）。"""
    if mode_of(config) != "server" or not required(config, m):
        return ""
    box = box if box is not None else sandbox_for(config)
    if box.isolates:
        return ""
    why = f"（{box.problem}）" if box.problem else ""
    return (f"只對擁有者開放：policy.sandbox.required_for={settings_of(config).get('required_for')} 要求沙盒，"
            f"但目前的後端是 {box.name}{why}，不算真隔離（要 bwrap 或 systemd）")


def grants_for(m, config, ph: Dict[str, str], *, pass_env: Sequence[str] = ()) -> Grants:
    """pack.json 的宣告＋這一次的人（ph＝loader.placeholders）→ Grants。"""
    from synox.packs import envs
    settings = settings_of(config)
    data_dir = getattr(config, "data_dir", "") or ph.get("data_dir", "")
    scope = data_scope(m)
    write: List[str] = []
    if scope == "user":
        write.append(os.path.join(ph.get("user_data_dir") or data_dir, m.name))
    elif scope == "shared":
        write.append(os.path.join(data_dir, "packs", m.name))
    read = [m.folder, envs.env_dir(data_dir, m.name)]
    for p in (sys.prefix, getattr(sys, "base_prefix", sys.prefix)):
        if p and p not in read:
            read.append(p)
    timeout = (getattr(m, "cli", {}) or {}).get("timeout", 120)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        timeout = 120.0
    return Grants(read=tuple(os.path.normpath(p) for p in read), write=tuple(os.path.normpath(p) for p in write),
                  network="network" in (getattr(m, "capabilities", None) or ()),
                  mem_mb=settings.get("mem_mb") or None, procs=settings.get("max_procs") or None,
                  timeout=timeout, pass_env=tuple(pass_env), hide=(os.path.normpath(data_dir),) if data_dir else ())


def doctor_line(config) -> Tuple[str, int]:
    """doctor 的一行：目前的後端、算不算真隔離。回 (行, 要處理的個數)。"""
    box = sandbox_for(config)
    settings = settings_of(config)
    real = "是" if box.isolates else "否"
    line = (f"• 沙盒：後端 {box.describe()}；真隔離：{real}"
            f"（設定 backend={settings.get('backend')}、required_for={settings.get('required_for')}）")
    bad = 0
    if box.problem:
        line += f"\n  ⚠️ {box.problem}"
        bad += settings.get("backend") != "auto"          # 明寫的後端用不了才算問題；auto 找不到只是提醒
    if mode_of(config) == "server" and not box.isolates and settings.get("required_for") != "none":
        line += "\n  ⚠️ 伺服器版沒有真隔離：要沙盒的 cli pack 只對擁有者開放（Linux 裝 bubblewrap 後 backend 寫 auto 或 bwrap）"
    return line, bad


# ── jobobject 的 launcher（python -I sandbox.py jobobject --mem-mb N --procs N -- argv…） ─────────────

JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


def job_structs(ctypes_mod=None):
    """JOBOBJECT_EXTENDED_LIMIT_INFORMATION 的 ctypes 結構（winnt.h 的欄位順序）。"""
    import ctypes as _ctypes
    c = ctypes_mod or _ctypes

    class IO_COUNTERS(c.Structure):
        _fields_ = [(n, c.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                  "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(c.Structure):
        _fields_ = [("PerProcessUserTimeLimit", c.c_int64), ("PerJobUserTimeLimit", c.c_int64),
                    ("LimitFlags", c.c_uint32), ("MinimumWorkingSetSize", c.c_size_t),
                    ("MaximumWorkingSetSize", c.c_size_t), ("ActiveProcessLimit", c.c_uint32),
                    ("Affinity", c.c_size_t), ("PriorityClass", c.c_uint32), ("SchedulingClass", c.c_uint32)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(c.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", c.c_size_t), ("JobMemoryLimit", c.c_size_t),
                    ("PeakProcessMemoryUsed", c.c_size_t), ("PeakJobMemoryUsed", c.c_size_t)]

    return JOBOBJECT_EXTENDED_LIMIT_INFORMATION


def apply_job_limits(mem_mb: Optional[int], procs: Optional[int], *, kernel32=None, ctypes_mod=None):
    """建一個 Job Object、設上限、把目前這個程序放進去（之後叫的子程序繼承）。回 (job handle, 設定的結構)。
    kernel32：測試給假的（記錄呼叫，不真的呼叫 Windows）。失敗丟 OSError。
    procs 是「裡面的程式」能開幾個：launcher 自己也在 Job 裡，所以上限 +1。"""
    import ctypes as _ctypes
    c = ctypes_mod or _ctypes
    if kernel32 is None:                                     # pragma: no cover - 只在 Windows 真的跑
        kernel32 = c.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = c.c_void_p
        kernel32.CreateJobObjectW.argtypes = [c.c_void_p, c.c_wchar_p]
        kernel32.SetInformationJobObject.argtypes = [c.c_void_p, c.c_int, c.c_void_p, c.c_uint32]
        kernel32.GetCurrentProcess.restype = c.c_void_p
        kernel32.AssignProcessToJobObject.argtypes = [c.c_void_p, c.c_void_p]
    info = job_structs(c)()
    flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
    if mem_mb:
        flags |= JOB_OBJECT_LIMIT_JOB_MEMORY
        info.JobMemoryLimit = int(mem_mb) * 1024 * 1024
    if procs:
        flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        info.BasicLimitInformation.ActiveProcessLimit = int(procs) + 1
    info.BasicLimitInformation.LimitFlags = flags
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError("CreateJobObjectW 失敗")
    if not kernel32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, c.byref(info),
                                            c.sizeof(info)):
        raise OSError("SetInformationJobObject 失敗")
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        raise OSError("AssignProcessToJobObject 失敗")
    return job, info


def parse_launcher(args: Sequence[str]) -> Tuple[Optional[int], Optional[int], List[str]]:
    """jobobject [--mem-mb N] [--procs N] -- argv… → (mem_mb, procs, argv)。不合丟 ValueError。"""
    args = list(args)
    if not args or args[0] != "jobobject" or "--" not in args:
        raise ValueError("用法：sandbox.py jobobject [--mem-mb N] [--procs N] -- 程式 參數…")
    split = args.index("--")
    opts, rest = args[1:split], args[split + 1:]
    mem_mb = procs = None
    i = 0
    while i < len(opts):
        if opts[i] in ("--mem-mb", "--procs") and i + 1 < len(opts):
            value = int(opts[i + 1])
            if opts[i] == "--mem-mb":
                mem_mb = value
            else:
                procs = value
            i += 2
            continue
        raise ValueError(f"不認得 {opts[i]!r}")
    if not rest:
        raise ValueError("-- 後面沒有要跑的程式")
    return mem_mb, procs, rest


def main(args: Sequence[str], *, kernel32=None, run=subprocess.call) -> int:
    """launcher：設好 Job 才跑；設不起來就不跑（印一行 JSON 給 JsonCli，不會變成「沒限制照跑」）。"""
    import json
    try:
        mem_mb, procs, rest = parse_launcher(args)
        apply_job_limits(mem_mb, procs, kernel32=kernel32)
    except (ValueError, OSError, AttributeError) as e:
        print(json.dumps({"ok": False, "reason": f"沙盒（jobobject）設不起來，沒有執行：{e}"}, ensure_ascii=False))
        return 126
    return int(run(rest))


if __name__ == "__main__":                                 # pragma: no cover - launcher
    sys.exit(main(sys.argv[1:]))
