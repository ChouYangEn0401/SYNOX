# Discord 交接：從零到上線

**給誰**：要在另一台可以上網的電腦上，第一次把 SYNOX 接上真的 Discord 的人。照順序做，不用會寫程式。
**現況**：Discord 通道的程式都寫好了，測試全部用程式內的假 Gateway、假 HTTP；**還沒跟真的 Discord 連過**。這次就是第一次。
**依據**：`docs/discord.md`（設定說明）與 `src/synox/discord/`（程式）。兩邊不一樣時以程式為準；這份文件寫的是程式實際的行為。
Developer Portal 的選單名稱常改版，標「以官方文件為準」的地方照意思找最接近的選項。

SYNOX 連 Discord 的方式：bot 自己**往外**連 Discord 的 Gateway（WebSocket）。**不開任何埠、不需要公開網址、不用動防火牆**。

先做完 [real-service-testing.md](real-service-testing.md) 第 1 節（下載 SYNOX、裝套件、`config.json`）。

---

## 1. 在 Developer Portal 建 App 和 bot

1. 開 <https://discord.com/developers/applications> → 右上 **New Application** → 取名（例如 `SYNOX`）→ 建立。
2. 左邊 **Bot** 頁：
   - **Reset Token** → 複製 token（只顯示一次）。**不要貼到任何聊天**，等一下第 3 步直接貼進 SYNOX。
   - 往下 **Privileged Gateway Intents** → 打開 **Message Content Intent** → **Save Changes**。
     沒開的話 SYNOX 連上就被踢掉，狀態顯示「Developer Portal 沒開 Message Content intent（4014）」。
   - **不用**開 Server Members Intent、Presence Intent。
3. SYNOX 連線時要的 intents（程式寫死，不用在網頁上設）：
   - 私訊型 bot：`DIRECT_MESSAGES`＋`MESSAGE_CONTENT`
   - 頻道型 bot：`GUILDS`＋`GUILD_MESSAGES`＋`MESSAGE_CONTENT`

要好幾個 bot（例如一個私訊型、一個頻道型）：**每個 bot 各建一個 Application**，各自一個 token。兩個 bot 不能共用 token。

---

## 2. 讓 bot 找得到你

### 2-1 私訊型 bot（你私訊它）

擇一（畫面以官方文件為準）：

- **User Install**：左邊 **Installation** 頁 → Installation Contexts 勾 **User Install** → 複製 Install Link 打開 →「加入我的應用程式」。
- **邀進一個你也在的伺服器**：**OAuth2 → URL Generator** → Scopes 勾 `bot`（私訊型不用勾任何 Bot Permissions）→
  複製網址打開 → 選伺服器 → 授權。然後在那個伺服器的成員清單點 bot → 傳私訊。
  （私訊型 bot 不會在伺服器頻道裡講話。）

### 2-2 頻道型 bot（在伺服器頻道裡被 @ 才回）

1. **OAuth2 → URL Generator** → Scopes 勾 `bot`；Bot Permissions 勾 **View Channels**、**Send Messages**、**Read Message History**
   → 複製最下面的網址打開 → 選伺服器 → 授權。（只有伺服器管理員能邀）
2. 那個頻道如果有權限覆寫（私人頻道），要讓 bot 的身分組在那個頻道也有上面三個權限。

### 2-3 拿 id（頻道型才需要；私訊型跳過）

1. Discord 左下 ⚙️ 使用者設定 → **進階（Advanced）** → 打開 **開發者模式（Developer Mode）**。
2. 都是一串數字：
   - **伺服器 id**：左邊伺服器圖示按右鍵 →「複製伺服器 ID」
   - **頻道 id**：頻道名稱按右鍵 →「複製頻道 ID」
   - **身分組 id**（要用 `role_map` 才需要）：伺服器設定 → 身分組 → 右鍵（或 ⋯）→「複製身分組 ID」

id 不是秘密，可以貼在 `config.json`。

---

## 3. 把 token 存進保管箱

在 SYNOX 資料夾開命令提示字元：

```
.venv\Scripts\python.exe -m synox discord token
```

貼上 token、按 Enter（**畫面不會顯示**，正常）。看到「✅ 存進保管箱了」。

- 多個 bot：每個 bot 各存一次，`--bot <名字>`（名字只能小寫英文、數字、`-`、`_`）：
  ```
  .venv\Scripts\python.exe -m synox discord token --bot synox
  .venv\Scripts\python.exe -m synox discord token --bot lookup
  ```
