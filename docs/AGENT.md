# SYNOX — AGENT.md

給 AI 與接手的人看的地圖。設計規格（合約）在擁有者的 ClawBot repo：`docs/plans/2026-11-09-synox-design.md`；
給人看的在 [../README.md](../README.md)。

## Commands

- 安裝（開發）：`py -3.11 -m venv .venv` → `.venv\Scripts\python.exe -m pip install -e .[dev]`
- 測試：`.venv\Scripts\python.exe -m pytest -q`（約 10 秒；不連網、不開埠、不開 Telegram、不叫 `claude`）
- 終端機：`.venv\Scripts\python.exe -m synox console`（`--llm fake` 換假 AI；沒有 config.json 用示範設定）
- 健康檢查：`.venv\Scripts\python.exe -m synox doctor --offline`
- 重新 vendor SDK：`.venv\Scripts\python.exe scripts\vendor_sdk.py`；打包：`scripts\make_zip.py`
- 主控台是 cp950：跑 Python 前 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`

## Map

| Path | Role |
|---|---|
| `vendor/isdtelekit/` | ISDTeleKitSDK 的**原樣**複製（版本與 commit 在 `vendor/VERSION`）。不要改；要不同的行為就在 `src/synox` 寫轉接 |
| `src/synox/__main__.py` | `python -m synox run｜console｜wizard｜doctor｜stop` |
| `src/synox/app.py` | `build(config, home=, adapter=, vault=)`：SDK `build_app` → basics/help → `packs.load_all` → `agent.install` → `schedule.install` |
| `src/synox/config.py` | `SynoxConfig`＝SDK `BotConfig`＋`llm`／`vault`／`packs`；路徑相對 SYNOX 資料夾（`ROOT`） |
| `src/synox/llm/` | `base.py`（`ChatAdapter`、`Message`、`Reply`、`ToolCall`、`ToolSpec`）、`openai_compat`、`anthropic_api`、`claude_code`、`fake`、`textproto`、`factory.make_adapter` |
| `src/synox/vault/` | `vault.py`（Fernet＋每檔 scrypt、`*.json.enc`）、`keyring.py`（DPAPI 包住主金鑰 `data/.synox.key`） |
| `src/synox/packs/` | `manifest.py`（pack.json 檢查）、`loader.py`（掃 `packs/`＋`connectors/`、`Pack`／`PackStore`）、`kit.py`（照位置填的指令） |
| `src/synox/agent/` | `tools.py`（葉節點 → ToolSpec）、`loop.py`（`ai_decision`、一輪、用量）、`capture.py`、`approve.py`（核准卡）、`skills.py` |
| `src/synox/schedule/` | `store.py`、`runner.py`（30 秒、via=ROUTINE）、`commands.py`（`/remind_*`、`/schedule_*`） |
| `src/synox/wizard/` | `pages.py`（tkinter 畫面）、`logic.py`（寫 config、金鑰進保管箱）、`telegram_probe.py`（getMe、配對碼）、`shortcuts.py` |
| `src/synox/doctor.py` | 健康檢查（不改任何檔、不產生金鑰） |
| `packs/notes`、`packs/money`、`packs/remind` | 出廠 pack；remind 的程式在 `synox/schedule` |
| `connectors/*` | `kind: connector` 的設計稿（只有 pack.json、SKILL.md、README；沒有連網程式） |
| `Setup.bat`、`setup/bootstrap.ps1` | 一鍵安裝；`Start.bat`／`Stop.bat`／`Console.bat` |
| `tests/` | pytest；`conftest.py` 的 `make_bot` 用真的 packs＋真的 Vault＋`FakeAdapter`＋SDK `BotHarness` |

## Invariants

SDK 的 12 條照用（只 vendor 了套件、沒有 vendor 文件；原文在 ISDTeleKitSDK repo 的 AGENT.md：唯一的 `authorize()`、
權限沿樹只收緊、指令名由路徑產生、按鈕綁節點、核心不認識 Telegram、等待都有期限、表單、🔐 fail closed、
jsonstore、外部程式經 JobRunner、回覆走 handler 的 api、角色階梯是參數）。SYNOX 多的（spec §7）：

1. **AI 能不能用一個節點只有一個判斷**：`agent/loop.py` 的 `ai_decision(registry, user, node)`。工具清單、每次呼叫、
   排程裡包的指令都問它。`effect=DANGER`（含 `Node.effect_of` 算出來的）、要 /sudo、有驗證碼欄位的 → 一律核准卡。
   驗證碼欄位不出現在工具 schema（`tools.schema` 跳過 `fresh_code`），核准後由人那一端照常問碼。
2. **adapter 只會聊天**：`llm/*` 不 import registry、不拿 Telegram api。換 LLM 只改 `config.json` 的 `llm`。
3. **pack 不互相 import、不自己開檔**：資料經 `pack.store`（vault → 密文）；自己的檔案經 `pack.path()`。共用的放 `synox`（例如 `synox.packs.kit`）。
4. **安裝不需要使用者打任何指令**：Setup.bat 之後全部在視窗裡點。
5. **沒有隱藏的背景程式**：Start.bat 開看得到的（最小化）視窗；開機自啟是使用者在精靈裡勾的。
6. **.bat 只用 ASCII＋CRLF；.ps1 UTF-8 有 BOM＋CRLF；requirements.txt 只用 ASCII**。`.gitattributes` 的萬用規則放第一行（後面的規則才蓋得過它）。
7. **測試不綁埠、不連網、不開 Telegram、不開 `claude`**；requests 用假的 session，`claude` 用假的 runner/which。
8. **repo 裡沒有真名、token、Telegram id 或個人資料**；`config.json`、`data/` 在 `.gitignore`。範例一律佔位字。

另外：
- pack 的群組由 loader 依 pack.json 定義，`access: owner`（預設）＝整組 `owner_only`。v0 的 AI 也只給擁有者（`AgentFallback.accepts`）。
- 保管箱解不開時**丟 VaultError，絕不當成空的再蓋過去**；金鑰檔不見而 `data/` 已有 `*.json.enc` 時不產生新金鑰。

## 跟 SDK 的差異／轉接（vendor 沒有改過）

| 什麼 | 為什麼 |
|---|---|
| `synox.packs.kit.command`（照位置填）而不是 SDK `Forms.leaf` | SDK 的 `parse_fields` 把第一個 `key=` 之前的字全給第一個欄位：`/money 120 午餐` 會變成 amount="120 午餐"。kit 照位置分配，最後一個欄位吃剩下的；仍設 `node.fields` 給 AI schema。缺必填回用法、不開問答；不收 `fresh_code` 欄位（要碼的指令用 SDK Forms） |
| `llm/claude_code.py` 直接 `subprocess.run`，不經 `JobRunner`（SDK invariant 10） | adapter 不拿 app（invariant 2）。有 argv 陣列、`CREATE_NO_WINDOW`、逾時；沒有 Job Object 收程序樹 |
| 核准卡的節點叫 `agent.ai_approve`（`/ai_approve`），不是 `agent.approve` | 群組 `agent` 是 bare（葉節點直接用自己的名字：`/ai`、`/ai_usage`），`approve` 會變成 `/approve`，跟 AI 無關的名字容易撞名 |
| 排程（`synox/schedule`） | SDK D6 沒有排程。照 ClawBot `routines/runner.py`，只做每天 HH:MM 與某一天一次；沒有「連續失敗自動暫停」 |

## Known limitations / next steps

- AI 對話紀錄只在記憶體（每個聊天最近 6 輪），重開就忘。
- 經 AI 呼叫、會丟到 `app.tasks` 背景回覆的指令（例如 kind=cli 的 service 指令）：AI 拿到的工具結果是空的，真正的回覆之後直接送給使用者。
- 核准卡按下執行的結果直接給使用者，只在 AI 的紀錄留一句「已執行」，不會自動再開一輪讓 AI 接著做。
- `Setup.bat` 的完整安裝路徑（winget、embeddable zip）沒有在任何一台陌生電腦上跑過；精靈的畫面沒有自動化測試（只測了 logic／probe／shortcuts）。
- `/backup`（spec §6）沒做。connector 只有設計稿。
- 文字協定一次只解析一個工具呼叫。
