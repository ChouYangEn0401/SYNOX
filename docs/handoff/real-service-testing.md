# 真機測試教學：Notion、Google 日曆、Apple 提醒事項、Todoist、Discord

**給誰**：要在「另一台可以上網的電腦」上，用真的帳號試 SYNOX 能不能接上這五個服務的人。不用會寫程式，照順序做就好。
**為什麼要做**：開發用的那台電腦只用「假的網路」測過（程式裡的假傳輸），還沒真的連過這些服務。
**要多久**：準備 20 分鐘；每個服務 5～15 分鐘（Google 最久）。
**做完會得到**：一張「哪些通、哪些不通、為什麼」的表，和一段可以直接貼進「部署測試板」的文字。

> 標「以官方文件為準」的地方，是各服務自己的網站畫面或網址，可能已經改版；看不到一模一樣的字時，照意思找最接近的選項。
> Discord 從零到上線的完整步驟另外寫在 [discord-handoff.md](discord-handoff.md)。

---

## 0. 先看安全守則（一定要讀）

| 不要 | 為什麼 |
|---|---|
| 把 token、密碼、App 專用密碼、refresh token 貼到**任何聊天**（包括跟 Claude、Telegram、Discord、LINE） | 聊天紀錄會留著、會被同步到別的裝置；貼了就當它外洩，馬上去撤銷（第 7 節） |
| 把 `config.json`、`data` 資料夾**提交進 git** 或上傳到雲端硬碟 | `data` 裡是加密的憑證和解密用的金鑰檔；`config.json` 可能有你的 id |
| 用你**主要的**個人帳號測 | 建議每個服務開一個**專用的測試帳號**（或測試工作區），測完整個刪掉最乾淨 |
| 截圖時把 token 拍進去 | 截圖也算外洩。回報時只貼腳本印出來的表格（腳本會自己把憑證換成 `***`） |

SYNOX 存憑證的地方是**保管箱**：`data\` 底下的 `*.json.enc` 檔，是加密過的，只有**這台電腦、這個 Windows 帳號**解得開。

---

## 1. 準備另一台電腦（約 20 分鐘）

需要：Windows 10／11、可以上網、Git（沒有的話到 <https://git-scm.com/> 下載安裝，一路按「下一步」）。

### 1-1 下載 SYNOX

開「命令提示字元」（開始選單搜尋 `cmd`），一行一行打：

```
cd %USERPROFILE%\Documents
git clone https://github.com/ChouYangEn0401/SYNOX.git
cd SYNOX
git checkout dev
dir scripts\smoke_real.py
```

- 最後一行要看到 `smoke_real.py`。看不到 → 這份教學的程式還沒合併進 `dev`，請找擁有者。
- repo 是私人的話，`git clone` 會要你登入 GitHub（照畫面做）。

### 1-2 裝 Python 套件（二選一）

**A. 雙擊 `Setup.bat`（建議）**：它會找或安裝 Python、建立 `.venv`、裝好套件，最後打開安裝精靈。
- 你**有** Telegram bot 要一起測 → 照精靈四頁做完（見 SYNOX 的 [README](../../README.md)）。
- 你**只想測這五個服務** → 看到精靈視窗時直接關掉，接著做 1-3 自己寫 `config.json`。

**B. 自己打指令**（Setup.bat 失敗時）：要先有 Python 3.11 以上（<https://www.python.org/downloads/>）。

```
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

### 1-3 `config.json`（沒跑完精靈時才要做）

在 SYNOX 資料夾新增一個檔案叫 `config.json`（用記事本，存檔時「編碼」選 UTF-8），內容：

```json
{
  "mode": "personal",
  "owner_id": 1,
  "llm": { "kind": "none" },
  "vault": { "mode": "dpapi" },
  "web": { "enabled": false }
}
```

