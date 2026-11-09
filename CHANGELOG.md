# Changelog

## 未發佈（branch feat/connector-todoist）

### 新增
- **Todoist connector 接上了**（`connectors/todoist`，從設計稿變成 `kind: python`＋`capabilities: ["network"]`）：Todoist API v1、個人 API token；
  `/todoist`（加）、`_list`（today｜overdue｜#專案｜@標籤）、`_done`、`_due`（改期）、`_rm`（DANGER）、`_projects`、`_labels`、
  `_token`／`_logout`（ai=False）。寫法與欄位跟 SYNOXPacks 的 `todo` pack 一樣。token 在保管箱（伺服器版每人一份）。
- `synox.packs.kit.redact_in_logs("/指令")`：那個指令後面的字在 log（SDK 的 `[ROUTE]` 行）換成 `***`。

## 未發佈（branch feat/pack-security）

### 新增
- **裝 pack 的五關**（docs/security.md）：pack.json v2 宣告檢查、ast 靜態掃描（沒宣告的能力拒裝、列檔名:行號）、
  `data/packs.lock`（載入時雜湊不符＝不載、通知擁有者一次）、AI 每次工具呼叫前驗參數（`agent/validate.py`）、
  工具結果包在每輪隨機的 `⟦SYNOX-TOOL-<nonce>⟧` 裡。
- `python -m synox install <檔.synoxpack> [--yes]`、`python -m synox packs status｜lock --approve <name>`；`Install-Pack.bat`；
  精靈完成頁可以勾「.synoxpack 點兩下就安裝」（HKCU，不要管理員）。
- `synox.sdk`：JSON 信封、`Pack.load`、`init_pack`、`zip_pack`；`synox-sdk init｜check｜zip`；`scripts/pack_zip.py`；docs/sdk.md。
- kind=cli：`{python}`、`{pack_dir}`、`{data_dir}`、`{user_data_dir}`、`{tg_id}` 代換（argv、env、cwd，每次呼叫照下令的人）；
  `cli.python`（絕對路徑｜venv）與 `runtime.python`／`python_posix`（相對 pack 資料夾）；最上層 `env`；cli pack 的面板（`web.api` → READ command）。
- `kind: mcp`（只登記）。

### 修正
- cli 的選填旗標：SDK `service.build_argv` 在後面的 `--k={v}` 沒填時會把前面已經填好的 `--a=1` 一起拿掉；loader 改用自己的 `build_argv`。

## branch feat/web-ui（已合併）

### 新增
- **Web UI**（`src/synox/web/`，標準函式庫、只綁 127.0.0.1、預設埠 8830）：`/web` 一次性登入連結（7 天、只能用一次）→ cookie session；
  對話頁（每人的對話紀錄、密文、每段 50 則；按鈕可以按、核准卡可以用）、工具頁（看得到的功能、每個指令一個執行框、pack 面板）、
  設定頁（AI 來源、`.synoxpack` 上傳／移除／重新載入、伺服器版帳號表、加密備份下載）。`/web_off` 關掉。埠開不起來 bot 照常跑。
- pack.json 的 `web.panel`／`web.api`、`pack.web_route()`；記帳的面板範例。
- 備份：`synox/backup.py`（data/ 的 zip，用保管箱主金鑰加密）。
- **伺服器版的成員**：AI（工具只有他能用的、每月額度 `ai_member_monthly_usd`、`/ai_budget`）、每人自己的提醒與排程。
  提醒 pack 的 access 改成 `member`（個人版不變）。

## branch feat/llm-and-modes（已合併）

### 新增
- **個人版／伺服器版**：`config.json` 的 `"mode": "personal" | "server"`（沒寫＝personal，行為跟以前一樣）。
  伺服器版：陌生人是訪客（GUEST），只看得到 `access: everyone` 的 pack；裝 SDK 的 `accounts`（`/me`、`/me_upgrade`、`/user_list`、`/user_role`）
  與 `limits`（`/limit_*`）；新的 `access: member`（筆記、記帳改用它）；`pack.store.of(user)` 每人一份 `data/users/<id>/<pack>.json.enc`，
  金鑰 HKDF(主金鑰, `user:<id>`)。營運者仍看得到（docs/security.md）。
- **精靈**：第一頁「這台給誰用？」＋「工程師？直接改 config.json」；AI 頁改成「預設：Claude（這台電腦登入的 Claude Code）」在上、
  「其他金鑰來源」（OpenAI／Anthropic API／Gemini／相容端點）在下、「先不用 AI」。
- **AI 來源經 ntu_easy_llm**（擁有者的套件，0.5.0 的 `ntu_easy_llm.agent`）：新 kind `openai`、`gemini`；`anthropic`、`openai_compat` 也改走它。
  選用相依（`pip install -e .[llm]`），沒裝時用 API 金鑰的來源會說怎麼裝，其他照常。
- `doctor` 印模式、也檢查每個人的加密檔。

### 拿掉
- `src/synox/llm/openai_compat.py`、`anthropic_api.py`（換成 `easy_llm.py`）。


## 0.1.0 — 2026-11-09

第一版，照設計規格 v0（`2026-11-09-synox-design.md`）。

### 有
- **底層**：ISDTeleKitSDK 0.2.1（vendor 在 `vendor/isdtelekit`，`scripts/vendor_sdk.py` 複製、`vendor/VERSION` 記版本與 commit）。
- **AI adapter**：`openai_compat`（OpenAI、Gemini 相容端點、公司閘道、Ollama）、`anthropic`、`claude_code`（本機 `claude -p`，走文字協定）、`fake`（劇本／示範）、`none`。
  不支援 tool-calling 的端點走 JSON-in-text 協定（容錯解析）。用量記在 `data/llm_usage.json`（`/ai_usage`）。
- **AI 助理**（只給擁有者）：指令樹 → 工具；`ai_decision` 唯一判斷；危險的動作送核准卡（✅／❌、10 分鐘、一次性、按下時再 authorize）；
  SKILL.md frontmatter 進系統提示、`skill_read` 讀全文；`/ai`、`/ai_usage`、`/ai_reset`；私訊直接打字＝`/ai`。
- **保管箱**：Fernet＋每檔 scrypt、`*.json.enc`；主金鑰用 Windows DPAPI 保護；壞檔／錯金鑰報錯不清空。
- **pack 載入器**：`packs/*`、`connectors/*` 的 pack.json；kind `python`／`cli`／`connector`；`pack.store`、`pack.path()`。
- **出廠 pack**：notes（`/note`…）、money（`/money`…，超過預算提醒）、remind（`/remind_*`）。connector 設計稿：Google 日曆、Notion、Todoist、Apple 提醒事項。
- **排程**：每 30 秒；提醒與 `/schedule_add`（`Node.wraps`，建立時 via=SCHEDULE、觸發時 via=ROUTINE）；一次性 `date=`。
- **安裝**：`Setup.bat` → `setup/bootstrap.ps1`（py → winget → embeddable zip）→ tkinter 精靈（token、配對碼、AI 來源＋測一下、捷徑、開機自啟）。
  `Start.bat`（看得到的最小化視窗）、`Stop.bat`、`Console.bat`。
- **doctor**：`python -m synox doctor [--offline]`。**打包**：`scripts/make_zip.py`。
- 測試：pytest，不連網、不開埠、不開 Telegram。

### 還沒有
見 README「還沒有」。重點：`/backup`、connector 實作、AI 長期記憶、非 Windows 安裝器、exe。
