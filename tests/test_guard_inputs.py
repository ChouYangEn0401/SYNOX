"""門禁核心：輸入的基本檢查（ADR 0025 §4、ADR 0026 §5）。只擋、不改字；錯誤訊息裡沒有輸入。"""

import pytest

from synox.guard import inputs
from synox.guard.inputs import Bad

pytestmark = pytest.mark.usefixtures("no_sockets")

# ADR 0026 §5 模糊測試清單裡的路徑
BAD_PATHS = ["/../", "/..%2f", "/%2e%2e/", "/.%2e/", "/%252e%252e/", "/..;/", "//etc/passwd", "/\\..\\", "/C:/",
             "/app/../../config.json", "/a%00b", "/a\x00b", "/．．／", "/e\u0301", "/a\u202eb", "/\ud800",
             "http://evil/", "", "/", "/a//b", "/.env", "/a/", "/" + "a" * 2050, "/a b", "/a?x=1"]


@pytest.mark.parametrize("value,code", [
    ("x" * 2001, "long"), ("a\x00b", "nul"), ("a\x1bb", "control"), ("a\nb", "control"), ("\ud800", "encoding"),
    ("a\u202eb", "bidi"), ("a\u2066b", "bidi"), ("a\x85b", "control"), (5, "type"), (None, "type"),
])
def test_text_rejects(value, code):
    with pytest.raises(Bad) as e:
        inputs.text(value)
    assert e.value.code == code
    assert e.value.text == inputs.TEXT[code]
    if isinstance(value, str) and value.strip("\x00\x1b\n\x85"):
        assert value not in e.value.text


@pytest.mark.parametrize("value", ["午餐 跟同事", "咖啡 ☕ 🎉", "ＡＢＣ　全形", "x" * 2000, "", "tab\tok"])
def test_text_passes_unchanged(value):
    if "\t" in value:
        assert inputs.text(value, multiline=True) == value
    else:
        assert inputs.text(value) is value


def test_multiline_keeps_newlines():
    assert inputs.text("a\nb\r\nc\t", multiline=True) == "a\nb\r\nc\t"
    with pytest.raises(Bad):
        inputs.text("a\x07", multiline=True)


def test_values():
    assert inputs.values(["a", "b"], {"a": "1"}) == {"a": "1"}
    for raw, code in [({"zz": "1"}, "field"), ({f"k{i}": "1" for i in range(21)}, "many"), ({"a": 1}, "type"),
                      ("a=1", "type")]:
        with pytest.raises(Bad) as e:
            inputs.values(["a", "b"] + [f"k{i}" for i in range(21)], raw)
        assert e.value.code == code


@pytest.mark.parametrize("body,code", [
    (b'{"a":1,"a":2}', "dupkey"), (b'{"a":{"b":{"c":{"d":{"e":1}}}}}', "deep"), (b"[1,2]", "json"),
    (b"\xff\xfe", "encoding"), (b'{"a":"' + b"x" * 70000 + b'"}', "long"), (b"{nope", "json"),
    (b'{"a": NaN}', "json"), (b'{"a":"\\u0000"}', "nul"), (b"{\"a\":" * 2000 + b"1" + b"}" * 2000, "deep"),
])
def test_json_object_rejects(body, code):
    with pytest.raises(Bad) as e:
        inputs.json_object(body, max_bytes=65536)
    assert e.value.code == code


def test_json_object_deep_recursion():
    body = b'{"a":' * 5000 + b"1" + b"}" * 5000
    with pytest.raises(Bad) as e:
        inputs.json_object(body, max_bytes=1 << 20)
    assert e.value.code == "deep"


def test_json_object_ok():
    assert inputs.json_object(b'{"a": {"b": ["c", 1]}, "t": "\xe4\xb8\xad\\n"}') == {"a": {"b": ["c", 1]}, "t": "中\n"}


@pytest.mark.parametrize("raw", BAD_PATHS)
def test_rel_path_rejects(raw):
    with pytest.raises(Bad) as e:
        inputs.rel_path(raw)
    assert e.value.code == "path"


def test_rel_path_ok():
    assert inputs.rel_path("/app.js") == "app.js"
    assert inputs.rel_path("/img/a.png") == "img/a.png"
    assert inputs.rel_path("app.js") == "app.js"


def test_money_add_with_nul_is_refused_with_the_fixed_sentence(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/money 80 咖啡 a\x00b")
    assert bot.last(owner) == "❌ " + inputs.TEXT["nul"]
    bot.say(owner, "/money_list")
    assert "咖啡" not in bot.last(owner)
    bot.say(owner, "/money 80 咖啡 跟同事")
    assert "記了：咖啡 80 元" in bot.last(owner)


def test_guard_modules_do_not_import_synox():
    import os
    import synox.guard as g
    folder = os.path.dirname(g.__file__)
    for name in ("origin.py", "inputs.py", "limits.py", "audit.py"):
        lines = open(os.path.join(folder, name), encoding="utf-8").read().splitlines()
        assert not [x for x in lines if x.startswith(("import synox", "from synox"))], name
