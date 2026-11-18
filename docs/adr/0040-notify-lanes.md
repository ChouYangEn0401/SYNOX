# ADR 0040：通知分流——每個入口兩條線（主線、安靜線）、響不響、太久沒處理才升級

- 日期：2026-11-17
- 狀態：**提案（契約定稿，還沒有程式）**。實作分支 `feat/notify-lanes`。
- 基準：分支 `dev`，commit `86a930d`。
- 來源：合一規劃（維護者的私有文件庫，2026-11-17）第 4.4 節、第 13 節。
- 相關：[notifications.md](../notifications.md)（通知中心的現況）、[0029](0029-reminder-delivery-on-notify-hub.md)（送達確認、重試——不變）、
  [0037](0037-approval-cards-upgrade.md)（核准卡）、[0025](0025-guard-core-and-stepup.md)（驗證碼的提示）。
- 程式：`src/synox/notify/hub.py`（查表、分線）、`notify/lanes.py`（新：表與查法，純函式）、`notify/kinds.json`（新：repo 的預設表）、
  `notify/channels.py`（每個入口怎麼送兩條線）、`notify/store.py`（偏好多兩欄、升級的時間）、`notify/web_api.py`、`packs/manifest.py`（`notify.kinds`）、
  `packs/loader.py`（工具發通知的入口）、`sdk/`、`doctor.py`。
- 測試：`tests/test_notify_lanes.py`、`tests/test_notify_tools.py`；既有的 `tests/test_notify*.py` 不可以壞。

## 背景

通知中心現在（**已查證** `src/synox/notify/hub.py`）：一則通知同時送到網頁、Telegram、Discord；每一類可以一格一格關；有去重、送達確認、重試。
它沒有的：

| 沒有的 | 結果 |
|---|---|
| 「要你決定的」與「看了就好的」分開 | 背景工作的進度跟核准卡擠在同一個聊天裡，重要的被洗掉 |
| 響不響 | 每一則都響 |
| 先安靜、太久沒處理才吵 | 只能選一直吵或一直不吵 |
| 工具自己說「這一則是哪一類」 | 只有 SYNOX 自己發的有分類；而且**工具根本沒有發通知的介面**（**已查證**：SDK 與 `pack-format.md` 都沒有） |

先前的聊天機器人用「三支 bot＋一張分流表」解決前面三樣。SYNOX 有三種入口（網頁、Telegram、Discord），不能照抄「幾支 bot」；
要的是那張表的想法：**哪一類走哪一條線是資料，不是程式**。

## 決定

| # | 題目 | 決定 |
|---|---|---|
| 1 | 兩條線 | 每一類通知有 `lane`：`main`（主線：要你按、要你回的）｜`quiet`（安靜線：看了就好）。**每個入口**各自決定兩條線長什麼樣 |
| 2 | 響不響 | 每一類有 `sound`（布林）。跟線是兩回事：安靜線也可以響（例如每天的簡報） |
| 3 | 升級 | 每一類可以有 `escalate`：過了幾分鐘還沒被處理，照另一組設定**再送一次**，之後不再重複 |
| 4 | 表在哪 | repo 的預設表（資料檔）→ 這台電腦的覆寫（`data/`）→ 每個人在設定頁選的。類別名有階層（`task.done` 找不到就找 `task`） |
| 5 | 鎖住的 | 核准卡、AI 的問題、驗證與解鎖、安全警告：**永遠主線、會響、關不掉** |
| 6 | 工具 | pack.json 宣告自己會發哪幾類（`notify.kinds`）；這份順便定工具發通知的介面 |
| 7 | 給別人用的那支 bot | 不放進個人的 SYNOX（它的做法是另一個伺服器版的實例） |
| 8 | 既有行為 | 沒設定任何東西的人，升級之後只有兩類變安靜（「有新版」「SYNOX 開起來了」）；其他照舊 |

## 1. 表

### 1.1 一列長什麼樣

