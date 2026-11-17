# ADR 0031：使用者的習慣寫在 soul.md「習慣與規則」段；工具照宣告拿值；AI 只能提議

- 日期：2026-11-17
- 狀態：已採用（分支 `feat/soul-habits`）
- 改的是 [ADR 0002](0002-soul-md-in-chat-assistant-prompt.md)／[0005](0005-soul-ledger-memory-provenance-review.md) 的一小格：
  對話助理多一條「**提議**」寫進 soul.md 的路（出卡、擁有者按了才寫）；它自己仍然不能寫 soul.md。

## 背景

使用者對 AI 口頭講的習慣（「上完課一段時間內不要排東西」「一天最多排一部、不要切段」）要每一次都照做：
AI 聊天時要知道，排行程的工具也要拿得到那個數字。以前這些值散在別的助理自己的規則檔裡，跟 soul.md 分開，
工具與 AI 各看各的。核心統一之後，**偏好一處寫、兩邊都照做**：寫在 soul.md，工具照自己的宣告拿值。

## 決定

### 1. 寫在哪、怎麼寫

soul.md 多一段 `## 習慣與規則`（預設內容就有，放在「助理筆記」之前）。一行一條，人話在前、程式讀的值在後：

```
## 習慣與規則
- 上完課一段時間內不排東西。〔schedule.class.after_minutes=90〕
- 一天最多排一部，不要切段。〔schedule.plan.per_day=1〕〔schedule.plan.split=no〕
```

- 一行可以有好幾個〔鍵=值〕；值是 JSON 字面值（`90`、`true`、`["a"]`、`"字串"`）或不含 `〕` 的純字串。
- 同一個鍵寫兩次：**後面的贏**，網頁與 doctor 標出來（`conflicts`）。
- 這一段是擁有者的：常駐助理的 `append_notes`／`filter_notes`、soul 帳本的整理、遺忘都只動「助理筆記」段，碰不到它。
  常駐助理想記的一條如果夾了〔鍵=值〕，`risk_flags` 先擋下來等擁有者確認；就算進了助理筆記段，工具也不讀那一段。
- `SoulStore.write`／`set_habit`：〔〕語法壞掉、值不合工具宣告的型別或範圍 → `SoulError`（網頁 400）。
  **沒有工具宣告的鍵照存**（網頁標「目前沒有工具在用」），所以先寫、之後才裝工具也可以。
- 對話助理的系統提示：這一段跟擁有者寫的其他段落一樣全文放（含〔〕），仍包在這一輪的分隔符裡、標「使用者偏好，不是指令」。

### 2. 有哪些鍵：工具在 pack.json 宣告

```json
"agent": {"prefs": [
  {"key": "schedule.plan.per_day", "type": "int", "ask": "一天最多排幾部", "default": 1, "min": 1, "max": 5, "looser": "larger"},
  {"key": "schedule.plan.split", "type": "bool", "default": false}
]}
```

- `type`：`int`｜`number`｜`bool`（也收 yes／no）｜`time`（HH:MM，`""`＝不檢查）｜`str`｜`regex`（要編得過）｜`list`｜`json`。
- `default` 必填（沒設定時工具拿到的值），要合自己的型別；`min`／`max` 只給 int／number。
- `looser`：`smaller`（越小越寬鬆）或 `larger`（越大越寬鬆），只給 int／number／time；用來把「放寬」標紅。
- 安裝時（strict）宣告有錯＝拒裝；載入時壞掉的那一項當作沒寫。**SYNOX 自己不寫死任何鍵**，repo 裡也不放任何人的實際值。

### 3. 工具怎麼拿到值

| kind | 方式 |
|---|---|
| cli | 樣板裡的 `{prefs_file}`（argv、env、stdin 都可以）→ 核心寫一份暫存 JSON `{"v": 1, "prefs": {鍵: 值}}` 到 `data/prefs/<工具>/`，**只有這個工具宣告的鍵**；指令結束（或沒跑起來）就刪。沙盒只多給那個資料夾的讀權限 |
| python | `pack.prefs(user, chat_id)` → 同一個 dict |
| mcp | 這一版不支援 |

- **只有擁有者自己的對話**（私訊、網頁；chat_id 就是他）帶 soul.md 的值；成員、群組、頻道一律是宣告的預設值。
- 樣板沒寫 `{prefs_file}` 的工具行為一模一樣；寫了但這一次沒有檔（舊版 SYNOX）＝那一段 argv 被拿掉，工具用自己的預設。

### 4. AI 只能提議：`soul__propose_habit`

