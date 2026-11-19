# SYNOX 交接入口：給新開發者與雲端 agent

這一頁是給「只拿到 GitHub 上這個 repo」的人或 AI（例如在 Linux 容器裡的雲端 Claude Code session）的入口：
讀完知道 SYNOX 是什麼、程式怎麼分層、東西放在哪、哪些地方不能亂動，然後照連結去做事。
**不需要任何私人資料、金鑰或帳號**就能讀懂、跑測試、開發工具、改核心。

> **新來的先讀這 3 份**（照順序）：
> 1. 這一頁（全貌、目錄地圖、ADR 摘要、雲端注意事項）；
> 2. [development.md](development.md)（從零開始：clone → 建環境 → 跑測試 → 不用金鑰的開發設定 → 開分支 → 交 PR；開發 pack 的流程；改核心的規則）；
> 3. [AGENT.md](AGENT.md)（程式地圖到模組與函式、**不能破壞的規則（invariants）**、已知限制）。
>
> 碰到安全相關的地方，再讀 [security.md](security.md)。全部文件的目錄：[README.md](README.md)。
> 文件跟程式對不上時，**以程式為準**，並順手改文件（在 PR 裡寫出來）。

---

## 1. SYNOX 是什麼

一個**住在使用者自己電腦上的 AI 助理**（Python 3.11+，Windows 為主，程式本身跨平台）。使用者從 Telegram、Discord 私訊、
這台電腦的網頁介面（或終端機）跟它講話；它有一棵**指令樹**（`/help` 看得到的每個指令），接了 AI 之後 AI 也只能透過同一棵樹做事，
危險的動作一律先送**核准卡**給人按。設定、金鑰、資料都在本機，筆記類資料用保管箱加密。

- **出廠不帶工具**：記帳、筆記、接外部服務的工具都在另一個公開 repo **SYNOX_Libs（工具庫）**，一個工具一個 `.synoxpack`，使用者挑來裝。
  SYNOX 本體只有系統指令（提醒、排程、說明、教學、帳號…）。
  要在工具庫開發新工具：讀工具庫 repo（SYNOX_Libs，網址在 [../README.md](../README.md) 頂端）的 `docs/HANDOFF.md`。
- **底層 SDK**：`vendor/isdtelekit/` 是上游 SDK 的原樣複本（指令樹、dispatcher、表單、Telegram 通道、角色），**不改它**，差異在 `src/synox/` 寫轉接。
- **授權**：核心 AGPL-3.0-or-later；工具 SDK 與範例 Apache-2.0（[../LICENSING.md](../LICENSING.md)）。
- **現況**：0.2.1 的預覽版（tag 已到 `v0.2.1-beta.2`，發佈分支 `release/0.2.1`）。**`dev` 上 `pyproject.toml` 的版本號可能比 release 分支或最新的 tag 舊**（升號是在 release 分支上做、之後才合回 `dev`）；要知道發到哪一版，看 `git tag` 與 release 分支，不要照 `dev` 的版本號推斷。很多東西只在自動測試裡跑過、沒在真的 Windows／真的服務上驗證，README 頂端的 alpha 說明是準的。

## 2. 架構大圖

```
  人                         入口（channel）                         核心
 ─────                      ─────────────────                       ─────
 Telegram  ──► vendor SDK 的 poller ─┐
 Discord   ──► src/synox/discord ────┤      ┌──────────── policy.decide()：權限的唯一交會點 ────────────┐
 網頁介面  ──► src/synox/web（127.0.0.1）┼──► SDK dispatcher ──► 指令樹（Node）──► handler
 終端機    ──► synox console ─────────┘      │   系統指令（remind、schedule、help、tutorial…）
                                             │   pack 的指令（loader 依 pack.json 掛上去）
                                             │
 自由文字（沒有 /）────────────────────────► AI：agent/loop.py（AgentLoop）
                                             │   工具＝指令樹的葉節點；能不能用只問 ai_decision()
                                             │   DANGER／要驗證碼 → 核准卡（agent/approve.py）→ 人按 ✅ 才執行
                                             │   LLM 介面卡 llm/*：claude_code｜local｜openai｜anthropic｜gemini｜openai_compat｜fake｜none
                                             │
 背景（不經人）  runtime/loop.py（RuntimeLoop）：心跳、常駐助理、排程、連動、工具健康、更新檢查
                 notify/：通知中心（同一則送網頁、Telegram、Discord，送達確認與重試）
 資料            vault/：保管箱（Fernet；主金鑰 Windows 用 DPAPI 包、其他平台明文檔）　data/：全部執行期資料
```

