# -*- coding: utf-8 -*-
"""SDK P8（文件與範例）：examples/ 底下每個範例都通過 SYNOX 安裝時的第 1、2 關（`synox-sdk check`＝`sdk.Pack.load`），
有 README／pack.json／SKILL.md、程式檔有 Apache-2.0 的 SPDX 檔頭；node-mcp-tool 只驗宣告與報告（**絕不執行 Node**）；
any-language-cli（只用標準函式庫、不 import SDK）用 synox-sdk run 跑一次確認來回；給作者的文件沒有本機路徑、連結都對得到。
不連網、不開埠；子程序只有本機的 Python。"""
import ast
import io
import json
import os
import re

import pytest

from synox import sdk
from synox.packs import admin, tier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")
NAMES = sorted(n for n in os.listdir(EXAMPLES) if os.path.isfile(os.path.join(EXAMPLES, n, "pack.json")))
CODE_EXT = (".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".ps1")


def test_examples_are_all_there():
    assert {"hello", "any-language-cli", "node-mcp-tool", "mcp-remote-notion", "mcp-remote-todoist"} <= set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_every_example_passes_gates_1_and_2(name):
    folder = os.path.join(EXAMPLES, name)
    check = sdk.Pack.load(folder)                             # 第 1 關不合會丟 ValueError
    assert check.ok, check.problems
    assert "✅" in check.format()
    m = check.manifest
    assert m.publisher, "範例都要寫 publisher"
    for rel in ("README.md", "SKILL.md"):
        assert os.path.isfile(os.path.join(folder, rel)), f"{name} 少了 {rel}"
    if m.kind == "mcp":
        assert set(m.mcp["effects"]) == set(m.mcp["tools_allow"])
    else:
        assert all(c.get("effect") for c in m.commands)


@pytest.mark.parametrize("name", NAMES)
def test_example_code_files_have_spdx_apache_header(name):
    folder = os.path.join(EXAMPLES, name)
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            if f.endswith(CODE_EXT) or f == "README.md":
                with open(os.path.join(dirpath, f), "r", encoding="utf-8") as fh:
                    head = "".join(fh.readline() for _ in range(5))
                assert "SPDX-License-Identifier: Apache-2.0" in head, f"{name}/{f} 檔頭沒有 SPDX"


# ── node-mcp-tool：只驗宣告與報告，不執行 ────────────────────────────────

def test_node_mcp_tool_declaration_and_report():
    folder = os.path.join(EXAMPLES, "node-mcp-tool")
    assert not os.path.exists(os.path.join(folder, "node_modules"))      # 只用 Node 標準函式庫
    assert not os.path.exists(os.path.join(folder, "package.json"))
    m, report, hashes, problems = admin.run_gates(folder)
    assert problems == []
    assert m.kind == "mcp" and m.mcp_stdio and m.mcp["transport"] == "stdio"
    assert m.mcp["argv"] == ["{node}", "./server.js"]
    assert {"subprocess", "exec"} <= set(m.capabilities) and m.publisher == "SYNOX examples"
    assert m.mcp["tools_allow"] == ["count_words", "roll_dice"]
    assert m.mcp["effects"] == {"count_words": "READ", "roll_dice": "READ"}
    summary = admin.summary_of(m, report, hashes, problems)
    assert [(t["name"], t["effect"]) for t in summary["mcp"]["tools"]] == [("count_words", "READ"), ("roll_dice", "READ")]
    assert summary["scan"]["ok"] and summary["publisher"] == "SYNOX examples"
    assert "server.js" in summary["files"]
    # server.js 列出的 internal_stats 沒有在 tools_allow：SYNOX 不會掛它
    with open(os.path.join(folder, "server.js"), "r", encoding="utf-8") as f:
        source = f.read()
    assert "internal_stats" in source and "internal_stats" not in m.mcp["tools_allow"]
    assert "require(" in source and re.findall(r"require\(\"([^\"]+)\"\)", source) == ["readline"]   # 只有標準函式庫
    # .js 是別的語言的原始碼（掃不到內容）、{node} 是 pack 外的直譯器 → T2，安裝要輸入 publisher（只查路徑，不執行 node）
    info = tier.assess(m, report)
    assert info["tier"] == tier.T2 and info["needs_publisher"]
    assert [o["path"] for o in info["opaque"]] == ["server.js"] and "別的語言的原始碼" in info["opaque"][0]["why"]
    assert [e["program"] for e in info["external"]] == ["{node}"] and info["external"][0]["interpreter"] == "node"
    assert tier.confirm_problem(info, m, None) and tier.confirm_problem(info, m, "SYNOX examples") is None


# ── any-language-cli：不用 SDK，照協定手寫 ───────────────────────────────

def test_any_language_cli_does_not_use_the_sdk():
    path = os.path.join(EXAMPLES, "any-language-cli", "tool.py")
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not mods & {"synox", "synox_sdk"}
    import sys
    assert mods <= set(sys.stdlib_module_names), mods


def test_any_language_cli_round_trip(tmp_path):
    folder = os.path.join(EXAMPLES, "any-language-cli")

    def run(command, args, **kw):
        out = io.StringIO()
        code = sdk.run_command(folder, command, args, data_dir=str(tmp_path), out=out, **kw)
        return code, out.getvalue()

    assert run("add", ["買牛奶"])[0] == 0
    assert run("add", ["text=繳電費"])[0] == 0
    code, text = run("list", [])
    assert code == 0 and "1. 買牛奶" in text and "2. 繳電費" in text
    code, text = run("clear", [])                             # 沒按 ✅：只出確認卡，不刪
    assert code == 0 and "SYNOX 會出確認卡：要刪掉全部 2 筆" in text
    assert "2. 繳電費" in run("list", [])[1]
    code, text = run("clear", [], confirmed=True)             # 當作按了 ✅
    assert code == 0 and "刪掉了 2 筆" in text
    assert "清單是空的" in run("list", [])[1]
    stored = tmp_path / "any-language-cli" / "items.json"     # 資料在 <user_data_dir>/<pack 名>/
    assert json.loads(stored.read_text(encoding="utf-8")) == {"schema": 1, "items": []}
    assert run("add", ["-rf"])[0] == 2                        # 值以 - 開頭：SYNOX 不讓它執行
    assert not list((tmp_path).rglob("__pycache__"))


# ── 給作者的文件：乾淨、連結對得到 ────────────────────────────────────────

AUTHOR_DOCS = [os.path.join(ROOT, "docs", "tools.md"), os.path.join(ROOT, "docs", "README.md")] + [
    os.path.join(EXAMPLES, n, f) for n in ("hello", "any-language-cli", "node-mcp-tool") for f in ("README.md", "SKILL.md")]
PRIVATE = re.compile(r"[A-Za-z]:[\\/]Users[\\/]|/home/\w|[\w.+-]+@[\w-]+\.(?:com|net|org|tw)\b", re.I)  # prepublish-check: allow (fake test value)


@pytest.mark.parametrize("path", AUTHOR_DOCS, ids=lambda p: os.path.relpath(p, ROOT))
def test_author_docs_have_no_local_paths_or_emails(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    assert not PRIVATE.findall(text), PRIVATE.findall(text)


@pytest.mark.parametrize("path", AUTHOR_DOCS, ids=lambda p: os.path.relpath(p, ROOT))
def test_author_docs_relative_links_resolve(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
        if "://" in target:
            continue
        assert os.path.exists(os.path.normpath(os.path.join(os.path.dirname(path), target))), f"{path} → {target}"
