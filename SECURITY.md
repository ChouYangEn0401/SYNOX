# 回報安全問題

謝謝你願意幫忙。發現 SYNOX 的安全問題時：

1. **請不要開公開 issue、不要在 pull request 或討論區貼細節。**
2. 寫信到 `mi.anthony.chou+security@gmail.com`，內容盡量包含：
   - 影響哪個版本或 commit、個人版還是伺服器版；
   - 怎麼重現（最小的步驟或 pack）；
   - 你認為的影響（誰能做到什麼）。
3. **不要附上真的 token、API 金鑰、密碼或別人的個人資料**；需要示範就用假值。

## 回應時程

SYNOX 是小型、志願維護的專案，回應是**盡力而為**，沒有保證的時程。我們會盡量在收到後確認收件、評估嚴重度，
修好後在 [CHANGELOG.md](CHANGELOG.md) 記錄；你願意的話，會在修正說明裡致謝。請在修正發佈前不要公開細節。

## 範圍

**在範圍內**（這個 repo 的程式）：

- SYNOX 核心（`src/synox/`）：權限判斷、保管箱與加密、網頁介面（登入、CSRF、Origin）、Telegram／Discord 通道的身分與配對。
- pack 安裝與執行：五關檢查、完整性鎖定、信任層級、沙盒包裝、依賴建置（pip／npm）。
- 工具 SDK（`src/synox/sdk/`、`sdk/`）與官方工具（2026-11-12 起在 SYNOX 工具庫 SYNOX_Libs；以前在這裡的 `packs/`、`connectors/`）。
- 安裝器與腳本（`setup/`、`scripts/`、`*.bat`）。

**不在範圍內**：

- [docs/security.md](docs/security.md)「這套系統現在能保證什麼、不能保證什麼」與「沒有做的保護（誠實清單）」已經寫明**不保證**的事
  （例如：伺服器版營運者看得到使用者資料；個人版的 python pack 沒有隔離；你自己按下確認安裝的惡意 pack）。
  若你找到的是繞過**已宣稱**的保護，仍然在範圍內。
- 第三方 pack、外部服務（Telegram、Discord、Notion、Todoist、Google、Apple、LLM 供應商）本身的漏洞——請回報給它們。
- `vendor/isdtelekit/` 的問題請一併告訴我們，但修正會在上游進行。
- 需要已經能控制使用者電腦或 Windows 帳號的攻擊。
- 社交工程、阻斷服務（例如大量傳訊息給 bot）。
