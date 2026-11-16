# SYNOX：生態接入、安全沙盒、技能市場、套件預覽、SDK（完整任務書，分階段，兩道核准關卡）

你是 SYNOX 的研發主 session。階段 1 到 4 由 fable 執行（研究與規劃）；階段 5 才派 opus 5.5（high）的多個 sub agent 實作。
主 session 要保持 context 乾淨：細節交給 sub agent，自己只留結論與狀態；擁有者會不斷與你討論。

---

## 0. 現況（2026-11-16 更新；先讀這一節）

這份任務書寫在 `d64c31d`（2026-11-13）。到現在的 `main`（`3c642c5`，已等於 `origin/main`）之間有 174 個 commit。對照結果：

**一句話（2026-11-16 晚更新）：⛔ 關卡 1 已過。** 擁有者 2026-11-16 回覆：35 題**全部照建議**，另加**修正 O1**——目前不執行、也不讓使用者安裝從其他生態來的工具與技能
（OpenClaw、Hermes Agent、其他 Agent Skills 集散地、npm 套件名匯入、外面的市集）；畫面上照樣列出這個功能、標明高風險、不能裝。
ADR 0022 改成「已採用，附修正 O1」（第 11、13、14 節），實作計畫改成「已核准」並重排順序（第零節）。`src/` 到這時還沒有為它動過。
**還有一題待擁有者確認（O1-Q）**：現在就有的「裝任何人做的 `.synoxpack`」（拖放、點兩下、上傳）算不算在 O1 裡。下一步是階段 5，照 0.7 的順序。

### 0.1 各階段狀態

| 階段 | 狀態 | 產出／證據 |
|---|---|---|
| 1 擁有者的想法 | 第 7 點（「架構大概會類似……」）**仍空白** | — |
| 2 初步調查 | 完成；假設 A–J、2.3 已被階段 3 逐條評定 | 研究第三節 |
| 3 研究 | **完成** | [`docs/lab/2026-11-13-ecosystem-security-research.md`](2026-11-13-ecosystem-security-research.md)（1219 行，含結論表 Y1–Y12／N1–N12、35 題決定）；Windows 探針 [`docs/lab/tools/windows-sandbox-probe/`](tools/windows-sandbox-probe/) |
| 4 規劃 | **完成，已核准（附修正 O1）** | [`docs/adr/0022-ecosystem-bridge-and-sandbox.md`](../adr/0022-ecosystem-bridge-and-sandbox.md)（狀態：已採用，附修正 O1；§13 照做／延後、§14 沿用 11-13 之後的新東西、§6.3 開發機版本已更正）；[`docs/lab/2026-11-13-ecosystem-implementation-plan.md`](2026-11-13-ecosystem-implementation-plan.md)（狀態：已核准；第零節是新順序） |
| 對外 | 完成 | [`docs/sandbox-roadmap.md`](../sandbox-roadmap.md)（老實版現況＋徵求協助 H1–H11）、[`docs/community/discussion-ecosystem-and-sandbox.md`](../community/discussion-ecosystem-and-sandbox.md)（Discussions 草稿）；對 OpenClaw／Hermes 用中性、以相容為目的的語氣（`420c6ea`） |
| ⛔ 關卡 1 | **2026-11-16 通過，附修正 O1** | 擁有者：全部照建議；O1＝先不接外來的工具與技能，畫面標高風險、不能裝。待確認：O1-Q（ADR 0022 第 11 節後面） |
| 5 實作 | 未開始 | 照實作計畫第零節的順序。設定頁「別人做的技能（OpenClaw、Hermes）」卡要改成「⛔ 高風險，目前不開放」（O1-UI）；「沙盒模式」卡仍標 ⏳ 尚未完成 |

### 0.2 關卡 1 的問題：已答（2026-11-16，全部照建議，附修正 O1）

