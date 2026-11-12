# connectors/：已經搬走了（2026-11-12）

這裡以前放 SYNOX 出廠就帶的 4 個「接外面服務」的工具：🗂 Notion、✅ Todoist、📅 Google 日曆、🍎 Apple 提醒事項（CalDAV）。
2026-11-12 起它們跟其他工具一樣放在 **SYNOX 工具庫（SYNOX_Libs）**，SYNOX 主程式出廠不帶任何工具。
原本做什麼、為什麼搬、怎麼救回：[../legacy/connectors.md](../legacy/connectors.md)。

- 要用：從工具庫裝 `notion`、`todoist`、`google-calendar`、`apple-reminders` 的 `.synoxpack`（裝法見 [../packs/README.md](../packs/README.md)）。
  pack 名字沒變，**以前存的 token／帳號（保管箱）照用**，裝回去就接著用。
- SYNOX 不再掃這個資料夾（`src/synox/packs/loader.py` 的 `PACK_DIRS` 只剩 `packs/`）：從舊版解壓縮蓋過來、留在這裡的舊檔不會被載入，可以自己刪掉。
- 這份說明以外不要再放東西進來；新工具一律放工具庫、走安裝流程。
