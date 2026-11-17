# -*- coding: utf-8 -*-
"""soul.md「習慣與規則」（核心統一規劃 11.4；runtime/habits.py、habit_card.py、habit_import.py）：
解析與型別、放寬標紅、AI 只能提議（按了才寫）、常駐助理／排程提不了、成員拿不到、{prefs_file} 只含那個工具宣告的鍵且用完就刪、
pack.prefs、網頁的 SOUL 頁、匯入程式的乾跑。全部假 AI、假資料；cli 工具是本機的一支 Python 小程式（經 JobRunner），不連網、不開埠。"""

import json
import os
import sys
import time

import pytest
from isdtelekit.users.roles import BasicRoles

from synox import runtime
from synox.guard import scope as scope_mod
from synox.llm.fake import FakeAdapter
from synox.runtime import habit_import, habits
from synox.runtime.soul import DEFAULT_SOUL, NOTES_HEADING, SoulError, prompt_text

from conftest import OTHER_ID
from test_web import Client, ui_of

pytestmark = pytest.mark.usefixtures("no_sockets")

PLAN_PREFS = [
    {"key": "schedule.plan.per_day", "type": "int", "ask": "一天最多排幾部", "default": 1, "min": 1, "max": 5,
     "looser": "larger"},
    {"key": "schedule.plan.split", "type": "bool", "ask": "可不可以切段", "default": False},
    {"key": "schedule.class.after_minutes", "type": "int", "default": 30, "min": 0, "max": 240, "looser": "smaller"},
    {"key": "schedule.busy.day_latest", "type": "time", "default": "23:30", "looser": "larger"},
]
SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "schedule_rules_sample.json")


def _decls(prefs=PLAN_PREFS):
    out, bad = habits.parse_decls(prefs, pack="planner", title="假的排程工具")
    assert bad == []
    return {p.key: p for p in out}


def _with_habits(*lines):
    return DEFAULT_SOUL.replace(f"\n{NOTES_HEADING}", "\n" + "\n".join(lines) + f"\n\n{NOTES_HEADING}")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# 假的 cli 工具：把 --prefs 那個檔的內容與路徑印回來
PREFS_CLI = r'''
import json, os, sys
path = ""
for a in sys.argv[1:]:
    if a.startswith("--prefs="):
        path = a[len("--prefs="):]
seen = json.load(open(path, encoding="utf-8")) if path and os.path.exists(path) else None
print(json.dumps({"ok": True, "seen": json.dumps(seen, ensure_ascii=False, sort_keys=True), "path": path}, ensure_ascii=False))
'''


def _cli_pack(base, name="planner", prefs=PLAN_PREFS):
    folder = os.path.join(str(base), name)
    raw = {"name": name, "title": "假的排程工具", "summary": "測試用", "version": "0.1.0", "kind": "cli",
           "access": "member", "auth": "none", "capabilities": ["subprocess"], "skill": "SKILL.md",
           "agent": {"prefs": prefs},
           "cli": {"python": sys.executable, "argv": ["{python}", "{pack_dir}/plan_cli.py"], "timeout": 30,
                   "commands": [{"name": "show", "default": True, "effect": "read", "summary": "印出拿到的習慣",
                                 "argv": ["show", "--prefs={prefs_file}"]}]}}
    _write(os.path.join(folder, "pack.json"), json.dumps(raw, ensure_ascii=False))
    _write(os.path.join(folder, "SKILL.md"), f"---\nname: {name}\ndescription: 測試\n---\n")
    _write(os.path.join(folder, "plan_cli.py"), PREFS_CLI)
    return folder


def _py_pack(base, name="habitpy", prefs=PLAN_PREFS[:2]):
    folder = os.path.join(str(base), name)
    raw = {"name": name, "title": "假的 python 工具", "summary": "測試用", "version": "0.1.0", "kind": "python",
           "group": name, "skill": "SKILL.md", "python": {"module": "pack"}, "agent": {"prefs": prefs}}
    _write(os.path.join(folder, "pack.json"), json.dumps(raw, ensure_ascii=False))
    _write(os.path.join(folder, "SKILL.md"), f"---\nname: {name}\ndescription: 測試\n---\n")
    _write(os.path.join(folder, "pack.py"),
           "import json\n"
           "def install(app, pack):\n"
           "    pack.group.leaf('show', lambda api, c, u, a: api.send_message(c, 'PREFS ' + "
           "json.dumps(pack.prefs(u, c), sort_keys=True)), '看習慣')\n")
    return folder


