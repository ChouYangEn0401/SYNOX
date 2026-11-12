# Discord 觀念篇：私訊、伺服器、頻道、每個頻道不一樣（2026-11-12）

**給誰**：覺得 Discord 比 Telegram 難懂、不確定「一支 bot 到底能怎麼用」的人。
**搭配**：步驟教學在 [tutorials/discord/](tutorials/discord/README.md)（HTML 版 `index.html`，純文字版 `README.md`）；設定欄位的完整說明在 [discord.md](discord.md)。
**依據**：Discord 官方開發者文件（2026-11 讀的；頁面已搬到 `docs.discord.com/developers`）與 `src/synox/discord/` 的程式。
**誠實聲明**：SYNOX 的 Discord 通道到目前為止**只用程式內的假傳輸測過**，還沒跟真的 Discord 連過（[README](../README.md) 頂端的 alpha 說明）。
這份文件裡「Discord 怎麼運作」的部分是查官方文件得到的；「SYNOX 會怎麼做」的部分是照程式寫的；兩者接在一起的實際效果要等真機驗證。標了「未驗證」的地方請當成待確認。

---

## 1. 一句話版

Discord 的 bot 不是「一個聊天對象」，而是「一個帳號」：它可以被**私訊**，也可以被**加進伺服器**；加進伺服器之後它在每個**頻道**裡能不能看、能不能講，由那個伺服器的**權限**決定；它要**回什麼**，則完全由 SYNOX 這邊的設定決定。
所以「一支 bot 同時能私訊、能在伺服器公開用、每個頻道行為不一樣」在 Discord 這邊**都是允許的**；差別在 SYNOX 現在**做到哪裡**（第 4 節）。

## 2. 名詞對照（Discord 這邊）

| 名詞 | 是什麼 | 跟 Telegram 比 |
|---|---|---|
| **Application**（應用程式） | 你在 Developer Portal 建的那一個「專案」，有 Application ID（＝ client_id） | BotFather 建的那個 bot |
| **Bot user**（bot 帳號） | Application 底下的機器人帳號，有自己的名字、頭像、**token** | 同上（Telegram 一個 bot 就是一個） |
| **Token** | bot 登入用的密碼，Bot 頁按 **Reset Token** 才看得到、**只顯示一次**；外洩就再 Reset 一次讓舊的失效 | BotFather 的 token |
| **Gateway** | bot 自己**往外**連的 WebSocket，收訊息用；SYNOX 走這條，**不開埠、不要公開網址** | long polling |
| **Intent** | 連 Gateway 時「我要收哪幾類事件」的宣告；其中 **Message Content** 是特權（privileged），要在 Portal 打開 | 沒有對應（Telegram 用 privacy mode） |
| **伺服器 (guild)** | 一群頻道＋一群成員＋身分組的那個「社群」 | 群組（但有層級） |
| **頻道 (channel)** | 伺服器裡的一個房間（`#general`…）；每個頻道可以覆寫權限 | 群組裡的話題（topic） |
| **私訊 (DM)** | 你跟 bot 一對一的對話；Discord 把它當成一個「沒有 guild_id 的頻道」 | 私聊 |
| **身分組 (role)** | 伺服器內的角色，決定權限；bot 進伺服器時會拿到一個同名身分組 | 群組管理員（粗很多） |
| **權限 (permissions)** | 位元旗標；bot 在某頻道能不能看（View Channel）、講（Send Messages）、讀歷史（Read Message History） | 沒有這麼細 |
| **開發者模式 (Developer Mode)** | Discord 使用者設定 → 進階 → 開啟後，右鍵就能「複製 ID」 | 沒有（Telegram 的 id 要問 bot） |
| **Slash 指令** | Discord 原生的 `/` 選單（要先向 Discord 登記）；**SYNOX 沒做**，SYNOX 的 `/help` 只是文字 | Telegram 的指令選單 |

ID 都是一串 17–19 位數字（snowflake），**不是秘密**，可以寫進 `config.json`。Token 才是秘密。

## 3. 三種用法（Discord 允許的）

