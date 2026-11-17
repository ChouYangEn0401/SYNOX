"""工具登記與索引（ADR 0030；agent/index.py、pack.json 的 agent 區塊與 requires.packs／requires.system）。

全部在 tmp 裡手放假工具、記憶體裡的 bot；不開埠、不開子程序。"""

import json
import os

import pytest

from synox.agent import index as agent_index
from synox.agent import skills as skills_mod
from synox.agent import toolpick
from synox.agent.validate import check_skill_read
from synox.llm.base import ToolSpec
from synox.packs import admin, lock, pkgload, upgrade
from synox.packs.manifest import ManifestError, read, validate

from conftest import FIXTURE_PACKS, trust_core

pytestmark = pytest.mark.usefixtures("no_sockets")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


PACK_PY = ("def install(app, pack):\n"
           "    pack.group.leaf('add', lambda api, c, u, a: api.send_message(c, 'ok'), '記一筆')\n"
           "    pack.group.leaf('report', lambda api, c, u, a: api.send_message(c, 'ok'), '看報表')\n")


def _pack(base, name, agent=None, *, requires=None, summary="測試用的工具", title=None, extra=None, py=PACK_PY):
    folder = os.path.join(str(base), name)
    raw = {"name": name, "title": title or f"T-{name}", "summary": summary, "version": "0.1.0", "kind": "python",
           "group": name.replace("-", "").replace("_", "")[:16], "skill": "SKILL.md", "python": {"module": "pack"}}
    if agent is not None:
        raw["agent"] = agent
    if requires is not None:
        raw["requires"] = requires
    raw.update(extra or {})
    _write(os.path.join(folder, "pack.json"), json.dumps(raw, ensure_ascii=False))
    _write(os.path.join(folder, "SKILL.md"), f"---\nname: {name}\ndescription: 測試\n---\n總表\n")
    _write(os.path.join(folder, "pack.py"), py)
    return folder


def _status(bot):
    return {i.name: (i.status, i.detail) for i in bot.app.extras["synox_pack_report"].items}


MONEY_AGENT = {"index": "記一筆支出或收入、看這個月花多少", "triggers": ["記帳", "花了"], "load": "on_trigger",
               "provides": ["ledger.record"], "promises": {"report": "watch"}}


# ── 索引多一行 ─────────────────────────────────────────────────────────

def test_installing_a_pack_with_agent_block_adds_one_index_line(make_bot, tmp_path):
    before = make_bot(["好"]).app
    lines_before = agent_index.lines_for(before)
    _pack(tmp_path / "extra", "ledger", MONEY_AGENT)
    bot = make_bot(["好"], pack_dirs=(FIXTURE_PACKS, str(tmp_path / "extra")))
    assert _status(bot)["ledger"][0] == "loaded"
    lines = agent_index.lines_for(bot.app)
    assert len(lines) == len(lines_before) + 1
    assert "- T-ledger：記一筆支出或收入、看這個月花多少" in lines
    entry = agent_index.current(bot.app).get("ledger")
    assert entry.triggers == ["記帳", "花了"] and entry.tools == ["ledger__add", "ledger__report"]
    assert agent_index.promised_tools(bot.app)["ledger__report"] == "watch"
    assert agent_index.promised_tools(bot.app)["remind__add"] == "schedule"      # 系統層走同一個登記口
    data = json.loads((tmp_path / "data" / agent_index.INDEX_FILE).read_text(encoding="utf-8"))
    names = [e["name"] for e in data["entries"]]
    assert "ledger" in names and "remind" in names and data["total_chars"] <= agent_index.INDEX_MAX
    row = next(e for e in data["entries"] if e["name"] == "ledger")
    assert row["chars"] > 0 and len(row["sha256"]) == 64


def test_twenty_tools_stay_within_the_limit(make_bot, tmp_path):
    long = ("記一筆支出、看報表、設預算、匯出明細、" * 4)[:60]
    for i in range(20):
        _pack(tmp_path / "many", f"tool{i:02d}", {"index": long}, title=f"第 {i} 號很長標題的測試工具")
    bot = make_bot(["好"], pack_dirs=(str(tmp_path / "many"),))
    assert all(s == "loaded" for s, _ in _status(bot).values())
    lines = agent_index.lines_for(bot.app)
    assert sum(len(x) + 1 for x in lines) <= agent_index.INDEX_MAX
    assert len([x for x in lines if "測試工具" in x]) == 20                     # 縮短每一行，不是丟掉工具
    full = [e.line() for e in agent_index.current(bot.app).entries if e.listed and e.index]
    assert sum(len(x) + 1 for x in full) > agent_index.INDEX_MAX              # 不縮的話會超過