def _seen(bot, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for t in bot.texts():
            if "seen" in t and "{" in t:
                line = next(x for x in t.splitlines() if "seen" in x)
                return json.loads(line.split("：", 1)[1] if "：" in line else line.split(":", 1)[1])
        time.sleep(0.1)
    raise AssertionError(bot.texts())


# ── 純函式：解析、型別、放寬 ───────────────────────────────────────────

def test_parse_values_types_and_later_line_wins():
    text = _with_habits("- 一天最多排一部，不要切段。〔schedule.plan.per_day=1〕〔schedule.plan.split=no〕",
                        "- 只是一句話，沒有值",
                        "- 後來改成兩部〔schedule.plan.per_day=2〕",
                        "- 沒人宣告的鍵〔other.thing=[1, \"a\"]〕")
    h = habits.parse(text, _decls())
    assert h.values["schedule.plan.per_day"] == 2                     # 同鍵兩次：後面的贏
    assert h.values["schedule.plan.split"] is False                   # no → False（照宣告的 bool）
    assert h.values["other.thing"] == [1, "a"]                        # 沒宣告的照 JSON 讀
    assert list(h.conflicts) == ["schedule.plan.per_day"] and len(h.conflicts["schedule.plan.per_day"]) == 2
    assert [ln.text for ln in h.lines][1] == "只是一句話，沒有值" and h.problems == []


def test_parse_reports_broken_lines_and_type_mismatches():
    text = _with_habits("- 壞的〔schedule.plan.per_day=1", "- 型別錯〔schedule.plan.per_day=很多〕",
                        "- 超出範圍〔schedule.plan.per_day=9〕", "- 沒有等號〔schedule.plan.split〕",
                        "- 時間錯〔schedule.busy.day_latest=25:00〕")
    h = habits.parse(text, _decls())
    whys = " | ".join(why for _l, why in h.problems)
    assert len(h.problems) == 5 and "沒有成對" in whys and "要是整數" in whys and "最大是 5" in whys
    assert "少了 =" in whys and "HH:MM" in whys
    assert "schedule.plan.per_day" not in h.values


def test_comments_and_other_sections_are_not_habits():
    text = DEFAULT_SOUL.replace("## 偏好\n", "## 偏好\n- 不是習慣〔schedule.plan.per_day=3〕\n") + \
        "- 助理筆記裡的也不算〔schedule.plan.per_day=4〕\n"
    assert habits.parse(text, _decls()).values == {}
    assert habits.parse(DEFAULT_SOUL).lines == [] and prompt_text(DEFAULT_SOUL) == ""   # 預設（含說明註解）照舊不放


def test_looser_follows_the_declared_direction():
    d = _decls()
    assert habits.is_looser(d["schedule.plan.per_day"], 1, 2)                  # larger：變大＝放寬
    assert not habits.is_looser(d["schedule.plan.per_day"], 2, 1)
    assert habits.is_looser(d["schedule.class.after_minutes"], 30, 10)         # smaller：變小＝放寬
    assert habits.is_looser(d["schedule.busy.day_latest"], "23:30", "23:59")
    assert habits.is_looser(d["schedule.busy.day_latest"], "23:30", "")        # "" 不檢查＝最寬
    assert not habits.is_looser(d["schedule.plan.split"], False, True)         # 沒宣告 looser 就不判斷


def test_declarations_are_checked():
    _ok, bad = habits.parse_decls([{"key": "Bad Key", "type": "int", "default": 1},
                                   {"key": "a.b", "type": "colour", "default": 1},
                                   {"key": "a.c", "type": "int"},
                                   {"key": "a.d", "type": "bool", "default": True, "looser": "larger"},
                                   {"key": "a.e", "type": "int", "default": "x"},
                                   {"key": "a.f", "type": "int", "default": 1, "min": 5}])
    text = " | ".join(bad)
    assert len(bad) == 6 and "小寫英數字" in text and "type 只能是" in text and "要寫 default" in text
    assert "只有 int／number／time 可以寫 looser" in text and "default 要是整數" in text and "最小是 5" in text


def test_insert_replaces_same_keys_and_keeps_partial_overlaps():
    text = _with_habits("- 一天一部、不切段〔schedule.plan.per_day=1〕〔schedule.plan.split=no〕",
                        "- 課後半小時〔schedule.class.after_minutes=30〕")
    new, replaced, shadowed = habits.insert(text, "- 課後一小時〔schedule.class.after_minutes=60〕")
    assert replaced == ["- 課後半小時〔schedule.class.after_minutes=30〕"] and shadowed == []
    new, replaced, shadowed = habits.insert(new, "- 一天兩部〔schedule.plan.per_day=2〕")
    assert replaced == [] and shadowed and "不切段" in shadowed[0]
    h = habits.parse(new, _decls())
    assert h.values["schedule.plan.per_day"] == 2 and h.values["schedule.class.after_minutes"] == 60
    assert new.index("一天兩部") < new.index(NOTES_HEADING)                # 留在這一段，不跑到助理筆記
    no_section = "# soul.md\n\n## 偏好\n- 叫我阿明\n"
    added = habits.insert(no_section, "- 一天一部〔schedule.plan.per_day=1〕")[0]
    assert habits.parse(added).values == {"schedule.plan.per_day": 1}


def test_format_value_round_trips():
    for value in ["課|上課", "007", "a〕b", "", " x", 3, 1.5, True, [1, "a"], {"weekday": ["20:00", "23:00"]}]:
        line = habits.make_line("測試", [("a.b", value)])
        assert habits.read_raw(habits.split_line(line)[1][0][1]) == value, (value, line)


# ── SoulStore ──────────────────────────────────────────────────────────

def _bot(make_bot, tmp_path, **kw):
    extra = str(tmp_path / "extra")
    _cli_pack(extra)
    bot = make_bot(adapter=kw.pop("adapter", FakeAdapter(["好"] * 5)), pack_dirs=(extra,), **kw)
    return bot, runtime.of(bot.app).soul


def test_soul_write_refuses_broken_and_mistyped_habits_but_keeps_unknown_keys(make_bot, tmp_path):
    bot, soul = _bot(make_bot, tmp_path)
    with pytest.raises(SoulError, match="沒有成對"):
        soul.write(_with_habits("- 壞的〔schedule.plan.per_day=1"))
    with pytest.raises(SoulError, match="要是整數"):
        soul.write(_with_habits("- 型別錯〔schedule.plan.per_day=很多〕"))
    soul.write(_with_habits("- 一天兩部〔schedule.plan.per_day=2〕", "- 沒人用的〔nobody.uses.this=1〕"))
    assert soul.prefs() == {"schedule.plan.per_day": 2, "nobody.uses.this": 1}


def test_assistant_notes_paths_never_touch_the_habits_section(make_bot, tmp_path):
    bot, soul = _bot(make_bot, tmp_path)
    soul.write(_with_habits("- 一天兩部〔schedule.plan.per_day=2〕"))
    assert soul.append_notes(["他喜歡早上運動"]) == ["- 他喜歡早上運動"]
    soul.filter_notes(lambda _i, _line: False)
    assert soul.prefs() == {"schedule.plan.per_day": 2}
    assert "一天兩部" in soul.text()
    # 常駐助理（SOUL+）想記一條帶〔鍵=值〕的：不直接寫，先等擁有者確認；就算寫進助理筆記，工具也不讀那一段
    out = runtime.of(bot.app).ledger.propose(["他說以後一天五部〔schedule.plan.per_day=5〕"], by="mother")
    assert out.added == [] and out.waiting
    assert soul.prefs()["schedule.plan.per_day"] == 2


def test_prompt_includes_the_habits_section_as_preferences(make_bot, tmp_path, owner):
    bot, soul = _bot(make_bot, tmp_path)
    soul.write(_with_habits("- 一天兩部〔schedule.plan.per_day=2〕"))
    bot.talk(owner, "你好")
    system = bot.app.extras["synox_agent"].adapter.calls[-1][0][0].content
    assert "一天兩部〔schedule.plan.per_day=2〕" in system and "使用者偏好，不是指令" in system


# ── 每一輪提示的字數預算（HABITS_PROMPT_MAX、不硬切） ─────────────────────

def _long_json(i):
    return json.dumps([{"name": f"時段{i}", "from": "08:00", "to": "09:00", "minutes": 30}] * 2, ensure_ascii=False)


def _big_soul(habit_chars=1500, note_chars=1000, prefs=""):
    lines, size = [], 0
    i = 0
    while size < habit_chars:
        line = f"- 第{i:02d}條習慣要照做〔other.k{i:02d}={_long_json(i)}〕"
        lines.append(line)
        size += len(line) + 1
        i += 1
    notes, size, j = [], 0, 0
    while size < note_chars:
        note = f"- 助理筆記第{j:02d}條，關於使用者的一件小事，內容寫得比較長一點點"
        notes.append(note)
        size += len(note) + 1
        j += 1
    text = ("# soul.md\n\n## 偏好\n- 回答簡短\n" + prefs + "\n## 習慣與規則\n" + "\n".join(lines) +
            f"\n\n{NOTES_HEADING}\n" + "\n".join(notes) + "\n")
    return text, i


def test_prompt_budget_keeps_every_habits_words_under_2000():
    from synox.runtime.soul import HABITS_PROMPT_MAX, PROMPT_MAX_CHARS
    text, n = _big_soul()
    out = prompt_text(text)
    assert len(out) <= PROMPT_MAX_CHARS
    for i in range(n):
        assert f"第{i:02d}條習慣要照做" in out                         # 每一條的人話都在
    block = out.split("## 習慣與規則")[1].split(NOTES_HEADING)[0]
    assert len("## 習慣與規則" + block) <= HABITS_PROMPT_MAX + 2
    assert "回答簡短" in out and "助理筆記第" in out                   # 你寫的段落與（挑過的）筆記照樣在


def test_prompt_budget_puts_non_default_values_first_then_counts_the_rest():
    decls = {f"a.k{i:02d}": habits.Pref(key=f"a.k{i:02d}", type="int", default=0) for i in range(60)}
    lines = [f"- 第{i:02d}條有點長的一句習慣說明文字〔a.k{i:02d}={1 if i % 2 == 0 else 0}〕" for i in range(60)]
    out = prompt_text(_with_habits(*lines), decls=decls)
    for i in range(0, 60, 2):
        assert f"第{i:02d}條" in out                                     # 跟預設不同的先放
    assert "另有" in out and "條習慣，見 SOUL 頁" in out
    missing = sum(1 for i in range(60) if f"第{i:02d}條" not in out)
    assert f"另有 {missing} 條習慣" in out and missing > 0
    assert all(f"第{i:02d}條" not in out for i in range(1, 60, 2) if f"第{i:02d}條" not in out)


def test_prompt_budget_owner_text_too_long_cuts_owner_rows_not_habits():
    from synox.runtime.soul import CUT_NOTE, PROMPT_MAX_CHARS
    prefs = "".join(f"- 很長的偏好第{i:03d}行，" + "字" * 40 + "\n" for i in range(60))
    text, n = _big_soul(habit_chars=800, note_chars=300, prefs=prefs)
    out = prompt_text(text)
    assert len(out) <= PROMPT_MAX_CHARS and out.endswith(CUT_NOTE)
    for i in range(n):
        assert f"第{i:02d}條習慣要照做" in out                         # 習慣段的人話沒被切
    assert "助理筆記第" not in out                                      # 先拿掉的是助理筆記


# ── soul__propose_habit：只能提議、按了才寫 ─────────────────────────────

def _propose(bot, owner, args):
    bot.app.extras["synox_agent"].adapter.script[:0] = [{"tool": "soul__propose_habit", "args": args}]
    bot.talk(owner, "以後一天可以排兩部")


def test_ai_proposal_is_a_card_and_only_the_button_writes(make_bot, tmp_path, owner):
    bot, soul = _bot(make_bot, tmp_path)
    tools = [t.name for t in bot.app.extras["synox_agent"].tools_for(bot.app.users.get(owner), owner)]
    assert "soul__propose_habit" in tools
    _propose(bot, owner, {"text": "一天最多排兩部", "key": "schedule.plan.per_day", "value": "2"})
    card = next(t for t in bot.texts(owner) if "習慣與規則" in t and "〔schedule.plan.per_day=2〕" in t)
    assert "這會影響：假的排程工具" in card and "🔴 放寬：schedule.plan.per_day 1 → 2" in card
    assert soul.prefs() == {}                                                 # 還沒按：沒有寫
    go = [b for b in bot.buttons(owner) if b.startswith("soul_habit:go:")][0]
    bot.press(OTHER_ID, go)                                                   # 別人按：當作不存在
    assert soul.prefs() == {}
    bot.press(owner, go)
    assert soul.prefs() == {"schedule.plan.per_day": 2}
    assert any("寫進「習慣與規則」了" in t for t in bot.texts(owner))
    assert soul.audit()[-1]["by"] == "owner"
    bot.press(owner, go)                                                      # 同一張卡只能用一次
    assert any("過期" in t for t in bot.texts(owner))


def test_tightening_is_not_marked_looser_and_no_suppresses(make_bot, tmp_path, owner):
    bot, soul = _bot(make_bot, tmp_path)
    _propose(bot, owner, {"text": "課後一小時內不排", "key": "schedule.class.after_minutes", "value": "60"})
    card = next(t for t in bot.texts(owner) if "〔schedule.class.after_minutes=60〕" in t)
    assert "放寬" not in card
    bot.press(owner, [b for b in bot.buttons(owner) if b.startswith("soul_habit:no:")][0])
    assert soul.prefs() == {} and runtime.of(bot.app).ledger.is_suppressed("- 課後一小時內不排〔schedule.class.after_minutes=60〕")
    bot.api.clear()
    _propose(bot, owner, {"text": "課後一小時內不排", "key": "schedule.class.after_minutes", "value": "60"})
    assert not [b for b in bot.buttons(owner) if b.startswith("soul_habit:")]   # 說過不要：不再出卡


def test_unknown_keys_and_bad_values_are_refused(make_bot, tmp_path, owner):
    bot, soul = _bot(make_bot, tmp_path)
    bot.say(owner, "/soul_propose_habit 亂寫 key=not.declared value=1")
    assert "不是任何已載入工具宣告的鍵" in bot.last(owner)
    bot.say(owner, "/soul_propose_habit 一天九部 key=schedule.plan.per_day value=9")
    assert "最大是 5" in bot.last(owner)
    bot.say(owner, "/soul_propose_habit 一天兩部 key=schedule.plan.per_day")
    assert "要一起給" in bot.last(owner)
    assert not bot.buttons(owner) and soul.prefs() == {}


def test_schedule_mother_and_remote_cannot_propose(make_bot, tmp_path, owner):
    bot, _soul = _bot(make_bot, tmp_path)
    node = bot.app.registry.node("soul.propose_habit")
    from synox import guard
    gate = guard.of(bot.app)
    for caller in ("schedule", "system", "remote"):
        assert not gate.scope.allows(node, caller)
    assert gate.scope.allows(node, "human") and gate.scope.allows(node, "ai")
    assert set(scope_mod.CALLERS) == {"human", "remote", "ai", "schedule", "system"}
    bot.say(owner, "/schedule_add 21:00 /soul_propose_habit 一天兩部 key=schedule.plan.per_day value=2")
    assert "不能排進排程" in bot.last(owner)


def test_members_get_no_tool_no_command_and_only_defaults(make_bot, tmp_path, owner):
    bot, soul = _bot(make_bot, tmp_path, raw={"mode": "server"})
    soul.write(_with_habits("- 一天兩部〔schedule.plan.per_day=2〕"))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    member = bot.app.users.get(OTHER_ID)
    tools = [t.name for t in bot.app.extras["synox_agent"].tools_for(member, OTHER_ID)]
    assert "soul__propose_habit" not in tools
    bot.say(OTHER_ID, "/soul_propose_habit 一天三部 key=schedule.plan.per_day value=3")
    assert "習慣與規則" not in bot.last(OTHER_ID) and not bot.buttons(OTHER_ID)
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "planner")
    assert pack.prefs(member, OTHER_ID)["schedule.plan.per_day"] == 1           # 成員＝預設
    me = bot.app.users.get(owner)
    assert pack.prefs(me, owner)["schedule.plan.per_day"] == 2                  # 擁有者自己的對話＝soul 的
    assert pack.prefs(me, -100123)["schedule.plan.per_day"] == 1                # 群組／頻道＝預設


