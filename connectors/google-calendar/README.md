# 📅 google-calendar（connector 設計稿，v0 還沒接）

**狀態**：只登記。`/gcal` 會回「還沒接上」。這個資料夾沒有任何連網程式。

## 打算怎麼接
- 走 Google 官方的遠端 MCP 伺服器：`https://calendarmcp.googleapis.com`（Google Calendar MCP）。
- 認證：OAuth 2.0（`auth: "oauth"`）。精靈多一頁「連 Google 日曆」：開瀏覽器到 Google 同意畫面 →
  本機 loopback 收 code（**注意：這會開一個本機埠，跟「不開埠」的原則衝突，要另外決定**；替代做法是 device code flow）。
- refresh token 存保管箱（`data/google-calendar.json.enc`），不放 config.json。
- 範圍（scope）只要 `calendar.events`；唯讀模式只要 `calendar.readonly`。

## 會變成哪些指令
| 指令 | 效果 |
|---|---|
| `/gcal` | 今天、明天的行程（READ） |
| `/gcal_add <時間> <標題>` | 加一個行程（WRITE） |
| `/gcal_rm` | 刪行程（DANGER，AI 要做會先送確認卡） |
