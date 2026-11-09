# ⏰ remind（提醒）

這個資料夾只放說明與 SKILL.md；程式在 `src/synox/schedule/`（同一個排程器也替 `/schedule_*` 跑指令）。

| 指令 | 做什麼 |
|---|---|
| `/remind_add <HH:MM> <內容>` | 每天這個時間提醒 |
| `/remind_add <HH:MM> <內容> date=2026-11-20` | 那一天提醒一次 |
| `/remind_list` | 列出提醒 |
| `/remind_rm <編號>` | 刪掉一個 |

資料：`data/schedule.json.enc`（保管箱加密）。只有 bot 開著（Start.bat）時才會送出；
終端機模式（Console.bat）不跑排程。