```json
{"version": 1,
 "default": {"lane": "main", "sound": true},
 "kinds": {
   "approval":     {"label": "🔒 要你確認的卡", "lane": "main", "sound": true, "locked": true},
   "question":     {"label": "❓ AI 在問你", "lane": "main", "sound": true, "locked": true},
   "stepup":       {"label": "🔐 驗證與解鎖", "lane": "main", "sound": true, "locked": true},
   "safety":       {"label": "⚠️ 安全警告", "lane": "main", "sound": true, "locked": true, "locked_channels": ["web"]},
   "alarm":        {"label": "⏰ 鬧鐘與提醒", "lane": "main", "sound": true},
   "followup":     {"label": "💬 做完之後順手問的", "lane": "main", "sound": false},
   "task":         {"label": "🧩 背景工作的進度", "lane": "quiet", "sound": false},
   "task.done":    {"label": "✅ 交代的事做完了", "lane": "main", "sound": false},
   "task.problem": {"label": "❗ 背景工作出問題", "lane": "main", "sound": true},
   "brief":        {"label": "📰 簡報與摘要", "lane": "quiet", "sound": true},
   "assistant":    {"label": "🫀 常駐助理的消息", "lane": "main", "sound": true},
   "tools":        {"label": "🧩 工具裝好了／出問題", "lane": "main", "sound": true},
   "tool_idle":    {"label": "🧩 工具畫面太久沒人用", "lane": "main", "sound": true},
   "update":       {"label": "🆕 SYNOX 有新版", "lane": "quiet", "sound": false},
   "greeting":     {"label": "👋 SYNOX 開起來了", "lane": "quiet", "sound": false, "off": ["web"]},
   "general":      {"label": "📣 其他", "lane": "main", "sound": true}
 }}
```

| 欄位 | 規則 |
|---|---|
| 類別名 | 每一段 `[a-z][a-z0-9_]{0,23}`，用 `.` 接，最多 3 段、總長 64 |
| `label` | 設定頁顯示的名字（一行、24 字內）。子類沒寫＝不單獨列在設定頁（跟著上一層） |
| `lane` | `main`｜`quiet` |
| `sound` | 布林 |
| `off` | 預設不送的入口（現有的欄位，照舊） |
| `locked` | `true`＝`lane`、`sound` 不能被覆寫或被使用者改；而且至少一個聊天入口關不掉（見 1.4） |
| `locked_channels` | 這幾個入口一定送（現有 `safety` 的 `locked: ["web"]` 改名搬過來） |
| `escalate` | `{"after_min": 1–1440, "to": {"lane": "main", "sound": true}}`；`to` 的兩個欄位都要寫 |

數值都是**提案值**。

### 1.2 怎麼查（`notify/lanes.py`，純函式）

```python
@dataclass(frozen=True)
class Route:
    kind: str                 # 實際用到的那一列的名字
    lane: str; sound: bool
    escalate: Optional[dict]
    locked: bool
    off: frozenset[str]       # 不送的入口

def load(repo_file, data_file, tool_kinds) -> Table        # 合併三個來源；格式錯的那一列丟掉並記 log
def lookup(table, kind) -> dict                            # 階層：a.b.c → a.b → a → default
def route(table, kind, prefs) -> Route                     # 再套上這個人的偏好
```

一則通知的 `kind` 怎麼變成 `Route`（**由上到下，先找到的贏**；`locked` 的那幾類跳過 2、3）：

1. 鎖住的類：表上寫什麼就是什麼。
2. 這個人在設定頁選的（`prefs.lane[kind]`、`prefs.sound[kind]`、`prefs.off[kind]`）。
3. 這台電腦的覆寫：`data/notify_kinds.json`（跟 repo 的檔同一個格式；同名的列**逐欄**蓋過）。
4. 工具宣告的（第 3 節）；repo 的預設表。
5. 階層往上找：`task.card.info` → `task.card` → `task`。
6. `default`。

- `data/notify_kinds.json` 是一般的設定檔（不進保管箱；裡面只有類別名與線，沒有私人內容）。改了下一則就生效，不用重開。要在 `.gitignore`。
- 覆寫檔與使用者的偏好**不能**新增 `locked`、不能動鎖住的類；寫了＝那一欄忽略、doctor 列出來。
- 不認得的 `kind`（沒有任何一層有）＝`general`。

### 1.3 每個入口的兩條線

| 入口 | 主線 | 安靜線 |
|---|---|---|
| Telegram | 主 bot | `notify.lanes.telegram.quiet_token` 有設＝**第二支 bot**（只送、不收）；沒設＝同一支 bot |
| Discord | 私訊 | `notify.lanes.discord.quiet_channel_id` 有設＝那個頻道；沒設＝私訊 |
| 網頁 | 跳出小卡＋🔔 的數字 | 只進清單（不跳、不加數字；清單裡標「安靜」） |
| 電腦提醒視窗 | 會跳 | 不跳（那個入口記成 `skipped`） |

