# SYNOX：你自己電腦上的 Telegram 小助手

> ⚠️ **目前是 alpha，請先別拿來放重要資料。**
> - 所有 connector（Notion、Todoist、Google 日曆、Apple 提醒事項）與 Discord 通道都**只用假傳輸測過**，還沒對真實服務驗證。
> - 沙盒後端**還沒在 Linux 實機上驗證**。
> - **伺服器版的營運者（架的人）看得到使用者的資料**。
> - 第三方 pack 的安全邊界：見 [docs/security.md](docs/security.md)「這套系統現在能保證什麼、不能保證什麼」。
> - 授權：見 [LICENSING.md](LICENSING.md)。發現安全問題：見 [SECURITY.md](SECURITY.md)（請不要開公開 issue）。

在手機的 Telegram 跟它講話：記帳、隨手記、提醒；接了 AI 之後，直接說人話它就會替你按指令
（刪東西這類危險的事，會先送一張確認卡給你按）。資料都在**你自己的電腦**上，筆記和記帳是加密存的。

> **SYNOX 出廠不帶工具**（2026-11-12 起）：記帳、隨手記、提醒、行事曆、待辦……都在另一個專案 **SYNOX 工具庫（SYNOX_Libs）**，
> 一個工具一個 `.synoxpack` 檔，要什麼自己裝（見下面「裝工具」）。從舊版更新上來的人：資料還在，裝回同名工具就接著用
> （[legacy/builtin-packs.md](legacy/builtin-packs.md)）。

## 快速開始：三步裝好（Windows 10／11）

1. **雙擊 `Setup.bat`**。第一次會花幾分鐘準備 Python 和套件（會出現一個顯示進度的視窗，不用打任何字；
   電腦沒有 Python 的話，它會自己裝）。
2. **照安裝視窗點四頁**：
   - **這台給誰用？**「只有我（個人版）」或「一群人（伺服器版）」（差在哪見下面）。
   - **Telegram bot 的 token**：照畫面上的三步跟 @BotFather 拿一個，貼上，按「檢查 token」。
   - **你是誰**：畫面會給你六個數字，按按鈕打開你的 bot，把數字傳給它，畫面就認得你了。
   - **AI 從哪裡來**：最上面是預設的 **Claude（這台電腦登入的 Claude Code）**，畫面會說找不找得到；
     下面「其他金鑰來源」可以選 OpenAI、Anthropic API、Gemini，或「相容端點」（公司給的網址、自己電腦上的 Ollama），填金鑰和模型；
     也可以「先不用 AI」。按「測一下」確認接得通。
3. **按「完成並開始」**。手機會收到「👋 我在了，按 /help 看我會什麼」。
4. **裝工具**：剛裝好的 SYNOX 是空的（`/help` 會提醒你）。拿到工具庫的 `.synoxpack` 檔，點兩下或在網頁「設定 → 裝功能」上傳。

之後要開 bot：雙擊桌面的「SYNOX」捷徑（或 `Start.bat`）。會有一個縮小的視窗，那就是 bot；關掉它（或雙擊 `Stop.bat`）bot 就停了。

在命令列也可以：在 SYNOX 資料夾開命令列，下面的 `synox` 打成 `.venv\Scripts\synox`（或 `.venv\Scripts\python.exe -m synox`；
啟用了 `.venv` 就直接打 `synox`）：

```
synox open      在這台電腦上打開網頁介面（沒在跑會先幫你開；跟雙擊 Open-SYNOX.bat 一樣）
synox doctor    健康檢查
synox about     版本、授權、裝在哪裡
synox tips      隨機一則使用小提示
```

在終端機打這些指令（或只打 `synox`）會先看到 SYNOX 的歡迎畫面；不想看到就加 `--quiet`，或設環境變數 `SYNOX_NO_BANNER=1`
（長相：[docs/ui/cli-welcome.txt](docs/ui/cli-welcome.txt)）。

## 在電腦上用網頁（Web UI）

在 Telegram 打 `/web`，bot 會給你一個登入連結（只能用一次、7 天內有效），在**跑 SYNOX 的那台電腦**上打開就登入了
（安裝精靈按「完成並開始」之後也會自己打開一次）。三頁：

- **對話**：跟 Telegram 一樣的訊息流，左邊是對話清單（新對話／接著上一段）；打字給 AI、打 `/指令`，確認卡的 ✅／❌ 直接按。
- **工具**：你裝的每個功能一張卡，指令旁邊的框直接執行；工具自己可以帶小面板（例如記帳的「這個月花多少、預算剩多少」）。
- **設定**（擁有者）：換 AI 來源、裝／移除功能（`.synoxpack`）、下載加密備份；伺服器版還有帳號表（改角色、看用量）。