- `owner_id`：有 Telegram 的話填**你的 Telegram id**（數字）；只測這五個服務填 `1` 就好。
- 要測 Discord 時還要加 `channels` 那一段，見 [discord-handoff.md](discord-handoff.md)。

### 1-4 檢查

```
.venv\Scripts\python.exe -m synox doctor --offline
```

看到「設定：✅ config.json」就可以了（`bot_token ❌ 不是有效的 token` 在只測服務時是正常的）。

### 1-5 兩個會一直用到的視窗

| 視窗 | 怎麼開 | 拿來做什麼 |
|---|---|---|
| **SYNOX 終端機** | 雙擊 `Console.bat` | 在電腦上直接打 `/notion_token` 這類設定指令（**不經過 Telegram**，最安全）。打 `/help` 看全部指令 |
| **命令提示字元** | 在 SYNOX 資料夾的網址列打 `cmd` 按 Enter | 跑 `python -m synox …` 和 `scripts\smoke_real.py` |

終端機裡打的 token 會留在那個視窗的畫面上：設定完把視窗關掉就好，不會存到任何檔案。

---

## 2. 各服務：取得憑證、交給 SYNOX

每個服務都是兩步：**在服務的網站拿到鑰匙** → **交給 SYNOX 存進保管箱**。
也可以不先存：直接跑 `smoke_real.py`，它發現保管箱沒有時會用「打字不顯示」的方式問你（只用這一次，不存）。
但只有存進保管箱，SYNOX 平常的指令才用得到。

### 2-1 Notion（約 3 分鐘）

用的是「internal integration」：一把只看得到你分享給它的頁面的鑰匙。

1. 電腦開 <https://www.notion.so/profile/integrations> →「新增 integration」（New integration）→ 名字 `SYNOX`、選工作區、
   類型 **Internal** → 儲存。（畫面以官方文件為準）
2. 在那個 integration 的頁面：
   - 「功能」（Capabilities）勾**讀取內容**；要測寫入（`--write`）再勾**插入內容**、**更新內容**。
   - 複製 **Internal Integration Secret**（`ntn_` 開頭的一長串）。
3. **把頁面分享給 integration**（最常忘）：在 Notion 打開一頁 → 右上角 **⋯** → **連接**（Connections）→ 選 `SYNOX`。
   分享一頁，它底下的子頁也一起分享。沒分享的頁面 SYNOX 看不到。
4. 交給 SYNOX：開 `Console.bat`，打 `/notion_token`，它說「貼上來」之後貼上、按 Enter。看到「✅ 接上 Notion 了」。
5. 試：`/notion_status`、`/notion 關鍵字`。

> ⚠️ **不要用** `python -m synox connect notion`：那個指令存的位置 `/notion` 讀不到（已知問題，已回報擁有者）。
> 用了也沒關係，`smoke_real.py` 會在「token 存的位置」那一行提醒你，改用上面第 4 步重存一次。

### 2-2 Todoist（約 1 分鐘）

1. 開 <https://app.todoist.com> 登入 → 頭像 → **設定 → 整合（Integrations）→ 開發者（Developer）** →「API token」按複製
   （一串 40 個英數字）。（選單位置以官方文件為準）
2. `Console.bat` 打：`/todoist_token 貼上那串字` → 看到「✅ 接上 Todoist 了（看得到 N 個專案）」。
3. 試：`/todoist_list`。

這個 token 能讀寫**整個 Todoist 帳號**（Todoist 沒有更小的權限），所以更建議用測試帳號。

### 2-3 Google 日曆（約 10～15 分鐘，只要做一次）

Google 規定每個程式要有自己的「OAuth 用戶端」，所以要在你自己的 Google 帳號建一個（免費）。
以下 Google Cloud 的選單名稱常改版，**以官方文件為準**。

**A. 在 Google Cloud 建用戶端**

