"""Before making the repo public: look for secrets, local paths, personal e-mails and sensitive files.

    .venv\\Scripts\\python.exe scripts\\prepublish_check.py [--repo PATH] [--worktree-only]

Scans
  1. the working tree: every file git tracks plus untracked files that are not ignored;
  2. the git history: every blob reachable from any ref (each distinct blob is read once with
     `git cat-file --batch`, so this stays fast), every path that was ever committed, and the
     author / committer e-mails of every commit.

The report only says *where* (file:line) and *what kind* -- it never prints the matched text,
so the report itself is safe to paste. Exit code: 0 = nothing found, 1 = findings, 2 = could not run.

History findings do not mean you must rewrite history; they are listed so the maintainer can decide.
A line that contains `prepublish-check: allow` is skipped (use it for documented examples).
Standard library only; it never connects to the network and never runs anything from the repo.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOW_MARK = "prepublish-check: allow"
MAX_BYTES = 2_000_000

# ---- what counts as a problem ------------------------------------------------------------------

SECRET_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("Telegram bot token", re.compile(r"(?<![0-9A-Za-z])\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")),
    ("OpenAI／Anthropic 金鑰（sk-…）", re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-|ant-[a-z0-9]+-)?[A-Za-z0-9_-]{20,}")),
    ("Google API 金鑰（AIza…）", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("Google OAuth client secret（GOCSPX-…）", re.compile(r"GOCSPX-[A-Za-z0-9_-]{20,}")),
    ("Slack token（xox…）", re.compile(r"xox[abposr]-[A-Za-z0-9-]{10,}")),
    ("GitHub token", re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("AWS access key（AKIA…）", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])")),
    ("私鑰檔頭", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("Notion token", re.compile(r"(?:ntn_[A-Za-z0-9]{30,}|secret_[A-Za-z0-9]{43})")),
    ("Discord bot token", re.compile(r"(?<![A-Za-z0-9_-])[MNO][A-Za-z0-9_-]{23,27}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,40}(?![A-Za-z0-9_-])")),
]

# C:\Users\<name>, C:/Users/<name>, C:\\Users\\<name>; /Users/<name> (macOS); /home/<name> (Linux)
WIN_PATH = re.compile(r"[A-Za-z]:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)+([^\\/\s\"'`<>|*?:;,)\]}]*)", re.I)
POSIX_PATH = re.compile(r"(?<![A-Za-z]:)(?<![\w.])/(?:Users|home)/([^/\s\"'`<>|*?:;,)\]}]*)")
PLACEHOLDER_NAMES = {
    "", "x", "xx", "xxx", "you", "your", "yourname", "your_name", "your-name", "name", "username", "user_name",
    "me", "example", "public", "default", "all users", "someone", "somebody", "foo", "bar", "alice", "bob",
    "runner", "runneradmin", "ci", "test", "tester", "admin", "...", "…",
}

EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?![A-Za-z0-9-])")
ALLOWED_EMAILS = {"noreply@anthropic.com", "git@github.com", "noreply@github.com"}
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "users.noreply.github.com")
RESERVED_TLDS = (".invalid", ".test", ".example", ".localhost", ".local")
PLACEHOLDER_LOCAL_PARTS = {"me", "you", "user", "test", "foo", "bar", "someone", "name", "example", "nobody", "noreply", "no-reply"}

SENSITIVE_NAMES = [".env", ".env.*", "config.json", "packs.lock", "*.enc", ".synox.key", "*.key", "*.pem", "*.p12", "*.pfx",
                   "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials.json", "token.json", "client_secret*.json",
                   "*.kdbx", "secrets.json"]
ALLOWED_NAMES = {"config.example.json", ".env.example", ".env.sample"}


class Finding(NamedTuple):
    where: str      # "worktree" / "history" / "commit"
    path: str
    line: int       # 0 = whole file
    kind: str
    note: str = ""  # extra, never the matched secret


# ---- matching ----------------------------------------------------------------------------------

def _placeholder_name(name: str) -> bool:
    n = name.strip().lower()
    return (n in PLACEHOLDER_NAMES or n[:1] in "<{%$[(" or n.startswith(("%user", "$user", "${user", "$env"))
            or set(n) <= {"x", "*", "."})


def email_allowed(addr: str) -> bool:
    local, _, domain = addr.lower().rpartition("@")
    return (addr.lower() in ALLOWED_EMAILS or domain.endswith(RESERVED_TLDS)
            or any(domain == d or domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS)
            or local in PLACEHOLDER_LOCAL_PARTS)


def scan_text(text: str) -> List[Tuple[int, str]]:
    """(line number, kind) for every problem in one file's text. Never returns the matched text."""
    out: List[Tuple[int, str]] = []
    for no, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARK in line:
            continue
        for kind, pat in SECRET_PATTERNS:
            if pat.search(line):
                out.append((no, "疑似密鑰：" + kind))
        if any(not _placeholder_name(m.group(1)) for m in WIN_PATH.finditer(line)) or \
           any(not _placeholder_name(m.group(1)) for m in POSIX_PATH.finditer(line)):
            out.append((no, "本機絕對路徑（含使用者名稱）"))
        if any(not email_allowed(m.group(0)) for m in EMAIL.finditer(line)):
            out.append((no, "個人信箱"))
    return out