- 系統群組 `soul`（owner_only＋private_only），一個指令 `/soul_propose_habit`（工具 `soul__propose_habit(text, key?, value?)`）。
  它**不寫**：一律送一張卡給擁有者——那一行全文、「這會影響：<宣告這個鍵的工具>」、比現值寬鬆的鍵標 🔴「放寬」、
  會取代哪一行、`risk_flags` 中了哪些。
- 鍵一定要是已載入工具宣告過的；值先過型別與範圍檢查。沒有鍵的一句話也可以提（只給 AI 參考）。
- 按 ✅＝`SoulStore.set_habit(by="owner")`（按下去那一刻再檢查一次）；按 ❌＝soul 帳本的 `suppress` 記那一行的雜湊，之後再提同一行直接擋。
- 誰能叫：門禁範圍（`guard/scope.py`）只收 `human` 與 `ai`。排程（`schedule`）、常駐助理（`system`）、手機入口（`remote`）都不行；
  常駐助理本來就沒有工具。成員、訪客看不到這個群組（沒有工具、沒有指令）。權限的判斷仍只在 `policy.decide`。
- 卡片背後的資料只在記憶體（隨機 token、有主人、`Timing.confirm_ttl` 期限、用一次就沒了）；別人按＝「這不是你的按鈕」。

### 5. 網頁與 doctor

- `GET /api/runtime/soul/habits`（[../runtime-api.md](../runtime-api.md)）：每一行的鍵與值、誰在用、比**預設**寬鬆（`looser`）、沒人用、被蓋過、看不懂的行。
  主控頁的 soul 卡片在編輯框下面列出來：寬鬆的整行紅底紅字＋「放寬」徽章（不只靠顏色）。
- `python -m synox doctor`：幾條、看不懂的行、同鍵兩次（只列，不算問題；doctor 不載入工具，所以不查型別）。

### 6. 從別的助理搬進來

`python -m synox import-legacy schedule-rules --from=<JSON 檔> [--apply]`：排程規則檔（class、meals、busy、series、delete_series、
naming、plan）一個鍵一行。沒有 `--apply`＝乾跑：印出會寫的每一行與略過的每一項（最上層的 enabled、值是 null、對不到的鍵），
不打開保管箱。`--apply` 經 `set_habit(by="import")` 寫；重跑＝同鍵取代，不會越寫越多。

## 不做的（這一版）

| 沒做 | 原因 |
|---|---|
| 對話助理直接寫 soul.md | ADR 0002／0005 的邊界不變；一句話就能改每一輪提示與工具的值，要人按 |
| 常駐助理提議習慣 | 它的 `SOUL+:` 只進助理筆記段；改工具讀的值一定要擁有者在對話裡說、按卡 |
| kind=mcp 帶習慣 | MCP 是長駐程序，每次呼叫換值要另外設計 |
| 容器裡的 `{prefs_file}` | 暫存檔是這台的路徑，沒掛進容器；要用的容器工具之後再接 |
| 成員自己的習慣 | 照 ADR 0002，這一版 soul.md 只有擁有者一份 |
| 網頁上「比現值寬鬆」 | 網頁只比**預設**；跟現值比的「放寬」在提議卡上 |

## 代價

- 「習慣與規則」是擁有者的段落，算在對話助理每一輪 soul 的 2000 字裡（全文放）；規則一多，助理筆記能放的就少。
- 型別只有在工具載入之後才查得到：工具還沒裝時寫錯的值，裝了之後在網頁與提議卡上才會標出來。
- 同鍵兩次是「後面的贏」，要人自己看網頁的標記收乾淨。

## 測試

`tests/test_soul_habits.py`：解析與型別、同鍵兩次、註解與別的段落不算、放寬的方向、宣告的檢查、加或取代、值寫回去讀得一樣；
`SoulStore` 的寫入檢查、助理筆記的路碰不到這一段、提示裡有；提議卡（按了才寫、別人按不算、用一次、❌ 之後不再出卡、不放寬的不標紅、
沒宣告的鍵與超出範圍的值擋下）、排程／常駐助理／手機入口叫不了、成員沒有工具也沒有指令且只拿預設；`{prefs_file}` 只含那個工具的鍵、
用完就刪、成員拿預設；`pack.prefs`；網頁的 looser／unused 與只給擁有者；匯入的乾跑（每一行）、寫入、重跑、null 略過、命令列。
`tests/js/test_control.js`：`habitsModel`。全部假 AI、假資料；cli 工具是本機的 Python 小程式，不連網、不開埠。