```
                ┌────────────────────────────────────────────────┐
                │           Discord Developer Portal             │
                │   Application ──► Bot user（token、intents）    │
                └───────────────┬────────────────────────────────┘
                                │ 同一支 bot 可以同時出現在下面三種地方
          ┌─────────────────────┼─────────────────────────────────┐
          ▼                     ▼                                 ▼
   (a) 私訊 DM            (b) 伺服器 guild                 (c) 同一伺服器、不同頻道
   你 ⇄ bot 一對一         #general  所有成員都看得到          #公告   bot 只能看、不能講
   沒有 guild_id           bot 被 @ 才回（SYNOX 規則）         #問答   bot 能看能講
   只有你看得到回覆         每個人都能叫它                      #內部   bot 根本看不到（權限覆寫）
```

### (a) 私訊：只有你跟它

- 想私訊一支 bot，你跟它要先「認識」：**最常見的方法是 bot 已經在一個你也在的伺服器**（可以是你自己新建、只有你一個人的伺服器）。
  Discord 的「Create DM」與「Cannot send messages to this user（50007）」規則都是這個意思。
- Portal 的 **Installation → User Install**（把 app 加到「我的應用程式」）照官方文件是給 **slash 指令**用的（「user-installed apps can only use commands」）。
  SYNOX 沒有登記任何 slash 指令，所以**User Install 能不能讓 SYNOX 收到你的私訊文字，未驗證**；本文件與教學一律推薦「邀進伺服器」這條。
- 私訊裡沒有「權限」這回事：bot 能收到你打的每一個字（Discord 規定私訊給 app 的內容本來就不受 Message Content intent 限制；
  不過 SYNOX 連線時**一律宣告**要 Message Content，所以 Portal 還是要打開，否則連不上（4014））。

### (b) 伺服器：一群人共用

- 用 **OAuth2 邀請連結**（`scope=bot`＋權限數字）把 bot 加進伺服器；只有該伺服器有 **Manage Server** 權限的人（通常是管理員）能邀。
- 進去之後 bot 是一個「成員」：拿到一個同名身分組，權限照 `@everyone` ＋ 身分組 ＋ 各頻道的覆寫算。
- 伺服器裡的訊息事件（`GUILD_MESSAGES`）每一則都會送給 bot，但**沒開 Message Content intent 的話內容是空的**（例外：@到 bot 的那則、回覆 bot 的那則）。
- 誰能叫它：預設**每個看得到那個頻道的人**都能。要限制「誰可以命令 bot」，Discord 這邊只能靠頻道權限（讓某些人看不到那個頻道），
  bot 自己這邊要靠程式（SYNOX 的 `role_map`、`max_effect`、allowlist）。

### (c) 同一支 bot、不同頻道不一樣

Discord 給的工具有兩層：

1. **頻道權限覆寫**（伺服器管理員設）：在 `#內部` 把 bot 的身分組 View Channel 關掉 → bot 連訊息都收不到；在 `#公告` 關 Send Messages → 收得到、回不了。
   這是「**能不能**」，是 Discord 幫你擋的，最可靠。
2. **bot 自己看 channel_id**（程式設）：同一則事件都帶 `guild_id`、`channel_id`，程式可以決定「在這個頻道只做查詢、那個頻道也能寫」。
   這是「**要不要**」，是 SYNOX 這邊的事。

SYNOX 今天做到哪一層，看下一節。

## 4. 對照到 SYNOX：今天做得到、做不到

