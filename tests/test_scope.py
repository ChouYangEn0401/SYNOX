"""範圍宣告（ADR 0025 §3；計畫 K4）：pack.json 的 callers／stepup、執行時的檢查、報告、升級紅字、kit 的小介面。"""

import os
from datetime import datetime

import pytest

from isdtelekit.core.registry import TYPED

from synox import guard, policy
from synox.guard.origin import Origin
from synox.guard.testing import Clock, as_origin, code_for, enroll
from synox.packs import admin, kit, upgrade
from synox.packs.manifest import ManifestError, validate

from conftest import FIXTURE_PACKS
from test_web import Client

pytestmark = pytest.mark.usefixtures("no_sockets")
SCOPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "scoped_pack")


def scoped_bot(make_bot, script=None):
    return make_bot(script, pack_dirs=(FIXTURE_PACKS, SCOPED))


def cli_raw(**extra):
    return {"name": "demo", "title": "示範", "summary": "示範", "version": "0.1.0", "kind": "cli",
            "cli": {"argv": ["{python}", "tool.py"], "commands": [
                {"name": "look", "argv": ["look"], "effect": "READ", "summary": "看"},
                {"name": "rm_all", "argv": ["rm"], "effect": "DANGER", "summary": "全刪"}]}, **extra}


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: demo\ndescription: 示範\n---\n", encoding="utf-8")
    return str(tmp_path)


@pytest.mark.parametrize("extra,needle", [
    ({"callers": {"nope": ["human"]}}, "nope"),
    ({"callers": {"look": []}}, "callers.look"),
    ({"callers": {"look": ["robot"]}}, "robot"),
    ({"callers": {"rm_all": ["human", "remote"]}}, "rm_all"),
    ({"stepup": ["ghost"]}, "ghost"),
    ({"callers": ["look"]}, "callers"),
])
def test_gate1_rejects_by_name(folder, extra, needle):
    with pytest.raises(ManifestError) as e:
        validate(cli_raw(**extra), folder, strict=True)
    assert needle in str(e.value)


def test_load_time_bad_entries_are_ignored(folder):
    m = validate(cli_raw(callers={"nope": ["human"], "look": ["human"]}, stepup=["ghost", "rm_all"]), folder)
    assert m.callers == {"look": ["human"]} and m.stepup == ["rm_all"]


def test_undeclared_pack_report_is_unchanged(folder):
    m = validate(cli_raw(), folder, strict=True)
    assert m.callers == {} and m.stepup == []
    scope = admin.scope_of(m)
    assert not {"callers", "stepup", "callers_text"} & set(scope)
    assert not any("收緊了範圍" in w for w in admin.warnings_for(m))
    declared = validate(cli_raw(callers={"look": ["human", "ai"]}, stepup=["rm_all"]), folder, strict=True)
    s2 = admin.scope_of(declared)
    assert s2["callers"] == {"look": ["human", "ai"]} and "一定要先用手機驗證器解鎖" in s2["callers_text"]
    assert any("收緊了範圍" in w for w in admin.warnings_for(declared))
    assert {k: v for k, v in s2.items() if k not in ("callers", "stepup", "callers_text")} == scope


def test_human_only_command(make_bot, owner):
    bot = scoped_bot(make_bot, [{"tool": "scoped__mine", "args": {}}, "好"])
    bot.say(owner, "/scoped_mine")
    assert bot.last(owner) == "mine ok"
    bot.talk(owner, "跑 mine")
    adapter = bot.app.extras["synox_agent"].adapter
    names = [t.name for t in adapter.calls[0][1]]
    assert "scoped__mine" not in names and "scoped__open" in names
    assert "沒有 scoped__mine 這個工具" in adapter.calls[1][0][-1].content
    bot.say(owner, "/schedule_add 21:00 /scoped_mine")
    bot.say(owner, "/schedule_list")
    assert "/scoped_mine" not in bot.last(owner)
    user = bot.app.users.get_or_create(owner)
    node = bot.app.registry.node("scoped.mine")
    open_node = bot.app.registry.node("scoped.open")
    d = policy.decide(bot.app, user, node, via=TYPED, chat_id=owner)              # 沒設來源＝unknown
    assert not d.allowed and d.reason == "caller" and "你本人" in d.message
    assert policy.decide(bot.app, user, open_node, via=TYPED, chat_id=owner).allowed
    with as_origin("remote", owner):
        assert policy.decide(bot.app, user, node, via=TYPED, chat_id=owner).reason == "caller"
    with as_origin("web", owner):
        assert policy.decide(bot.app, user, node, via=TYPED, chat_id=owner).allowed


