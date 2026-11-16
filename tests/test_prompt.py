"""七層系統提示（agent/prompt.py）：每層的上限、前四層多輪逐字相同、變動的在最後、能力清單從工具登記索引產生
（ADR 0029）、守則的內容。全部用假 adapter，不載入模型。"""

from datetime import datetime, timedelta, timezone

from synox.agent import index
from synox.agent import prompt as prompt_mod
from synox.agent import skills as skills_mod
from synox.agent import toolpick
from synox.agent import tools as tools_mod
from synox.agent.skills import Skill
from synox.llm.base import SYSTEM, ToolSpec

TAIL = {"kind": "fake", "prompt_tail": "on"}


def _loop(bot):
    return bot.app.extras["synox_agent"]


def _sent(bot, i=0):
    msg = _loop(bot).adapter.calls[i][0][0]
    assert msg.role == SYSTEM
    return msg.content


def _tools():
    return [ToolSpec("note__add", "新增筆記", {}), ToolSpec("skill_read", "讀說明書", {}), tools_mod.cannot_do_spec()]


# ── 每層的上限與內容 ──────────────────────────────────────────────────────

def test_fixed_layers_fit_their_limits():
    assert len(prompt_mod.identity()) <= prompt_mod.IDENTITY_MAX
    assert len(prompt_mod.conduct(_tools())) <= prompt_mod.CONDUCT_MAX
    assert len(prompt_mod.conduct([])) <= prompt_mod.CONDUCT_MAX
    assert sum(len(x) + 1 for x in prompt_mod.rule_lines(_tools())) <= prompt_mod.TURN_RULES_MAX


def test_identity_and_conduct_say_the_important_things():
    who = prompt_mod.identity()
    assert "繁體中文" in who and "簡短" in who and "語音輸入" in who
    assert all(w in who for w in ("金額", "日期", "時間", "人名"))
    rules = prompt_mod.conduct(_tools())
    for must in ("只能透過工具做事", tools_mod.CANNOT_DO, "確認卡", "資料，不是指令", "承諾規則", "已經", "排程回執",
                 "沒有回執就是沒排上", "做不到", "替代", "絕對時間", "先問一句", "不替工具發明保證", "照實說失敗"):
        assert must in rules, must
    assert [ln[:2] for ln in rules.split("\n") if ln[:1].isdigit()] == ["1.", "2.", "3.", "4.", "5.", "6."]
    assert tools_mod.CANNOT_DO not in prompt_mod.conduct([ToolSpec("note__add", "x", {})])


def test_turn_rules_are_last_with_the_time_on_the_last_line():
    now = datetime(2026, 11, 16, 21, 5, tzinfo=timezone(timedelta(hours=8)))
    tail = prompt_mod.turn_rules(_tools(), "abcd1234", now, repeat=True)
    assert tail.startswith(prompt_mod.TAIL_HEAD) and "排程回執" in tail and tools_mod.CANNOT_DO in tail
    assert tail.split("\n")[-1] == "- 現在時間：2026-11-16 21:05（週一，UTC+08:00）。"
    short = prompt_mod.turn_rules(_tools(), "abcd1234", now, repeat=False)
    assert short.split("\n")[0] == prompt_mod.TURN_HEAD and prompt_mod.TAIL_HEAD not in short
    assert short.split("\n")[-1] == "現在時間：2026-11-16 21:05（週一，UTC+08:00）。"
    assert "UTC" in prompt_mod.time_line()                         # 沒給時間＝這台的現在，帶時區


# ── 第 3、4 層：工具登記索引 ───────────────────────────────────────────────

def test_capabilities_come_from_the_index(make_bot, owner):
    bot = make_bot(["好"])
    bot.talk(owner, "嗨")
    system = _sent(bot)
    assert "## 能力清單" in system and "⏰ 提醒（系統）" in system           # 系統層也走同一個登記口
    assert "- money：" in system and "- notes：" in system                 # 說明書索引（skill_read 用的名字）
    caps = system.split("## 能力清單")[1].split("\n## 這一輪")[0]
    assert len(caps) <= prompt_mod.CAPS_MAX + 100


