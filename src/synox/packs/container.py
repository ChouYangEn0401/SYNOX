"""
容器（S0，docs/lab/discussions/2026-11-10-sandbox-and-skill-containers.md §D2、2026-11-10-isolation-howto.md）：
pack.json 的 `runtime.container` 第 1 關檢查、Dockerfile 的第 2 關掃描。**只讀字串與 pack 裡的檔，不執行任何東西**
（不叫 podman／docker、不拉映像、不 build）。執行期組 argv 的是 synox/sandbox.py 的 ContainerSandbox（S1）。

    "runtime": {"container": {
        "image": "ghcr.io/example/tool@sha256:<64 hex>",    image／dockerfile 至少一個；image 一定帶 @sha256: digest
        "dockerfile": "./Dockerfile", "base": "docker.io/library/python@sha256:<64 hex>",   有 dockerfile 就要 base
        "entry": "stdio",                                    只有 stdio（容器的 stdin／stdout 就是 cli／MCP 的管線）
        "network": false,                                    沒寫＝false；寫了要跟 capabilities 的 network 一致
        "resources": {"mem_mb": 512, "cpus": 1, "pids": 64}, 只能比 policy.sandbox 小（執行時取小的）
        "mounts": {"pack": "/pack", "user_data": "/data/user", "shared_data": "/data/shared"},   只改容器裡的路徑
        "env_passthrough": ["WEATHER_API_KEY"],              只能是 requires.env／auth.fields[].env 列的名字
        "user": "nonroot",                                   nonroot（預設）或 "uid:gid"（都不是 0）；root 一律拒
        "python": "python3", "node": "node"}}               {python}／{node} 在容器裡換成什麼（預設 python3／node）

第 1 關（check）一律拒：沒有 digest 的映像（tag 會被換掉）、registry 不在白名單、localhost／IP／http://、
`--privileged`／cap_add／devices／volumes／network=host 這類把牆打掉的欄位（白名單以外的欄位都拒）、
mounts 指到本機路徑或逃出（..、相對路徑、/、/proc、/etc…、docker.sock）、user=root。
第 2 關（dockerfile_findings）：只准一個 FROM、FROM 要跟 base 一字不差（帶 digest）、ADD 網址、RUN --network／
--security、COPY --from=沒有 digest 的映像 → 拒；RUN 裡的 curl／wget／pip install… 列進報告（提醒不是門）。
"""

from __future__ import annotations

import os
import posixpath
import re
from typing import Dict, List, Optional, Sequence, Tuple

DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
# <registry 主機>/<路徑>[:tag]@sha256:<64 hex>；主機一定要寫（不靠 docker.io 的預設）
IMAGE_RE = re.compile(r"^(?P<host>[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,})/"
                      r"(?P<path>[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*)*)"
                      r"(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}))?"
                      r"@sha256:(?P<digest>[0-9a-f]{64})$")
REGISTRIES = ("docker.io", "ghcr.io", "quay.io")
KEYS = ("image", "dockerfile", "base", "entry", "network", "resources", "mounts", "env_passthrough", "user",
        "python", "node")