`sound` 管的是聊天入口響不響，跟走哪條線無關：

| 入口 | `sound: false` 怎麼送 |
|---|---|
| Telegram | `disable_notification`。vendor 的 `send_message` 沒有這個參數（**已查證**），所以在 `notify/channels.py` 用 `BotAPI.post("sendMessage", …)` 自己帶；`reply_markup`、HTML 的處理要跟 `send_message` 一樣 |
| Discord | 訊息旗標 `SUPPRESS_NOTIFICATIONS`（`discord/rest.py` 已經有這個旗標的用法） |
| 網頁 | 小卡照跳（主線），但不播聲音 |
| 電腦提醒視窗 | 照跳，不播聲音 |

第二支 Telegram bot 的規則：

- **只送不收**：SYNOX 不對它開收訊（不 `getUpdates`、不設 webhook）。所以它送出去的訊息**不能有按鈕**——按了沒有人接。
  有按鈕（`actions`）的通知走安靜線時，一律改由主 bot 送、照 `sound` 決定響不響。
- token 放保管箱（`vault:telegram_quiet_token`），永遠不進 log。
- Telegram 的 bot 不能主動私訊沒跟它講過話的人：設定頁有「試送一則」。送不到（對方沒按過開始、被封鎖）＝那一則改由主 bot 不響地送，
  並通知一次（類別 `tools`）：「安靜線的那支 bot 送不到你：先私訊它一次。」
- 伺服器版：安靜的 bot 只送給擁有者；成員的安靜線＝主 bot 不響。

Discord 的安靜頻道：設定頁要寫明「這個頻道裡的每個人都看得到安靜線的通知」。頻道送不到＝退回私訊（不提示）。

### 1.4 鎖住的四類

`approval`、`question`、`stepup`、`safety`：

- `lane` 一律 `main`、`sound` 一律 `true`；設定頁那兩格是灰的。
- 入口的勾選：`safety` 的網頁照舊關不掉。四類都一樣——**不能把接上的聊天入口全部關掉**（存的時候檢查：至少留一個接上的入口；只有網頁的人就是網頁）。
- 對話裡的東西本來就在主線：回覆、核准卡、AI 的問題、驗證碼的提示都是從那段對話的管子送的，**不經過通知中心**。
  這四類是給「主動送」的情況用的（過期的卡、被叫醒那一輪出的卡、解鎖被鎖住的通知…）；凡是主動送這幾種東西，`kind` 一定要用這四個之一。

## 2. 升級

- 送出時 `Route.escalate` 不是空的，而且這一則**有辦法被處理**（有 `actions`，或送的人給了 `key`）：在通知的紀錄裡記 `escalate_at = 現在 + after_min`。
  沒有按鈕也沒有 `key` 的＝不升級（沒有東西可以判斷「處理了沒」），log 一行。
- 「處理了」＝下面任何一個：按了那一則的任何按鈕；在網頁標成已讀；送的人叫了 `hub.settle(uid, key)`（新的小入口）；走送達層的被 `delivery.resolve()`。
- 常駐迴圈每 30 秒看一次（任務 `system.notify`；沒有 runtime 時在下一次 `hub.notify` 順便看）：到了 `escalate_at` 還沒處理＝照 `to` 的線與聲音**再送一次**，
  字的最前面加「⏫ 還沒處理：」，按鈕照舊；然後把 `escalate_at` 清掉。**只升級一次。**
- 升級的那一次不受去重影響（它是同一件事的第二次，用自己的鍵 `<key>#escalated`）。
- 時間記在通知的紀錄裡（磁碟上），重開之後照樣會升級。紀錄被擠掉（每人只留 100 則）＝不升級。

## 3. 工具宣告自己會發哪幾類

### 3.1 pack.json

```json
"requires": {"system": ["notify"]},
"notify": {
  "kinds": [
    {"kind": "progress", "label": "搬檔的進度", "lane": "quiet", "sound": false},
    {"kind": "stuck", "label": "搬檔卡住了", "lane": "quiet", "sound": false,
     "escalate": {"after_min": 30, "to": {"lane": "main", "sound": true}}}
  ]
}
```