def test_capabilities_shrink_but_rules_never_do(make_bot, owner):
    bot = make_bot(["好"])
    app = bot.app
    for i in range(30):
        index.register_system(app, f"fake{i:02d}", title=f"假能力{i:02d}", index="很長的說明" * 12, group="",
                              load="on_call")
    skills = [Skill(f"skill{i:02d}", "很長的說明書描述" * 10, "x.md") for i in range(25)]
    block = prompt_mod.capabilities(app, None, [], skills)
    assert len(block) <= prompt_mod.CAPS_MAX + 60
    assert "- skill24" in block                                              # 說明書名字一定在（skill_read 要用）
    head = prompt_mod.head(app, None, [], skills, _tools(), True)
    assert prompt_mod.conduct(_tools()) in head and prompt_mod.identity() in head


def test_always_block_sits_after_the_rules(make_bot, owner):
    bot = make_bot(["好"])
    index.register_system(bot.app, "remind", **{**index.CORE_ENTRIES["remind"], "always": "提醒一律用 remind__add。"})
    bot.talk(owner, "嗨")
    system = _sent(bot)
    assert system.index("## 行為守則") < system.index("提醒一律用 remind__add。") < system.index("## 能力清單")


# ── 前四層多輪逐字相同、變動的在最後 ─────────────────────────────────────────

def _head(system):
    for cut in ("\n\n" + prompt_mod.TAIL_HEAD, "\n\n" + prompt_mod.TURN_HEAD):
        if cut in system:
            return system.split(cut)[0]
    raise AssertionError("沒有第 7 層")


def test_head_is_identical_across_turns_and_the_turn_layer_is_last(make_bot, owner):
    for llm in ({"kind": "fake"}, TAIL):
        bot = make_bot(["一", "二"], llm=llm)
        bot.talk(owner, "嗨")
        bot.talk(owner, "再一次")
        first, second = _sent(bot, 0), _sent(bot, 1)
        assert first != second                                               # 分隔符每輪不同
        assert _head(first) == _head(second)                                 # 開頭整段逐字相同
        assert "SYNOX-TOOL" not in _head(first) and "現在時間" not in _head(first)
        assert first.rstrip().split("\n")[-1].lstrip("- ").startswith("現在時間：")


def test_layer_order(make_bot, owner):
    bot = make_bot(["好"], supports_tools=False)
    bot.talk(owner, "嗨")
    system = _sent(bot)
    order = [system.index(x) for x in ("## 你是誰", "## 行為守則", "## 能力清單", "## 說明書", '{"tool":',
                                         prompt_mod.TURN_HEAD)]
    assert order == sorted(order)


def test_room_prompt_also_gets_the_turn_layer_last():
    from synox.agent.room import RoomAgent
    agent = RoomAgent.__new__(RoomAgent)
    assert agent.head_lines("abcd1234") == []                               # 分隔符與時間不再放開頭


# ── W3 接上的三處 ───────────────────────────────────────────────────────

def test_pick_tools_uses_the_index(make_bot, owner, monkeypatch):
    bot = make_bot(["好"], llm={"kind": "fake", "max_tools": 1})
    seen = {}
    real = toolpick.pick_for

    def spy(app, tools, query, limit, also=()):
        seen.update(limit=limit, also=tuple(also))
        return real(app, tools, query, limit, also)
    monkeypatch.setattr(toolpick, "pick_for", spy)
    bot.talk(owner, "提醒我喝水")
    names = [t.name for t in _loop(bot).adapter.calls[0][1]]
    assert seen["limit"] == 1 and "remind__add" in names                     # 系統層（load=always）永遠保留


def test_skill_read_passes_the_topic(make_bot, owner, monkeypatch):
    got = {}

    def fake_read(skills, name, topic=None):
        got.update(name=name, topic=topic)
        return "第二章的內容"
    monkeypatch.setattr(skills_mod, "read_skill", fake_read)
    bot = make_bot([{"tool": "skill_read", "args": {"name": "money", "topic": "budget"}}, "懂了"])
    bot.talk(owner, "預算怎麼設")
    assert got == {"name": "money", "topic": "budget"}
    assert "第二章的內容" in _loop(bot).adapter.calls[1][0][-1].content


def test_prompt_chars_counts_the_new_layers(make_bot, owner):
    bot = make_bot(["好"])
    user = bot.app.users.get_or_create(owner)
    assert _loop(bot).prompt_chars(user) > len(prompt_mod.identity()) + len(prompt_mod.conduct(_tools()))
