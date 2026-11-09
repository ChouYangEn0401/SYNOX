# Changelog

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
