# Discord 通道：現況與設定（2026-11-09，含多 bot）

## 現況（最小可用版）

| 項目 | 狀態 |
|---|---|
| 私訊收訊（文字、指令、直接跟 AI 講話） | ✅ |
| 回覆（文字、超過 2000 字自動切段、按鈕、改訊息、刪訊息、傳本機檔案） | ✅ |
| 按鈕（Telegram 的 inline 按鈕 → Discord 按鈕；按了照樣經過權限檢查） | ✅ |
| 主動通知（提醒、排程、背景工作做完）送到 Discord | ✅ 只用 Discord 的人走 Discord；有 Telegram 的擁有者照舊走 Telegram |
| 只有 Discord、沒有 Telegram 也能啟動 | ✅ |
| 擁有者配對（私訊 bot 六位數字） | ✅ `python -m synox discord pair` |
| 一個 SYNOX 開好幾個私訊型 bot（各自的 token；回覆用收到訊息的那個 bot） | ✅ `channels.discord.bots`（見下面「多個 bot」） |
| 伺服器頻道（guild）裡的訊息 | ❌ 一律不讀不回（只做私訊）；`surface: "channel"` 的 bot 設定看得懂但不會連線（PERM-5） |
| 收附件（圖片、檔案） | ❌ |
| 斜線指令選單（Discord 的 `/` 自動完成） | ❌ 指令照打字就能用 |

連線方式：bot 自己連出去到 Discord 的 Gateway（WebSocket），**不開任何埠、不需要公開網址、不用動防火牆**。

## 怎麼設定（給一般使用者）

### 1. 在 Discord Developer Portal 建 bot

1. 打開 <https://discord.com/developers/applications> → 右上 **New Application** → 取名（例如 SYNOX）。
2. 左邊 **Bot** 頁：
   - **Reset Token** → 複製那串 token（只會顯示一次；不要貼到任何聊天裡）。
   - 往下找 **Privileged Gateway Intents**，打開 **Message Content Intent** → **Save Changes**。
     沒開的話 SYNOX 會連不上，狀態顯示「Developer Portal 沒開 Message Content intent（4014）」。
3. 讓 bot 能收你的私訊（擇一）：
   - 左邊 **Installation** 頁 → Installation Contexts 勾 **User Install** → 複製 Install Link 打開、按「加入我的應用程式」；或
   - 把 bot 邀進一個你也在的伺服器（OAuth2 → URL Generator 勾 `bot`），然後從成員清單點 bot 傳私訊。
     （bot 只回私訊，不會在伺服器頻道講話。）

### 2. 把 token 存進保管箱

在 SYNOX 資料夾開終端機：

```
.venv\Scripts\python.exe -m pip install -e .          （第一次：裝 websocket-client）
.venv\Scripts\python.exe -m synox discord token        （貼上 token，畫面不會顯示）
```

### 3. 改 config.json

加上這一段（token 不寫在檔案裡，只寫保管箱的名字）：

```json
"channels": { "discord": { "enabled": true, "bot_token": "vault:discord_bot_token" } }
```

- 也有 Telegram：其他照舊。
- **只用 Discord**：`bot_token`、`owner_id` 可以拿掉；SYNOX 會用保留號段的號碼當擁有者。

### 3b. 多個 bot（選用）

想要好幾個 bot（例如一個什麼都能做的「SYNOX」、一個只開查詢 pack 的小幫手）：每個 bot 在 Developer Portal 各建一個
Application、各自一個 token，config.json 改成 `bots` 寫法（**跟上面的 `bot_token` 寫法擇一**）：

```json
"channels": { "discord": { "bots": {
  "synox":  { "token": "vault:discord_bot_token:synox",  "surface": "dm", "packs": "all", "ai": true },
  "helper": { "token": "vault:discord_bot_token:helper", "surface": "dm", "packs": ["dict", "weather"], "max_effect": "read" }
} } }
```

每個 bot 的 token 各存一次：

```
.venv\Scripts\python.exe -m synox discord token --bot synox
.venv\Scripts\python.exe -m synox discord token --bot helper
```

| 欄位 | 意思 | 沒寫時 |
|---|---|---|
| `token` | 保管箱名字 `vault:…`（或 `env:環境變數`）；**不能**直接把 token 寫進檔案 | `vault:discord_bot_token:<名字>`（名字叫 `default` 時是 `vault:discord_bot_token`） |
| `surface` | `dm`（私訊）／`channel`（伺服器頻道，這一版還不會連線） | `dm` |
| `packs` | `"all"` 或 pack 名字清單 | `"all"` |
| `max_effect` | 這個 bot 最多能做到 `read`／`write`／`danger` | 私訊型不設上限；頻道型 `read`（頻道型設 `danger` 會被拒） |
| `ai` | `true`／`false` 或 `{"enabled": true, "pool_usd_month": 5}` | `true` |
| `enabled` | `false`＝先不開這個 bot | `true` |