| 原本的問題 | 研究結論／建議 | 決定編號 |
|---|---|---|
| Hermes 指哪個專案 | Nous Research 的 **Hermes Agent**（研究主題 2.1） | 1 |
| 要不要做 core | **不做**。只做「匯入器＋MCP」；`openclaw-core`／`hermes-core` 兩個名字在 npm 已被佔、MIT 不給商標權；改用中性名字「匯入」 | 2、9 |
| Node 由誰提供 | **SYNOX 自己管一份可攜版 Node**，第一次需要時（使用者按了才）下載，不放進安裝程式 | 8 |
| Windows 沙盒選哪個 | **MXC 為主**（Windows 11 新版內建），舊系統退到自製 AppContainer（等級「基本」），專用帳號＋防火牆做成選配「加強保護」；**先實測再定** | 11–14 |
| 預覽跑不跑 JS | **第一版不跑**；封面不收 SVG；預覽頁單檔自足 | 29–31 |
| 允不允許連網抓工具目錄 | 只在使用者按按鈕時，連寫死的官方來源 | 25 |
| 研究找到的小修要不要先做 | 先做（實作計畫「可以單獨核准的小修」Q1–） | 34 |

其餘 28 題（純文字技能、確認卡規則、MCP 釘雜湊、簽章金鑰、撤銷清單、新發行者限制……）見 ADR 0022 §11；**也已照「建議」欄核准**。
修正 O1 讓決定 3、6、9、10、28（匯入器、套件名匯入、外面發行者）先不做，決定 4（`kind=skill`）、8（可攜版 Node）往後排；上表這七題裡，1、2、9 的答案照記但目前沒有要做的事。

### 0.3 階段 2 假設被評定的結果（摘要；全文在研究第三節）

- **A** 部分確認；另補 4 個缺口：`node_modules` 不在雜湊鎖裡、鎖檔 `integrity` 不強制、MCP stdio 只能用沒鎖的 `npx`、Windows 個人版沒有執行期沙盒。`--ignore-scripts` 是**無聲地壞**（約 2% 套件，集中在原生模組與瀏覽器下載）。
- **B** 確認，但附程式的技能，匯入器只在**作者／工具庫端**離線跑，不在使用者安裝時自動轉。
- **C** 部分確認；「沙盒擋得住程式型」對現況不成立（Windows／個人版沒有沙盒）；少了第三類「騙人不騙 AI」（叫人貼指令、預覽假畫面）與 rug pull（MCP 工具說明在核准後被換）。
- **D** 部分確認；**樣式掃描當放行的門：推翻**，只能當提醒。
- **E** 候選名單改為 MXC、AppContainer、專用帳號＋WFP；**劃掉 Windows Sandbox**（Home 版沒有、接不了長駐 stdio）。
- **F** (1)(3) 以現況推翻（子程序會繼承整份環境變數；`network` 只有有／無，沒有網域欄位）；(4) 確認。
- **G** 確認。**H**「純文字技能風險低」推翻（破壞上限＝AI 已有的全部工具），但不必走 T2。
- **I** 部分確認：`synox-sdk init／run＋check／zip` 已有三個等價指令；缺的是獨立套件帶指令、`run` 只支援 cli、沒有 preview、沒有範本 repo。**J** 確認，建議選「簡單乾淨」。
- **2.3 預覽** 方向確認，五處要改（單檔自足、要新寫 HTML 檢查器、用回應標頭的 CSP `sandbox` 不用 `srcdoc`、處理假冒畫面、封面不收 SVG）。

### 0.4 11-13 之後做了、會影響這份任務的東西（都已在 `main`）