# 會把牆打掉的寫法：認得的給一句清楚的理由（其他不認得的欄位一樣拒）
DANGEROUS_KEYS = {
    "privileged": "--privileged 等於把容器的牆整個拆掉（看得到主機的裝置、能載入核心模組）",
    "cap_add": "--cap-add 把 Linux 特權加回去（SYNOX 一律 --cap-drop ALL）",
    "capabilities": "容器的 Linux 特權由 SYNOX 決定（一律 --cap-drop ALL）",
    "devices": "--device 把主機的裝置交給容器",
    "volumes": "不能自己指定本機資料夾；要掛什麼由 SYNOX 照 data 宣告算（mounts 只能改容器裡的路徑）",
    "binds": "不能自己指定本機資料夾（同 volumes）",
    "security_opt": "seccomp／apparmor／no-new-privileges 由 SYNOX 決定，不能關掉",
    "network_mode": "網路只有 network: true／false（不收 host、container:…）",
    "pid": "--pid=host 看得到主機的所有程序",
    "ipc": "--ipc=host 共用主機的記憶體區段",
    "uts": "--uts=host 共用主機名",
    "userns": "user namespace 由 SYNOX 決定（podman 一律 keep-id）",
    "runtime": "容器執行器（runc／runsc）由營運者決定，不由 pack 決定",
    "args": "不收任意的 podman／docker 參數（--privileged、-v /var/run/docker.sock… 都可能夾在裡面）",
    "extra_args": "不收任意的 podman／docker 參數",
    "options": "不收任意的 podman／docker 參數",
    "ports": "SYNOX 不開埠：容器跟 SYNOX 只用 stdin／stdout 講話",
    "publish": "SYNOX 不開埠：容器跟 SYNOX 只用 stdin／stdout 講話",
    "env": "容器的環境變數照 cli.env／mcp.env 與 SYNOX 的規則（env_passthrough 只能放行已宣告的密鑰名）",
    "entrypoint": "要跑什麼照 cli.argv／mcp.argv（不另外改映像的 entrypoint）",
    "privileged_mode": "--privileged 等於把容器的牆整個拆掉",
}
MOUNT_KEYS = ("pack", "user_data", "shared_data")
DEFAULT_MOUNTS = {"pack": "/pack", "user_data": "/data/user", "shared_data": "/data/shared"}
# 容器裡不能拿來掛 pack／資料的路徑（系統資料夾、/tmp 是 tmpfs）
FORBIDDEN_MOUNT_ROOTS = ("/proc", "/sys", "/dev", "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64",
                         "/libx32", "/boot", "/run", "/var/run", "/var/lib", "/root", "/tmp", "/var/tmp")
RESOURCE_LIMITS = {"mem_mb": (16, 65536, int), "cpus": (0.1, 64.0, float), "pids": (1, 4096, int)}
USER_RE = re.compile(r"^([1-9]\d{0,9}):([1-9]\d{0,9})$")
CMD_NAME_RE = re.compile(r"^(python|pypy)(\d+(\.\d+)*)?$|^node(js)?$")
DOCKERFILE_NAME_RE = re.compile(r"(^|/)((Dockerfile|Containerfile)(\.[A-Za-z0-9_-]+)?|[A-Za-z0-9_-]+\.(Dockerfile|Containerfile))$")
DEFAULT_PYTHON = "python3"
DEFAULT_NODE = "node"
MAX_DOCKERFILE = 256 * 1024
# RUN 裡會在 build 時連網下載的指令：列進報告（提醒不是門）
NETWORK_TOOLS = re.compile(r"\b(curl|wget|pip3?\s+install|python3?\s+-m\s+pip\s+install|npm\s+(install|ci)|yarn|pnpm|"
                           r"apt(-get)?\s+install|apk\s+add|dnf\s+install|yum\s+install|git\s+clone|go\s+get|cargo\s+install|"
                           r"gem\s+install)\b")


def image_problem(value, label: str) -> str:
    """映像參照的檢查：""＝可以；否則一句理由。只看字串。"""
    if not isinstance(value, str) or not value.strip():
        return f"{label} 要是映像參照字串（例如 ghcr.io/作者/工具@sha256:<64 個 16 進位字>）"
    text = value.strip()
    if "://" in text:
        return f"{label} 不能寫成網址（{text[:80]!r}）：寫 registry 主機/路徑@sha256:…"
    if not DIGEST_RE.search(text):
        return (f"{label} 一定要帶 @sha256:<64 個 16 進位字> 的 digest（{text[:80]!r}）："
                "只寫 tag（:latest、:1.0）的映像可以被換成別的內容，SYNOX 不收")
    m = IMAGE_RE.match(text)
    if m is None and "/" not in text.split("@", 1)[0]:
        return (f"{label} 要寫 registry 主機（{text[:80]!r}）：主機一定要寫，"
                "例如 docker.io/library/python@sha256:…（不靠 docker.io 的預設）")
    if m is None:
        host = text.split("/", 1)[0]
        if host in ("localhost",) or host.startswith("localhost:") or re.match(r"^\d+\.\d+\.\d+\.\d+(:\d+)?$", host) \
                or host.startswith("["):
            return f"{label} 不能用 localhost 或 IP 位址當 registry（{host!r}）"
        if ":" in host:
            return f"{label} 的 registry 不能指定埠（{host!r}）"
        return (f"{label} 看不懂（{text[:80]!r}）：要寫成 <registry 主機>/<路徑>[:tag]@sha256:<64 個 16 進位字>，"
                "主機一定要寫（例如 docker.io/library/python@sha256:…）")
    if m.group("host") not in REGISTRIES:
        return (f"{label} 的 registry {m.group('host')!r} 不在白名單（{'、'.join(REGISTRIES)}）："
                "要用別的 registry 請先跟擁有者討論")
    return ""


