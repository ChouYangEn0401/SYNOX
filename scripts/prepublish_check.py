"""Before making the repo public: look for secrets, local paths, personal e-mails, private names and sensitive files.

    .venv\\Scripts\\python.exe scripts\\prepublish_check.py [--repo PATH] [--worktree-only] [--terms FILE]
    .venv\\Scripts\\python.exe scripts\\prepublish_check.py --pre-push <remote>        (git pre-push hook; refs on stdin)

Scans
  1. the working tree: every file git tracks plus untracked files that are not ignored;
  2. the git history: every blob reachable from any ref (each distinct blob is read once with
     `git cat-file --batch`, so this stays fast), every path that was ever committed, every commit
     and tag message, and the author / committer e-mails of every commit.
  --pre-push: for every ref being pushed, the WHOLE tree of the pushed commit (not only the diff), every
     commit that the remote does not have yet (message, author / committer, every new blob and path) and the
     message of a pushed annotated tag. scripts/hooks/pre-push is the hook that calls it.

Private terms (names of the maintainer's private projects, accounts, quote markers...) are NOT stored in this
repo: the list is read from --terms FILE, else the file named by $SYNOX_PRIVATE_TERMS, else the text in
$SYNOX_PRIVATE_TERMS_TEXT (a CI secret), else <git common dir>/info/synox-private-terms.txt (inside .git, never
committed, shared by every worktree). Format: one string per line (case-insensitive), `re:<regex>`, `#` comments,
`# @category: <name>` and `# @level: block|note` lines (note lines are ignored here). Without a list the check
says so loudly; --pre-push then refuses (exit 2) unless --allow-no-terms is given.

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
ALLOWED_EMAILS = {"noreply@anthropic.com", "git@github.com", "noreply@github.com",
                  "mi.anthony.chou@gmail.com", "mi.anthony.chou+security@gmail.com"}   # project contact addresses (published on purpose)
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "users.noreply.github.com")
RESERVED_TLDS = (".invalid", ".test", ".example", ".localhost", ".local")
PLACEHOLDER_LOCAL_PARTS = {"me", "you", "user", "test", "foo", "bar", "someone", "name", "example", "nobody", "noreply", "no-reply"}

SENSITIVE_NAMES = [".env", ".env.*", "config.json", "packs.lock", "*.enc", ".synox.key", "*.key", "*.pem", "*.p12", "*.pfx",
                   "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials.json", "token.json", "client_secret*.json",
                   "*.kdbx", "secrets.json"]
ALLOWED_NAMES = {"config.example.json", ".env.example", ".env.sample"}


# ---- private terms (the list itself never lives in the repo) ------------------------------------

TERMS_ENV = "SYNOX_PRIVATE_TERMS"            # path to the list
TERMS_TEXT_ENV = "SYNOX_PRIVATE_TERMS_TEXT"  # the list itself (e.g. a CI secret)
TERMS_FILE = "synox-private-terms.txt"       # default: <git common dir>/info/<this>
TERM_LABELS = {"private_project": "私人專案名", "account": "帳號／信箱", "local_path": "本機路徑", "third_party": "第三者名",
               "secret": "金鑰", "quote_marker": "原話標記", "private_path": "私人路徑", "private_dep": "私人相依套件名"}
NO_TERMS_WARNING = ("⚠⚠⚠ 沒有私人詞清單：私人專案名、帳號、原話標記這類字【沒有被檢查】。"
                    f"把清單放在 .git/info/{TERMS_FILE}（或設 {TERMS_ENV}／{TERMS_TEXT_ENV}，或用 --terms）；"
                    "說明見 docs/AGENT.md「公開前檢查清單」。")


class Terms(NamedTuple):
    source: str                                      # where the list came from (a description, never the content)
    rules: List[Tuple[str, "re.Pattern[str]"]]       # (kind label, combined pattern); block level only
    count: int


_TERMS: Optional[Terms] = None


def _term_literal(lit: str) -> str:
    body = re.escape(lit)
    if len(lit) < 6 and re.fullmatch(r"[A-Za-z0-9._-]+", lit):
        body = rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"
    return f"(?i:{body})"


def parse_terms(text: str, source: str) -> Terms:
    """Same format as the maintainer's deny list. Raises ValueError (never echoing the content) on a bad line."""
    groups: Dict[str, List[str]] = {}
    cat, level, count = "private", "block", 0
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            m = re.match(r"#\s*@(category|level)\s*:\s*(\S+)\s*$", s)
            if m and m.group(1) == "category":
                cat = m.group(2)
            elif m:
                level = m.group(2)
            continue
        if level != "block":
            continue
        if s.startswith("re:"):
            m = re.match(r"^\(\?([aiLmsux]+)\)", s[3:])
            piece = f"(?{m.group(1)}:{s[3 + m.end():]})" if m else f"(?:{s[3:]})"
            try:
                re.compile(piece)
            except re.error:
                raise ValueError(f"私人詞清單第 {n} 行的正規式寫錯") from None
        else:
            if len(s) < (4 if s.isascii() else 3):       # too short: too many false hits
                continue
            piece = _term_literal(s)
        groups.setdefault(TERM_LABELS.get(cat, "私人詞"), []).append(piece)
        count += 1
    rules = [(label, re.compile("|".join(pieces))) for label, pieces in groups.items()]
    return Terms(source, rules, count)


