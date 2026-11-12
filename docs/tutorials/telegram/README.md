# 把 SYNOX 接上 Telegram（純文字版）

圖文版在同一個資料夾的 [index.html](index.html)（雙擊就能用瀏覽器打開，離線也可以；
SYNOX 在跑的時候也可以開 `http://127.0.0.1:8830/tutorials/telegram/`）。
這一份是同樣的步驟，給看不了 HTML 的情況用。全程大約五分鐘。

## 0. 開始前

- 一個 Telegram 帳號，手機（或電腦）上裝好 Telegram 並登入。
- 電腦上已經雙擊過 `Setup.bat`，安裝精靈停在「Bot 的 token」那一頁；或 SYNOX 已經在跑、打開了網頁的「設定 → 聊天通道」。
- 手機和電腦都能上網。

bot 可以想成「一個只跟你講話的 Telegram 聯絡人」，本體是你電腦上的 SYNOX；token 是這個聯絡人的鑰匙。

## 1. 跟 @BotFather 拿 token

1. 在 Telegram 搜尋 `BotFather`，點帳號剛好是 **@BotFather**、名字旁有**藍色勾勾**的那一個（沒有藍勾勾的都是仿冒）。第一次打開按 **START**。
2. 傳 `/newbot`。
3. 它問**名字**（顯示用，中文可以，之後能改）：例如「我的小助手」。
4. 它問**帳號**（username）：只能英文字母、數字、底線，5–32 個字，**結尾一定是 `bot`**（例如 `amy_helper_bot`），不能跟別人重複、之後不能改。
   它說「already taken」就換一個再傳。
5. 它回「Done! Congratulations on your new bot.」那一則裡，「Use this token to access the HTTP API:」下面那一整串就是 token，
   長得像 `123456789:AAH…`（冒號前是數字，冒號後一長串字母數字，整串約 45 個字）。
6. 手機：長按那一串 → 複製。電腦版：點一下通常就複製了。要複製**完整的一串**，前後不要多空格。

token 等於這支 bot 的密碼，不要貼到群組、截圖分享、交給任何網站。外流了看下面「換一組 token」。
之後要再看 token：對 BotFather 傳 `/mybots` → 點你的 bot → **API Token**。

## 2. 貼進 SYNOX，按「檢查 token」

**A. 安裝精靈（第一次安裝）**：第 2 頁「Bot 的 token」→「用哪一個」選 Telegram → 貼上 token →「檢查 token」→
看到「✅ 這支 bot 叫 @你的帳號」→「下一步」。（精靈上的「看圖文教學」按鈕會開這份教學的圖文版。）

**B. 網頁設定頁（SYNOX 已經在跑）**：雙擊桌面的「SYNOX」捷徑（或 `Open-SYNOX.bat`）→ 設定 → 聊天通道 → Telegram →
貼上 token →「檢查並存起來」→「✅ token 已存：bot @你的帳號」。之後**要重新啟動 SYNOX**（先雙擊 `Stop.bat`，再雙擊桌面捷徑）才會上線。
存好之後網頁不會再顯示 token 本身。

## 3. 配對：把六個數字傳給你的 bot

1. 精靈第 3 頁「你是誰」顯示一組六位數字（網頁設定頁：Telegram 那一格按「產生配對碼」）。數字有效 15 分鐘。
2. 按「打開 t.me/你的bot」，或在手機 Telegram 搜尋你剛取的帳號。
3. 第一次先按最下面的 **START**。
4. 把六個數字直接打出來送出（例如 `429170`）。
5. bot 回「✅ 配對成功！回到電腦上的安裝畫面，按『下一步』。」電腦畫面變成「✅ 認得你了：@你的帳號（id …）」→「下一步」去設定 AI。

## 4. 第一則訊息

精靈最後一頁按「完成並開始」，SYNOX 會開起來（一個縮小的小視窗）。幾秒內 bot 傳來「👋 我在了，按 /help 看我會什麼。」
回它 `/help` 看現在會的指令；有設定 AI 的話直接用人話講也行。

以後要開 bot：雙擊桌面的「SYNOX」捷徑（或 `Start.bat`）；關掉小視窗（或 `Stop.bat`）bot 就下線。

## 常見問題

**「❌ 這看起來不是 token」**：格式不對（一定是「數字:字母數字」）。常見是只複製到一半、多貼了前後的字、或貼成 bot 的帳號。回 BotFather 重新整串複製。

**「token 不對（Telegram 說 401）」**：這把鑰匙不存在或已作廢：你 Revoke 過、傳過 `/token`、複製少了一個字、或貼到別支 bot 的舊 token。
對 BotFather 傳 `/mybots` → 你的 bot → API Token，拿現在有效的那串重貼。