def _mount_problem(key: str, value) -> str:
    where = f"runtime.container.mounts.{key}"
    if not isinstance(value, str) or not value:
        return f"{where} 要是容器裡的絕對路徑（例如 /pack）"
    if "\\" in value or re.match(r"^[A-Za-z]:", value) or value.startswith("//"):
        return f"{where} 只能寫容器裡的路徑（/開頭的 Linux 路徑），不能指定本機路徑：{value[:80]!r}"
    if not value.startswith("/"):
        return f"{where} 要是 / 開頭的絕對路徑（{value[:80]!r}）"
    if any(c in value for c in ",:=\"'\n\r\t ") or any(ord(c) < 32 for c in value):
        return f"{where} 只能用英數字、/、-、_、.（{value[:80]!r}）"
    if value.rstrip("/") == "":
        return f"{where} 不能是 /（整個根目錄）"
    parts = value.split("/")[1:]
    if ".." in parts or "." in parts or "" in parts:
        return f"{where} 不能有 ..、. 或連續的 /（{value[:80]!r}）"
    norm = posixpath.normpath(value)
    if "sock" in norm.lower():
        return f"{where} 不能碰 socket（{value!r}；掛 docker.sock／podman.sock 等於把整台主機交出去）"
    for root in FORBIDDEN_MOUNT_ROOTS:
        if norm == root or norm.startswith(root + "/"):
            return f"{where} 不能放在 {root} 底下（系統資料夾或 SYNOX 給的暫存區）：{value!r}"
    return ""


