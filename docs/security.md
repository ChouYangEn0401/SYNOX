# SYNOX 的安全邊界（資料在哪、誰看得到、怎麼備份）

說實話版：哪些有保護、哪些沒有。

## 資料在哪

| 檔案 | 內容 | 保護 |
|---|---|---|
| `config.json` | Telegram bot token、你的 Telegram id、AI 設定 | **明文**（只靠 Windows 帳號的檔案權限）。AI 的金鑰不在這裡：精靈存進保管箱，這裡只寫 `vault:llm_api_key` |
| `data/.synox.key` | 保管箱的主金鑰（32 bytes 隨機） | Windows：用 **DPAPI** 包起來，只有這台電腦的這個 Windows 帳號解得開。其他平台或 `vault.mode: file`：明文（會記警告） |
| `data/notes.json.enc`、`data/money.json.enc`、`data/schedule.json.enc`、`data/secrets.json.enc` | 筆記、記帳、提醒、AI 金鑰 | **密文**：Fernet（AES-128-CBC＋HMAC-SHA256），每次存檔換新的 salt、檔案金鑰＝scrypt(主金鑰, salt)。被改過一個 byte 就解不開（會報錯，不會默默清空） |
| `data/users.json`、`data/llm_usage.json`、`data/host.lock`、`data/last_update_id`… | 誰傳過訊息、AI 用量、執行狀態 | 明文（沒有內容，只有 id、次數） |

**硬碟被拷走、`data/` 被同步到雲端被看到**：拿到的是密文和 DPAPI 包住的金鑰，解不開（除非也能登入你的 Windows 帳號）。
**有人登入你的 Windows 帳號、或在你的帳號下跑程式**：DPAPI 擋不住，他看得到一切。這是 DPAPI 的設計，不是 bug。

## 會離開這台電腦的只有兩條

1. **Telegram**：你跟 bot 之間的訊息經過 Telegram 的伺服器。bot 訊息**不是**端對端加密，Telegram 與 bot 兩端都看得到明文——
   這是平台的事實，SYNOX 修不了。不要在聊天裡傳密碼。
2. **LLM（有設定 AI 時）**：送出去的是你那一句話、系統提示（已裝的功能、技能清單）、最近 6 輪的對話、
   以及 AI 呼叫工具時**那個指令回的那幾行**（例如「記了：咖啡 80 元，這個月共 230 元」）。
   AI 看不到你的整個資料庫，只看得到它叫的指令回了什麼。

## 用朋友／公司的 LLM

- 公司看得到「你的問句＋AI 工具回傳的那幾行」，看不到你的資料庫、看不到 Telegram 聊天全文。
- 要再保守：本機模型（Ollama、LM Studio），一樣選「朋友／公司給的 AI 網址」填 `http://localhost:11434/v1`，什麼都不出電腦。

## 整個 SYNOX 架在別人（例如公司）的電腦上

那就是「那台電腦的管理者看得到一切」：他能登入那個 Windows 帳號，DPAPI 就擋不住。
加密在這個情況只防「資料庫檔案被偷走」，**防不了營運者**。不要把這種安排說成安全的。

## 誰能用你的 bot

- 只有安裝時配對的 Telegram 帳號（`owner_id`）。出廠 pack 都是 `access: owner`：別人傳 `/note`，回的跟「沒有這個指令」一模一樣。
- AI 只聽你的（別人傳的人話不會送去 LLM）。
- 危險的動作（刪光筆記、把危險指令排進排程）AI 不能直接做，一定先送確認卡，**你按了**才做；確認卡 10 分鐘過期、只能按一次、別人偽造按鈕無效。
- 你的 Telegram 帳號被盜 = 對方能用你的 bot。SDK 有 `/sudo`（手機驗證器）的第二道門，但出廠的 pack 沒有用到；要用的話，
  把危險的指令標 `elevated=True` 並裝 SDK 的 `sudo` pack。

## 備份

- v0 **還沒有** `/backup`。要備份就把整個 `data/` 資料夾複製走——但要知道：DPAPI 包住的金鑰**換電腦或換 Windows 帳號就解不開**，
  所以這份備份只能在同一台電腦、同一個帳號還原。
- 之後的 `/backup`（spec §6）：把 `data/` 打成一個用保管箱金鑰衍生的密碼加密的 zip，放到你指定的資料夾（OneDrive、Google Drive 同步資料夾）。
- `vault.mode: file` 時金鑰是明文檔，備份 `data/` 就能在別台還原，但拿到備份的人也能解開。

## 沒有做的保護（誠實清單）

- `config.json` 的 bot token 是明文。
- 不防「在你的 Windows 帳號下跑的惡意程式」。
- 不防 prompt injection 的全部情況：工具結果裡的文字有提示 AI「當資料、不當指令」，真正擋住危險動作的是確認卡（結構），不是提示。
- `claude_code` 這個 AI 來源以 `--tools ""` 跑（Claude Code 自己不能動檔案），但它走的是你本機的 Claude Code 登入。
