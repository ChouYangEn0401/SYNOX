# 實作計畫：接上 OpenClaw／Hermes 生態、npm 工具、市集、隔離、預覽（給平行的實作代理）

- 日期：2026-11-13
- 狀態：**計畫，等擁有者核准**。核准之前不動 `src/`。這份只講「怎麼分工、先後、怎麼驗收」；「為什麼這樣設計」在 [ADR 0022](../adr/0022-ecosystem-bridge-and-sandbox.md)，
  「查到什麼」在[研究](2026-11-13-ecosystem-security-research.md)。
- 對象：主 session 與之後各自在自己的 worktree 裡實作的代理（工程師）。
- 決定的編號（決定 1–35）跟研究第七節、ADR 第 11 節一致。`§` 指 ADR 0022 的章節。
- 程式的行號對的是分支 `dev`、commit `a22382c`。

## 一、先講三件事

1. **平台現實**：開發與自動測試都在 Linux 雲端機器上跑。**Windows 上的行為只有擁有者能在真機驗證**，瀏覽器的實際行為、真的模型也一樣。
   所以每個區塊的驗收分兩半：「自動測試（Linux，用假的後端／假的網路／暫存資料夾）」與「擁有者在真的 Windows 上測」。前一半過了只代表邏輯對，不代表在 Windows 上能用。
   沒在真機驗證過的功能，交付時要在畫面與文件上照實寫（照 repo 既有的做法：`docs/security.md:321-322`）。
2. **不重疊的方法是「接點先行」**。這幾塊功能都要動同一批中樞檔（`manifest.py`、`scan.py`、`admin.py`、`loader.py`、`mcp.py`、`server.py`、`app.html`）。
   做法：第 0 波由**一個**代理（區塊 Z）先在中樞檔開好接點、建好各區塊的空殼檔；第 1 波各區塊**只寫自己的檔**；第 2 波再由 Z 接線。中樞檔從頭到尾只有 Z 改。
3. **新行為先掛在開關後面**。第 1 波裡任何會改變既有行為的東西（多出確認卡、拒裝沒列網域的工具、環境變數白名單…）預設＝舊行為，第 2 波整合時才由 Z 打開並修既有測試。
   這樣各分支的既有測試在第 1 波都維持綠的。

## 二、共用規則（每個區塊都要守）

ADR 第 0 節的 R1–R9 全部適用。實作上再加：

- 只在自己的 worktree 分支上 commit；不 merge、不 push；不碰別的區塊的檔。需要別人的檔改一行＝寫進自己的交接筆記的「接線請求」，不要自己改。
- **README.md、CHANGELOG.md、docs/AGENT.md、`src/synox/web/static/app.html` 只有主 session 能改。**
- 既有的門一個都不能變鬆：每個新來源最後都呼叫 `admin.stage`（`src/synox/packs/admin.py:329`），不另寫安裝路徑。
- 測試先寫。測試一律用假的：假 opener、假 `which`、暫存資料夾、假的子程序；**不在測試裡連網、不下載、不執行第三方套件**（repo 的家規：`docs/security.md:314`）。
- 給使用者看的字：白話繁體中文；一個檔一張字串表（Python 模組一個 `TEXT`、JS 檔開頭一個 `TEXT`）。
- `.bat` 只用 ASCII＋CRLF；`.ps1` 是 UTF-8 有 BOM＋CRLF（`docs/AGENT.md` 第 6 條）。這一輪預期不需要新的 `.bat`；真的需要就寫進接線請求給 Z。
- 路徑：不跟著資料夾外的路徑、符號連結、UNC 走；解壓與複製沿用 `admin.py:81-135`、`manifest.py:152-157` 的檢查，不自己重寫一套。
- 交付前：整套測試 `python -m pytest -q` 全過；`python scripts/prepublish_check.py --worktree-only` 的「目前的檔案」是零。
- 每個區塊交一份交接筆記 `docs/lab/eco-notes/<區塊代號>.md`：做了什麼、哪些沒驗證（標 待實測／待查）、接線請求、要 F 寫進文件的內容、擁有者要在 Windows 上測的清單。

### 非工程師測試（共同定義，每個有畫面的區塊都要過）

| 代號 | 內容 | 怎麼驗 |
|---|---|---|
| NE-1 | 主流程不出現術語 | 自動：`tests/test_eco_plain_text.py`（Z 寫）讀每個區塊的 `TEXT` 表。鍵名不是 `adv_` 開頭的字串，去掉全形小括號（…）裡的內容後，不得出現禁用詞：npm、Node、node_modules、lockfile、鎖檔、sandbox、沙盒、hash、雜湊、sha256、CSP、iframe、MCP、stdio、registry、token、JSON、argv、PATH、UAC、AppContainer、MXC、WFP、proxy、T0、T1、T2 |
| NE-2 | 每個失敗訊息都寫下一步 | 自動：同一支測試。鍵名 `fail_` 開頭的項目必須是「發生什麼＋下一步」兩段（兩段都不是空的） |
| NE-3 | 不開終端機就做得完 | 人工：擁有者（最好再找一位不寫程式的人）在真的 Windows 上照該區塊的「任務卡」做，不看文件、不問人、不開終端機。記下卡住的地方與原話 |
| NE-4 | 進階的東西收得起來 | 人工：主畫面上看不到「進階」區的內容，要自己點開 |

禁用詞清單放在測試檔裡一個地方，擁有者可以加。NE-1、NE-2 過了只代表沒有明顯的術語；**白話寫得好不好只有 NE-3 能回答**。

## 三、波次與先後