| 規則 | |
|---|---|
| 最多 8 類；`kind` 是一段（`[a-z][a-z0-9_]{0,23}`） | 登記成 `<工具名>.<kind>`（所以不會跟核心或別的工具撞名） |
| `label` | 一行、24 字內，過 `agent.index` 那一套文字檢查 |
| 要先宣告 `requires.system` 有 `notify` | 沒有＝第 1 關拒 |
| 不能宣告 `locked`、`locked_channels`、`off` | 寫了＝拒 |
| 安裝報告 | 多一段「🔔 這個工具會發這幾類通知」：每類一行（名字、哪條線、響不響、會不會升級） |
| 升級報告 | 新增的類、改成主線、改成會響、加了升級＝一般字（使用者可以在設定頁改回去；它不是權限） |

工具發了沒宣告過的類＝當成 `<工具名>.general`，再往上就是 `general`。

### 3.2 工具怎麼發（這份新定的介面）

| 工具種類 | 寫法 |
|---|---|
| kind=cli、kind=mcp | 成功信封多一個選填的 `"notify": [{"kind": "progress", "text": "…", "key": "…"}]` |
| kind=python | `pack.notify(user, text, *, kind="progress", key=None)` |

- 收的人**只有一個**：這次指令是替誰跑的那個人（排程＝排程的主人）。工具不能指定別人。
- 每次呼叫最多 3 則；`text` 純文字、500 字內（超過截短）；`key` 選填（`[A-Za-z0-9_.:-]{1,64}`，同一個 `key` 12 小時內不重送——現有的去重）。
- 這一版**不能帶按鈕**（按鈕要綁在節點上；之後另外定）。所以工具的通知要升級，一定要給 `key`，並在事情處理掉時用下一次的信封帶
  `"notify_settle": ["<key>"]`（python：`pack.notify_settle(user, key)`）。
- 人或 AI 當場叫的指令：結果照舊直接回給他；`notify` 是「另外也告訴他一聲」，主要給背景與排程的指令用。
- 次數上限：每個工具每小時 30 則（提案值）。超過的丟掉，並通知擁有者一次（類別 `tools`）。
- 文字過 `mcp.redact` 與 `kit.mask_tokens`；送出前照通道跳脫。
- SDK：`Ok(message, data, notify=[…])`；單檔 SDK 與 `synox-sdk check` 一起更新。舊工具不用改。

## 4. 設定與設定頁

```json
"notify": {
  "desktop": true,
  "lanes": {
    "telegram": {"quiet_token": "vault:telegram_quiet_token"},
    "discord": {"quiet_channel_id": ""}
  }
}
```

設定 → 電腦與備份 →「🔔 通知要送到哪裡」那張表，每一類多兩格：**線**（主線／安靜線）、**響**（開／關）。鎖住的類是灰的。
工具宣告的類排在核心的後面，前面寫工具的名字。下面一塊「安靜線要送到哪」：Telegram 的第二支 bot（貼 token、試送一則）、Discord 的頻道。

API（`notify/web_api.py`）：

- `GET /api/notifications/prefs` 多回每一類的 `lane`、`sound`、`locked`、`escalate`（唯讀）、`source`（`core`｜`<工具名>`）。
- `POST /api/notifications/prefs` 的 body 從 `{"off": …}` 變成 `{"off": {…}, "lane": {kind: "main|quiet"}, "sound": {kind: true|false}}`；
  只帶 `off` 的舊請求照舊能用。鎖住的類寫了＝忽略那一項（不整個拒）。
- `GET /api/notifications` 的每一則多 `lane`、`sound`（前端決定跳不跳、播不播）。
- 存檔（`notify/store.py`）：`prefs` 多 `lane`、`sound` 兩個字典；舊檔沒有＝空的。

`python -m synox doctor`：列出每一類實際的線與聲音（照擁有者）、安靜線接在哪、覆寫檔裡看不懂或被忽略的列。

## 5. 跟先前的聊天機器人分流表的對照

那邊是「流.種類 → 哪一支 bot、響不響」。搬過來時：主機 bot＝主線、緩衝 bot＝安靜線。