def check(raw, *, kind: str, mcp_stdio: bool, capabilities: Sequence[str], folder: str,
          secret_names: Sequence[str]) -> Tuple[Optional[dict], List[str]]:
    """runtime.container（第 1 關）→ (整理過的設定｜None, 問題清單)。raw=None＝沒寫（回 (None, [])）。
    folder：pack 資料夾（dockerfile 要在裡面、要存在）。只看字串與檔案在不在，不執行任何東西。"""
    if raw is None:
        return None, []
    problems: List[str] = []
    if not isinstance(raw, dict):
        return None, ["runtime.container 要是物件"]
    if not (kind == "cli" or mcp_stdio):
        problems.append("runtime.container 只給 kind=cli 與 kind=mcp（transport=stdio）用：python pack 在 SYNOX 程序裡跑、"
                        "connector 與遠端 MCP 沒有程式在這台跑，容器包不到")
    for key in raw:
        if key in KEYS:
            continue
        why = DANGEROUS_KEYS.get(str(key).lower().replace("-", "_"))
        problems.append(f"runtime.container 不收 {key}：{why}" if why else
                        f"runtime.container 不認得 {key!r}（只收 {'、'.join(KEYS)}）")
    out: dict = {}
    image, dockerfile = raw.get("image"), raw.get("dockerfile")
    if image is None and dockerfile is None:
        problems.append("runtime.container 要寫 image（帶 digest 的映像）或 dockerfile（pack 裡的 Dockerfile）")
    if image is not None:
        why = image_problem(image, "runtime.container.image")
        if why:
            problems.append(why)
        else:
            out["image"] = image.strip()
    if dockerfile is not None:
        rel = str(dockerfile).replace("\\", "/") if isinstance(dockerfile, str) else ""
        rel = rel[2:] if rel.startswith("./") else rel
        if not rel or os.path.isabs(rel) or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) \
                or ".." in rel.split("/"):
            problems.append(f"runtime.container.dockerfile 要是 pack 資料夾裡的相對路徑（不能有 .. 或絕對路徑）：{dockerfile!r}")
        elif not DOCKERFILE_NAME_RE.search(rel):
            problems.append(f"runtime.container.dockerfile 檔名要是 Dockerfile／Containerfile（或 x.Dockerfile）：{rel!r}")
        elif not _inside(folder, rel) or not os.path.isfile(os.path.join(folder, *rel.split("/"))):
            problems.append(f"找不到 runtime.container.dockerfile 檔 {rel}")
        else:
            out["dockerfile"] = rel
        base = raw.get("base")
        if base is None:
            problems.append("有 runtime.container.dockerfile 就要寫 base（Dockerfile 的 FROM，帶 @sha256: digest）")
        else:
            why = image_problem(base, "runtime.container.base")
            if why:
                problems.append(why)
            else:
                out["base"] = base.strip()
    elif raw.get("base") is not None:
        problems.append("runtime.container.base 只給有 dockerfile 的時候用")
    entry = raw.get("entry", "stdio")
    if entry != "stdio":
        problems.append("runtime.container.entry 只能是 stdio（容器的 stdin／stdout 就是管線；SYNOX 不開埠）")
    network = raw.get("network", False)
    declared = "network" in (capabilities or ())
    if not isinstance(network, bool):
        problems.append("runtime.container.network 只能是 true 或 false（不收 host、bridge 這類網路名；"
                        "--network host 等於跟主機共用網路，連得到本機的每個服務）")
        network = False
    elif network != declared:
        problems.append("runtime.container.network 要跟 capabilities 的 network 一致（一邊有一邊沒有＝拒）："
                        + ("capabilities 有 network，這裡要寫 true" if declared else
                           "這裡寫了 true，capabilities 也要宣告 network"))
    out["network"] = bool(network)
    resources = raw.get("resources", {})
    out["resources"] = {}
    if not isinstance(resources, dict):
        problems.append("runtime.container.resources 要是物件（mem_mb、cpus、pids）")
    else:
        for key, value in resources.items():
            if key not in RESOURCE_LIMITS:
                problems.append(f"runtime.container.resources 不認得 {key!r}（只收 mem_mb、cpus、pids）")
                continue
            low, high, kind_ = RESOURCE_LIMITS[key]
            ok = not isinstance(value, bool) and isinstance(value, (int, float)) and \
                (kind_ is float or float(value).is_integer()) and low <= value <= high
            if not ok:
                problems.append(f"runtime.container.resources.{key} 要是 {low}～{high} 的{'整數' if kind_ is int else '數字'}")
            else:
                out["resources"][key] = kind_(value)
    mounts = raw.get("mounts", {})
    out["mounts"] = dict(DEFAULT_MOUNTS)
    if not isinstance(mounts, dict):
        problems.append("runtime.container.mounts 要是物件（pack、user_data、shared_data → 容器裡的路徑）")
    else:
        for key, value in mounts.items():
            if key not in MOUNT_KEYS:
                problems.append(f"runtime.container.mounts 不收 {key!r}：只能改 pack、user_data、shared_data 在容器裡的路徑；"
                                "本機要掛什麼由 SYNOX 照 data 宣告算（不能掛別的本機資料夾、docker.sock）")
                continue
            why = _mount_problem(key, value)
            if why:
                problems.append(why)
            else:
                out["mounts"][key] = posixpath.normpath(value)
        paths = list(out["mounts"].values())
        for i, a in enumerate(paths):
            for b in paths[i + 1:]:
                if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                    problems.append(f"runtime.container.mounts 的路徑不能重疊（{a}、{b}）")
    passthrough = raw.get("env_passthrough")
    if passthrough is not None:
        if not isinstance(passthrough, list) or not all(isinstance(n, str) for n in passthrough):
            problems.append("runtime.container.env_passthrough 要是環境變數名字的清單")
        else:
            bad = [n for n in passthrough if n not in secret_names]
            if bad:
                problems.append("runtime.container.env_passthrough 只能放行 requires.env／auth.fields[].env 列過的名字"
                                f"（{'、'.join(bad[:5])} 沒列）")
            out["env_passthrough"] = [n for n in passthrough if n in secret_names]
    user = raw.get("user", "nonroot")
    if user == "nonroot":
        out["user"] = "nonroot"
    elif isinstance(user, str) and USER_RE.match(user):
        out["user"] = user
    else:
        problems.append("runtime.container.user 只能是 nonroot（預設）或 \"uid:gid\"（都不能是 0）：容器裡一律不用 root"
                        f"（現在是 {user!r}）")
    for key, default in (("python", DEFAULT_PYTHON), ("node", DEFAULT_NODE)):
        value = raw.get(key, default)
        name = value.rsplit("/", 1)[-1] if isinstance(value, str) else ""
        if not isinstance(value, str) or not CMD_NAME_RE.match(name) or \
                ("/" in value and (not value.startswith("/") or ".." in value.split("/"))):
            problems.append(f"runtime.container.{key} 要是容器裡的 {key} 指令名（例如 {default}）或 / 開頭的絕對路徑")
        else:
            out[key] = value
    return (out if not problems else None), problems