**「連不到 Telegram：檢查網路」**：換個網路、關掉 VPN／防火牆再按一次。

**傳了六個數字 bot 沒反應**：先按 START 了嗎？傳給的是你的 bot 而不是 BotFather？數字過了 15 分鐘（畫面「⌛ 等太久了」）就關掉精靈、再雙擊 Setup.bat 重來。
要用私訊、用你自己的帳號傳。

**配對好了之後 bot 都不回**（依序檢查）：
1. SYNOX 有開著嗎（工作列有那個小視窗）？電腦關機、睡眠時 bot 也下線。
2. 小視窗裡有紅字嗎？常見是 token 失效（401）或網路不通。
3. 你用的是配對的那個帳號嗎？個人版只回主人；換帳號要重新配對（網頁設定 → 聊天通道 → Telegram → 重新配對）。
4. 在群組裡嗎？SYNOX 現在只回私訊。
5. 剛在網頁改過 token？要重新啟動 SYNOX。
6. 還是不行：雙擊 `Console.bat` 在電腦上直接試指令；或跑 `.venv\Scripts\python.exe -m synox doctor`。

**token 外流了、想換一組**：對 BotFather 傳 `/mybots` → 你的 bot → API Token → **Revoke current token**（或直接傳 `/revoke`／`/token`），它立刻給新的、舊的失效。
把新 token 貼回 SYNOX（網頁設定 → 聊天通道 → Telegram，或重跑 Setup.bat），然後重新啟動 SYNOX。配對不用重做。

**隱私模式（Privacy mode）**：只影響 bot 在**群組**裡收得到哪些訊息（預設開著＝只收指令、回覆它的、@ 它的），私訊永遠不受影響。
SYNOX 只在私訊工作，所以**不用動**。真要改：`/setprivacy` → 選 bot → Enable／Disable；改了之後 bot 要從群組移除再加回去才生效。

**可以拉進群組一起用嗎**：目前不行。SYNOX 的指令和 AI 在群組裡都被擋掉（群組裡的人不該碰到你的資料）。要讓家人、同事用，安裝時選「一群人（伺服器版）」，
每個人各自私訊 bot，你用 `/user_list`、`/user_role` 決定誰能用什麼。

**改名字、頭像、說明**（都在 BotFather，不用重貼 token）：`/setname` 名字（帳號不能改）、`/setuserpic` 頭像、`/setdescription` 對話開頭的說明（最多 512 字）、
`/setabouttext` 簡介（最多 120 字）、`/setcommands` 指令提示（SYNOX 啟動時會自己設）、`/mybots` 用按鈕看全部設定。

**「Sorry, this username is already taken」**：帳號被用掉了，換一個再傳（不用重來 /newbot）。「invalid」通常是結尾不是 bot，或用了中文、空格、連字號。

**換了一台電腦**：token 不綁電腦，`/mybots` → API Token 拿同一串貼上即可，配對要再做一次。
但同一個 token 同一時間只能有一台電腦在跑（舊電腦先 `Stop.bat`）；資料綁舊電腦加密、不會自動搬，見 README「換電腦？」。

---

## 怎麼更新這份教學（給維護者）

- 圖文版 `index.html` 是**自足的一頁**：沒有外部資源（字型、圖片、程式都內嵌）、**沒有 JavaScript**（網頁的 `/tutorials/<名字>/`
  路由用嚴格 CSP，`<script>` 不會執行）。示意圖是 HTML／CSS 畫的手機與視窗框，不是截圖；改畫面時維持「示意圖」標示。
- 改步驟時**兩份一起改**（`index.html` 與這份 `README.md`），步驟編號與錯誤訊息的字句要跟程式一致：
  精靈的字在 `src/synox/wizard/lang/zh_TW.py`（`how_to_token`、`tg_bad_401`、`pair_*`…），網頁的在 `src/synox/web/static/app.html`
  與 `src/synox/telegram_link.py`（`UNPAIRED`、`PAIRED_OK`），開機問候在 `src/synox/app.py`（`GREETING`）。
- BotFather 的指令與規則請對照 Telegram 官方文件 <https://core.telegram.org/bots/features>（BotFather、Privacy mode 兩節）與
  <https://core.telegram.org/bots/tutorial>；頁尾寫的「確認日期」改掉。範例 token 一律用 `123456789:AAH…` 這種看得出是假的、
  **不要**放一串長度剛好像真的（`scripts/prepublish_check.py` 會把它當成外洩的 token）。
- 改完跑 `tests/test_tutorials.py`（自足、沒有 script、指令都還在、打包有帶到），並重新發佈 Artifact 後更新
  [../README.md](../README.md) 索引裡的網址。