```
第 0 波（序列）
  擁有者：核准決定（至少「最要緊的六件事」與決定 34）；跑 Windows 探測腳本（決定 14）
  主 session：在 app.html 加掛載點與 include（一個 commit）
  區塊 Z：小修 Q1、Q3a；開接點；建空殼；寫接點測試與 NE-1／NE-2 的測試
        │
第 1 波（平行，各自的 worktree）
  A 匯入與套件名（含執行元件）   B 宣告、確認、提示標示   C1 隔離的共用部分與 Linux
  D 市集來源與信任               E 套件預覽               F1 SDK 指令
        │            （G 可以在每個區塊交付時各審一次）
第 2 波（序列）
  Z 接線（照各區塊的接線請求、打開開關、修既有測試）→ F2 文件 → 主 session 整合 → G 總審
        │
第 3 波（等擁有者的 Windows 實測結果與決定 11–13）
  C2 Windows 的隔離後端
```

| 區塊 | 開工前一定要有的決定 | 依賴 |
|---|---|---|
| Z | 34（小修）；19 的 a（Q3a） | 無 |
| A | 2、3、4、5、6、7、8、9、10 | Z 的接點；`network.hosts` 的格式（下面的合約） |
| B | 18、19、20、21、23 | Z 的接點 |
| C1 | 15、16、17 | Z 的接點 |
| C2 | **11、12、13、14**（要先有實測結果） | C1 |
| D | 24、25、26、27、28、35 | Z 的接點；E 的 `preview` 欄位名、A 的 `origin` 欄位名（合約） |
| E | 29、30、31、32 | Z 的接點 |
| F | 23、33 | F1 只依賴 Z；F2 要等 A–E 的交接筆記 |
| G | 無 | 被審的區塊已交付 |

決定 1（Hermes 是哪一個）只影響匯入器裡 Hermes 那張方言表；答案是「不是」的話，A 的其他部分不受影響。

## 四、接點合約（Z 在第 0 波做；簽名若要改，改這一節並通知各區塊）

空殼檔由 Z 建立（只有函式簽名、說明、「什麼都不做」的預設回傳），建立之後**歸該區塊所有，Z 不再改**。下表的簽名是提案，Z 定稿。

| 接點 | 中樞檔（Z 的） | 呼叫誰（空殼；歸屬） | 合約 |
|---|---|---|---|
| S1 宣告的新區塊 | `packs/manifest.py`（讀 pack.json 時）、新檔 `packs/ext.py` | `packs/origin.py`（A）、`packs/egress_decl.py`（C）、`packs/preview.py`（E）、`packs/skill_kind.py`（A） | `check(raw, kind, folder, strict) -> (值, [問題])`；結果放 `Manifest.ext["origin"｜"network"｜"preview"]`。pack.json 的欄位名固定：`origin`（§1.5）、`network.hosts`（§5.2）、`preview.entry｜cover｜title｜summary`（§7.2）、`kind: "skill"`（§1.2） |
| S2 門與報告 | `packs/admin.py` 的 `run_gates`（`:143`）、`summary_of`（`:161`） | 各區塊的 `gate(m, folder) -> [拒裝理由]`、`report(m, folder, data_dir) -> dict` | 報告多一個鍵 `eco`：`origin`（A）、`npm`（A）、`ai_text`（B）、`protection`（C）、`market`（D）、`preview`（E）。內容是可以轉 JSON 的資料，不放 HTML |
| S3 事件 | `packs/admin.py`（暫存、確認、安裝、移除、丟棄）、`packs/loader.py`（狀態改變） | `packs/audit.py`（D）：`record(data_dir, event, **fields)` | 只追加；不記密鑰與檔案內容。B（工具定義變了、出了幾張卡）、C（擋下的連線）、A（下載執行元件、建環境）也呼叫它 |
| S4 網頁 | `web/server.py`、新檔 `web/eco_api.py` | `web/api_import.py`（A）、`api_caps.py`（B）、`api_sandbox.py`（C）、`api_market.py`（D）、`api_preview.py`（E） | `/api/eco/<區>/…` 轉給 `handle(server, method, rest, query, data, user) -> Resp`，照 `/api/runtime/…` 的先例（`server.py:527`）；登入與 CSRF 由 `server.py` 先驗（`:329-335`）。預覽的四條路由（§7.3）轉給 `api_preview.serve(...)` |
| S5 執行 | `packs/loader.py`（`:597-606` 組子程序環境）、`packs/mcp.py`（`:856`、`:978-988`） | `sandbox.child_env(m, env, config)`（C）；`packs/mcp_pins.py`（B）：`observe(data_dir, m, listed) -> 放行的工具名`；`packs/node_runtime.py`（A）經 `envs.node_of` | 預設回傳＝現在的行為 |
| S6 指令與健康檢查 | `src/synox/__main__.py`、`src/synox/doctor.py` | `packs/market.py`（D）、各區塊的 `doctor_lines(config) -> [字串]` | `synox-sdk` 的子指令由 F 接：`sdk/importer.py` 的 `main(argv)`（A）、`sdk/preview_dev.py` 的 `main(argv)`（E） |
| S7 畫面 | `app.html`（**主 session**）：每個區塊一個空的掛載點 `<div id="eco-…">`，以及 `eco_*.js`／`eco_*.css` 的 include（沿用 `server.py:102-104` 的機制） | `static/eco_import.*`（A）、`eco_caps.*`（B）、`eco_sandbox.*`（C）、`eco_market.*`（D）、`eco_preview.*`（E） | 每個 JS 檔開頭一張 `TEXT`；只畫在自己的掛載點裡；資料從報告的 `eco.<鍵>` 與自己的 `/api/eco/<區>/` 拿 |

## 五、檔案歸屬總表（一個檔只有一個主人）

