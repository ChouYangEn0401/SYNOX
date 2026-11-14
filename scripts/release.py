"""SYNOX release helper: bump the version, check it is consistent, draft the GitHub release notes.

    python scripts/release.py show
    python scripts/release.py bump patch|minor|alpha|beta|final [--next minor] [--date YYYY-MM-DD] [--dry-run]
    python scripts/release.py check [--tag vX.Y.Z[-alpha.N|-beta.N]]
    python scripts/release.py notes [--version X.Y.Z[-alpha.N|-beta.N]] [--exe]
    python scripts/release.py sign --dist dist --key <私鑰檔> [--security] [--summary "…"] [--min-from X.Y.Z] [--rebuild-venv]
    python scripts/release.py keygen --out <repo 以外的路徑>

The rules are in docs/versioning.md (plain Chinese). In short:
  X.Y.Z               stable (what `main` and the landing page's ZIP give people)
  X.Y.Z-beta.N        external testing (people who volunteered)
  X.Y.Z-alpha.N       internal testing (the SYNOX team)
  tag                 vX.Y.Z / vX.Y.Z-beta.N / vX.Y.Z-alpha.N  (== "v" + the version, scripts/installer_ci.py checks it too)

bump   rewrites the version everywhere it lives (VERSION_FILES) and turns the 「未發佈」 sections at the top of
       CHANGELOG.md into one `## X.Y.Z（YYYY-MM-DD）` section, then prints the diff. It never commits, tags or pushes;
       --dry-run only prints the diff.
check  version is the same everywhere, has an allowed format, CHANGELOG.md has a section for it; with --tag (the
       release gate) also: the tag matches, the section has a date, nothing is left under 「未發佈」.
notes  prints a draft of the GitHub release notes (「這版改了什麼／要不要更新／怎麼更新」) from the CHANGELOG section.
       The maintainer rewrites the bullet points in plain words before publishing.

sign   (docs/adr/0023 U5, docs/release-build.md「簽章金鑰」) writes, next to the built files in --dist:
       SHA256SUMS.txt (SYNOX-<v>.zip, SYNOX-Setup-<v>.exe when there), release.json (version, date, severity, summary,
       notes_url, every asset's sha256 + size, rebuild_venv, min_from) and release.json.sig (Ed25519 over the exact
       bytes of release.json, base64). Upload all three with the ZIP. The private key comes from --key <file> or
       SYNOX_RELEASE_KEY_FILE (a PEM file, password in SYNOX_RELEASE_KEY_PASSWORD, or one line of base64 = the 32-byte
       seed); it must live outside the repository (refused otherwise) and never goes into git.
keygen makes a new key pair (offline, once, by the founding maintainer): writes the private key (PEM; encrypted when
       SYNOX_RELEASE_KEY_PASSWORD is set) outside the repository and prints the public key for
       src/synox/update/signing.py RELEASE_PUBLIC_KEYS.

Standard library only (sign/keygen also need `cryptography`, already a SYNOX dependency); never connects to the
network, never runs git. Exit code: 0 ok, 1 check failed, 2 cannot run.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_URL = "https://github.com/ChouYangEn0401/SYNOX"
RELEASES_URL = REPO_URL + "/releases"

VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta)\.([1-9]\d*))?$")
TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta)\.([1-9]\d*))?$")

# Every place the SYNOX version is written (path, regex whose group 1 is the version). Keep them all equal.
VERSION_FILES: List[Tuple[str, "re.Pattern[str]"]] = [
    ("pyproject.toml", re.compile(r'^\[project\][^\[]*?^version\s*=\s*"([^"]*)"', re.M | re.S)),
    ("src/synox/__init__.py", re.compile(r'^__version__\s*=\s*"([^"]*)"', re.M)),
]
# The SDK has its own version (docs/sdk.md); the generated single-file copy must say the same as the source.
SDK_FILES: List[Tuple[str, "re.Pattern[str]"]] = [
    ("src/synox/sdk/author.py", re.compile(r'^SDK_VERSION\s*=\s*"([^"]*)"', re.M)),
    ("sdk/synox_sdk.py", re.compile(r'^SDK_VERSION\s*=\s*"([^"]*)"', re.M)),
]
# Places that show the version but are hand-made pages owned by others: only a reminder when they differ.
SHOWN_FILES: List[Tuple[str, "re.Pattern[str]"]] = [
    ("docs/landing/page.html", re.compile(r'class="ver"[^>]*>.*?<b>([^<]*)</b>', re.S)),
]

CHANGELOG = "CHANGELOG.md"
RELEASED_RE = re.compile(r"^## v?(\d+\.\d+\.\d+(?:-(?:alpha|beta)\.\d+)?)"
                         r"(?:\s*(?:（(\d{4}-\d{2}-\d{2})）|\((\d{4}-\d{2}-\d{2})\)|[—–-]\s*(\d{4}-\d{2}-\d{2})))?\s*$")
UNRELEASED_RE = re.compile(r"^## 未發佈(?:（(.*)）)?\s*$")
PLACEHOLDER = "（還沒寫：這版改了什麼）"

LABEL_TEXT = {None: "正式版", "beta": "測試版（beta，給外部試用）", "alpha": "內部測試版（alpha）"}


class ReleaseError(ValueError):
    pass


# ── versions ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    label: Optional[str] = None      # None (stable) | "alpha" | "beta"
    n: int = 0

    @classmethod
    def parse(cls, text: str) -> "Version":
        m = VERSION_RE.match(str(text or "").strip())
        if m is None:
            raise ReleaseError(f"版本 {text!r} 的格式不對：要像 0.2.1、0.2.1-beta.1、0.2.1-alpha.1（docs/versioning.md）")
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4), int(m.group(5) or 0))

    @property
    def base(self) -> "Version":
        return Version(self.major, self.minor, self.patch)

    @property
    def tag(self) -> str:
        return "v" + str(self)

    def __str__(self) -> str:
        core = f"{self.major}.{self.minor}.{self.patch}"
        return f"{core}-{self.label}.{self.n}" if self.label else core


def next_version(current: Version, kind: str, next_minor: bool = False) -> Version:
    """The version after `current` for bump <kind> (docs/versioning.md「怎麼升號」)."""
    if next_minor and not (kind in ("alpha", "beta") and current.label is None):
        raise ReleaseError("--next minor 只用在「從正式版開始下一輪 alpha／beta」")
    fresh = Version(current.major, current.minor + 1, 0) if next_minor else \
        Version(current.major, current.minor, current.patch + 1)
    if kind in ("patch", "minor"):
        if current.label:
            raise ReleaseError(f"現在是預覽版 {current}：要發它的正式版用 `bump final`，要下一個預覽版用 `bump alpha`／`bump beta`")
        return fresh if kind == "patch" else Version(current.major, current.minor + 1, 0)
    if kind == "alpha":
        if current.label is None:
            return Version(fresh.major, fresh.minor, fresh.patch, "alpha", 1)
        if current.label == "alpha":
            return Version(current.major, current.minor, current.patch, "alpha", current.n + 1)
        raise ReleaseError(f"{current} 已經是 beta，不能退回 alpha（要再修就 `bump beta`）")
    if kind == "beta":
        if current.label is None:
            return Version(fresh.major, fresh.minor, fresh.patch, "beta", 1)
        if current.label == "alpha":
            return Version(current.major, current.minor, current.patch, "beta", 1)
        return Version(current.major, current.minor, current.patch, "beta", current.n + 1)
    if kind == "final":
        if current.label is None:
            raise ReleaseError(f"{current} 已經是正式版；下一版用 `bump patch` 或 `bump minor`")
        return current.base
    raise ReleaseError(f"不認得 {kind!r}：要 patch、minor、alpha、beta 或 final")


def check_tag(version: str, tag: str) -> Optional[str]:
    if not TAG_RE.match(tag or ""):
        return f"tag {tag!r} 的格式不對：要像 v0.2.1、v0.2.1-beta.1、v0.2.1-alpha.1"
    if tag != "v" + version:
        return f"tag {tag} 跟版本 {version} 對不上（要 v{version}）"
    return None


# ── files ─────────────────────────────────────────────────────────────────

def _read(root: str, rel: str) -> Optional[str]:
    try:
        with open(os.path.join(root, rel), "r", encoding="utf-8", newline="") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _write(root: str, rel: str, text: str) -> None:
    with open(os.path.join(root, rel), "w", encoding="utf-8", newline="") as f:
        f.write(text)


def versions_in(root: str, files=VERSION_FILES) -> Dict[str, Optional[str]]:
    """{file: version written there, or None when the file or the line is missing}."""
    out: Dict[str, Optional[str]] = {}
    for rel, rx in files:
        text = _read(root, rel)
        m = rx.search(text) if text is not None else None
        out[rel] = m.group(1) if m else None
    return out


def current_version(root: str = ROOT) -> Version:
    found = versions_in(root)
    values = set(found.values())
    if None in values:
        missing = [rel for rel, v in found.items() if v is None]
        raise ReleaseError("找不到版本：" + "、".join(missing))
    if len(values) != 1:
        raise ReleaseError("版本不一致：" + "、".join(f"{rel}={v}" for rel, v in found.items()))
    return Version.parse(values.pop())


def set_version(text: str, rx: "re.Pattern[str]", new: str) -> str:
    m = rx.search(text)
    if m is None:
        raise ReleaseError("找不到要改的版本行")
    return text[:m.start(1)] + new + text[m.end(1):]


# ── CHANGELOG ─────────────────────────────────────────────────────────────

def _released(line: str) -> Optional[Tuple[str, str]]:
    m = RELEASED_RE.match(line.rstrip("\r\n"))
    if m is None:
        return None
    return m.group(1), next((d for d in m.group(2, 3, 4) if d), "")


def pending_span(lines: List[str]) -> Tuple[int, int]:
    """[start, end) of the block at the top that is not released yet: from the first `## ` heading up to the
    first version heading. start == end when there is nothing pending."""
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
    end = next((i for i in range(start, len(lines)) if _released(lines[i])), len(lines))
    if start < len(lines) and _released(lines[start]):
        return start, start
    return start, end


def _demote(block: List[str]) -> List[str]:
    """`## 未發佈（標題）` → `### 標題`；every other heading one level down. Fenced code is left alone."""
    out: List[str] = []
    fence = False
    for ln in block:
        if ln.lstrip().startswith("```"):
            fence = not fence
        if not fence and ln.startswith("#"):
            m = UNRELEASED_RE.match(ln.rstrip("\r\n"))
            if m:
                if m.group(1):
                    out.append(f"### {m.group(1)}\n")
                continue                      # a bare 「## 未發佈」 heading just disappears into the version section
            if re.match(r"^#{2,5} ", ln):
                ln = "#" + ln
        out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    return out


def sections(lines: List[str]) -> Dict[str, Tuple[int, int, str]]:
    """{version: (heading index, end index, date)} for every released heading."""
    found: Dict[str, Tuple[int, int, str]] = {}
    heads = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    for k, i in enumerate(heads):
        rel = _released(lines[i])
        if rel and rel[0] not in found:
            end = heads[k + 1] if k + 1 < len(heads) else len(lines)
            found[rel[0]] = (i, end, rel[1])
    return found


def stub_changelog(text: str, version: Version, date: str) -> str:
    """CHANGELOG.md with the pending 「未發佈」 sections gathered under `## <version>（<date>）`."""
    lines = text.splitlines(keepends=True)
    if str(version) in sections(lines):
        raise ReleaseError(f"CHANGELOG.md 已經有 {version} 這一節")
    start, end = pending_span(lines)
    body = _demote(lines[start:end])
    intro: List[str] = []
    if version.label is None:
        pre = sorted((v for v in sections(lines) if v.startswith(str(version) + "-")), key=_pre_key)
        if pre:
            intro = [f"{version} 的正式版，也包含 {'、'.join(pre)} 的改動（見下面那幾節）。\n", "\n"]
    if not body:
        body = [f"- {PLACEHOLDER}\n"]
    block = [f"## {version}（{date}）\n", "\n"] + intro + body + ["\n", "\n"]
    if start == len(lines) and lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return "".join(lines[:start] + block + lines[end:])


def _pre_key(v: str) -> tuple:
    p = Version.parse(v)
    return (p.label or "~", p.n)


def section_of(text: str, version: str) -> Tuple[str, List[str]]:
    lines = text.splitlines(keepends=True)
    found = sections(lines)
    if version not in found:
        raise ReleaseError(f"CHANGELOG.md 沒有 {version} 這一節（先 `bump`）")
    i, end, date = found[version]
    return date, lines[i + 1:end]


# ── commands ──────────────────────────────────────────────────────────────

def _diff(rel: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        fromfile="a/" + rel, tofile="b/" + rel))


def bump(root: str, kind: str, date: str = "", next_minor: bool = False, dry_run: bool = False) -> Tuple[Version, str]:
    """Returns (new version, unified diff). Writes the files unless dry_run; never commits."""
    old = current_version(root)
    new = next_version(old, kind, next_minor)
    date = date or _dt.date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise ReleaseError(f"日期 {date!r} 要寫成 YYYY-MM-DD")
    changes: Dict[str, Tuple[str, str]] = {}
    for rel, rx in VERSION_FILES:
        text = _read(root, rel) or ""
        changes[rel] = (text, set_version(text, rx, str(new)))
    log = _read(root, CHANGELOG)
    if log is None:
        raise ReleaseError("找不到 CHANGELOG.md")
    changes[CHANGELOG] = (log, stub_changelog(log, new, date))
    diff = "".join(_diff(rel, a, b) for rel, (a, b) in changes.items())
    if not dry_run:
        for rel, (_a, b) in changes.items():
            _write(root, rel, b)
    return new, diff


def check(root: str, tag: str = "") -> Tuple[List[str], List[str], List[str]]:
    """(ok, problems, reminders). Problems fail the check; reminders do not."""
    ok: List[str] = []
    bad: List[str] = []
    warn: List[str] = []
    found = versions_in(root)
    values = {v for v in found.values() if v is not None}
    for rel, v in found.items():
        if v is None:
            bad.append(f"{rel}：找不到版本")
    version = ""
    if len(values) > 1:
        bad.append("版本不一致：" + "、".join(f"{rel}={v}" for rel, v in found.items()))
    elif values:
        version = values.pop()
        try:
            Version.parse(version)
            ok.append(f"版本 {version}（{'、'.join(found)} 都一樣）")
        except ReleaseError as e:
            bad.append(str(e))
    sdk = versions_in(root, SDK_FILES)
    if len({v for v in sdk.values()}) == 1 and None not in sdk.values():
        ok.append(f"SDK {next(iter(sdk.values()))}（{'、'.join(sdk)} 都一樣）")
    else:
        bad.append("SDK 版本不一致（改了 author.py 要重產 sdk/synox_sdk.py：scripts/build_synox_sdk.py）："
                   + "、".join(f"{rel}={v}" for rel, v in sdk.items()))
    for rel, v in versions_in(root, SHOWN_FILES).items():
        if v is not None and version and v != version:
            warn.append(f"{rel} 顯示的版本是 {v}，不是 {version}（這頁由別人維護：發版時請他們更新）")
    if tag:
        problem = check_tag(version, tag) if version else f"沒有版本可以對 tag {tag}"
        if problem:
            bad.append(problem)
        else:
            ok.append(f"tag {tag}")
    log = _read(root, CHANGELOG)
    if log is None:
        bad.append("找不到 CHANGELOG.md")
    elif version:
        lines = log.splitlines(keepends=True)
        found_sections = sections(lines)
        if version not in found_sections:
            bad.append(f"CHANGELOG.md 沒有 {version} 這一節（`python scripts/release.py bump …` 會開）")
        else:
            i, end, date = found_sections[version]
            body = "".join(lines[i + 1:end])
            if not date:
                (bad if tag else warn).append(f"CHANGELOG.md 的 {version} 那一節沒有日期（要寫成 `## {version}（YYYY-MM-DD）`）")
            if PLACEHOLDER in body:
                (bad if tag else warn).append(f"CHANGELOG.md 的 {version} 那一節還沒寫改了什麼")
            if date:
                ok.append(f"CHANGELOG.md 有 {version}（{date}）")
        start, end = pending_span(lines)
        if end > start:
            count = sum(1 for ln in lines[start:end] if UNRELEASED_RE.match(ln.rstrip("\r\n")))
            msg = f"CHANGELOG.md 最上面還有 {count} 節「未發佈」（下一次 bump 會收進新版本）"
            (bad if tag else warn).append(msg + ("：發版前先 bump" if tag else ""))
    return ok, bad, warn


def _bullets(body: List[str]) -> List[str]:
    """The first line of every top-level bullet, under the sub-section titles (bold)."""
    out: List[str] = []
    fence = False
    for ln in body:
        s = ln.rstrip("\r\n")
        if s.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = re.match(r"^#{3,6}\s+(.*)$", s)
        if m:
            out.append(f"\n**{m.group(1).strip()}**")
        elif s.startswith("- "):
            item = s[2:].strip()
            out.append("- " + (item if len(item) <= 160 else item[:159] + "…"))
        elif s.strip() and not s.startswith(" ") and not out:
            out.append(s.strip())
    return out


def notes(root: str, version: str = "", exe: bool = False) -> str:
    v = Version.parse(version) if version else current_version(root)
    log = _read(root, CHANGELOG)
    if log is None:
        raise ReleaseError("找不到 CHANGELOG.md")
    date, body = section_of(log, str(v))
    items = _bullets(body) or ["- " + PLACEHOLDER]
    if v.label is None:
        should = ["建議更新。", "<!-- 有安全修正時改成：**強烈建議更新**：修了 …（一句話說是什麼問題） -->"]
        who = "這是**正式版**：大家都可以裝，`main` 與介紹頁的「⬇ 下載 SYNOX」就是這一版。"
    elif v.label == "beta":
        should = [f"想幫忙試新東西的人再更新。平常在用、不想遇到問題的人，請等正式版 {v.base}。",
                  "遇到問題請到 GitHub 開 issue（安全問題請看 SECURITY.md，不要公開）。"]
        who = "這是**測試版（beta）**：給願意幫忙試用的人，可能還有問題。"
    else:
        should = ["一般人請不要裝，等正式版。"]
        who = "這是**內部測試版（alpha）**：給 SYNOX 團隊自己測試用。"
    exe_line = (f"- **用安裝程式（.exe）的人**：下載這頁下面的 `SYNOX-Setup-{v}.exe`，裝在原本的位置（預設就是）；"
                "設定、資料、裝好的工具會留著。" if exe else
                "- **用安裝程式（.exe）的人**：⏳ 安裝程式還沒正式發佈，請先用 ZIP。")
    how = [
        "- **用 ZIP 的人**：點兩下 SYNOX 資料夾裡的 `Update.bat`（或網頁「設定 → 💻 電腦與備份 → 檢查更新」→「更新…」）："
        "它會先給你看這版改了什麼、問你一次，再下載、核對檔案、換好；出問題點 `Update.bat -Rollback` 回到上一版。"
        "<!-- 這一版沒有簽 release.json（release.py sign）的話，加一句：要打 `Update.bat -AllowUnsigned` 才會換 -->",
        f"- **用 ZIP、但還沒有 Update.bat 的舊版**：先點兩下 `Stop.bat` 關掉 SYNOX → 下載這頁下面的 `SYNOX-{v}.zip` → 解開 → 把裡面 `SYNOX` 資料夾的"
        "**全部內容**複製到你原本的 SYNOX 資料夾，問要不要取代就選「取代」→ 點兩下 `Setup.bat`。"
        "你的設定（`config.json`）、資料（`data`）、裝好的工具（`packs`）不在 ZIP 裡，不會被蓋掉。",
        f"- **用 git 的人**：`Stop.bat` → `git pull`（只要這一版：`git checkout {v.tag}`）→ `Setup.bat`。",
        exe_line,
        "- **工具**：網頁「設定 → 功能與安裝 → 工具庫（官方）」按「載入工具清單」，有新版的會標出來，按「安裝」就是更新"
        "（會先給你看改了什麼）；不滿意可以退回：`synox packs rollback <工具名>`。",
        "- 不確定自己是哪一版：在 SYNOX 資料夾打 `.venv\\Scripts\\synox about`，跟這頁的版本比。",
    ]
    out = [f"## SYNOX {v}" + (f"（{date}）" if date else ""), "", who, "", "### 這版改了什麼", "",
           "<!-- 維護者：把下面改成一般人看得懂的話，每條一句；技術細節留在 CHANGELOG.md -->"]
    out += items
    out += ["", "### 要不要更新", ""] + should + ["", "### 怎麼更新", ""] + how
    out += ["", "---", f"完整的改動：`CHANGELOG.md` 的「{v}」那一節。下載的檔可以對照 `SHA256SUMS.txt` 確認沒有壞掉或被換過。",
            f"所有版本：{RELEASES_URL}"]
    return "\n".join(out).replace("\n\n\n", "\n\n") + "\n"


# ── 簽章（docs/adr/0023 U5；src/synox/update/signing.py 驗）───────────────

KEY_ENV = "SYNOX_RELEASE_KEY_FILE"
KEY_PASSWORD_ENV = "SYNOX_RELEASE_KEY_PASSWORD"
SEVERITIES = ("normal", "security")


def _inside(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def load_private_key(path: str, root: str = ROOT):
    """私鑰檔（PEM，或一行 base64＝32 位元組 seed）→ Ed25519PrivateKey。檔案在 repo 裡面＝拒絕（私鑰絕不進 git）。"""
    import base64
    import binascii
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if not path:
        raise ReleaseError(f"要給私鑰：--key <檔案> 或環境變數 {KEY_ENV}（docs/release-build.md「簽章金鑰」）")
    if _inside(path, root):
        raise ReleaseError("私鑰檔在 repo 裡面：拒絕使用。私鑰只能放在 repo 以外、離線的地方（docs/release-build.md）")
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise ReleaseError(f"讀不到私鑰檔：{e}")
    if raw.lstrip().startswith(b"-----BEGIN"):
        password = os.environ.get(KEY_PASSWORD_ENV)
        try:
            key = serialization.load_pem_private_key(raw, password=password.encode() if password else None)
        except (ValueError, TypeError) as e:
            raise ReleaseError(f"私鑰檔打不開（密碼放在 {KEY_PASSWORD_ENV}？）：{e}")
    else:
        try:
            seed = base64.b64decode(raw.strip(), validate=True)
            key = Ed25519PrivateKey.from_private_bytes(seed)
        except (binascii.Error, ValueError) as e:
            raise ReleaseError(f"私鑰檔的格式不對（要 PEM 或一行 base64 的 32 位元組）：{e}")
    if not isinstance(key, Ed25519PrivateKey):
        raise ReleaseError("私鑰不是 Ed25519")
    return key


def public_key_b64(key) -> str:
    import base64
    from cryptography.hazmat.primitives import serialization
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def _sha256_file(path: str) -> Tuple[str, int]:
    import hashlib
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def sign(root: str, dist: str, key_path: str, *, severity: str = "normal", summary: str = "", min_from: str = "",
         rebuild_venv: bool = False, date: str = "", version: str = "") -> Dict[str, str]:
    """寫 dist/SHA256SUMS.txt、dist/release.json、dist/release.json.sig。回 {檔名: 路徑}。"""
    import base64
    import json
    v = Version.parse(version) if version else current_version(root)
    if severity not in SEVERITIES:
        raise ReleaseError(f"severity 只能是 {'、'.join(SEVERITIES)}")
    if min_from:
        Version.parse(min_from)
    key = load_private_key(key_path, root)
    names = [f"SYNOX-{v}.zip", f"SYNOX-Setup-{v}.exe"]
    assets: Dict[str, dict] = {}
    for name in names:
        path = os.path.join(dist, name)
        if os.path.isfile(path):
            sha, size = _sha256_file(path)
            assets[name] = {"sha256": sha, "size": size}
    if names[0] not in assets:
        raise ReleaseError(f"{dist} 裡沒有 {names[0]}（先 `python scripts/make_zip.py --tools …`）")
    manifest = {"version": str(v), "date": date or _dt.date.today().isoformat(), "severity": severity,
                "summary": summary, "notes_url": f"{RELEASES_URL}/tag/{v.tag}", "assets": assets,
                "rebuild_venv": bool(rebuild_venv), "min_from": min_from or None}
    blob = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    sig = base64.b64encode(key.sign(blob)).decode("ascii") + "\n"
    key.public_key().verify(base64.b64decode(sig), blob)            # 自己先驗一次
    out = {"SHA256SUMS.txt": os.path.join(dist, "SHA256SUMS.txt"), "release.json": os.path.join(dist, "release.json"),
           "release.json.sig": os.path.join(dist, "release.json.sig")}
    with open(out["SHA256SUMS.txt"], "w", encoding="utf-8", newline="\n") as f:
        for name, info in assets.items():
            f.write(f"{info['sha256']}  {name}\n")
    with open(out["release.json"], "wb") as f:
        f.write(blob)
    with open(out["release.json.sig"], "w", encoding="ascii", newline="\n") as f:
        f.write(sig)
    return out


def keygen(out_path: str, root: str = ROOT) -> str:
    """產生新的 Ed25519 金鑰：私鑰（PEM）寫到 out_path（repo 以外、不能蓋掉舊檔），回傳公鑰 base64。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if not out_path or _inside(out_path, root):
        raise ReleaseError("私鑰要寫到 repo 以外的地方（例如加密的隨身碟）：--out <路徑>")
    if os.path.exists(out_path):
        raise ReleaseError(f"{out_path} 已經有檔案了，不會蓋掉")
    key = Ed25519PrivateKey.generate()
    password = os.environ.get(KEY_PASSWORD_ENV)
    enc = serialization.BestAvailableEncryption(password.encode()) if password else serialization.NoEncryption()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)
    fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return public_key_b64(key)


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="release.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="print the current version")
    b = sub.add_parser("bump", help="next version + CHANGELOG section (prints the diff, never commits)")
    b.add_argument("kind", choices=["patch", "minor", "alpha", "beta", "final"])
    b.add_argument("--next", choices=["minor"], default="", help="alpha/beta from a stable version: of the next minor")
    b.add_argument("--date", default="", help="YYYY-MM-DD (default: today)")
    b.add_argument("--dry-run", action="store_true", help="only print the diff")
    c = sub.add_parser("check", help="version consistent, CHANGELOG section, tag format")
    c.add_argument("--tag", default="", help="the release gate: also require the tag to match and a dated section")
    n = sub.add_parser("notes", help="draft GitHub release notes from the CHANGELOG section")
    n.add_argument("--version", default="")
    n.add_argument("--exe", action="store_true", help="this release has SYNOX-Setup-<version>.exe")
    g = sub.add_parser("sign", help="SHA256SUMS.txt + release.json + release.json.sig next to the built files")
    g.add_argument("--dist", default=os.path.join(ROOT, "dist"))
    g.add_argument("--key", default="", help=f"private key file outside the repo (or env {KEY_ENV})")
    g.add_argument("--version", default="")
    g.add_argument("--security", action="store_true", help="a security fix (severity: security)")
    g.add_argument("--summary", default="", help="one plain sentence: what changed")
    g.add_argument("--min-from", default="", help="oldest version that may update straight to this one")
    g.add_argument("--rebuild-venv", action="store_true", help="tell Update.bat to reinstall the packages")
    g.add_argument("--date", default="")
    g.add_argument("--show-public", action="store_true", help="only print the public key of --key")
    k = sub.add_parser("keygen", help="make a new Ed25519 key pair (private key outside the repo)")
    k.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "show":
            print(current_version(args.root))
            return 0
        if args.cmd == "bump":
            old = current_version(args.root)
            new, diff = bump(args.root, args.kind, args.date, args.next == "minor", args.dry_run)
            print(diff, end="")
            print(f"\n{old} → {new}" + ("（--dry-run：沒有改任何檔）" if args.dry_run else "（檔案已改，還沒 commit）"),
                  file=sys.stderr)
            if not args.dry_run:
                print(f"下一步：補好 CHANGELOG 那一節 → `python scripts/release.py check --tag {new.tag}` → commit"
                      "（docs/versioning.md「發版步驟」）", file=sys.stderr)
            return 0
        if args.cmd == "check":
            ok, bad, warn = check(args.root, args.tag)
            for line in ok:
                print("✅ " + line)
            for line in warn:
                print("⚠️ " + line)
            for line in bad:
                print("❌ " + line)
            return 1 if bad else 0
        if args.cmd == "notes":
            print(notes(args.root, args.version, args.exe), end="")
            v = Version.parse(args.version) if args.version else current_version(args.root)
            hint = "勾「Set as a pre-release」" if v.label else "勾「Set as the latest release」"
            print(f"\n（GitHub 發佈頁：tag {v.tag}，標題「SYNOX {v}」，{hint}）", file=sys.stderr)
            return 0
        if args.cmd == "sign":
            key_path = args.key or os.environ.get(KEY_ENV, "")
            if args.show_public:
                print(public_key_b64(load_private_key(key_path, args.root)))
                return 0
            out = sign(args.root, args.dist, key_path, severity="security" if args.security else "normal",
                       summary=args.summary, min_from=args.min_from, rebuild_venv=args.rebuild_venv, date=args.date,
                       version=args.version)
            for name, path in out.items():
                print(f"✅ {name}  {path}")
            print("上傳這三個檔＋ZIP 到發佈頁（docs/versioning.md「每一版都要有」）", file=sys.stderr)
            return 0
        if args.cmd == "keygen":
            pub = keygen(args.out, args.root)
            print(pub)
            print(f"私鑰寫在 {args.out}（離線保存；不要放進 repo、雲端硬碟或聊天）。上面這行公鑰加進 "
                  "src/synox/update/signing.py 的 RELEASE_PUBLIC_KEYS。", file=sys.stderr)
            return 0
    except ReleaseError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