# ── {prefs_file} 與 pack.prefs ──────────────────────────────────────────

def test_prefs_file_has_only_the_tools_keys_and_is_deleted(make_bot, tmp_path, owner):
    extra = str(tmp_path / "extra")
    _cli_pack(extra)
    _py_pack(extra)
    bot = make_bot(adapter=FakeAdapter(["好"]), pack_dirs=(extra,))
    soul = runtime.of(bot.app).soul
    soul.write(_with_habits("- 一天兩部、可以切段〔schedule.plan.per_day=2〕〔schedule.plan.split=yes〕",
                            "- 不是這個工具的〔other.tool.key=7〕"))
    bot.say(owner, "/planner")
    bot.app.tasks.wait(20)
    seen = _seen(bot)
    assert seen["v"] == 1
    assert seen["prefs"] == {"schedule.plan.per_day": 2, "schedule.plan.split": True,
                             "schedule.class.after_minutes": 30, "schedule.busy.day_latest": "23:30"}
    folder = habits.prefs_dir(bot.app.config.data_dir, "planner")
    assert os.path.isdir(folder) and os.listdir(folder) == []                  # 用完就刪
    bot.api.clear()
    bot.say(owner, "/habitpy_show")
    shown = json.loads(bot.last(owner).split("PREFS ", 1)[1])
    assert shown == {"schedule.plan.per_day": 2, "schedule.plan.split": True}   # python：只有它宣告的兩個


