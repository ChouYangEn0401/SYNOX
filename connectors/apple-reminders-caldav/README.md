# 🍎 apple-reminders-caldav（connector 設計稿，v0 還沒接）

**狀態**：只登記。`/applerem` 會回「還沒接上」。這個資料夾沒有任何連網程式。

## 打算怎麼接
- iCloud 的提醒事項走 CalDAV：`https://caldav.icloud.com`（`auth: "caldav"`）。
- 認證：Apple ID ＋ **App 專用密碼**（appleid.apple.com → 登入與安全性 → App 專用密碼）；不要用 Apple ID 本身的密碼。
  精靈多一頁讓使用者貼上，存進保管箱（`data/apple-reminders.json.enc`）。
- CalDAV 是 WebDAV＋iCalendar（VTODO）；只用 `requests` 就能做（PROPFIND 找清單、REPORT 讀、PUT 加），不需要第三方套件。
- 注意：Apple 新版「提醒事項」的部分功能（子任務、標籤）CalDAV 看不到。

## 會變成哪些指令
| 指令 | 效果 |
|---|---|
| `/applerem` | 列出未完成的提醒事項（READ） |
| `/applerem_add <內容> [due=…]` | 加一個（WRITE） |
