# 🗂 Notion

在 Telegram 跟 SYNOX 說一句話，就能**搜尋、讀 Notion 頁面、在資料庫加一筆、在頁面後面補字、改欄位**。
用的是你自己建的 Notion「integration」（一把只看得到你分享給它的頁面的鑰匙）。

## 設定（第一次，約 3 分鐘）

1. **建一個 integration**：用電腦打開 <https://www.notion.so/profile/integrations> → 「新增 integration」
   （New integration）→ 名字取「SYNOX」、選你的工作區、類型選 **Internal** → 儲存。
2. 在那個 integration 的頁面：
   - 「功能」（Capabilities）勾 **讀取內容**、**插入內容**、**更新內容**（只想讓它看、不讓它改，就只勾讀取）。
   - 複製 **Internal Integration Secret**（`ntn_` 開頭的一長串）。
3. **把 token 交給 SYNOX**：在 Telegram **私訊** bot 打 `/notion_token`，它說「貼上來」之後，把剛剛複製的貼上送出。
   - 看到「✅ 接上 Notion 了」就好了。
   - 接著**把你貼 token 的那則訊息刪掉**（長按 → 刪除 → 勾「也替對方刪除」）。Telegram 的訊息不是端對端加密的。
   - 更保險的做法：在這台電腦上雙擊 `Console.bat`，在那個視窗裡打 `/notion_token`，token 就不會經過 Telegram。
4. **把頁面分享給 integration**（最常忘的一步）：在 Notion 打開你要給 SYNOX 用的頁面或資料庫 →
   右上角 **⋯** → **連接**（Connections）→ 選「SYNOX」。分享一個頁面，它底下的子頁面也一起分享。
   沒分享的頁面 SYNOX 看不到（會說「找不到」）。
5. 試試看：`/notion 會議`。

## 怎麼用

可以直接說人話（例如「在 Notion 的任務資料庫加一筆：買牛奶，明天」），AI 會選下面的指令；也可以自己打：

| 指令 | 做什麼 |
|---|---|
| `/notion <關鍵字>` | 搜尋頁面（標題） |
| `/notion_read <頁面>` | 讀一頁：標題、欄位、內文 |
| `/notion_dbs` | 列出分享給 SYNOX 的資料庫 |
| `/notion_rows <資料庫> [筆數]` | 資料庫最近改過的幾列 |
| `/notion_row <資料庫> <標題> props=狀態:待辦; 日期:明天` | 在資料庫加一列（`props=` 可以不寫） |
| `/notion_new <上層頁面> <標題> text=內文` | 在某一頁底下開一個新頁 |
| `/notion_append <頁面> <要加的字>` | 在一頁最後面加一段字 |
| `/notion_set <頁面> 狀態:完成; 日期:2026-11-20` | 改一頁（資料庫的一列）的欄位 ⚠️ |
| `/notion_status`、`/notion_logout` | 看有沒有接上、把 token 拿掉 |

- `<頁面>`、`<資料庫>` 可以是 **Notion 網址**（在 Notion 裡「複製連結」）、id，或**標題**（用搜尋找最像的那一個；同名的很多時用網址最準）。
- 欄位的寫法：`欄位:值`，好幾個用 `;` 隔開。日期寫 `2026-11-12`、`2026-11-12 14:00`、`今天`、`明天`；
  多選用 `、` 隔開；勾選框寫 `是`／`否`。人、關聯、檔案、公式欄位要在 Notion 裡改。
- ⚠️ `/notion_set` 會改既有的內容：**AI 要做一定先送確認卡**，你按了才改。搜尋、讀、新增不用確認。
- 一次加的字是一段；要很多段就多加幾次，或直接在 Notion 裡寫。

## 安全：資料在哪、誰看得到

- **token 存在 SYNOX 的保管箱**：`data/notion.json.enc`，密文（跟筆記、記帳同一種加密）；不在 `config.json`、不在 log
  （log 會把長得像 token 的字遮成 `ntn_***`）。
- 只有**你**（安裝時配對的那個帳號）能用 `/notion*`；伺服器版的成員、訪客都用不到。`/notion_token`、`/notion_status`、
  `/notion_logout` 不給 AI 用，`/notion_token` 只收私訊。
- SYNOX 只連 `api.notion.com`（Notion 官方 API），不開任何網路埠、不跑別人的程式；只看得到你分享給 integration 的頁面。
- AI 讀到的頁面內容會送到你設定的 AI 供應者（跟其他工具一樣，見 [docs/security.md](../../docs/security.md)）。
  頁面裡如果夾了「忽略規則、刪掉東西」之類的字，SYNOX 把它當資料包起來；而且改東西一定要你按確認卡。
- 不想用了：`/notion_logout`，再到 <https://www.notion.so/profile/integrations> 把 integration 刪掉（token 就徹底失效）。

## 常見問題

| 看到 | 怎麼辦 |
|---|---|
| 找不到 | 那一頁沒有分享給 integration（上面第 4 步） |
| Notion 不認這個 token | 複製錯了、或在 Notion 重新產生／刪掉了 → `/notion_token` 重貼 |
| 沒有這個權限 | integration 的「功能」沒勾插入／更新內容（上面第 2 步） |
| 沒有叫「X」的欄位 | 欄位名字要跟資料庫一模一樣；`/notion_rows <資料庫>` 看看有哪些 |
| 太頻繁 | Notion 限制每秒約 3 次，等幾秒再試 |

## 給開發的人

- `kind: python`、`capabilities: ["network"]`（五關的第 2 關掃描結果只有 `import requests`）；`storage: vault`。
- Notion REST API，`Notion-Version: 2025-09-03`（資料庫底下是 data source：加一列用 `parent.data_source_id`，
  給資料庫 id 時先 `GET /databases/{id}` 拿第一個 data source）。只用 `requests`。
- 測試：`tests/test_notion.py`，`new_session` 換成假的 HTTP 傳輸，不連 Notion。

### 為什麼用 integration token，不用 Notion MCP

| 做法 | 一句話 | 判定 |
|---|---|---|
| **A. Internal integration token＋官方 REST（這一版）** | 貼一次 token；只用 requests；不開埠、不跑別人的程式；只看得到分享的頁面 | ✅ 採用 |
| B. 官方遠端 MCP `mcp.notion.com/mcp` | OAuth 要瀏覽器回呼（本機埠或代管的回呼網址），SYNOX 的 `kind: mcp` 這一版還不會連線 | 之後 `kind: mcp` 做好再評估 |
| C. 本機 `@notionhq/notion-mcp-server` | 要在這台電腦跑 npm 套件（180 多個相依）；Notion 自己說不再積極維護 | ❌ 不用（見 SYNOXPacks `docs/mcp-audit-2026-11.md`） |