def _inside(folder: str, rel: str) -> bool:
    base = os.path.realpath(folder)
    target = os.path.realpath(os.path.join(folder, *rel.split("/")))
    try:
        return os.path.commonpath([base, target]) == base and target != base
    except ValueError:
        return False


def spec_of(m) -> Optional[dict]:
    """manifest 的 runtime.container（第 1 關整理過的）；沒寫回 None。"""
    spec = (getattr(m, "runtime", None) or {}).get("container")
    return spec if isinstance(spec, dict) else None


def image_ref(m, spec: Optional[dict] = None) -> str:
    """執行時用的映像：有 image 用 image；只有 dockerfile＝本機建的 localhost/synox-<pack>:<Dockerfile sha256 前 12 字>
    （S3 才會由 SYNOX 建；現在要營運者自己 build 成這個名字）。"""
    spec = spec if spec is not None else spec_of(m)
    if not spec:
        return ""
    if spec.get("image"):
        return spec["image"]
    digest = dockerfile_sha256(m, spec)
    return f"localhost/synox-{m.name}:{digest[:12] or 'unbuilt'}"


def dockerfile_sha256(m, spec: Optional[dict] = None) -> str:
    spec = spec if spec is not None else spec_of(m)
    rel = (spec or {}).get("dockerfile")
    if not rel:
        return ""
    import hashlib
    try:
        with open(os.path.join(m.folder, *rel.split("/")), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def summary(m) -> dict:
    """安裝報告／tier.assess 用的摘要（不是 runtime.container 就回 {}）。"""
    spec = spec_of(m)
    if not spec:
        return {}
    res = spec.get("resources") or {}
    return {"image": spec.get("image", ""), "dockerfile": spec.get("dockerfile", ""), "base": spec.get("base", ""),
            "network": bool(spec.get("network")), "resources": dict(res), "user": spec.get("user", "nonroot"),
            "mounts": dict(spec.get("mounts") or DEFAULT_MOUNTS), "run_image": image_ref(m, spec),
            "dockerfile_sha256": dockerfile_sha256(m, spec)}


# ── 第 2 關：Dockerfile ─────────────────────────────────────────────────

def _logical_lines(text: str) -> List[Tuple[int, str]]:
    """Dockerfile → [(開始的行號, 接好的一行)]：去掉註解與空行，行尾 \\ 接下一行。heredoc 不特別處理（推測少見）。"""
    out: List[Tuple[int, str]] = []
    buf, start = "", 0
    for no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("#")):
            continue
        if buf and stripped.startswith("#"):
            continue
        if not buf:
            start = no
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        buf += stripped
        out.append((start, buf))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