| 你想要的 | Discord 允許嗎 | SYNOX 今天 | 怎麼設 |
|---|---|---|---|
| 私訊 bot，像 Telegram 一樣用全部功能（指令、AI、按鈕、提醒通知） | ✅ | ✅ **私訊型 bot**（`surface: "dm"`，預設） | [discord.md §1–4](discord.md) |
| 同一支 bot 既私訊又在伺服器頻道回 | ✅ | ❌ **一支 bot 只能二選一**：私訊型只收私訊、頻道型只收列出的頻道。要兩種就建**兩個 Application、兩個 token** | `bots` 寫法，一個 `dm`、一個 `channel` |
| 在伺服器某個頻道裡，大家都能叫它 | ✅ | ✅ **頻道型 bot**（`surface: "channel"`）：只收 `guilds.<伺服器>.channels` 列出的頻道、被 @（或以 `/` 開頭）才回、回覆引用發話者 | [discord.md §3c](discord.md) |
| 頻道裡跟 AI 聊 | ✅ | ✅ 選用，要設整支 bot 的每月額度 `pool_usd_month`；沒有工具卡、沒有個人資料 | [discord.md §3d](discord.md) |
| 頻道裡做危險動作（刪東西、花錢、跑程式） | ✅（Discord 不管） | ❌ **程式永遠擋**：`max_effect` 不能是 `danger`，確認卡不送進頻道，回「這個動作要到私訊做」 | 不能開 |
| 頻道裡用記帳、記事、提醒這種「每個人自己的資料」 | ✅ | ❌ `data: user` 的 pack 在頻道裡當作不存在（怕洩漏誰的資料）。目前**沒有任何出廠工具宣告 `surfaces: ["channel"]`**，所以頻道型 bot 今天只有 `/help`、`/start`、`/exit` 和頻道 AI | 要等工具作者在 pack.json 宣告 `channel`＋`data: shared` |
| Discord 身分組 → SYNOX 角色 | ✅ | ✅ `role_map`，最高只到成員（管理員要擁有者用 `/user_role` 給）；只影響那一次請求 | [discord.md §3c](discord.md) |
| **同一支 bot，A 頻道只能查、B 頻道可以寫** | ✅ | ⚠️ **只做到一半**：allowlist 是「每個頻道」的（沒列就不收），但 `packs`、`max_effect`、`trigger`、`ai`、節流是「**每支 bot**」的，不是每個頻道的 | 今天的做法：**一個頻道一支 bot**（第 6 節）；真正的每頻道設定是提案（第 7 節） |
| Discord 原生 slash 指令選單 | ✅ | ❌ 沒做；指令照打字 `@bot /help` | — |
| 收圖片、檔案 | ✅ | ❌ 沒做（頻道 AI 只看得到檔名） | — |
| 多個伺服器 | ✅ | ✅ 頻道型 bot 的 `guilds` 可以列好幾個伺服器 | — |

## 5. 決定表：我該選哪一種？

| 情境 | 推薦設定 | 要建幾個 Application | 要開的 intent | 邀請連結的權限 | 風險等級 |
|---|---|---|---|---|---|
| **① 只有我自己用（私訊）** | 一支私訊型 bot；用「邀進一個只有我的伺服器」讓它收得到我的私訊 | 1 | Message Content | `scope=bot`，權限給 Send Messages（2048）就夠；私訊不看伺服器權限 | 低。配對前誰的私訊都不收；個人版陌生人一律擋 |
| **② 我和幾個朋友的私人伺服器** | 私訊型 bot（每人各自私訊它用自己的資料；伺服器版 mode 才有成員制度）＋**選用**一支頻道型 bot 放在一個頻道給大家查 | 1 或 2 | Message Content | 頻道型：View Channels＋Send Messages＋Read Message History（68608） | 中。私訊型照個人版／伺服器版的角色；頻道型最多 `write` 且只對 `data: shared` 的工具 |
| **③ 公開頻道，誰都能叫** | **只放頻道型 bot**；`max_effect: "read"`（預設）；`rate_per_minute`、`room_rate_per_minute` 留預設或更嚴；頻道 AI 要就設小一點的 `pool_usd_month`；**私訊型 bot 另一個 Application，不要邀進公開伺服器** | 2（私訊型留著自己用） | Message Content | 同上 68608；不要給 Administrator、Manage 之類 | 高（見第 8 節）。程式擋了危險動作與個人資料，但花錢（AI 額度）、被灌爆（節流擋）、bot 名字被人冒用都要留意 |
| **④ 每個頻道不同功能** | 今天：**一個頻道一支頻道型 bot**（各自的 `packs`、`max_effect`、`trigger`、`ai`）；或先用 Discord 的頻道權限覆寫擋掉不該看的頻道 | 每個「功能組合」一個 | Message Content | 68608，再用頻道覆寫收窄 | 中。見第 6、7 節 |

挑完之後去 [tutorials/discord/](tutorials/discord/README.md) 照步驟做。

## 6. 情境 ④ 今天怎麼做（不改程式）

想要「`#查詢` 只能查字典、`#記錄` 可以寫共用的清單」：

```json
"channels": { "discord": { "bots": {
  "me":     { "surface": "dm", "packs": "all" },
  "lookup": { "surface": "channel", "packs": ["dict"], "max_effect": "read",
              "guilds": { "<伺服器 id>": { "channels": ["<#查詢 的 id>"] } } },
  "log":    { "surface": "channel", "packs": ["shared-list"], "max_effect": "write",
              "guilds": { "<伺服器 id>": { "channels": ["<#記錄 的 id>"], "role_map": { "<身分組 id>": "member" } } } }
} } }
```

