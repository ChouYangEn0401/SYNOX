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