- 存在哪：`data\secrets.json.enc`（加密），名字 `discord_bot_token`（`--bot x` 時是 `discord_bot_token:x`）。
- 如果 `config.json` 用的是多個 bot 的寫法（`bots`），一定要加 `--bot`，不然它會說「加 --bot <名字> 指定存哪一個」。

---

## 4. 改 `config.json`

token **不寫在檔案裡**，只寫保管箱的名字（`vault:…`）。

### 4-1 最簡單：一個私訊型 bot

```json
{
  "mode": "personal",
  "owner_id": 1,
  "llm": { "kind": "none" },
  "vault": { "mode": "dpapi" },
  "web": { "enabled": false },
  "channels": { "discord": { "enabled": true, "bot_token": "vault:discord_bot_token" } }
}
```

- 也有 Telegram：`owner_id` 填你的 Telegram id、加上 `bot_token`（精靈會寫），其他照舊。
- **只用 Discord**：`owner_id`、`bot_token` 都可以拿掉，SYNOX 會用保留號碼 1000000000000000 當擁有者。
- 要 AI：`llm` 照 SYNOX 的 README 設（沒有 AI 也能測指令）。

### 4-2 多個 bot（`bots` 寫法，跟上面 `bot_token` 擇一）

```json
"channels": { "discord": { "bots": {
  "synox":  { "token": "vault:discord_bot_token:synox", "surface": "dm", "packs": "all", "ai": true },
  "helper": { "token": "vault:discord_bot_token:helper", "surface": "dm", "packs": ["todoist"], "max_effect": "read" }
} } }
```

| 欄位 | 意思 | 沒寫時 |
|---|---|---|
| `token` | `vault:<名字>` 或 `env:<環境變數>`；不能直接寫 token | `vault:discord_bot_token:<bot 名字>` |
| `surface` | `dm`（私訊）／`channel`（伺服器頻道） | `dm` |
| `packs` | `"all"` 或 pack 名字清單；不在清單的 pack 對這個 bot「不存在」 | `"all"` |
| `max_effect` | `read`／`write`／`danger`：這個 bot 最多能做到哪 | 私訊型不限；頻道型 `read`（頻道型不能 `danger`） |
| `ai` | `true`／`false`／`{"enabled": true, "pool_usd_month": 5}` | 私訊型 `true`；頻道型關 |
| `enabled` | `false`＝先不開 | `true` |

同一個 Discord 帳號私訊哪個 bot 都是同一個人；**配對一次就好**。

### 4-3 頻道型 bot

在 `bots` 裡加一個（數字換成第 2-3 步複製的 id）：

```json
"lookup": {
  "token": "vault:discord_bot_token:lookup",
  "surface": "channel",
  "guilds": { "123456789012345678": {
      "channels": ["234567890123456789"],
      "role_map": { "345678901234567890": "member" } } },
  "trigger": "mention",
  "packs": "all",
  "max_effect": "read",
  "rate_per_minute": 5
}
```

| 欄位（頻道型才有） | 意思 | 沒寫時 |
|---|---|---|
| `guilds` | 哪些伺服器的哪些頻道要收；**沒列的頻道一律不讀不回** | 沒寫＝收不到任何訊息（啟動與 doctor 會說） |
| `role_map` | Discord 身分組 → SYNOX 角色，只能 `guest`／`member`；只影響這一次請求，不寫回 | 不對應 |
| `trigger` | `"mention"`＝被 @ 才回；`"/"`＝訊息以 / 開頭才回 | `"mention"` |
| `rate_per_minute` | 同一個人在同一個頻道每分鐘幾則；超過的**靜默略過** | `5` |
| `room_rate_per_minute` | 同一個頻道所有人加起來每分鐘幾則 | `20` |

頻道裡的規則（程式擋的，改設定也打不開）：
- 只有 pack.json 寫了 `"surfaces": ["dm", "channel"]`、而且 `data` 不是 `user` 的 pack 會出現。
  **⚠️ 這個 repo 裡目前沒有任何 pack 宣告 `channel`**（記帳、筆記、提醒、四個 connector 都是 `dm`／`data: user`），
  所以頻道型 bot 現在只有內建的 `/help`、`/start`、`/exit`（和開了的話「頻道 AI」聊天，沒有工具）。測試時這是正常的。
- 危險動作（DANGER）在頻道裡永遠不行；寫入要 `max_effect: "write"`＋pack 的 `data` 是 `shared`＋發話者至少是成員。
- 回覆引用並提及發話者那則訊息；其他 @、@everyone 不解析。按鈕只有發話者能按。