組裝順序在 `src/synox/app.py` 的 `build()`：SDK `build_app` → `policy.install` → 通知中心、門禁 → 系統指令 → `loader.load_all`（pack）
→ `agent.install` → Discord → runtime → 工具健康 → 排程 → 送達層 → 更新 → `web.install`。

### 幾個一定要懂的概念

| 概念 | 一句話 | 程式／文件 |
|---|---|---|
| **模式** | `config.json` 的 `mode`：`personal`（只有擁有者；別人傳訊息＝當作沒這個指令）或 `server`（一群人；陌生人是訪客、每人一份資料、成員有 AI 額度）。伺服器版的營運者**看得到**使用者資料 | `config.py`、[AGENT.md](AGENT.md)「模式」、[security.md](security.md) |
| **Node（指令樹的節點）** | 每個指令是 SDK 指令樹上的一個葉節點：名字由路徑產生、帶 `effect`（READ／WRITE／DANGER）、`fields`（參數）、`ai`（給不給 AI 用）、`wraps`（之後替你跑別的指令的節點，例如排程）。人打字、按鈕、排程、AI 都走同一棵樹 | `vendor/isdtelekit/core/registry.py`、`packs/loader.py`、`packs/kit.py` |
| **守門** | ① `policy.decide()`＝唯一的權限判斷（SDK authorize ∧ 角色能力上限 ∧ bot 範圍 ∧ 頻道規則 ∧ 門禁）；② `ai_decision()`＝AI 能不能用某個節點（就是 decide(via=AI)）；③ 核准卡；④ 門禁核心 `guard/`：每個入口標**來源**（人／AI／排程／系統／遠端），驗證碼只收人的入口；⑤ 裝別人的 pack 的**五關**（宣告 → 靜態掃描 → `packs.lock` 雜湊 → 呼叫前驗參數 → ai_decision＋核准卡＋分隔符） | `policy.py`、`agent/loop.py`、`guard/`、`packs/{manifest,scan,lock}.py`、`agent/{validate,delimit}.py`；[security.md](security.md)「五關」 |
| **pack（工具）** | 一個資料夾：`pack.json`（宣告）＋`SKILL.md`（給 AI 的說明）＋程式。`kind`：`cli`（任何語言的命令列程式，SYNOX 的首選）、`python`（在 SYNOX 程序裡跑）、`mcp`（stdio 或遠端 http）、`theme`（外觀包）。壓成 `.synoxpack` 給人裝；裝的時候跑檢查、人按確認、寫 `data/packs.lock`；**沒有鎖的 pack 一律不載入** | `packs/`、[pack-format.md](pack-format.md)、[tools.md](tools.md)、[sdk.md](sdk.md) |
| **信任層級與簽章** | T0／T1／T2（T2＝附執行檔或外部程式，要一字不差輸入 publisher）；`.synoxpack` 可帶 `pack.sig.json`（Ed25519），標章由 SYNOX 自己驗：✅ 官方／✍️ 作者簽章／⚠️ 不是官方／⛔ 被改過（拒裝） | `packs/tier.py`、`packs/signing.py`、[adr/0028](adr/0028-pack-signatures-official-badge.md)、[signing.md](signing.md) |
| **soul.md** | 擁有者寫給助理的偏好（存在保管箱）。對話助理**唯讀**、包在分隔符裡標明「是偏好不是指令」；「習慣與規則」段的〔鍵=值〕給工具照宣告拿值，AI 只能提議、擁有者按了才寫 | `runtime/soul.py`、`runtime/habits.py`、[adr/0002](adr/0002-soul-md-in-chat-assistant-prompt.md)、[adr/0031](adr/0031-soul-habits-and-prefs.md) |
| **ledger（soul 帳本）** | 常駐助理想記進 soul.md 的筆記一律經帳本：記來歷、像指令或有網址的先問擁有者、取代不刪除、可以收起與遺忘 | `runtime/ledger.py`、[adr/0005](adr/0005-soul-ledger-memory-provenance-review.md) |
| **常駐助理（母 session）與心跳** | 背景裡**沒有工具**的助理，看心跳快照決定要不要通知擁有者；要它做事得走 ai_decision＋核准卡、另寫 ADR | `runtime/mother.py`、`runtime/heartbeat.py`、[adr/0001](adr/0001-runtime-loop-heartbeat-mother-session.md) |
| **Web UI** | 一頁式網頁（vanilla JS、nonce CSP、沒有外部資源），**只綁 127.0.0.1**；`WebUI.route()` 做全部判斷，非 GET 要 CSRF；送出的指令照樣經 dispatcher。工具服務（每個工具自己的完整畫面）只綁 127.0.0.2 | `web/server.py`、`web/apps/`、[adr/0024](adr/0024-tool-apps-services.md)、[security/web-threats.md](security/web-threats.md) |
| **channels（通道）** | Telegram（SDK）、Discord（私訊型與頻道型 bot）、網頁、終端機。核心不認識任何一家平台；通道只把訊息轉成 SDK 的輸入、提供回覆的 api | `discord/`、`web/channel.py`、[discord.md](discord.md) |
| **runtime 任務** | 背景工作一律登記成 `RuntimeLoop` 的任務（逾時、退避、失敗通知都在那裡），不要自己開執行緒；「A 做完做 B」寫成連動規則 | `runtime/loop.py`、`runtime/activator.py`、[adr/0004](adr/0004-activator-event-driven-rules.md) |
| **AI 的 harness** | 提示分七層、完成宣稱要有工具證據、救回洩漏的工具呼叫、每輪工具上限、context 預算……新行為預設只對本地／弱模型開 | `agent/{prompt,claims,toolpick,context,auto}.py`、ADR 0008–0020 |

