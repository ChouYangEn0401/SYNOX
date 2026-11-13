# ADR 0015：Context 預算：估算與 Qwen-Agent 式分級截斷

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/small_model_harness`）
- 依據：研究交接書前 8 項的第 6 項（卡片 E1、E2、E5）
- 程式：`src/synox/agent/context.py`（`estimate`、`fit`、`note_text`、`context_limit`）、`src/synox/agent/loop.py`（`_fit`、`_budget_note`）

## 決定

1. 預算上限＝`llm.context_size`（ADR 0007 的同一個鍵；kind=local 以外的來源也收）。**沒設＝不裁**，跟以前一樣。
   預算＝context_size − 回覆上限（`llm.max_tokens`）− 工具規格的估算。
2. `estimate`：CJK 字 1、其他每 4 字 1、×1.15（留 15%）；每則訊息另加 4。只是粗估，偏保守。
3. `fit` 的順序（Qwen-Agent `_truncate_input_messages_roughly`）：丟最舊的歷史（使用者／AI 成對）→ 這一輪除最後一則以外的工具結果
   換成「（省略）」→ 截最後一則工具結果（保頭 2/3、尾 1/3）→ 拿掉系統提示裡的 soul.md 區塊。系統提示其他部分與這一輪使用者說的話不裁；
   都做完還超過＝`over`，照送並告訴使用者。
4. 每次 `adapter.chat` 前對**副本**套用（對話紀錄 append-only，E5）；步數總結那次也套用。
5. **不靜默**：每次有裁就 `logging.warning("[AGENT] context budget: …")`；這一輪結束時另送一則「⚠️ 對話超過 context 預算…省略了：…」
   （不進對話記憶）。ADR 0007 的伺服器端截斷提醒照舊。

## 跟規格不同

- 規格的 limit 寫 `llm.num_ctx`／`llm.context_tokens`；SYNOX 已有 `llm.context_size`（ADR 0007），沿用它，不另開鍵。
- 第 (4) 步規格寫「裁 soul block」；soul 包在分隔符裡，從中間裁會弄壞結尾的分隔符，所以整段拿掉換成一行說明。
- 沒做 Qwen-Agent「system 佔滿預算直接拒」：照送並告訴使用者（拒絕＝整輪沒回應，對個人助理更糟）。
