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
