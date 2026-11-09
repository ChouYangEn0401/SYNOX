# Changelog

## 未發佈（branch feat/sdk-p6-upgrade）

### 新增
- **pack 升級**：同名的 pack 再裝＝升級（以前是拒裝、要先移除）。安裝報告多一段「改了什麼」：新增／移除的 command；
  effect 變寬、新增 WRITE／DANGER command、capabilities 新增、執行方式（runtime、cli.argv…）或 auth 改動、多要密鑰、access 變寬、
  新加面板一律紅字。版本要是 semver 且比裝著的新；一樣或比較舊會明講並拒絕，除非明確選降級（網頁勾選框、`--allow-downgrade`）。
  確認後舊資料夾搬到 `packs/_removed/<name>-<版本>-<時間>`（旁邊留舊的鎖）、`packs.lock` 換新、重新載入。Web UI 設定頁按「確認升級」；
  `python -m synox install <檔> --yes` 自動走升級。資料不在 pack 資料夾，不受影響；資料 schema 升級由 pack 自己負責（pack-format.md「升級」）。
- `python -m synox packs rollback <name>`：`_removed` 裡最近一份舊版搬回、鎖改回當時的（檔案對不上就不鎖）；現在那份搬到 `_removed`。
- 移除的資料夾名多了版本（`<name>-<版本>-<時間>`），旁邊留 `.lock.json`，移除之後也能 rollback。測試 `tests/test_upgrade.py`（22 個）。

## 未發佈（branch feat/sdk-p5-envs）

### 新增
- **依賴與環境自動建置**（SDK P5，`src/synox/packs/envs.py`）：kind=cli 的 `runtime.python` 可以寫 `"auto"`——安裝時在
  `data/envs/<pack>/venv` 建 venv，`pip install --no-deps --only-binary=:all:` 裝 `requires.pip`（只收 `名字==版本`，其他寫法 pack.json 不合）；
  新的 `runtime.node`（路徑或 `"auto"`）與代換 `{node}`：`auto`＝`npm ci --ignore-scripts` 照 pack 的 `package-lock.json` 裝進
  `data/envs/<pack>/node_modules`（子程序拿到 `NODE_PATH`）。pack 資料夾不寫任何東西。
- 安裝報告（終端機與網頁）在第 2 關之後多一段「🧱 要建環境：Python venv、裝 N 個套件：名稱 版本」；按確認、裝好之後才建
  （JobRunner，整個最多 10 分鐘，log 進 `data/job_logs/`）。失敗不卡安裝：pack 已裝、狀態 `missing`，doctor 標「環境沒建好」並說原因；
  沒網路說「連不上網路」、找不到版本說是哪個套件。網頁裝完會在背景建，好了／失敗都通知擁有者。
- `python -m synox packs env rebuild <name>`：重建。`requires.pip`／`package-lock.json` 改了，doctor 會說環境對不上、要重建。
  系統沒有 node（而 pack 用 `{node}`／`runtime.node`）＝doctor 說缺、不載入。
- `Builder` 是可替換的介面（`envs.set_factory`；預設 `VenvBuilder`）。`node` 成為保留的代換名（欄位不能叫 node）。
  備份略過 `data/envs/`（可以重建）。測試 `tests/test_envs.py`（36 個；假的 JobRunner 與 which，不真的 pip／npm、不連網）。

## 未發佈（branch feat/sdk-p2-secret）

### 新增
- **pack 的 secret**（pack.json `auth.fields[]`，`auth.type` 是 `token`／`file`；oauth 這一版不做）：
  `{"name", "label", "secret": true, "env": "TODOIST_API_KEY", "kind": "text|file", "required"}`。
  - 存保管箱 `pack_secrets`（鍵 `packs/<pack>/<field>`）；伺服器版每人一份（`vault.for_user`）。
  - Web UI 工具頁每個 pack 的「🔌 連接」：secret 用密碼框、**永遠不回傳值**（只回「有填」與最後 4 碼）、留空沿用原值、`kind: file` 可上傳；
    `GET/POST /api/pack-secrets/<name>` 走既有的 CSRF 與 Origin 檢查；個人版只有擁有者、伺服器版每人設自己的。Telegram 不收。
  - `python -m synox connect <pack>` 對這類 pack 寫同一份（secret 用 getpass、file 問路徑）。
  - kind=cli：只有寫了 `env` 的欄位放進子程序環境（同時列進 `keep_env`），**絕不進 argv**；必填的沒填＝回「到網頁工具頁按『連接』」、不執行。
  - kind=python：`pack.secret(name, user=None)`（伺服器版一定要給 user；沒宣告的名字丟 KeyError）。掃描器把 `pack.secret` 列成「讀使用者填的 secret」，不算 capability。
  - 第 4 關：AI 帶的欄位值等於（或夾著 8 字以上的）這個人已存的 secret ＝拒，不執行。
  - 工具頁狀態照這個人存了沒：「要先設定」→「已連接」；doctor 列出還缺哪些（伺服器版看擁有者那一份）。
  - pack.json 第 1 關檢查 `auth.fields`（名字、env、kind、secret／required 是布林）與 `auth.managed`（`synox`｜`pack`）。
