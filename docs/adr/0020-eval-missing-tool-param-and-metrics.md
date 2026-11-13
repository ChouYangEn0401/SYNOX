# ADR 0020：評測擴充：missing_tool／missing_param、Reliable Pass Rate、工具觸發 F1、第 4 關通過率

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/small_model_harness`）
- 依據：研究交接書前 8 項的第 8 項（卡片 H1、H2）
- 程式：`src/synox/evals/cases.py`、`checks.py`（`cannot_do`）、`report.py`（`metrics`、`merge_repeats`）、`scripts/eval_assistant.py --merge`、`evals/assistant/cases/missing_*`

## 決定

1. 新類別 `missing_tool`（工具清單故意沒有合適的工具）、`missing_param`（缺參數、要回問）各 2 題，tune／holdout 各一（共 36 題）。
2. 新檢查 `cannot_do`（expect 寫 true 才跑）：整題不能叫寫入／危險工具，而且最後一輪要呼叫 `system__cannot_do`、或回覆有拒絕標記、
   或在回問。missing_param 用既有的 `ask_back`＋`must_not_call`。
3. 報表多三個指標（JSON 的 `metrics`、文字的「== 指標 ==」）：
   - Reliable Pass Rate＝（通過題數 − claimed_without_call 沒過的題數）÷ 題數（Relign）；
   - 工具觸發 F1：有 must_call 的題叫了該叫的＝TP、沒叫＝FN；must_not_call 的題叫了列出的、或 cannot_do 題叫了寫入工具＝FP（K2VV）；
   - 第 4 關通過率＝被接受的指令工具呼叫 ÷ AI 叫的指令工具（system__cannot_do 不算）。
4. `report.merge_repeats` 與 `eval_assistant.py --merge a.json b.json …`：同一份題目重跑 N 次的報表合起來（每題幾次過、pass^N、平均）。

## 跟規格不同

- `claimed_without_call`、`any_of` 已在 ADR 0008 做完，這裡只補測試。
- `tools/local-llm-live/live.py --repeat N` 在 SYNOX_Plans，**不改它**；SYNOX 這邊只提供讀它輸出的合併（`--merge`），
  格式要求寫在 evals README。重放本身是決定性的，在 SYNOX 加 `--repeat` 沒有意義。
- 寫參考回覆時發現：「告訴我日期和時間，我再幫你加進行事曆。」會被完成宣稱詞表抓成宣稱（「我再…」不在排除字裡）。
  詞表只能加嚴、改了要重新標定，這次沒改，換了參考回覆的說法；記在這裡給下一次標定。