- `lookup`、`log` 各是一個 Application、各一個 token（`python -m synox discord token --bot lookup`…）、各自邀進伺服器。
- 兩支 bot 在 Discord 成員清單裡是兩個名字（例如「SYNOX 查詢」「SYNOX 記錄」），使用者反而比較清楚在 @ 誰。
- 再用 Discord 的頻道權限覆寫把 `lookup` 的身分組從 `#記錄` 拿掉（反之亦然），就算 SYNOX 設定寫錯，Discord 也不會把那個頻道的訊息送過來。
- 缺點：Application 數量跟頻道數量一起長；每支 bot 一條 Gateway 連線（十幾支以上要注意 Discord 對同一 IP 的連線頻率）。

## 7. 提案：真正的「每頻道設定」（還沒做、不在這次範圍）

程式現況：`BotSpec`（`src/synox/discord/bots.py`）的 `packs`／`max_effect`／`trigger`／`ai`／`rate_per_minute` 是 bot 一層；`guilds.<g>.channels` 只是 id 清單。
`policy.decide` 用 `policy.current_bot()`（contextvar）拿 bot 範圍，`chat_id` 已經是頻道的負號 id。

最小改法（向下相容）：

1. **設定**：`guilds.<g>.channels` 除了字串，也接受物件：
   ```json
   "channels": {
     "<#查詢 id>": { "packs": ["dict"], "max_effect": "read" },
     "<#記錄 id>": { "packs": ["shared-list"], "max_effect": "write", "trigger": "/", "ai": false }
   }
   ```
   物件裡的欄位只能是 bot 一層已有的那幾個（`packs`、`max_effect`、`trigger`、`ai`、`rate_per_minute`、`persona`），沒寫的沿用 bot 的；`max_effect` 仍不能 `danger`。
   `bots._guilds` 解析成 `{"channels": {id: ChannelSpec|None}}`；`BotSpec.allows()` 介面不變。
2. **套用**：`RoomEntry` 收訊時算 `spec.for_channel(channel_id)` → 一個**派生的 BotSpec**（欄位覆蓋），丟給 `policy.using_bot(derived)`。
   這樣 `decide`、`/help`、AI 工具清單、`RoomAgent`、節流**一行都不用改**（它們只看 `current_bot()`）。
3. **報告**：`scope.report` 每個頻道多列一行（會出現的 pack、上限、觸發）；`/bot_status`、doctor 跟著出來。
4. **測試**：`tests/test_discord_channel.py` 加「同一支 bot、兩個頻道、不同 packs／max_effect」；設定錯誤（頻道物件寫 `danger`、不認得的欄位）要有人話。

不做的：每頻道不同 token（那就是另一支 bot）、每頻道不同 `pool_usd_month`（額度仍是整支 bot 一池，比較好管）。
要不要做、優先序，請擁有者決定（可以記進 QuestionToUser）。

## 8. 公開頻道的風險（情境 ③）

| 風險 | Discord 這邊 | SYNOX 這邊（程式已擋的） | 你要做的 |
|---|---|---|---|
| 任何人都能命令 bot | 看得到頻道的人都能 @ 它 | 頻道裡只有 `surfaces: channel`＋`data: shared` 的工具；DANGER 永遠拒；WRITE 要 `max_effect: write`＋成員以上；訪客聊得到 AI 但沒有工具 | 頻道型 bot `max_effect` 留 `read`；不要把私訊型 bot 邀進公開伺服器 |
| 危險動作的確認卡被別人按 | — | 確認卡**不送進頻道**；頻道裡的按鈕只有發話者能按 | 要確認的事到私訊做 |
| AI 額度被燒光 | — | `pool_usd_month` 一池、用完整支 bot 停；三層節流（人／頻道／AI） | 額度設小、看 `/bot_status` |
| bot 回覆洩漏 token／金鑰 | — | 送出前遮罩已存的 secret 與看起來像 token 的字（多一層） | 不要在 persona、工具結果裡放秘密 |
| token 外洩（貼錯地方、截圖） | 任何拿到 token 的人就是這支 bot | token 只在保管箱、不進 log | **Portal → Bot → Reset Token**，再 `python -m synox discord token` 重存 |
| 被灌爆（rate limit、429） | 全域每秒 50 次 REST；超過回 429；10 分鐘 1 萬次無效請求會被 Cloudflare 暫時封 | 收訊節流靜默略過；回覆用 REST | 不要把 `rate_per_minute` 調太高 |
| 有人把 bot 邀進別的伺服器 | Portal「Public Bot」開著時，任何有 client_id 的人都能邀 | 沒列在 `guilds` 的伺服器一律不收不回 | 不想被邀就把 Bot 頁的 **Public Bot** 關掉 |

