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
| [../examples/](../examples/) | 作者 | 可以照抄的範例：`hello`（SDK）、`any-language-cli`（不用 SDK）、`node-mcp-tool`（MCP stdio）、`mcp-remote-*`（遠端 MCP） |
| [AGENT.md](AGENT.md) | 維護者 | 程式地圖、不能破壞的規則（invariants）、已知限制 |
| [../CHANGELOG.md](../CHANGELOG.md) | 維護者 | 每個版本改了什麼 |
| [../LICENSING.md](../LICENSING.md) | 全部 | 授權：核心 AGPL-3.0-or-later，工具 SDK 與範例 Apache-2.0 |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | 維護者 | 怎麼貢獻、貢獻者同意書 |
| [from-clawbot/](from-clawbot/) | 維護者 | 從前身專案複製過來的設計參考資料（副本，不是 SYNOX 的正式文件） |