def test_shrink_falls_back_to_more_line_when_titles_alone_overflow():
    entries = [agent_index.Entry(name=f"t{i}", title="標" * 30, index="說明") for i in range(100)]
    lines = agent_index.shrink(entries, 500)
    assert sum(len(x) + 1 for x in lines) <= 500 and lines[-1].startswith("- …另有")


# ── 第三方寫 agent.always 被拒 ───────────────────────────────────────────

def test_third_party_with_agent_always_is_refused(make_bot, tmp_path):
    data = tmp_path / "data"
    folder = _pack(tmp_path / "packs", "pushy", {"index": "測試", "always": "每輪都提醒一句話。"})
    m, _report, problems = admin.approve_installed(folder, str(data), trust="third-party")
    assert problems and "agent.always" in problems[0] and "核心" in problems[0]
    assert lock.entry(str(data), "pushy") is None                           # 沒寫鎖
    bot = make_bot(["好"], pack_dirs=(str(tmp_path / "packs"),))           # make_bot 把它鎖成第三方（沒經過安裝頁的不會載入，見 test_unapproved）→ rejected
    status, detail = _status(bot)["pushy"]
    assert status == "rejected" and "agent.always" in detail
    assert "每輪都提醒一句話。" not in agent_index.always_lines(bot.app)


def test_core_trust_allows_agent_always(make_bot, tmp_path):
    folder = _pack(tmp_path / "packs", "pushy", {"index": "測試", "always": "每輪都提醒一句話。", "load": "always"})
    trust_core(tmp_path / "data", folder)
    bot = make_bot(["好"], pack_dirs=(str(tmp_path / "packs"),))
    assert _status(bot)["pushy"][0] == "loaded"
    assert "每輪都提醒一句話。" in agent_index.always_lines(bot.app)
    assert "pushy__" in toolpick.keep_for(bot.app)                          # load=always：挑工具時永遠保留


def test_official_signature_counts_as_trusted_for_agent_always(make_bot, tmp_path):
    """ADR 0028 的「✅ 官方」簽章（鎖裡記著、安裝時驗過）跟信任選 core 一樣可以寫 agent.always；作者自己的簽章不行。"""
    from synox.packs.manifest import agent_trust_problem
    folder = _pack(tmp_path / "packs", "pushy", {"index": "測試", "always": "每輪都提醒一句話。"})
    m = read(folder)
    assert agent_trust_problem(m, "third-party", "official") == ""
    assert "agent.always" in agent_trust_problem(m, "third-party", "author")
    assert "agent.always" in agent_trust_problem(m, "third-party", "none")
    data = str(tmp_path / "data")
    lock.approve(data, m, None, None, via="test", folder=folder, trust="third-party",
                 signature={"status": "official", "key_id": "k1", "public_key": "pub"})
    bot = make_bot(["好"], pack_dirs=(str(tmp_path / "packs"),))
    assert _status(bot)["pushy"][0] == "loaded"
    assert "每輪都提醒一句話。" in agent_index.always_lines(bot.app)
    lock.approve(data, m, None, None, via="test", folder=folder, trust="third-party",
                 signature={"status": "author", "key_id": "k2", "public_key": "pub2"})
    bot = make_bot(["好"], pack_dirs=(str(tmp_path / "packs"),))
    assert _status(bot)["pushy"][0] == "rejected"


def test_unapproved_pack_never_reaches_the_index(make_bot, tmp_path):
    """沒經過安裝頁（沒有鎖）的工具不載入，也就不進 AI 的能力清單（ADR 0028 §4 在索引彙整之前）。"""
    _pack(tmp_path / "packs", "sneaky", {"index": "偷偷進索引的工具", "triggers": ["偷偷"]})
    bot = make_bot(["好"], pack_dirs=(str(tmp_path / "packs"),), lock_packs=False)
    assert _status(bot)["sneaky"][0] == "unapproved"
    assert agent_index.current(bot.app).get("sneaky") is None
    assert not any("偷偷進索引的工具" in line for line in agent_index.lines_for(bot.app))
    assert "sneaky__" not in agent_index.trigger_map(bot.app)


def test_install_report_shows_per_turn_chars_and_refuses_third_party_always(tmp_path):
    folder = _pack(tmp_path, "pushy", {"index": "測試", "always": "每輪都提醒一句話。"})
    m = read(folder, strict=True)
    info = admin.summary_of(m, admin.scan(m), {}, [])["agent"]
    assert info["chars"] > 0 and info["needs_core"] == ["agent.always"]
    text = admin.format_summary(admin.summary_of(m, admin.scan(m), {}, []))
    assert "每輪會多佔約" in text and "只有信任選「核心（core）」或有「✅ 官方」簽章才裝得進來" in text