網頁只聽這台電腦（127.0.0.1:8830，`config.json` 的 `web.port` 可以改）。不想要：`/web_off`（到重開前關掉），或 `"web": {"enabled": false}`。

## 每天怎麼用

| 在 Telegram 打 | 做什麼 |
|---|---|
| `/help` | 看全部指令（還沒裝工具時會告訴你去哪裡裝） |
| `/note 買牛奶`、`/note_list`、`/note_rm 1` | 隨手記（要先裝工具庫的 `notes`） |
| `/money 120 午餐`、`/money_month`、`/money_budget 20000` | 記帳、看這個月、設預算（要先裝 `money`） |
| `/remind_add 08:00 吃藥`、`/remind_list` | ⏰ 提醒（系統）：每天提醒；加 `date=2026-11-20` 只提醒那一天（SYNOX 本體就有，不用裝；跟 Apple 提醒事項無關） |
| `/schedule_add 21:00 /money_month` | 每天幾點自動替你跑一個指令（SYNOX 本體就有） |
| 直接打字，例如「幫我記一筆 80 元咖啡」 | 交給 AI（有設定 AI 時） |
| `/ai_usage` | AI 用了多少 |
| `/web` | 拿網頁介面的登入連結 |

個人版：只有你（安裝時配對的那個 Telegram 帳號）用得到這些指令；別人傳訊息給你的 bot，看不到也用不了。

## 個人版和伺服器版

| | 只有我（個人版） | 一群人（伺服器版） |
|---|---|---|
| 給誰 | 你一個人 | 家人、同事、社團 |
| 別人傳訊息 | 當作沒這個指令 | 自動變成「訪客」，只看得到開放給所有人的功能 |
| 讓別人用 | — | 你打 `/user_list` 看誰來過、`/user_role <id> member` 讓他用筆記、記帳、提醒、排程和 AI（或在網頁設定頁的帳號表改）；他也可以 `/me_upgrade` 申請 |
| AI | 你 | 成員以上，每人每月有額度（`ai_member_monthly_usd`，預設 US$2；`/ai_budget <id> <美元>` 調） |
| 資料 | 一份，加密存在這台電腦 | **每個人一份**，各自加密；使用者之間互相看不到 |
| 誰看得到資料 | 只有這台電腦、這個 Windows 帳號 | **架這台的人（你）技術上看得到所有人的資料**（見 [docs/security.md](docs/security.md)），給別人用前要講清楚 |

伺服器版每個人的提醒、排程也各自一份，提醒只送給建立的那個人。之後要換：改 `config.json` 的 `"mode"`（或重跑 `Setup.bat`），重開 bot；
個人版的舊資料不會自動搬到伺服器版（留著不動，改回個人版又會用它們）。

## 工程師模式：不用精靈

直接照 `config.example.json` 寫一份 `config.json`（`mode`、`bot_token`、`owner_id`、`llm`…），然後：

```
.venv\Scripts\python.exe -m synox doctor --offline     先檢查
.venv\Scripts\python.exe -m synox run                  開 bot（跟 Start.bat 一樣）
```

`llm.kind` 可以是 `claude_code`、`openai`、`anthropic`、`gemini`、`openai_compat`（要 `base_url`）、`fake`、`none`；
`api_key` 可以直接寫、寫 `env:環境變數名`，或 `vault:llm_api_key`（精靈存進保管箱的）。
用金鑰的四種要先裝 ntu_easy_llm（見 [docs/AGENT.md](docs/AGENT.md) 的「ntu_easy_llm」）；沒裝時 `doctor` 和「測一下」會說怎麼裝。

## 常見問題

- **手機沒收到「我在了」？** 看 `Start.bat` 開的那個小視窗有沒有紅字；雙擊 `Console.bat` 可以不連 Telegram 直接在電腦上試指令。
  也可以在 SYNOX 資料夾開命令列跑 `.venv\Scripts\python.exe -m synox doctor`，它會檢查設定、AI、資料。
- **提醒沒有響？** 提醒只有 bot 開著（那個小視窗在）的時候才會送。可以在安裝精靈勾「開機自動啟動」。
- **換 AI？** 再雙擊一次 `Setup.bat`，AI 那一頁選別的。或直接改 `config.json` 的 `llm`。
- **「還沒安裝 ntu_easy_llm」？** 用 API 金鑰的 AI（OpenAI、Anthropic、Gemini、相容端點）要多裝這個套件；Claude Code 不用。
  裝法見 [docs/AGENT.md](docs/AGENT.md) 的「ntu_easy_llm」。