| 主人 | 檔案 |
|---|---|
| **主 session** | `README.md`、`CHANGELOG.md`、`docs/AGENT.md`、`src/synox/web/static/app.html`、`docs/lab/README.md` |
| **Z 接點** | `src/synox/packs/`：`manifest.py`、`scan.py`、`admin.py`、`loader.py`、`mcp.py`、`mcp_http.py`、`mcp_schema.py`、`tier.py`、`lock.py`、`upgrade.py`、新 `ext.py`；`src/synox/web/server.py`、新 `web/eco_api.py`；`src/synox/__main__.py`、`doctor.py`、`config.py`；`static/packdrop.js`、`packdrop.css`、`tools.js`；新 `tests/test_eco_seams.py`、`tests/test_eco_plain_text.py`；**所有沒有列在別的區塊底下的既有測試檔** |
| **A 匯入與套件名** | `src/synox/packs/envs.py`；新 `packs/origin.py`、`skill_kind.py`、`npm_lock.py`、`node_runtime.py`、`importing.py`；新 `src/synox/sdk/importer.py`；新 `web/api_import.py`、`static/eco_import.js`、`eco_import.css`；`examples/node-mcp-tool/`；`tests/test_envs.py`、新 `tests/test_eco_import*.py`、`test_eco_npm*.py`、`test_eco_node_runtime.py`、`tests/js/test_eco_import.js`；`docs/lab/eco-notes/A.md` |
| **B 宣告、確認、提示標示** | `src/synox/agent/` 整個資料夾（含新 `taint.py`）；新 `packs/ai_text.py`、`packs/mcp_pins.py`；新 `web/api_caps.py`、`static/eco_caps.js`、`eco_caps.css`；`evals/assistant/` 底下**新增**的題目檔（不改既有的）；`tests/test_agent*.py`、`tests/test_prompt_tail.py`、新 `tests/test_eco_confirm*.py`、`test_eco_ai_text.py`、`test_eco_mcp_pins.py`；`docs/lab/eco-notes/B.md` |
| **C 隔離、密鑰、連外名單** | `src/synox/sandbox.py`、`src/synox/packs/container.py`、`packs/secrets.py`；新 `src/synox/egress.py`、`src/synox/sandbox_win.py`、`packs/egress_decl.py`；新 `web/api_sandbox.py`、`static/eco_sandbox.js`、`eco_sandbox.css`；`docs/lab/tools/windows-sandbox-probe/`；`tests/test_sandbox.py`、`tests/test_container_sandbox.py`、新 `tests/test_eco_sandbox*.py`、`test_eco_egress*.py`；`docs/lab/eco-notes/C.md` |
| **D 市集來源與信任** | `src/synox/wizard/tools.py`、`src/synox/packs/library.py`；新 `packs/market.py`、`packs/audit.py`；新 `web/api_market.py`、`static/eco_market.js`、`eco_market.css`；新 `tests/test_eco_market*.py`、`test_eco_audit.py`；`docs/lab/eco-notes/D.md`；**另一個 repo SYNOX_Libs**：`scripts/build.py`、新的簽章腳本、它的 `docs/adr/`、它的測試（另開分支，不在這個 worktree） |
| **E 套件預覽** | 新 `packs/preview.py`、`web/api_preview.py`、`static/eco_preview.js`、`eco_preview.css`、`src/synox/sdk/preview_dev.py`；新 `tests/test_eco_preview*.py`、`tests/js/test_eco_preview.js`、`tests/fixtures/eco_preview/`；`docs/lab/eco-notes/E.md` |
| **F SDK 與文件** | `src/synox/sdk/__init__.py`、`__main__.py`、`author.py`；`sdk/`（`synox_sdk.py` 是產生的，改正本再跑 `scripts/build_synox_sdk.py`）、`scripts/build_synox_sdk.py`；`examples/`（`node-mcp-tool/` 除外）；`docs/sdk.md`、`docs/tools.md`、`docs/pack-format.md`、`docs/security.md`、`docs/install-packs.md`、`docs/ecosystem.md`、新 `docs/quickstart-tool.md`、`docs/import.md`、`docs/pack-preview.md`；`tests/test_sdk*.py`、`tests/test_examples.py`、`tests/test_pack_docs.py`；`docs/lab/eco-notes/F.md` |
| **G 獨立審查** | 只有 `docs/lab/eco-review/` 底下的報告。**不改任何其他檔** |

`vendor/` 沒有人能改（「vendor 沒有改過」是現有規則）。環境變數白名單要動的是 SYNOX 這一側的呼叫（S5），不是 `vendor/isdtelekit/jobs/`。

---

## 六、各區塊

### 區塊 Z：接點與整合（第 0 波、第 2 波；序列）

**做什麼**：第 0 波＝小修 Q1、Q3a＋第四節的接點＋空殼＋兩支共用測試。第 2 波＝照各區塊的接線請求改中樞檔、打開開關、修既有測試。Z 不寫任何功能。

**先寫的測試**

- `tests/test_eco_seams.py`：空殼都在的時候，`admin.stage` 對一個既有的範例 pack 的報告，除了多一個空的 `eco` 鍵以外跟現在一模一樣；每個接點用假的區塊函式換進去，確認被呼叫到、回傳的拒裝理由真的會擋下安裝。
- `tests/test_eco_plain_text.py`：NE-1、NE-2（先對空的 `TEXT` 表通過，之後各區塊填字時自動生效）。

**驗收**

1. 第 0 波結束時整套既有測試全過，行為跟 `dev` 一樣（除了已核准的小修）。
2. 每一個新來源都只能經 `admin.stage` 進來：測試列舉 `eco` 的各個入口，確認沒有任何一條路會在沒有暫存 token 的情況下寫進 `packs/`。
3. 第 2 波結束時：所有開關照擁有者的決定打開；整套測試全過；`prepublish_check` 零發現。

