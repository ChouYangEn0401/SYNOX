# ADR 0011：「做不到」的出口 system__cannot_do

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/completion_guard`）
- 依據：研究交接書前 8 項的第 4 項（卡片 A3、A6；ToolBeHonest 的 `UnsolvableQuery`、Relign 的 `give_up_and_talkto_user`）
- 程式：`src/synox/agent/tools.py`（`CANNOT_DO`、`cannot_do_spec`）、`src/synox/agent/loop.py`（`cannot_do`、`cannot_do_line`）

## 決定

1. 迴圈像 `skill_read` 一樣，自己附一個偽工具 `system__cannot_do(reason)`：**不是指令樹的節點、不經 `ai_decision`，也不能做任何事**。
   只有這一輪有指令工具時才附（只有 `skill_read` 或沒有工具的對話照舊）。**沒有放進 `tools.build()`**（規格寫 build）：
   build 的輸出是「指令節點 → 工具」，很多權限測試拿它比對群組集合；偽工具跟 `skill_read` 放在同一個地方比較一致。
2. AI 呼叫它＝這一輪結束：送「做不到：{reason}」（reason 壓成一行、遮掉已存的 secret（`mcp.redact`）與 token 樣式（`kit.mask_tokens`）、最多 200 字），
   記進對話記憶。同一則回覆裡排在它後面的呼叫不執行。頻道 AI 一樣（`RoomAgent.say` 再遮一次）。
3. 系統提示第 2 行改成「沒有呼叫工具就什麼都沒做，不要說已經做了。沒有適合的工具就呼叫 system__cannot_do 說明原因，不要假裝做了。」
   （有這個工具時；頻道版同樣意思）。這也是 ADR 0008 修正字句裡「做不到就直接說」的合法出口。
4. 評測：`REFUSE_MARKERS` 加「做不到」，用這個出口拒絕的回覆也算拒絕的標記（仍要有替代建議的標記才算 refuse 過）。

## 擋不住的

- 模型可以不用它、照樣用文字說做不到——那也沒關係（是誠實的）；它存在的目的只是讓「做不到」有一條比「假裝做了」更容易的路。
