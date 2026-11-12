# SYNOX 接 Discord：步驟教學（純文字版）

**線上版（HTML Artifact，有示意圖）**：<https://claude.ai/artifact/21KFtvB7EVKsV4bjCE5h1h>
**本機版**：這個資料夾的 [`index.html`](index.html)，雙擊就能開（單一檔案、沒有外部程式；字型從 Google Fonts 載，沒網路也看得到、只是換成系統字型）。
**觀念篇**：[../../discord-concepts.md](../../discord-concepts.md)（私訊／伺服器／頻道／每頻道不同、決定表、SYNOX 今天做到哪）。
**設定欄位的完整說明**：[../../discord.md](../../discord.md)。**真機交接與 D1–D18 測試**：[../../handoff/discord-handoff.md](../../handoff/discord-handoff.md)。

> ⚠ 圖都是示意圖，不是真實截圖；Discord 的選單名稱常改版，照意思找最接近的。
> ⚠ SYNOX 的 Discord 通道到目前為止只用程式內的假傳輸測過，還沒跟真的 Discord 連過。

---

## 0. 先挑情境

| 情境 | SYNOX 設定 | Application 數 | 要開的 intent | 邀請連結的權限數字 |
|---|---|---|---|---|
| ① 只有我自己用（私訊） | 一支私訊型（`surface: "dm"`，預設） | 1 | Message Content | `2048`（Send Messages） |
| ② 我和幾個朋友的私人伺服器 | 私訊型 ＋（選用）頻道型 `max_effect: "read"` 或 `"write"` | 1 或 2 | Message Content | 頻道型 `68608`（View Channels＋Send Messages＋Read Message History） |
| ③ 公開頻道，誰都能叫 | 只有頻道型、`max_effect: "read"`、節流留預設或更嚴；私訊型是另一支，不要邀進公開伺服器 | 2 | Message Content | `68608`；不要給 Administrator |
| ④ 每個頻道不同功能 | 今天：每個頻道一支頻道型 bot；真正的每頻道設定是提案（觀念篇第 7 節） | 每個功能組合 1 個 | Message Content | `68608`，再用 Discord 頻道權限覆寫收窄 |

一支 bot 的 `surface` 只能二選一（私訊型或頻道型），所以「既私訊又在頻道回」要兩個 Application、兩個 token。

## 1. 建 Application（Developer Portal）

1. <https://discord.com/developers/applications> 登入 → 右上 **New Application** → 取名（例如 `SYNOX`）→ 勾同意 → **Create**。
2. **General Information** 頁的 **Application ID** 之後邀請連結會用到（不是秘密）。
3. 每一支 bot（私訊型、每一支頻道型）各一個 Application。

## 2. Bot 頁：拿 token

1. 左邊 **Bot**（新建的 Application 已自帶 bot user）。
2. **Token** 那格 → **Reset Token**（有兩步驟驗證會先問驗證碼）→ 整串複製。**只顯示一次**。
3. 不要貼到聊天、不要截圖、不要寫進 config.json。外洩就再 Reset 一次。
4. 情境 ①②：**Public Bot** 關掉（只有你能邀）。

## 3. 同一頁往下：Privileged Gateway Intents

- 打開 **Message Content Intent**；Presence、Server Members 不用。
- 最下面 **Save Changes** 一定要按。
- 沒開：SYNOX 連上就被踢掉，狀態「Developer Portal 沒開 Message Content intent（4014）」。SYNOX 不管私訊型或頻道型連線時都一律宣告要它。
- 審核：官方現在的門檻是「能看到 app 的不重複使用者超過 1 萬」才要申請（舊規則 100 個伺服器）；個人使用不會碰到。

## 4. OAuth2 → URL Generator：做邀請連結

