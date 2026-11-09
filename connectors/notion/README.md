# 🗂 notion（connector 設計稿，v0 還沒接）

**狀態**：只登記。`/notion` 會回「還沒接上」。這個資料夾沒有任何連網程式。

## 打算怎麼接
- Notion 官方遠端 MCP：`https://mcp.notion.com/mcp`（Streamable HTTP）。
- 認證：OAuth（`auth: "oauth"`），使用者在 Notion 的同意畫面選要分享給 SYNOX 的頁面。
  OAuth 回呼一樣有「本機埠」的問題，見 google-calendar 的說明。
- token 存保管箱（`data/notion.json.enc`）。

## 會變成哪些指令
| 指令 | 效果 |
|---|---|
| `/notion <關鍵字>` | 搜尋頁面（READ） |
| `/notion_add <資料庫> <內容>` | 在指定資料庫加一筆（WRITE） |
