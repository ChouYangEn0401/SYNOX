"""
pack 的依賴與環境自動建置（SDK P5）。kind=cli 的 pack.json 寫：

    "runtime": {"python": "auto", "node": "auto"},
    "requires": {"pip": ["requests==2.32.3"]}

  runtime.python = "auto"   安裝時在 data/envs/<pack>/venv 建一個 venv（python -m venv），再
                            pip install --no-deps --only-binary=:all: -r requirements.txt；
                            requires.pip 只能寫「名字==版本」（釘死版本），其他寫法 pack.json 不合（manifest 檢查）。
  runtime.node   = "auto"   pack 裡要有 package.json＋package-lock.json；複製到 data/envs/<pack>/ 後
                            npm ci --ignore-scripts（套件的安裝腳本一律不跑），裝進 data/envs/<pack>/node_modules。
                            {node}＝系統的 node；子程序拿到 NODE_PATH 指到那個 node_modules。
                 = 路徑      相對於 pack 資料夾（或絕對路徑），跟 runtime.python 的規則一樣。

    b = builder(data_dir)            可替換（set_factory）；預設 VenvBuilder（venv＋pip／npm）
    b.plan(m)                        → EnvPlan：要做什麼（給人看的清單；不跑任何東西）
    b.build(m, jobs, on_done)        經 JobRunner 一步一步跑（總共最多 10 分鐘，log 進 job_logs），
                                     結束呼叫 on_done(BuildResult)；結果寫 data/envs/<pack>/env.json
    python_of(m, data_dir)／node_of(m, data_dir)    loader 代換 {python}／{node} 用；不是 auto 回 ""
    env_problem(m, data_dir)         環境沒建好／跟 pack.json 對不上 → 一句人話；好了（或不用建）→ None

pack 資料夾本身一律不寫（packs.lock 的雜湊才對得上）；建出來的東西全在 data/envs/<pack>/。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

AUTO = "auto"
ENVS_DIR = "envs"
STATE_FILE = "env.json"
TIMEOUT = 600.0                                   # 整個建置最多 10 分鐘
OK, FAILED, BUILDING = "ok", "failed", "building"
NODE_FILES = ("package.json", "package-lock.json")
# requires.pip 在 runtime.python=auto 時只接受「名字==版本」：沒有 extras、環境標記、網址、旗標
PIN_RE = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?)==([0-9][0-9A-Za-z.+!_-]{0,63})$")
OFFLINE_HINTS = ("NewConnectionError", "Failed to establish a new connection", "getaddrinfo failed",
                 "Temporary failure in name resolution", "Name or service not known", "No route to host",
                 "ConnectTimeoutError", "Read timed out", "ProxyError", "Network is unreachable",
                 "ENOTFOUND", "EAI_AGAIN", "ECONNREFUSED", "ECONNRESET", "ETIMEDOUT", "ENETUNREACH")


# ── pack.json 的欄位 ───────────────────────────────────────────────────

def pin_problems(pip) -> List[str]:
    """requires.pip 每一項都要是「名字==版本」；回不合的說明（空清單＝都合）。"""
    if pip is None:
        return []
    if not isinstance(pip, list):
        return ["requires.pip 要是清單"]
    bad = [str(p) for p in pip if not isinstance(p, str) or not PIN_RE.match(p.strip())]
    if bad:
        return ["runtime.python 是 auto 時，requires.pip 只能寫釘死的版本（名字==版本，例如 requests==2.32.3）："
                + "、".join(bad[:10])]
    return []


def pins(m) -> List[Tuple[str, str]]:
    """requires.pip → [(名字, 版本)]（已經過 manifest 檢查）。"""
    out = []
    for p in (m.requires or {}).get("pip") or []:
        mm = PIN_RE.match(str(p).strip())
        if mm:
            out.append((mm.group(1), mm.group(2)))
    return out


def _runtime_python(m) -> str:
    runtime = getattr(m, "runtime", {}) or {}
    return (runtime.get("python") if os.name == "nt" else (runtime.get("python_posix") or runtime.get("python"))) or ""


def wants_python(m) -> bool:
    return _runtime_python(m) == AUTO and not (getattr(m, "cli", {}) or {}).get("python")


def wants_node(m) -> bool:
    return ((getattr(m, "runtime", {}) or {}).get("node") or "") == AUTO


def needs_env(m) -> bool:
    return wants_python(m) or wants_node(m)


def uses_node(m) -> bool:
    """這個 pack 會用到 node 嗎（runtime.node 有寫，或 argv 樣板裡有 {node}）。"""
    if (getattr(m, "runtime", {}) or {}).get("node"):
        return True
    return any("{node}" in str(a) for a in (getattr(m, "cli", {}) or {}).get("argv") or [])


# ── 路徑 ───────────────────────────────────────────────────────────────

def _default_data_dir() -> str:
    from synox.config import ROOT
    return os.path.join(ROOT, "data")


def env_dir(data_dir: Optional[str], name: str) -> str:
    return os.path.join(data_dir or _default_data_dir(), ENVS_DIR, name)


def venv_python(folder: str) -> str:
    exe = os.path.join("Scripts", "python.exe") if os.name == "nt" else os.path.join("bin", "python")
    return os.path.join(folder, "venv", exe)


def node_modules(data_dir: Optional[str], name: str) -> str:
    return os.path.join(env_dir(data_dir, name), "node_modules")


def python_of(m, data_dir: Optional[str] = None) -> str:
    """runtime.python=auto → data/envs/<pack>/venv 的 python；不是 auto 回 ""（loader 照舊的規則）。"""
    return venv_python(env_dir(data_dir, m.name)) if wants_python(m) else ""


def system_node(which: Callable[[str], Optional[str]] = shutil.which) -> str:
    return which("node") or ""


def node_of(m, data_dir: Optional[str] = None, which: Callable[[str], Optional[str]] = shutil.which) -> str:
    """{node} 換成什麼：runtime.node 是路徑 → 相對於 pack 資料夾（或絕對）；auto 或沒寫 → 系統的 node
    （找不到就回 "node"，跑的時候才會失敗；doctor 會先說缺）。"""
    value = (getattr(m, "runtime", {}) or {}).get("node") or ""
    if value and value != AUTO:
        return value if os.path.isabs(value) else os.path.normpath(os.path.join(m.folder, value))
    return system_node(which) or "node"


def node_env(m, data_dir: Optional[str] = None) -> Dict[str, str]:
    """runtime.node=auto 的子程序環境：NODE_PATH 指到 data/envs/<pack>/node_modules。"""
    return {"NODE_PATH": node_modules(data_dir, m.name)} if wants_node(m) else {}


# ── 狀態（data/envs/<pack>/env.json） ──────────────────────────────────

def spec_of(m) -> str:
    """這次要建的東西的指紋（requires.pip＋package-lock.json）：pack.json 改了就知道要重建。"""
    h = hashlib.sha256()
    if wants_python(m):
        h.update(("py:" + "\n".join(f"{n}=={v}" for n, v in pins(m))).encode("utf-8"))
    if wants_node(m):
        try:
            with open(os.path.join(m.folder, "package-lock.json"), "rb") as f:
                h.update(b"node:" + f.read())
        except OSError:
            h.update(b"node:missing")
    return h.hexdigest()


def read_state(data_dir: Optional[str], name: str) -> dict:
    try:
        with open(os.path.join(env_dir(data_dir, name), STATE_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(data_dir: Optional[str], name: str, **state) -> dict:
    folder = env_dir(data_dir, name)
    os.makedirs(folder, exist_ok=True)
    state = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), **state}
    tmp = os.path.join(folder, STATE_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(folder, STATE_FILE))
    return state


def rebuild_hint(name: str) -> str:
    return f"python -m synox packs env rebuild {name}"


def env_problem(m, data_dir: Optional[str] = None, which: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    """環境沒建好 → 一句人話（doctor、loader 用）；不用建或建好了 → None。"""
    node_path = (getattr(m, "runtime", {}) or {}).get("node") or ""
    if uses_node(m) and node_path in ("", AUTO) and not system_node(which):
        return "這台電腦沒有 Node.js（找不到 node）：先裝 Node.js LTS 再用這個 pack"
    if not needs_env(m):
        return None
    state = read_state(data_dir, m.name)
    hint = rebuild_hint(m.name)
    if not state:
        return f"環境沒建好（還沒建過）：跑 {hint}"
    if state.get("state") == BUILDING:
        return "環境正在建（最多 10 分鐘）"
    if state.get("state") != OK:
        return f"環境沒建好：{state.get('detail') or '上次建失敗'}（修好後跑 {hint}）"
    if state.get("spec") != spec_of(m):
        return f"環境跟 pack.json 對不上（套件清單改過）：跑 {hint} 重建"
    if wants_python(m) and not os.path.isfile(python_of(m, data_dir)):
        return f"環境沒建好（venv 不見了）：跑 {hint}"
    return None


# ── Builder ────────────────────────────────────────────────────────────

@dataclass
class Step:
    label: str                      # 給人看的（「建 Python venv」）
    argv: List[str]
    cwd: str
    prepare: Optional[Callable[[], None]] = field(default=None, repr=False)   # 跑之前做的事（寫 requirements.txt…）


@dataclass
class EnvPlan:
    name: str
    python: bool = False
    packages: List[Tuple[str, str]] = field(default_factory=list)
    node: bool = False
    node_packages: int = 0
    steps: List[Step] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)       # 現在就知道建不起來的原因（沒有 node／npm…）

    @property
    def needed(self) -> bool:
        return self.python or self.node

    def lines(self) -> List[str]:
        """「要建環境：Python venv、裝 N 個套件（名稱與版本）」——安裝前的報告。"""
        out = []
        if self.python:
            names = "、".join(f"{n} {v}" for n, v in self.packages) or "（沒有套件）"
            out.append(f"Python venv、裝 {len(self.packages)} 個套件：{names}")
        if self.node:
            out.append(f"Node 套件（照 package-lock.json，{self.node_packages} 個；不跑套件的安裝腳本）")
        return out

    def text(self) -> str:
        if not self.needed:
            return ""
        body = "；".join(self.lines())
        tail = "".join(f"\n  ⚠️ {p}" for p in self.problems)
        return f"要建環境：{body}（要網路，最多 10 分鐘；在 data/envs/{self.name}/）{tail}"

    def to_dict(self) -> dict:
        return {"needed": self.needed, "python": self.python,
                "packages": [{"name": n, "version": v} for n, v in self.packages],
                "node": self.node, "node_packages": self.node_packages, "lines": self.lines(),
                "problems": list(self.problems), "text": self.text()}


@dataclass
class BuildResult:
    name: str
    ok: bool
    detail: str = ""                # 給人看的（成功＝「環境建好了」；失敗＝原因＋怎麼辦）
    offline: bool = False
    log: str = ""                   # 失敗那一步的 log 檔
    steps: List[str] = field(default_factory=list)


class Builder:
    """介面：plan(m) → EnvPlan；build(m, jobs, on_done)。換實作用 set_factory（例如將來的 python-env-auto-builder）。"""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or _default_data_dir()

    def plan(self, m) -> EnvPlan:                    # pragma: no cover - 介面
        raise NotImplementedError

    def build(self, m, jobs, on_done: Callable[[BuildResult], None]) -> None:   # pragma: no cover - 介面
        raise NotImplementedError

    def build_wait(self, m, jobs, timeout: float = TIMEOUT + 30) -> BuildResult:
        """同步版（終端機用）：build 然後等它結束。"""
        box: List[BuildResult] = []
        done = threading.Event()

        def finish(result):
            box.append(result)
            done.set()

        self.build(m, jobs, finish)
        if not done.wait(timeout):
            return BuildResult(m.name, False, "建環境超過時間還沒結束")
        return box[0]


def node_pins(folder: str) -> List[Tuple[str, str]]:
    """package-lock.json 列的套件 [(名字, 版本)]（lockfile v2/v3 的 packages，或 v1 的 dependencies；只讀 JSON）。"""
    try:
        with open(os.path.join(folder, "package-lock.json"), "r", encoding="utf-8-sig") as f:
            lock = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(lock, dict):
        return []
    out: List[Tuple[str, str]] = []
    pkgs = lock.get("packages")
    if isinstance(pkgs, dict):
        for key, info in pkgs.items():
            if not key:
                continue                            # "" 是專案自己
            name = key.split("node_modules/")[-1]
            version = info.get("version", "") if isinstance(info, dict) else ""
            out.append((name, str(version or "?")))
    elif isinstance(lock.get("dependencies"), dict):
        for name, info in lock["dependencies"].items():
            out.append((str(name), str((info or {}).get("version", "?") if isinstance(info, dict) else "?")))
    return sorted(out)


def all_pins(m) -> List[dict]:
    """runtime auto 會裝的套件：[{"name", "version", "source": "pip"|"npm"}]（T2 的安裝報告列這個）。"""
    out = [{"name": n, "version": v, "source": "pip"} for n, v in pins(m)] if wants_python(m) else []
    if wants_node(m):
        out += [{"name": n, "version": v, "source": "npm"} for n, v in node_pins(m.folder)]
    return out


def _count_lock_packages(folder: str) -> int:
    try:
        with open(os.path.join(folder, "package-lock.json"), "r", encoding="utf-8-sig") as f:
            lock = json.load(f)
    except (OSError, ValueError):
        return 0
    pkgs = lock.get("packages") if isinstance(lock, dict) else None
    if isinstance(pkgs, dict):
        return sum(1 for k in pkgs if k)            # "" 是專案自己
    deps = lock.get("dependencies") if isinstance(lock, dict) else None
    return len(deps) if isinstance(deps, dict) else 0


def explain_failure(name: str, label: str, state: str, log_text: str, returncode=None) -> Tuple[str, bool]:
    """失敗的那一步 → (人話, 是不是沒網路)。"""
    hint = rebuild_hint(name)
    if state == "timed_out":
        return f"{label}超過 10 分鐘被停掉了（網路太慢？）；之後跑 {hint} 再試", False
    if any(h in log_text for h in OFFLINE_HINTS):
        return f"連不上網路（下載套件要網路）：網路好了之後跑 {hint}", True
    miss = re.search(r"No matching distribution found for (\S+)", log_text)
    if miss:
        return (f"找不到套件 {miss.group(1)}（版本寫錯，或這個版本沒有給這台電腦用的現成安裝檔）；"
                f"請 pack 作者修 requires.pip"), False
    if "npm ci" in log_text and ("package-lock.json" in log_text or "EUSAGE" in log_text):
        return "package-lock.json 跟 package.json 對不上（npm ci 拒絕）；請 pack 作者重新產生 package-lock.json", False
    rc = f"（代碼 {returncode}）" if returncode not in (None, 0) else ""
    return f"{label}失敗{rc}；log 在 data/job_logs，修好後跑 {hint}", False


class VenvBuilder(Builder):
    """預設實作：python -m venv＋pip（只裝釘死版本、--no-deps、只用現成的 wheel）；npm ci --ignore-scripts。"""

    def __init__(self, data_dir: Optional[str] = None, *, python: str = "",
                 which: Callable[[str], Optional[str]] = shutil.which, read_log: Optional[Callable[[str], str]] = None):
        super().__init__(data_dir)
        self.python = python or sys.executable
        self.which = which
        if read_log is None:
            from isdtelekit.jobs.runner import read_log as _read
            read_log = _read
        self.read_log = read_log

    def plan(self, m) -> EnvPlan:
        p = EnvPlan(m.name)
        folder = env_dir(self.data_dir, m.name)
        if wants_python(m):
            p.python = True
            p.packages = pins(m)
            req = os.path.join(folder, "requirements.txt")
            py = venv_python(folder)

            def write_req(req=req, items=p.packages):
                os.makedirs(os.path.dirname(req), exist_ok=True)
                with open(req, "w", encoding="utf-8") as f:
                    f.write("".join(f"{n}=={v}\n" for n, v in items))

            p.steps.append(Step("建 Python venv", [self.python, "-m", "venv", "--clear", os.path.join(folder, "venv")],
                                folder))
            if p.packages:
                p.steps.append(Step(f"裝 {len(p.packages)} 個 Python 套件",
                                    [py, "-m", "pip", "install", "--no-deps", "--only-binary=:all:",
                                     "--disable-pip-version-check", "--no-input", "-r", req],
                                    folder, prepare=write_req))
        if wants_node(m):
            p.node = True
            p.node_packages = _count_lock_packages(m.folder)
            npm = self.which("npm") or ""
            if not system_node(self.which):
                p.problems.append("這台電腦沒有 Node.js（找不到 node）：先裝 Node.js LTS，再跑 " + rebuild_hint(m.name))
            elif not npm:
                p.problems.append("找不到 npm（Node.js 裝好了嗎？）")
            missing = [f for f in NODE_FILES if not os.path.isfile(os.path.join(m.folder, f))]
            if missing:
                p.problems.append("pack 裡缺 " + "、".join(missing))

            def copy_lock(src=m.folder, dst=folder):
                os.makedirs(dst, exist_ok=True)
                for f in NODE_FILES:
                    shutil.copyfile(os.path.join(src, f), os.path.join(dst, f))

            p.steps.append(Step("裝 Node 套件", [npm or "npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                                folder, prepare=copy_lock))
        return p

    def build(self, m, jobs, on_done: Callable[[BuildResult], None]) -> None:
        p = self.plan(m)
        name = m.name
        if not p.needed:
            on_done(BuildResult(name, True, "這個 pack 不用建環境"))
            return
        if p.problems:
            detail = "；".join(p.problems)
            write_state(self.data_dir, name, state=FAILED, detail=detail, spec=spec_of(m))
            on_done(BuildResult(name, False, detail))
            return
        write_state(self.data_dir, name, state=BUILDING, detail="", spec=spec_of(m))
        deadline = time.monotonic() + TIMEOUT
        done_labels: List[str] = []

        def fail(detail: str, offline: bool = False, log: str = "") -> None:
            write_state(self.data_dir, name, state=FAILED, detail=detail, spec=spec_of(m), log=log, offline=offline)
            on_done(BuildResult(name, False, detail, offline=offline, log=log, steps=list(done_labels)))

        def run(i: int) -> None:
            if i >= len(p.steps):
                write_state(self.data_dir, name, state=OK, detail="", spec=spec_of(m))
                on_done(BuildResult(name, True, "環境建好了", steps=list(done_labels)))
                return
            step = p.steps[i]
            left = deadline - time.monotonic()
            if left <= 0:
                fail(f"{step.label}還沒開始就超過 10 分鐘了；之後跑 {rebuild_hint(name)} 再試")
                return
            try:
                if step.prepare is not None:
                    step.prepare()
                os.makedirs(step.cwd, exist_ok=True)

                def finished(job, step=step, i=i):
                    try:
                        if job.state == "succeeded":
                            done_labels.append(step.label)
                            run(i + 1)
                            return
                        text = self.read_log(job.log_path) if getattr(job, "log_path", "") else ""
                        detail, offline = explain_failure(name, step.label, job.state, text, job.returncode)
                        fail(detail, offline, getattr(job, "log_path", ""))
                    except Exception as e:                       # on_done 一定要叫到
                        fail(f"{step.label}之後出錯：{e}")

                jobs.start(f"env-{name}", step.argv, cwd=step.cwd, timeout=left, on_done=finished)
            except OSError as e:
                fail(f"{step.label}叫不起來：{e}")

        run(0)


_factory: Callable[[Optional[str]], Builder] = VenvBuilder


def set_factory(factory: Optional[Callable[[Optional[str]], Builder]]) -> None:
    """換掉預設的 Builder（None＝回到 VenvBuilder）。"""
    global _factory
    _factory = factory or VenvBuilder


def builder(data_dir: Optional[str] = None) -> Builder:
    return _factory(data_dir)
