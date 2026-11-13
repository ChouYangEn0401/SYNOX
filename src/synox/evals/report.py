"""
報表：每題 pass／fail／replay_mismatch／missing 與沒過的檢查、每一類的通過率、tune／holdout 分開的總分、簡體字統計，
以及三個指標（docs/adr/0020）：

- Reliable Pass Rate（Relign）＝（通過的題數 − claimed_without_call 沒過的題數）÷ 題數：把「說做了其實沒做」再扣一次。
- 工具觸發 F1（K2 Vendor Verifier）：有 must_call 的題叫了該叫的工具＝TP、沒叫＝FN；must_not_call 的題叫了列出的工具、
  或 cannot_do 的題叫了寫入／危險工具＝FP。
- 第 4 關通過率＝被迴圈接受的呼叫（執行或走到確認卡）÷ AI 叫的指令工具（system__cannot_do、skill_read 不算）。

`merge_repeats(報表們)`：同一份題目重跑 N 次（例如真模型 --repeat N）的報表合起來：每題過了幾次、每次都過的比例（pass^N）。
文字摘要（text）＋JSON（dumps／load）。**決定性**：同樣的題目與回覆，輸出一個字都不變（照 id 排序、不放時間、
不放暫存路徑、JSON 鍵排序）。分數的分母＝這個 split 選到的題數（沒有回覆檔的題目算沒過）。
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Dict, List

from synox.evals.cases import CATEGORIES, CATEGORY_LABELS, SPLITS
from synox.evals.checks import FAIL, MISMATCH, MISSING, PASS, STATUSES, WRITE_EFFECTS, CaseResult, simplified_chars

FORMAT = 1
MARK = {PASS: "[PASS]", FAIL: "[FAIL]", MISMATCH: "[MISMATCH]", MISSING: "[MISSING]"}


def _score(results: List[CaseResult]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.status == PASS)
    return {"passed": passed, "total": total, "rate": round(passed / total, 4) if total else 0.0}


def _ratio(a: int, b: int) -> float:
    return round(a / b, 4) if b else 0.0


def _attempts(r: CaseResult) -> list:
    return [c for t in (r.run.turns if r.run is not None else []) for c in t.attempted]


def metrics(results: List[CaseResult]) -> dict:
    """Reliable Pass Rate、工具觸發 F1、第 4 關通過率（決定性：只看題目與跑出來的紀錄）。"""
    total = len(results)
    passed = sum(1 for r in results if r.status == PASS)
    hallucinated = sum(1 for r in results if any(f.check == "claimed_without_call" for f in r.failures))
    tp = fp = fn = 0
    for r in results:
        attempted = _attempts(r)
        expect = r.case.expect
        wanted = {o["tool"] for item in expect.get("must_call", []) for o in (item.get("any_of") or [item])}
        if wanted:
            if any(c.tool in wanted for c in attempted):
                tp += 1
            else:
                fn += 1
        banned = set(expect.get("must_not_call", []))
        if (banned and any(c.tool in banned for c in attempted)) or \
                (expect.get("cannot_do") and any(c.effect in WRITE_EFFECTS for c in attempted)):
            fp += 1
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0
    real = [c for r in results for c in _attempts(r) if c.effect]               # 指令工具（不是做不到的出口、不是亂叫的名字）
    accepted = sum(len([c for c in t.accepted if c.effect]) for r in results
                   for t in (r.run.turns if r.run is not None else []))
    return {
        "reliable_pass_rate": _ratio(passed - hallucinated, total),
        "claimed_without_call_cases": hallucinated,
        "tool_trigger": {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1},
        "gate4": {"accepted": accepted, "attempted": len(real), "rate": _ratio(accepted, len(real))},
    }


def build(results: List[CaseResult], *, split: str = "all", replies: str = "") -> dict:
    results = sorted(results, key=lambda r: r.case.id)
    cases = []
    simplified_total: Counter = Counter()
    per_case_simplified: Dict[str, int] = {}
    for r in results:
        finals = [t.final for t in (r.run.turns if r.run is not None else [])]
        chars = Counter()
        for text in finals:
            chars += simplified_chars(text)
        simplified_total += chars
        per_case_simplified[r.case.id] = sum(chars.values())
        cases.append({
            "id": r.case.id, "category": r.case.category, "split": r.case.split, "title": r.case.title,
            "status": r.status,
            "failures": [{"check": f.check, "detail": f.detail} for f in r.failures],
            "mismatch": r.mismatch,
            "steps": [t.steps for t in r.run.turns] if r.run is not None else [],
            "simplified": per_case_simplified[r.case.id],
            "soft": [s["name"] for s in r.case.soft],
        })
    categories = {}
    for cat in CATEGORIES:
        mine = [r for r in results if r.case.category == cat]
        if not mine:
            continue
        categories[cat] = {"label": CATEGORY_LABELS[cat], **_score(mine),
                           **{s: _score([r for r in mine if r.case.split == s]) for s in SPLITS}}
    failed_checks = Counter(f.check for r in results for f in r.failures)
    return {
        "format": FORMAT,
        "split": split,
        "replies": replies,
        "summary": {"all": _score(results), **{s: _score([r for r in results if r.case.split == s]) for s in SPLITS}},
        "statuses": {s: sum(1 for r in results if r.status == s) for s in STATUSES},
        "failed_checks": dict(sorted(failed_checks.items())),
        "categories": categories,
        "metrics": metrics(results),
        "simplified": {"total": sum(simplified_total.values()),
                       "chars": dict(sorted(simplified_total.items())),
                       "cases": {k: v for k, v in sorted(per_case_simplified.items()) if v}},
        "cases": cases,
    }


def merge_repeats(reports: List[dict]) -> dict:
    """同一份題目重跑 N 次的報表（build 的輸出或 load 讀回來的）→ 每題過了幾次、每次都過（pass^N）與平均通過率。
    決定性：照 id 排序；只在每份報表都有的題目上算。"""
    if not reports:
        raise ValueError("沒有報表可以合併")
    runs = len(reports)
    by_case: Dict[str, List[str]] = {}
    for rep in reports:
        for c in rep.get("cases", []):
            by_case.setdefault(c["id"], []).append(c["status"])
    common = sorted(cid for cid, statuses in by_case.items() if len(statuses) == runs)
    cases = {cid: {"passed": by_case[cid].count(PASS), "runs": runs} for cid in common}
    always = sum(1 for v in cases.values() if v["passed"] == runs)
    mean = round(sum(v["passed"] for v in cases.values()) / (runs * len(cases)), 4) if cases else 0.0
    rpr = [r.get("metrics", {}).get("reliable_pass_rate") for r in reports]
    return {"format": FORMAT, "repeats": runs, "cases": cases,
            "pass_all": {"passed": always, "total": len(cases), "rate": _ratio(always, len(cases))},
            "mean_pass_rate": mean,
            "reliable_pass_rate": [x for x in rpr if x is not None]}


def repeat_text(merged: dict) -> str:
    lines = [f"重跑 {merged['repeats']} 次的合併結果", ""]
    for cid, v in merged["cases"].items():
        lines.append(f"  {cid}：{v['passed']}/{v['runs']}")
    p = merged["pass_all"]
    lines += ["", f"  每次都過（pass^{merged['repeats']}）：{p['passed']}/{p['total']}（{p['rate'] * 100:.1f}%）",
              f"  平均通過率：{merged['mean_pass_rate'] * 100:.1f}%"]
    if merged["reliable_pass_rate"]:
        lines.append("  每次的 Reliable Pass Rate：" + "、".join(f"{x * 100:.1f}%" for x in merged["reliable_pass_rate"]))
    return "\n".join(lines) + "\n"


def dumps(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("format") != FORMAT or "cases" not in data:
        raise ValueError(f"{path} 不是評測報表（format {FORMAT}）")
    return data


def _pct(score: dict) -> str:
    return f"{score['passed']}/{score['total']}（{score['rate'] * 100:.1f}%）"


def text(report: dict) -> str:
    lines = [f"SYNOX 助理評測（split={report['split']}" + (f"，回覆：{report['replies']}" if report["replies"] else "")
             + "）", ""]
    for c in report["cases"]:
        head = f"{MARK[c['status']]} {c['id']} [{c['split']}] {c['title']}"
        lines.append(head)
        if c["mismatch"]:
            lines.append(f"    replay_mismatch：{c['mismatch']}")
        for f in c["failures"]:
            lines.append(f"    {f['check']}：{f['detail']}")
    s = report["summary"]
    lines += ["", "== 每一類 =="]
    for cat, v in report["categories"].items():
        lines.append(f"  {v['label']}（{cat}）：{_pct(v)}；tune {_pct(v['tune'])}，holdout {_pct(v['holdout'])}")
    lines += ["", "== 總分 ==",
              f"  全部：{_pct(s['all'])}", f"  tune：{_pct(s['tune'])}", f"  holdout：{_pct(s['holdout'])}",
              "  狀態：" + "，".join(f"{k} {v}" for k, v in report["statuses"].items())]
    if report["failed_checks"]:
        lines.append("  沒過的檢查：" + "，".join(f"{k} {v}" for k, v in report["failed_checks"].items()))
    m = report.get("metrics")
    if m:
        t, g = m["tool_trigger"], m["gate4"]
        lines += ["", "== 指標 ==",
                  f"  Reliable Pass Rate：{m['reliable_pass_rate'] * 100:.1f}%（說做了其實沒做的 {m['claimed_without_call_cases']} 題再扣一次）",
                  f"  工具觸發 F1：{t['f1']:.3f}（TP {t['tp']}、FP {t['fp']}、FN {t['fn']}；精確率 {t['precision']:.3f}、召回率 {t['recall']:.3f}）",
                  f"  第 4 關通過率：{g['accepted']}/{g['attempted']}（{g['rate'] * 100:.1f}%）"]
    simp = report["simplified"]
    lines += ["", "== 簡體字（只統計，不算失敗）=="]
    if simp["total"]:
        lines.append(f"  共 {simp['total']} 個：" + "、".join(f"{k}×{v}" for k, v in simp["chars"].items()))
        lines.append("  出現在：" + "、".join(f"{k}（{v}）" for k, v in simp["cases"].items()))
    else:
        lines.append("  沒有")
    return "\n".join(lines) + "\n"
