# 📅 Google 日曆（google-calendar）

讓 SYNOX 直接看、加、刪**你自己的 Google 日曆**。跟本機的「📅 行事曆」（`/cal`）用法一樣，只是指令換成 `/gcal`。

| 指令 | 做什麼 |
|---|---|
| `/gcal 明天 14:00 看牙醫` | 加一個行程（也收 `location=診所`、`note=帶健保卡`；`/gcal 11/20 整天 員工旅遊`） |
| `/gcal_today` | 今天的行程 |
| `/gcal_week` | 這 7 天的行程 |
| `/gcal_list [n]` | 接下來的 n 個行程（預設 10） |
| `/gcal_rm <編號>` | 刪掉一個（編號是最近一次列出來的 `[3]`；AI 要刪會先送確認卡給你按） |
| `/gcal_status` | 連上了沒、唯讀還是可以寫 |
| `/gcal_setup`、`/gcal_code`、`/gcal_token`、`/gcal_logout` | 連接／中斷（只有你能打，AI 用不到） |

---

## 第一次設定（大約 10 分鐘，只要做一次）

Google 規定每個程式都要有自己的「OAuth 用戶端」。SYNOX 沒有一個大家共用的，所以要在你自己的 Google 帳號裡建一個
（免費、不用信用卡）。

### A. 在 Google Cloud 建一個用戶端

1. 打開 <https://console.cloud.google.com/>，用你的 Google 帳號登入。
2. 左上角「選取專案」→「新增專案」，名字隨便（例如 `my-synox`）→ 建立。
3. 上面的搜尋框打 **Google Calendar API** → 點進去 →「啟用」。
4. 左邊選單「API 和服務」→「OAuth 同意畫面」（新版叫「Google Auth Platform」）：
   - 使用者類型選「**外部**」→ 填應用程式名稱（例如 `SYNOX`）、你的 email → 一路儲存。
   - 「目標對象／測試使用者」：把**你自己的 Gmail** 加進去。
   - **建議**：在「發布狀態」按「**發布應用程式**」（改成「正式版」）。不發布的話（停在「測試」），
     Google 每 **7 天**會讓授權失效，你就得重新連一次。發布後不用給 Google 審核也能自己用（登入時會看到「尚未驗證」的警告，按「進階 → 前往」即可）。
5. 左邊「憑證」→「建立憑證」→「OAuth 用戶端 ID」→ 應用程式類型選「**電腦版應用程式**（Desktop app）」→ 建立。
6. 畫面會給你兩串字：**用戶端 ID**（`….apps.googleusercontent.com` 結尾）和**用戶端密鑰**（`GOCSPX-…`）。先留著這個視窗。

### B. 在 SYNOX 連上

> 建議在**這台電腦上的 SYNOX 終端機**（`Console.bat`）或網頁介面打這幾步，而不是在 Telegram 打：
> Telegram 的訊息不是端對端加密。如果用 Telegram 打，完成後把那幾則訊息刪掉。

1. 打：`/gcal_setup <用戶端 ID> <用戶端密鑰>`
   （只想讓 SYNOX 看、不能改：最後加 `readonly`，例如 `/gcal_setup 123….apps.googleusercontent.com GOCSPX-… readonly`）
2. SYNOX 回你一個 Google 連結 → 用瀏覽器打開 → 選你的帳號 →（看到「尚未驗證」→「進階」→「前往」）→ 勾選日曆權限 →「繼續」。
3. 最後瀏覽器會顯示「**無法連上這個網站**」或「127.0.0.1 拒絕連線」——**這是正常的**。
   SYNOX 故意不在你的電腦上開任何網路埠；要的東西就在網址列裡。
4. 把**網址列整串**（`http://127.0.0.1:47231/?state=…&code=…&scope=…`）複製下來，打：
   `/gcal_code <貼上整串網址>`
5. 看到「✅ 連上 Google 日曆了」就好了。試試 `/gcal_today`。

連結 15 分鐘內有效；超過就再 `/gcal_setup` 一次（第二次可以只打 `/gcal_setup`，會沿用存著的用戶端）。

### 另一條路（進階）：直接貼 refresh token

已經有同一個用戶端發的 refresh token（例如用 Google 的 OAuth 2.0 Playground、勾「Use your own OAuth credentials」拿到的）：
先 `/gcal_setup <用戶端 ID> <用戶端密鑰>`（不用開連結），再 `/gcal_token <refresh token>`。SYNOX 會先跟 Google 確認它能用才存。