def test_stepup_command(make_bot, owner):
    bot = scoped_bot(make_bot)
    bot.say(owner, "/scoped_vault")
    assert "一定要先設定手機驗證器" in bot.last(owner) and "安全" in bot.last(owner)
    g = guard.of(bot.app)
    clock = Clock()
    secret = enroll(g, owner, clock)                    # 開關沒開：一定要的照樣要
    bot.say(owner, "/scoped_vault")
    assert "要先解鎖" in bot.last(owner)
    bot.say(owner, f"/unlock {code_for(secret, clock)}")
    bot.say(owner, "/scoped_vault")
    assert bot.last(owner) == "vault ok"


def test_upgrade_red_and_plain(folder):
    old = validate(cli_raw(callers={"look": ["human"]}, stepup=["rm_all"]), folder)
    new = validate(cli_raw(callers={"look": ["human", "ai"]}), folder)
    changes = upgrade.caller_changes(old, new)
    assert [c["alert"] for c in changes] == [True, True]
    tighter = upgrade.caller_changes(new, old)
    assert [c["alert"] for c in tighter] == [False, False]
    gone = upgrade.caller_changes(old, validate(cli_raw(stepup=["rm_all"]), folder))
    assert gone[0]["alert"] and "拿掉" in gone[0]["text"]
    assert any(c["kind"] == "callers" for c in upgrade.diff_manifests(old, new))


def test_reload_leaves_nothing_behind(make_bot, owner):
    bot = scoped_bot(make_bot)
    g = guard.of(bot.app)
    assert g.scope.of("scoped.mine")["callers"] == ["human"] and g.scope.of("scoped.vault")["stepup"]
    from synox.packs import loader
    m = next(p.manifest for p in bot.app.extras["synox_packs"] if p.name == "scoped")
    m.callers, m.stepup = {}, []
    loader.apply_scope(bot.app, m)
    assert g.scope.of("scoped.mine") == {"callers": None, "stepup": False}
    assert g.scope.of("scoped.vault") == {"callers": None, "stepup": False}


def test_kit_caller_in_each_entry(make_bot, owner):
    bot = scoped_bot(make_bot, [{"tool": "scoped__who", "args": {}}, "好"])
    bot.say(owner, "/scoped_who")
    assert bot.last(owner) == "caller=telegram human=True"
    ui = bot.app.extras["synox_web"]
    c = Client(ui)
    c.login(owner)
    c.say("tools", "/scoped_who")
    assert "caller=web human=True" in str(c.events("tools"))
    bot.talk(owner, "誰在叫")
    adapter = bot.app.extras["synox_agent"].adapter
    assert "caller=ai human=False" in adapter.calls[1][0][-1].content
    bot.say(owner, "/schedule_add 21:00 /scoped_who")
    bot.app.extras["synox_schedule_runner"].tick(datetime(2026, 11, 9, 21, 0, 5))
    assert "caller=schedule human=False" in bot.texts(owner)


def test_require_human(make_bot, owner):
    bot = scoped_bot(make_bot, [{"tool": "scoped__self", "args": {}}, "好"])
    bot.say(owner, "/scoped_self")
    assert bot.last(owner) == "self ok"
    bot.talk(owner, "自己檢查")
    adapter = bot.app.extras["synox_agent"].adapter
    assert kit.NOT_HUMAN in adapter.calls[1][0][-1].content
    from synox import health
    reg = health.of(bot.app)
    assert reg is None or not [k for k in reg.entries if "scoped" in str(k)]       # 拒絕不算工具壞掉


@pytest.mark.parametrize("check,good,bad", [
    (kit.checks.positive_int, "3", "0"), (kit.checks.amount, "99.5", "1.234"), (kit.checks.amount, "1,200", "-5"),
    (kit.checks.iso_date, "2026-11-14", "2026-02-30"), (kit.checks.one_line, "一行", "兩\n行"),
    (kit.checks.max_len(3), "abc", "abcd"), (kit.checks.number, "1.5", "x"), (kit.checks.hhmm, "08:00", "8:0"),
])
def test_kit_checks(check, good, bad):
    assert check(good) is None
    assert isinstance(check(bad), str) and check(bad)


def test_sdk_caller(monkeypatch):
    from synox.sdk import author
    monkeypatch.delenv("SYNOX_CALLER", raising=False)
    assert author.caller() == ("unknown", False)
    monkeypatch.setenv("SYNOX_CALLER", "telegram")
    assert author.caller().human
    author.require_human()
    monkeypatch.setenv("SYNOX_CALLER", "ai")
    with pytest.raises(author.ToolError) as e:
        author.require_human()
    assert e.value.code == "not_human"


def test_core_restrictions(make_bot, owner):
    bot = make_bot()
    g = guard.of(bot.app)
    for path in ("unlock.on", "unlock.off", "webui.web", "webui.web_off"):
        assert g.scope.of(path)["callers"] == ["human"], path
    user = bot.app.users.get_or_create(owner)
    with as_origin("schedule", owner):
        assert policy.decide(bot.app, user, bot.app.registry.node("webui.web"), via=TYPED, chat_id=owner).reason \
            == "caller"
    assert Origin("console").human