| 那邊的列 | 那邊 | SYNOX 的類 | 線／響 | 備註 |
|---|---|---|---|---|
| `chat` | 主機、響 | —— | 主線 | 對話的回覆不經過通知中心 |
| `pending` | 主機、響 | `approval`、`question` | 主線、響（鎖住） | |
| `pending.panel` | 主機、不響 | `pending` | 主線、不響 | 「在等你的一覽」那個 PR 才加這一列 |
| `task` | 緩衝、不響 | `task` | 安靜、不響 | |
| `task.problem` | 主機、響 | `task.problem` | 主線、響 | |
| `task.done` | 主機、不響 | `task.done` | 主線、不響 | |
| `task.card.approve`／`decide`／`report`／`alert`／`digest` | 主機、響 | 那個任務系統的工具宣告的 `approve`… | 主線、響 | 卡片來自外部的任務系統＝一個私人工具；它在 pack.json 宣告自己的類 |
| `task.card.confirm` | 主機、不響 | 同上 `confirm` | 主線、不響 | |
| `task.card.stuck`＋`.escalate`（30 分） | 緩衝、不響 → 主機、響 | 同上 `stuck` | 安靜、不響、`escalate` 30 分 → 主線、響 | |
| `task.card.info` | 緩衝、不響 | 同上 `info` | 安靜、不響 | |
| `task.card.silent` | 緩衝、不響 | —— | —— | 只原地改、不發新則：不是通知 |
| `remind` | 緩衝、不響 | 行事曆工具宣告的類 | 安靜、不響 | |
| `remind.due` | 主機、響 | `alarm` | 主線、響 | |
| `remind.brief` | 緩衝、響 | `brief` | 安靜、響 | |
| `remind.followup` | 主機、不響 | `followup` | 主線、不響 | |
| `remind.card.*`（九列） | 同 `task.card.*` 的樣子，`digest` 在緩衝、響 | 行事曆工具宣告的類 | 照那邊的值 | |
| `remind.drill` | 主機、響 | 練習工具宣告的類 | 主線、響 | 到點要人按「開始」的卡 |
| `remind.companion`、`remind.checkin` | 緩衝、不響 | 陪伴類工具宣告的類 | 安靜、不響 | 常駐的那張卡是原地改 |
| `money` | 緩衝、不響 | 記帳工具宣告的類 | 安靜、不響 | |
| `money.prompt` | 主機、響 | 記帳工具的 `prompt` | 主線、響 | 要人回答的 |
| `news` | 緩衝、不響 | 情報工具宣告的類 | 安靜、不響 | |
| `news.ask` | 主機、響 | 情報工具的 `ask` | 主線、響 | |
| `system` | 緩衝、響 | `tools`、`update`、`assistant` 各自的列 | 照 1.1 的表 | 那邊一列，這邊本來就分三類 |
| `system.hello` | 主機、不響 | `greeting` | 安靜、不響 | **不一樣**：SYNOX 的預設放安靜線；要跟那邊一樣就在覆寫檔寫一列 |
| `system.trigger` | 主機、響 | `task.problem` | 主線、響 | 連動被斷路器停掉 |
| `service.*`（五列） | 服務 bot 等 | —— | —— | 不搬：給別人用的那支 bot 不放進個人的 SYNOX |
| （那邊的規則）要他決定的一律主機 | | 鎖住的四類 | 主線、響 | |

擁有者自己那台的實際設定（哪一類要不要響）不進這個 repo：搬的時候寫進他的 `data/notify_kinds.json`。

## 不做的事

- **「幾支 bot」的模型**：不做。只有「每個入口兩條線」。
- **給別人用的 bot、廣播**：不做。
- **勿擾時段、依時間換線**：這一版不做（常駐助理自己的安靜時段照舊，那是另一件事）。
- **升級超過一次、升級到別的人**：不做。
- **工具的通知帶按鈕**：這一版不做。
- **工具指定收件人、指定入口、指定「一定要響」**：永遠不做；工具只能宣告預設，使用者說了算。
- **讓覆寫檔或使用者把鎖住的四類改成安靜或關掉**：永遠不做。
- **改送達層**（確認、重試、去重，`notify/outbox.py`）：不改，只是多帶線與聲音。

## 測試怎麼寫

`tests/test_notify_lanes.py`（假的 Telegram／Discord 管子、假時鐘；不連網）：

