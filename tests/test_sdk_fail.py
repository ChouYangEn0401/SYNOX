# -*- coding: utf-8 -*-
"""SDK 0.2.1 的失敗信封 v1：`fail()` 丟 `ToolFailure`（`ToolError` 的子類別）、印 v1 信封；不在表上的碼＝unclassified；
舊的 `ToolError` 信封一個字都不變；MCP 模式 isError＋structuredContent（不帶 diag）。只在程序內跑，不開子程序。"""
import io
import json

import pytest

from synox.sdk import author


def _tools():
    @author.tool("READ")
    def broken():
        """壞的。"""
        author.fail("upstream_changed", "格式變了",
                    remedy={"kind": "needs_update", "id": "upgrade", "summary": "要換成 1.3.0 以上的版本。"},
                    diag={"tool_version": "1.2.0", "upstream": "KeyError: 'price'"})

    @author.tool("READ")
    def limited():
        """限流。"""
        author.fail("rate_limited", "太快了", retry_after=30, scope="environment")

    @author.tool("READ")
    def odd():
        """怪碼。"""
        author.fail("my_own_code", "怪")

    @author.tool("READ")
    def old():
        """舊的。"""
        try:
            author.fail("not_found", "沒有")
        except author.ToolError as e:                     # 舊的 except ToolError 照樣接得到
            raise author.ToolError(e.code, e.message)

    @author.tool("READ")
    def typo():
        """作者寫錯 scope。"""
        author.fail("timeout", "慢", scope="everywhere")

    return [broken, limited, odd, old, typo]


def _cli(name):
    out = io.StringIO()
    code = author.run_cli([name, "--json"], out=out, tools=_tools())
    return code, json.loads(out.getvalue())


def test_version_and_class_hierarchy():
    assert issubclass(author.ToolFailure, author.ToolError)
    assert author.SDK_VERSION == "0.2.1" and author.SDK_REQUIRES == ">=0.2,<0.3"     # 只加 API：範圍不變
    assert "fail" in author.__all__ and "ToolFailure" in author.__all__
    assert set(author.FAILURE_SCOPES) == {"input", "user", "tool", "pack", "environment"}
    assert "unclassified" in author.FAILURE_CODES and len(author.FAILURE_CODES) == 18
    with pytest.raises(author.ToolFailure) as e:
        author.fail("timeout", "x" * 400)
    assert len(e.value.message) == 300 and e.value.code == "timeout" and e.value.failure == {"v": 1}


def test_fail_envelopes():
    assert _cli("broken") == (1, {
        "ok": False, "error": "格式變了", "code": "upstream_changed",
        "failure": {"v": 1, "remedy": {"kind": "needs_update", "id": "upgrade", "summary": "要換成 1.3.0 以上的版本。"},
                    "diag": {"tool_version": "1.2.0", "upstream": "KeyError: 'price'"}}})
    code, env = _cli("limited")
    assert env["failure"] == {"v": 1, "scope": "environment", "retry": {"ok": True, "after_s": 30}}
    code, env = _cli("odd")
    assert env["code"] == "unclassified" and env["failure"]["diag"] == {"code": "my_own_code"}
    assert _cli("old") == (1, {"ok": False, "error": "沒有", "code": "not_found"})      # 舊 API 不變
    code, env = _cli("typo")                                                     # 作者用錯 fail()：沒處理的例外
    assert code == 1 and env["code"] == "unclassified" and env["failure"]["diag"] == {"exception": "ValueError"}


def test_diag_is_capped():
    with pytest.raises(author.ToolFailure) as e:
        author.fail("timeout", "x", diag={f"k{i}": "值" * 500 for i in range(20)})
    diag = e.value.failure["diag"]
    assert all(len(v) <= 200 for v in diag.values())
    assert len(json.dumps(diag, ensure_ascii=False).encode("utf-8")) <= 1024


def test_mcp_failure_is_structured_without_diag(capsys):
    reqs = "\n".join(json.dumps(m) for m in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "broken", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "old", "arguments": {}}})) + "\n"
    out = io.StringIO()
    author.run_mcp(io.StringIO(reqs), out, tools=_tools())
    replies = [json.loads(line)["result"] for line in out.getvalue().splitlines()[1:]]
    broken, old = replies
    assert broken["isError"] is True and broken["content"][0]["text"] == "格式變了"
    sc = broken["structuredContent"]
    assert sc["code"] == "upstream_changed" and sc["failure"]["remedy"]["id"] == "upgrade"
    assert "diag" not in sc["failure"]                                         # 別的 MCP 用戶端可能把它給 AI
    assert "KeyError" in capsys.readouterr().err                                # diag 改印到 server 的 stderr
    assert old["structuredContent"] == {"ok": False, "error": "沒有", "code": "not_found"}
