"""scripts/prepublish_check.py：對暫存 git repo 跑（不連網、不執行 repo 裡的任何東西）。
假密鑰都在執行時拼出來，這個檔本身不會被檢查器抓到。"""

import importlib.util
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("prepublish_check", os.path.join(ROOT, "scripts", "prepublish_check.py"))
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

FAKE = {
    "Telegram": "123456789:" + "A" * 35,
    "sk": "sk-" + "a1B2" * 6,
    "AIza": "AIza" + "x" * 35,
    "GOCSPX": "GOCSPX-" + "y" * 24,
    "xox": "xoxb-" + "1234567890-abc",
    "ghp": "ghp_" + "z" * 36,
    "AKIA": "AKIA" + "Q" * 16,
    "key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "ntn": "ntn_" + "n" * 40,
    "discord": "M" + "a" * 25 + "." + "GaBcDe" + "." + "b" * 30,
}


def git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args], check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def kinds(findings, where=None):
    return {f.kind for f in findings if where is None or f.where == where}


@pytest.mark.parametrize("name", sorted(FAKE))
def test_each_secret_kind_is_found(name):
    hits = pc.scan_text(f"x = '{FAKE[name]}'\n")
    assert hits and all(k.startswith("疑似密鑰") for _n, k in hits), name


def test_clean_text_and_placeholders_pass():
    text = "\n".join([
        r"C:\Users\<你的帳號>\SYNOX", r"C:\Users\Public\x", "C:/Users/%USERNAME%/a", "/Users/you/SYNOX", "/home/<name>/x",
        "noreply@anthropic.com", "me@icloud.com", "p@mcp.test.invalid", "a@example.com", "git@github.com",
        "react@18.3.1", "@BotFather", "sk-short", "AKIA-not", "Todoist P1",
    ])
    assert pc.scan_text(text) == []


def test_local_paths_and_personal_email_found():
    hits = pc.scan_text("a = r'C:\\Users\\alice2\\Documents\\x'\nb = '/Users/carol/x'\nc = 'dan.lee@gmail.com'\n")  # prepublish-check: allow
    assert hits == [(1, "本機絕對路徑（含使用者名稱）"), (2, "本機絕對路徑（含使用者名稱）"), (3, "個人信箱")]
    assert pc.scan_text("C:\\\\Users\\\\erin\\\\x\n") == [(1, "本機絕對路徑（含使用者名稱）")]   # escaped in source code  prepublish-check: allow


def test_allow_marker_skips_line():
    assert pc.scan_text(f"t = '{FAKE['ghp']}'  # {pc.ALLOW_MARK}\n") == []


def test_sensitive_names():
    for bad in (".env", "a/.env.local", "config.json", "data/packs.lock", "x/notes.json.enc", "id_ed25519", "k.pem"):
        assert pc.sensitive_name(bad), bad
    for ok in ("config.example.json", ".env.example", "pack.json", "docs/security.md"):
        assert not pc.sensitive_name(ok), ok


def test_clean_repo_exits_zero(tmp_path, capsys):
    repo = make_repo(tmp_path, {"README.md": "hello\n", "config.example.json": "{}\n"})
    assert pc.main(["--repo", str(repo)]) == 0
    assert "沒有發現問題" in capsys.readouterr().out


def test_worktree_findings_report_location_not_content(tmp_path, capsys):
    secret = FAKE["Telegram"]
    repo = make_repo(tmp_path, {"a.py": f"\nTOKEN = '{secret}'\n", "config.json": "{}\n"})
    assert pc.main(["--repo", str(repo), "--worktree-only"]) == 1
    out = capsys.readouterr().out
    assert "a.py:2" in out and "Telegram bot token" in out and "config.json" in out and "敏感檔名" in out
    assert secret not in out and secret.split(":")[1] not in out


def test_untracked_but_not_ignored_files_are_checked(tmp_path):
    repo = make_repo(tmp_path, {"README.md": "x\n", ".gitignore": "ignored.txt\n"})
    (repo / "new.txt").write_text(FAKE["AKIA"], encoding="utf-8")
    (repo / "ignored.txt").write_text(FAKE["AKIA"], encoding="utf-8")
    paths = {f.path for f in pc.scan_worktree(str(repo))}
    assert paths == {"new.txt"}