**擁有者要在 Windows 上測的**：第 0 波後照平常的方式裝一個現有的工具（網頁上傳、點兩下、拖放各一次），確認跟以前一樣。

### 區塊 A：匯入與套件名（含執行元件）

**做什麼**（§1、§2、§3）

1. 新種類「純文字技能」`kind=skill`：只有說明文字；資料夾裡有程式檔就拒；載入後出現在技能清單。
2. 匯入器 `sdk/importer.py`（只用標準函式庫）：讀 Agent Skills 資料夾與 MCP 設定的一筆，輸出標準 pack 資料夾；`origin` 區塊；OpenClaw 與 Hermes 各一張方言表。
   使用者端入口 `packs/importing.py`：只收純文字技能與 MCP 伺服器，產出 `.synoxpack` 的位元組交給 `admin.stage`。附程式的技能只在 `synox-sdk import` 產生草稿。
3. 鎖檔：`packs/npm_lock.py`——從套件名產生鎖檔（§2.1 第 1–5 步）、嚴格檢查（每項都要有官方 `resolved` 與 `integrity`）、列出有安裝腳本的套件、建完檢查。
4. 執行元件：`packs/node_runtime.py`——下載官方的 Node 壓縮檔、對寫死的雜湊、解到 `data/node/<版本>/`；`envs.py` 改用它（含同一包裡的 npm）。
5. 畫面 `eco_import`：「從其他助理的技能匯入」；「進階」裡的「用套件名安裝」；「下載並繼續」。

**先寫的測試**

- 匯入：三家各一個純文字技能的假資料夾 → 產出的 pack 過得了第 1、2 關；有 `scripts/` 的在使用者端被拒；`metadata.*.install` 與正文的「Prerequisites」**沒有任何程式路徑會執行它**（測試確認只變成報告上的文字）；
  MCP 設定裡的金鑰值不會出現在產出的 pack 裡；壓縮檔裡的 `..`、絕對路徑、符號連結、UNC 被拒；超過大小與檔數上限被拒。
- 套件名：網址、git、`file:`、路徑、別名都被拒；合法名字產生的 npm 指令列跟 §2.1 第 3 步一字不差（假的子程序，只比 argv 與環境變數）。
- 鎖檔檢查：少了 `resolved`、少了 `integrity`、不是官方來源、有 `link` 各一個假鎖檔 → 都拒；`hasInstallScript` 的清單讀得對；`inBundle` 的項目照合約處理（規則先對 [NP2] 原文，寫進交接筆記）。
- 建完檢查：假的 `node_modules`（有 `binding.gyp`、沒有 `.node`）→ 標「不能用」並帶原因與下一步。
- 執行元件：假 opener 回傳一個小壓縮檔——雜湊對＝解出來；雜湊不對＝刪掉、不解壓、回 `fail_` 訊息；壓縮檔裡有逃出資料夾的路徑＝拒；沒按「下載並繼續」＝不連網（測試確認 opener 沒被叫到）。

**驗收**

1. 上面的測試全過；`kind=skill` 的 pack 能經網頁上傳、看報告、確認、載入（用假 AI 跑一輪，`skill_read` 讀得到）。
2. 任何匯入路徑產出的東西都有 `origin`，而且 `origin` 的字不出現在給 AI 的系統提示與工具說明裡（測試比對整份提示）。
3. 沒有任何一條路會在按確認之前建立 `node_modules` 或下載套件本體。
4. 非工程師測試：NE-1、NE-2 自動過。任務卡（NE-3）：(a) 把一個別的助理的技能資料夾（測試用、純文字）匯入並裝起來；(b) 裝一個需要執行元件的工具庫工具，中途只按畫面上的按鈕；(c) 拔掉網路再做 (b)，照畫面寫的下一步恢復。

**擁有者要在 Windows 上測的**

- 任務卡 (a)(b)(c)。
- 下載執行元件後：`data/node/<版本>/` 裡有 `node.exe`；系統的 PATH 沒有被改；移除 `data/` 後不留東西。
- 「進階 → 用套件名安裝」裝一個純 JS 的 MCP 伺服器，走完報告、確認、第一次連線。**鎖檔流程在 Windows 上從來沒跑過**（研究只在 Linux 實測），這一步失敗的話把畫面與 log 帶回來。
- 裝一個已知「不跑安裝腳本就壞」的套件（例如會用到 better-sqlite3 的），確認畫面講的是「不能用、原因、下一步」，而不是到用的時候才出錯。

### 區塊 B：宣告、確認、提示標示

**做什麼**（§5）

1. 小修 Q3b、Q4（組提示時截斷）。
2. 確認卡的新規則 C2、C3（開關後面）：`agent/taint.py` 記「這一輪讀過不可信內容」；卡片內容照 §5.4（固定樣板、參數全顯示、空白摺疊提示、會送去哪）。
3. 「AI 會讀到的內容」`packs/ai_text.py`：SKILL.md 全文、每個指令的說明與欄位提示、MCP 的工具說明 → 報告的 `eco.ai_text`；樣式提醒（沿用 `risk_flags`，只標不擋）。
4. 釘 MCP 的工具定義 `packs/mcp_pins.py`（§5.6）：第一次連線等核准、之後比對、變了就停用那個工具。
5. 第三方的介紹搬進有分隔符的區塊（開關後面，預設關）；用現有評測量工具觸發 F1 與第 4 關通過率，數字寫進交接筆記。
6. 畫面 `eco_caps`：確認卡的新樣子、報告裡「AI 會讀到的內容」、工具定義變了的通知與新舊對照。

**先寫的測試**

