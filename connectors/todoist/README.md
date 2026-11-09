# ✅ todoist（connector 設計稿，v0 還沒接）

**狀態**：只登記。`/todoist` 會回「還沒接上」。這個資料夾沒有任何連網程式。

## 打算怎麼接
- Todoist 官方遠端 MCP：`https://ai.todoist.net/mcp`。
- 認證：OAuth（`auth: "oauth"`）；替代做法是使用者自己到 Todoist 設定頁複製 API token 貼進精靈（較簡單、不用開埠）。
- token 存保管箱（`data/todoist.json.enc`）。

## 會變成哪些指令
| 指令 | 效果 |
|---|---|
| `/todoist` | 今天的待辦（READ） |
| `/todoist_add <內容> [due=明天]` | 加一個待辦（WRITE） |
| `/todoist_done <編號>` | 完成一個（WRITE） |
