from synox.llm import textproto
from synox.llm.base import ToolSpec


def test_plain_json():
    call, rest = textproto.parse('{"tool": "money__add", "args": {"amount": "80", "category": "咖啡"}}')
    assert call.name == "money__add" and call.args == {"amount": "80", "category": "咖啡"} and rest == ""


def test_fenced_block_with_prose():
    text = '好的，我來記：\n```json\n{"tool": "note__add", "args": {"text": "買牛奶"}}\n```\n記好了'
    call, rest = textproto.parse(text)
    assert call.name == "note__add" and call.args["text"] == "買牛奶"
    assert "好的" in rest and "記好了" in rest


def test_prose_around_without_fence():
    call, rest = textproto.parse('我會呼叫 {"tool": "money__month", "args": {}} 這個工具。')
    assert call.name == "money__month" and rest == "我會呼叫  這個工具。"


def test_aliases_and_string_args():
    call, _ = textproto.parse('{"name": "money__add", "arguments": "{\\"amount\\": \\"5\\"}"}')
    assert call.name == "money__add" and call.args == {"amount": "5"}
    call, _ = textproto.parse('{"tool_name": "x__y", "parameters": {"a": "1"}}')
    assert call.name == "x__y" and call.args == {"a": "1"}


def test_braces_inside_strings_and_earlier_non_tool_object():
    text = '先看 {"note": "不是工具"}，再 {"tool": "note__add", "args": {"text": "a {b} c"}}'
    call, _ = textproto.parse(text)
    assert call.name == "note__add" and call.args["text"] == "a {b} c"


def test_no_tool():
    for text in ("今天天氣很好", '{"tool": 3}', "{壞掉的 json", "", '```json\n{"a": 1}\n```'):
        call, rest = textproto.parse(text)
        assert call is None


def test_snippet_lists_tools():
    spec = ToolSpec("money__add", "記一筆", {"type": "object", "properties": {"amount": {"description": "金額"}},
                                              "required": ["amount"]})
    snippet = textproto.system_snippet([spec])
    assert "money__add" in snippet and "amount（必填）" in snippet and '{"tool":' in snippet