- 出卡規則的真值表：{官方／第三方} × {READ／WRITE／DANGER} × {讀過／沒讀過不可信內容} × {有沒有宣告連網}，每一格預期出不出卡（§5.3）。
- 污點：第三方工具的結果、第三方技能的 `skill_read`、宣告連網的工具的結果會設；新的一輪會清。
- 卡片文字：主句不含作者寫的說明；一長串空白顯示成「（中間有 N 個空白）」；2000 字的參數完整可見。
- 釘定義：第一次連線前 AI 的工具清單裡沒有這些工具；說明、schema、annotations 任一變動都偵測得到；變動後那個工具被拿掉、有稽核事件；pack 升級版本後要重新核准。
- 提示：多行、超長、夾控制字元的 `summary` 與 frontmatter 進提示前被截成一行；既有的官方工具的提示**一個字都不變**（跟 `dev` 的輸出比）。
- 新增評測題（只放假資料）：工具說明裡夾指令、`summary` 裡夾指令、說明要 AI 把上一個工具的結果送出去。

**驗收**

1. 上面的測試全過；開關全關時整套既有測試與評測結果跟 `dev` 相同。
2. 開關打開時：真值表每一格符合；AI 永遠沒有辦法呼叫「改設定／裝工具／放行隔離」（測試列舉工具清單）。
3. 分隔符那一項附評測數字（開與關各一次）；沒有量就不能建議預設打開。
4. 非工程師測試：NE-1、NE-2 自動過（確認卡與通知的字都在 `TEXT` 表裡）。任務卡：(a) 請 AI 用一個第三方工具新增一筆資料，看懂確認卡在問什麼、按同意；(b) 遇到「說明跟上次不一樣」的通知，能說出發生什麼事、下一步是什麼；(c) 在報告裡找到並打開「AI 會讀到的內容」。

**擁有者要在 Windows 上測的**

- 任務卡 (a)(b)(c)，Telegram 與網頁各一次（確認卡兩邊都有）。
- 用平常的方式用一天，數出了幾張卡（設定頁的安裝紀錄會有數字）；覺得太多就回報是哪一種卡。
- **用真的模型**（尤其本地小模型）試：把分隔符的開關打開後，AI 還找不找得到對的工具。這一項自動測試回答不了。

### 區塊 C：隔離、密鑰、連外名單

**C1（第 1 波）做什麼**（§6.2、§6.4、§6.5）

1. `Grants` 補齊（讀、寫、環境變數白名單、網路三態、主機名單）；每個後端回答「擋不擋得住檔案／直連／只連名單／要不要先按系統同意」；算出保護等級（完整／基本／沒有）與白話。
2. `network.hosts` 的宣告檢查 `packs/egress_decl.py`（確切主機名；不收萬用字元與 IP）。
3. 連外代理 `src/synox/egress.py`（標準函式庫）：每個工具一個入口；只到名單上的主機的 443；解析後是回送／內網／link-local 位址的拒；擋下的記稽核。
4. Linux：bwrap 改成「拿掉網路命名空間＋unix socket 接代理」（宣告連網時也一樣，補掉 `sandbox.py:173-174` 的洞）；容器與 systemd 後端照同一個形狀。
5. 環境變數白名單 `sandbox.child_env`（開關後面；先警告一個版本）。
6. 政策：等級「沒有」的電腦上，第三方 T2 工具預設不執行、可逐個放行（開關後面）。畫面 `eco_sandbox`：每個工具的保護等級、放行、擋下的連線通知。
7. 更新探測腳本的說明；**為 MXC 寫探測腳本之前要先查出 `wxc-exec.exe` 的來源**（現在查不到）。

**C2（第 3 波）做什麼**（§6.3）：照擁有者的實測結果與決定 11–13 寫 Windows 後端（`src/synox/sandbox_win.py`）。**實測結果回來之前不寫。**

**先寫的測試**

- 代理（只走 127.0.0.1：真的在本機起一個，連的對象是測試自己開的假伺服器，不出這台機器）：名單上的主機通；不在名單上的回拒絕；IP 字面值拒；名單上的主機名被假的解析器指到 `127.0.0.1` 時拒；工具甲的入口用不到工具乙的名單。
- 後端 argv（照 repo 既有的做法，只比組出來的 argv）：宣告連網時 bwrap 的 argv **有** `--unshare-net`，而且掛了代理的 socket。
- 環境變數：白名單開的時候，啟動 SYNOX 前設的任意變數不會進子程序；宣告的密鑰名照樣進得去；`SYNOX_CONFIRM_TOKEN` 照舊。
- 保護等級：每個後端（含 `none`、jobobject）算出的等級與白話；`kind=python` 一律算「沒有」。
- 政策：等級「沒有」＋第三方 T2 → 不執行，回的訊息有下一步；放行後才執行；放行只對那一個工具。

**驗收**

1. 上面的測試全過；開關全關時既有測試不變。
2. 在這台 Linux 開發機上真的跑一次（不是只比 argv）：隔離裡的程式連得到名單上的主機、連不到別的主機、連不到主機的 `127.0.0.1`。做不到就照實寫原因
   （研究機器沒有 bwrap、不是 systemd 開機；一般使用者的 user namespace 可能被 AppArmor 擋：**待實測**），不能寫成通過。
3. 文件與畫面沒有任何一句說「Windows 已經有隔離」——直到 C2 做完而且擁有者測過。
4. 非工程師測試：NE-1、NE-2 自動過（「隔離」可以用，「沙盒」不行）。任務卡：(a) 在工具頁看懂一個工具現在的保護等級；(b) 遇到「這台電腦沒辦法把這個工具隔開，所以先不執行」，照畫面的下一步決定要不要放行；(c) 看懂「擋下來了」的通知。

**擁有者要在 Windows 上測的**