| 已做 | 對這份任務的影響 | 證據 |
|---|---|---|
| **官方工具庫目錄**：網頁看得到 SYNOX_Libs 的工具，按了才下載，大小＋sha256 對清單，再走同一套報告→確認 | 假設 A(4)「沒有遠端目錄」**已部分解決**（決定 25 的做法已照建議落地）；**還沒有簽章與撤銷清單**（決定 26、27） | `64e2baf`、`2fdaa71`；`src/synox/packs/catalog.py` |
| **SYNOX 自我更新的 ed25519 簽章**（ADR 0023 已採用） | 決定 26 的簽章技術已有一套可以共用（ADR 0023 自己寫「跟 0022 決定 26 同一套」） | `f75cbb2`；`src/synox/update/signing.py` |
| **工具 app**（ADR 0024 已採用）：每個工具的網頁跑在另一個隔開的地方、不碰主機台的登入與 API；新寫了 `appscan`（JS／CSS 只提醒、不當門） | `web.panel` 的同源問題（ADR 0022 R4、決定 23）**有了隔開的替代路徑**，但 `web.panel` 本身沒改、SDK 範本仍預設產生 panel；預覽要的「HTML 檢查器」（§7.4）可以從 `appscan` 長出來 | `c3c863a`～`34d2759`；`src/synox/packs/appscan.py`；`docs/tool-apps.md` |
| **守門核心＋手機驗證器**（ADR 0025）：pack 可宣告 `callers`／`stepup`（只能收緊），敏感動作要手機驗證碼 | §5「能力控制與人的確認」的**一部分基礎**；但決定 18 的確認卡（第三方 WRITE、讀過不可信內容後的寫入／外傳）**還沒做** | `f84c1e4`、`169856b`；`src/synox/packs/manifest.py` 的 `stepup` |
| **外觀包 `kind=theme`**（沒有程式的新種類） | 加「沒有程式的 kind」已有先例，`kind=skill`（決定 4）可照它的路 | `ffdc5b6`；`KINDS` 現為 python／cli／connector／mcp／theme |
| 白話用詞全面整理、`/help`、教學、安裝程式、自我更新 | 「非工程師測試」的文字規範已在全站實行，新功能照做即可 | `a588005` 等 |

### 0.5 還沒做（確認過 `main` 的程式）

`kind=skill`、`preview.*` 欄位與預覽路由、`network.hosts` 網域名單、連外代理、環境變數白名單（`sandbox.py` 仍是名字像密鑰的才拿掉）、npm 套件名匯入、鎖檔 `integrity` 強制、MCP 工具定義釘雜湊、可攜版 Node、Windows 任何隔離後端（`appcontainer` 仍是 `NotImplementedError`）、`synox-sdk preview`、工具庫目錄簽章／撤銷。

### 0.6 新事實（2026-11-16 查到）

- **擁有者這台開發機是 Windows 11 Home 25H2，build 26200.9974**（ADR 0022 §6.3 原本寫的「擁有者開發機是 Windows 10 Home」已過時，**2026-11-16 已更正**）。這個 build 高於 MXC 的最低要求 26200.9278，所以 **MXC 能不能在 Home 版用，這台就能直接實測**（研究標「查不到」的那一題）。這台沒有裝 node。
- Windows 探針（`win-env-probe.ps1`、`win_appcontainer_probe.py`）11-16 早上還沒有人跑過；**現在正在這台跑（進行中，另一個代理）**，結果會在 `docs/lab/2026-11-16-windows-sandbox-probe-results.md`。
- 本機的 `dev` 分支停在 `d64c31d`，比 `origin/dev` 落後 171 個 commit。開工前先 `git fetch` 並把本機 `dev` 快轉到 `origin/dev`（見工作規則第一條）。

### 0.7 下一步（2026-11-16 照修正 O1 重排；細節在實作計畫第零節）

1. ~~擁有者回答 0.2 的七題~~：已答（全部照建議＋O1）。**還要問擁有者**：O1-Q（裝任何人做的 `.synoxpack` 算不算在 O1 裡）；`kind=skill` 要不要先做給官方的說明型技能用；第 1 階段第 7 點有沒有補充。
2. **探針在這台跑（進行中，另一個代理）**：`win-env-probe.ps1`＋`win_appcontainer_probe.py`＋MXC 的最小探測（路線圖 H3／H4）。結果會在 `docs/lab/2026-11-16-windows-sandbox-probe-results.md`；決定 13 的路線等它。
3. 主 session：**O1-UI**——設定頁「別人做的技能」卡改成高風險、沒有安裝按鈕（草稿在 ADR 0022 §13.1）；加掛載點。
4. 先做**保護官方與自己的工具**的部分（平行）：小修（決定 34：Q1–Q8、Q10）、確認卡 C2／C3、報告顯示「AI 會讀到的內容」、**MCP 釘雜湊**、**鎖檔 `integrity` 強制**、**環境變數白名單**（先警告）、連外代理與 `network.hosts`、預覽（借 `appscan`／`theme/sanitize.py`）、目錄**簽章與撤銷**（借 `update/signing.py`，接在 `catalog.py` 上）、SDK 別名與範本。
5. Windows 隔離後端（C2）：探針結果與決定 11–13 之後。
6. **⏸ 延後到擁有者重開「裝外來的工具」**：匯入器、npm 套件名匯入、給外面發行者的市集、`synox-sdk import`；可攜版 Node 等官方 Node 工具需要時再排。