### 不想用了

`/gcal_logout`：刪掉這台電腦上的授權，並請 Google 收回。也可以到 <https://myaccount.google.com/permissions> 手動移除。

---

## 常見問題

| 狀況 | 怎麼辦 |
|---|---|
| 「Google 不再接受這個授權」 | 授權被收回或過期（app 停在「測試」狀態時 7 天就失效）。照上面 A-4 發布，再 `/gcal_setup` 一次 |
| 「state 對不上」 | 你貼的是比較舊的那次登入。用最新一次 `/gcal_setup` 給的連結 |
| 「Google 沒有給 refresh token」 | 到 <https://myaccount.google.com/permissions> 移除這個 app，再 `/gcal_setup` 一次 |
| 「client_id／client_secret 不對」 | 檢查 A-6 那兩串有沒有複製完整、用戶端類型是不是「電腦版應用程式」 |
| 時間差了幾小時 | SYNOX 用這台電腦的時區；檢查 Windows 的時區設定 |

---

## 安全：資料在哪、誰看得到

- **用戶端 ID／密鑰、refresh token、access token** 全部存在 SYNOX 的加密保管箱（`data/google-calendar.json.enc`，密文；
  伺服器版每個人一份）。不寫進 `config.json`、不寫進 log、不會出現在任何回覆或 AI 看到的工具結果裡。
- **AI 碰不到憑證**：連接用的四個指令（setup／code／token／logout）不給 AI；AI 只能看行程、加行程、刪行程，
  刪行程一定先送確認卡給你按。行程標題是 Google 那邊的資料（可能是別人邀請你時寫的），交給 AI 時包在隨機分隔符裡、當資料看。
- **不開網路埠**：登入不用本機的 loopback 伺服器。Google 把瀏覽器轉到 `http://127.0.0.1:47231/`，那裡沒有任何程式在聽，
  你把網址貼回來。就算這台電腦上剛好有別的程式在用那個埠、看到了網址，它也換不到 token（有 PKCE：
  換 token 要一串只存在 SYNOX 保管箱裡的 code_verifier）。
- **權限範圍**：預設 `calendar.events`（看、加、改、刪**你看得到的日曆上的行程**；不能改日曆設定、分享）；
  `readonly` 用 `calendar.events.readonly`。預設用「主要日曆」（primary）。
- **連到哪裡**：只有 `accounts.google.com`（你在瀏覽器登入）、`oauth2.googleapis.com`（換 token、收回）、
  `www.googleapis.com/calendar/v3`（行程）。只用 `requests`，沒有其他套件，沒有在本機跑別人的程式。
- 會離開這台電腦的：你的行程經過 Google（本來就在那裡）；AI 看行程時，那幾行會送到你設定的 LLM（跟其他 pack 一樣，見 docs/security.md）。

## 給開發的人

- 為什麼不用 device flow：Google 的「電視與輸入受限裝置」流程**不允許 Calendar 的 scope**（只收 email／profile、
  `drive.file`、`drive.appdata`、YouTube）。舊的 OOB（`urn:ietf:wg:oauth:2.0:oob`、手動複製碼）2023 年起已停用。
  所以用電腦版用戶端＋loopback redirect＋PKCE，只是**不開 listener**，讓使用者貼網址。
- 為什麼不用 MCP：Google 官方遠端 Calendar MCP 端點沒有驗證過、SYNOX 的 `kind: mcp` 還不會連線，最後一樣要 OAuth；
  社群的 nspady/google-calendar-mcp 要在本機跑 166 個 npm 套件、登入時對所有網卡開 3500–3505 埠、token 明文
  （審查見 SYNOXPacks `docs/mcp-audit-2026-11.md`）。REST 直連只要 requests。
- 指令、欄位跟 SYNOXPacks 的本機 `calendar` pack 一樣（`add`／`today`／`week`／`list`／`rm`、`text`／`date`／`time`／`location`／`note`），
  日期解析是同一份 `zhdate`（照抄在 pack.py 裡，正本在 SYNOXPacks `packs/_shared/zhdate.py`）。差別：`rm` 是 DANGER（刪的是雲端的資料），
  編號是「最近一次列出來的那一份」（Google 的 event id 太長，不給人打）。
- 測試：`tests/test_gcal.py`，假的 HTTP（換 `transport`），不連 Google。
