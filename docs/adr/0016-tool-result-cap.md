# ADR 0016：工具結果上限（cap_result）

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/small_model_harness`）
- 依據：研究交接書前 8 項的第 6 項（卡片 E3）
- 程式：`src/synox/agent/context.py`（`cap_result`、`result_chars`）、`src/synox/agent/loop.py`（`_cap`）

## 決定

1. `call_tool` 回來、`delimit.wrap` 之前：結果超過 `llm.tool_result_chars` 字就保頭 2/3、尾 1/3，中間一行
   「（省略 N 字；工具的完整輸出已直接給使用者的部分不受影響）」。
2. `llm.tool_result_chars`＝`auto`（預設：**有 context 預算（設了 context_size）時 3000，沒有＝不限**）｜0｜字數。
   所以沒設 context_size 的設定（含所有雲端預設）結果不變。
3. 截了就寫 log（工具名、前後字數，不記內容），並列進這一輪結束時的提醒。
4. 證據帳本（ADR 0008）記的是截之前的結果；MCP 的結果也走同一條（在 loop 裡截，不改 `mcp.render_result`）。

## 跟規格不同

- 規格預設 3000（不分來源）；這裡跟 context 預算綁在一起，沒設 context_size 就不截，保持既有行為。
- 規格說 MCP 的 `render_result` 也套；MCP 結果本來就經 `call_tool` 回到迴圈，在迴圈截一次就涵蓋，沒有另外改 mcp.py。
