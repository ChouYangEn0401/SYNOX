"""Pre-release check: every place that states the SYNOX version agrees, and the version is newer than every tag.

    python scripts/check_version_consistency.py [--tag vX.Y.Z[-alpha.N|-beta.N]] [--no-git] [--root DIR]

Rules: docs/versioning.md (§1 order, §2 where the version lives). Checked:

  errors (exit 1)
    - src/synox/__init__.py `__version__` == pyproject.toml [project].version (the one source; release.py bump
      writes both), and it is a SemVer version
    - CHANGELOG.md: the first version heading (`## X（YYYY-MM-DD）` or the planned `## X（未發佈）`) is that version
    - setup/installer/synox.iss: the version is not written there (only the "0.0.0" fallback); the build passes
      /DAppVersion from `installer_ci.py version`, which reads pyproject.toml
    - docs: every 「目前版本：`X`」 line in README.md and docs/**/*.md says that version
    - git tags (`git tag --list v*`, local only, never fetches): the version sorts after the newest tag (SemVer);
      it may equal a tag only when that tag points at HEAD (a checkout of a released version). A tag that is not
      SemVer is reported. --tag vX (the release gate) also requires vX == "v" + version.
  reminders (exit 0)
    - docs/landing/page.html version badge (that page has its own maintainer)
    - the CHANGELOG section is still 「未發佈」 (no date): fine on dev, `release.py bump keep` dates it

Standard library only; no network; runs `git tag` / `git rev-parse` read-only (skipped with --no-git, or when
git or the tags are not there, e.g. a shallow CI checkout: then only a reminder).
Exit code: 0 ok, 1 a check failed, 2 cannot run.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_ID = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
                       rf"(?:-({_ID}(?:\.{_ID})*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
PYPROJECT_RE = re.compile(r'^\[project\][^\[]*?^version\s*=\s*"([^"]*)"', re.M | re.S)
INIT_RE = re.compile(r'^__version__\s*=\s*"([^"]*)"', re.M)
HEADING_RE = re.compile(r"^## v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?:\s*(?:（(.*?)）|\((.*?)\)|[—–-]\s*(\S+)))?\s*$")
ISS_DEFINE_RE = re.compile(r'^\s*#define\s+AppVersion\s+"([^"]*)"', re.M)
ISS_LITERAL_RE = re.compile(r"^\s*AppVersion\s*=\s*(?!\{#AppVersion\})(\S.*)$", re.M)
CURRENT_RE = re.compile(r"目前版本[：:]\s*`v?([^`]+)`")
BADGE_RE = re.compile(r'class="ver"[^>]*>.*?<b>([^<]*)</b>', re.S)
ISS = "setup/installer/synox.iss"
PLACEHOLDER_VERSION = "0.0.0"


def semver_key(version: str) -> Optional[tuple]:
    """SemVer 2.0.0 precedence (same rules as synox.packs.upgrade.semver_key); None when not SemVer."""
    m = SEMVER_RE.match(str(version or "").strip())
    if m is None:
        return None
    pre = m.group(4)
    tail: tuple = (1,) if pre is None else \
        (0,) + tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), tail


def _read(root: str, rel: str) -> Optional[str]:
    try:
        with open(os.path.join(root, rel), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def changelog_top(text: str) -> Tuple[str, str]:
    """(first version heading's version, what is in its brackets: a date, 「未發佈」 or "")."""
    fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        if fence:
            continue
        m = HEADING_RE.match(line.rstrip())
        if m:
            return m.group(1), next((g for g in m.group(2, 3, 4) if g), "")
    return "", ""


def doc_files(root: str) -> List[str]:
    out = ["README.md"] if os.path.isfile(os.path.join(root, "README.md")) else []
    for base, dirs, files in os.walk(os.path.join(root, "docs")):
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "_")))
        out += sorted(os.path.relpath(os.path.join(base, f), root).replace(os.sep, "/") for f in files if f.endswith(".md"))
    return out


