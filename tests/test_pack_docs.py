"""pack.json 給網頁工具頁與 AI 看的說明欄位：category、commands[].summary、fields[] 的 ask／help／required／default
（安裝時 strict 檢查型別、載入時寬鬆），以及說明不齊的提醒（doc_warnings，不擋）。只用 tmp 裡的宣告，不執行任何程式。"""

import os

import pytest

from synox.packs import admin
from synox.packs.manifest import ManifestError, doc_warnings, read, validate

SKILL = "---\nname: {name}\ndescription: 使用者想{what}的時候使用。\n---\n\n# {name}\n"


def _raw(**over):
    raw = {"name": "x", "title": "X", "summary": "s", "version": "0.1.0", "kind": "cli", "skill": "SKILL.md",
           "capabilities": [], "cli": {"argv": ["{python}", "./t.py"], "commands": [
               {"name": "go", "effect": "READ", "summary": "跑", "argv": ["go", "--n={n}"],
                "fields": [{"name": "n", "ask": "幾次", "kind": "int"}]}]}}
    raw.update(over)
    return raw


def _field(tmp_path, **f):
    raw = _raw()
    raw["cli"]["commands"][0]["fields"] = [{"name": "n", "ask": "幾次", "kind": "int", **f}]
    return raw


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "SKILL.md").write_text(SKILL.format(name="x", what="跑"), encoding="utf-8")
    return str(tmp_path)


def test_category_is_checked_at_install_and_ignored_when_broken_at_load(folder):
    assert validate(_raw(category=" 生活 "), folder, strict=True).category == "生活"
    assert validate(_raw(), folder, strict=True).category == ""
    for bad in ("", "x" * 25, "a\nb", 5):
        with pytest.raises(ManifestError, match="category"):
            validate(_raw(category=bad), folder, strict=True)
        assert validate(_raw(category=bad), folder).category == ""        # 載入時：當作沒寫


@pytest.mark.parametrize("field, why", [
    ({"required": "false"}, "required 要是 true 或 false"),
    ({"default": "abc"}, "不合 kind=int"),
    ({"default": [1]}, "default 要是"),
    ({"ask": "第一行\n第二行"}, "換行"),
    ({"help": "x" * 201}, "太長"),
])
def test_field_docs_are_checked_at_install_only(folder, tmp_path, field, why):
    raw = _field(tmp_path, **field)
    with pytest.raises(ManifestError, match=why):
        validate(raw, folder, strict=True)
    validate(_field(tmp_path, **field), folder)                             # 舊 pack 載入時照舊


def test_good_field_docs_pass_and_choice_default_must_be_a_choice(folder, tmp_path):
    validate(_field(tmp_path, default=3, help="一到十", required=False), folder, strict=True)
    raw = _raw()
    raw["cli"]["commands"][0]["fields"] = [{"name": "s", "ask": "語氣", "kind": "choice", "choices": ["a", "b"],
                                            "default": "c"}]
    with pytest.raises(ManifestError, match="只能是 a／b"):
        validate(raw, folder, strict=True)
    raw["cli"]["commands"][0]["fields"][0]["default"] = "B"
    validate(raw, folder, strict=True)
    raw["cli"]["commands"][0]["summary"] = "兩行\n說明"
    with pytest.raises(ManifestError, match="summary"):
        validate(raw, folder, strict=True)


def test_doc_warnings_are_reminders_in_the_install_report(folder):
    m = validate(_raw(), folder, strict=True)
    assert doc_warnings(m) == []
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("沒有 frontmatter")
    raw = _raw()
    raw["cli"]["commands"][0].pop("summary")
    raw["cli"]["commands"][0]["fields"][0].pop("ask")
    m = validate(raw, folder, strict=True)                                   # 不擋
    warns = doc_warnings(m)
    assert len(warns) == 3 and "frontmatter" in warns[0] and "go" in warns[1] and "go.n" in warns[2]
    assert all(w in admin.warnings_for(m) for w in warns)


def test_examples_hello_declares_category_and_defaults():
    hello = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "hello")
    m = read(hello, strict=True)
    assert m.category == "示範"
    tip = next(c for c in m.commands if c["name"] == "tip")
    assert {f["name"]: f.get("default") for f in tip["fields"]} == {"amount": None, "percent": 10, "round_up": False}
    assert doc_warnings(m) == []