def test_history_finds_removed_secret_file_and_path(tmp_path, capsys):
    repo = make_repo(tmp_path, {"README.md": "x\n", "notes.md": "see C:\\Users\\frank\\Documents\\proj\n",  # prepublish-check: allow
                                ".env": "K=" + FAKE["sk"] + "\n"})
    (repo / "notes.md").write_text("see <你的資料夾>\n", encoding="utf-8")
    os.remove(repo / ".env")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "clean")
    assert kinds(pc.scan_worktree(str(repo))) == set()
    hist = pc.scan_history(str(repo))
    assert {(f.path, f.kind) for f in hist} == {
        (".env", "敏感檔名（曾經提交過）"),
        (".env", "疑似密鑰：OpenAI／Anthropic 金鑰（sk-…）"),
        ("notes.md", "本機絕對路徑（含使用者名稱）"),
    }
    assert pc.main(["--repo", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "git 歷史" in out and "notes.md:1" in out and FAKE["sk"] not in out and "frank" not in out


def test_history_includes_other_branches(tmp_path):
    repo = make_repo(tmp_path, {"README.md": "x\n"})
    git(repo, "checkout", "-q", "-b", "side")
    (repo / "k.txt").write_text(FAKE["GOCSPX"], encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "side")
    git(repo, "checkout", "-q", "-")
    assert [(f.path, f.line) for f in pc.scan_history(str(repo))] == [("k.txt", 1)]


def test_commit_author_email_checked_and_masked(tmp_path, capsys):
    repo = make_repo(tmp_path, {"README.md": "x\n"})
    env = {**os.environ, "GIT_AUTHOR_NAME": "p", "GIT_COMMITTER_NAME": "p",
           "GIT_AUTHOR_EMAIL": "private.person@gmail.com", "GIT_COMMITTER_EMAIL": "t@example.com"}  # prepublish-check: allow
    (repo / "b.txt").write_text("y\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-q", "-m", "b"], check=True, env=env)
    found = [f for f in pc.scan_history(str(repo)) if f.where == "commit"]
    assert len(found) == 1 and found[0].kind == "個人信箱"
    pc.main(["--repo", str(repo)])
    out = capsys.readouterr().out
    assert "private.person" not in out and "gmail.com" in out


def test_not_a_repo_exits_two(tmp_path):
    assert pc.main(["--repo", str(tmp_path)]) == 2


def test_binary_files_are_skipped(tmp_path):
    repo = make_repo(tmp_path, {"README.md": "x\n"})
    (repo / "blob.bin").write_bytes(b"\0\1" + FAKE["AKIA"].encode())
    assert pc.scan_worktree(str(repo)) == []


# ---- private terms (the maintainer's list lives outside the repo) and the pre-push mode ----------------------

TERM = "Zq" + "xprivproj"            # made up at run time, so this file never contains the "private" word itself


@pytest.fixture(autouse=True)
def _no_terms_from_the_environment(monkeypatch):
    """A maintainer's own list (env vars) must not leak into these temp-repo tests."""
    monkeypatch.delenv(pc.TERMS_ENV, raising=False)
    monkeypatch.delenv(pc.TERMS_TEXT_ENV, raising=False)


def write_terms(repo, text=None):
    common = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            stdout=subprocess.PIPE, check=True).stdout.decode().strip()
    path = os.path.join(common, "info", pc.TERMS_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if text is not None else f"# @category: private_project\n{TERM}\nre:(?i)secret[-_]?thing\n")
    return path


