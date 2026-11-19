# 交接：到另一台電腦做真機測試

開發用的電腦只用程式內的假傳輸測過 connector 和 Discord；這個資料夾是「帶到另一台可以上網的電腦，用真的帳號試」的全部東西。

> **交辦單**（檔名 `YYYYMMDD-HHMMSS-<主題>.md`）是給完全空白的 session（另一台電腦、docker、雲端）的：固定六段——狀態、前情提要、任務（含不要做的事）、安裝流程與環境確認、驗證清單集（merge 前由驗收者逐項確認）、交回。只讀那一份就能開工。

> 要接手**開發**（不是真機測試）的人或雲端 agent：入口在 [../HANDOFF.md](../HANDOFF.md)、流程在 [../development.md](../development.md)（兩份都只在 git clone／GitHub 上有）。

| 文件／程式 | 做什麼 | 先讀順序 |
|---|---|---|
| [real-service-testing.md](real-service-testing.md) | 準備那台電腦、Notion／Todoist／Google 日曆／Apple 提醒事項的憑證與設定、跑煙霧測試、錯誤排除、清理、回報格式、安全守則 | 1 |
| [discord-handoff.md](discord-handoff.md) | Discord 從零到上線：建 bot、intent、邀請、id、存 token、配對、config 範例（私訊型、頻道型、多 bot、頻道 AI）、排查、D1–D18 測試清單、已知限制 | 2 |
| [clean-machine-test.md](clean-machine-test.md) | 空白 Windows（VM 或新的使用者帳號）上裝 SYNOX：git clone 路線、安裝程式的建置（發佈機）與安裝、可勾選的步驟與預期、失敗時回報什麼 | 另一條線（安裝，QL4） |
| [container-verification.md](container-verification.md) | 容器隔離（podman／Docker）與 Linux 沙盒（bwrap／systemd）的真機驗證：給那台 Claude 的 prompt、探針 pack、C／M／B 檢查清單（每項：做什麼、預期、失敗代表什麼） | 另一條線（Linux 實驗室） |
| [sandbox-real-machine.md](sandbox-real-machine.md) | 帶警告的 pack（ADR 0041 S1／S2／S4）與沙盒後端的真機驗證：背景、已做／沒做／沒驗證、假 pack 與 config、逐步驗證、驗收標準、一件一檔的回報格式、不要做的事；清單在 [../testing/sandbox-real-machine-checklist.md](../testing/sandbox-real-machine-checklist.md)，待決定的題目在 [open-questions/](open-questions/) | 另一條線（另一台電腦） |
| [20261119-134608-sandbox-real-machine.md](20261119-134608-sandbox-real-machine.md) | **交辦單**（六段：狀態、前情提要、任務、安裝流程與環境確認、驗證清單集、交回）：上一列的沙盒真機驗證整理成給空白 session 的版本，含測試基準數字、`warnbox` 的 `net` 指令、merge 前的 V1–V24 | 另一條線（另一台電腦；先讀這份） |
| [20261119-134609-core-real-device-checks.md](20261119-134609-core-real-device-checks.md) | **交辦單**：pack 警告（H1–H14）與外觀套用（T1–T12）兩份真機清單——哪些雲端 session 能做、哪些**僅擁有者本機**、假包怎麼做、merge 前的 V1–V20 | 另一條線（雲端先做終端機那半，擁有者本機做畫面） |
| [20261119-160000-local-llm-gateway-integration.md](20261119-160000-local-llm-gateway-integration.md) | **交辦單**：讓 SYNOX 接上外部的本地 LLM 閘道（llmop）的 H-S1～H-S3——可選 API key 標頭、確認標頭與串流、可選的 SDK adapter | 另一條線（開發；等 llmop 實測通過再做） |
| [20261119-153430-mascot-states-wiring.md](20261119-153430-mascot-states-wiring.md) | **交辦單**：外觀包的四個吉祥物狀態——先盤點各畫面用到哪些（盤點表放 `docs/design/`），再把狀態接上 AI 實際發生的事（等回覆、工具完成、核准卡）與空狀態／錯誤頁；沒有外觀包時一律用 SYNOX 預設；merge 前的 V1–V23 | 另一條線（開發；前端） |
| [20261119-153431-windows-isolation-stage0-1.md](20261119-153431-windows-isolation-stage0-1.md) | **交辦單**：Windows 隔離（ADR 0022 §6 的延伸）的階段 0（禁寫 `.git/`、`.vscode/` 等，核心與工具庫兩層）與階段 1（環境變數白名單、保護等級偵測與顯示），加上階段 1.5～3 的設計草案與實測清單；AppContainer／MXC 的實作另開單；merge 前的 V1–V24 | 另一條線（開發；沙盒） |
| [open-questions/](open-questions/) | 要擁有者決定的題目（一件一檔）：S3 沒有隔離時預設不執行、S5 要求宣告 `runtime.container`、驗證機能不能拉官方 Python 映像、能不能跑 MXC 探針、能不能裝 bubblewrap／podman／Docker Desktop、常駐小吉祥物預設開或關、環境變數白名單怎麼上線 | 開工前看 |
| [2026-11-14-session-handoff.md](2026-11-14-session-handoff.md) | 2026-11-13～14 合進 `dev` 的東西、線上頁面與本機副本、SYNOX_Libs 的衣櫃分支、怎麼跑測試（Linux 基準線 14 個失敗）／打包／發版、沒在 Windows 上試過的清單、要擁有者決定的事 | 另一條線（工作交接；只在 git clone／GitHub 上有） |
| [../release-playbook.md](../release-playbook.md) | 發版與更新的手冊：在 Windows 上先測 `Update.bat`（`scripts/make_update_testkit.py` 做測試包、`Update.bat -FromZip`、`-Rollback`）、發 SYNOX／工具庫、改下載連結、出事怎麼退、給新 session 的檢查表 | 另一條線（發版、更新） |
| [`scripts/smoke_real.py`](../../scripts/smoke_real.py) | 煙霧測試：用各 connector 自己的程式逐一試唯讀操作；`--write` 才做一個建立後立刻刪掉的小寫入（要輸入 yes）；最後印一段可貼進部署測試板的摘要 | 照第 1 份第 3 節跑 |

最短路徑：

```
git clone https://github.com/ChouYangEn0401/SYNOX.git && cd SYNOX && git checkout dev
Setup.bat                                             （或自己建 .venv、pip install -e .）
Console.bat → /notion_token、/todoist_token、/gcal_setup …（存憑證）
.venv\Scripts\python.exe -m synox connect apple-reminders   （Apple）
.venv\Scripts\python.exe -m synox discord token        （Discord）
.venv\Scripts\python.exe scripts\smoke_real.py         （唯讀測試，把最後那段貼進部署測試板）
```

三條守則：token 不貼到任何聊天、`config.json` 和 `data` 不進 git、測試用專用帳號。