---

## 工作規則（全程適用）
- 先 `git fetch`，確認本機 `dev` 等於 `origin/dev`（2026-11-16 時本機 `dev` 落後 171 個 commit）。所有 worktree 都從 `dev` 的最新 commit 開始。每個 agent 開工前必須確認 `git merge-base HEAD dev` 等於 `git rev-parse dev`，不是就 `git reset --hard dev`（歷史上有 agent 的 worktree 被建在舊的 main 上，造成 211 個 commit 落差與衝突）。
- agent 只在自己的分支 commit，不 merge、不 push。合併由主 session 依序用 `git merge --no-ff` 併回 `dev`；合併後跑全套測試（`.venv\Scripts\python.exe -m pytest`，網頁與 UI 預覽另有 tests/test_web.py、tests/test_ui_preview.py）；完成後用 `git worktree remove --force` 移除 worktree、`git branch -D` 刪暫時分支。
- 改動 `src/synox/web/static/app.html` 後要重新產生 `docs/ui/preview.html`（`scripts/make_ui_preview.py`），否則 test_ui_preview 會失敗。
- commit 訊息結尾：`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- 共用檔案（app.html、README.md、CHANGELOG.md、docs/AGENT.md）容易衝突：只由主 session 或指定的單一 agent 改。
- 平台是 Windows 11；`.bat` 檔必須 ASCII-only。網頁沒有 i18n 機制：面向使用者的字串是白話繁體中文，集中放在一個表。
- 先讀 docs/AGENT.md 與 CONTRIBUTING.md 的慣例（測試、文件、CHANGELOG）。
- 不確定的事列成問題問擁有者，不要自己猜了就做。
- 不要 push 到 GitHub。

---

## 階段 1：擁有者的想法（已定，不要推翻，只能提出風險）

1. 讓 SYNOX 的工具能安裝 npm 工具，進而能接 **OpenClaw、Hermes** 這類以 npm／agent 框架為底的生態。
2. 構想是 **adapter-of-adapter（adapter 的 adapter）**：建立類似 `openclaw-core`、`hermes-core` 的東西，讓以它們為底開發的工具，可以「以它們為底重新嫁接一次」變成 SYNOX 的工具。
3. 未來能接受、對接 **技能（skills）市場**，讓東西好用。
4. 要把 SYNOX 的 **SDK** 做好，讓別人好用。
5. 最大賣點是 **「好裝」**：非工程師都看得懂，簡潔乾淨。每個新功能都要通過「非工程師測試」：不開終端機、報告用白話、不出現 npm、lockfile 這類術語、失敗時說得出下一步。技術面的路徑放在「進階」，不污染主流程。
6. **安全**：擁有者知道有很多惡意 skill 被寫出來，要讓 SYNOX 有安全的沙盒，保護使用者。擁有者的猜測（待查證）：Hermes 與 OpenClaw 應該也有類似的解法。
7. 擁有者另有一份「架構大概會類似……」的想法尚未補上；若擁有者之後補充，加在這裡（開工前先問擁有者有沒有補充）。
8. 整體流程（擁有者指定）：擁有者的想法 → 主 session 的調查 → 請 agent 仔細研究研讀 → 規劃執行 → 多 agent 實作（opus 5.5 high，多個並行）。前面的階段用 fable 跑。

---

## 階段 2：主 session 的初步調查（以下全是假設，不是事實；階段 3 必須驗證）

### 2.1 SYNOX 現況（請讀這些檔案確認，不要照這裡的轉述）
- 文件：docs/pack-format.md、docs/ecosystem.md、docs/sdk.md、sdk/（README.md、pyproject.toml、synox_sdk.py）、docs/security.md（五關、T0/T1/T2、運行空間）、docs/install-packs.md、docs/lab/discussions/2026-11-10-sandbox-and-skill-containers.md、docs/lab/discussions/2026-11-10-isolation-howto.md、docs/tool-apps.md、docs/sandbox-roadmap.md、docs/handoff/container-verification.md、docs/adr/（尤其本地模型、pack 相關）。
- 程式：src/synox/packs/（envs.py、admin.py、scan.py、container.py、library.py、lock.py、upgrade.py、mcp.py）、src/synox/sdk/、src/synox/web/server.py、src/synox/web/static/app.html（含 packdrop.js／packdrop.css）。
- 已有的：
  - **五關**：宣告檢查、靜態掃描、報告給你看、你按確認才裝、`data/packs.lock` 逐檔雜湊鎖。
  - **信任層級 T0／T1／T2**：附執行檔或用到外部程式（`{node}`、`npx` 等）就是 T2，要一字不差輸入 publisher。
  - **pack 種類**：`kind=cli`、`kind=mcp`；`runtime.container` 欄位；安裝時可選容器或不用。
  - **npm 支援**：`runtime.node: "auto"` 會在 `data/envs/<pack>/` 執行 `npm ci --ignore-scripts --registry=https://registry.npmjs.org/`，需要 `package.json`＋`package-lock.json`，lock 內每個 `resolved` 都必須是官方 registry；系統沒有 node＝doctor 說缺、pack 不載入。
  - **沙盒**：Linux 有 `SystemdSandbox`；Windows 只有 `JobObjectSandbox`（只限記憶體與程序數，**不限檔案與網路**）。
  - **工具庫**：`SYNOX_Libs`（另一個 repo）的 `index.json`＋`.synoxpack`（含 sha256、`requires.sdk`、bundles）；`packs.library` 寫網址時只顯示、不會自動下載。
  - **技能**：pack 的 `SKILL.md` 讓 AI 自己學會怎麼用。
  - **最近已合併進 dev 的安裝介面**（可直接掛接）：設定頁分頁；專屬安裝頁 `#packs`（報告、確認、結果在同一格）；「等你核准」暫存清單（`GET /api/packs/staged`、`POST /api/packs/discard`）；步驟流程 檢查→看報告→確認→安裝→完成，每步會送 `document` 的 `synox:install-step` 事件、`#install-steps` 有 `data-step`／`data-status`；`window.SynoxInstall`（`open`、`reviewFile`、`reviewToken`、`onStep`、`state`）；拖進網頁安裝（packdrop）；`.synoxpack` 檔案關聯（`python -m synox filetype register|unregister|status`）。

