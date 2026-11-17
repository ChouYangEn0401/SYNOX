# -*- coding: utf-8 -*-
"""給 AI 的結構化結果（核心合一規劃 11.6；SDK 0.2.4 的信封 "ai"）：
SDK 印得出 "ai"、精簡 JSON 一定合法而且在上限內、人看到的跟以前一樣。不連網、不開埠、不叫真的 AI。"""
import io
import json

import pytest

from synox.agent import structured
from synox.packs import render
from synox.sdk import author, reply_ok
from synox.sdk.author import Ok, tool

from conftest import OWNER_ID

pytestmark = pytest.mark.usefixtures("no_sockets")


# ── SDK ───────────────────────────────────────────────────────────────

def _last(out: io.StringIO) -> dict:
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_sdk_ok_with_ai_field():
    @tool("READ")
    def rows():
        """列出。"""
        return Ok("共 2 筆", [{"id": 1}, {"id": 2}], ai={"count": 2, "ids": [1, 2]})

    out = io.StringIO()
    assert author.run_cli(["rows", "--json"], out=out, tools=[rows]) == 0
    env = _last(out)
    assert env == {"ok": True, "message": "共 2 筆", "data": [{"id": 1}, {"id": 2}], "ai": {"count": 2, "ids": [1, 2]}}


def test_sdk_ok_without_ai_is_unchanged():
    @tool("READ")
    def one():
        """一筆。"""
        return Ok("共 1 筆", {"count": 1})

    out = io.StringIO()
    author.run_cli(["one", "--json"], out=out, tools=[one])
    assert _last(out) == {"ok": True, "message": "共 1 筆", "data": {"count": 1}}      # 沒給 ai＝沒有這個鍵


def test_reply_ok_ai_keyword():
    out = io.StringIO()
    reply_ok({"n": 1}, "好", ai={"n": 1, "why": "x"}, out=out)
    assert _last(out)["ai"] == {"n": 1, "why": "x"}


def test_sdk_version_bumped_patch_only():
    assert author.SDK_VERSION == "0.2.4"
    assert author.SDK_REQUIRES == ">=0.2,<0.3"            # 只加不改：範圍不變，舊工具照樣裝得上


# ── 信封 → 兩份 ────────────────────────────────────────────────────────

def test_payload_prefers_ai_then_data():
    assert structured.payload_of({"ok": True, "data": [1], "ai": {"a": 1}}) == (True, {"a": 1})
    assert structured.payload_of({"ok": True, "data": [1]}) == (True, [1])
    assert structured.payload_of({"ok": True, "message": "好"}) == (False, None)
    assert structured.payload_of("x") == (False, None)


def test_people_never_see_the_ai_field():
    env = {"ok": True, "data": {"count": 3}, "ai": {"secret_plan": "只給 AI"}}
    shown = render.render(structured.for_people(env))
    assert shown == render.render({"ok": True, "data": {"count": 3}})
    assert "secret_plan" not in shown
    with_message = {"ok": True, "message": "共 3 筆", "data": [1, 2, 3], "ai": {"n": 3}}
    assert render.render(structured.for_people(with_message)) == "共 3 筆"


# ── 精簡 JSON ──────────────────────────────────────────────────────────

def test_compact_small_is_verbatim():
    value = {"date": "2026-01-02", "items": [1, 2, 3], "ok": True, "x": None, "f": 1.5}
    assert json.loads(structured.compact(value, 4000)) == value


@pytest.mark.parametrize("limit", [60, 120, 300, 1000, 3000])
def test_compact_always_valid_and_within_limit(limit):
    big = {"rows": [{"id": i, "title": "標題" * 20, "tags": ["a", "b", "c"] * 5,
                     "nested": {"deep": {"deeper": {"deepest": list(range(30))}}}} for i in range(200)],
           "note": "長" * 5000, "nan": float("nan"), "set": {1, 2}}
    text = structured.compact(big, limit)
    assert len(text) <= limit
    json.loads(text)                                         # 一定讀得回來


def test_compact_list_keeps_head_and_counts_the_rest():
    text = structured.compact(list(range(1000)), 200)
    data = json.loads(text)
    assert data[0] == 0 and data[-1].get("_more") == 1000 - (len(data) - 1)


def test_compact_tiny_limit_still_json():
    for limit in (2, 5, 20):
        text = structured.compact({"a": "b" * 100}, limit)
        assert len(text) <= max(2, limit)
        json.loads(text)


def test_compose_message_plus_json_within_limit():
    text = structured.compose("共 200 筆", [{"id": i, "name": "x" * 30} for i in range(200)], 500)
    assert text.startswith("共 200 筆\n" + structured.LABEL)
    assert len(text) <= 500
    assert isinstance(structured.parse(text), list)