def test_terms_found_in_files_paths_history_and_messages_without_printing_them(tmp_path, capsys):
    repo = make_repo(tmp_path, {"README.md": f"made with {TERM.lower()}\n", f"docs/{TERM}-notes.md": "x\n"})
    (repo / "old.md").write_text("from secret_thing\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"talk about {TERM}")
    os.remove(repo / "old.md")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "drop it")
    write_terms(repo)
    assert pc.main(["--repo", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "README.md:1" in out and "old.md:1" in out and "的訊息" in out and "檔名含私人詞" in out
    assert TERM.lower() not in out.lower() and "secret_thing" not in out
    assert "synox-private-terms.txt（2 筆）" in out


def test_without_terms_normal_run_warns_loudly(tmp_path, capsys):
    repo = make_repo(tmp_path, {"README.md": f"{TERM}\n"})
    assert pc.main(["--repo", str(repo), "--worktree-only"], ) == 0
    cap = capsys.readouterr()
    assert "沒有私人詞清單" in cap.err and "私人詞沒有檢查" in cap.out


def test_terms_from_env_text_and_missing_file_is_an_error(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, {"README.md": f"{TERM}\n"})
    monkeypatch.setenv(pc.TERMS_TEXT_ENV, TERM)
    assert pc.main(["--repo", str(repo), "--worktree-only"]) == 1
    monkeypatch.setenv(pc.TERMS_ENV, str(tmp_path / "nope.txt"))
    assert pc.main(["--repo", str(repo), "--worktree-only"]) == 2


def _push_lines(repo, ref="refs/heads/main"):
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], stdout=subprocess.PIPE, check=True).stdout.decode().strip()
    return f"{ref} {sha} {ref} {pc.ZERO}\n"


def test_pre_push_refuses_without_terms(tmp_path, capsys):
    repo = make_repo(tmp_path, {"README.md": "x\n"})
    assert pc.main(["--repo", str(repo), "--pre-push", "origin"], stdin_text=_push_lines(repo)) == 2
    assert "擋下" in capsys.readouterr().err
    assert pc.main(["--repo", str(repo), "--pre-push", "origin", "--allow-no-terms"], stdin_text=_push_lines(repo)) == 0


def test_pre_push_scans_the_whole_tree_not_only_the_new_commit(tmp_path, capsys):
    """An old file that the pushed commit does not touch is still checked (the bug this mode exists for)."""
    upstream = tmp_path / "up.git"
    subprocess.run(["git", "init", "-q", "--bare", str(upstream)], check=True)
    repo = make_repo(tmp_path, {"old.md": f"{TERM}\n", "README.md": "x\n"})
    git(repo, "remote", "add", "origin", str(upstream))
    git(repo, "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main")
    git(repo, "fetch", "-q", "origin")
    (repo / "README.md").write_text("y\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "clean change")
    write_terms(repo)
    assert pc.main(["--repo", str(repo), "--pre-push", "origin"], stdin_text=_push_lines(repo)) == 1
    out = capsys.readouterr().out
    assert "old.md:1" in out and "要推出去的版本" in out and TERM not in out


def test_pre_push_checks_new_commit_messages_and_deleted_files(tmp_path, capsys):
    repo = make_repo(tmp_path, {"README.md": "x\n"})
    (repo / "tmp.md").write_text(f"{TERM}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add")
    os.remove(repo / "tmp.md")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"remove {TERM}")
    write_terms(repo)
    assert pc.main(["--repo", str(repo), "--pre-push", "origin"], stdin_text=_push_lines(repo)) == 1
    out = capsys.readouterr().out
    assert "tmp.md:1" in out and "的訊息" in out and TERM not in out


def test_pre_push_clean_push_passes_and_deletes_are_ignored(tmp_path):
    repo = make_repo(tmp_path, {"README.md": "x\n"})
    write_terms(repo)
    assert pc.main(["--repo", str(repo), "--pre-push", "origin"], stdin_text=_push_lines(repo)) == 0
    assert pc.main(["--repo", str(repo), "--pre-push", "origin"],
                   stdin_text=f"(delete) {pc.ZERO} refs/heads/x {'1' * 40}\n") == 0


def test_no_term_list_is_committed_in_this_repo():
    """The list must never be in the public repo; only the hook and the checker are."""
    tracked = subprocess.run(["git", "-C", ROOT, "ls-files"], stdout=subprocess.PIPE, check=True).stdout.decode("utf-8", "replace")
    names = {p.rsplit("/", 1)[-1].lower() for p in tracked.splitlines()}
    assert pc.TERMS_FILE not in names and not any("terms" in n and n.endswith(".txt") for n in names)
    hook = os.path.join(ROOT, "scripts", "hooks", "pre-push")
    with open(hook, encoding="utf-8") as f:
        assert "--pre-push" in f.read()