1. 開 <https://console.cloud.google.com/> 登入 → 左上「選取專案」→「新增專案」（名字例如 `synox-test`）→ 建立。
2. 上面搜尋 **Google Calendar API** → 點進去 →「啟用」。
3. 左邊「API 和服務」→「OAuth 同意畫面」（新版叫「Google Auth Platform」）：
   - 使用者類型「**外部**」→ 填應用程式名稱、你的 email → 儲存。
   - 「目標對象／測試使用者」：加入**要測的那個 Gmail**。
   - 停在「測試」狀態時，授權 **7 天就失效**；只測幾天的話不用管，長期用才按「發布應用程式」。
4. 「憑證」→「建立憑證」→「OAuth 用戶端 ID」→ 類型「**電腦版應用程式**（Desktop app）」→ 建立。
5. 記下**用戶端 ID**（`….apps.googleusercontent.com` 結尾）和**用戶端密鑰**（`GOCSPX-` 開頭）。

**B. 在 SYNOX 連上**（在 `Console.bat` 裡做）

1. 打：`/gcal_setup <用戶端 ID> <用戶端密鑰>`（只想讓它看不能改：最後加 `readonly`）。
2. SYNOX 回一個 Google 連結 → 複製到瀏覽器打開 → 選帳號 →（看到「Google 尚未驗證這個應用程式」→「進階」→「前往」）→ 允許。
3. 最後瀏覽器顯示「**無法連上這個網站**」或「127.0.0.1 拒絕連線」——**這是正常的**（SYNOX 故意不開網路埠）。
4. 把**網址列整串**（`http://127.0.0.1:47231/?state=…&code=…`）複製，打：`/gcal_code <貼上整串>`。
5. 看到「✅ 連上 Google 日曆了」。試：`/gcal_status`、`/gcal_today`。

連結 15 分鐘內有效，超過就再 `/gcal_setup` 一次（第二次可以只打 `/gcal_setup`）。

### 2-4 Apple 提醒事項（CalDAV）（約 5 分鐘）

#### 先講結論

**iCloud 裡「升級過」的提醒事項，Apple 不開放 CalDAV**——第三方程式（包括 SYNOX）讀不到也寫不進去。
iOS 13（2019）之後幾乎所有人的提醒事項都升級過了（子任務、標籤、群組這些功能都要升級才有）。
這是 Apple 的限制，不是設定錯，也不是 SYNOX 的 bug。

| 你的情況 | 能不能用 |
|---|---|
| iCloud 帳號、提醒事項升級過（幾乎所有人） | ❌ 登入會成功，但找不到任何清單 |
| iCloud 帳號、提醒事項從沒升級（極少數舊裝置） | ✅ 可以，但 Apple 隨時可能關掉 |
| **iPhone 提醒事項 App 加一個別家的 CalDAV 帳號**，在那個帳號建清單 | ✅ **建議的做法**（下面「替代做法」） |

#### 怎麼判斷自己是哪一種

1. **最準**：照下面做完設定後跑 `smoke_real.py --only apple`（第 3 節）：
   - 「登入 ✅」但「列清單 ❌ iCloud 帳號裡找不到能用 CalDAV 讀的提醒事項清單」→ **升級過**，改用替代做法。
   - 「登入 ✅」「列清單 ✅」→ 能用。
   - 「登入 ❌ 帳號或密碼不對」→ 密碼的問題，不是升級的問題（看第 5 節）。
2. 在 iPhone 上看（畫面以官方文件為準）：打開「提醒事項」App，清單裡用得到**標籤**、**子任務**或清單**群組**，就是升級過的；
   App 最上面還跳「升級」的提示，就是還沒升級（**不要按升級**，按了就回不去）。

#### iCloud 帳號（先試一下也好）

1. 產生 **App 專用密碼**：<https://appleid.apple.com> → 登入 →「登入與安全性」→「App 專用密碼」→ 產生一組（名字寫 SYNOX）。
   （位置以官方文件為準；Apple ID 要開雙重認證才有這個選項）