「營運者也看不到使用者資料」的版本（SYNOX Node 規格）**還沒有做**，不在這個 repo。

## 3. 目錄地圖

| 位置 | 是什麼 |
|---|---|
| `src/synox/` | 核心（AGPL）。模組逐一的說明在 [AGENT.md](AGENT.md)「Map」 |
| `src/synox/sdk/`、`sdk/` | 給工具作者的 SDK（Apache-2.0）：`python -m synox.sdk`（`synox-sdk`）與產生出來的單檔版 `sdk/synox_sdk.py` |
| `vendor/isdtelekit/` | 上游 SDK 的原樣複本（版本在 `vendor/VERSION`）。不改 |
| `tests/` | pytest，一個功能一兩個檔（`test_<主題>.py`）；`conftest.py` 的 `make_bot` 在記憶體裡建整支 SYNOX（假通道、假 AI、真的加密）；`fixtures/` 測試用的 pack；`js/` 前端的 node 測試（沒有 node 就略過） |
| `evals/assistant/` | 對話助理的離線評測題目與劇本（`scripts/eval_assistant.py`，不叫真的 AI） |
| `examples/` | 可以照抄的工具範例（SDK、任何語言的 CLI、node MCP、遠端 MCP） |
| `packs/` | 使用者裝的工具的落點；**出廠是空的**，只有 `README.md` 進 git |
| `scripts/` | 開發與發佈工具：`make_zip.py`、`release.py`、`prepublish_check.py`、`clean_room_check.py`、`build_synox_sdk.py`… |
| `setup/`、`*.bat` | Windows 安裝、更新、啟動（`.bat` 只用 ASCII＋CRLF、`.ps1` 是 UTF-8 有 BOM） |
| `Dockerfile`、`docker-compose.yml`、`docker/`、`.devcontainer/` | 容器跑法與開發容器（[docker.md](docker.md)；映像檔還沒實際建置驗證過） |
| `docs/` | 文件，目錄在 [README.md](README.md)；`adr/` 架構決定、`handoff/` 真機測試交接、`lab/` 實驗與提案、`legacy/` 下架說明 |
| `.github/` | PR 範本、議題範本、治理文件、Windows 安裝程式的 CI |
| `config.example.json` | `config.json` 的範本（真的 `config.json`、`data/` 都在 `.gitignore`） |

## 4. 重要的 ADR（一行一份）

全部 40 份（0001–0041，0032 是空號）的標題與狀態在 [adr/README.md](adr/README.md)（也寫了什麼時候要寫新的、編號規則）。最常碰到的：

