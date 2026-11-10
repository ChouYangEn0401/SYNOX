---
name: notion-mcp
description: 使用者想在 Notion 找頁面、讀一頁、開新頁或改一頁時使用（遠端 MCP 範例）。
---

# 🗂 Notion（遠端 MCP）

## 什麼時候用
- 「在 Notion 找會議紀錄」→ `notionmcp__search`
- 「把那一頁讀給我聽」→ `notionmcp__fetch`
- 「開一頁新的」→ `notionmcp__create_pages`（會寫入）
- 「改那一頁」→ `notionmcp__update_page`（危險：每次都要使用者按核准）

## 注意
- 參數照工具清單給的欄位（第一次連上之後 SYNOX 才知道）。
- 還沒登入時請使用者私訊打 /notionmcp_login。
