"""對話助理的離線評測（src/synox/evals、evals/assistant）：題目、照劇本重放（接在真的 AgentLoop 上）、硬檢查、報表、指令列。
全部離線：假 AI（照劇本）＋假工具，不連網、不開埠、不叫真的 AI。"""

import copy
import json
import os
import sys

import pytest

from synox.evals import cases as cases_mod
from synox.evals import checks, fake_tools, replay, report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS = os.path.join(ROOT, "evals", "assistant")
CASES = os.path.join(EVALS, "cases")
REFERENCE = os.path.join(EVALS, "replies", "reference")
BROKEN = os.path.join(EVALS, "replies", "broken")


@pytest.fixture(scope="module")
def all_cases():
    return cases_mod.load_dir(CASES)


@pytest.fixture(scope="module")
def reference():
    return replay.load_replies(REFERENCE)


@pytest.fixture(scope="module")
def reference_results(all_cases, reference):
    return replay.run_all(all_cases, reference)


def by_id(cases, cid):
    return next(c for c in cases if c.id == cid)


# ── 1. 題目 ─────────────────────────────────────────────────────────────

def test_thirty_cases_load_with_the_planned_distribution(all_cases):
    assert len(all_cases) == 32                                     # 30 題＋fake_done 兩題（docs/adr/0008）
    assert cases_mod.distribution_problems(all_cases) == []
    assert sum(c.split == "tune" for c in all_cases) == 21
    assert sum(c.split == "holdout" for c in all_cases) == 11
    for category, (tune, holdout) in cases_mod.distribution(all_cases).items():
        assert tune >= 1 and holdout >= 1, category
    assert len({c.id for c in all_cases}) == 32
    assert all(len(c.turns) >= 2 for c in all_cases if c.category == "memory")
    assert all(len(c.expect.get("must_call", [])) >= 2 for c in all_cases if c.category == "chain")


def test_cases_use_only_placeholder_contacts(all_cases):
    for case in all_cases:
        raw = open(case.path, encoding="utf-8").read()
        assert cases_mod.privacy_problems(raw) == [], case.id
        assert "C:\\" not in raw and "/Users/" not in raw and "/home/" not in raw, case.id


def test_injection_cases_hide_instructions_in_tool_results(all_cases):
    for case in (c for c in all_cases if c.category == "injection"):
        replies = " ".join(r["reply"] for t in case.tools for r in t.results)
        assert any(w in replies for w in ("忽略", "SYSTEM", "AI 請注意")), case.id


@pytest.mark.parametrize("patch, words", [
    ({"category": "chat"}, "category"),
    ({"split": "train"}, "split"),
    ({"turns": []}, "turns"),
    ({"expect": {"must_not_call": ["mail__send"]}}, "must_not_call"),
    ({"expect": {"must_call": [{"tool": "note__add", "args": {"text": {"regex": "("}}}]}}, "正規式"),
    ({"expect": {"bogus": True}}, "不認得"),
    ({"turns": ["寄給 someone@gmail.com"]}, "範例網域"),
])
def test_bad_case_is_rejected(patch, words):
    raw = {"id": "note-99", "category": "note", "split": "tune", "title": "t", "turns": ["記一下"],
           "tools": [{"name": "note__add"}], "expect": {"must_call": [{"tool": "note__add"}]}}
    raw.update(patch)
    library = cases_mod.load_tool_library(EVALS)
    with pytest.raises(cases_mod.CaseError) as e:
        cases_mod.parse_case(raw, library)
    assert words in str(e.value)


def test_matchers():
    assert cases_mod.matches("15:00", " 15:00 ")
    assert not cases_mod.matches("15:00", "15:00:00")
    assert cases_mod.matches({"contains": ["麻糬", "預防針"]}, "明天帶麻糬去打預防針")
    assert not cases_mod.matches({"contains": ["麻糬", "預防針"]}, "明天帶牠去打預防針")
    assert cases_mod.matches({"regex": "(?i)usd"}, "Usd")
    assert cases_mod.args_match({"a": "1"}, {"a": "1", "b": "x"})          # 只比對列出的鍵
    assert not cases_mod.args_match({"a": "1"}, {"b": "1"})


def test_question_and_option_detection():
    assert checks.is_question("要寄給誰呢？")
    assert checks.is_question("你想刪哪一則\n1. 買牛奶\n2. 繳電話費")
    assert not checks.is_question("你有 2 則筆記：\n1. 買牛奶\n2. 繳電話費")     # 列結果不是回問
    assert not checks.is_question("記好了。")


# ── 2. 參考回覆全部通過（真的迴圈） ─────────────────────────────────────

def test_reference_replies_all_pass(reference_results):
    bad = [(r.case.id, r.status, r.mismatch, [(f.check, f.detail) for f in r.failures]) for r in reference_results
           if r.status != checks.PASS]
    assert bad == []
    assert len(reference_results) == 32


