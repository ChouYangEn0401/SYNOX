---
name: todoist-mcp
description: 使用者想看、加、完成或刪掉 Todoist 待辦時使用（遠端 MCP 範例）。
---

# ✅ Todoist（遠端 MCP）

## 什麼時候用
- 「今天有什麼待辦」→ `todoistmcp__find_tasks`
- 「加一個待辦：明天繳電費」→ `todoistmcp__add_tasks`（會寫入）
- 「把繳電費打勾」→ `todoistmcp__complete_tasks`（會寫入）
- 「刪掉那個專案」→ `todoistmcp__delete_object`（危險：每次都要使用者按核准）

## 注意
- 參數照工具清單給的欄位（第一次連上之後 SYNOX 才知道）。
- 還沒連接時請使用者到網頁介面的工具頁按「連接」填 API token（不要在聊天裡收）。