- [0001](adr/0001-runtime-loop-heartbeat-mother-session.md) runtime loop、心跳、常駐助理、soul.md——背景工作的骨架。
- [0002](adr/0002-soul-md-in-chat-assistant-prompt.md)／[0005](adr/0005-soul-ledger-memory-provenance-review.md)／[0031](adr/0031-soul-habits-and-prefs.md) soul.md 怎麼進提示、帳本、習慣與規則。
- [0003](adr/0003-distribution-git-clone-and-installer.md) 發佈方式與「沒有 hidden dependency」（路徑一律相對或可設定）。
- [0004](adr/0004-activator-event-driven-rules.md) 連動規則與防無限連動。
- [0007](adr/0007-local-llm-platform.md) 本地模型；[0008](adr/0008-completion-guard.md)–[0020](adr/0020-eval-missing-tool-param-and-metrics.md) AI harness 的各條規則。
- [0021](adr/0021-vlm-vision.md) 看圖只是 provider 能力。
- [0022](adr/0022-ecosystem-bridge-and-sandbox.md) 其他生態、沙盒、隔離的總決定；[0028](adr/0028-pack-signatures-official-badge.md) 簽章、標章、沒經過安裝頁不載入。
- [0023](adr/0023-updates-and-hotfixes.md) SYNOX 自己更新與 hotfix。
- [0024](adr/0024-tool-apps-services.md)／[0025](adr/0025-guard-core-and-stepup.md)／[0026](adr/0026-remote-tool-apps.md) 工具服務、門禁核心與手機驗證器、手機入口。
- [0027](adr/0027-multi-file-python-packs.md) 多檔 python 工具；[0030](adr/0030-tool-registration-index.md) 工具登記與索引（pack.json 的 `agent` 區塊）。
- [0029](adr/0029-reminder-delivery-on-notify-hub.md) 提醒必達（通知中心、送達與重試、提醒視窗）。
- 0033–0040：「一次改好幾筆」與核准卡、通知分流的**提案**（還沒有程式；0038 第一段已做）。
- [0041](adr/0041-pack-warnings.md) pack.json 的標記警告（`warnings`）：每個看得到工具的地方都顯示、第一次啟用要確認；§5 是跟沙盒的關係（目前不會因為警告就被隔離）。

## 5. 在雲端 session（或任何不是擁有者電腦的地方）工作

- **你拿不到、也不需要**任何私人資料或金鑰：沒有 Telegram／Discord token、沒有 AI 金鑰、沒有擁有者的 `config.json`、`data/`、簽章私鑰。
  全部測試與開發設定都用假的東西（[development.md](development.md)「不用金鑰的開發設定」）。看到某件事「需要真的帳號」，就寫進交件說明，留給擁有者在他的電腦上驗。
- **機密的設計與計畫文件不在這個 repo**。需要時由擁有者另行經加密分支提供（分支名 `encrypted/<主題>-<日期>[-<序號>]`），
  解密方式見該分支的 `encrypted/README.md`（若該分支存在）；解出來的內容**不能**寫進這個公開 repo 的檔案、commit 訊息或 PR。
  **解密用的私鑰不在任何分支裡**，只會由維護者設在雲端環境的祕密（secret／環境變數）裡；環境裡沒有這個祕密，就停下來回報，不要找別的方法拿、也不要請人把私鑰貼進對話。
- **這是公開 repo**：檔案、commit 訊息、PR 說明都不能有真名、信箱、本機路徑（`C:\Users\<名字>`、`/home/<名字>`）、token、別人的個人資料；
  範例一律用假資料。交件前跑 `python scripts/prepublish_check.py --worktree-only`（[AGENT.md](AGENT.md)「公開前檢查清單」）。
- **Windows 專屬的東西在 Linux 上驗不了**（`.bat`、PowerShell、DPAPI、登錄檔、tkinter 視窗、Job Object、安裝程式）：
  改到這些時照常寫測試（用假的 kernel32／假 Popen 等），並在交件說明列「沒在 Windows 上試過」。
- **不要動發佈相關的東西**：不升版本號、不打 tag、不發 release、不改 `main`、不碰簽章的公鑰常數——這些由擁有者決定（[release-playbook.md](release-playbook.md) 第 6 節）。
- **交件**：在自己的分支上 commit，開 PR 到 `dev`（或照指派你的人說的做）；不要直接推 `dev`／`main`。PR 說明照範本寫，並列出測試結果與沒驗到的東西。

## 6. 接下來去哪

| 想做的事 | 讀這些 |
|---|---|
| 建環境、跑測試、交 PR | [development.md](development.md) |
| 寫一個工具（pack） | [development.md](development.md)「開發 pack」→ [tools.md](tools.md) → [pack-format.md](pack-format.md)、[sdk.md](sdk.md)、[../examples/](../examples/)；要交給工具庫的，以工具庫 repo 的 `docs/HANDOFF.md` 為準 |
| 改核心 | [development.md](development.md)「改核心的規則」→ [AGENT.md](AGENT.md) invariants → 相關的 ADR |
| 動到安全 | [security.md](security.md)、[security/web-threats.md](security/web-threats.md)、[sandbox-roadmap.md](sandbox-roadmap.md) |
| 發版（只有擁有者決定時） | [versioning.md](versioning.md)、[release-playbook.md](release-playbook.md)、[signing.md](signing.md) |
| 前面幾輪做了什麼 | [../CHANGELOG.md](../CHANGELOG.md) 最上面幾節、`git log --first-parent dev`、[handoff/](handoff/README.md)（真機測試交接與舊的工作交接） |