2. 雙擊 `Connect-Apple.bat`（或 `.venv\Scripts\python.exe -m synox connect apple-reminders`）：
   - 伺服器網址：直接 Enter（預設 `https://caldav.icloud.com`）
   - 帳號：Apple ID 的 email
   - App 專用密碼：貼上（**畫面不會顯示**，正常）
3. `Console.bat` 打 `/applerem_status` 看結果。

#### 替代做法：接一個別家的 CalDAV 帳號

1. 準備一個支援 CalDAV 的帳號：Fastmail、mailbox.org（付費），或自己架的 Nextcloud、Radicale、Synology Calendar。
   每家的 CalDAV 伺服器網址不一樣，**以那一家的官方文件為準**（要的是 `https://` 開頭的那個網址；
   Nextcloud 常見是 `https://<你的網域>/remote.php/dav`，一樣以官方文件為準）。很多家要另外產生「App 密碼」。
2. iPhone：「設定 → 提醒事項 → 帳號 → 加入帳號 → 其他 → 加入 CalDAV 帳號」，填同一組網址、帳號、密碼（路徑以官方文件為準）。
3. 在 iPhone 提醒事項 App 裡，**在那個帳號底下**建一個清單（例如「SYNOX」）。
4. 電腦上雙擊 `Connect-Apple.bat`，填**那一家**的網址、帳號、密碼；`/applerem_status` 應該列得出那個清單。

SYNOX 只連 `https://`、只連你填的那台主機（iCloud 允許 `*.icloud.com`），不跟隨轉址。

### 2-5 Discord（只驗 token；上線另見交接文件）

照 [discord-handoff.md](discord-handoff.md) 的第 1～4 步：在 Developer Portal 建 bot、打開 Message Content Intent、
`python -m synox discord token` 存 token、在 `config.json` 加 `channels.discord`。做到這裡就可以跑煙霧測試；
配對（`discord pair`）和上線（`Start.bat`）在那份文件後半段。

---

## 3. 跑煙霧測試 `smoke_real.py`

在 SYNOX 資料夾的命令提示字元：

```
.venv\Scripts\python.exe scripts\smoke_real.py
```

- 預設**只讀**：只做「驗證 token、搜尋、列清單、列行程」這類動作，不會在任何服務上改東西，也不會改你電腦上的保管箱。
- 保管箱裡沒有的憑證，它會問你（打字不顯示；直接按 Enter＝跳過那個服務）。
- 只測其中幾個：`--only notion,todoist`（可以用 `notion`、`todoist`、`gcal`、`apple`、`discord`）。
- 不想被問、只測存好的：加 `--no-ask`。
- Notion 搜尋特定關鍵字：`--notion-query 會議`。

### 3-1 預期輸出

```
SYNOX 真機煙霧測試（唯讀）　2026-11-12 14:03
| 服務 | 項目 | 結果 | 原因／下一步 |
|---|---|---|---|
| Notion | token 驗證 | ✅ | integration：SYNOX，工作區：我的工作區 |
| Notion | 搜尋頁面 | ✅ | 看得到 3 頁以上（例：首頁） |
| Notion | 搜尋資料庫 | ✅ | 看得到 0 個資料庫（0 個也沒關係） |
| Todoist | token 驗證（列專案） | ✅ | 看得到 2 個專案 |
| Todoist | 列任務 | ✅ | 5 項還沒做完 |
| Todoist | 今天到期 | ✅ | 1 項 |
| Google 日曆 | 授權（換 access token） | ✅ | 授權有效（可以看、加、刪；日曆：primary） |
| Google 日曆 | 今天的行程 | ✅ | 2 個 |
| Google 日曆 | 這 7 天的行程 | ✅ | 6 個 |
| Apple 提醒事項 | 登入 | ✅ | 登入成功（m***@icloud.com，caldav.icloud.com） |
| Apple 提醒事項 | 列清單（/applerem_status） | ❌ | iCloud 帳號裡找不到能用 CalDAV 讀的提醒事項清單。… → 改接別家 CalDAV 帳號 |
| Discord | bot default：身分 | ✅ | synox-bot（id 1234…；私訊型） |
| Discord | bot default：Gateway 資訊 | ✅ | Gateway 可用（建議分片 1；今天還能開 999/1000 次連線） |
| Discord | bot default：Message Content intent | ✅ | Message Content intent 已開 |
| Discord | 擁有者配對 | ❌ | 擁有者還沒配對 Discord 帳號… → 先關掉正在跑的 SYNOX，再 python -m synox discord pair… |
共 15 項：✅ 13　❌ 2　⏭ 0

──── 下面這段可以整段貼進「部署測試板」────
【真機煙霧測試】2026-11-12 14:03（smoke_real.py，唯讀）
✅ Notion：token 驗證✅、搜尋頁面✅、搜尋資料庫✅
…
問題：
- Apple 提醒事項／列清單（/applerem_status）：…
```