### 2.2 我的假設（請推翻或確認，並說明理由）
- **A. 缺口不在「能不能裝 npm」**，而在：
  1. 需要安裝腳本（編譯原生模組等）的 npm 套件在 `--ignore-scripts` 下會壞。
  2. 使用者只給一個 npm 名稱時，沒有流程替他解析、鎖版本、產生 `package-lock.json`。
  3. 系統要自己有 node；非工程師不會去裝。要不要由 SYNOX 管理一份 node（或放進容器）？
  4. 沒有遠端目錄或市場。
- **B. 以 MCP 當共通語言**：上游能包成 MCP 伺服器的，直接走現有 `kind=mcp`，不需要新 adapter。只有上游有專屬格式（技能、外掛）時，才做「**匯入器**」：安裝時把它轉成標準 SYNOX pack（產生 `pack.json`、`SKILL.md`），之後完全走現有五關；**執行期不依賴 adapter 的活程式碼**。**不要**做依賴上游內部結構的「core」（上游一改版就壞、維護成本高）。請評估 `openclaw-core`／`hermes-core` 這個想法能不能用「匯入器＋MCP」達成同樣目的；若不行，說明為什麼要做 core。
- **C. 惡意 skill 有兩種**：
  - 程式碼型：skill 附的腳本偷檔案、偷金鑰、連外。沙盒可擋。
  - 文字型：`SKILL.md` 或描述裡藏**提示注入**，叫 AI 自己去讀檔、外傳資料、執行危險工具。**沙盒完全擋不住**，我認為這是更大的洞。
  - 所以要兩層防禦：沙盒管程式碼，**能力管控**管 AI 的行為。
