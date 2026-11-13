"""docs/advanced-install.md（給工程師的進階安裝）：連結與提到的 repo 路徑都要真的存在、指令名要是真的子指令、
沒有個人路徑。只讀檔案，不執行任何東西。"""

import os
import re

from synox import __main__ as cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "advanced-install.md")
# 別的工作同時在寫的文件：還沒進來時先不擋（進來之後就照常檢查）
PENDING = {os.path.join(ROOT, "docs", "versioning.md")}
PRIVATE = re.compile(r"[A-Za-z]:[\\/]Users[\\/]|/home/\w|[\w.+-]+@[\w-]+\.(?:com|net|org|tw)\b", re.I)  # prepublish-check: allow (fake test value)
# 反引號裡、以 repo 的這些位置開頭的才當成「repo 裡的路徑」（容器裡的 /synox/…、執行時才有的 data/… 不算）
REPO_PREFIXES = ("src/", "scripts/", "tests/", "docker/", "docs/", "sdk/", "vendor/", "examples/", ".devcontainer/")
REPO_FILES = {"Dockerfile", "docker-compose.yml", ".env.example", ".dockerignore", "requirements.txt", "pyproject.toml",
              "config.example.json", "Start.bat", "Stop.bat", "Console.bat", "Open-SYNOX.bat", "Setup.bat"}


def _text():
    with open(DOC, "r", encoding="utf-8") as f:
        return f.read()


def test_relative_links_resolve():
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", _text()):
        if "://" in target:
            continue
        path = os.path.normpath(os.path.join(os.path.dirname(DOC), target))
        if path in PENDING and not os.path.exists(path):
            continue
        assert os.path.exists(path), target


def test_backticked_repo_paths_exist():
    seen = set()
    for token in re.findall(r"`([^`\s]+)`", _text()):
        token = token.split("::", 1)[0]
        if token in REPO_FILES or token.startswith(REPO_PREFIXES):
            seen.add(token)
            assert os.path.exists(os.path.join(ROOT, token)), token
    assert {"Dockerfile", "docker-compose.yml", "src/synox/config.py", "scripts/lock_deps.py"} <= seen


def test_synox_subcommands_in_the_doc_are_real():
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main([])                                        # 沒給子指令：印 help（第一個 {…} 是全部子指令）
    commands = set(re.search(r"\{([a-z,-]+)\}", out.getvalue()).group(1).split(","))
    used = set(re.findall(r"synox (?:-q )?([a-z][a-z-]+)", _text())) - {"synox"}   # exec 要寫兩次 synox
    assert used and used <= commands, used - commands
    assert "link" not in commands, "哨兵（link）合進來了：更新 advanced-install.md 第 3 節"


def test_no_local_paths_or_emails():
    assert not PRIVATE.findall(_text())