def test_prefs_file_for_a_member_has_only_defaults(make_bot, tmp_path, owner):
    # 伺服器版沒有真隔離時第三方 cli 只給擁有者（PERM-7）、成員預設沒有 subprocess：這裡放寬這兩條，才測得到成員那一邊
    policy = {"sandbox": {"required_for": "none"},
              "roles": {"member": {"capabilities": ["network", "filesystem:own", "subprocess"]}}}
    bot, soul = _bot(make_bot, tmp_path, raw={"mode": "server", "policy": policy})
    soul.write(_with_habits("- 一天兩部〔schedule.plan.per_day=2〕"))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.say(OTHER_ID, "/planner")
    bot.app.tasks.wait(20)
    assert _seen(bot)["prefs"]["schedule.plan.per_day"] == 1
    assert os.listdir(habits.prefs_dir(bot.app.config.data_dir, "planner")) == []


def test_two_calls_at_once_cannot_read_each_others_prefs_file(make_bot, tmp_path, owner):
    """同一個工具同時被兩個人叫：各自一個資料夾，沙盒只准讀自己那一個（不是整個 data/prefs/<工具>/）。"""
    from synox import sandbox
    from synox.packs.loader import placeholders
    bot, soul = _bot(make_bot, tmp_path, raw={"mode": "server"})
    soul.write(_with_habits("- 一天兩部〔schedule.plan.per_day=2〕"))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "planner")
    config = bot.app.config
    me, member = bot.app.users.get(owner), bot.app.users.get(OTHER_ID)
    path_a = habits.write_prefs_file(config.data_dir, "planner", habits.values_for(bot.app, pack, me, owner))
    path_b = habits.write_prefs_file(config.data_dir, "planner", habits.values_for(bot.app, pack, member, OTHER_ID))
    try:
        dir_a, dir_b = os.path.dirname(path_a), os.path.dirname(path_b)
        assert dir_a != dir_b and os.path.basename(path_a) == os.path.basename(path_b) == "prefs.json"
        assert os.listdir(dir_a) == ["prefs.json"]                                     # 資料夾裡只有自己的檔
        for mine, theirs, user in ((path_a, dir_b, me), (path_b, dir_a, member)):
            ph = dict(placeholders(pack.manifest, config, user), prefs_file=mine)
            reads = [os.path.normcase(p) for p in sandbox.grants_for(pack.manifest, config, ph).read]
            assert os.path.normcase(os.path.dirname(mine)) in reads
            base = os.path.normcase(habits.prefs_dir(config.data_dir, "planner"))
            other = os.path.normcase(theirs)
            assert not any(other == r or other.startswith(r + os.sep) for r in reads)   # 對方的資料夾不在讀得到的範圍
            assert base not in reads and os.path.normcase(os.path.join(config.data_dir, "prefs")) not in reads
        for path, want in ((path_a, 2), (path_b, 1)):                                  # 擁有者的值／成員的預設
            with open(path, encoding="utf-8") as f:
                assert json.load(f)["prefs"]["schedule.plan.per_day"] == want
    finally:
        habits.remove_prefs_file(path_a)
        habits.remove_prefs_file(path_b)
    assert not os.path.exists(os.path.dirname(path_a)) and not os.path.exists(os.path.dirname(path_b))   # 連資料夾一起刪