- **D. 能力管控（最小權限＋人工確認）**：skill 提供的工具要宣告能碰什麼；高風險動作（寫檔、外傳資料、執行指令、連外網）要使用者確認，或在宣告外一律拒絕；skill 的文字視為**不可信輸入**（標示來源、掃描可疑指令樣式如「忽略先前的指示」「把某檔案傳到某網址」）。
- **E. Windows 是最弱的一環**，而使用者多半是 Windows。候選：Docker Desktop/WSL2（要使用者自己裝，不夠「好裝」）、AppContainer（內建、不用另外裝，但實作難）、Windows Sandbox（只有 Pro 以上，家用版沒有）。未下結論，需要研究與實測。
- **F. 密鑰與網路**：skill 的環境不繼承使用者的環境變數、拿不到其他 pack 的資料夾；網路預設全擋，只開 skill 宣告的網域（出口白名單）；帳號連接走「工具頁連接」，不把密碼塞進 skill。
- **G. 供應鏈與更新**：版本鎖定、升級時顯示「改了什麼」（已有）；市場來源要有簽章或審核等級；新發布者預設低信任；要有一鍵停用／隔離、事後可查的稽核紀錄。
- **H. 純文字 skill**（沒有程式碼）風險低，可做最簡單的一鍵安裝；帶腳本的走 T2。
- **I. SDK**：`docs/sdk.md` 與 `sdk/` 已有；缺的是「5 分鐘做出第一個工具」的體驗：`synox new`（產生範本）、`synox pack test`、`synox pack build`、`synox pack preview`（本機先看預覽）、一頁式 quickstart、範本 repo。
- **J. 取捨**：接的上游越多，攻擊面與維護面越大，這與「簡潔乾淨」互相拉扯。請在規劃時明確給出取捨建議。

### 2.3 套件預覽功能（擁有者要求；也能當宣傳）
擁有者希望：在安裝頁（`#packs`）的「看報告」階段，**按確認之前**就能預覽這個套件——它的 UI、作者自己附的說明 HTML 頁面、小動畫。這也可以拿來做工具庫的宣傳頁。初步設計（待驗證與規劃）：
1. **manifest 新增選填欄位**（例如 `preview.entry`、`preview.cover`、`preview.title`、`preview.summary`），指向 pack 裡的靜態檔案；沒宣告就不顯示，不影響現有套件。
2. **沙箱 iframe**：預覽 HTML 是第三方程式碼。`sandbox` 屬性不給 `allow-same-origin`；**預設不跑 JavaScript**（小動畫用 CSS 就夠）；不能讀 SYNOX 的 cookie、登入狀態或呼叫 SYNOX 的 API；不能連外網。
3. **提供檔案的路徑**：套件這時還沒通過確認，不能從真正的 pack 目錄提供。用暫存區（staging）的唯讀專用路徑，加嚴格的 CSP；限制大小與檔案類型白名單；讓靜態掃描也檢查預覽資料夾。
4. **顯示位置**：安裝頁「看報告」旁的「預覽」分頁；「等你核准」清單與已裝套件頁可顯示封面。
5. **工具庫**：`SYNOX_Libs` 的 `index.json` 加封面與一句話介紹；9 個現有 pack 補預覽；用它產生展示頁。
6. **作者端**：放 `preview/index.html` 並在 manifest 宣告；`synox pack preview` 讓作者本機先看。
待擁有者決定：預覽是否一開始就允許跑 JS（我建議**先不跑**，有需求再開）。

