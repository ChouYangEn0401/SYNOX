"""Offline eval of the chat assistant: replay recorded replies on the real agent loop with fake tools, then score.

    .venv\\Scripts\\python.exe scripts\\eval_assistant.py [--cases evals\\assistant\\cases]
        [--replies evals\\assistant\\replies\\reference] [--split tune|holdout|all] [--json <report.json>]
        [--stamp <folder>] [--max-steps 6]
    .venv\\Scripts\\python.exe scripts\\eval_assistant.py --merge run1.json run2.json run3.json [--json merged.json]

No network, no ports, no real AI: the "AI" only reads the recorded replies (one <case id>.json per case).
--stamp: replay every reply once without comparing tool results and write it to <folder> with each call's
actual result filled in (use it after writing a new reference reply). --merge: combine report JSON files of the same
cases run N times (e.g. a real model with --repeat N in tools/local-llm-live): per-case passes and pass^N.
Exit code: 0 = every selected case passed, 1 = something failed / replay_mismatch / missing, 2 = bad input. How to add a case: evals/assistant/README.md.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("vendor", "src"):
    _path = os.path.join(ROOT, _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)

DEFAULT_CASES = os.path.join(ROOT, "evals", "assistant", "cases")
DEFAULT_REPLIES = os.path.join(ROOT, "evals", "assistant", "replies", "reference")


def main(argv=None) -> int:
    from synox.evals import cases as cases_mod
    from synox.evals import replay, report
    from synox.evals.checks import PASS

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=DEFAULT_CASES, help="folder of case files (default: evals/assistant/cases)")
    parser.add_argument("--replies", default=DEFAULT_REPLIES, help="folder of recorded replies, one <case id>.json each")
    parser.add_argument("--split", default="all", choices=("tune", "holdout", "all"))
    parser.add_argument("--json", default="", help="also write the report as JSON to this file")
    parser.add_argument("--stamp", default="", help="write the replies with actual tool results filled in to this folder")
    parser.add_argument("--max-steps", type=int, default=replay.DEFAULT_MAX_STEPS,
                        help="the agent loop's step limit (config llm.max_steps; default 6)")
    parser.add_argument("--merge", nargs="+", default=[], metavar="REPORT",
                        help="merge report JSON files of repeated runs (e.g. a real model run N times): per-case passes "
                             "and pass^N; nothing is replayed")
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)            # SYNOX 自己的 log 不混進報表
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # cp950 主控台印不出的字換成 ?，不要當掉
        except (AttributeError, ValueError):
            pass
    if args.merge:                               # 重跑 N 次的報表合起來（docs/adr/0020）；不重放、不叫 AI
        try:
            merged = report.merge_repeats([report.load(path) for path in args.merge])
        except (OSError, ValueError) as e:
            print(f"[X] {e}", file=sys.stderr)
            return 2
        print(report.repeat_text(merged), end="")
        if args.json:
            folder = os.path.dirname(os.path.abspath(args.json))
            os.makedirs(folder, exist_ok=True)
            with open(args.json, "w", encoding="utf-8", newline="\n") as f:
                f.write(report.dumps(merged))
        return 0
    try:
        cases = cases_mod.select(cases_mod.load_dir(args.cases), args.split)
        replies = replay.load_replies(args.replies)
    except (cases_mod.CaseError, replay.ReplayError) as e:
        print(f"[X] {e}", file=sys.stderr)
        return 2
    if args.stamp:
        os.makedirs(args.stamp, exist_ok=True)
        bad = 0
        for case in cases:
            if case.id not in replies:
                continue
            stamped, mismatch = replay.stamp(case, replies[case.id], max_steps=args.max_steps)
            with open(os.path.join(args.stamp, case.id + ".json"), "w", encoding="utf-8", newline="\n") as f:
                f.write(replay.dump_recording(stamped))
            if mismatch:
                bad += 1
                print(f"[MISMATCH] {case.id}: {mismatch}")
        print(f"stamped {sum(1 for c in cases if c.id in replies)} replies -> {args.stamp}")
        return 1 if bad else 0
    results = replay.run_all(cases, replies, max_steps=args.max_steps)
    data = report.build(results, split=args.split, replies=os.path.basename(os.path.normpath(args.replies)))
    print(report.text(data), end="")
    if args.json:
        folder = os.path.dirname(os.path.abspath(args.json))
        os.makedirs(folder, exist_ok=True)
        with open(args.json, "w", encoding="utf-8", newline="\n") as f:
            f.write(report.dumps(data))
    return 0 if results and all(r.status == PASS for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