def test_values_for_needs_a_chat_id(make_bot, tmp_path, owner):
    bot, soul = _bot(make_bot, tmp_path)
    soul.write(_with_habits("- 一天兩部〔schedule.plan.per_day=2〕"))
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "planner")
    me = bot.app.users.get(owner)
    assert pack.prefs(me, None)["schedule.plan.per_day"] == 1                     # 不知道是哪個對話＝預設
    assert not habits.is_owners_own(bot.app, me, None)
    with pytest.raises(TypeError):
        habits.values_for(bot.app, pack, me)                                       # chat_id 一定要給


def test_bad_prefs_declaration_refuses_install(tmp_path):
    from synox.packs.manifest import ManifestError, read
    folder = _cli_pack(tmp_path, prefs=[{"key": "x.y", "type": "int"}])
    with pytest.raises(ManifestError, match="要寫 default"):
        read(folder, strict=True)


# ── 網頁 SOUL 頁 ───────────────────────────────────────────────────────

def test_web_habits_view_marks_looser_and_unused(make_bot, tmp_path, owner):
    bot, soul = _bot(make_bot, tmp_path)
    soul.write(_with_habits("- 一天三部〔schedule.plan.per_day=3〕", "- 課後一小時〔schedule.class.after_minutes=60〕",
                            "- 沒人用〔nobody.uses.this=1〕"))
    c = Client(ui_of(bot))
    c.login(owner)
    status, data = c.get("/api/runtime/soul/habits")
    assert status == 200
    keys = {k["key"]: k for ln in data["lines"] for k in ln["keys"]}
    assert keys["schedule.plan.per_day"]["looser"] is True                   # 比預設 1 寬鬆 → 畫面標紅
    assert keys["schedule.class.after_minutes"]["looser"] is False           # 比預設嚴
    assert keys["nobody.uses.this"]["unused"] is True
    assert keys["schedule.plan.per_day"]["used_by"] == ["假的排程工具"]
    assert {p["key"] for p in data["declared"]} >= {"schedule.plan.per_day", "schedule.plan.split"}
    status, _data = c.get("/api/runtime/soul")                                # 原本的合約不變
    assert status == 200 and set(_data) == {"text", "updated_at"}