| 符號 | 意思 |
|---|---|
| ✅ | 通了 |
| ❌ | 沒通；「原因」是 SYNOX 自己的中文說明，「→」後面是下一步 |
| ⏭ | 沒測（沒設定、前一步沒過、或你沒輸入 yes） |

全部 ✅ 時結束碼是 0，有 ❌ 是 1。

### 3-2 寫入測試（選用，`--write`）

只讀都通了，想確認「加東西」也行時才做：

```
.venv\Scripts\python.exe scripts\smoke_real.py --write --notion-parent https://www.notion.so/某一頁的網址
```

1. 它先跑完只讀的檢查。
2. 列出要做的寫入，例如：
   ```
   ── 要做的寫入（做完立刻刪掉／完成）──
   1. Notion：在 --notion-parent 那一頁底下開一頁「SYNOX-smoke-test 20261112-140301」，再把它移到 Notion 的垃圾桶
   2. Todoist：在收件匣加一項「SYNOX-smoke-test 20261112-140301」，再把它刪掉
   3. Google 日曆：在主要日曆（primary）明天加一個整天的「SYNOX-smoke-test …」，再把它刪掉
   4. Apple 提醒事項：在清單「SYNOX」加一個「SYNOX-smoke-test …」，再把它打勾完成（CalDAV 沒有刪除，會留一筆「已完成」）
   全部照做請輸入 yes（其他＝都不做）：
   ```
3. 打 `yes` 才做；打別的就全部不做。
4. 每一項都用標題含 **`SYNOX-smoke-test`** 的新東西，做完馬上刪掉（Notion 是移到垃圾桶；Apple 是打勾完成）。
   萬一中途失敗，表格會寫「請手動刪掉「SYNOX-smoke-test …」」——到那個服務搜尋 `SYNOX-smoke-test` 刪掉即可。

注意：
- Notion 要給 `--notion-parent`（一頁你分享給 integration 的頁面網址），沒給就跳過 Notion 的寫入。integration 要勾「插入內容」「更新內容」。
- Google 是 `readonly` 連的話會跳過寫入。
- Discord **不做**寫入測試（不上線、不送訊息）；上線測試照 [discord-handoff.md](discord-handoff.md)。

---

## 4. 測完之後在 SYNOX 裡試試「串起來」

煙霧測試只確認「接得上」。真正想知道的是能不能串出東西，建議在 `Console.bat`（或 Telegram／Discord）試：

| 試什麼 | 打 |
|---|---|
| Notion 讀一頁 | `/notion_read <頁面網址>` |
| Todoist 加一項再完成 | `/todoist SYNOX-smoke-test 明天` → `/todoist_list` → `/todoist_done <編號>` |
| Google 日曆加一個再刪 | `/gcal 明天 14:00 SYNOX-smoke-test` → `/gcal_list` → `/gcal_rm <編號>` |
| Apple 加一個再完成 | `/applerem_add SYNOX-smoke-test due=明天` → `/applerem` → `/applerem_done <編號>` |
| 有設定 AI 的話 | 直接說「把 Todoist 今天要做的事加到 Google 日曆明天早上」，看 AI 會不會依序叫兩個指令 |