- **先做（決定 14）**：照 [探測腳本的說明](tools/windows-sandbox-probe/README.md) 跑 `win-env-probe.ps1` 與 `win_appcontainer_probe.py`（約半小時），把兩個結果檔帶回來。**這兩個腳本本身也沒有在 Windows 上跑過**，腳本出錯請把錯誤原樣帶回來。
- C1 交付後：任務卡 (a)(b)(c)；確認現有的工具在環境變數白名單打開後還能用（哪一個壞了、缺哪個變數）。
- C2 交付後：每條後端各做一次「讀得到自己的資料夾、讀不到文件資料夾、連得到名單上的網站、連不到別的網站、連不到 `127.0.0.1:11434` 與 `:8830`」；記下有沒有跳出系統的同意視窗、跳了幾次。

### 區塊 D：市集來源與信任

**做什麼**（§4、§7.7）

1. `packs/market.py`：從寫死的官方網址抓目錄（只在按下按鈕時）、大小上限、驗 ed25519 簽章（內建兩把公鑰）、序號只增不減、讀舊格式的本機目錄（沒有新欄位＝最低信任）。
2. 審查等級 × 檢查結果的表（§4.2）；新發行者只能是沒有程式的條目；第三方的 `kind=python` 不收（決定 35）。
3. 撤銷：比對已裝的工具，命中的停用（不刪）、通知、記稽核。
4. 稽核紀錄 `packs/audit.py`（只追加）與白話的「安裝紀錄」。
5. 畫面 `eco_market`：「看看有什麼工具」（封面、等級的白話、來源）、「檢查更新」、撤銷通知、安裝紀錄。下載下來的檔交給 `admin.stage`（R1）。
6. SYNOX_Libs（另一個 repo）：`index.json` 的新欄位、序號、撤銷清單、簽章腳本、金鑰輪換的步驟文件。**私鑰不進任何 repo**；測試用臨時產生的金鑰。

**先寫的測試**

- 簽章：對的過；改一個位元組拒；用不在內建清單裡的鑰簽的拒；備用鑰簽的過。序號比記住的小拒。
- 連線：目的地不是寫死的主機就不連（含轉址到別的主機）；超過大小上限中斷；沒按按鈕時 opener 沒被叫到；**沒有任何網址參數能改目的地**（測試試 `?library=`、`?pack=` 帶網址）。
- 等級表每一格；`listed` 的條目帶程式＝拒；第三方的 `kind=python`＝拒。
- 撤銷：命中的工具狀態變停用、資料夾還在、有稽核事件、通知的字有下一步；擁有者重新打開後不會被同一筆撤銷再關一次（除非目錄換了新的一筆）。
- 稽核檔：只追加；不含密鑰樣式的字（用現有的密鑰偵測樣式掃一次）。
- 舊目錄（現在的格式）照樣讀得了、裝得了。

**驗收**

1. 上面的測試全過；離線（沒有網路）時現有的本機工具庫流程不變。
2. 從市集裝的工具看到的報告，跟自己上傳同一個檔看到的報告，檢查項目完全一樣（多的只有來源與等級的說明）。
3. 沒有任何「免確認」的路：等級最高的官方工具也要看報告、按確認。
4. 非工程師測試：NE-1、NE-2 自動過。任務卡：(a) 打開「看看有什麼工具」，挑一個裝起來；(b) 說得出「官方出品／有人看過內容／只是上架」的差別；(c) 遇到下架通知，能決定移除或繼續用；(d) 在安裝紀錄裡找到上星期裝了什麼。

**擁有者要在 Windows 上測的**

- 任務卡 (a)–(d)。
- **金鑰**：照步驟文件在離線的電腦上產生金鑰、簽一份目錄、演練一次換鑰（這件事只有擁有者能做）。
- 公司或學校網路（有代理的環境）抓不抓得到目錄；抓不到時畫面寫的下一步有沒有用。

### 區塊 E：套件預覽

**做什麼**（§7）

1. `packs/preview.py`：`preview` 欄位的檢查（路徑規則沿用 `web.panel` 的）、白名單式的 HTML 檢查器（§7.4）、封面的檔頭判定（PNG／JPEG／WebP；不收 SVG）、大小上限。
2. `web/api_preview.py`：四條唯讀路由與標頭（§7.3）。
3. 畫面 `eco_preview`：`<iframe sandbox="">`、外框的固定說明、固定高度；確認鈕不在同一個畫面。
4. `sdk/preview_dev.py`：作者端的臨時伺服器（只綁 127.0.0.1、同一組標頭、同一個外框）。

**先寫的測試**

- 檢查器：§7.4 列的每一種禁止項各一個假檔 → 拒並帶行號；大小寫與空白變形（`<ScRiPt`、`on click =`、`url (`）也拒；合法的排版＋內嵌樣式＋`data:` 圖過。
- 路由：回應標頭跟 §7.3 一字不差；檔名來自 manifest，網址帶 `..`、編碼過的斜線、別的檔名都拿不到別的檔；`preview.entry` 是指向資料夾外的符號連結＝拒；沒登入＝401（或照實測結果改成短效票，見下）。
- 封面：副檔名是 `.png`、內容是 SVG 或 HTML → 拒；`Content-Type` 來自檔頭。
- `preview.title`／`summary` 不出現在給 AI 的任何文字裡。
- JS（`tests/js/`）：建出來的 iframe 的 `sandbox` 屬性是空字串；畫面上有預覽時沒有確認鈕。

**驗收**

1. 上面的測試全過；沒有 `preview` 的 pack 行為不變。
2. 預覽的回應裡沒有任何 SYNOX 的資料（測試比對回應＝檔案內容）。
3. 交接筆記列出所有只能在真的瀏覽器驗的項目與預期。
4. 非工程師測試：NE-1、NE-2 自動過。任務卡：(a) 裝工具前打開「看看作者的介紹」，看完回到報告按確認；(b) 說得出外框那句話的意思（這是作者寫的，SYNOX 沒有驗證）。