# ── 缺相依不載入、說缺什麼 ────────────────────────────────────────────────

def test_missing_dependencies_are_not_loaded_and_say_what_is_missing(make_bot, tmp_path):
    base = tmp_path / "deps"
    _pack(base, "needy", requires={"packs": ["ghost>=1.0"]})
    _pack(base, "oldie", requires={"packs": ["base-lib>=2.0"]})
    _pack(base, "base-lib")                                                    # 0.1.0：版本不合
    _pack(base, "psychic", requires={"system": ["telepathy"]})
    _pack(base, "aaa", requires={"packs": ["zzz"], "system": ["notify", "schedule"]})   # 名字排在前面也照相依順序載入
    _pack(base, "zzz")
    bot = make_bot(["好"], pack_dirs=(str(base),))
    status = _status(bot)
    assert status["needy"] == ("missing", "缺 工具 ghost>=1.0（沒裝或沒載入）")
    assert status["oldie"][0] == "missing" and "base-lib>=2.0（裝的是 0.1.0）" in status["oldie"][1]
    assert status["psychic"][0] == "missing" and "telepathy" in status["psychic"][1]
    assert status["aaa"][0] == "loaded" and status["zzz"][0] == "loaded"
    names = [i.name for i in bot.app.extras["synox_pack_report"].items]
    assert names.index("zzz") < names.index("aaa")


def test_requires_packs_and_system_format_is_checked(tmp_path):
    folder = _pack(tmp_path, "x")
    raw = json.loads(open(os.path.join(folder, "pack.json"), encoding="utf-8").read())
    for bad in ({"packs": "notes"}, {"packs": ["Notes"]}, {"packs": ["notes>>1"]}, {"system": ["Notify"]}):
        with pytest.raises(ManifestError, match="requires"):
            validate({**raw, "requires": bad}, folder, strict=True)
    m = validate({**raw, "requires": {"packs": ["notes>=0.2,<1.0", "calendar"], "system": ["notify"]}}, folder,
                 strict=True)
    assert agent_index.dependency_problems(m, {"notes": "0.3.0", "calendar": "1.0.0"}, ["notify"]) == []
    assert agent_index.dependency_problems(m, {"notes": "1.2.0"}, []) == [
        "工具 notes>=0.2,<1.0（裝的是 1.2.0）", "工具 calendar（沒裝或沒載入）", "系統能力 notify（這台的 SYNOX 沒有）"]


def test_doctor_lists_missing_dependencies_and_usage(tmp_path):
    from synox import doctor
    a = read(_pack(tmp_path, "needy", {"index": "要別人"}, requires={"packs": ["ghost"]}))
    b = read(_pack(tmp_path, "chain", requires={"packs": ["needy"]}))
    c = read(_pack(tmp_path, "fine", {"index": "什麼都不缺"}))
    lines, bad = doctor.agent_lines(None, [a, b, c])
    text = "\n".join(lines)
    assert bad == 2 and "needy 0.1.0：不會載入，缺 工具 ghost" in text and "chain 0.1.0：不會載入，缺 工具 needy" in text
    assert "AI 能力清單：每輪約" in text and "fine：每輪約" in text and "needy：每輪約" not in text


# ── 舊工具（沒有區塊）行為不變 ───────────────────────────────────────────

def test_packs_without_agent_block_behave_as_before(make_bot, owner):
    bot = make_bot(["好"])
    for pack in bot.app.extras["synox_packs"]:
        assert pack.manifest.agent == {"declared": False, "index": "", "triggers": [], "load": "on_trigger",
                                       "topics": {}, "provides": [], "promises": {}, "always": "", "prefs": []}
    loop = bot.app.extras["synox_agent"]
    skills = skills_mod.from_packs(loop.visible_packs(None))
    spec = skills_mod.read_tool_spec(skills)
    assert set(spec.parameters["properties"]) == {"name"}                  # 沒有主題＝skill_read 跟以前一模一樣
    entry = agent_index.current(bot.app).get("money")
    assert entry.index and entry.triggers == [] and entry.load == "on_trigger" and not entry.always
    assert agent_index.always_lines(bot.app) == []
    user = bot.app.users.get_or_create(owner)
    tools = loop.tools_for(user, owner)
    assert toolpick.pick_for(bot.app, tools, "嗨", 0) == tools