### 4-4 頻道 AI（選用，要先有 `llm`）

頻道型 bot 加 `ai`，**一定要有 `pool_usd_month`**（整個 bot 每月共用的額度，美元，不算進任何人的個人額度）：

```json
"ai": { "enabled": true, "pool_usd_month": 5, "persona": "你是讀書會的小幫手。", "history_turns": 6, "rate_per_minute": 2 }
```

| 欄位 | 意思 | 沒寫時 |
|---|---|---|
| `pool_usd_month` | 這個 bot 每月的 AI 額度；用完整個 bot 的頻道 AI 停到下個月（指令照常） | **沒寫＝設定錯誤，頻道 AI 不開**（doctor、/bot_status 用 ❌ 說明） |
| `persona` | 附加在系統提示後面的角色設定 | bot 的 `persona` |
| `history_turns` | 這個頻道共用的記憶留幾輪（1–50），重開 SYNOX 就清空 | `6` |
| `rate_per_minute` | 每人每分鐘幾次（1–60） | `2` |

用量記在 `data\bot_pools\<bot 名字>\llm_usage.json`；私訊 SYNOX 打 `/bot_status` 看用了多少。

改完 `config.json` 先檢查：

```
.venv\Scripts\python.exe -m synox doctor --offline
```

`Discord：開（N 個 bot…）` 底下每個 bot 一行，要看到「✅ token 在保管箱」；寫錯的欄位會直接說是哪一格。

---

## 5. 配對（先配對，再上線）

告訴 SYNOX「哪個 Discord 帳號是擁有者」。**沒配對前，私訊型 bot 誰的私訊都不收**（只回一句「還沒配對」），免得陌生人搶先被當成擁有者。

1. **先關掉正在跑的 SYNOX**（`Stop.bat`），不然兩邊會搶訊息。
2. 命令提示字元：
   ```
   .venv\Scripts\python.exe -m synox discord pair
   ```
   多個 bot 時可以加 `--bot synox` 指定用哪個私訊型 bot（頻道型不能拿來配對）。
3. 畫面出現**六位數字**。15 分鐘內，用**你自己的 Discord 帳號私訊那個 bot**，只傳這六個數字。
4. bot 回「✅ 配對成功！」、命令列印「✅ 已把 Discord 帳號 … 接到擁有者」就好了。
   15 分鐘沒收到 → 「⌛ 沒有收到配對碼，沒有改任何東西」，重跑一次（每次的數字都不一樣）。

配對寫在 `data\identities.json`。另一種做法：在 `channels.discord` 寫 `"owner_user_id": "<你的 Discord 使用者 id>"`（開發者模式下右鍵自己的名字「複製使用者 ID」）。

---

## 6. 上線

雙擊 `Start.bat`（或 `.venv\Scripts\python.exe -m synox run`）。小視窗出現「✅ SYNOX 開始收訊息了」。

- 有 bot 沒開成會印「⚠️ Discord bot X 沒有開：原因」（例如保管箱沒有 token）。其他 bot、其他通道照跑。
- 私訊 bot 打 `/help`，應該看到指令清單。
- 停：關掉小視窗，或雙擊 `Stop.bat`。

---

## 7. 看狀態：`/bot_status` 與 doctor

**`/bot_status`**（私訊 SYNOX；個人版只有擁有者能用）——每個 bot：

- 狀態：「✅ 收訊中」／「⚠️ 原因」／「⏸ 關著（enabled=false）」
- 頻道型：收訊（幾個伺服器、頻道、觸發方式、role_map 幾筆、節流），頻道 AI 用了多少
- **會出現**：這個 bot 上看得到的 pack
- **設定了但不會出現**：寫在 `packs` 裡卻不會出現的 pack 和原因（沒裝、頻道型的 surfaces 沒有 channel、`data=user`、指令全超過 `max_effect`…）
- **沒開給這個 bot**：有裝但不在這個 bot 的 `packs` 裡

**`python -m synox doctor`**（不用開 SYNOX，不連 Discord）——`Discord：` 底下：
- `❌ 身分：…`：擁有者還沒配對，或 `identities.json` 有問題
- 每個 bot 一行：私訊型／頻道型、pack 範圍、上限、AI、`✅ token 在保管箱`／`❌ 保管箱裡沒有 …（python -m synox discord token --bot X）`
- 下面接這個 bot「會出現／設定了但不會出現」（python pack 的指令效果要 `/bot_status` 才知道）

