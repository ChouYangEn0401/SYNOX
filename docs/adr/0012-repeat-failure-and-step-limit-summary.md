# ADR 0012：同一個呼叫連續失敗就停、步數用完請 AI 總結

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/completion_guard`）
- 依據：研究交接書前 8 項的第 4 項（卡片 C1：OpenManus `is_stuck`、AgentScope `tool_retries_limit`、OpenHands `stuck.py`；
  卡片 C2：AgentScope v0 `_summarizing`）
- 程式：`src/synox/agent/loop.py`（`call_key`、`REPEAT_HINT`／`REPEAT_STOP`、`_out_of_steps`）、`src/synox/agent/claims.py`（`summarize_on`）

## 決定

1. **同一個呼叫連續失敗**：「同一個」＝工具名＋參數值完全一樣（只在記憶體比，不寫 log；規格寫的 `arg_shape` 只有欄位名與長度，
   金額 80 與 90 會被當成同一個，所以改用值）。「失敗」＝`call_tool` 的 ok=False（第 4 關、失敗信封、不認得的工具、缺參數）。
   中間有成功或換了別的呼叫就重算。第 2 次：交回 AI 的結果後面（分隔符外面，是系統說的）附「（這個呼叫已連續失敗 2 次：換個參數、
   換個工具，或呼叫 system__cannot_do）」；第 3 次：結束這一輪，送「（同一個動作連續失敗 3 次，先停。…）」。對所有來源都生效
   （只在重複失敗時才有差別，正常的對話一個字都不變）。
2. **步數用完的總結**：`llm.summarize_on_limit` = `"auto"`（預設）｜`"on"`｜`"off"`。auto 跟 ADR 0008 同一個判斷（本地／私網來源才開）。
   開著時再叫一次**不帶工具**的 `adapter.chat(messages + [USER: "步數用完。用一兩句告訴使用者做到哪裡、還差什麼。不要呼叫工具。"])`，
   最多 400 字，前面一律加「（做了 N 步還沒做完，先停在這裡。）」；總結裡宣稱做完了而沒有寫入證據＝照 ADR 0008 照實說並附原文。
   關著、額度用完、叫不動、回空白＝照舊那一句。

## 跟規格不一樣的地方

規格寫 `summarize_on_limit` 預設 true。這裡預設 auto：規格本身的原則是「預設值不改變雲端模型的現有行為」，多一次呼叫對雲端是錢；
另外離線評測重放錄好的劇本時，多出來的那一次呼叫會變成 replay_mismatch。本地來源預設就有（那正是 C2 想解決的「使用者看不到做到哪裡」）。

## 擋不住的

- 參數每次都改一點點的無限重試不算「同一個呼叫」，靠 max_steps 收尾。
- 總結本身也可能幻覺；閘門只擋「說做完了」這一種。
