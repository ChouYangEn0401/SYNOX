# docs/artifacts：claude.ai Artifact 的本機副本

這個資料夾放 SYNOX 相關的 claude.ai Artifact（調查、計畫、交接、測試板…）的本機 HTML 副本。Artifact 服務哪天打不開，內容還在 repo 裡。

## 規則

- **每一份關於 SYNOX 的 Artifact 都要有一份本機副本。** 檔名是 `<最後更新日期>-<英文短名>.html`；教學頁的正本在 `docs/tutorials/<名字>/index.html`。
- **每一頁最底下有一行小字**：線上版網址、本機路徑、頁面版本 `<span data-stamp>…</span>`。頁面版本＝把 `data-stamp` 裡的字清空後整頁的 sha256 前 10 碼＋日期，線上版和本機版這一行一樣＝同一份。
- 清單在 `registry-archive.json`：每一頁的標題、線上網址、本機路徑、有沒有重新發佈（`republished`）、Artifact 版本（`artifact_version`）。
- 有些頁面不重新發佈（例如用 Artifact 資料庫存資料的「部署測試板」，重新發佈可能動到線上的資料或行為）；那一頁的小字會寫「線上版未重新發佈：本機版是 <版本> 的副本」，`republished` 是 `false`。本機副本只有頁面，看不到資料庫裡的資料。
- 本機副本不放私人路徑、金鑰、token；原文裡的 `C:\Users\<名字>` 已換成 `%USERPROFILE%`。

## 怎麼更新

1. 改本機檔（本機檔是唯一的正本，不要直接在線上改）。
2. 重算頁面版本：`python scripts/page_stamp.py docs/artifacts/<檔名>.html`
3. 用 Artifact 工具發佈到**同一個網址**（`url` ＋ `file_path`，不要開新的 Artifact）。
4. 版本有變就更新 `registry-archive.json` 的 `artifact_version`。

服務會在發佈時自動包一層外框、在有 Mermaid 圖的頁面自動加上繪圖程式；那些不寫進本機檔。