---

## 5. 常見錯誤與排除

下面的「看到」是 SYNOX 會回的原句（煙霧測試的「原因」欄也是同一句）。

### Notion

| 看到 | 意思 | 怎麼辦 |
|---|---|---|
| Notion 不認這個 token（打錯了，或在 Notion 被撤銷了） | 401 | 重新複製 Internal Integration Secret，`/notion_token` 再存一次 |
| 這個 integration 沒有這個權限 | 403 | integration 設定頁「功能」勾讀取／插入／更新內容 |
| 找不到。（Notion 那邊要先把頁面或資料庫分享給你的 integration…） | 404 | 頁面右上 ⋯ → 連接 → 選你的 integration |
| API 通了，但一頁都看不到 | （煙霧測試）token 對，但沒分享任何頁面 | 同上 |
| Notion 說太頻繁了，N 秒後再試 | 429 | 等一下（Notion 大約每秒 3 次） |
| Notion 說同時有別的修改，再試一次 | 409 | 再試一次 |
| Notion 不收這個請求：… | 其他 4xx（後面是 Notion 的英文原因） | 回報那一行 |
| Notion 那邊出錯了（5xx） | Notion 自己的問題 | 等一下再試 |
| 連不到 Notion（…） | 網路 | 檢查網路、公司防火牆 |
| 這看起來不是 Notion 的 integration token | 格式不對 | 要 `ntn_` 開頭（舊的是 `secret_`） |
| 還沒設定 Notion | 保管箱沒有 token | `/notion_token` |
| token 存的位置 ❌（煙霧測試） | 用了 `python -m synox connect notion` | 改用 `/notion_token` 存一次 |

### Todoist

| 看到 | 意思 | 怎麼辦 |
|---|---|---|
| Todoist 不收這個 token（打錯了、或被撤銷了） | 401／403 | 重新複製 API token，`/todoist_token <token>` |
| 這看起來不是 Todoist 的 API token | 格式不對 | 應該是 40 個英數字 |
| Todoist 找不到這一項（可能已經完成或刪掉了） | 404 | 先 `/todoist_list` 看編號 |
| Todoist 說太頻繁了 | 429 | 等一下 |
| Todoist 不接受這個要求（4xx）：… | 其他 4xx | 回報那一行 |
| Todoist 那邊出錯了（5xx） | Todoist 自己的問題 | 等一下 |
| Todoist 沒有回應（逾時）／連不上 Todoist（網路斷了？） | 網路 | 檢查網路 |
| Todoist 回了看不懂的東西 | 回應不是 JSON | 回報 |

### Google 日曆

| 看到 | 意思 | 怎麼辦 |
|---|---|---|
| Google 不再接受這個授權（被收回、過期，或 app 還在「測試」狀態時 7 天就失效） | invalid_grant | `/gcal_setup` 重新連；長期用就把 app 發布 |
| Google 說 client_id／client_secret 不對 | invalid_client | 檢查複製完整、類型是「電腦版應用程式」 |
| client_id 看起來不對（應該是 ….apps.googleusercontent.com 結尾） | 格式 | 重新複製用戶端 ID |
| 沒有等待中的登入（或已經超過 15 分鐘） | 太久才貼網址 | 再 `/gcal_setup` 一次 |
| 這個網址不是剛剛那次登入的（state 對不上） | 貼到舊的那次 | 用最新一次給的連結 |
| 看不到授權碼 | 貼的不是整串網址 | 貼網址列整串（有 `code=`） |
| Google 說沒有允許（…） | 你在 Google 頁面按了拒絕 | 重新 `/gcal_setup` |
| Google 沒有給 refresh token | 同一個帳號之前授權過 | <https://myaccount.google.com/permissions> 移除這個 app 再 `/gcal_setup` |
| Google 的授權失效了，請重新 /gcal_setup | 401 | 重新連 |
| Google 說沒有權限（唯讀模式？或這個日曆不是你的） | 403 | 要寫入就不加 `readonly` 重連；也確認 Calendar API 有啟用 |
| Google 那邊找不到（可能已經被刪掉了） | 404／410 | 重新列一次 |
| Google 現在忙不過來 | 429／5xx | 等一下 |
| 連不上 Google（網路有問題？） | 網路 | 檢查網路 |
| 時間差了幾小時 | SYNOX 用這台電腦的時區 | 檢查 Windows 時區 |