def sensitive_name(path: str) -> bool:
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    if base.lower() in ALLOWED_NAMES:
        return False
    return any(fnmatch.fnmatch(base.lower(), pat) for pat in SENSITIVE_NAMES)


def _decode(data: bytes) -> Optional[str]:
    if b"\0" in data[:8000]:
        return None                                  # binary
    return data.decode("utf-8", errors="replace")


# ---- git ---------------------------------------------------------------------------------------

def _git(repo: str, *args: str, data: Optional[bytes] = None) -> bytes:
    proc = subprocess.run(["git", "-C", repo, "-c", "core.quotepath=off", *args], input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} 失敗：{proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


def worktree_files(repo: str) -> List[str]:
    out = _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted({p for p in out.decode("utf-8", "replace").split("\0") if p})


def scan_worktree(repo: str) -> List[Finding]:
    found: List[Finding] = []
    for rel in worktree_files(repo):
        if sensitive_name(rel):
            found.append(Finding("worktree", rel, 0, "敏感檔名（不該提交）"))
        full = os.path.join(repo, rel)
        try:
            if not os.path.isfile(full) or os.path.getsize(full) > MAX_BYTES:
                continue
            with open(full, "rb") as fh:
                text = _decode(fh.read())
        except OSError:
            continue
        if text is not None:
            found.extend(Finding("worktree", rel, no, kind) for no, kind in scan_text(text))
    return found


def _history_blobs(repo: str) -> Dict[str, str]:
    """{blob sha: one path it was committed under} for every blob reachable from any ref (size-capped)."""
    lines = _git(repo, "rev-list", "--all", "--objects").decode("utf-8", "replace").splitlines()
    named: Dict[str, str] = {}
    for ln in lines:
        sha, _, path = ln.partition(" ")
        if path:
            named.setdefault(sha, path)
    if not named:
        return {}
    check = _git(repo, "cat-file", "--batch-check=%(objecttype) %(objectname) %(objectsize)",
                 data=("\n".join(named) + "\n").encode()).decode().splitlines()
    blobs = {}
    for row in check:
        parts = row.split()
        if len(parts) == 3 and parts[0] == "blob" and int(parts[2]) <= MAX_BYTES:
            blobs[parts[1]] = named[parts[1]]
    return blobs


def _history_paths(repo: str) -> Set[str]:
    """Every path any commit on any ref ever added or changed."""
    out = _git(repo, "log", "--all", "--name-only", "--format=", "-z", "--no-renames")
    return {p.strip("\n") for p in out.decode("utf-8", "replace").split("\0") if p.strip("\n")}


def _read_blobs(repo: str, shas: List[str]) -> Iterable[Tuple[str, bytes]]:
    if not shas:
        return
    raw = _git(repo, "cat-file", "--batch", data=("\n".join(shas) + "\n").encode())
    pos = 0
    while pos < len(raw):
        nl = raw.index(b"\n", pos)
        sha, _type, size = raw[pos:nl].decode().split()
        start = nl + 1
        yield sha, raw[start:start + int(size)]
        pos = start + int(size) + 1


def _commit_of(repo: str, sha: str) -> str:
    try:
        out = _git(repo, "log", "--all", "-1", "--format=%h", f"--find-object={sha}").decode().strip()
    except RuntimeError:
        out = ""
    return out.splitlines()[0] if out else ""


def scan_history(repo: str) -> List[Finding]:
    found: List[Finding] = []
    current = {ln.split()[1] for ln in _git(repo, "ls-files", "-s").decode("utf-8", "replace").splitlines() if ln.strip()}
    tracked_now = set(worktree_files(repo))
    blobs = _history_blobs(repo)
    for path in sorted(_history_paths(repo)):
        if sensitive_name(path) and path not in tracked_now:
            found.append(Finding("history", path, 0, "敏感檔名（曾經提交過）"))
    todo = sorted(sha for sha in blobs if sha not in current)       # same content as now = already in worktree report
    for sha, data in _read_blobs(repo, todo):
        text = _decode(data)
        if text is None:
            continue
        hits = scan_text(text)
        if hits:
            commit = _commit_of(repo, sha)
            note = f"commit {commit}" if commit else ""
            found.extend(Finding("history", blobs[sha], no, kind, note) for no, kind in hits)
    emails = _git(repo, "log", "--all", "--format=%ae%n%ce").decode("utf-8", "replace").split()
    for addr in sorted(set(emails)):
        if not email_allowed(addr):
            found.append(Finding("commit", "(commit 作者／提交者)", 0, "個人信箱", f"{addr.split('@')[0][:1]}…@{addr.rpartition('@')[2]}"))
    return found


# ---- report ------------------------------------------------------------------------------------

def report(findings: List[Finding], history: bool) -> str:
    out = ["公開前檢查（prepublish_check）", ""]
    sections = [("worktree", "目前的檔案（要在公開前修掉）"), ("history", "git 歷史（舊版本裡有；要不要改寫歷史由維護者決定）"),
                ("commit", "commit 的作者／提交者資訊")]
    for key, title in sections:
        if key != "worktree" and not history:
            out.append(f"■ {title}：沒有檢查（--worktree-only）")
            continue
        rows = [f for f in findings if f.where == key]
        if key == "history":                         # one row per (file, kind): many old versions share a line
            groups: Dict[Tuple[str, str], List[Finding]] = {}
            for f in rows:
                groups.setdefault((f.path, f.kind), []).append(f)
            out.append(f"■ {title}：{'沒有發現' if not groups else f'{len(groups)} 項'}")
            for (path, kind), fs in sorted(groups.items()):
                lines = sorted({f.line for f in fs if f.line})
                commits = sorted({f.note for f in fs if f.note})
                loc = path + (":" + ",".join(map(str, lines[:5])) + ("…" if len(lines) > 5 else "") if lines else "")
                extra = f"{len(commits)} 個相關 commit，例如 {commits[0]}" if commits else ""
                out.append(f"  - {loc}　{kind}" + (f"（{extra}）" if extra else ""))
            out.append("")
            continue
        out.append(f"■ {title}：{'沒有發現' if not rows else f'{len(rows)} 項'}")
        for f in sorted(set(rows)):
            loc = f.path + (f":{f.line}" if f.line else "")
            out.append(f"  - {loc}　{f.kind}" + (f"（{f.note}）" if f.note else ""))
        out.append("")
    if findings:
        out.append("結果：有需要處理的項目（只列位置與種類，沒有印出內容）。")
        out.append(f"確定是範例或假資料的行，可以在同一行加上 `{ALLOW_MARK}`。")
    else:
        out.append("結果：沒有發現問題。")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="公開前檢查：密鑰、本機路徑、個人信箱、敏感檔名（工作樹＋git 歷史）")
    parser.add_argument("--repo", default=ROOT, help="要檢查的 git repo（預設：這個 SYNOX）")
    parser.add_argument("--worktree-only", action="store_true", help="只看目前的檔案，不看 git 歷史")
    args = parser.parse_args(argv)
    try:
        _git(args.repo, "rev-parse", "--git-dir")
        findings = scan_worktree(args.repo)
        if not args.worktree_only:
            findings += scan_history(args.repo)
    except (RuntimeError, OSError) as e:
        print(f"沒辦法檢查：{e}", file=sys.stderr)
        return 2
    text = report(findings, history=not args.worktree_only)
    if not sys.stdout.isatty():                       # redirected on a cp950 machine: write UTF-8, not the locale code page
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", "replace"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
