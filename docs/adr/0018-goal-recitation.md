# ADR 0018：多步時覆誦目標

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/small_model_harness`）
- 依據：研究交接書前 8 項的第 7 項（卡片 E5（Manus 的 recitation））
- 程式：`src/synox/agent/loop.py`（`recite_line`、`goal_of`）、`src/synox/agent/room.py`（`goal_of`）

## 決定

1. 跟 ADR 0017 同一個開關（`llm.prompt_tail`）。開著時，從第二步（step ≥ 1）起，每個工具結果後面（分隔符外面，系統說的）附一行
   「（目標：{使用者原句前 80 字}；做完就回答，做不到就說）」。第一步不附（目標還在眼前）。
2. 只用使用者說的話，不含任何工具參數。頻道 AI 去掉發話者標籤與訊息分隔符再取。原生與文字協定都附。
3. 會多幾十個 token；context 預算（0015）會把它算進去。