**擁有者要在 Windows 上測的**（真的瀏覽器：Edge、Chrome、Firefox 各一次）

- 用 `tests/fixtures/eco_preview/` 裡的「壞預覽」（測試用，內容無害：想跑腳本、想載外部圖、想送表單、想自動轉址、想開新視窗、點外部連結）**直接繞過檢查器放進暫存**（開發用的旗標），確認瀏覽器真的都擋下來——這是在驗 CSP 與 sandbox，不是驗檢查器。
- 隔離的 iframe 第一次載入時有沒有顯示內容（＝瀏覽器有沒有帶登入狀態）。沒有的話回報，E 改成短效票。
- 直接把預覽的網址貼到網址列開：沒有腳本、碰不到 SYNOX。
- CSS 動畫在沒有腳本時會不會動。

### 區塊 F：SDK 與文件

**F1（第 1 波）做什麼**（§8）：小修 Q8；`new`／`test`／`build`／`preview` 四個別名；獨立套件也帶 `synox-sdk` 指令（只做格式檢查，訊息講清楚跟完整檢查的差別）；
`run` 支援 mcp（握手、列工具、叫一個）與 python；接上 `import`（A）與 `preview`（E）的子指令；把 `examples/` 整理成可以直接複製的範本。

**F2（第 2 波）做什麼**：照 A–E 的交接筆記寫文件——`docs/pack-format.md`（新種類、`origin`、`network.hosts`、`preview`）、`docs/security.md`（Q7、新的確認規則、隔離的現況照實寫）、
`docs/install-packs.md`、`docs/ecosystem.md`（「之後的路」哪些做了）、新的 `docs/quickstart-tool.md`（一頁）、`docs/import.md`、`docs/pack-preview.md`。
把要主 session 寫進 README／CHANGELOG／docs/AGENT.md 的內容列在 `docs/lab/eco-notes/F.md`，**自己不改那三個檔**。

**先寫的測試**

- 別名跟原指令的輸出相同；`synox-sdk --help` 列得出全部子指令。
- 獨立套件：在看不到核心的環境裡（測試用子程序，`sys.path` 只有 `sdk/`）`synox-sdk new`→`build` 走得完，而且沒有 import 核心。
- `run` 對 `examples/node-mcp-tool` 用假的伺服器程序走完握手與一次呼叫；對 kind=python 的範例跑一個指令。
- 範本不再產生 `panel.html`；`tests/test_examples.py` 每個範例照樣過第 1、2 關。
- 一頁入門裡的每一個指令都在測試裡照打一次（文件跟程式不會走鐘）。

**驗收**

1. 上面的測試全過。
2. 「從空資料夾到打包好一個工具」最多 4 個指令（`new`、`test`、`build`，加一個選用的 `preview`），測試照做一次。
3. 文件裡每一句講到 Windows 隔離、瀏覽器行為、真的模型的地方，都標了有沒有實測過。
4. 非工程師測試：SDK 的對象是工具作者，不適用 NE-3；但 `docs/install-packs.md` 是給使用者看的，要過 NE-1 的禁用詞檢查（測試讀那一份文件的主流程段落）。

**擁有者要在 Windows 上測的**：照 `docs/quickstart-tool.md` 從零做一個工具並裝進 SYNOX，**計時**（「5 分鐘」從來沒有量過）；記下第一個看不懂的地方。

### 區塊 G：獨立審查（只回報，不改檔）

**做什麼**：每個區塊交付時審一次，第 2 波整合後總審一次。只寫 `docs/lab/eco-review/<區塊>-<日期>.md`。**不改程式、不改別人的文件**；發現問題只回報給主 session。

**審什麼**

1. R1–R9 有沒有被打破：有沒有不經 `admin.stage` 的安裝路；有沒有在確認之前執行或下載第三方的東西；有沒有新的連網點不在寫死的清單裡；有沒有新的監聽不是 127.0.0.1。
2. 歸屬：`git diff --stat` 對照第五節，有沒有人改了不是自己的檔。
3. 每一條驗收有沒有對應的測試；測試有沒有真的在驗（把被測的那一行註解掉，測試會不會紅——抽查）。
4. ADR §9 的威脅表逐列：對策有沒有做、剩下的風險有沒有照實寫在文件與畫面上。
5. 標籤有沒有被洗掉：研究裡「待實測／待查」的事，有沒有在程式註解、文件、畫面裡被寫成已經確定。
6. 給使用者看的字：照 NE-1、NE-2 之外，再人工讀一遍主流程，挑出讀不懂的句子。

**驗收**：每份報告分「一定要修／建議修／只是提醒」，每一條有 `檔案:行號`；報告自己不含任何修改。

---

## 七、可以單獨核准的小修（決定 34）

這些是研究找到、跟大功能無關的缺口。每一條可以單獨核准、單獨一個 commit。由該檔的主人做（所以沒有檔會有兩個主人），放在那個區塊的最前面。