1. `lanes.lookup`：`task.card.info` → `task`；完全不認得 → `default`；三層都有時用最細的。
2. `lanes.load`：覆寫檔逐欄蓋過；覆寫檔想動鎖住的類、想加 `locked`＝那一欄被忽略；格式錯的一列被丟掉、其他列照用；沒有覆寫檔＝repo 的表。
3. `route` 的順序：鎖住 > 個人偏好 > 覆寫檔 > 工具宣告／repo > 上一層 > `default`，每一級一個案例。
4. 既有行為：沒有任何設定時，`alarm`、`safety`、`tools`、`assistant`、`general` 的送法跟現在逐字相同（既有測試不改就過）；`update`、`greeting` 變成不響。
5. Telegram、同一支 bot：安靜線＝送出的請求帶 `disable_notification`；主線而且 `sound: true`＝不帶；`sound: false` 的主線＝帶。
   HTML 與按鈕的參數跟 `send_message` 產生的一樣。
6. Telegram、第二支 bot：沒按鈕的安靜線通知從第二支送；**有按鈕的**從主 bot 送、不響；第二支送失敗（被封鎖）＝改主 bot 不響地送＋通知一次；
   token 不出現在任何 log。SYNOX 沒有對第二支 bot 開任何收訊。
7. Discord：安靜線有設頻道＝送到頻道；沒設＝私訊帶 `SUPPRESS_NOTIFICATIONS`；頻道送不到＝退回私訊。
8. 網頁：`GET /api/notifications` 的那一則有 `lane`；安靜線的不算進未讀數字。
9. 電腦提醒視窗：安靜線＝那個入口是 `skipped`，不是失敗。
10. 鎖住的四類：`save_prefs` 想改線、關聲音＝沒變；想把接上的聊天入口全部關掉＝被拒並說原因；`safety` 的網頁照舊關不掉。
11. 升級：有按鈕、沒按 → 到時間再送一次，前面有「⏫」、走 `to` 的線；按了／網頁已讀／`settle` → 不升級；只升級一次；重新建 hub（模擬重開）之後照樣升級；
    沒按鈕也沒 `key` 的不升級。
12. 去重、送達確認、重試：既有的 `tests/test_remind_contract.py` 與送達層的測試不改就過。
13. 伺服器版：成員的安靜線不會用到擁有者的第二支 bot；每個人的偏好互不影響。

`tests/test_notify_tools.py`：

14. 第 1 關：`notify.kinds` 合格；超過 8 類、`kind` 有點、寫了 `locked`、沒宣告 `requires.system: ["notify"]`＝各拒。
15. 工具宣告的類登記成 `<工具名>.<kind>`、出現在設定頁的資料裡、可以被個人偏好改線。
16. 假的 cli 工具回帶 `notify` 的信封：收的人是下令的那個人；照宣告的線送；沒宣告的類＝`general`；一次 4 則＝只送 3 則；
    `text` 超過 500 字被截；有金鑰樣式的字被遮。
17. 次數上限：第 31 則被丟、擁有者收到一次通知。
18. `notify_settle`：之後不升級。
19. kind=python 的 `pack.notify`：同上的幾條。
20. 舊工具（信封沒有 `notify`）：行為不變。

## 跟規劃不一樣的地方

| 規劃 | 這份 | 為什麼 |
|---|---|---|
| `telegram.quiet_token` | `notify.lanes.telegram.quiet_token`、`notify.lanes.discord.quiet_channel_id` | `config.json` 已經有 `notify` 這一塊，而且沒有 `telegram` 這一塊（Telegram 的 token 在最上層）（**已查證**） |
| 第二支 bot「只送不收」 | 加一條：有按鈕的通知不走第二支 bot | 沒有人收訊，按鈕按了沒有反應 |
| 「工具發通知時帶 `kind`（SDK 的通知介面）」 | 這份順便把那個介面定出來 | 現在沒有（**已查證**） |
| 升級：「還沒被處理（按鈕沒按）」 | 「處理了」多兩種（網頁已讀、送的人說處理了）；沒有按鈕也沒有 `key` 的不升級 | 工具的通知這一版沒有按鈕；只在網頁看的人沒有「按」這件事 |
| 「永遠主線」的四類 | 講清楚它們在對話裡時不經過通知中心；這四類管的是主動送的情況 | 核准卡現在是從對話的管子送的（**已查證** `agent/approve.py`） |
| 既有的類沒說怎麼設 | `update`、`greeting` 預設改成安靜、不響；其他不變 | 要有一個不讓現有使用者嚇一跳的預設 |
| 分流表的對照 | 外部系統與各專案的卡片類別不放進核心的表，由各自的工具宣告 | 核心的表是公開發行版的預設，不該有只屬於一個人的類別 |
