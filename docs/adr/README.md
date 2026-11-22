# 架構決定（ADR）索引

一件決定一個檔。每份開頭有「日期」「狀態」；**兩邊對不上時以程式為準**，並順手把 ADR 的狀態改對。

## 什麼時候要寫 ADR

改到下面任何一項，先寫（或改）一份 ADR，再寫程式：

- **安全邊界**：權限的交會點（`policy.decide`／`ai_decision`）、核准卡、驗證碼、五關、信任層級、沙盒、簽章、網頁綁定與登入。
- **對外的合約**：`pack.json` 欄位、SDK 介面（`SDK_VERSION`）、子程序的環境變數與 JSON 信封、網頁 API 的合約文件（`runtime-api.md`、`apps-api.md`）。
- **資料格式**：`config.json`、`data/` 底下的檔案格式、要轉換舊資料的改動。
- **AI 的行為規則**：提示的分層、完成宣稱檢查、工具挑選、context 預算這類「harness」的規則。
- 會讓使用者多做事、或改變「什麼會離開這台電腦」的改動。

只是修錯、重構、加測試、改文件：不用寫 ADR，CHANGELOG 寫一行就好。

## 編號與格式

- 檔名 `NNNN-<英文短名>.md`，四位數、**接著目前最大的號碼往下編**（現在最大是 0046，下一份是 **0047**）。
  號碼不重用、不改號；撞號時晚進來的那一份改號，並在兩份與本索引註明（例：0024 原本叫 0023）。
- **0032 是空號**：當初留給「給 AI 的結構化結果與核准後叫醒」的實作分支，那個分支沒有另寫 ADR，介面記在 [0038](0038-wake-ai-after-card.md)。不要拿 0032 給新的決定。
- 開頭固定幾行：`# ADR NNNN：<標題>`、`- 日期：YYYY-MM-DD`、`- 狀態：提案｜已採用｜已取代（被 NNNN）｜作廢`，有實作分支就寫分支名。
  內文建議：背景 → 決定 → 為什麼不選別的 → 已知代價與不做 → 測試怎麼守。
- 狀態變了（提案 → 已採用、有了程式）就改那一行，並在本索引同步。
- 公開 repo：ADR 裡不放擁有者的原話、私人專案名或本機路徑；「來源是維護者的私有文件」這種說法可以。

## 全部 ADR

狀態欄：**已採用**＝有程式、照它做；**提案**＝契約定稿或還在討論、還沒有程式（或只有一部分）。

