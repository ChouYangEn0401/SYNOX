# -*- coding: utf-8 -*-
from synox.packs import render


def test_message_wins():
    assert render.render({"ok": True, "message": "記下了", "result": [1, 2]}) == "記下了"
    assert render.render({"text": "  hi  "}) == "hi"


def test_envelope_with_single_list_is_unwrapped_and_listed():
    out = render.render({"ok": True, "result": [
        {"id": "jot", "name": "隨手記", "minutes": 2, "tags": ["快速"]},
        {"id": "three-part", "name": "三段式", "minutes": 10},
    ]})
    lines = out.splitlines()
    assert lines[0].startswith("1. ") and "隨手記" in lines[0] and "jot" in lines[0] and "minutes=2" in lines[0]
    assert lines[1].startswith("2. ") and "三段式" in lines[1]


def test_dict_becomes_key_value_lines_and_lists_are_items():
    out = render.render({"month": "2026-11", "total": 185, "by_category": [{"name": "食", "amount": 185}], "ok": True})
    assert "month：2026-11" in out and "total：185" in out
    assert "by_category：" in out and "• 食（amount=185）" in out


def test_long_lists_are_capped():
    out = render.render(list(range(40)))
    assert out.count("\n") == render.MAX_LINES and out.endswith("…還有 15 項")


def test_empty_and_scalars():
    assert render.render(None) == "（沒有內容）"
    assert render.render([]) == "（沒有內容）"
    assert render.render("ok") == "ok"
    assert render.render(3.0) == "3"