- **換電腦？** 加密的資料只有**這台電腦、這個 Windows 帳號**解得開（見 [docs/security.md](docs/security.md)）。
  網頁設定頁的「下載備份」也只能在同一台電腦、同一個帳號還原；換電腦前先別刪舊的。
- **`data` 資料夾可以刪嗎？** 不要。裡面是你的筆記、記帳和**解密用的金鑰（`.synox.key`）**；金鑰不見，加密的資料就再也打不開了。

## 裝工具：丟一個 pack 進來

一個功能＝一個 pack（一個資料夾：`pack.json`、`SKILL.md`、`README.md`、程式），壓成 `.synoxpack` 給人裝。
SYNOX 出廠不帶任何工具；官方的工具都在 **SYNOX 工具庫（SYNOX_Libs）**：一堆 `.synoxpack`＋一份目錄 `index.json`（名稱、版本、說明、
建議組合、雜湊），挑你要的裝。工具庫放在哪裡可以寫進 `config.json`：`"packs": {"library": "<工具庫的 dist 資料夾或網址>"}`，
`/help`、`doctor`、網頁就會直接告訴你位置（沒寫只給說明）。

拿到 `.synoxpack`：在網頁設定頁上傳，或點兩下檔案，或 `.venv\Scripts\python.exe -m synox install <檔>`；
SYNOX 先檢查、把報告給你看，你按確認才裝。裝好 `/help` 就多一組，AI 也會自己學會怎麼用。
每個工具會宣告它照哪一版 SDK 寫（`requires.sdk`）；跟這台不合的會明說、不裝。

**想自己寫工具接進來**（任何語言的命令列程式、MCP 伺服器、別人架好的遠端 MCP）：從 [docs/tools.md](docs/tools.md) 開始——
怎麼選接入方式、十行入門、權限怎麼宣告、怎麼測試與打包；範例在 [examples/](examples/)。全部文件的索引：[docs/README.md](docs/README.md)。

不想要某個 pack：`config.json` 的 `"packs": {"disabled": ["money"]}`。
pack 放在別的地方（例如另一個 repo 裡、要用那個 repo 自己的 Python）：
`"packs": {"dirs": ["<你的資料夾>/synox-pack"]}`——每一項可以是一個 pack 的資料夾，或裝了很多 pack 的資料夾。

## 還沒有（v0 不做的）

- 多支 bot 分流、服務別人的角色商店、Remote Control／派工、AI 的情境（persona）與長期記憶。
- 伺服器版：個人版的舊資料不會自動搬過去；「連架設的人都看不到」的版本（另一份規格）；網頁介面對外開放（要自己架反向代理＋TLS）。
- 匯入前身專案的資料；換電腦的匯出（備份綁這個 Windows 帳號）、還原按鈕；網頁看圖／下載檔案、網頁收提醒（提醒只走 Telegram）。
- connector：Notion、Todoist、Google 日曆、Apple 提醒事項都做好了（設定步驟見各自 `connectors/*/README.md`），但都只用假傳輸測過，還沒對真的服務跑過。
  到另一台電腦用真的帳號測（含 Discord）：[docs/handoff/](docs/handoff/README.md)（教學＋煙霧測試 `scripts/smoke_real.py`）。
  Apple 提醒事項要注意：iCloud 升級過的提醒事項 Apple 不開放 CalDAV，見 `connectors/apple-reminders-caldav/README.md`。
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
公開 repo 或發佈之前：[docs/AGENT.md](docs/AGENT.md) 的「公開前檢查清單」（`scripts\prepublish_check.py`）。

## 回報安全問題

請**不要**開公開 issue。回報方式、範圍與回應時程見 [SECURITY.md](SECURITY.md)。

## 授權

- **核心**：AGPL-3.0-or-later（[LICENSE](LICENSE)）。自己用、公司內部用、商用都可以；改了核心再架成網路服務給別人用，就要提供修改後的原始碼。
- **工具 SDK 與範例**：Apache-2.0（[LICENSE-APACHE](LICENSE-APACHE)）。你用 SDK 寫的工具，授權由你決定，閉源、商用都可以。
- 範圍、商業授權、貢獻者同意書與商標政策：[LICENSING.md](LICENSING.md)、[CONTRIBUTING.md](CONTRIBUTING.md)、[TRADEMARK.md](TRADEMARK.md)。