def test_compose_long_message_is_cut_before_json():
    text = structured.compose("字" * 2000, {"a": 1}, 400)
    assert len(text) <= 400
    assert structured.parse(text) == {"a": 1}


def test_scrub_masks_keys_and_values():
    value = {"token_abcdefgh12": ["x token_abcdefgh12 y", 3]}
    out = structured.scrub(value, ["token_abcdefgh12"])
    assert "token_abcdefgh12" not in json.dumps(out, ensure_ascii=False)
    assert value == {"token_abcdefgh12": ["x token_abcdefgh12 y", 3]}      # 原本的不改


# ── 整支 bot：kind=cli 經 AI 呼叫 ──────────────────────────────────────────

TOOL_SRC = r'''"""結構化結果測試用的工具。"""
from synox_sdk import Ok, serve, tool


@tool("READ")
def rows(n: int = 3):
    """列出幾筆。"""
    data = [{"id": i, "title": f"第 {i} 筆", "amount": i * 10} for i in range(1, n + 1)]
    return Ok(f"共 {n} 筆", data, ai={"count": n, "total": sum(r["amount"] for r in data)})


@tool("READ")
def raw(n: int = 3):
    """只回資料，沒有 message。"""
    return [{"id": i, "title": "標題" * 10} for i in range(1, n + 1)]


if __name__ == "__main__":
    serve()
'''


def _pack(tmp_path):
    from synox import sdk
    folder = tmp_path / "packs" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tool.py").write_text(TOOL_SRC, encoding="utf-8")
    sdk.write_single_file(str(folder / "synox_sdk.py"))
    sdk.init_from(str(folder / "tool.py"), "demo", "示範")
    return folder


def _tool_text(bot) -> str:
    from synox.agent import delimit
    from synox.llm.base import TOOL
    messages, _tools = bot.app.extras["synox_agent"].adapter.calls[-1]
    content = [m for m in messages if m.role == TOOL][-1].content
    return delimit.unwrap(content)[1]


def test_ai_gets_message_plus_ai_json(make_bot, tmp_path):
    folder = _pack(tmp_path)
    bot = make_bot([{"tool": "demo__rows", "args": {"n": "3"}}, "好了"], pack_dirs=(str(folder.parent),))
    bot.talk(OWNER_ID, "列出來")
    text = _tool_text(bot)
    assert text.startswith("共 3 筆\n" + structured.LABEL)
    assert structured.parse(text) == {"count": 3, "total": 60}             # ai 那一份，不是 data
    assert not any("count" in t for t in bot.texts(OWNER_ID))              # 給人的東西沒有混進去


def test_people_see_the_same_as_before(make_bot, tmp_path):
    folder = _pack(tmp_path)
    bot = make_bot(pack_dirs=(str(folder.parent),))
    bot.say(OWNER_ID, "/demo_rows 3")
    bot.app.tasks.wait(30)
    assert bot.last(OWNER_ID) == "共 3 筆"
    bot.say(OWNER_ID, "/demo_raw")
    bot.app.tasks.wait(30)
    expected = render.render({"ok": True, "data": [{"id": i, "title": "標題" * 10} for i in (1, 2, 3)]})
    assert bot.last(OWNER_ID) == expected                                   # 沒有 message：照舊攤平


def test_ai_json_is_capped_by_tool_result_chars(make_bot, tmp_path):
    folder = _pack(tmp_path)
    llm = {"kind": "fake", "tool_result_chars": 400}
    bot = make_bot([{"tool": "demo__raw", "args": {"n": "300"}}, "好了"], llm=llm, pack_dirs=(str(folder.parent),))
    bot.talk(OWNER_ID, "全部列出來")
    text = _tool_text(bot)
    assert len(text) <= 400
    data = structured.parse(text)                                            # 合法 JSON
    assert isinstance(data, list) and data[-1]["_more"] == 300 - (len(data) - 1)
    assert data[0]["id"] == 1


def test_without_payload_ai_text_is_unchanged(make_bot):
    """python pack（fixture 的 money）沒有交結構化結果：AI 拿到的跟以前一樣。"""
    from synox.llm.base import TOOL
    bot = make_bot([{"tool": "money__add", "args": {"amount": "80", "category": "咖啡"}}, "記好了"])
    bot.talk(OWNER_ID, "記 80 咖啡")
    messages, _ = bot.app.extras["synox_agent"].adapter.calls[1]
    content = [m for m in messages if m.role == TOOL][0].content
    assert structured.LABEL not in content and "記了：咖啡 80 元" in content