- 內建 connector（notion／todoist／google-calendar／apple-reminders）沒呼叫 `pack.secret`，不算 SYNOX 收：照舊用自己的 token 指令，行為不變。
- 測試 `tests/test_sdk_p2_secret.py`（21 個；假的本機命令列程式，不連網、不開埠）。

## 未發佈（branch feat/sdk-p0-fixes）

### 修正
- **AI 呼叫 cli pack 的指令拿到空結果**（G3）：經 AI 呼叫時改成同步跑完，結果（包每輪的 nonce 分隔符）交回 AI 轉述；
  人自己打的指令照舊在背景跑、直接回覆。`background: true` 的指令不變（AI 只知道「開始了」）。
- **cli pack 拿不到任何密鑰**（G1）：SDK 的 `clean_env` 會拿掉 `*_TOKEN`、`*_API_KEY`… 的環境變數，loader 沒傳 `keep_env`。
  現在把 `requires.env`（之後 `auth.fields[].env` 也算）列的名字傳成 `keep_env`，只放行這些；其他像密鑰的照樣拿掉。vendor 沒改。

### 新增
- `pack.json` 的 `requires.synox`（例如 `">=0.3"`、`">=0.3,<1.0"`）：寫錯＝pack.json 不合；版本不合＝不載入（狀態 `incompatible`，
  網頁「SYNOX 版本不合」），doctor、`python -m synox packs status`、安裝報告說要哪一版、這台是哪一版、該怎麼做。
- `fields[].kind` 多了 `int`、`number`、`bool`、`choice`（配 `choices`）：AI 看到的 schema 仍是字串；交給程式前照 kind 檢查
  （不合回人話、不執行），並整理成固定寫法（bool → true/false、去千分位、choice 換成宣告的拼法）。`choices` 比對改成不分大小寫。
- `requires.env` 的名字要是合法的環境變數名（清單或物件都收）。測試 `tests/test_sdk_p0.py`（31 個；假的本機命令列程式，不連網、不開埠）。

## 未發佈（branch feat/connector-notion）

### 新增
- **Notion connector 接上了**（`connectors/notion`，`kind: python`、`capabilities: ["network"]`）：`/notion` 搜尋、`/notion_read`、
  `/notion_dbs`、`/notion_rows`、`/notion_row`（資料庫加一列，`props=欄位:值; …`）、`/notion_new`、`/notion_append`、
  `/notion_set`（DANGER：AI 要做先出核准卡）；`/notion_token`（私訊、不給 AI；token 進保管箱 `data/notion.json.enc`）、
  `/notion_status`、`/notion_logout`。Notion REST `2025-09-03`，只用 requests；log 裡長得像 Notion token 的字遮成 `ntn_***`。
  測試 `tests/test_notion.py` 用假的 HTTP 傳輸，五關各走一次。
## 未發佈（branch feat/connector-todoist）

### 新增
- **Todoist connector 接上了**（`connectors/todoist`，從設計稿變成 `kind: python`＋`capabilities: ["network"]`）：Todoist API v1、個人 API token；
  `/todoist`（加）、`_list`（today｜overdue｜#專案｜@標籤）、`_done`、`_due`（改期）、`_rm`（DANGER）、`_projects`、`_labels`、
  `_token`／`_logout`（ai=False）。寫法與欄位跟 SYNOXPacks 的 `todo` pack 一樣。token 在保管箱（伺服器版每人一份）。
- `synox.packs.kit.redact_in_logs("/指令")`：那個指令後面的字在 log（SDK 的 `[ROUTE]` 行）換成 `***`。

## 未發佈（branch feat/connector-apple）

### 新增
- `connectors/apple-reminders-caldav` 從設計稿變成真的 pack（`kind: python`、`capabilities: ["network"]`，只用 requests＋標準函式庫）：
  `/applerem`、`/applerem_lists`、`/applerem_add`、`/applerem_done`、`/applerem_status`、`/applerem_logout`；自己解析／產生最小的 VTODO。
  研究結論：iCloud 升級過（iOS 13 起）的提醒事項 Apple 不經 CalDAV 提供；建議 iPhone 接別家 CalDAV 帳號（見該資料夾 README）。
- `python -m synox connect <pack> [--user ID] [--clear]`＋`Connect-Apple.bat`：照 pack.json 的 `auth.fields` 把帳號存進保管箱
  （密碼用 getpass，不經聊天、不進 log）。

## 未發佈（branch feat/connector-gcal）

### 新增
- **Google 日曆 connector**（`connectors/google-calendar`，kind=python、`capabilities: ["network"]`）：REST 直連 Calendar API v3，只用 requests。
  `/gcal`、`/gcal_today`、`/gcal_week`、`/gcal_list`、`/gcal_rm`（DANGER）跟 SYNOXPacks 本機 `calendar` pack 同名同欄位；
  連接 `/gcal_setup`、`/gcal_code`、`/gcal_token`、`/gcal_logout`、`/gcal_status`（前四個 ai=False）。
  OAuth：電腦版用戶端＋PKCE＋state，loopback 轉址但**不開 listener**（使用者貼網址列回來）；憑證全在保管箱。測試 `tests/test_gcal.py`（假 HTTP）。

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