| # | 問題 | 依據 | 怎麼修 | 誰做 | 還要哪個決定 | 沒驗證的 |
|---|---|---|---|---|---|---|
| Q1 | 從對話頁把工具檔拖進來，會跳到設定頁但**可能停在別的分頁**，報告在看不到的分頁裡 | `src/synox/web/static/packdrop.js:119` 設的是 `#settings` 不是 `#settings:packs`；`app.html:859-862`、`1155-1160` 對沒有分頁名的 `#settings` 沿用上次的分頁 | 改成跳到 `#settings:packs`；補 `tests/js/test_packdrop.js` | Z | 無 | 畫面行為**待實測**（只讀過程式） |
| Q2 | 鎖檔裡沒寫 `resolved` 或沒有 `integrity` 的項目照樣過 | `src/synox/packs/envs.py:449`、`466-468`；**已實測**：刪掉 `integrity` 後 `npm ci` 照裝、回 0 | 每一項都要有官方 `resolved` 與 `integrity`。新裝的拒；已經裝的照跑、doctor 提醒；重建環境時拒並寫下一步 | A | 無（「已裝的重建時拒」太嚴的話擁有者可改成只提醒） | `inBundle` 項目的規則**待查** |
| Q3a | `pack.json` 的 `title`／`summary` 沒有長度限制、可以多行 | `src/synox/packs/manifest.py:1057-1059` | 第 1 關：一行、`title` ≤ 40 字、`summary` ≤ 200 字、不准控制字元（新裝的拒） | Z | 19 的 a；上限是提案值 | 現有工具庫裡有沒有超過的：做之前先掃一次 |
| Q3b | 上面兩個欄位**原樣進系統提示**，沒有分隔符 | `src/synox/agent/loop.py:265-267` | 組提示時把換行變空白、截到上限（已經裝的也生效，不擋任何工具） | B | 19 的 a | 能不能真的帶偏模型**待實測** |
| Q4 | SKILL.md 開頭的 `description`／`when` 沒有長度上限就進系統提示 | `src/synox/agent/skills.py:39-51`、`76-82` | 組提示時截斷（`description` 200 字、`when` 120 字，提案值）、拿掉控制字元 | B | 19 的 a | 同上 |
| Q5 | MCP 類的工具不能用鎖檔，只能寫 `npx`（每次從網路抓、版本沒鎖） | `src/synox/packs/manifest.py:1145-1146`；`src/synox/packs/scan.py:1558` | 放寬成 `kind=mcp`（stdio）也能用 `runtime.node: "auto"`＋鎖檔；`npx` 的紅字提醒照留。小修裡最大的一條（`mcp.py:856` 已經會帶 Node 的環境） | Z（宣告與啟動）＋A（環境與範例 `examples/node-mcp-tool`） | **5** | Windows 上沒跑過 |
| Q6 | 需要安裝腳本的套件裝完是壞的，但 SYNOX 說「環境建好了」，要到第一次用才出錯 | `src/synox/packs/envs.py:627-628`；**已實測** 5 個套件（§2.2） | 報告列出有安裝腳本的套件（讀鎖檔的 `hasInstallScript`，離線）；建完檢查，壞了就標「不能用」並寫原因與下一步 | A | 7 的 a | 檢查規則（有 `binding.gyp`、沒有 `.node`）只對過 5 個套件 |
| Q7 | 文件寫「npm 照 `integrity` 驗」，其實只有鎖檔寫了才驗 | `docs/security.md:389-390` | 跟 Q2 一起改文字 | F | 無 | — |
| Q8 | SDK 的範本預設產生一個「同源、能跑腳本」的面板，等於教新作者做完全信任的畫面 | `src/synox/sdk/__init__.py:316`、`336` | 範本不再預設產生面板（要的人自己加） | F | 23 的 c | — |
| Q10 | 找系統的 Node 只看有沒有，不看版本 | `src/synox/packs/envs.py:236-237` | doctor 顯示版本、太舊就提醒。決定 8 選「SYNOX 自己管」的話，這一條被區塊 A 取代，可以不做 | A | 無 | — |

**還不能核准的**（要先實測才知道該不該修、怎麼修）：

- 建環境時保留了 `HOME`／`USERPROFILE`，使用者的 `~/.npmrc` 可能影響 `npm ci`（`envs.py:56-59`）。影響多大**待實測**。
- bwrap 後端在工具宣告連網時不隔離網路，工具連得到本機的 11434 與 8830（`src/synox/sandbox.py:173-174`）。這不是小修（要有連外代理），在區塊 C1。
- MCP 的工具說明每次連線都可以無聲換掉（`src/synox/packs/mcp.py:978-988`）。這不是小修，在區塊 B 第 4 項。

（沒有 Q9：原本編給「工具說明無聲換掉」，後來歸到區塊 B。）

## 八、擁有者決定清單

只有一份清單：[研究第七節](2026-11-13-ecosystem-security-research.md#七要擁有者決定的事)（35 題，每題有選項、建議、後果）。ADR 第 11 節有一張對照表。這裡只列「不先定，哪個區塊開不了工」。

| 先定這些 | 才能開始 |
|---|---|
| 34（小修先做）、19 的 a | 第 0 波 |
| **14**（先跑 Windows 探測）→ **11、12、13** | C2（Windows 後端）。這是整個計畫裡等最久的一條，建議第 0 波就跑探測 |
| **2**、3、4、**8**、5、6、7、9、10；**1** 只影響 Hermes 的方言表 | A |
| 18、19、20、21、23 | B |
| 15、16、17 | C1 |
| 24、**25**、26、27、28、35 | D |
| **29**、30、31、32 | E |
| 23、33 | F |
| 22（另一個 AI 掃文字） | 建議這一輪不做，沒有區塊在等它 |

## 九、這份計畫沒有驗證的事

- 接點的簽名是照讀程式的結果提的，**沒有試寫過**；Z 動手後可能要調整（調整時改第四節）。
- 「第 1 波各分支的既有測試都維持綠的」依賴「新行為掛在開關後面」這條紀律；有區塊做不到時要先講，不要硬改既有測試。
- 各區塊的工作量沒有估時。
- SYNOX_Libs 那個 repo 的分工只列了要改什麼，沒有對過它現在的測試與發佈流程。
- 所有 Windows、瀏覽器、真的模型的行為（見各區塊「擁有者要在 Windows 上測的」）。