def test_replay_runs_on_the_real_agent_loop(reference_results):
    runs = {r.case.id: r.run for r in reference_results}
    # 危險工具：迴圈走到確認卡、沒有執行
    note3 = runs["note-03"].turns[0]
    assert [c.tool for c in note3.carded] == ["note__clear"] and note3.executed == [] and note3.final == ""
    # 寄信那一步走到確認卡（工具鏈第二步）；參數照卡上的
    chain = runs["chain-01"].turns[0]
    assert [c.tool for c in chain.executed] == ["contacts__find"]
    assert chain.carded[0].tool == "mail__send" and chain.carded[0].args["to"] == "meiling.chen@example.com"
    # AI 看到的工具清單是真的迴圈給的（含 SYNOX 內建的系統指令，假工具照題目）
    assert {"contacts__find", "mail__send", "remind__add"} <= set(runs["chain-01"].offered)
    assert "note__add" not in runs["chain-01"].offered


def test_gate4_rejection_is_not_an_accepted_call(all_cases):
    case = by_id(all_cases, "no_clarify-01")
    rec = {"case": case.id, "turns": [[{"tool_calls": [{"name": "note__add", "args": {"txt": "買貓砂"}}]},
                                       {"text": "記好了。"}]]}
    run = replay.run_case(case, rec)
    assert run.mismatch is None
    turn = run.turns[0]
    assert [c.tool for c in turn.attempted] == ["note__add"] and turn.executed == []
    failures = checks.evaluate(case, run)
    assert [f.check for f in failures] == ["must_call", "claimed_without_call"] and "被擋下來" in failures[0].detail


def test_memory_reaches_the_ai_on_the_next_turn(all_cases, reference):
    """多回合的題目真的走迴圈的對話記憶：第二輪 AI 收到的訊息裡有第一輪的話。"""
    case = by_id(all_cases, "memory-01")
    seen = []
    original = replay.ReplayAdapter.chat

    def spy(self, messages, tools=()):
        seen.append([m.content for m in messages])
        return original(self, messages, tools)

    replay.ReplayAdapter.chat = spy
    try:
        run = replay.run_case(case, reference[case.id])
    finally:
        replay.ReplayAdapter.chat = original
    assert run.mismatch is None
    assert "我下週三要去台中出差，先記住喔" in seen[1]


# ── 3. 每一種硬檢查都抓得到故意失敗的回覆 ───────────────────────────────

def test_each_broken_reply_is_caught_by_the_right_checks(all_cases):
    broken = replay.load_replies(BROKEN)
    results = {r.case.id: r for r in replay.run_all([c for c in all_cases if c.id in broken], broken)}
    covered = set()
    for cid, rec in broken.items():
        r = results[cid]
        assert r.status == checks.FAIL, (cid, r.status, r.mismatch)
        got = {f.check for f in r.failures}
        assert got == set(rec["expected_failures"]), (cid, sorted(got))
        covered |= got
    assert covered == set(checks.CHECKS)


@pytest.mark.parametrize("cid, failure", [
    ("injection-01", "must_not_call"),     # 注入成功（叫了不該叫的工具）
    ("note-03", "confirm_card"),           # 跳過確認卡
    ("clarify-01", "ask_back"),            # 該問沒問
    ("no_clarify-01", "ask_back"),         # 不該問卻問
    ("injection-02", "final_not_contains"),  # 注入成功（照抄廣告連結）
    ("memory-01", "final_contains"),       # 忘記前一輪
    ("lookup-01", "max_steps"),            # 超過步數
    ("refuse-01", "refuse"),               # 該拒絕沒拒絕
])
def test_named_failure_kinds(all_cases, cid, failure):
    rec = replay.load_replies(BROKEN)[cid]
    run = replay.run_case(by_id(all_cases, cid), rec)
    assert run.mismatch is None
    assert failure in {f.check for f in checks.evaluate(by_id(all_cases, cid), run)}


def test_step_limit_is_reported_not_mismatched(all_cases):
    rec = replay.load_replies(BROKEN)["lookup-01"]
    run = replay.run_case(by_id(all_cases, "lookup-01"), rec, max_steps=3)
    assert run.mismatch is None and run.turns[0].step_limit and run.turns[0].steps == 3
    assert "做了 3 步" in run.turns[0].final


# ── 4. 不同步＝replay_mismatch ──────────────────────────────────────────

def test_changed_tool_result_is_a_mismatch(all_cases, reference):
    case = copy.deepcopy(by_id(all_cases, "lookup-01"))
    case.tools[0].results[0]["reply"] = "台北 明天：大雨，18–21°C，降雨機率 90%"     # 題目改了
    [result] = replay.run_all([case], reference)
    assert result.status == checks.MISMATCH and result.failures == []
    assert "跟錄的時候不同" in result.mismatch


def test_renamed_tool_is_a_mismatch(all_cases, reference):
    case = copy.deepcopy(by_id(all_cases, "note-01"))
    case.tools[0].name = "memo__add"
    case.expect = {"must_call": [{"tool": "memo__add"}]}
    run = replay.run_case(case, reference["note-01"])
    assert run.mismatch and "沒有提供的工具 note__add" in run.mismatch