def _git_common_dir(repo: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", repo, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.decode("utf-8", "replace").strip() or None


def load_terms(repo: str, path: Optional[str] = None, environ=None) -> Optional[Terms]:
    """The private term list, or None when there is none. Never returns or prints the content."""
    environ = os.environ if environ is None else environ
    if path or environ.get(TERMS_ENV):
        p, label = (path, "--terms") if path else (environ[TERMS_ENV], f"${TERMS_ENV}")
        if not os.path.isfile(p):
            raise ValueError(f"找不到私人詞清單（{label} 指的檔案不存在）")
    elif environ.get(TERMS_TEXT_ENV):
        return parse_terms(environ[TERMS_TEXT_ENV], f"${TERMS_TEXT_ENV}")
    else:
        common = _git_common_dir(repo)
        p, label = (os.path.join(common, "info", TERMS_FILE) if common else ""), f".git/info/{TERMS_FILE}"
        if not p or not os.path.isfile(p):
            return None
    with open(p, encoding="utf-8-sig") as fh:
        return parse_terms(fh.read(), label)


def set_terms(terms: Optional[Terms]) -> None:
    global _TERMS
    _TERMS = terms


def term_kinds(text: str) -> List[str]:
    if not _TERMS:
        return []
    return [label for label, rx in _TERMS.rules if rx.search(text)]


def mask_terms(text: str) -> str:
    if not _TERMS:
        return text
    for _label, rx in _TERMS.rules:
        text = rx.sub("＊＊＊", text)
    return text


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
        out.extend((no, "私人詞：" + kind) for kind in term_kinds(line))
    return out


def path_findings(where: str, path: str, note: str = "") -> List[Finding]:
    """Private terms in a file name. The name is printed with the term masked."""
    return [Finding(where, mask_terms(path), 0, "檔名含私人詞：" + kind, note) for kind in term_kinds(path)]


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
        found.extend(path_findings("worktree", rel))
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
        if path not in tracked_now:
            found.extend(path_findings("history", path))
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
    found.extend(scan_commits(repo, ["--all"]))
    found.extend(scan_tag_messages(repo, [ln for ln in _git(repo, "for-each-ref", "--format=%(refname)", "refs/tags")
                                          .decode("utf-8", "replace").splitlines() if ln]))
    return found


def scan_commits(repo: str, revs: List[str]) -> List[Finding]:
    """Commit messages, and private terms in author / committer names and e-mails, for `git log <revs>`."""
    found: List[Finding] = []
    raw = _git(repo, "log", *revs, "--format=%H%x00%an <%ae>%x00%cn <%ce>%x00%B%x01").decode("utf-8", "replace")
    for rec in raw.split("\x01"):
        rec = rec.lstrip("\n")
        if not rec:
            continue
        sha, author, committer, body = rec.split("\x00", 3)
        where = f"commit {sha[:10]} 的訊息"
        found.extend(Finding("commit", where, no, kind) for no, kind in scan_text(body))
        found.extend(Finding("commit", f"commit {sha[:10]} 的作者／提交者", 0, "私人詞：" + kind)
                     for kind in sorted(set(term_kinds(author) + term_kinds(committer))))
    return found


def scan_tag_messages(repo: str, refs: List[str]) -> List[Finding]:
    found: List[Finding] = []
    for ref in refs:
        if _git(repo, "cat-file", "-t", ref).decode().strip() != "tag":
            continue
        body = _git(repo, "cat-file", "tag", ref).decode("utf-8", "replace").split("\n\n", 1)[-1]
        found.extend(Finding("commit", f"tag {ref.rsplit('/', 1)[-1]} 的訊息", no, kind) for no, kind in scan_text(body))
    return found


def _scan_blobs(repo: str, where: str, named: Dict[str, str], note: str = "") -> List[Finding]:
    found: List[Finding] = []
    check = _git(repo, "cat-file", "--batch-check=%(objecttype) %(objectname) %(objectsize)",
                 data=("\n".join(named) + "\n").encode()).decode().splitlines() if named else []
    shas = [p[1] for p in (row.split() for row in check) if len(p) == 3 and p[0] == "blob" and int(p[2]) <= MAX_BYTES]
    for sha, data in _read_blobs(repo, shas):
        text = _decode(data)
        if text is not None:
            found.extend(Finding(where, named[sha], no, kind, note) for no, kind in scan_text(text))
    return found


ZERO = "0" * 40


def scan_push(repo: str, remote: str, updates: str) -> List[Finding]:
    """What `git push` is about to publish: for every pushed ref the whole tree of the pushed commit, every commit the
    remote does not have yet (message, author, new blobs and paths) and a pushed annotated tag's message."""
    found: List[Finding] = []
    remote_refs = [ln for ln in _git(repo, "for-each-ref", "--format=%(refname)", f"refs/remotes/{remote}")
                   .decode("utf-8", "replace").splitlines() if ln]
    seen_trees: Set[str] = set()
    seen_blobs: Set[str] = set()                              # several refs in one push share most of their files
    done: List[str] = []                                      # commits already covered by an earlier ref of this push
    for line in updates.splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[1] == ZERO:
            continue                                          # malformed, or a delete
        local_ref, local_sha = parts[0], parts[1]
        commit = _git(repo, "rev-parse", f"{local_sha}^{{commit}}").decode().strip()
        if commit not in seen_trees:                          # 1. the whole tree that will be on the remote
            seen_trees.add(commit)
            named: Dict[str, str] = {}
            for row in _git(repo, "ls-tree", "-r", "-z", commit).decode("utf-8", "replace").split("\0"):
                if not row:
                    continue
                meta, path = row.split("\t", 1)
                if meta.split()[2] not in seen_blobs:
                    named.setdefault(meta.split()[2], path)
                if sensitive_name(path):
                    found.append(Finding("worktree", path, 0, "敏感檔名（不該提交）"))
                found.extend(path_findings("worktree", path))
            seen_blobs.update(named)
            found.extend(_scan_blobs(repo, "worktree", named, local_ref))
        revs = [local_sha, "--not", *remote_refs, *done]
        done.append(commit)
        found.extend(scan_commits(repo, revs))                # 2. every commit that is new to the remote
        emails = _git(repo, "log", *revs, "--format=%ae%n%ce").decode("utf-8", "replace").split()
        for addr in sorted(set(emails)):
            if not email_allowed(addr):
                found.append(Finding("commit", "(commit 作者／提交者)", 0, "個人信箱",
                                     f"{addr.split('@')[0][:1]}…@{addr.rpartition('@')[2]}"))
        named = {}
        for row in _git(repo, "rev-list", "--objects", *revs).decode("utf-8", "replace").splitlines():
            sha, _, path = row.partition(" ")
            if path and sha not in seen_blobs:
                named.setdefault(sha, path)
        for path in sorted(set(named.values())):
            found.extend(path_findings("history", path))
        seen_blobs.update(named)
        found.extend(_scan_blobs(repo, "history", named))
        found.extend(scan_tag_messages(repo, [local_sha]))   # 3. an annotated tag's own message
    return sorted(set(found))


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


def _warn_no_terms() -> None:
    print(NO_TERMS_WARNING, file=sys.stderr)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning::{NO_TERMS_WARNING}")


def main(argv: Optional[List[str]] = None, stdin_text: Optional[str] = None) -> int:
    parser = argparse.ArgumentParser(description="公開前檢查：密鑰、本機路徑、個人信箱、私人詞、敏感檔名（工作樹＋git 歷史）")
    parser.add_argument("--repo", default=ROOT, help="要檢查的 git repo（預設：這個 SYNOX）")
    parser.add_argument("--worktree-only", action="store_true", help="只看目前的檔案，不看 git 歷史")
    parser.add_argument("--terms", help="私人詞清單的檔案（預設：$SYNOX_PRIVATE_TERMS，或 .git/info/synox-private-terms.txt）")
    parser.add_argument("--pre-push", metavar="REMOTE", help="給 git pre-push hook 用：stdin 讀要推的 ref，檢查整棵樹與每個新 commit")
    parser.add_argument("--allow-no-terms", action="store_true", help="沒有私人詞清單也照樣檢查其他項目（會大聲警告）")
    parser.add_argument("url", nargs="?", help=argparse.SUPPRESS)      # pre-push passes the remote URL too
    args = parser.parse_args(argv)
    try:
        _git(args.repo, "rev-parse", "--git-dir")
        terms = load_terms(args.repo, args.terms)
    except (RuntimeError, OSError, ValueError) as e:
        print(f"沒辦法檢查：{e}", file=sys.stderr)
        return 2
    set_terms(terms)
    if terms is None:
        _warn_no_terms()
        if args.pre_push and not args.allow_no_terms:
            print("推送前檢查：沒有私人詞清單，先擋下這次推送（確定要推就加 --allow-no-terms，或先放好清單）。", file=sys.stderr)
            return 2
    try:
        if args.pre_push:
            findings = scan_push(args.repo, args.pre_push, sys.stdin.read() if stdin_text is None else stdin_text)
        else:
            findings = scan_worktree(args.repo)
            if not args.worktree_only:
                findings += scan_history(args.repo)
    except (RuntimeError, OSError) as e:
        print(f"沒辦法檢查：{e}", file=sys.stderr)
        return 2
    finally:
        set_terms(None)
    text = report(findings, history=not args.worktree_only)
    if args.pre_push:
        text = text.replace("目前的檔案（要在公開前修掉）", "要推出去的版本（整棵樹）").replace(
            "git 歷史（舊版本裡有；要不要改寫歷史由維護者決定）", "這次要推的 commit 帶進來的檔案")
    text += f"\n私人詞清單：{terms.source}（{terms.count} 筆）" if terms else "\n私人詞清單：沒有（私人詞沒有檢查）"
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