def test_multi_file_python_pack_still_works_with_agent_block(make_bot, owner, tmp_path):
    folder = _pack(tmp_path / "pk", "pkgagent", {"index": "多檔工具的索引行", "triggers": ["多檔"]},
                   extra={"python": {"module": "pack", "package": True}},
                   py="from .engine import word\n\ndef install(app, pack):\n"
                      "    pack.group.leaf('hi', lambda api, c, u, a: api.send_message(c, word.HI), 'hi')\n")
    _write(os.path.join(folder, "engine", "__init__.py"), "")
    _write(os.path.join(folder, "engine", "word.py"), "HI = 'hello-from-engine'\n")
    try:
        bot = make_bot(["好"], pack_dirs=(str(tmp_path / "pk"),))
        assert _status(bot)["pkgagent"][0] == "loaded"
        bot.say(owner, "/pkgagent_hi")
        assert bot.last(owner) == "hello-from-engine"
        assert "- T-pkgagent：多檔工具的索引行" in agent_index.lines_for(bot.app)
    finally:
        pkgload.forget("pkgagent")


# ── 主題檔、觸發字、系統層登記 ───────────────────────────────────────────

def test_skill_read_topic_reads_only_that_chapter(make_bot, tmp_path):
    folder = _pack(tmp_path / "tp", "ledger", {"index": "記帳", "skill": {"file": "SKILL.md",
                                                                        "topics": {"receipt": "skills/receipt.md"}}})
    _write(os.path.join(folder, "skills", "receipt.md"), "# 收據\n照片裡的金額先唸回來再記。\n")
    bot = make_bot(["好"], pack_dirs=(str(tmp_path / "tp"),))
    skills = skills_mod.from_packs(bot.app.extras["synox_packs"])
    spec = skills_mod.read_tool_spec(skills)
    assert "topic" in spec.parameters["properties"] and "ledger：receipt" in spec.description
    assert "照片裡的金額" in skills_mod.read_skill(skills, "ledger", "receipt")
    assert skills_mod.read_skill(skills, "ledger") == "總表"
    assert "沒有 'nope' 這個主題" in skills_mod.read_skill(skills, "ledger", "nope")
    assert check_skill_read({"name": "ledger", "topic": "receipt"}) is None
    assert check_skill_read({"name": "ledger", "x": 1}) is not None
    assert "〔主題：receipt〕" in agent_index.current(bot.app).get("ledger").line()


def test_topic_files_must_exist_inside_the_pack(tmp_path):
    folder = _pack(tmp_path, "x")
    raw = json.loads(open(os.path.join(folder, "pack.json"), encoding="utf-8").read())
    for topics in ({"a": "missing.md"}, {"a": "../x/SKILL.md"}, {"Bad Name": "SKILL.md"}):
        with pytest.raises(ManifestError, match="agent.skill"):
            validate({**raw, "agent": {"skill": {"topics": topics}}}, folder, strict=True)
        assert validate({**raw, "agent": {"skill": {"topics": topics}}}, folder).agent["topics"] == {}   # 載入時寬鬆


def test_agent_block_rules_at_install(tmp_path):
    folder = _pack(tmp_path, "x")
    raw = json.loads(open(os.path.join(folder, "pack.json"), encoding="utf-8").read())
    bad = [({"index": "x" * 61}, "agent.index"), ({"index": "看 https://example.com"}, "agent.index"),
           ({"triggers": ["a"] * 13}, "agent.triggers"), ({"triggers": ["一二三四五六七八九十一二三"]}, "agent.triggers"),
           ({"load": "sometimes"}, "agent.load"), ({"provides": ["Money"]}, "agent.provides"),
           ({"promises": {"add": "forever"}}, "agent.promises"), ({"always": "y" * 201}, "agent.always"),
           ({"colour": "red"}, "不認得"), ("not-an-object", "agent 要是物件")]
    for agent, why in bad:
        with pytest.raises(ManifestError, match=why):
            validate({**raw, "agent": agent}, folder, strict=True)
        validate({**raw, "agent": agent}, folder)                               # 載入時：壞的那一項當作沒寫
    cli = {**raw, "kind": "cli", "cli": {"argv": ["{python}", "./t.py"], "commands": [
        {"name": "add", "effect": "WRITE", "argv": ["add"]}]}}
    cli.pop("python")
    with pytest.raises(ManifestError, match="不是這個工具宣告過的指令"):
        validate({**cli, "agent": {"promises": {"remove": "schedule"}}}, folder, strict=True)
    assert validate({**cli, "agent": {"promises": {"add": "schedule"}}}, folder, strict=True).agent["promises"] == \
        {"add": "schedule"}