### Apple 提醒事項（CalDAV）

| 看到 | 意思 | 怎麼辦 |
|---|---|---|
| iCloud 帳號裡找不到能用 CalDAV 讀的提醒事項清單 | 升級過的 iCloud 提醒事項（見 2-4） | 改接別家 CalDAV 帳號 |
| 這個 CalDAV 帳號裡沒有提醒事項（VTODO）清單 | 別家帳號但還沒建清單 | 在 iPhone 那個帳號底下建一個清單 |
| 帳號或密碼不對。iCloud 要用「App 專用密碼」… | 401 | 用 App 專用密碼（不是 Apple ID 密碼）；`Connect-Apple.bat` 重設 |
| 伺服器網址要是 https://… | 網址不是 https | 改成 `https://` 開頭 |
| 連不上伺服器（…）。網路斷了，或伺服器網址不對？ | 網路或網址 | 檢查網址 |
| 伺服器沒有告訴我你的帳號在哪（current-user-principal） | 網址不是 CalDAV 的入口 | 用那一家文件寫的 CalDAV 網址 |
| 伺服器沒有告訴我你的行事曆在哪（calendar-home-set） | 同上 | 同上 |
| 伺服器要我連到別的地方（…），為了帳密安全沒有連 | 伺服器把你轉到另一台主機 | 直接填最後那台主機的網址；回報 |
| 伺服器回 HTTP N（方法） | 其他錯誤 | 回報那一行 |
| 這一筆剛剛在別的裝置上改過了 | 412 | `/applerem` 重列再試 |
| 伺服器回的資料太大了／XML 有 DOCTYPE／不是看得懂的 XML | 安全檢查擋下 | 回報 |
| 這是重複的提醒事項… | 重複的不經 CalDAV 打勾 | 在 iPhone 上完成 |
| 還沒設定帳號 | 保管箱沒有 | `Connect-Apple.bat` |

### Discord

完整的排查清單在 [discord-handoff.md](discord-handoff.md) 第 9 節；煙霧測試會出現的：

| 看到 | 意思 | 怎麼辦 |
|---|---|---|
| Discord 不認這個 token…；上線會是 4004 | token 錯或按過 Reset Token | Developer Portal → Bot → Reset Token，`python -m synox discord token` 重存 |
| 這個 token 不是 bot 的 | 貼到別的東西（例如 Client Secret） | 要 Bot 頁的 token |
| Message Content intent 看起來沒開；上線會被 4014 拒絕 | Portal 沒開 | Bot 頁 → Privileged Gateway Intents → Message Content Intent → Save |
| bot X：token ❌ 保管箱裡沒有／保管箱裡找不到 … | 還沒存 | `python -m synox discord token`（多個 bot 加 `--bot 名字`） |
| 擁有者還沒配對 Discord 帳號 | 還沒 `discord pair` | 見交接文件第 5 步 |
| config.json ❌ … | `channels.discord` 寫錯 | 照錯誤訊息說的那一格改 |

### 腳本本身