| # | 標題 | 狀態 |
|---|---|---|
| [0001](0001-runtime-loop-heartbeat-mother-session.md) | Runtime loop、心跳、常駐助理（母 session）與 soul.md | 已採用 |
| [0002](0002-soul-md-in-chat-assistant-prompt.md) | soul.md 放進對話助理的系統提示（唯讀、包在分隔符裡） | 已採用 |
| [0003](0003-distribution-git-clone-and-installer.md) | 發佈方式（git clone＋安裝程式）、工具庫放哪裡、乾淨安裝（沒有 hidden dependency） | 已採用（安裝程式還沒在空白電腦上實測） |
| [0004](0004-activator-event-driven-rules.md) | 連動（activator）：任務做完就觸發下一件，防無限連動 | 已採用 |
| [0005](0005-soul-ledger-memory-provenance-review.md) | soul 帳本：助理筆記的來歷、有疑慮先問、取代不刪除、整理與遺忘 | 已採用 |
| [0006](0006-keep-awake-screen-may-sleep.md) | 保持清醒：電腦不睡、螢幕可以熄 | 已採用 |
| [0007](0007-local-llm-platform.md) | 本地模型是內建能力（`llm.kind = "local"`） | 已採用 |
| [0008](0008-completion-guard.md) | 虛假完成檢測：說做好了卻沒有成功的工具呼叫＝不放行 | 已採用 |
| [0009](0009-leaked-tool-call-recovery.md) | 救回文字裡洩漏的工具呼叫、剝除思考段 | 已採用 |
| [0010](0010-stop-words.md) | 停止詞 | 已採用 |
| [0011](0011-cannot-do-exit.md) | 「做不到」的出口 `system__cannot_do` | 已採用 |
| [0012](0012-repeat-failure-and-step-limit-summary.md) | 同一個呼叫連續失敗就停、步數用完請 AI 總結 | 已採用 |
| [0013](0013-tool-scenario-descriptions.md) | 工具說明精簡化：`commands[].ai.scenario` | 已採用 |
| [0014](0014-per-turn-tool-cap.md) | 每輪工具數上限與「auto」的共用判斷 | 已採用 |
| [0015](0015-context-budget.md) | Context 預算：估算與分級截斷 | 已採用 |
| [0016](0016-tool-result-cap.md) | 工具結果上限 | 已採用 |
| [0017](0017-tail-rules-and-time-last.md) | 系統提示尾端重注入本輪規則、時間放最後一行 | 已採用 |
| [0018](0018-goal-recitation.md) | 多步時覆誦目標 | 已採用 |
| [0019](0019-qwen3-no-think-sampling.md) | Qwen3 不思考模式的取樣參數（只有 Ollama） | 已採用 |
| [0020](0020-eval-missing-tool-param-and-metrics.md) | 評測擴充：missing_tool／missing_param 與指標 | 已採用 |
| [0021](0021-vlm-vision.md) | 看圖（VLM）：只加 provider 能力，harness 不分叉 | 已採用（沒在真的 VLM 上跑過） |
| [0022](0022-ecosystem-bridge-and-sandbox.md) | 接上其他生態、npm 工具、技能市集、隔離與預覽 | 已採用（附修正 O1；目錄簽章還沒做） |
| [0023](0023-updates-and-hotfixes.md) | SYNOX 自己更新：檢查更新、`synox update`、hotfix、退回 | 已採用 |
| [0024](0024-tool-apps-services.md) | 工具服務：每個工具自己的完整網頁，要用才開 | 已採用（真機關卡 G1 待測） |
| [0025](0025-guard-core-and-stepup.md) | 門禁核心（來源、輸入、稽核）與手機驗證器 | 已採用 |
| [0026](0026-remote-tool-apps.md) | 在手機上打開工具的畫面（臨時通道） | 已採用（真的通道與手機實測待做） |
| [0027](0027-multi-file-python-packs.md) | kind=python 的工具可以是多個檔（`python.package`） | 已採用 |
| [0028](0028-pack-signatures-official-badge.md) | 工具的簽章與「官方」標章、沒經過安裝頁不載入、面板隔開 | 已採用（官方公鑰還沒貼進程式） |
| [0029](0029-reminder-delivery-on-notify-hub.md) | 提醒必達：資料格式、排程回執、送達與重試、提醒視窗與哨兵 | 已採用（W1、W2 隨 0.2.1-alpha.1 發佈） |
| [0030](0030-tool-registration-index.md) | 工具登記與索引（`agent` 區塊、`requires.packs`／`requires.system`） | 已採用 |
| [0031](0031-soul-habits-and-prefs.md) | 習慣與規則寫在 soul.md；工具照宣告拿值；AI 只能提議 | 已採用 |
| 0032 | （空號，見上面「編號與格式」） | — |
| [0033](0033-work-protocol-work1.md) | 工作協定 `work/1`：工具的七個動作 | 提案（還沒有程式） |
| [0034](0034-pack-agent-work.md) | pack.json 的 `agent.work` | 提案（還沒有程式） |
| [0035](0035-workmode-core.md) | 工作模式的核心（`workmode.py`）與在 SYNOX 的掛點 | 提案（還沒有程式） |
| [0036](0036-triangle-review.md) | 三角審查：執行者、挑錯者、驗證者 | 提案（還沒有程式） |
| [0037](0037-approval-cards-upgrade.md) | 核准卡升級：檢查、之前→之後、多動作、編號、收回、過期 | 提案（還沒有程式） |
| [0038](0038-wake-ai-after-card.md) | 核准卡執行完叫醒 AI | 第一段已採用（`agent/wake.py`）；後兩段提案 |
| [0039](0039-local-project-link.md) | 本機專案直接接（`link`、synox-agent 結構） | 提案（還沒有程式） |
| [0040](0040-notify-lanes.md) | 通知分流：主線與安靜線、太久沒處理才升級 | 提案（還沒有程式） |
| [0041](0041-pack-warnings.md) | pack.json 的標記警告（`warnings`）：每個看得到工具的地方都顯示、第一次啟用要確認 | 已採用 |
| [0042](0042-theme-tokens-single-source-and-forward-compat.md) | 外觀的顏色只宣告一次（contract）、舊外觀包遇到新 token 不會壞、套用時列逐項檢查 | 已採用 |
| [0043](0043-version-order-and-upgrade-matrix.md) | 版本號的排序（SemVer）、升級矩陣、錯版只能往前補、不相容的工具新版不算「有新版」 | 已採用（預覽版的通道 2026-11-19 決定，見 0045） |
| [0044](0044-data-versions-and-migrations.md) | 每份持久化資料都有版本號、逐版連續遷移；工具的 `data_schema` 與 data-adapter 契約；不服務降級 | 提案（有程式；待擁有者確認備份份數、cli 契約細節） |
| [0045](0045-update-channels.md) | 更新檢查同時顯示正式版與測試版（SemVer 排序）、更新通道 `updates.channel`（預設只提醒正式版）；修訂 0023 U3 | 已採用 |
| [0046](0046-llm-source-tree-and-waterfall.md) | AI 來源改成分步選擇（ntu_easy_llm 0.6 的來源目錄、`kind: "source"`）、錯誤照種類說人話、可選的備援 `llm.waterfall`（ask＝按鈕卡） | 已採用（router 與新 adapter 合併後待實測） |

工具庫（SYNOX_Libs）自己的決定（工具庫與 SDK 相依）在那個 repo 的 `docs/adr/`，編號另計。