def git_tags(root: str) -> Tuple[Optional[List[str]], List[str]]:
    """(every v* tag, the tags on HEAD); (None, []) when git or the repository is not there."""
    def run(*args: str) -> Optional[str]:
        try:
            proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout if proc.returncode == 0 else None
    tags = run("tag", "--list", "v*")
    if tags is None:
        return None, []
    head = run("tag", "--points-at", "HEAD") or ""
    return [t.strip() for t in tags.splitlines() if t.strip()], [t.strip() for t in head.splitlines() if t.strip()]


def released_code_unchanged(root: str, tag: str) -> bool:
    """True when `tag` is an ancestor of HEAD and nothing that ships (src/, vendor/, pyproject.toml) changed since it:
    HEAD only adds merge commits or docs on top of the released version (dev after a release merge, main after a merge)."""
    def ok(*args: str) -> bool:
        try:
            return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return ok("merge-base", "--is-ancestor", tag, "HEAD") and ok("diff", "--quiet", tag, "HEAD", "--", "src", "vendor", "pyproject.toml")


def check(root: str = ROOT, tag: str = "", use_git: bool = True,
          tags: Optional[Sequence[str]] = None, head_tags: Sequence[str] = (),
          unchanged_since: Optional[Sequence[str]] = None) -> Tuple[List[str], List[str], List[str]]:
    """(ok, problems, reminders). `tags`/`head_tags`/`unchanged_since` replace the git calls (tests)."""
    ok: List[str] = []
    bad: List[str] = []
    warn: List[str] = []

    py = _read(root, "pyproject.toml")
    init = _read(root, "src/synox/__init__.py")
    m_py = PYPROJECT_RE.search(py or "")
    m_init = INIT_RE.search(init or "")
    if not m_py:
        bad.append("pyproject.toml：找不到 [project] version")
    if not m_init:
        bad.append("src/synox/__init__.py：找不到 __version__")
    if not (m_py and m_init):
        return ok, bad, warn
    version = m_py.group(1)
    if m_init.group(1) != version:
        bad.append(f"版本不一致：pyproject.toml={version}、src/synox/__init__.py={m_init.group(1)}"
                   "（用 `python scripts/release.py bump …` 一起改）")
        return ok, bad, warn
    key = semver_key(version)
    if key is None:
        bad.append(f"版本 {version!r} 不是 SemVer（要像 0.2.2、0.2.2-beta.1；docs/versioning.md §1）")
        return ok, bad, warn
    ok.append(f"版本 {version}（pyproject.toml、src/synox/__init__.py）")

    log = _read(root, "CHANGELOG.md")
    if log is None:
        bad.append("找不到 CHANGELOG.md")
    else:
        top, note = changelog_top(log)
        if top != version:
            bad.append(f"CHANGELOG.md 最上面的版本是 {top or '（沒有）'}，不是 {version}"
                       "（版本由新到舊排，最上面一節是這一版；docs/versioning.md §4）")
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", note):
            ok.append(f"CHANGELOG.md 最上面是 {version}（{note}）")
        else:
            (bad if tag else warn).append(f"CHANGELOG.md 的 {version} 還沒有日期（「{note or '空白'}」）：發版那天 "
                                          "`python scripts/release.py bump keep` 會寫上")

    iss = _read(root, ISS)
    if iss is None:
        warn.append(f"找不到 {ISS}（沒有安裝器就不查）")
    else:
        defines = ISS_DEFINE_RE.findall(iss)
        literal = ISS_LITERAL_RE.findall(iss)
        if any(d != PLACEHOLDER_VERSION for d in defines) or literal:
            bad.append(f"{ISS} 寫死了版本（{', '.join(defines + literal)}）：版本只能在建置時用 /DAppVersion 從 "
                       f"`installer_ci.py version` 帶進去，檔裡只留 \"{PLACEHOLDER_VERSION}\"")
        else:
            ok.append(f"安裝器：版本在建置時從 pyproject.toml 帶入（{ISS} 只有 {PLACEHOLDER_VERSION} 的預設）")

    stale = []
    for rel in doc_files(root):
        for n, line in enumerate((_read(root, rel) or "").splitlines(), 1):
            for found in CURRENT_RE.findall(line):
                if found != version:
                    stale.append(f"{rel}:{n} 寫「目前版本：{found}」")
    if stale:
        bad.append(f"文件裡的「目前版本」不是 {version}：" + "；".join(stale))
    else:
        ok.append("文件裡的「目前版本」都一樣")

    page = _read(root, "docs/landing/page.html")
    badge = BADGE_RE.search(page or "")
    if badge and badge.group(1).strip() != version:
        warn.append(f"docs/landing/page.html 的版本徽章是 {badge.group(1).strip()}，不是 {version}（介紹頁的維護者發版時改）")

    if tag:
        if tag != "v" + version:
            bad.append(f"tag {tag} 跟版本 {version} 對不上（要 v{version}）")
        else:
            ok.append(f"tag {tag}")

    if tags is None and use_git:
        tags, head_tags = git_tags(root)
    if tags is None:
        warn.append("沒有比 git tag（--no-git，或這裡沒有 git）")
        return ok, bad, warn
    if not tags:
        warn.append("沒有任何 v* tag 可以比（淺層 clone？發版前在完整的 clone 再跑一次）")
        return ok, bad, warn
    parsed = []
    for t in tags:
        k = semver_key(t[1:]) if t.startswith("v") else None
        if k is None:
            bad.append(f"tag {t} 不是 v＋SemVer（發出去的 tag 不改；之後不要再這樣打）")
        else:
            parsed.append((k, t))
    if parsed:
        newest_key, newest = max(parsed)
        mine = "v" + version
        if key > newest_key:
            ok.append(f"{version} 比最新的 tag {newest} 新")
        elif mine in tags and mine in head_tags and key == newest_key:
            ok.append(f"這裡就是已發佈的 {mine}（HEAD 上的 tag）")
        elif mine in tags and mine not in head_tags and key == newest_key and (
                (mine in unchanged_since) if unchanged_since is not None else (use_git and released_code_unchanged(root, mine))):
            ok.append(f"{mine} 的 tag 在這個 commit 的祖先上，之後只有合併與文件（src、vendor、pyproject.toml 沒變）")
        elif mine in tags and mine not in head_tags:
            bad.append(f"{mine} 已經發過了（tag 在別的 commit）：版本號不能重用，"
                       "要再發就用下一個號碼（`python scripts/release.py bump …`；docs/versioning.md §5）")
        else:
            bad.append(f"{version} 沒有比最新的 tag {newest} 新：更新檢查會把它當成舊版。"
                       "照 SemVer 排（alpha < beta < 正式版；發過 beta 的號碼不能再發 alpha，要 `bump alpha --next patch`）")
    return ok, bad, warn


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", default=ROOT, help="repository root (default: this checkout)")
    p.add_argument("--tag", default="", help="the release gate: the tag about to be pushed, must be v + version")
    p.add_argument("--no-git", action="store_true", help="do not compare with git tags")
    args = p.parse_args(argv)
    if not os.path.isfile(os.path.join(args.root, "pyproject.toml")):
        print(f"{args.root} 不是 SYNOX 的 repo（沒有 pyproject.toml）", file=sys.stderr)
        return 2
    ok, bad, warn = check(args.root, tag=args.tag, use_git=not args.no_git)
    for line in ok:
        print("✅ " + line)
    for line in warn:
        print("⚠️ " + line)
    for line in bad:
        print("❌ " + line)
    print("版本一致：通過" if not bad else f"版本一致：{len(bad)} 個問題", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    sys.exit(main())
