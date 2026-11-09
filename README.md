# SYNOX：你自己電腦上的 Telegram 小助手

在手機的 Telegram 跟它講話：記帳、隨手記、提醒；接了 AI 之後，直接說人話它就會替你按指令
（刪東西這類危險的事，會先送一張確認卡給你按）。資料都在**你自己的電腦**上，筆記和記帳是加密存的。

## 三步裝好（Windows 10／11）

1. **雙擊 `Setup.bat`**。第一次會花幾分鐘準備 Python 和套件（會出現一個顯示進度的視窗，不用打任何字；
   電腦沒有 Python 的話，它會自己裝）。
2. **照安裝視窗點三頁**：
   - **Telegram bot 的 token**：照畫面上的三步跟 @BotFather 拿一個，貼上，按「檢查 token」。
   - **你是誰**：畫面會給你六個數字，按按鈕打開你的 bot，把數字傳給它，畫面就認得你了。
   - **AI 從哪裡來**：朋友或公司給的網址＋金鑰、自己的 API key、這台電腦已登入的 Claude Code，或先不用 AI。按「測一下」確認接得通。
3. **按「完成並開始」**。手機會收到「👋 我在了，按 /help 看我會什麼」。

之後要開 bot：雙擊桌面的「SYNOX」捷徑（或 `Start.bat`）。會有一個縮小的視窗，那就是 bot；關掉它（或雙擊 `Stop.bat`）bot 就停了。

## 每天怎麼用

| 在 Telegram 打 | 做什麼 |
|---|---|
| `/help` | 看全部指令 |
| `/note 買牛奶`、`/note_list`、`/note_rm 1` | 隨手記 |
| `/money 120 午餐`、`/money_month`、`/money_budget 20000` | 記帳、看這個月、設預算（超過會提醒你） |
| `/remind_add 08:00 吃藥`、`/remind_list` | 每天提醒；加 `date=2026-11-20` 只提醒那一天 |
| `/schedule_add 21:00 /money_month` | 每天幾點自動替你跑一個指令 |
| 直接打字，例如「幫我記一筆 80 元咖啡」 | 交給 AI（有設定 AI 時） |
| `/ai_usage` | AI 用了多少 |

只有你（安裝時配對的那個 Telegram 帳號）用得到這些指令；別人傳訊息給你的 bot，看不到也用不了。

## 常見問題

- **手機沒收到「我在了」？** 看 `Start.bat` 開的那個小視窗有沒有紅字；雙擊 `Console.bat` 可以不連 Telegram 直接在電腦上試指令。
  也可以在 SYNOX 資料夾開命令列跑 `.venv\Scripts\python.exe -m synox doctor`，它會檢查設定、AI、資料。
- **提醒沒有響？** 提醒只有 bot 開著（那個小視窗在）的時候才會送。可以在安裝精靈勾「開機自動啟動」。
- **換 AI？** 再雙擊一次 `Setup.bat`，第三頁選別的。或直接改 `config.json` 的 `llm`。
- **換電腦？** 加密的資料只有**這台電腦、這個 Windows 帳號**解得開（見 [docs/security.md](docs/security.md)）。
  v0 還沒有「匯出／匯入」，換電腦前先別刪舊的。
- **`data` 資料夾可以刪嗎？** 不要。裡面是你的筆記、記帳和**解密用的金鑰（`.synox.key`）**；金鑰不見，加密的資料就再也打不開了。

## 想加功能：丟一個 pack 進來

一個功能＝`packs/` 底下一個資料夾（`pack.json`、`SKILL.md`、`README.md`、`pack.py`）。把資料夾放進去、重開 bot，
`/help` 就多一組，AI 也會自己學會怎麼用。格式與範例在 [docs/pack-format.md](docs/pack-format.md)。
不想要某個 pack：`config.json` 的 `"packs": {"disabled": ["money"]}`。

## 還沒有（v0 不做的）

- 本機 HTTP 入口、多支 bot 分流、服務別人的角色商店、Remote Control／派工、AI 的情境（persona）與長期記憶。
- 匯入 ClawBot 的資料；`/backup` 加密備份與換電腦的匯出（v0 只有：資料留在 `data/`，金鑰綁這個 Windows 帳號）。
- Google 日曆、Notion、Todoist、Apple 提醒事項：`connectors/` 裡只有設計稿，打 `/gcal` 之類的會說「還沒接上」。
- macOS／Linux 的安裝器（程式本身跨平台，但 `Setup.bat` 只有 Windows）；打包成 .exe（之後用 PyInstaller）。
- AI 的對話紀錄只放在記憶體（重開 bot 就忘了），每個聊天留最近 6 輪。

## 給開發的人

```
.venv\Scripts\python.exe -m pytest -q          測試（不連網、不開埠、不連 Telegram）
.venv\Scripts\python.exe -m synox console      終端機模式（沒有 config.json 時用示範設定＋假 AI）
.venv\Scripts\python.exe -m synox doctor --offline
.venv\Scripts\python.exe scripts\make_zip.py   打包給人的 zip（不含 .venv、data、config.json）
.venv\Scripts\python.exe scripts\vendor_sdk.py 重新複製 ISDTeleKitSDK 到 vendor/
```

地圖與規則在 [docs/AGENT.md](docs/AGENT.md)；版本紀錄在 [CHANGELOG.md](CHANGELOG.md)。