1. 左邊 **OAuth2** → **OAuth2 URL Generator**。
2. **Scopes** 勾 `bot`。
3. **Bot Permissions**：私訊型只勾 **Send Messages**；頻道型勾 **View Channels**、**Send Messages**、**Read Message History**。不要勾 Administrator。
4. **Generated URL** → Copy。長得像 `https://discord.com/oauth2/authorize?client_id=<Application ID>&scope=bot&permissions=68608`。

懶人版：SYNOX 網頁「設定 → 聊天通道 → Discord」存好 token 後會顯示 `permissions=2048` 的邀請連結（精靈的配對頁也有），私訊型剛好；頻道型自己勾三個。

「Installation → User Install」那條路：官方說 User Install 的 app 只能用 slash 指令，SYNOX 沒有 slash 指令，**能不能收到私訊文字未驗證**；本教學一律走「邀進伺服器」。

## 5. 邀進伺服器；私訊型再去私訊它

**5a 邀進伺服器**（每支 bot 都要）：貼網址 → 用有該伺服器管理權限的帳號 → 「新增至伺服器」選伺服器（沒有就先建一個免費、只有你的）→ 看權限 → 授權。成員清單多一個 bot（離線正常）。

**5b 私訊型**：bot 要收得到你的私訊，你跟它要有共同伺服器（就是 5a 那個）。成員清單找到 bot → 點名字 → 訊息。私訊型 bot 不會在頻道講話。

## 6. 開發者模式與複製 ID（頻道型必做）

1. Discord 左下 ⚙️ 使用者設定 → **進階（Advanced）** → **開發者模式（Developer Mode）** 打開（手機版在 設定 → 外觀 或 進階）。
2. 右鍵（手機長按）：
   - 伺服器圖示 → **複製伺服器 ID** → `guilds` 的鍵
   - 頻道名稱 → **複製頻道 ID** → `guilds.<伺服器>.channels`
   - 伺服器設定 → 身分組 → 右鍵 → **複製身分組 ID** → `role_map`（要對到 SYNOX 成員才需要）
   - 你的名字 → **複製使用者 ID** → 第 8 步手動配對或 `owner_user_id`（非必要）

ID 是 17–19 位數字，不是秘密。

## 7. 把 token 貼進 SYNOX（擇一）

| 路 | 怎麼做 | 適合 |
|---|---|---|
| A. 精靈 | 雙擊 `Setup.bat` → bot 頁選 **Discord** → 貼 token → 檢查 → 下一頁配對 | 第一次裝、情境 ① |
| B. 網頁 | 設定 → 聊天通道 → Discord → 貼 token → 存（會先驗證 bot 名字、顯示邀請連結）；**要重新啟動 SYNOX** | 情境 ①② |
| C. 終端機 | `.venv\Scripts\python.exe -m synox discord token`（多個 bot 加 `--bot 名字`）→ 貼上按 Enter（畫面不顯示）→ 自己改 config.json | 多 bot、頻道型 |

token 只在保管箱 `data\secrets.json.enc`；config.json 只寫 `vault:…`。

情境 ①：
```json
"channels": { "discord": { "enabled": true, "bot_token": "vault:discord_bot_token" } }
```
只用 Discord 的話 `owner_id`、Telegram 的 `bot_token` 可以不寫；配對前誰的私訊都不收。

情境 ②④（`bots` 寫法，跟 `bot_token` 擇一）：
```json
"channels": { "discord": { "bots": {
  "synox":  { "token": "vault:discord_bot_token:synox", "surface": "dm", "packs": "all", "ai": true },
  "lookup": { "token": "vault:discord_bot_token:lookup", "surface": "channel",
              "guilds": { "123456789012345678": { "channels": ["234567890123456789"],
                          "role_map": { "345678901234567890": "member" } } },
              "trigger": "mention", "packs": ["dict"], "max_effect": "read", "rate_per_minute": 5 }
} } }
```

