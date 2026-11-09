import json
import os

import pytest

from isdtelekit.core.registry import Field

from synox.packs import kit, loader
from synox.packs.manifest import ManifestError, validate


def _pack(folder, **over):
    os.makedirs(folder, exist_ok=True)
    raw = {"name": "demo", "title": "Demo", "summary": "s", "version": "0.1.0", "kind": "python", "skill": "SKILL.md"}
    raw.update(over)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: demo\ndescription: d\n---\nbody\n")
    return raw


def test_shipped_manifests_are_valid():
    folders = loader.discover()
    names = {os.path.basename(f) for f in folders}
    assert {"notes", "money", "remind", "google-calendar", "notion", "todoist", "apple-reminders-caldav"} <= names
    for folder in folders:
        from synox.packs.manifest import read
        m = read(folder)
        assert os.path.isfile(m.skill_path) and os.path.isfile(os.path.join(folder, "README.md"))


@pytest.mark.parametrize("over,needle", [
    ({"kind": "plugin"}, "kind"),
    ({"name": "Bad Name"}, "name"),
    ({"version": "1"}, "version"),
    ({"skill": "NOPE.md"}, "skill"),
    ({"kind": "connector"}, "auth"),
    ({"kind": "cli"}, "cli.argv"),
    ({"storage": "cloud"}, "storage"),
    ({"access": "public"}, "access"),
])
def test_manifest_errors(tmp_path, over, needle):
    raw = _pack(str(tmp_path / "p"))
    raw.update(over)
    with pytest.raises(ManifestError) as e:
        validate(raw, str(tmp_path / "p"))
    assert needle in str(e.value)


def test_missing_python_module(tmp_path):
    raw = _pack(str(tmp_path / "p"))
    with pytest.raises(ManifestError) as e:
        validate(raw, str(tmp_path / "p"))
    assert "pack.py" in str(e.value)


def test_loader_report_and_isolation(make_bot, tmp_path):
    base = tmp_path / "extra"
    _pack(str(base / "broken"), name="broken", kind="weird")
    good = base / "good"
    _pack(str(good), name="good", group="good")
    (good / "pack.py").write_text(
        "def install(app, pack):\n"
        "    pack.group.leaf('hi', lambda api, c, u, a: api.send_message(c, 'hi ' + str(pack.store.encrypted)), 'hi')\n",
        encoding="utf-8")
    boom = base / "boom"
    _pack(str(boom), name="boom", group="boom")
    (boom / "pack.py").write_text("def install(app, pack):\n    pack.group.leaf('x', None, 'x')\n    raise RuntimeError('nope')\n",
                                  encoding="utf-8")
    off = base / "off"
    _pack(str(off), name="off", group="off")
    (off / "pack.py").write_text("def install(app, pack):\n    raise AssertionError('should not load')\n", encoding="utf-8")
    bot = make_bot(raw={"packs": {"enabled": "all", "disabled": ["off"]}})
    report = loader.load_all(bot.app, bot.app.config, bot.app.extras["vault"], dirs=[str(base)])
    status = {i.name: i.status for i in report.items}
    assert status == {"broken": "invalid", "good": "loaded", "boom": "error", "off": "disabled"}
    assert bot.app.registry.node("boom") is None                 # 裝到一半壞掉：整組拿掉
    bot.say(100, "/good_hi")
    assert bot.last(100) == "hi False"                           # storage 沒寫＝plain


def test_connector_leaf(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/gcal")
    assert "還沒接上" in bot.last(owner)
    leaf = bot.app.registry.node("gcal.status")
    assert leaf is not None and leaf.ai is False


def test_cli_pack_registers_service_commands(make_bot, tmp_path):
    folder = tmp_path / "cli" / "svc"
    _pack(str(folder), name="svc", group="svc", kind="cli",
          cli={"argv": ["{python}", "./tool.py"], "commands": [
              {"name": "status", "argv": ["status"], "summary": "看狀態", "default": True},
              {"name": "add", "argv": ["add", "{item}"], "summary": "加", "effect": "write",
               "fields": [{"name": "item", "ask": "加什麼", "required": True}]}]})
    bot = make_bot()
    report = loader.load_all(bot.app, bot.app.config, None, dirs=[str(tmp_path / "cli")])
    assert [i.status for i in report.items] == ["loaded"]
    assert bot.app.registry.node("svc.status").command == "/svc"
    assert [f.name for f in bot.app.registry.node("svc.add").fields] == ["item"]


def test_kit_positional_and_keys():
    fields = (Field("amount", "金額", required=True, check=kit.number), Field("category", "類別", required=True),
              Field("memo", "備註"))
    v, missing, errors = kit.parse_args(fields, ["120", "午餐", "跟", "同事"])
    assert v == {"amount": "120", "category": "午餐", "memo": "跟 同事"} and not missing and not errors
    v, missing, errors = kit.parse_args(fields, ["120", "memo=好吃", "category=午餐"])
    assert v == {"amount": "120", "category": "午餐", "memo": "好吃"}
    v, missing, errors = kit.parse_args(fields, ["abc"])
    assert errors and [f.name for f in missing] == ["category"]


def test_money_budget_warning(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/money_budget 100")
    bot.say(owner, "/money 60 午餐")
    assert "預算還剩 40 元" in bot.last(owner)
    bot.say(owner, "/money 50 晚餐 和朋友")
    assert "這一筆讓這個月超過預算了" in bot.last(owner) and "（和朋友）" in bot.last(owner)
    bot.say(owner, "/money_month")
    assert "共 110 元" in bot.last(owner) and "超過 10 元" in bot.last(owner)
    bot.say(owner, "/money_list 1")
    assert "晚餐 50 元" in bot.last(owner)
    bot.say(owner, "/money abc 午餐")
    assert "要是數字" in bot.last(owner)


def test_notes_commands(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/note 買牛奶")
    bot.say(owner, "/note 繳電費")
    bot.say(owner, "/note_list 牛奶")
    assert "買牛奶" in bot.last(owner) and "繳電費" not in bot.last(owner)
    bot.say(owner, "/note_rm 5")
    assert "沒有第 5 筆" in bot.last(owner)
    bot.say(owner, "/note_rm 1")
    assert "買牛奶" in bot.last(owner)
    raw = open(bot.app.extras["vault"].path("notes"), "rb").read()
    assert "繳電費".encode() not in raw