- bot 名字只能小寫英文、數字、`-`、`_`；兩個 bot 不能用同一個 token。設定寫錯，啟動和 `doctor` 會直接說哪一格錯。
- **`packs`、`max_effect` 這一版只記下來，還不會擋**（PERM-4 才生效）：現在每個私訊型 bot 能用的指令都一樣。
- 同一個 Discord 帳號不管私訊哪個 bot 都是同一個人（同一份資料、同一個角色）；**配對一次就好**
  （`discord pair` 預設用 `default` 或第一個私訊型 bot，也可以 `--bot <名字>`）。
- 回覆一律由「收到訊息的那個 bot」送出。主動通知（提醒、排程、背景工作做完）走**這個人最近私訊過的 bot**，
  沒私訊過就走設定裡第一個私訊型 bot（記在 `data/discord_last_bot.json`，重開也記得）。
- 狀態頁每個 bot 一條連線，名字 `discord:<名字>`；舊的 `bot_token` 寫法維持叫 `discord`。
- 舊寫法 `{"enabled": true, "bot_token": "vault:discord_bot_token"}` 照舊能用，等於只有一個叫 `default` 的私訊型 bot。

### 4. 配對（告訴 SYNOX 哪個 Discord 帳號是你）

```
.venv\Scripts\python.exe -m synox discord pair
```

畫面會出現六位數字，15 分鐘內在 Discord 私訊 bot 傳那六個數字，看到「✅ 配對成功」就好了。
（配對前先把正在跑的 SYNOX 關掉。）之後照常 `Start.bat`，在 Discord 私訊 bot 打 `/help`。

## 身分與安全

- 內部使用者 id 原本就是 Telegram id。Discord 的人在 `data/identities.json` 換成內部 id：
  **新人一律發 10^15 以上的號碼**，不會撞到 Telegram id；號碼只增不減、永不重用，陌生人不會拿到別人留下的資料。
- 只有在這台電腦上跑 `discord pair`（或在 config 寫 `channels.discord.owner_user_id`）才能把 Discord 帳號接到擁有者身上。
- 陌生人私訊：個人版一律被擋；伺服器版自動登記成訪客（跟 Telegram 一樣）。
- token 只在保管箱（`data/secrets.json.enc`），不進 log、不進 git。

## 已知限制

- 只做私訊；Gateway 收訊和指令處理在同一條執行緒，指令很慢時心跳會晚（AI 那一輪本來就丟背景，影響小）。
- 按鈕必須 3 秒內回應：指令沒回應按鈕時 SYNOX 會自動確認；超過 3 秒的指令按鈕會顯示「交互失敗」但動作照做。
- 文字一律純文字（Telegram 的粗體等 HTML 格式在 Discord 會被拿掉）。
- Telegram 一台電腦一支 bot；Discord 可以多個私訊型 bot（`bots`），頻道型還不行。不支援分片（bot 加進 2500 個以上伺服器才需要）。
- 多個 bot 時，每個 bot 一條 Gateway 執行緒；bot 很多（十幾個以上）時注意 Discord 對同一個 IP 的連線頻率限制。
- 測試全部用程式內的假 Gateway、假 HTTP；**還沒跟真的 Discord 連過**，第一次真連請擁有者在可以上網的地方試。

## 程式在哪

| 檔案 | 做什麼 |
|---|---|
| `src/synox/identity.py` | (通道, 外部 id) → 內部 id |
| `src/synox/discord/events.py` | Gateway 事件 → Inbound（純函式） |
| `src/synox/discord/rest.py` | `DiscordChannel`：回覆（REST v10，requests） |
| `src/synox/discord/gateway.py` | Gateway 迴圈：hello／心跳／identify／resume／退避 |
| `src/synox/discord/bots.py` | `channels.discord` → 每個 bot 的設定（BotSpec，解析與檢查；舊寫法＝bots.default） |
| `src/synox/discord/__init__.py` | `install`（每個 bot 一個 DiscordChannel＋Gateway、MultiHome 主動通知分流與挑 bot）、配對 |
| `vendor/isdtelekit/host/app.py` | **改了 vendor**：`telegram_api(home)`，讓 home 可以是多通道（建議回灌上游） |
| `tests/test_discord.py` | 28 個測試（單一 bot） |
| `tests/test_discord_multibot.py` | 26 個測試（多 bot：設定解析、兩個 bot 同時收私訊、通知挑 bot、CLI、doctor） |

## 未做項目與原因

| 項目 | 為什麼還沒做 |
|---|---|
| Web UI 的 Discord 設定卡（貼 token、按鈕配對） | 低優先；目前用終端機兩行指令就能設定。要做時照 wizard 的 telegram_probe 頁面加一頁。 |
| 精靈（Setup.bat）裡選 Discord | 同上，先等真機驗證過再放進給一般人的流程。 |
| LINE | Messaging API 只能用 **webhook** 收訊：要一個公開 HTTPS 網址打進這台電腦（開埠或通道服務），違反「不開埠、不碰防火牆」。 |
| Microsoft Teams | Bot Framework 一樣要公開 HTTPS 端點，還要 Azure Bot 註冊與租戶管理員核准，對個人使用太重。 |
| Discord 斜線指令、附件 | 最小版先不做。 |
| 伺服器頻道（`surface: "channel"`）、bot 的 pack 範圍與上限真的生效 | 照權限規格分階段：PERM-4 bot 範圍、PERM-5 頻道收訊、PERM-6 頻道 AI。 |
