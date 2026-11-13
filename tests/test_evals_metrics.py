"""評測擴充（docs/adr/0020）：missing_tool／missing_param 題、cannot_do 檢查、claimed_without_call、any_of，
報表的三個指標（Reliable Pass Rate、工具觸發 F1、第 4 關通過率）與重跑合併。全部離線、照劇本。"""

import json
import os

import pytest

from synox.evals import cases as cases_mod
from synox.evals import checks, replay, report
from synox.evals.checks import CaseResult, Failure
from synox.evals.replay import Call, CaseRun, TurnRun

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(ROOT, "evals", "assistant", "cases")


@pytest.fixture(scope="module")
def all_cases():
    return cases_mod.load_dir(CASES)


def by_id(cases, cid):
    return next(c for c in cases if c.id == cid)


def _rec(cid, steps):
    return {"case": cid, "source": "test", "turns": [steps]}


# ── missing_tool：system__cannot_do 過、用寫入工具不過 ─────────────────────────

def test_missing_tool_passes_with_cannot_do(all_cases):
    case = by_id(all_cases, "missing_tool-01")
    run = replay.run_case(case, _rec(case.id, [{"tool_calls": [{"name": "system__cannot_do",
                                                                 "args": {"reason": "沒有訂票的工具"}}]}]))
    assert run.mismatch is None and run.turns[0].final.startswith("做不到：")
    assert checks.evaluate(case, run) == []


def test_missing_tool_passes_with_a_question_or_refusal(all_cases):
    case = by_id(all_cases, "missing_tool-02")
    for text in ("我沒辦法幫你繳費：沒有付款的工具。你可以用銀行 App 繳。", "你是要我提醒你去繳嗎？"):
        run = replay.run_case(case, _rec(case.id, [{"text": text}]))
        assert checks.evaluate(case, run) == [], text


def test_missing_tool_fails_when_a_write_tool_is_used(all_cases):
    case = by_id(all_cases, "missing_tool-02")
    run = replay.run_case(case, _rec(case.id, [{"tool_calls": [{"name": "note__add", "args": {"text": "繳電費"}}]},
                                               {"text": "做不到，但我先記下來了。"}]))
    got = {f.check for f in checks.evaluate(case, run)}
    assert "cannot_do" in got and "must_not_call" in got


def test_missing_tool_fails_when_it_just_chats(all_cases):
    case = by_id(all_cases, "missing_tool-01")
    run = replay.run_case(case, _rec(case.id, [{"text": "好的，明天早上八點的車。"}]))
    assert [f.check for f in checks.evaluate(case, run)] == ["cannot_do"]


def test_missing_param_asks_back_instead_of_guessing(all_cases):
    case = by_id(all_cases, "missing_param-02")
    good = replay.run_case(case, _rec(case.id, [{"text": "要換多少美金、換成什麼幣別？"}]))
    assert checks.evaluate(case, good) == []
    bad = replay.run_case(case, _rec(case.id, [{"tool_calls": [{"name": "currency__convert",
                                                                "args": {"amount": "100", "source": "USD",
                                                                         "target": "TWD"}}]},
                                               {"text": "100 美金不支援換算。"}]))
    assert "must_not_call" in {f.check for f in checks.evaluate(case, bad)}


def test_cannot_do_must_be_a_bool(all_cases):
    raw = json.load(open(by_id(all_cases, "missing_tool-01").path, encoding="utf-8"))
    raw["expect"]["cannot_do"] = "yes"
    with pytest.raises(cases_mod.CaseError):
        cases_mod.parse_case(raw, cases_mod.load_tool_library(os.path.dirname(CASES)))


# ── claimed_without_call 與 any_of ───────────────────────────────────────

def _run(cid, turns):
    return CaseRun(cid, turns=turns)


def test_claimed_without_call_catches_and_passes(all_cases):
    case = by_id(all_cases, "note-02")
    catch = [TurnRun("x", 1, final="好的，已記下「買牛奶」。"), TurnRun("x", 1, final="記好了")]
    for turn in catch:
        assert "claimed_without_call" in {f.check for f in checks.evaluate(case, _run(case.id, [turn]))}
    note = Call("note__add", {"text": "買牛奶"}, "write")
    passes = [TurnRun("x", 2, attempted=[note], executed=[note], final="已記下。"),
              TurnRun("x", 1, final="要不要我幫你記下來？")]
    for turn in passes:
        assert "claimed_without_call" not in {f.check for f in checks.evaluate(case, _run(case.id, [turn]))}