上線前也可以先跑 `scripts\smoke_real.py --only discord`：只查 token、bot 身分、Gateway 資訊、Message Content intent、配對，不上線。

---

## 8. 常見錯誤

| 看到 | 意思 | 怎麼辦 |
|---|---|---|
| Discord 拒絕連線：Developer Portal 沒開 Message Content intent（4014） | intent 沒開 | Bot 頁 → Privileged Gateway Intents → Message Content Intent → Save，重開 SYNOX |
| Discord 拒絕連線：bot token 不對（4004） | token 錯或按過 Reset Token | `python -m synox discord token`（`--bot X`）重存 |
| Discord 拒絕連線：intents 數值不對（4013）／分片設定錯（4010）／需要分片（4011）／Gateway 版本錯（4012） | 程式這邊的問題（或 bot 進了 2500 個以上伺服器） | 回報擁有者 |
| 缺少套件 websocket-client | 沒裝好 | `.venv\Scripts\python.exe -m pip install -e .` |
| 🔒 這個 SYNOX 的擁有者還沒把 Discord 帳號配對好，暫時不收任何私訊 | 只用 Discord、還沒配對 | 第 5 步 |
| identities.json 是舊版的：Discord 帳號 X 對到擁有者的號碼… | 舊版檔案，分不出是不是你 | 是你本人就重跑 `discord pair` |
| ⌛ 沒有收到配對碼，沒有改任何東西 | 15 分鐘內沒收到六位數字 | 重跑；確認是**私訊**那個 bot、只傳六個數字、SYNOX 已關 |
| ❌ bot X 是頻道型的；配對要用私訊型的 bot | `--bot` 指到頻道型 | 換私訊型的名字 |
| ❌ config.json 用的是多個 bot 的寫法…：加 --bot <名字> | `discord token` 沒指定 | 加 `--bot 名字` |
| 保管箱裡找不到 discord_bot_token… | 還沒存 token | 第 3 步 |
| 跟另一個 bot 的 token 一樣（一個 bot 只能有一條連線） | 兩個 bot 填同一個 token | 每個 bot 各建一個 Application |
| 頻道型 bot 沒有列任何伺服器／頻道（guilds），不會收到訊息 | 沒寫 `guilds` | 第 4-3 步 |
| config.json 的 channels.discord.bots.X：…（各種格式錯誤） | 某一格寫錯 | 照訊息改那一格（例如 id 要是一串數字） |
| config.json 的 channels.discord 同時寫了 bot_token 和 bots | 兩種寫法混用 | 擇一 |
| 頻道裡回「頻道裡只收指令（例如 @我 /help）；想聊天請私訊。」 | 被 @ 了但不是指令、頻道 AI 沒開 | 正常；要聊天就開 4-4 |
| 「🔒 這個動作要到私訊做」 | 頻道裡要確認卡／危險動作 | 到私訊做 |
| 「這個 bot 這個月的頻道 AI 額度用完了」 | pool 用完 | 調高 `pool_usd_month` 或等下個月 |
| 按鈕顯示「交互失敗」但動作有做 | 指令超過 3 秒才回 | 已知限制，不影響結果 |

### 頻道沒反應：照順序檢查

1. `/bot_status` 那個 bot 是「✅ 收訊中」嗎？不是 → 看它寫的原因。
2. 那個**頻道 id** 有在 `guilds.<伺服器 id>.channels` 裡嗎？（沒列的頻道一律不讀）
3. `trigger` 是 `mention` 時，有沒有真的 **@ 到那個 bot**（不是 @ 身分組、不是打名字）？
4. Message Content Intent 有開嗎？（沒開會 4014 連不上）
5. bot 在那個頻道有 **View Channels、Send Messages、Read Message History** 嗎？私人頻道要另外給。
6. 是不是**講太快**？同一人同頻道每分鐘超過 `rate_per_minute`（預設 5）、或整個頻道超過 20，會**靜默略過**（log 有一行 throttled）。
7. 打的指令在頻道裡存在嗎？`/bot_status` 的「會出現」是空的就只有 `/help`、`/start`、`/exit`（見 4-3 的 ⚠️）。
8. 這些一律不回：其他 bot、webhook、自己、**編輯過的訊息**、只有附件沒有字的訊息、SYNOX 剛連上（READY 之前）那一下的訊息。
9. 有人在頻道裡開了一段問答（表單）時，別人說的話不會被當成他的回答，也不會被處理。
10. 都對還是沒反應：看 `Start.bat` 小視窗的紅字，整段（不要含 token）回報。

---