def _flags(rest: str) -> Tuple[List[str], str]:
    """「--x=y --z 其他」→ (["--x=y", "--z"], "其他")。"""
    flags = []
    tokens = rest.split()
    while tokens and tokens[0].startswith("--"):
        flags.append(tokens.pop(0))
    return flags, " ".join(tokens)


def dockerfile_issues(folder: str, rel: str, base: str) -> List[Tuple[int, str, str, bool]]:
    """Dockerfile 的第 2 關：[(行號, 片段, 說明, 擋不擋)]。只讀檔、不 build。"""
    path = os.path.join(folder, *rel.split("/"))
    try:
        if os.path.getsize(path) > MAX_DOCKERFILE:
            return [(0, rel, f"Dockerfile 太大（超過 {MAX_DOCKERFILE // 1024} KB）", True)]
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return [(0, rel, f"Dockerfile 讀不了：{type(e).__name__}", True)]
    out: List[Tuple[int, str, str, bool]] = []
    froms = []
    stages = set()
    for no, line in _logical_lines(text):
        word, _, rest = line.partition(" ")
        inst = word.upper()
        snippet = line if len(line) <= 120 else line[:117] + "…"
        flags, args = _flags(rest.strip())
        if inst == "FROM":
            froms.append(no)
            parts = args.split()
            ref = parts[0] if parts else ""
            if len(parts) >= 3 and parts[1].upper() == "AS":
                stages.add(parts[2].lower())
            bad_flags = [f for f in flags if not f.startswith("--platform=")]
            if bad_flags:
                out.append((no, snippet, f"FROM 不收 {' '.join(bad_flags)}", True))
            if ref != base:
                out.append((no, snippet, f"FROM 要跟 pack.json 的 runtime.container.base 一字不差（{base[:60]}…）；"
                                         "不准用沒有 digest 的映像", True))
        elif inst == "ADD":
            if re.search(r"(^|\s)(https?://|git@|ftp://)", args) or any(f.startswith("--checksum") for f in flags):
                out.append((no, snippet, "ADD 不能從網址下載（build 時連到 pack 以外的地方拿程式，內容 SYNOX 看不到）", True))
            if any(f.startswith("--from=") for f in flags):
                out.append((no, snippet, "ADD --from 不收（從別的映像拿檔）", True))
        elif inst == "COPY":
            for f in flags:
                if f.startswith("--from="):
                    src = f.split("=", 1)[1]
                    if src.lower() not in stages and not DIGEST_RE.search(src):
                        out.append((no, snippet, f"COPY --from={src}：從沒有 digest 的映像拿檔（內容會被換掉）", True))
        elif inst == "RUN":
            for f in flags:
                if f.startswith("--network") or f.startswith("--security"):
                    out.append((no, snippet, f"RUN {f} 不收（build 時改網路／安全設定）", True))
            if NETWORK_TOOLS.search(args):
                out.append((no, snippet, "RUN 在 build 時下載東西（curl／wget／pip install…）：內容 SYNOX 看不到，"
                                         "跟 pip／npm 套件一樣（提醒不是門）", False))
        elif inst == "ONBUILD":
            out.append((no, snippet, "ONBUILD 不收（把指令留給別人的 build）", True))
        elif inst == "USER" and args.split(":")[0].strip() in ("root", "0"):
            out.append((no, snippet, "USER root：SYNOX 執行時一律換成非 root（podman keep-id／docker --user），"
                                     "建議 Dockerfile 自己就用非 root 使用者", False))
    if len(froms) != 1:
        out.append((froms[1] if len(froms) > 1 else 0, rel,
                    f"Dockerfile 要剛好一個 FROM（現在 {len(froms)} 個）：多階段 build 會拉沒有在 pack.json 宣告的映像",
                    True))
    return out