def test_web_habits_is_owner_only(make_bot, tmp_path, owner):
    bot, _soul = _bot(make_bot, tmp_path, raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    c = Client(ui_of(bot))
    c.login(OTHER_ID)
    assert c.get("/api/runtime/soul/habits")[0] == 403


# ── 匯入程式 ───────────────────────────────────────────────────────────

def test_import_dry_run_prints_every_line_and_changes_nothing(make_bot, tmp_path):
    out = []
    assert habit_import.run(SAMPLE, out=out.append) == 0
    text = "\n".join(out)
    lines = [x for x in out if x.startswith("- ")]
    assert out[0].startswith("乾跑") and len(lines) == 17
    assert "- 上完課 30 分鐘內不排別的。〔schedule.class.after_minutes=30〕" in lines
    assert "- 一部不要切段。〔schedule.plan.split=false〕" in lines
    assert "- 每天最晚排到 23:30。〔schedule.busy.day_latest=23:30〕" in lines
    assert "enabled：整個檢查的總開關" in text and "something_new" in text
    for line in lines:                                                        # 每一行都讀得回原本的值
        habits.check_line(line)


def test_import_apply_writes_and_can_rerun(make_bot, tmp_path):
    bot, soul = _bot(make_bot, tmp_path)
    assert habit_import.run(SAMPLE, apply=True, soul=soul, out=lambda _x: None) == 0
    first = soul.prefs()
    assert first["schedule.plan.per_day"] == 1 and first["schedule.meals"][0]["name"] == "午餐"
    assert first["schedule.plan.windows"] == {"weekday": ["20:00", "23:00"], "weekend": ["09:00", "23:00"]}
    count = len(soul.habits().lines)
    assert habit_import.run(SAMPLE, apply=True, soul=soul, out=lambda _x: None) == 0
    assert len(soul.habits().lines) == count and soul.habits().conflicts == {}    # 重跑＝取代，不會越來越多


def test_import_null_means_skip(tmp_path):
    lines, skipped = habit_import.convert({"busy": {"day_latest": None, "max_hours": 0}, "_說明": "x"})
    assert lines == ["- 連續排超過 0 小時要休息。〔schedule.busy.max_hours=0〕"]
    assert any(s.startswith("busy.day_latest＝null") for s in skipped)


def test_import_cli_entry(tmp_path, capsys):
    from synox.__main__ import main
    assert main(["import-legacy", "schedule-rules", f"--from={SAMPLE}"]) == 0
    assert "〔schedule.plan.per_day=1〕" in capsys.readouterr().out
    assert main(["import-legacy", "schedule-rules", f"--from={tmp_path / 'missing.json'}"]) == 2
