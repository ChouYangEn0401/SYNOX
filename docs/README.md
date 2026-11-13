# SYNOX 文件索引

標示：**使用者**＝裝 SYNOX 來用的人（含架伺服器版的營運者）；**作者**＝寫工具（pack）接進 SYNOX 的人；**維護者**＝改 SYNOX 本身的人。

| 文件 | 給誰 | 一行說明 |
|---|---|---|
| [../README.md](../README.md) | 使用者 | 怎麼裝、每天怎麼用、個人版與伺服器版的差別、常見問題 |
| [landing/index.html](landing/index.html) | 使用者 | 介紹頁（雙擊就能看；線上版 <https://claude.ai/artifact/SNsSkbcVQm7BU22BBZN3gW#synox>）：標語與支援平台、能做什麼、網頁版畫面（可切換、可放大）、放心用、三步裝好、給開發者、alpha 現況。原稿是 `landing/page.html`，`scripts/make_landing.py` 組成 index.html |
| [tutorials/](tutorials/README.md) | 使用者 | 第一次裝、接 Telegram／Discord 的圖文教學；Discord 的名詞在 [discord-concepts.md](discord-concepts.md) |
| [install-packs.md](install-packs.md) | 使用者 | 怎麼裝一個 `.synoxpack`：點兩下、拖到 Install-Pack.bat、拖進網頁、`synox install`；圖示空白／點兩下沒反應怎麼辦 |
| [ecosystem.md](ecosystem.md) | 使用者、作者、維護者 | 工具生態：找、裝、更新、移除工具；做一個工具給人裝；之後的路（哪些是提案）；每次發版要更新哪些文件 |
| [versioning.md](versioning.md) | 使用者、作者、維護者 | 版本號怎麼看（正式版／beta／alpha）、我是不是最新版、**我要怎麼更新**（ZIP、git、安裝程式、工具、SDK）；維護者：升號規則、分支、tag、每版要有什麼、`scripts/release.py`；自己更新的設計在 [adr/0023](adr/0023-updates-and-hotfixes.md)（提案） |
| [security.md](security.md) | 使用者、作者 | 資料存在哪、誰看得到、裝別人的 pack 時的五關、信任層級、沙盒、沒有做的保護 |
| [discord.md](discord.md) | 使用者 | Discord 通道的現況與設定（含多個 bot） |
| [docker.md](docker.md) | 使用者、維護者 | 用 Docker 跑 SYNOX（compose、資料 volume、網頁只發佈到 127.0.0.1）與開發容器；已知限制、驗證清單、檢查表（**還沒實際建置過**） |
| [handoff/](handoff/README.md) | 使用者 | 到另一台電腦用真的帳號測 connector 與 Discord：教學、Discord 交接、煙霧測試 `scripts/smoke_real.py` |
| [tools.md](tools.md) | 作者 | **從這裡開始**：三條接入路怎麼選、權限欄位、secret、確認來回、測試、安全自檢表 |
| [sdk.md](sdk.md) | 作者 | Python 工具 SDK（`@tool`、`serve()`、`secret()`、`context()`、`synox-sdk` 指令） |
| [pack-format.md](pack-format.md) | 作者、維護者 | pack.json 每個欄位的完整規則、kind=cli／mcp／python 的細節、升級與環境建置 |
| [../packs/README.md](../packs/README.md) | 使用者 | SYNOX 出廠不帶工具：工具在 SYNOX 工具庫（SYNOX_Libs，另一個 repo），怎麼裝 |
| [../legacy/builtin-packs.md](../legacy/builtin-packs.md) | 使用者、維護者 | 下架的內建工具（記帳、隨手記、提醒）：為什麼、舊資料怎麼接回、怎麼救回 |
| [../legacy/connectors.md](../legacy/connectors.md) | 使用者、維護者 | 搬到工具庫的 4 個 connector（Notion、Todoist、Google 日曆、Apple 提醒事項）：為什麼、token／帳號怎麼接回、怎麼救回 |
| [../examples/](../examples/) | 作者 | 可以照抄的範例：`hello`（SDK）、`any-language-cli`（不用 SDK）、`node-mcp-tool`（MCP stdio）、`mcp-remote-*`（遠端 MCP） |
| [AGENT.md](AGENT.md) | 維護者 | 程式地圖、不能破壞的規則（invariants）、已知限制 |
| [adr/](adr/) | 維護者 | 架構決定（一件一檔）：[0001](adr/0001-runtime-loop-heartbeat-mother-session.md) runtime loop、心跳、常駐助理、soul.md；[0002](adr/0002-soul-md-in-chat-assistant-prompt.md) soul.md 放進對話助理的系統提示（Q7）；[0005](adr/0005-soul-ledger-memory-provenance-review.md) soul 帳本（助理筆記的來歷、有疑慮先問、取代不刪除、整理與遺忘）；[0004](adr/0004-activator-event-driven-rules.md) 連動：任務做完馬上觸發下一件、防無限連動；[0006](adr/0006-keep-awake-screen-may-sleep.md) 保持清醒（含現代待命附記）；[0007](adr/0007-local-llm-platform.md) 本地模型是內建能力（context 建議、無進展逾時） |
| [keep-awake-troubleshooting.md](keep-awake-troubleshooting.md) | 使用者 | 保持清醒開著、Google Drive 還是斷線：現代待命機型的排查步驟（只看、不改設定） |
| [presentation.md](presentation.md) | 維護者 | 呈現層（預設關）：AI 回覆的 Markdown → Telegram HTML／Discord／網頁區塊、各通道的降級規則、黃金檔案怎麼重產 |
| [runtime-api.md](runtime-api.md) | 維護者（前端） | 主控面板用的 `/api/runtime/...` 合約（狀態、心跳設定、soul.md、任務日誌、連動規則） |
| [../CHANGELOG.md](../CHANGELOG.md) | 維護者 | 每個版本改了什麼 |
| [ui/redesign-notes.md](ui/redesign-notes.md) | 維護者 | 網頁介面的設計 token、版面、參考對象；`ui/preview.html` 雙擊看假資料預覽（`scripts/make_ui_preview.py` 產生） |
| [debug-notes.md](debug-notes.md) | 維護者 | 安裝流程真機除錯：修好的（Fixed）與還開著、等擁有者決定的（Open） |
| [claude-code-cli.md](claude-code-cli.md) | 維護者 | 預設 AI 來源要的是 `claude` 命令列版：怎麼找、為什麼 Claude Desktop／VS Code 擴充功能不算、設定頁的安裝指令 |
| [handoffs/](handoffs/) | 維護者 | 請**別的 repo**（金流簿、ISDTeleKitSDK…）做的事，一件一檔，由擁有者轉交（跟上面給使用者的 `handoff/` 不同） |
| [../QuestionToUser.md](../QuestionToUser.md) | 維護者 | 等擁有者拍板的事（每題有建議，不答就照建議） |
| [../LICENSING.md](../LICENSING.md) | 全部 | 授權：核心 AGPL-3.0-or-later，工具 SDK 與範例 Apache-2.0 |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | 維護者 | 怎麼貢獻、貢獻者同意書 |

## 待做（擁有者說 MVP 完成之後才做）

- **agent 讀取 context 的說明**（2026-11-12，擁有者決定 Q7 時提的）：核心的幾個 agent（對話助理、常駐助理、頻道 AI）各自讀哪些 context
  （系統提示、soul.md、對話記憶、工具結果、心跳快照）、怎麼區隔資料與指令，做成**簡單的 HTML artifact、存一份本地 HTML**，給之後的工程人員追蹤。
  現在的依據：[adr/0001](adr/0001-runtime-loop-heartbeat-mother-session.md) §4、[adr/0002](adr/0002-soul-md-in-chat-assistant-prompt.md)。