| 看到 | 怎麼辦 |
|---|---|
| 程式出錯（某某Error）；細節不印 | 腳本故意不印內容（怕帶出憑證）。把那一行和你當時做了什麼回報給擁有者 |
| 保管箱打不開 | `data` 是從別台電腦複製來的？保管箱只認建立它的電腦＋帳號。刪掉這台的 `data` 重新設定 |
| （data 裡還沒有保管箱：憑證都會在這裡問） | 正常：還沒存過任何東西 |
| 找不到 config.json | 做第 1-3 步 |

---

## 6. 回報：貼進「部署測試板」

1. 把腳本最後「下面這段可以整段貼進「部署測試板」」底下的文字整段複製。
2. 在部署測試板：
   - **檢查項**：每個服務一列，結果照摘要的 ✅／❌／⏭ 勾；備註貼那一行（例如「✅ Notion：token 驗證✅、搜尋頁面✅…」）。
   - **問題紀錄**：摘要「問題：」底下每一行開一筆，欄位建議：日期時間、服務、項目、看到的訊息（照貼）、你做了什麼、下一步建議。
   - 欄位名稱以部署測試板上實際的為準。
3. 可以附上整張表格；**不要**附截圖裡有 token 的畫面、不要附 `config.json`、`data` 資料夾。
4. 想多說的（例如「Apple 用的是 Fastmail 帳號」「Google 停在測試狀態」）寫在備註。

---

## 7. 測完怎麼清理

### 7-1 SYNOX 這邊（刪掉這台電腦存的憑證）

| 服務 | 在 `Console.bat` 打（或命令列） |
|---|---|
| Notion | `/notion_logout` |
| Todoist | `/todoist_logout` |
| Google 日曆 | `/gcal_logout`（也會請 Google 收回授權） |
| Apple | `/applerem_logout`，或 `.venv\Scripts\python.exe -m synox connect apple-reminders --clear` |
| Discord | 目前**沒有**刪除指令：把 `config.json` 的 `channels` 拿掉，並到 Portal Reset Token 讓舊的失效（見下表） |

測試機不再用 SYNOX 的話：關掉所有 SYNOX 視窗，**直接刪掉整個 SYNOX 資料夾**（含 `data`）最乾淨。

### 7-2 服務那邊（讓 token 真的失效）

| 服務 | 到哪裡撤銷（位置以官方文件為準） |
|---|---|
| Notion | <https://www.notion.so/profile/integrations> → 那個 integration → 刪除 |
| Todoist | 設定 → 整合 → 開發者 →「重新產生」API token（舊的立刻失效） |
| Google | <https://myaccount.google.com/permissions> 移除這個 app；Google Cloud 主控台可以刪掉整個測試專案 |
| Apple | <https://appleid.apple.com> → 登入與安全性 → App 專用密碼 → 撤銷那一組；別家 CalDAV 到那一家的設定撤銷 App 密碼 |
| Discord | <https://discord.com/developers/applications> → 你的 App → Bot → Reset Token；不用了就刪掉整個 Application，伺服器裡也把 bot 踢掉 |

`--write` 留下的東西：Apple 會留一筆打勾完成的「SYNOX-smoke-test …」，在 iPhone 刪掉；Notion 的在垃圾桶，會自己清掉。

---

## 8. 這份教學依據的程式

| 服務 | 程式 | 原本的說明 |
|---|---|---|
| Notion | `connectors/notion/pack.py`（`Notion` 類別） | `connectors/notion/README.md` |
| Todoist | `connectors/todoist/pack.py`（`Client`） | `connectors/todoist/README.md` |
| Google 日曆 | `connectors/google-calendar/pack.py`（`Client`、OAuth） | `connectors/google-calendar/README.md` |
| Apple | `connectors/apple-reminders-caldav/pack.py`（`Client`） | `connectors/apple-reminders-caldav/README.md` |
| Discord | `src/synox/discord/`（`DiscordChannel`、`Gateway`） | `docs/discord.md`、[discord-handoff.md](discord-handoff.md) |
| 煙霧測試 | `scripts/smoke_real.py`（測試：`tests/test_smoke_real.py`） | 檔案開頭的說明 |
