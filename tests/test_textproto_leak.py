"""文字裡洩漏的工具呼叫與思考段（textproto.parse_leaked／strip_think，docs/adr/0009）：純函式。"""

from synox.llm import textproto


def _one(text):
    calls, rest = textproto.parse_leaked(text)
    assert len(calls) == 1, (calls, rest)
    return calls[0], rest


def test_tool_call_json():
    call, rest = _one('好的<tool_call>{"name": "note__add", "arguments": {"text": "買貓砂"}}</tool_call>')
    assert (call.name, call.args, call.id, rest) == ("note__add", {"text": "買貓砂"}, "leak-0", "好的")


def test_qwen_xml_inside_tool_call():
    text = ("<tool_call>\n<function=remind__add>\n<parameter=time>\n08:00\n</parameter>\n"
            "<parameter=text>\n帶雨傘\n</parameter>\n</function>\n</tool_call>")
    call, rest = _one(text)
    assert call.name == "remind__add" and call.args == {"time": "08:00", "text": "帶雨傘"} and rest == ""


def test_bare_qwen_xml():
    call, _ = _one('<function=note__add><parameter=text>{"a": 1}</parameter></function>')
    assert call.args == {"text": {"a": 1}}                     # 看起來是 JSON 物件就解開（schema 模式）


def test_minimax_invoke():
    text = ('<minimax:tool_call>\n<invoke name="note__add">\n<parameter name="text">買貓砂</parameter>\n</invoke>\n'
            '</minimax:tool_call>記好了')
    call, rest = _one(text)
    assert call.name == "note__add" and call.args == {"text": "買貓砂"} and rest == "記好了"


def test_bare_json_after_a_marker():
    call, _ = _one('<tool_call> 壞掉了 </tool_call> {"tool": "money__month", "args": {}}')
    assert call.name == "money__month"


def test_broken_json_is_repaired():
    call, _ = _one("<tool_call>{'name': 'note__add', 'arguments': {'text': '買貓砂',},}</tool_call>")
    assert call.name == "note__add" and call.args == {"text": "買貓砂"}
    call, _ = _one('<tool_call>{"name": "note__add", "arguments": {"text": "x"}')           # 少了 }，也沒有閉合
    assert call.name == "note__add" and call.args == {"text": "x"}


def test_scrape_when_json_cannot_be_repaired():
    call, _ = _one('<tool_call>{"name": "note__add", "arguments": {"text": "x"} 這裡多了字 ]]</tool_call>')
    assert call.name == "note__add" and call.args == {"text": "x"}


def test_unrepairable_returns_nothing():
    assert textproto.parse_leaked("<tool_call>完全不是 JSON</tool_call>") == ([], "<tool_call>完全不是 JSON</tool_call>")


def test_calls_inside_think_are_not_parsed():
    text = '<think>也許該 <tool_call>{"name": "note__clear", "arguments": {}}</tool_call></think>好的'
    assert textproto.parse_leaked(text) == ([], "好的")
    assert textproto.parse_leaked('想一下<tool_call>{"name": "note__clear"}</think>好的') == ([], "好的")


def test_at_most_three_calls():
    one = '<tool_call>{"name": "money__month", "arguments": {}}</tool_call>'
    calls, _ = textproto.parse_leaked(one * 5)
    assert [c.id for c in calls] == ["leak-0", "leak-1", "leak-2"]


def test_strip_think_variants():
    assert textproto.strip_think("<think>想</think>答") == ("答", "想")
    assert textproto.strip_think("想很久</think>答") == ("答", "想很久")        # 模板把 <think> 放在提示裡
    assert textproto.strip_think("答<think>想到一半") == ("答", "想到一半")      # 沒有結尾
    assert textproto.strip_think("沒有思考段") == ("沒有思考段", "")


def test_has_leak_and_parse_unchanged():
    assert textproto.has_leak("x<function=a>") and not textproto.has_leak("一般的回覆")
    call, rest = textproto.parse('好的 {"tool": "money__add", "args": {"amount": "5"}} 記好了')
    assert call.name == "money__add" and rest == "好的  記好了"
