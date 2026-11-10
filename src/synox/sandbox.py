"""
運行空間（沙盒，PERM-7）：kind=cli 的子程序（與 kind=mcp stdio 的長駐子程序，P4a）在什麼範圍裡跑。

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
- container（S1，每個 pack 自己的）：pack.json 有 runtime.container（packs/container.py 第 1 關）、packs.lock 的
  runtime.mode=container（安裝時擁有者選）、這台找得到引擎（policy.sandbox.engine：auto＝podman → docker；只用 which）
  → ContainerSandbox 組 `podman|docker run --rm -i --pull=never --network none --read-only --cap-drop ALL …`。
  box_for(config, m) 決定這一次用哪個：選了容器又有引擎＝容器，否則照上面的 backend（找不到引擎時 doctor 說原因）。
  代換用 view_for(box, ph)：容器裡 {pack_dir}＝/pack、{user_data_dir}＝/data/user、{data_dir}＝/data/shared、{python}＝python3。
  set_engine_which／set_container_factory 給測試換（**測試絕不執行 podman／docker**）。

真隔離＝bwrap／systemd／container（而且這台電腦找得到那個程式）。policy.sandbox.required_for（預設 "third-party"）命中的 cli pack，
在伺服器版又沒有真隔離 → 只對擁有者可見（loader 把群組改成 owner_only，doctor 說明原因）。個人版不受影響。
T2 pack（SDK P7，packs/tier.py：掃不到內容的執行檔／外部程式／runtime auto 套件）一定命中，不管 trust、required_for；
T2 的 python pack 在程序裡跑、包不到，伺服器版一律只給擁有者。個人版的 T2 照用，doctor 提醒（t2_personal_note）。
這支檔只用標準函式庫（jobobject 的 launcher 用 python -I 直接跑這個檔）。
**沙盒後端的真機驗證要在 Linux 伺服器上做；寫這一版的 Windows 電腦只驗證了組出來的 argv。**
（容器的清單：docs/handoff/container-verification.md）
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

BACKENDS = ("auto", "none", "jobobject", "bwrap", "systemd", "appcontainer")
REAL_ISOLATION = ("bwrap", "systemd", "container", "appcontainer")
REQUIRED_FOR = ("third-party", "all", "none")
CORE, THIRD_PARTY = "core", "third-party"
TRUSTS = (CORE, THIRD_PARTY)
DATA_SCOPES = ("none", "user", "shared")
ENGINES = ("podman", "docker")                      # 容器引擎（auto 的順序：rootless podman 優先，擁有者 Q2）
ENGINE_SETTINGS = ("auto",) + ENGINES
RUNTIME_MODES = ("container", "host")                # packs.lock 的 runtime.mode：安裝時擁有者選的
DEFAULTS = {"backend": "auto", "required_for": "third-party", "mem_mb": 1024, "max_procs": 64, "engine": "auto"}

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


CONTAINER_TMPFS = "/tmp:rw,noexec,nosuid,nodev,size=64m"
CONTAINER_HOME = "/tmp"
NOBODY = "65534:65534"
_MOUNT_BAD = (",", '"', "\n", "\r", "\x00")          # --mount 是逗號分隔的 key=value：本機路徑有這些字就不掛（不猜跳脫）


class ContainerSandbox(Sandbox):
    """pack 自己的容器（S1；pack.json runtime.container、packs.lock runtime.mode=container）：只組 argv，**不執行引擎**。

        <podman|docker> run --rm -i --pull=never --name synox-<pack>-<tg_id>-<亂數> --label synox.pack=<pack>
          --network none（沒宣告 network） --read-only --tmpfs /tmp:… --cap-drop ALL --security-opt no-new-privileges
          --pids-limit N --memory Nm --memory-swap Nm [--cpus X]
          podman：--userns=keep-id（＝SYNOX 帳號的 uid，非 root）｜docker：--user <uid>:<gid>（Windows：65534:65534）
          --mount type=bind,source=<pack 資料夾>,target=/pack,readonly
          --mount type=bind,source=<grants.write>,target=/data/user/<pack>（或 /data/shared/packs/<pack>）
          --workdir <cwd 在容器裡的路徑> --env HOME=/tmp --env 名字…（只有名字，值由引擎從 SYNOX 的環境拿）
          <image@sha256:…> <原本的 argv（loader 已經用 view() 換成容器裡的路徑）>

    絕對不加：--privileged、--network host、docker.sock、--cap-add、--device（第 1 關也不收這些欄位）。
    grants.read 裡 pack 資料夾以外的（data/envs、SYNOX 的 Python）不掛：容器用映像自己的 Python。
    which／uid／nonce 可以換（測試）。**真機驗證見 docs/handoff/container-verification.md**。"""
    name = "container"
    isolates = True

    def __init__(self, engine: str = "podman", spec: Optional[dict] = None, *, image: str = "", pack: str = "",
                 pack_dir: str = "", scope: str = "none", which: Callable[[str], Optional[str]] = shutil.which,
                 platform: str = sys.platform, uid: Optional[int] = None, gid: Optional[int] = None,
                 nonce: Optional[Callable[[], str]] = None):
        if engine not in ENGINES:
            raise ValueError(f"容器引擎只能是 {'、'.join(ENGINES)}")
        self.engine = engine
        self.spec = dict(spec or {})
        self.image = image or self.spec.get("image", "")
        self.pack = pack
        self.pack_dir = pack_dir
        self.scope = scope
        self.which = which
        self.platform = platform
        self.uid = uid
        self.gid = gid
        self.nonce = nonce
        mounts = self.spec.get("mounts") or {}
        self.mount_pack = mounts.get("pack", "/pack")
        self.mount_user = mounts.get("user_data", "/data/user")
        self.mount_shared = mounts.get("shared_data", "/data/shared")

    def available(self) -> bool:
        return bool(self.which(self.engine))

    def view(self, ph: Dict[str, str]) -> Dict[str, str]:
        """loader.placeholders → 容器裡的路徑（{pack_dir}、{user_data_dir}、{data_dir}、{python}、{node}）。"""
        return {**ph, "pack_dir": self.mount_pack, "user_data_dir": self.mount_user, "data_dir": self.mount_shared,
                "python": self.spec.get("python", "python3"), "node": self.spec.get("node", "node")}

    def write_target(self) -> str:
        """grants.write（data=user：<user_data_dir>/<pack>；shared：<data_dir>/packs/<pack>）在容器裡的路徑。"""
        if self.scope == "shared":
            return f"{self.mount_shared}/packs/{self.pack}"
        return f"{self.mount_user}/{self.pack}"

    def _container_path(self, host: str, grants: Grants) -> str:
        """本機路徑（cwd）→ 容器裡的路徑；不在掛進來的資料夾裡＝pack 的路徑。"""
        pairs = [(self.pack_dir, self.mount_pack)] + [(w, self.write_target()) for w in grants.write]
        for base, target in pairs:
            if not base:
                continue
            try:
                rel = os.path.relpath(os.path.normpath(host), os.path.normpath(base))
            except ValueError:                    # 不同磁碟機
                continue
            if rel == ".":
                return target
            if not rel.startswith(".."):
                return target + "/" + rel.replace(os.sep, "/")
        return self.mount_pack

    def _user_args(self) -> List[str]:
        user = self.spec.get("user", "nonroot")
        if user != "nonroot":
            return ["--user", user]
        if self.engine == "podman":
            return ["--userns=keep-id"]                    # rootless：容器裡就是 SYNOX 帳號的 uid（不是 root）
        if self.platform.startswith("win"):
            return ["--user", NOBODY]
        uid = self.uid if self.uid is not None else getattr(os, "getuid", lambda: 65534)()
        gid = self.gid if self.gid is not None else getattr(os, "getgid", lambda: 65534)()
        return ["--user", NOBODY if not uid else f"{uid}:{gid}"]   # SYNOX 用 root 跑時退回 nobody

    @staticmethod
    def _mount(source: str, target: str, readonly: bool) -> List[str]:
        if any(c in source for c in _MOUNT_BAD):
            raise ValueError(f"容器後端掛不了這個資料夾（路徑裡有逗號、引號或換行）：{source!r}；"
                             "把 SYNOX 的資料夾搬到沒有這些字的路徑")
        return ["--mount", f"type=bind,source={source},target={target}" + (",readonly" if readonly else "")]

    def limits(self, grants: Grants) -> Tuple[Optional[int], Optional[int], Optional[float]]:
        """(記憶體 MB, 程序數, CPU)：pack 寫的只能比 policy.sandbox 小（取小的）。"""
        res = self.spec.get("resources") or {}
        mem = [v for v in (grants.mem_mb, res.get("mem_mb")) if v]
        pids = [v for v in (grants.procs, res.get("pids")) if v]
        return (min(mem) if mem else None), (min(pids) if pids else None), res.get("cpus")

    def wrap(self, argv, env, cwd, grants):
        env = dict(env or {})
        nonce = self.nonce() if self.nonce else secrets.token_hex(4)
        who = "".join(c for c in str(env.get("SYNOX_TG_ID") or "x") if c.isalnum()) or "x"
        out = [self.which(self.engine) or self.engine, "run", "--rm", "-i", "--pull=never",
               "--name", f"synox-{self.pack or 'pack'}-{who}-{nonce}", "--label", f"synox.pack={self.pack}"]
        if not grants.network:
            out += ["--network", "none"]
        out += ["--read-only", "--tmpfs", CONTAINER_TMPFS, "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges"]
        mem, pids, cpus = self.limits(grants)
        if pids:
            out += ["--pids-limit", str(int(pids))]
        if mem:
            out += ["--memory", f"{int(mem)}m", "--memory-swap", f"{int(mem)}m"]
        if cpus:
            out += ["--cpus", f"{float(cpus):g}"]
        out += self._user_args()
        if self.pack_dir:
            out += self._mount(os.path.normpath(self.pack_dir), self.mount_pack, True)
        for w in grants.write:
            out += self._mount(os.path.normpath(w), self.write_target(), False)
        out += ["--workdir", self._container_path(cwd, grants), "--env", f"HOME={CONTAINER_HOME}"]
        allow = self.spec.get("env_passthrough")
        names: List[str] = []
        for n in tuple(sorted(env)) + tuple(n for n in grants.pass_env if allow is None or n in allow):
            if n not in names and n != "HOME":
                names.append(n)
        for n in names:
            out += ["--env", n]                            # 只有名字：值由引擎從自己的環境拿（不進 argv）
        out.append(self.image)
        return out + [str(a) for a in argv], env

    def describe(self) -> str:
        how = "rootless podman：容器裡是 SYNOX 帳號的 uid" if self.engine == "podman" else \
            "docker：daemon 是 root 時，能叫 docker 的帳號等於 root"
        return (f"container（{self.engine}；{how}；斷網、唯讀根目錄、--cap-drop ALL、只掛 pack 與自己那一格資料夾；"
                f"映像 {self.image[:60] or '（沒有）'}）")


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
    if out["engine"] not in ENGINE_SETTINGS:
        raise ValueError(f"policy.sandbox.engine 只能是 {'、'.join(ENGINE_SETTINGS)}（現在是 {out['engine']!r}）。")
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


def pick_engine(settings: dict, which: Callable[[str], Optional[str]] = shutil.which) -> str:
    """policy.sandbox.engine → 這台找得到的容器引擎名字（""＝沒有）。auto：podman（rootless 優先）→ docker。
    **只用 which 看 PATH，不執行引擎**（不知道是不是 rootless、daemon 有沒有開——doctor 照實說）。"""
    wanted = settings.get("engine", "auto")
    for engine in (ENGINES if wanted == "auto" else (wanted,)):
        if which(engine):
            return engine
    return ""


def engines_text(settings: dict) -> str:
    wanted = settings.get("engine", "auto")
    return "podman 或 docker" if wanted == "auto" else wanted


def resolve(settings: dict, mode: str = "personal", *, platform: str = sys.platform,
            which: Callable[[str], Optional[str]] = shutil.which, container: Optional[dict] = None) -> Sandbox:
    """設定 → 後端。auto：個人版、Windows＝none；Linux 伺服器版＝bwrap，沒有就 systemd，都沒有＝none。
    明寫的後端用不了（找不到 bwrap…）＝none，problem 寫原因（fail closed：真隔離＝否，第三方 pack 只給擁有者）。
    container（container_target 的結果：這個 pack 有 runtime.container、擁有者選了容器）：先照 policy.sandbox.engine
    找引擎（auto：podman → docker；任何平台都可以，Windows 是使用者自己裝的 Docker Desktop）→ ContainerSandbox；
    找不到引擎＝退回上面的規則（Linux 伺服器版：bwrap → systemd → none），problem 寫「選了容器但找不到引擎」。"""
    if container is not None:
        engine = pick_engine(settings, which)
        if engine:
            return container_box(engine, container, which=which, platform=platform)
        host = resolve(settings, mode, platform=platform, which=which)
        note = f"選了容器，但這台找不到 {engines_text(settings)}：改用 {host.name}"
        host.problem = note + (f"；{host.problem}" if host.problem else "")
        return host
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


# ── 每個 pack 自己的容器（S1／S2） ──────────────────────────────────────

def container_spec(m) -> Optional[dict]:
    """pack.json 的 runtime.container（第 1 關整理過的）；沒寫回 None。"""
    spec = (getattr(m, "runtime", None) or {}).get("container")
    return spec if isinstance(spec, dict) else None


def runtime_mode(config, m) -> str:
    """container｜host：packs.lock 的 runtime.mode（安裝時擁有者選的；packs runtime 可以改）。
    沒有 runtime.container、沒有鎖、鎖裡沒寫＝host。"""
    if container_spec(m) is None:
        return "host"
    data_dir = getattr(config, "data_dir", "") if config is not None else ""
    if not data_dir:
        return "host"
    from synox.packs import lock as pack_lock
    found = pack_lock.entry(data_dir, m.name) or {}
    mode = (found.get("runtime") or {}).get("mode") if isinstance(found.get("runtime"), dict) else None
    return "container" if mode == "container" else "host"


def container_target(config, m) -> Optional[dict]:
    """這個 pack 要在容器裡跑嗎：有 runtime.container 而且擁有者選了容器 → {spec, image, pack, pack_dir, scope}；否則 None。"""
    spec = container_spec(m)
    if spec is None or runtime_mode(config, m) != "container":
        return None
    from synox.packs import container as pack_container
    return {"spec": spec, "image": pack_container.image_ref(m, spec), "pack": m.name, "pack_dir": m.folder,
            "scope": data_scope(m)}


def container_box(engine: str, target: dict, *, which: Callable[[str], Optional[str]] = shutil.which,
                  platform: str = sys.platform) -> "ContainerSandbox":
    return ContainerSandbox(engine, target["spec"], image=target.get("image", ""), pack=target.get("pack", ""),
                            pack_dir=target.get("pack_dir", ""), scope=target.get("scope", "none"), which=which,
                            platform=platform)


def default_container_factory(config, target: dict, engine: str) -> Sandbox:
    return container_box(engine, target, which=_engine_which)


_engine_which: Callable[[str], Optional[str]] = shutil.which
_container_factory: Callable[[object, dict, str], Sandbox] = default_container_factory


def set_engine_which(which: Optional[Callable[[str], Optional[str]]]) -> None:
    """換掉「找容器引擎」的 which（測試給假的；None＝shutil.which）。只看 PATH，不執行引擎。"""
    global _engine_which
    _engine_which = which or shutil.which


def set_container_factory(factory: Optional[Callable[[object, dict, str], Sandbox]]) -> None:
    """換掉容器後端的建法（測試給記錄 argv 的假後端；None＝ContainerSandbox）。factory(config, target, engine)。"""
    global _container_factory
    _container_factory = factory or default_container_factory


def box_for(config, m, host: Optional[Sandbox] = None) -> Sandbox:
    """這個 pack 這一次用哪個後端：選了容器、這台找得到引擎 → 容器；否則 host（sandbox_for(config)，或呼叫的人給的）。
    loader 的 make_cli、mcp 的 StdioBackend、restricted_reason 都用這個。"""
    target = container_target(config, m)
    if target is not None:
        engine = pick_engine(settings_of(config), _engine_which)
        if engine:
            return _container_factory(config, target, engine)
    return host if host is not None else sandbox_for(config)


def container_problem(config, m) -> str:
    """選了容器卻用不了的原因（""＝沒問題或沒選容器）。"""
    if container_target(config, m) is None:
        return ""
    settings = settings_of(config)
    if pick_engine(settings, _engine_which):
        return ""
    return f"選了容器，但這台找不到 {engines_text(settings)}（policy.sandbox.engine={settings.get('engine')}）"


def view_for(box: Sandbox, ph: Dict[str, str]) -> Dict[str, str]:
    """代換用的值：容器後端＝容器裡的路徑（{pack_dir}→/pack…）；其他後端原樣。"""
    view = getattr(box, "view", None)
    return view(ph) if callable(view) else ph


def runtime_note(config, m) -> str:
    """doctor／packs status 的一行（沒有 runtime.container 回 ""）。"""
    if container_spec(m) is None:
        return ""
    if runtime_mode(config, m) != "container":
        return (f"🧱 這個 pack 有提供容器，目前選「不用容器」（python -m synox packs runtime {m.name} container 改用容器）")
    problem = container_problem(config, m)
    if problem:
        return f"🧱 ⚠️ {problem}：退回這台的沙盒後端"
    engine = pick_engine(settings_of(config), _engine_which)
    from synox.packs import container as pack_container
    return f"🧱 容器（{engine}）：{pack_container.image_ref(m)[:90]}"


def engines_line(config) -> str:
    """doctor：這台找得到哪些容器引擎（只用 which 看 PATH，**不執行引擎**；rootless 與否、daemon 開了沒都不知道）。"""
    settings = settings_of(config)
    found = []
    for engine in ENGINES:
        path = _engine_which(engine)
        found.append(f"{engine} ✅（{path}）" if path else f"{engine} —（PATH 上沒有）")
    chosen = pick_engine(settings, _engine_which)
    tail = f"會用 {chosen}" if chosen else "選了容器的 pack 會退回沙盒後端"
    note = "；docker 的 daemon 是 root：能叫 docker 的帳號等於 root" if chosen == "docker" else ""
    return (f"• 容器引擎（engine={settings.get('engine')}）：{'、'.join(found)}；{tail}"
            f"（只看 PATH，沒有執行引擎{note}）")


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
    mcp = getattr(m, "mcp", {}) or {}
    if getattr(m, "kind", "") == "mcp" and isinstance(mcp, dict):     # kind=mcp stdio（P4a）
        out += [str(x) for x in mcp.get("argv") or []]
        out.append(str(mcp.get("cwd") or ""))
        out += [str(v) for v in (mcp.get("env") or {}).values()] if isinstance(mcp.get("env"), dict) else []
    return out


def runs_subprocess(m) -> bool:
    """SYNOX 會替這個 pack 開子程序：kind=cli，或 kind=mcp 的 transport=stdio（沙盒、required_for 都看這個）。"""
    kind = getattr(m, "kind", "")
    return kind == "cli" or (kind == "mcp" and ((getattr(m, "mcp", {}) or {}).get("transport") == "stdio"))


def data_scope(m) -> str:
    """這個 pack 的資料屬於誰：none｜user｜shared。**推斷都在這裡**（PERM-2 合進來後 pack.json 的 data 欄位優先）：
    pack.json 有 data → 用它；kind=cli 看樣板：有 {user_data_dir} → user，有 {data_dir} → shared，都沒有 → none；
    kind=python：有 storage → user（spec 的預設）。"""
    declared = (getattr(m, "raw", {}) or {}).get("data")
    if declared in DATA_SCOPES:
        return declared
    if getattr(m, "kind", "") in ("cli", "mcp"):
        text = "\n".join(_templates(m))
        if "{user_data_dir}" in text:
            return "user"
        if "{data_dir}" in text:
            return "shared"
        return "none"
    return "user" if (getattr(m, "raw", {}) or {}).get("storage") else "none"


def trust_of(data_dir: str, m) -> str:
    """core｜third-party。packs.lock 的 trust（安裝時擁有者選的；之後的階段寫）優先；
    沒寫：經安裝流程從檔案裝進來的（lock 的 via＝web／console）＝third-party；出廠的＝core。
    沒有鎖的（手動放進 packs/ 或 packs.dirs）：跟 kind=python 同一條規則（PERM-8）——不是出廠的就是 third-party。"""
    from synox.packs import lock as pack_lock
    from synox.packs.loader import is_bundled
    found = pack_lock.entry(data_dir, m.name) if data_dir else None
    if not found:
        return CORE if is_bundled(m) else THIRD_PARTY
    if found.get("trust") in TRUSTS:
        return found["trust"]
    return THIRD_PARTY if found.get("via") in ("web", "console") else CORE


def required(config, m) -> bool:
    """policy.sandbox.required_for 命中這個 pack 嗎（只看 SYNOX 會開子程序的：kind=cli、kind=mcp stdio；
    python pack 在程序裡跑，沙盒管不到，見 PERM-8）。"""
    if not runs_subprocess(m):
        return False
    if is_t2(m):                     # SDK P7：T2（掃不到內容的執行檔／外部相依）一定命中，不管 trust、required_for
        return True
    rule = settings_of(config).get("required_for", "third-party")
    if rule == "all":
        return True
    if rule == "none":
        return False
    return trust_of(getattr(config, "data_dir", ""), m) == THIRD_PARTY


def is_t2(m) -> bool:
    """T2（packs/tier.py）：pack 資料夾裡有掃不到內容的檔、argv 指到 pack 外的程式、或 runtime auto 會裝套件。"""
    if getattr(m, "registered_only", False) or not getattr(m, "folder", ""):
        return False
    from synox.packs import tier as pack_tier
    return pack_tier.is_t2(m)


def restricted_reason(config, m, box: Optional[Sandbox] = None) -> str:
    """伺服器版、required_for 命中（T2 一定命中）、又沒有真隔離 → 一句話說為什麼只給擁有者（""＝不受影響）。
    T2 的 python pack 在 SYNOX 程序裡跑、沙盒包不到 → 伺服器版一律只給擁有者（不管 trust）。"""
    if mode_of(config) != "server":
        return ""
    if getattr(m, "kind", "") == "python" and is_t2(m):
        return ("只對擁有者開放：這是 T2 python pack（附了掃不到內容的執行檔／編譯檔），在 SYNOX 程序裡跑、"
                "沙盒包不到；伺服器版不給成員用（不管 trust 怎麼選）")
    if not required(config, m):
        return ""
    box = box_for(config, m, host=box)            # 選了容器、引擎找得到 → 容器（算真隔離）
    if box.isolates:
        return ""
    problems = [p for p in (container_problem(config, m), box.problem) if p]
    why = f"（{'；'.join(problems)}）" if problems else ""
    hint = ""
    if container_spec(m) is not None and runtime_mode(config, m) != "container":
        hint = f"；這個 pack 有提供容器：python -m synox packs runtime {m.name} container 改用容器就能給成員"
    if is_t2(m):
        return (f"只對擁有者開放：這是 T2 pack（會執行掃不到內容的東西），一定要沙盒（不管 trust、required_for），"
                f"但目前的後端是 {box.name}{why}，不算真隔離（要 bwrap、systemd 或容器）{hint}")
    return (f"只對擁有者開放：policy.sandbox.required_for={settings_of(config).get('required_for')} 要求沙盒，"
            f"但目前的後端是 {box.name}{why}，不算真隔離（要 bwrap、systemd 或容器）{hint}")


def t2_personal_note(config, m) -> str:
    """個人版的 T2 pack：照用，doctor 提醒一句（伺服器版、不是 T2 回 ""）。"""
    if mode_of(config) == "server" or not is_t2(m):
        return ""
    from synox.packs import tier as pack_tier
    runs = pack_tier.assess(m)["runs"]
    what = "、".join(runs[:5]) if runs else "runtime auto 的套件"
    return (f"T2：會執行掃不到內容的東西（{what}）；個人版沒有沙盒，它用你的 Windows 帳號權限跑——"
            "只裝你信得過的發行者給的")


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
    if getattr(m, "kind", "") == "mcp":
        timeout = None            # MCP 伺服器是長駐的：壽命由 packs/mcp.py 管（閒置回收），每次呼叫的逾時也在那裡
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
        line += ("\n  ⚠️ 伺服器版沒有真隔離：要沙盒的 cli pack 只對擁有者開放（Linux 裝 bubblewrap 後 backend 寫 auto 或 bwrap；"
                 "或 pack 有提供容器、安裝時選「用容器」、這台有 podman／docker）")
    line += "\n" + engines_line(config)
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