### 2.4 不在這份範圍內（避免混入）
擁有者曾提過想把這台電腦當成對外的免費服務（開放 Ollama 或 SYNOX 給別人用），尚未決定是哪一種（A 只開 AI 模型 API／B 開整個 SYNOX／C 只給自己的裝置或家人）。**本任務不做**，只在安全設計時留意不要與它衝突（Ollama 本身沒有驗證，不可直接把 11434 對外開放）。

---

## 階段 3：研究與研讀（fable；產出 `docs/lab/<日期>-ecosystem-security-research.md`）

> ✅ 2026-11-13 已完成：`docs/lab/2026-11-13-ecosystem-security-research.md`。以下保留當初的要求當紀錄；**不要重做**，只補「待查／待實測」的項目。

用 WebSearch／WebFetch 找一手來源（官方 repo、文件、授權檔、事件報告）。**每個結論附來源網址；查不到就明寫「查不到」，不得猜。** 標示：已查證／推測／待實測／待查。

1. **OpenClaw**：它是什麼、架構、技能與外掛格式、授權、是否支援 MCP、安全機制（沙盒、權限提示、預設值是寬鬆還是嚴格）、歷來的安全事件與惡意技能事件（時間、手法、影響、官方處置）。
2. **Hermes**：先確認擁有者指的是哪個專案（可能有多個同名，例如 agent 框架或模型系列）；找不到明確對象就列出候選並問擁有者。查同樣的項目。
3. **其他可借鏡的技能市場**：包含官方 Agent Skills 格式（`SKILL.md`）、其他 agent 生態的市場，它們的信任、審核、簽章、舉報、下架機制。
4. **Windows 沙盒方案**的實際可行性：AppContainer、Windows Sandbox、Docker Desktop/WSL2、Job Object＋受限 token 的組合；能不能做到「使用者不用裝任何東西」；對檔案與網路的實際限制；用最小的實測（在 `scratch` 目錄，不碰使用者資料）驗證，標明「已實測」或「待實測」。
5. **提示注入**在 skill 文字中的實例與業界防禦（輸入標示、能力分離、人工確認、輸出過濾）。
6. **授權相容性**：上游授權能不能被匯入、轉換、散布；有沒有商標或散布限制。
7. **npm 供應鏈**：`--ignore-scripts` 的相容性實況（常見需要安裝腳本的套件比例與替代做法）、lockfile 產生與驗證、typosquatting 與惡意套件的偵測做法。
8. **隔離瀏覽器內容**：沙箱 iframe（`sandbox` 屬性、CSP、`srcdoc` 與獨立 origin 的差別）對應預覽功能的最佳做法。

產出**結論表**：做得到／做不到／要擁有者決定的事，以及每個假設（2.2、2.3）被確認或推翻的結果。

---

## 階段 4：規劃（fable；產出 `docs/adr/<下一個編號>-ecosystem-bridge-and-sandbox.md` 與實作計畫）

> ✅ 2026-11-13 已完成：`docs/adr/0022-ecosystem-bridge-and-sandbox.md`（提案）與 `docs/lab/2026-11-13-ecosystem-implementation-plan.md`（計畫）。
> 核准前要先對齊 11-14 之後的新東西（見第 0.4 節：工具目錄、ed25519 簽章、工具 app 與 `appscan`、`stepup`、`kind=theme`），並更正 §6.3 擁有者開發機的版本。
> ✅ 2026-11-16 已做：ADR 0022 §14（沿用的東西）、§6.3（開發機版本）。