## 9. 查證紀錄（2026-11-12）

| 說法 | 來源 | 狀態 |
|---|---|---|
| 特權 intent：Presence、Server Members、Message Content；沒開就連線時 4014 | docs.discord.com/developers/events/gateway、topics/opcodes-and-status-codes | ✅ 官方 |
| 沒開 Message Content 時 `content` 為空；例外：私訊給 app、@到 app、回覆 app、app 自己送的 | docs.discord.com/developers/gateway/you-might-not-need-a-privileged-intent | ✅ 官方 |
| 特權 intent 的審核門檻：以前「100 個伺服器」，現在是「**能看到 app 的不重複使用者超過 1 萬**」才要申請，以下自己在 Portal 開關 | docs.discord.com/developers/gateway/getting-started-with-privileged-intent-review | ✅ 官方（新規則） |
| Intent 位元：GUILDS 1、GUILD_MESSAGES 512、DIRECT_MESSAGES 4096、MESSAGE_CONTENT 32768；SYNOX 私訊型用 4096+32768、頻道型用 1+512+32768 | 同上＋`gateway.py` | ✅ |
| 權限位元：View Channel 1024、Send Messages 2048、Read Message History 65536（合計 68608）；Administrator 8；Manage Server 32 | docs.discord.com/developers/topics/permissions | ✅ 官方 |
| 頻道覆寫順序：@everyone 基底 → 身分組 → 頻道的 @everyone 覆寫 → 頻道的身分組覆寫 → 頻道的成員覆寫；Administrator 跳過全部 | 同上 | ✅ 官方 |
| `scope=bot` 把 bot 加進使用者選的伺服器；`applications.commands` 隨 `bot` 自動含；`integration_type=1` 是 User Install | docs.discord.com/developers/topics/oauth2 | ✅ 官方 |
| 只有伺服器 **Manage Server** 權限的人能把 app 裝進伺服器 | docs.discord.com/developers/resources/application | ✅ 官方 |
| User Install 的 app「只能用指令」（slash）；「只裝到伺服器的 app 不能在私訊用」 | resources/application、quick-start/getting-started | ✅ 官方；**對 SYNOX 的意義未驗證**（SYNOX 沒有 slash 指令） |
| bot 要私訊某人，通常要有共同伺服器；否則 50007 | 官方錯誤碼表＋社群（discord.js guide） | ⚠️ 共同伺服器的說法是社群共識，官方只給錯誤碼 |
| Close code 4004 token 錯、4013 intent 值錯、4014 特權 intent 沒開；都不能 resume | topics/opcodes-and-status-codes | ✅ 官方 |
| JSON 錯誤 50001 Missing Access、50013 Missing Permissions、50007 Cannot send messages to this user、40003 開私訊太快 | 同上 | ✅ 官方 |
| REST 全域每秒 50 次；429 帶 `retry_after`；10 分鐘 1 萬次 401/403/429 → Cloudflare 暫封 | topics/rate-limits | ✅ 官方 |
| 每條 Gateway 連線 24 小時最多 1000 次 IDENTIFY；2500 個伺服器以上要分片 | events/gateway | ✅ 官方 |
| Slash 指令要用 HTTP 向 Discord 登記；全域指令在私訊可用的前提是 bot 跟使用者有共同伺服器 | interactions/application-commands | ✅ 官方（SYNOX 沒做） |
| 開發者模式：使用者設定 → 進階 → Developer Mode；右鍵 → 複製 ID | Discord 支援中心文章 206346498（本次抓取被擋 403，內容來自社群轉述與 SYNOX 精靈既有文字） | ⚠️ 選單名稱以你手上的 Discord 版本為準 |
| SYNOX 私訊型 bot 收不到「沒有共同伺服器的人」的私訊 | `src/synox/wizard/discord_probe.py` 的註解（精靈的假設） | ⚠️ 未真機驗證 |