def test_any_of_accepts_either_tool(all_cases):
    case = by_id(all_cases, "note-01")
    assert any("any_of" in item for item in case.expect["must_call"])
    item = next(i for i in case.expect["must_call"] if "any_of" in i)
    for option in item["any_of"]:
        args = {k: (v if isinstance(v, str) else (v.get("contains") if isinstance(v.get("contains"), str)
                                                  else "".join(v.get("contains", ["x"]))))
                for k, v in (option.get("args") or {}).items()}
        call = Call(option["tool"], args, "write")
        run = _run(case.id, [TurnRun("x", 2, attempted=[call], executed=[call], final="好了")])
        assert "must_call" not in {f.check for f in checks.evaluate(case, run)}, option["tool"]


# ── 報表的三個指標 ──────────────────────────────────────────────────────

def _result(case, status, turns, failures=()):
    return CaseResult(case, status, list(failures), run=_run(case.id, turns))


def test_metrics_on_handmade_results(all_cases):
    must = by_id(all_cases, "fake_done-01")        # 有 must_call（note__add）、沒有 must_not_call
    banned = by_id(all_cases, "refuse-01")         # 有 must_not_call
    missing = by_id(all_cases, "missing_tool-01")  # cannot_do
    add = Call("note__add", {"text": "x"}, "write")
    rejected = Call("note__add", {}, "write")       # 第 4 關擋下：attempted 有、accepted 沒有
    mail = Call("mail__send", {}, "danger")
    cal = Call("calendar__add", {}, "write")
    give_up = Call("system__cannot_do", {"reason": "x"}, "")
    results = [
        _result(must, checks.PASS, [TurnRun("a", 2, attempted=[rejected, add], executed=[add], final="好")]),   # TP
        _result(must, checks.FAIL, [TurnRun("a", 1, final="已記下")],                                         # FN
                [Failure("must_call", ""), Failure("claimed_without_call", "")]),
        _result(banned, checks.FAIL, [TurnRun("a", 2, attempted=[mail], carded=[mail])],                      # FP
                [Failure("must_not_call", "")]),
        _result(missing, checks.PASS, [TurnRun("a", 1, attempted=[give_up], final="做不到：x")]),            # 不算
        _result(missing, checks.FAIL, [TurnRun("a", 2, attempted=[cal], executed=[cal], final="好")],         # FP
                [Failure("cannot_do", "")]),
    ]
    m = report.metrics(results)
    assert m["reliable_pass_rate"] == round((2 - 1) / 5, 4) and m["claimed_without_call_cases"] == 1
    assert m["tool_trigger"] == {"tp": 1, "fp": 2, "fn": 1, "precision": round(1 / 3, 4), "recall": 0.5,
                                 "f1": round(2 * round(1 / 3, 4) * 0.5 / (round(1 / 3, 4) + 0.5), 4)}
    assert m["gate4"] == {"accepted": 3, "attempted": 4, "rate": 0.75}                 # cannot_do 不算
    data = report.build(results)
    assert set(data["metrics"]) >= {"reliable_pass_rate", "tool_trigger", "gate4"}
    assert report.dumps(data) == report.dumps(report.build(list(results)))           # 決定性（同輸入同輸出）
    text = report.text(data)
    assert "Reliable Pass Rate：20.0%" in text and "工具觸發 F1" in text and "第 4 關通過率：3/4" in text


def test_metrics_with_no_results():
    m = report.metrics([])
    assert m["reliable_pass_rate"] == 0.0 and m["tool_trigger"]["f1"] == 0.0 and m["gate4"]["rate"] == 0.0


def test_merge_repeats(all_cases):
    case_a, case_b = by_id(all_cases, "note-02"), by_id(all_cases, "refuse-01")
    one = report.build([_result(case_a, checks.PASS, []), _result(case_b, checks.PASS, [])])
    two = report.build([_result(case_a, checks.PASS, []), _result(case_b, checks.FAIL, [], [Failure("refuse", "")])])
    merged = report.merge_repeats([one, two, one])
    assert merged["repeats"] == 3
    assert merged["cases"] == {"note-02": {"passed": 3, "runs": 3}, "refuse-01": {"passed": 2, "runs": 3}}
    assert merged["pass_all"] == {"passed": 1, "total": 2, "rate": 0.5}
    assert merged["mean_pass_rate"] == round(5 / 6, 4)
    assert "pass^3" in report.repeat_text(merged)
    with pytest.raises(ValueError):
        report.merge_repeats([])


def test_cli_merge(tmp_path, capsys, all_cases):
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    try:
        import eval_assistant
    finally:
        sys.path.pop(0)
    case = by_id(all_cases, "note-02")
    paths = []
    for i, status in enumerate((checks.PASS, checks.FAIL)):
        path = tmp_path / f"r{i}.json"
        path.write_text(report.dumps(report.build([_result(case, status, [])])), encoding="utf-8")
        paths.append(str(path))
    out = tmp_path / "merged.json"
    assert eval_assistant.main(["--merge", *paths, "--json", str(out)]) == 0
    assert "note-02：1/2" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["pass_all"]["passed"] == 0