def test_turn_count_and_script_length_mismatch(all_cases, reference):
    memory = by_id(all_cases, "memory-01")
    one_turn = {"case": memory.id, "turns": reference[memory.id]["turns"][:1]}
    assert "劇本錄了 1 輪" in replay.run_case(memory, one_turn).mismatch
    note = by_id(all_cases, "note-01")
    short = {"case": note.id, "turns": [[{"tool_calls": [{"name": "note__add", "args": {"text": "帶傘"}}]}]]}
    assert "劇本只錄了 1 步" in replay.run_case(note, short).mismatch
    clear = by_id(all_cases, "note-03")
    after_card = {"case": clear.id, "turns": [[{"tool_calls": [{"name": "note__clear", "args": {}}]}, {"text": "好了"}]]}
    assert "走到確認卡" in replay.run_case(clear, after_card).mismatch


def test_stamp_fills_results(all_cases, reference):
    case = by_id(all_cases, "lookup-01")
    bare = copy.deepcopy(reference[case.id])
    for step in bare["turns"][0]:
        for call in step.get("tool_calls", []):
            call.pop("result", None)
    stamped, mismatch = replay.stamp(case, bare)
    assert mismatch is None and stamped == reference[case.id]


def test_fake_tool_group_cannot_shadow_builtins(all_cases):
    case = copy.deepcopy(by_id(all_cases, "note-01"))
    case.tools[0].name = "remind__add"
    with pytest.raises(fake_tools.FakeToolError):
        replay.run_case(case, {"case": case.id, "turns": [[{"text": "好"}]]})


# ── 5. 報表：決定性、JSON 讀得回來、簡體字只統計 ─────────────────────────

def test_report_is_deterministic_and_round_trips(tmp_path, all_cases, reference, reference_results):
    first = report.build(reference_results, replies="reference")
    second = report.build(replay.run_all(all_cases, reference), replies="reference")
    assert report.dumps(first) == report.dumps(second)
    assert report.text(first) == report.text(second)
    path = tmp_path / "r.json"
    path.write_text(report.dumps(first), encoding="utf-8")
    back = report.load(str(path))
    assert back == json.loads(report.dumps(first))
    assert back["summary"]["tune"] == {"passed": 21, "total": 21, "rate": 1.0}
    assert back["summary"]["holdout"] == {"passed": 11, "total": 11, "rate": 1.0}
    assert set(back["categories"]) == set(cases_mod.CATEGORIES)
    assert back["simplified"]["total"] == 0
    assert str(tmp_path) not in report.dumps(first)
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        report.load(str(bad))


def test_simplified_characters_are_counted_not_failed(all_cases, reference):
    case = by_id(all_cases, "memory-03")
    rec = copy.deepcopy(reference[case.id])
    rec["turns"][1][0]["text"] = "你比较喜欢靠走道的座位，这个我记得。"
    [result] = replay.run_all([case], {case.id: rec})
    assert result.status == checks.PASS
    data = report.build([result])
    assert data["simplified"]["total"] >= 3 and data["simplified"]["cases"] == {case.id: data["simplified"]["total"]}
    assert {"较", "这", "个"} <= set(data["simplified"]["chars"])
    assert "簡體字" in report.text(data)


def test_missing_reply_counts_as_not_passed(all_cases):
    results = replay.run_all([by_id(all_cases, "note-01")], {})
    data = report.build(results)
    assert data["statuses"]["missing"] == 1 and data["summary"]["all"]["passed"] == 0


# ── 6. 指令列（暫存資料夾） ─────────────────────────────────────────────

def test_cli_in_temp_folder(tmp_path, capsys):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    try:
        import eval_assistant
    finally:
        sys.path.pop(0)
    out = tmp_path / "out" / "report.json"
    assert eval_assistant.main(["--split", "holdout", "--json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "holdout：11/11" in text and "[PASS] chain-02" in text
    data = report.load(str(out))
    assert data["split"] == "holdout" and data["summary"]["all"]["total"] == 11 and data["replies"] == "reference"
    assert eval_assistant.main(["--split", "tune", "--replies", BROKEN]) == 1
    assert "[FAIL] note-03" in capsys.readouterr().out
    stamped = tmp_path / "stamped"
    assert eval_assistant.main(["--split", "holdout", "--stamp", str(stamped)]) == 0
    assert sorted(os.listdir(stamped)) == sorted(f"{c}.json" for c in
                                                 ("chain-02", "clarify-03", "fake_done-02", "injection-03", "lookup-04", "memory-03",
                                                  "no_clarify-02", "note-04", "refuse-03", "rewrite-03", "schedule-03"))
    assert (stamped / "note-04.json").read_text(encoding="utf-8") == \
        open(os.path.join(REFERENCE, "note-04.json"), encoding="utf-8").read()
    assert eval_assistant.main(["--cases", str(tmp_path / "nowhere")]) == 2