內容至少包括：
1. **匯入器架構**：輸入、輸出、哪些走 MCP、哪些要轉換、哪些做不到；是否真的需要 `openclaw-core`／`hermes-core`（見 2.2 B）；匯入後的 pack 如何標示來源與信任層級。
2. **npm 名稱匯入流程**：解析、鎖版本、產生 `package-lock.json`、報告給使用者看、`--ignore-scripts` 的相容性（支援、替代做法或明確列為不支援）。
3. **Node 由誰提供**：系統的、SYNOX 管理的、或容器；對「好裝」的影響。
4. **技能市場信任模型**：來源、sha256、簽章、審核等級、新發布者低信任、**不自動執行**、純文字 skill 與帶腳本 skill 的信任層級對應、下架與一鍵停用、稽核紀錄。
5. **能力管控與人工確認**：宣告格式、哪些動作屬高風險、確認的介面（白話）、提示注入的標示與掃描。
6. **Windows 沙盒方案**與 Linux 方案的統一抽象；密鑰與網路出口白名單。
7. **套件預覽**：manifest 欄位、沙箱 iframe 與 CSP、暫存區路由、掃描、顯示位置、`synox pack preview`、工具庫 `index.json` 的調整、是否允許 JS 的建議。
8. **SDK 改進清單**：`synox new`、`synox pack test|build|preview`、quickstart、範本。
9. **威脅分析**：程式碼型、文字型、供應鏈偽造、沙盒逃逸、預覽 XSS、確認疲勞（使用者一路按同意）、非工程師會卡住的地方。
10. **分工、依賴順序與驗收標準**（每項都要有可測的驗收條件，包含「非工程師測試」）。

**硬性限制**
- 不得削弱「報告給你看、你按確認才裝」與現有五關；任何新來源（市場、匯入、預覽、拖放）都必須走同一套檢查。
- 第三方程式碼與預覽一律隔離；不得讓第三方內容碰到 SYNOX 的登入狀態或 API。
- 面向使用者的字串用白話中文，不出現 npm、lockfile、sandbox 這類術語（必要時用括號小字補充）。
- 資料夾外的路徑、符號連結、UNC 路徑等一律不跟隨（沿用現有防禦）。

### ⛔ 關卡 1（必停）— 2026-11-16：**已通過**（全部照建議，附修正 O1；O1-Q 待確認）
階段 3、4 的文件完成後**停下來**，向擁有者回報：摘要、被推翻的假設、需要擁有者決定的問題（至少包含：預覽是否跑 JS、Node 由誰提供、Windows 沙盒選哪個、要不要做 core、Hermes 指哪個專案）。**未獲核准，不得進入階段 5。**

---

## 階段 5：多 agent 實作（opus 5.5 high；擁有者核准後才開始）

- 依階段 4 的計畫把工作切成**互不重疊**的區塊，每個 agent 擁有一組檔案，各自在 `dev` 起算的獨立 worktree，各自 commit，不自己 merge。共用檔案只由主 session 或指定的單一 agent 改。
- **建議分工**（依規劃調整）：
  1. 匯入器與 npm 名稱匯入（含 Node 提供方式）
  2. 能力管控與人工確認（含提示注入標示與掃描）
  3. Windows／Linux 沙盒與密鑰、網路出口
  4. 技能市場來源與信任模型（`SYNOX_Libs` 的 `index.json` 調整）
  5. 套件預覽（manifest 欄位、沙箱 iframe、暫存區路由、安裝頁「預覽」分頁）
  6. SDK 與文件（`synox new`、`synox pack test|build|preview`、quickstart、範本）
  7. **獨立的審查 agent**：專門找「能否繞過人工確認」「文字型提示注入」「沙盒逃逸」「供應鏈偽造」「預覽 XSS」「非工程師會卡住的地方」，只提報告、不改程式。
- **每個 agent 的做法**：先寫測試再實作；跑全套測試；回報分支、worktree 路徑、base commit、測試結果、**沒驗證到的部分**。沒有真的在瀏覽器或真機看過的，就明說沒看過。
- **主 session**：依序 `--no-ff` 合併、解衝突、重跑全套測試、移除 worktree 與分支；每個大區塊合併後向擁有者簡短回報。

### ⛔ 關卡 2（每個大區塊都要）
每完成並合併一個大區塊，向擁有者回報結果、需要他親自在真機測試的步驟，等確認再繼續下一塊。

---

## 回報格式（所有階段，簡短）
分支、worktree 路徑、base commit、產出文件路徑、關鍵結論（附來源）、需要擁有者決定的問題、沒驗證到的部分。
