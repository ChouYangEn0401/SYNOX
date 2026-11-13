# ADR 0014：每輪工具數上限（toolpick）與「auto」的共用判斷

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/small_model_harness`）
- 依據：研究交接書前 8 項的第 5 項（卡片 D2、D3）
- 程式：`src/synox/agent/toolpick.py`、`src/synox/agent/auto.py`、`src/synox/agent/loop.py`（`pick_tools`、退回全集）

## 決定

1. `toolpick.pick(tools, query, limit, keep=)`：一般工具 ≤ limit 原樣回；否則用使用者這句話與（名稱、說明（含 scenario）、
   參數名與參數說明）的**字元 2-gram 重疊數**排序取前 limit 個（同分照原順序），輸出照原本的順序。不用嵌入模型、不用第三方套件。
2. **永遠保留**：`system__cannot_do`、`skill_read`、系統指令（`remind__*` 與 `app.extras[SYSTEM_GROUPS_KEY]` 登記的群組）。
   挑工具不能讓「做不到」的出口消失。
3. `llm.max_tools`＝`auto`（預設）｜`0`（不限）｜1～200。**auto＝本地／弱來源 12、雲端與 Claude Code 不限**——判斷抽成
   `agent/auto.py` 的 `weak_source`／`switch_on`（completion guard、步數總結、這裡、0015～0018 共用；`claims.py` 留舊名字）。
4. 權限不在清單：模型叫了清單外、但他有權的工具，`call_tool` 照常判斷（`ai_decision`）與執行；下一步退回全集
   （文字協定會重建系統提示的工具段）。同一輪內清單不重排（D3）。
5. doctor 多一行「小模型 harness」：工具上限、context 預算、工具結果上限、本輪規則開不開。

## 跟規格不同

- 規格的 `llm.max_tools` 預設 0（不限）、文件建議 12；這裡預設 auto（本地／弱來源 12），照擁有者「上限只對本地／弱 adapter 預設啟用」。
- 分數多算了參數說明（參數名是英文、使用者多半講中文，只看名字幾乎沒有訊號）。