## 9. 測試清單（對應部署測試板的 Discord 項目）

照順序做，每一項在部署測試板勾 ✅／❌／⏭，❌ 的開一筆問題紀錄（看到的訊息照貼）。欄位名稱以部署測試板實際的為準。

| # | 項目 | 怎麼做 | 預期 |
|---|---|---|---|
| D1 | token 與 intent | `scripts\smoke_real.py --only discord` | 身分、Gateway、Message Content intent 都 ✅ |
| D2 | doctor | `python -m synox doctor --offline` | 每個 bot「✅ token 在保管箱」 |
| D3 | 配對 | `python -m synox discord pair` → 私訊六位數字 | 「✅ 配對成功」 |
| D4 | 上線 | `Start.bat` | 「✅ SYNOX 開始收訊息了」，沒有「⚠️ Discord … 沒有開」 |
| D5 | 私訊指令 | 私訊 bot：`/help`、`/note_list` 或任一 connector 的 `_status` | 有回覆 |
| D6 | 按鈕 | 私訊一個會出按鈕的指令（例如只打群組名叫出選單，或會送確認卡的動作） | 按了有反應 |
| D7 | 長訊息 | 讓它回超過 2000 字的東西（例如很長的清單） | 自動切成幾則 |
| D8 | 主動通知 | `/remind_add <兩分鐘後的時間> 測試` | 時間到 Discord 收到提醒（SYNOX 要開著） |
| D9 | 陌生人 | 用**另一個** Discord 帳號私訊 bot | 個人版：被擋；伺服器版：變成訪客 |
| D10 | `/bot_status` | 私訊 `/bot_status` | 每個 bot 狀態、會出現的 pack |
| D11 | 多 bot（有設定才做） | 私訊第二個 bot `/help` | 只看得到它 `packs` 裡的；超過 `max_effect` 的回「🔒 這個 bot 只開放…」 |
| D12 | 頻道型（有設定才做） | 在列出的頻道 `@bot /help` | 引用你的訊息回覆 |
| D13 | 頻道 allowlist | 在**沒列出**的頻道 @bot | 不回 |
| D14 | 頻道按鈕 | 別人按你叫出來的按鈕 | 他看到「只有發這個指令的人能按這些按鈕」 |
| D15 | 頻道節流 | 一分鐘內 @bot 超過 5 次 | 超過的不回 |
| D16 | 頻道 AI（有開才做） | `@bot 你好` | AI 回覆；`/bot_status` 看得到用量 |
| D17 | 重開 | `Stop.bat` → `Start.bat` | 私訊照常；配對還在 |
| D18 | 清理 | 見 [real-service-testing.md](real-service-testing.md) 第 7 節 | Reset Token 後舊 token 失效 |

---

## 10. 已知限制

- 不收附件（圖片、檔案）；沒有 Discord 原生的斜線指令選單（照打字就能用；頻道裡用「@bot /指令」）。
- 文字一律純文字（Telegram 的粗體等格式會拿掉）。
- Gateway 收訊和指令處理在同一條執行緒，指令很慢時心跳會晚（AI 那一輪丟背景，影響小）。
- 按鈕要 3 秒內回應：超過 3 秒的指令按鈕顯示「交互失敗」但動作照做。
- 頻道型：「只有發話者能按」和節流都記在記憶體，SYNOX 重開後舊按鈕按不動、節流歸零；READY 前收到的 @ 不回。
- 頻道 AI 的共用記憶重開就清空（額度記在檔案）。送出前會遮掉看起來像 token 的字，但沒存在 SYNOX 裡的密碼認不出來。
- 確認卡（AI 想做危險動作）綁在 AI 助理：`ai: false` 的 bot、頻道型 bot、訪客按 ✅ 只會回沒有權限，要到開著 AI 的私訊型 bot 或 Telegram 做。
- 頻道型 bot 不送主動通知、不能拿來配對。主動通知走「這個人最近私訊過的 bot」，沒有就第一個私訊型。
- 不支援分片（bot 進了 2500 個以上伺服器才需要）；bot 很多時注意 Discord 對同一個 IP 的連線頻率限制。
- 保管箱裡的 Discord token 目前**沒有刪除指令**（`discord token` 只能存）；不用時在 Portal Reset Token 讓它失效。
- 這個 repo 沒有宣告 `channel` 的 pack，頻道型 bot 暫時只有內建指令與頻道 AI（見 4-3）。
- 精靈（Setup.bat）和網頁設定頁還沒有 Discord 的設定畫面，先用上面的終端機指令。
