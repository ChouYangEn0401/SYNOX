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


def test_ships_with_no_tools_at_all(tmp_path):
    """出廠真的全空（2026-11-12，docs/legacy/builtin-packs.md、docs/legacy/connectors.md）：packs/ 只有說明、
    以前的 connectors/ 整個拿掉了（2026-11-13）、沒有出廠名單、SYNOX 只掃 packs/。
    用 git 追蹤的檔判斷，開發機自己裝的工具不算。"""
    import subprocess

    from synox.config import ROOT
    for folder, tracked in (("packs", ["packs/README.md"]), ("connectors", [])):
        done = subprocess.run(["git", "-C", ROOT, "ls-files", folder], capture_output=True, text=True)
        if done.returncode == 0:                                 # 解開的 zip（沒有 .git）就不看這一項
            assert done.stdout.split() == tracked
    assert loader.BUNDLED == ()
    leftover = tmp_path / "connectors"                           # 舊版解壓縮蓋過來可能留下的空殼／不存在的資料夾
    assert loader.discover([str(leftover)]) == []
    leftover.mkdir()
    (leftover / "README.md").write_text("old note", encoding="utf-8")
    assert loader.discover([str(leftover)]) == []
    src = open(loader.__file__, encoding="utf-8").read()
    assert 'PACK_DIRS = (os.path.join(ROOT, "packs"),)' in src           # conftest 換掉了 PACK_DIRS，看原始碼


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

# 記帳、筆記這兩個工具本身的測試（test_money_budget_warning、test_notes_commands、test_money_isolation）
# 2026-11-12 跟著工具搬到 SYNOX_Libs 的 tests/test_money.py、tests/test_notes.py。