def test_python_promise_to_unknown_command_is_dropped(make_bot, tmp_path):
    _pack(tmp_path / "pp", "ledger", {"index": "記帳", "promises": {"add": "schedule", "ghost": "watch"}})
    bot = make_bot(["好"], pack_dirs=(str(tmp_path / "pp"),))
    promised = agent_index.promised_tools(bot.app)
    assert promised.get("ledger__add") == "schedule" and "ledger__ghost" not in promised


def _spec(name, desc):
    return ToolSpec(name, desc, {"type": "object", "properties": {}})


def test_triggers_raise_the_score():
    tools = [_spec(f"misc{i}__run", "查天氣、匯率") for i in range(10)] + [_spec("ledger__add", "新增一筆")]
    plain = {t.name for t in toolpick.pick(tools, "今天午餐花了 120", 3)}
    assert "ledger__add" not in plain
    hit = {t.name for t in toolpick.pick(tools, "今天午餐花了 120", 3, triggers={"ledger__": ["花了"]})}
    assert "ledger__add" in hit and len(hit) == 3


def test_pick_for_uses_triggers_from_the_index(make_bot, tmp_path, owner):
    _pack(tmp_path / "tr", "ledger", {"index": "記帳", "triggers": ["花了"]})
    for i in range(6):
        _pack(tmp_path / "tr", f"misc{i}", {"index": "雜項"})
    bot = make_bot(["好"], pack_dirs=(str(tmp_path / "tr"),))
    loop = bot.app.extras["synox_agent"]
    tools = loop.tools_for(bot.app.users.get_or_create(owner), owner)
    got = {t.name for t in toolpick.pick_for(bot.app, tools, "午餐花了 120", 2)}
    assert {"ledger__add", "ledger__report"} <= got and any(n.startswith("remind__") for n in got)


def test_register_system_replaces_the_default_and_updates_the_index(make_bot):
    app = make_bot(["好"]).app
    assert "notify" in agent_index.system_names(app) and "remind" in agent_index.system_names(app)
    agent_index.register_system(app, "remind", title="⏰ 提醒（系統）", index="新的說明", group="remind",
                                triggers=["提醒"], load="always", promises={"add": "schedule"})
    entry = agent_index.current(app).get("remind")
    assert entry.index == "新的說明" and entry.tools and all(t.startswith("remind__") for t in entry.tools)
    with pytest.raises(ValueError):
        agent_index.register_system(app, "Bad", title="x")
    with pytest.raises(ValueError):
        agent_index.register_system(app, "x", title="x", promises={"a": "forever"})


def test_visible_lines_follow_permissions(make_bot, tmp_path):
    from isdtelekit.testing import OWNER_ID
    _pack(tmp_path / "vis", "secret", {"index": "只有擁有者"})
    bot = make_bot(["好"], pack_dirs=(str(tmp_path / "vis"),), raw={"mode": "server"})
    stranger = bot.app.users.get_or_create(424242)
    owner = bot.app.users.get_or_create(OWNER_ID)
    assert any("只有擁有者" in x for x in agent_index.lines_for(bot.app, owner))
    assert not any("只有擁有者" in x for x in agent_index.lines_for(bot.app, stranger))


# ── 升級紅字、新工具骨架 ─────────────────────────────────────────────────

def test_upgrade_marks_new_promises_and_always_in_red(tmp_path):
    old = read(_pack(tmp_path / "a", "ledger", {"index": "記帳"}))
    new = read(_pack(tmp_path / "b", "ledger", {"index": "記帳與報表", "promises": {"report": "watch"},
                                                  "always": "金額一律唸回。", "triggers": ["記帳"]}))
    changes = upgrade.diff_manifests(old, new)
    alerts = {c["kind"] for c in changes if c["alert"]}
    plain = {c["kind"] for c in changes if not c["alert"]}
    assert {"agent_promise", "agent_always"} <= alerts and {"agent_index", "agent_triggers"} <= plain
    assert upgrade.agent_changes(old, old) == []


def test_sdk_skeleton_has_an_agent_block_that_passes_install_checks(tmp_path):
    from synox import sdk
    for kind in ("python", "cli"):
        folder = str(tmp_path / kind)
        sdk.init_pack(folder, kind, f"demo{kind}", "示範工具")
        raw = json.loads(open(os.path.join(folder, "pack.json"), encoding="utf-8").read())
        assert set(raw["agent"]) >= {"index", "triggers", "load"}
        m = read(folder, strict=True)
        assert m.agent_declared and m.agent["index"]