情境 ③（只有頻道型、保守）：
```json
"channels": { "discord": { "bots": {
  "public": { "token": "vault:discord_bot_token:public", "surface": "channel",
              "guilds": { "123456789012345678": { "channels": ["234567890123456789"] } },
              "trigger": "mention", "packs": ["dict"], "max_effect": "read",
              "rate_per_minute": 3, "room_rate_per_minute": 10,
              "ai": { "enabled": true, "pool_usd_month": 2, "rate_per_minute": 1 } }
} } }
```

改完：`.venv\Scripts\python.exe -m synox doctor --offline`，每支 bot 要「✅ token 在保管箱」。

## 8. 配對擁有者（有私訊型 bot 就要；只有頻道型的情境 ③ 不用）

沒配對前私訊型 bot 誰的私訊都不收。擇一：

- **A 精靈**：第 7 步 A 的下一頁出現六位數字 → 打開邀請連結 → 在伺服器成員清單私訊 bot 傳六個數字 → 「✅ 認得你了」。
- **B 網頁**：SYNOX 先啟動 → 設定 → 聊天通道 → Discord → **「配對我的 Discord 帳號」** → 六位數字 → 私訊 bot 傳它（15 分鐘、錯 10 次作廢）；或「手動」貼你的使用者 ID。
- **C 終端機**：`Stop.bat` → `.venv\Scripts\python.exe -m synox discord pair`（`--bot synox` 要私訊型）→ 六位數字 → 私訊 bot → 「✅ 已把 Discord 帳號 … 接到擁有者」。或 config 的 `channels.discord` 寫 `"owner_user_id": "<你的使用者 ID>"`。

配對一次就好（同一個 Discord 帳號對任何私訊型 bot 都是同一個人）；頻道型 bot 不能拿來配對。

## 9. 啟動、測試

1. `Start.bat` → 「✅ SYNOX 開始收訊息了」；有 bot 沒開成會印「⚠️ Discord bot X 沒有開：原因」。
2. 成員清單的 bot 變線上。
3. 私訊型：私訊 `/help`；再試按鈕、AI。
4. 頻道型：列出的頻道 `@bot /help`（真的 @ 到）；沒列的頻道 @ 它應該不回。
5. 私訊 `/bot_status`。
6. 陌生人：個人版擋、伺服器版訪客。
7. 重開：配對還在。

頻道型 bot 今天只會回 `/help`、`/start`、`/exit`（沒有任何工具宣告 `surfaces: ["channel"]`），是正常的。完整 D1–D18 在 handoff 第 9 節；`scripts\smoke_real.py --only discord` 可先離線查。

## 10. 伺服器頻道、每頻道不同功能

Discord 給兩層：**頻道權限覆寫**（Discord 擋：關 View Channel 就收不到、關 Send Messages 就回不了）＋ **bot 看 channel_id**（SYNOX 的 `guilds` allowlist）。

| 你想要 | 今天 |
|---|---|
| 某些頻道的人都能叫 bot | ✅ 頻道型 ＋ `guilds` |
| 頻道裡跟 AI 聊 | ✅ `ai.pool_usd_month` |
| Discord 身分組 → 寫入權 | ✅ `role_map`（最高成員）＋ `max_effect: "write"` ＋ 工具 `data: shared` |
| 頻道裡危險動作、確認卡 | ❌ 永遠不行（程式擋） |
| 頻道裡用記帳、記事、提醒 | ❌ `data: user` 的工具在頻道當作不存在 |
| 同一支 bot、A 頻道只查、B 頻道可寫 | ⚠ 一半：allowlist 是每頻道的，`packs`／`max_effect`／`trigger`／`ai`／節流是每支 bot 的 |
| 原生 `/` 選單、附件 | ❌ |

情境 ④ 今天：一個頻道一支頻道型 bot（各自 packs／max_effect），再用頻道權限覆寫雙保險。提案（每頻道設定、派生 BotSpec）在觀念篇第 7 節。

## 安全（重點）

