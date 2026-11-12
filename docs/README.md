# SYNOX 文件索引

標示：**使用者**＝裝 SYNOX 來用的人（含架伺服器版的營運者）；**作者**＝寫工具（pack）接進 SYNOX 的人；**維護者**＝改 SYNOX 本身的人。

| 文件 | 給誰 | 一行說明 |
|---|---|---|
| [../README.md](../README.md) | 使用者 | 怎麼裝、每天怎麼用、個人版與伺服器版的差別、常見問題 |
| [security.md](security.md) | 使用者、作者 | 資料存在哪、誰看得到、裝別人的 pack 時的五關、信任層級、沙盒、沒有做的保護 |
| [discord.md](discord.md) | 使用者 | Discord 通道的現況與設定（含多個 bot） |
| [handoff/](handoff/README.md) | 使用者 | 到另一台電腦用真的帳號測 connector 與 Discord：教學、Discord 交接、煙霧測試 `scripts/smoke_real.py` |
| [tools.md](tools.md) | 作者 | **從這裡開始**：三條接入路怎麼選、權限欄位、secret、確認來回、測試、安全自檢表 |
| [sdk.md](sdk.md) | 作者 | Python 工具 SDK（`@tool`、`serve()`、`secret()`、`context()`、`synox-sdk` 指令） |
| [pack-format.md](pack-format.md) | 作者、維護者 | pack.json 每個欄位的完整規則、kind=cli／mcp／python 的細節、升級與環境建置 |
| [../packs/README.md](../packs/README.md) | 使用者 | SYNOX 出廠不帶工具：工具在 SYNOX 工具庫（SYNOX_Libs，另一個 repo），怎麼裝 |
| [../legacy/builtin-packs.md](../legacy/builtin-packs.md) | 使用者、維護者 | 下架的內建工具（記帳、隨手記、提醒）：為什麼、舊資料怎麼接回、怎麼救回 |
| [../examples/](../examples/) | 作者 | 可以照抄的範例：`hello`（SDK）、`any-language-cli`（不用 SDK）、`node-mcp-tool`（MCP stdio）、`mcp-remote-*`（遠端 MCP） |
| [AGENT.md](AGENT.md) | 維護者 | 程式地圖、不能破壞的規則（invariants）、已知限制 |
| [adr/](adr/) | 維護者 | 架構決定（一件一檔）：[0001](adr/0001-runtime-loop-heartbeat-mother-session.md) runtime loop、心跳、常駐助理、soul.md |
| [runtime-api.md](runtime-api.md) | 維護者（前端） | 主控面板用的 `/api/runtime/...` 合約（狀態、心跳設定、soul.md、任務日誌） |
| [../CHANGELOG.md](../CHANGELOG.md) | 維護者 | 每個版本改了什麼 |
| [ui/redesign-notes.md](ui/redesign-notes.md) | 維護者 | 網頁介面的設計 token、版面、參考對象；`ui/preview.html` 雙擊看假資料預覽（`scripts/make_ui_preview.py` 產生） |
| [debug-notes.md](debug-notes.md) | 維護者 | 安裝流程真機除錯：修好的（Fixed）與還開著、等擁有者決定的（Open） |
| [handoffs/](handoffs/) | 維護者 | 請**別的 repo**（金流簿、ISDTeleKitSDK…）做的事，一件一檔，由擁有者轉交（跟上面給使用者的 `handoff/` 不同） |
| [../QuestionToUser.md](../QuestionToUser.md) | 維護者 | 等擁有者拍板的事（每題有建議，不答就照建議） |
| [../LICENSING.md](../LICENSING.md) | 全部 | 授權：核心 AGPL-3.0-or-later，工具 SDK 與範例 Apache-2.0 |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | 維護者 | 怎麼貢獻、貢獻者同意書 |
