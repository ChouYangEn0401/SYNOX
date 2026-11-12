"""
報表：每題 pass／fail／replay_mismatch／missing 與沒過的檢查、每一類的通過率、tune／holdout 分開的總分、簡體字統計。
文字摘要（text）＋JSON（dumps／load）。**決定性**：同樣的題目與回覆，輸出一個字都不變（照 id 排序、不放時間、
不放暫存路徑、JSON 鍵排序）。分數的分母＝這個 split 選到的題數（沒有回覆檔的題目算沒過）。
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Dict, List

from synox.evals.cases import CATEGORIES, CATEGORY_LABELS, SPLITS
from synox.evals.checks import FAIL, MISMATCH, MISSING, PASS, STATUSES, CaseResult, simplified_chars

FORMAT = 1
MARK = {PASS: "[PASS]", FAIL: "[FAIL]", MISMATCH: "[MISMATCH]", MISSING: "[MISSING]"}


def _score(results: List[CaseResult]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.status == PASS)
    return {"passed": passed, "total": total, "rate": round(passed / total, 4) if total else 0.0}


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
        "simplified": {"total": sum(simplified_total.values()),
                       "chars": dict(sorted(simplified_total.items())),
                       "cases": {k: v for k, v in sorted(per_case_simplified.items()) if v}},
        "cases": cases,
    }


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
    simp = report["simplified"]
    lines += ["", "== 簡體字（只統計，不算失敗）=="]
    if simp["total"]:
        lines.append(f"  共 {simp['total']} 個：" + "、".join(f"{k}×{v}" for k, v in simp["chars"].items()))
        lines.append("  出現在：" + "、".join(f"{k}（{v}）" for k, v in simp["cases"].items()))
    else:
        lines.append("  沒有")
    return "\n".join(lines) + "\n"