- 頻道型 `max_effect` 留 `read`；私訊型 bot 不要邀進公開伺服器；情境 ①② 把 Public Bot 關掉。
- 確認卡不送進頻道、頻道按鈕只有發話者能按；要確認的事到私訊做。
- AI 額度 `pool_usd_month` 設小；`/bot_status` 看用量。
- **token 外洩**：立刻 Portal → Bot → **Reset Token**（舊的馬上失效）→ `discord token` 重存 → 重開。`discord token --clear` 只是本機不再存，不會讓舊 token 失效。
- Discord REST 全域每秒 50 次、超過回 429；10 分鐘 1 萬次無效請求會被暫時封。

## 疑難排解

| 看到 | 意思 | 怎麼辦 |
|---|---|---|
| bot 一直離線 | SYNOX 沒啟動或這支沒開成 | 看 Start.bat 小視窗的「⚠️ Discord bot X 沒有開」；`doctor` |
| 4014／Used disallowed intent(s) | Message Content 沒開或沒 Save；token 是另一個 Application 的 | Bot 頁開 intent → Save → 重開；確認是同一個 Application |
| 4004／401 | token 錯或 Reset 過 | 再 Reset、`discord token` 重存 |
| 50001 Missing Access | bot 看不到那個頻道 | 頻道權限給 View Channel；私人頻道加 bot |
| 50013 Missing Permissions | 看得到但不能做 | 補 Send Messages／Read Message History，或用 68608 的連結再邀一次 |
| 50007 Cannot send messages to this user | 沒共同伺服器或對方關了私訊 | 邀進對方也在的伺服器；對方開「允許伺服器成員私訊」 |
| 私訊沒回 | 還沒配對／不是擁有者 | 第 8 步；`/bot_status` |
| 頻道沒回 | 頻道沒列、沒 @ 到、沒權限、被節流、編輯過或只有附件 | handoff「頻道沒反應：照順序檢查」1–10 |
| 「頻道裡只收指令；想聊天請私訊」 | 頻道 AI 沒開 | 正常 |
| 「🔒 這個動作要到私訊做」 | 頻道裡要確認卡 | 正常 |
| 429 | 打太快 | 調低節流 |
| token 外洩 | — | Reset Token → 重存 → 重開 |

## 還沒驗證

- 整條通道沒真連過；User Install 對 SYNOX 的效果；「沒共同伺服器收不到私訊」是社群共識；Discord 選單名稱來自社群轉述；手機版開發者模式位置各版本不同。

---

## 怎麼更新這份教學

- `index.html` 是**手寫的單一檔案**（內嵌 CSS／JS、示意圖用 HTML＋CSS 與一張內嵌 SVG，沒有外部程式；字型從 Google Fonts 載，載不到就用系統字型）。改內容直接改 HTML；`README.md` 是同一份的純文字版，**兩邊要一起改**。
- 檔案開頭刻意沒有 `<!doctype>`／`<html>`／`<body>`（Artifact 發佈時會自動包一層），本機雙擊也能正常開。
- 要重新發佈到同一個 Artifact 網址：在 Claude Code 用 Artifact 工具 publish 同一個檔案並帶上面的 `url`（換路徑或不帶 url 會變成新的網址，記得回來改這裡的連結）。
- 內容依據：`docs/discord-concepts.md` 第 9 節的查證紀錄（官方文件網址）＋ `src/synox/discord/`（`gateway.py` 的 intent 數值、`bots.py` 的欄位）。程式改了（新欄位、新的錯誤訊息、精靈／網頁的按鈕名稱）要回來對一次。
- 示意圖是刻意畫的，不是截圖：Discord 改版時改文字就好，不用重新截圖；但「以官方文件為準」的提醒要留著。
- 這份教學屬於 `docs/tutorials/`（索引在 `docs/tutorials/README.md`，由安裝流程的教學清單統一接入）。
