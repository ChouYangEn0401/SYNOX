"""完成宣稱檢查的離線標定（docs/adr/0008「標定」）：不載入任何模型，只用已存的回覆。

tests/fixtures/claims_calibration.json 每一則：
  source = real       本地模型的真實回覆（qwen3.5:9b、qwen3.6:27b 在 Ollama 上跑 evals 題目時錄下的 /v1 回應原文；
                      只收「這一步沒有工具呼叫」的那幾則——閘門只在這裡跑），ledger＝同一輪前面真的叫過的工具
           scripted   evals/assistant/replies/reference 與 broken 的劇本回覆（fake_done 的劇本取自 real，不重複算）
           synthetic  手寫的常見回覆（含刻意難的反例）：**跟詞表是同一個人寫的，會高估準確度**，所以分開報
  block = 人工標的「該攔」（宣稱做了、這一輪沒有成功的寫入／危險工具）

誤判（FP）＝不該攔卻被攔（REJECT），或不該介入卻被要求重試（NUDGE）；漏抓（FN）＝該攔卻放行。目標 FP ≤ 2%。
"""

import json
import os

import pytest

from synox.agent import claims

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "claims_calibration.json")


def _load():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _verdict(sample):
    ledger = [claims.Evidence(e["tool"], e["effect"], e["ok"]) for e in sample["ledger"]]
    return claims.verdict(sample["text"], ledger)


def _rates(samples):
    neg = [s for s in samples if not s["block"]]
    pos = [s for s in samples if s["block"]]
    fp = [s["id"] for s in neg if _verdict(s).kind != claims.PASS]
    fn = [s["id"] for s in pos if _verdict(s).kind != claims.REJECT]
    return {"negatives": len(neg), "positives": len(pos), "fp": fp, "fn": fn}


def test_fixture_shape():
    samples = _load()
    assert len(samples) == 116
    assert {s["source"] for s in samples} == {"real", "scripted", "synthetic"}
    assert len({s["id"] for s in samples}) == len(samples)
    real = [s for s in samples if s["source"] == "real"]
    assert len(real) == 23 and sum(s["block"] for s in real) == 3
    assert "C:\\" not in open(FIXTURE, encoding="utf-8").read()


@pytest.mark.parametrize("source, negatives, positives", [
    ("real", 20, 3), ("scripted", 37, 1), ("synthetic", 40, 15),
])
def test_calibration_by_source(source, negatives, positives):
    r = _rates([s for s in _load() if s["source"] == source])
    assert (r["negatives"], r["positives"]) == (negatives, positives)
    assert r["fp"] == [], r["fp"]              # ADR 0008 寫的數字：三組都是 0 誤判
    assert r["fn"] == [], r["fn"]


def test_false_positive_rate_target():
    r = _rates(_load())
    rate = len(r["fp"]) / r["negatives"]
    assert r["negatives"] == 97 and rate <= 0.02, (rate, r["fp"])


def test_the_three_real_false_completions_are_caught_for_the_right_reason():
    by_id = {s["id"]: s for s in _load()}
    assert _verdict(by_id["9b-native/note-01#0"]).reason == claims.FORGED              # 自己印分隔符與假 JSON
    assert _verdict(by_id["9b-text/note-01#0"]).reason == claims.FORGED                # 自己寫〔工具結果〕
    assert _verdict(by_id["9b-text/no_clarify-01#0"]).reason == claims.CLAIM_WITHOUT_CALL
    # 真的叫了工具之後說「已記下」「已設定」：放行（27b note-01 叫的是內建的 remind__add）
    assert _verdict(by_id["27b-native/note-01#1"]).kind == claims.PASS
    assert _verdict(by_id["9b-native/no_clarify-01#1"]).kind == claims.PASS
