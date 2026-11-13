# 第 3 階段研究：接上 OpenClaw／Hermes 生態、技能市集、沙盒與安全

- 日期：2026-11-13
- 狀態：研究完成，等擁有者看。這份只寫「查到什麼」；「要怎麼做」在 [ADR 0022](../adr/0022-ecosystem-bridge-and-sandbox.md)（提案），「怎麼分工」在 [實作計畫](2026-11-13-ecosystem-implementation-plan.md)。
- 對象：SYNOX 維護者（工程師）。
- 來歷：三個研究代理各寫一份報告（A 上游生態與授權、B Windows 沙盒與 npm、C 提示注入與預覽與 SDK），這份是規劃階段合併後的稿。三份報告都只讀 repo（分支 `dev`），沒有改程式。
- 規劃階段另外做的：把會影響決定的程式事實自己對過一次（第四節標「規劃階段複查」的列），補查了 3 個外部缺口（第九節）。
- Windows 實測腳本：[tools/windows-sandbox-probe/](tools/windows-sandbox-probe/)（**還沒有在 Windows 上跑過**）。

## 怎麼讀這份文件

每一句結論後面有標籤與來源。來源是 `檔案:行號`（SYNOX 自己的程式與文件，路徑相對於 repo 根目錄）或代號（對照表在第十節，每個代號都有網址）。

| 標籤 | 意思 |
|---|---|
| **已查證** | 開到一手來源讀到的：官方 repo 的檔案、官方文件（或它在 GitHub 上的原始檔）、官方 advisory、套件 registry 的 API、SYNOX 自己的檔案 |
| **已實測** | 研究階段在一台 Linux 雲端機器上真的跑過（Ubuntu 24.04、Node 22.23.4、npm 10.9.9） |
| **待查** | 只有二手報導或搜尋摘要，原文這次開不到；數字照報導寫，還沒對過原文 |
| **推測** | 從已查證的事實推出來的，沒有來源直接這樣寫 |
| **待實測** | 要動手試才知道（Windows 真機、真的瀏覽器、真的模型） |
| **查不到** | 找過，沒有找到 |

三個限制：

1. **研究環境的網路只開了一部分網站。** 開不到的有：`docs.openclaw.ai`、`openclaw.ai`、`koi.ai`、`snyk.io`、`unit42.paloaltonetworks.com`、`invariantlabs.ai`、`nvd.nist.gov`、`thehackernews.com`、`gnu.org`、`arxiv.org`、`simonwillison.net`、`learn.microsoft.com`、`docs.docker.com`、`docs.npmjs.com`、`openai.com`、`developers.openai.com`、`modelcontextprotocol.io`、`developer.mozilla.org`、`html.spec.whatwg.org`、`code.visualstudio.com`、`pnpm.io`、`bun.sh`、`chromium.googlesource.com`、`genai.owasp.org`。官方文件一律改讀**同一份文件在 GitHub 上的原始檔**；資安事件的原始報告（Koi、Unit 42、Snyk、Cisco、Censys、Trail of Bits）與 arXiv 論文只有搜尋摘要，一律標「待查」。
2. **網頁是經過一個小模型讀完再轉述的。** 文中的英文引句是它回報的原文；對外引用之前請再對一次原始檔。
3. **Windows 上的一切行為都沒有實測**（研究機器是 Linux）。主題 4 裡 Windows 的每一條都是文件上的說法。

---

## 一、結論先講

1. **「Hermes」就是 Nous Research 的 Hermes Agent**（`NousResearch/hermes-agent`）。SYNOX 的 `docs/ui/redesign-notes.md` 寫的「8 套主題和字型選擇器、網頁終端機、金鑰只顯示有填」跟它的 dashboard 文件四項全對得上。**已查證** [SX1][H9]（仍請擁有者點頭一次，決定 1）
2. **兩個上游都是 MIT；ClawHub 上的技能一律 MIT-0。** 匯入、轉換、再散布在授權上可以。真正的限制是名字：npm 的 `openclaw-core`、`hermes-core` 都已經被不相干的人佔走。**已查證** [O1][H1][C2][N1][N2]
3. **沒有「上游的沙盒」可以拿來擋惡意技能。** 兩邊都只有「把 AI 下的指令丟進容器」的選配功能，預設都關，而且兩邊官方文件都明寫 plugin 是「跟主程式同等信任的程式碼」。**已查證** [O2][O5][H3]
4. **不需要做 core。** 兩個上游互接對方的東西時，用的就是「匯入內容＋MCP」，沒有人做對方的 core；OpenClaw 的 plugin SDK 有 352 個匯出子路徑、官方自稱全部 experimental。**已查證** [O10][H10][O11][N3]
5. **只靠掃描的市集擋不住。** ClawHub 加了 VirusTotal 與自家掃描後仍被繞過（待查 [X3]）；兩個上游的官方文件都說掃描只是輔助（已查證 [C5][H3]）；Hermes 的掃描器自己還出過 CVE（已查證 [H13]）。有效的是結構：來源白名單、釘雜湊、簽章、新來源最低信任、更新列差異、能撤銷。
6. **Windows 是現在最弱的一環，而且候選名單要更新。** SYNOX 在 Windows 的預設後端是 `none`（不是 jobobject）。**規劃階段複查** `src/synox/sandbox.py:465-467`。2026 年多了兩條路：Windows 11 內建的 **MXC**（2026-10 GA，不用裝、每次啟動不用 UAC，VS Code 用的就是它）與**專用本機帳號＋WFP 防火牆過濾**（Anthropic sandbox-runtime、OpenAI Codex 的做法，要一次 UAC）。**已查證** [MX1][MX2][MX3][AN2][VS1]；Windows 行為全部**待實測**。
7. **沒有任何一條路同時滿足「不裝東西、不要管理員、Windows 10 也行、有網域白名單」。** AppContainer 自製做不到網域白名單（只有全開／全關）；MXC 沒有 Windows 10。**已查證** [MS1][MS2][MX2]
8. **npm：`--ignore-scripts` 壞掉的是少數、集中、而且無聲。** 實測 7 個熱門套件：esbuild、sharp 沒事；better-sqlite3、sqlite3、bcrypt、node-pty 沒有 `.node` 檔、puppeteer 沒下載瀏覽器，但 `npm ci` 都回 0。**已實測**。生態系自己也轉向預設不跑安裝腳本（npm 12、pnpm、Bun）。**已查證** [NP5][PN1][BN1]
9. **從套件名產生鎖檔可行**（0.5–3.5 秒、不下載套件本體、每一項都有官方 `resolved` 與 sha512 `integrity`）。**已實測**。但現在的程式有洞：沒寫 `resolved` 的項目放行、`integrity` 完全沒檢查（`npm ci` 接受沒有 `integrity` 的鎖檔）。**已實測＋規劃階段複查** `src/synox/packs/envs.py:449-469`
10. **提示注入沒有萬全解，各家共識是把重心放在結構。** 最小權限＋執行前驗參數＋高風險動作人按確認＋釘住工具定義；分隔符與樣式掃描都被明講「不是邊界」。**已查證** [PI6][PI7][PI8][PI9]。SYNOX 現在的缺口：`pack.json` 的 `title`／`summary` 與 SKILL frontmatter 直接進系統提示、沒有長度限制也沒包分隔符；MCP 的工具說明每次連線都可以無聲換掉；`WRITE` 與連網的 `READ` 不出確認卡。**規劃階段複查** `src/synox/agent/loop.py:96-98`、`265-270`、`src/synox/agent/skills.py:76-82`、`src/synox/packs/mcp.py:978-988`
11. **「純文字技能風險低」不成立。** Anthropic 把「Instruction manipulation」列為 High；ClawHavoc 的主力手法就是 SKILL.md 裡的文字。**已查證** [PI12]、待查 [X2]。它不必走 T2 那套，但要另一種審查：把 AI 會讀到的全文給人看、仍要按確認。
12. **套件預覽做得到，但第一版不該跑 JS。** 規格上 `<iframe sandbox="">`＋那條路由自己的 CSP 標頭（含 `sandbox`）擋得住腳本、cookie、表單、對外請求；業界在**安裝前**展示的都是靜態圖＋markdown。**已查證** [WB1][WB3][WB5][WB9][WB10]。瀏覽器擋不了的是「在預覽裡畫假的 SYNOX 畫面騙人」。

---

## 二、結論表：做得到／做不到／要擁有者決定

### 做得到

| # | 事情 | 依據 | 標籤 |
|---|---|---|---|
| Y1 | 接上游在用的 MCP 伺服器：用現有的 `kind=mcp`（stdio／http），不用新的轉接程式 | `docs/pack-format.md`「mcp」兩節 [SX2] | 已查證；常見伺服器實際能用到什麼程度待實測 |
| Y2 | 一個匯入器同時吃 OpenClaw、Hermes、Claude 的技能：三家都照同一份 Agent Skills 規格（`SKILL.md`） | [O3][H2][M1] | 已查證（格式）；語意只做得到一部分（見 N3） |
| Y3 | 從一個 npm 套件名產生釘死版本、帶 sha512 的鎖檔，不下載套件本體 | 主題 7 §7.2 | 已實測（Linux） |
| Y4 | 離線就能列出「哪些套件有安裝腳本、不會跑」：鎖檔的 `hasInstallScript` 是正式欄位 | [NP2] | 已查證（欄位）；讀取邏輯要新寫 |
| Y5 | SYNOX 自己管一份可攜版 Node（官方 `node-v24.22.3-win-x64.zip` 37.8 MB，有 `SHASUMS256.txt` 可驗；Node 核心是 MIT） | [ND1][ND2]；授權見第九節 | 已查證 |
| Y6 | Linux 上的網域白名單：拿掉 network namespace＋unix socket 接到沙盒外的白名單 proxy | 主題 4 §4.6 | 已實測（root；一般使用者的 user namespace 限制待實測） |
| Y7 | Windows 11 24H2 以上（更新到 2026-08／09 之後）：檔案＋網路隔離、不用裝東西、每次啟動不用 UAC（MXC） | [MX2][MX3][MX4] | 已查證（文件）；**全部待實測**，Home 版查不到 |
| Y8 | Windows 10／沒更新的 Windows 11：檔案隔離＋「全斷網或全開網」（AppContainer 自製） | [MS1][MS2][MS3] | 推測；待實測（腳本已備） |
| Y9 | 套件預覽：沙盒 iframe＋CSP 標頭，不碰 SYNOX 的登入狀態與 API | 主題 8 | 已查證（規格）；各瀏覽器實際行為待實測 |
| Y10 | 策展式市集：目錄＋sha256（已有）＋簽章與撤銷清單（要做） | `docs/ecosystem.md:94-104`、[M4][M9] | 已查證（現況與先例） |
| Y11 | 釘住 MCP 工具定義：第一次連線記下雜湊，變了就停用並請擁有者重新核准 | [PI7]；`src/synox/packs/mcp.py:744-768` 已有快取檔 | 已查證（建議與現況）；要新寫比對 |
| Y12 | SDK 補齊：獨立套件帶指令、`run` 支援 mcp／python、`preview`、一頁入門、範本 | 第六節 | 已查證（缺口） |

### 做不到（或不該做）

| # | 事情 | 為什麼 | 標籤 |
|---|---|---|---|
| N1 | 讓上游的**原生 plugin**原封不動在 SYNOX 裡跑 | OpenClaw 的是綁 `openclaw/plugin-sdk/*`（352 個子路徑、官方說會變）的程序內 TypeScript；Hermes 的是綁 `register(ctx)` 的程序內 Python。不重做一個上游主程式就沒有路 | 已查證 [O4][O11][N3][H6]；「做不到」是推測 |
| N2 | 沿用「上游的沙盒」擋惡意技能 | 上游的沙盒包的是 AI 下的指令，不包技能與 plugin；兩邊預設都關 | 已查證 [O2][O5][H3] |
| N3 | 把上游技能「自動轉好就能用」 | 技能是寫給「有 shell 的 AI」看的操作說明；SYNOX 的 AI 只有 pack 宣告過的指令，沒有通用 shell。指令是 READ／WRITE／DANGER，機器猜不出來 | 已查證 `src/synox/agent/loop.py:101-106`；其餘推測 |
| N4 | 用掃描當「放行」的門 | 掃描器被繞過（待查 [X3][Y6]）、自己出 CVE（已查證 [H13]）；OWASP 明講樣式比對不能證明剩下的字安全（已查證 [PI6][PI7]） | 已查證＋待查 |
| N5 | Windows 上同時要「不裝東西、不要管理員、Windows 10、網域白名單」 | 主題 4 §4.4 | 已查證（各條文件）；組合結論是推測 |
| N6 | 用 Windows Sandbox 當工具的執行環境 | Home 版不支援；接不了長駐的 stdio | 已查證（搜尋摘要）[MS4]；stdio 是推測 |
| N7 | 根治提示注入 | OWASP：「it is unclear if there are fool-proof methods」；Anthropic：「far from a solved problem」 | 已查證 [PI8][PI14] |
| N8 | 讓瀏覽器擋住「預覽頁裡畫假的 SYNOX 已驗證畫面」 | 這是版面與文案的事；MCP Apps 的威脅模型也列了 phishing | 已查證 [WB12] |
| N9 | 在 127.0.0.1 上給預覽一個真正獨立的來源 | 另一個 port 是不同 origin，但 cookie 不照 port 隔離 | 已查證 [WB7] |
| N10 | 在 `--ignore-scripts` 下使用要編譯的原生模組（better-sqlite3、sqlite3、bcrypt、node-pty）或要下載瀏覽器的套件（puppeteer） | 主題 7 §7.1 | 已實測 |
| N11 | 用 `openclaw-core`、`hermes-core` 當套件名 | 兩個名字在 npm 都被佔了；MIT／MIT-0 不授予商標權 | 已查證 [N1][N2][O1][L1] |
| N12 | 這一輪就做到「技能看不到自己的 token」 | 現在 secret 經環境變數進子程序（`src/synox/packs/loader.py:585-607`）；要看不到得由 proxy 代填，是另一級的工程 | 已查證（現況）；推測（工程量） |

### 要擁有者決定

完整清單（35 題，每題有建議與各選項的後果）在第七節。最要緊的六題：預覽能不能跑 JS（決定 29）、Node 由誰提供（決定 8）、Windows 沙盒走哪條路與 Windows 10／一次 UAC（決定 11–14）、做 core 還是只做匯入器＋MCP（決定 2）、確認 Hermes 是哪一個（決定 1）、要不要允許 SYNOX 連網抓工具目錄（決定 25）。

---

## 三、假設評定（A–J、2.3）

| 假設 | 評定 | 理由 | 主要來源 |
|---|---|---|---|
| **A**　缺口不是「能不能裝 npm」，而是四件事：(1) 要安裝腳本的套件會壞 (2) 沒有「套件名→釘版本→鎖檔」流程 (3) Node 要系統有 (4) 沒有遠端目錄 | **部分確認** | (1) 確認，補兩點：是**無聲**地壞（結束碼 0）；佔全體約 2%、集中在原生模組與瀏覽器下載。(2) 確認；技術上可行（已實測）。(3) 確認；傾向 SYNOX 自己管一份。(4) 部分：有本機目錄（`index.json`＋sha256），只是網址不下載。**少列 4 個缺口**：裝出來的 `node_modules` 不在雜湊鎖裡；鎖檔的 `integrity` 不強制；MCP stdio 只能用沒鎖的 `npx`；Windows 個人版沒有執行期沙盒 | 已實測（主題 7）；`src/synox/packs/envs.py:23`、`449`；`src/synox/packs/manifest.py:1145-1146`；`src/synox/wizard/tools.py:7`；待查 [R1] |
| **B**　用 MCP 當共同語言＋安裝前轉成標準 pack 的匯入器，不做依賴上游內部的 core | **確認（補三個修正）** | 兩個上游互接時自己就是這樣做的。修正：① 有程式的技能，匯入器是**作者端的離線工具**，不是安裝時自動轉；② SYNOX 現在沒有地方放「只有說明文字」的技能（`KINDS` 只有四種）；③ npm 上的 MCP 伺服器現在只能用沒鎖的 `npx` 接 | [O10][H10][H4][O11][N3]；`src/synox/packs/manifest.py:85` |
| **C**　惡意技能分程式型（沙盒擋）與文字型（沙盒擋不住）→ 兩層：沙盒管程式、能力控制管 AI 行為 | **部分確認** | 兩層的分法跟 OWASP AST01（code layer＋natural language instruction layer）一致。要修正：① 對 SYNOX 現況，「沙盒擋得住程式型」不成立（個人版／Windows 沒有沙盒）；② 少了第三類：**騙人不騙 AI**（Prerequisites 叫人貼指令、預覽頁假畫面），兩層都擋不到；③ 少了時間軸：更新夾帶與 rug pull，SYNOX 對 pack 檔有鎖，但 MCP 工具說明沒釘。「文字型是更大的洞」：就「更難根治」成立，就「更常見」不成立（arXiv 2601.10338 說附腳本的技能風險較高，待查） | [PI3][PI12]；`docs/security.md:16`、`384`；`src/synox/packs/mcp.py:978-988`；待查 [Y5] |
| **D**　能力控制＝工具宣告能碰什麼；高風險動作要確認或拒絕；技能文字當不可信輸入（標來源、掃樣式） | **部分確認** | 宣告＋執行前驗證＋人按確認：確認（MCP 規格、OWASP、OpenAI 都這樣講）。標來源：確認，但 OWASP 明講不要把文字標籤當成強制邊界。**掃樣式當成門：推翻**；當成「提醒人來看」的信號可以。SYNOX 還缺：`WRITE`／外傳不確認；`summary` 與 frontmatter 進系統提示沒有限制；人看不到 SKILL.md；MCP 說明沒釘；`network` 是布林 | [PI6][PI7][PI8][PI9][PI15]；`src/synox/agent/loop.py:96-98` |
| **E**　Windows 是最弱的一環；候選是 Docker Desktop／WSL2、AppContainer、Windows Sandbox；沒結論 | **前半確認，候選名單要改** | 現況最弱：確認（預設 `none`）。名單：**加上 MXC 與「專用帳號＋WFP」**（這兩條才是 VS Code、sandbox-runtime、Codex 實際在走的）；**劃掉 Windows Sandbox**；Docker Desktop 留給願意裝的人。仍沒有單一結論：取決於 Windows 10 與一次 UAC | `src/synox/sandbox.py:465-467`；[MX1][AN2][VS1][OA4] |
| **F**　技能的環境：(1) 不繼承使用者的環境變數 (2) 讀不到別的 pack (3) 預設斷網＋網域白名單 (4) 帳號走「連接」表單、密碼不進技能 | **(1)(3) 就現況而言推翻；(2) 部分；(4) 確認** | (1) 現在**會**繼承整份環境，只拿掉名字像密鑰的。(2) 只有 bwrap／container 成立；Windows 預設 `none` 什麼都讀得到。(3) 現在只有「有／沒有 network」，沒有網域欄位；斷網只在真沙盒後端生效。(4) 現有機制成立，但技能程序本身拿得到 token 的值。當成**目標**四條都對 | `vendor/isdtelekit/jobs/runner.py:48-51`、`vendor/isdtelekit/jobs/cli.py:39-49`；`src/synox/sandbox.py:756`；`src/synox/packs/manifest.py:88`；`docs/security.md:46` |
| **G**　市集：來源要簽章或審查分級；新發行者預設低信任；一鍵停用／隔離；稽核紀錄 | **確認** | 只靠掃描的市集被證明擋不住；有效的都是結構性的機制。SYNOX 現況：有 sha256、沒有簽章；`publisher` 是任意字串；有移除與停用、沒有遠端撤銷；`packs.lock` 記了誰、何時，沒有完整的生命週期紀錄 | [O14][C5][H3][H8][M4][M9]；`src/synox/packs/lock.py:165-185`；`docs/ecosystem.md:101` |
| **H**　純文字技能（沒有程式）風險低 → 最簡單的一鍵安裝；有腳本的進 T2 | **「風險低」推翻；「不必走 T2」確認** | Anthropic 把 Instruction manipulation 列 High、Tool calls 列 Medium；總則是「只用可信來源的 skill」，沒有為純文字開例外。在 SYNOX 的精確說法（推測）：純文字技能的破壞上限＝AI 當下已有的工具全部加起來，每多裝一個工具上限就變大。另外：SYNOX 現在**沒有**「純文字技能」這個種類 | [PI11][PI12]；`src/synox/packs/manifest.py:85`；`src/synox/agent/skills.py:64-73` |
| **I**　SDK 的缺口是「5 分鐘做出第一個工具」：`synox new`、`synox pack test／build／preview`、一頁入門、範本 repo | **部分確認** | 四個指令裡三個已經有等價的（`synox-sdk init`／`run`＋`check`／`zip`）。真正缺的：不裝整個 SYNOX 就沒有指令；`run` 只支援 cli；沒有 preview；沒有獨立的一頁入門；沒有範本 repo；名字對新手不直覺。「5 分鐘」沒有量過（待實測） | `pyproject.toml:21-23`；`sdk/pyproject.toml`；`src/synox/sdk/__init__.py:672-715`；`docs/tools.md:324` |
| **J**　上游越多，攻擊面與維護面越大；要在「容易安裝」與「簡單乾淨」之間取捨 | **確認；建議選「簡單乾淨」** | 相依一個上游的執行環境就繼承它的安全更新節奏（OpenClaw 的 advisory 列表分到第 73 頁）；每多一個解析器或掃描器就多一個被打的地方（Hermes 掃描器的 CVE）；「兩個公開標準」的維護量不隨上游數量增加，「N 個 core」會 | [O16][H13][O11] |
| **2.3**　套件預覽的設計 | **方向確認，五處要改** | 確認：沙盒 iframe 不給 `allow-same-origin`、預設不跑 JS、嚴格 CSP、唯讀路由、大小與型別白名單、作者端指令。要改：① 預覽要**單檔自足**（子資源帶不到 cookie）；② 「靜態掃描涵蓋預覽」現在沒有這個能力（第 2 關只讀 `.py`），要新寫白名單式的 HTML 檢查，而且它只是提醒；③ 回應標頭要帶 CSP `sandbox`，不要用 `srcdoc`／`blob:`；④ 要處理「預覽裡假裝成 SYNOX 的畫面」；⑤ 封面不收 SVG | 主題 8；`src/synox/packs/scan.py:174-192`；`src/synox/web/server.py:395-402` |
| 擁有者的猜測：兩邊沙盒做法差不多 | **部分** | 像：都是選配、預設關、用容器、官方自己說不是完整邊界。不像：Hermes 預設有「小模型判斷危險指令」，OpenClaw 預設不問。最重要：兩邊都不包技能與 plugin | [O2][O5][O8][H3][H5] |

---

## 四、現況核對：主 session 對程式的認知

「規劃階段複查」＝寫這份合併稿時自己再開檔對過一次（分支 `dev`，commit `30f32a4`）。定稿時 `dev` 已經到 `a22382c`；兩個 commit 之間只改了 `docs/landing/` 的兩個檔（`git diff --stat 30f32a4 a22382c`），所以文中的行號在 `a22382c` 上相同（ADR 0022 引用的行號在 `a22382c` 上逐一對過）。

### 4.1 安裝與執行環境

| # | 主 session 的認知 | 判定 | 依據 |
|---|---|---|---|
| 1 | `runtime.node: "auto"` 在 `data/envs/<pack>/` 跑 `npm ci --ignore-scripts --registry=https://registry.npmjs.org/` | **正確** | 實際 argv 是 `npm ci --ignore-scripts --no-audit --no-fund --registry=…`：`src/synox/packs/envs.py:601-603`；先複製兩個檔：`envs.py:595-598`；建置子程序用白名單環境變數：`envs.py:56-59`。規劃階段複查 |
| 2 | 要有 `package.json`＋`package-lock.json` | **正確** | `envs.py:44`、`590-592`；第 1 關也擋：`src/synox/packs/manifest.py:1153-1157`。規劃階段複查 |
| 3 | 鎖檔的每個 `resolved` 都要是官方 registry | **部分** | 有寫的必須是 `https://registry.npmjs.org/`：`envs.py:435-443`、`466-468`。**沒寫 `resolved` 的項目放行**（註解明寫「沒寫 resolved 的不算」）：`envs.py:449`。**`integrity` 沒有任何檢查**（`envs.py`、`scan.py`、`manifest.py` 裡 grep 不到 npm 的 `integrity`／`hasInstallScript`）。規劃階段複查 |
| 4 | 系統沒有 node＝doctor 說缺、pack 不載入 | **正確** | `envs.py:297-301`；loader 設成 `missing` 並跳過：`src/synox/packs/loader.py:900-903`。只用 `shutil.which("node")`，**不看版本**：`envs.py:236-237`。規劃階段複查 |
| 5 | Linux 有 SystemdSandbox | **部分** | Linux 有三個真隔離後端：`bwrap`（`auto` 的第一順位）、`systemd`、`container`。**`auto` 只在「伺服器版＋Linux」才挑後端，個人版一律 `none`**：`src/synox/sandbox.py:465-471`。全部只組 argv、沒在真機跑過：`docs/security.md:321-322`。規劃階段複查 |
| 6 | Windows 只有 JobObjectSandbox | **部分** | **Windows 預設是 `none`**：`sandbox.py:466-467`。jobobject 要在 config 明寫才用（`sandbox.py:474-476`），只設記憶體與程序數，自己標 `isolates = False`（`sandbox.py:124`）。另有 `container`（配使用者自己裝的 Docker Desktop）與只有介面的 `appcontainer`（`wrap` 丟 `NotImplementedError`：`sandbox.py:383-395`）。規劃階段複查 |
| 7 | 安裝五關＝宣告檢查、靜態掃描、報告給人看、人按確認、逐檔雜湊鎖 | **部分錯** | 文件與程式的「五關」是：①宣告 ②靜態掃描 ③完整性鎖定 ④**呼叫驗證**（AI 每次叫工具前驗參數）⑤**授權與核准**（核准卡＋分隔符）：`docs/security.md:177-183`。「報告給人看、按確認」發生在 ② 與 ③ 之間，不是編號的關（`docs/ecosystem.md:49`）。④⑤ 是執行期的。規劃階段複查 |
| 8 | 信任層級 T0／T1／T2 | **正確** | `src/synox/packs/tier.py:36-39`。層級只講「第 2 關掃得到多少」，不是沙盒（`tier.py:27-28`）。規劃階段複查 |

### 4.2 主 session 沒提到、但會影響決定的事

| # | 事實 | 依據 | 為什麼重要 |
|---|---|---|---|
| 9 | `runtime.node` **只給 kind=cli**；kind=mcp 寫了會被判不合 | `manifest.py:1145-1146`、`docs/pack-format.md:151`。規劃階段複查 | npm 最常見的用途是 MCP stdio 伺服器。它們現在只能寫 `npx …`，報告標「版本沒有鎖住」：`src/synox/packs/scan.py:1558`、`docs/security.md:241-243` |
| 10 | 裝出來的 `data/envs/<pack>/node_modules` **不在 packs.lock 的雜湊裡** | 「pack 資料夾本身一律不寫」：`envs.py:23`；雜湊只算 pack 資料夾：`src/synox/packs/lock.py:88-92`；環境指紋只含鎖檔內容：`envs.py:264-269`。規劃階段複查 | 安裝之後 `node_modules` 被改，SYNOX 不會發現 |
| 11 | 執行期子程序**繼承 SYNOX 的整份環境變數**，只拿掉名字符合 `(API_?KEY\|SECRET\|PASSWORD\|PASSWD\|_TOKEN)$` 的 | `vendor/isdtelekit/jobs/runner.py:48-51`、`vendor/isdtelekit/jobs/cli.py:39-49`；文件也明講：`docs/security.md:406`。規劃階段複查 | 假設 F(1) 不是現況。例外：systemd 與 container 後端只帶列名的變數（`sandbox.py:226-230`、`362-368`）；bwrap 沒有清環境（`sandbox.py:169-183`） |
| 12 | 網路是二元的：`capabilities` 有沒有 `network` | `sandbox.py:756`；能力只有五種：`manifest.py:88`。規劃階段複查 | pack.json 沒有網域欄位 |
| 13 | bwrap 後端：宣告了 `network` 就不加 `--unshare-net` | `sandbox.py:173-174`。規劃階段複查 | 技能直接在主機的網路裡，連得到 Ollama（11434）與 SYNOX 自己（8830） |
| 14 | 有本機工具庫目錄（`index.json`＋每個檔的 sha256），但**網址不會自動下載** | `src/synox/wizard/tools.py:7`、`99-101`；`src/synox/packs/library.py:7`。規劃階段複查 | 假設 A(4) 要寫成「沒有遠端目錄」，不是「沒有目錄」 |
| 15 | `index.json` 每一筆的欄位：name、title、summary、version、stage、kind、group、access、capabilities、requires、bundles、file、sha256、size。**沒有封面、沒有簽章、沒有發行者** | SYNOX_Libs `scripts/build.py:105-111`；SYNOX 讀的是 `wizard/tools.py:135-139`。規劃階段複查（報告 C 少列了 kind、group、access、capabilities、bundles） | 預覽與市集都要動這份目錄，兩個 repo 要一起改 |
| 16 | pack 的生命週期**沒有獨立的稽核紀錄**；`packs.lock` 每筆記了 `approved_by`、`via`、`approved_at` 與掃描摘要 | `src/synox/packs/lock.py:165-185`；`packs/admin.py`、`packs/lock.py` 裡 grep 不到 audit／稽核。規劃階段複查（報告 A 標待查） | 假設 G 的「稽核紀錄」要新做 |
| 17 | `docs/security.md:389-390` 寫「npm 照 `package-lock.json` 的 `integrity` 驗」 | 同左 | 只在鎖檔有寫 `integrity` 時成立（主題 7 §7.2 的實測） |

### 4.3 pack 的文字怎麼進 AI

| 文字來源 | 進到哪 | 有沒有包分隔符 | 安裝時檢查 |
|---|---|---|---|
| `pack.json` 的 `title`、`summary` | **系統提示**「## 已裝的功能」（`src/synox/agent/loop.py:265-267`） | **沒有** | 只查「是不空的字串」（`manifest.py:1057-1059`）；**沒有長度上限、沒擋換行、沒有樣式比對**。規劃階段複查 |
| SKILL.md frontmatter `description`、`when` | **系統提示**「## 技能」（`src/synox/agent/skills.py:76-82`） | **沒有** | 只查有沒有（`manifest.py:1193-1204`，提醒不擋）；解析器只認單行（`skills.py:39-51`），**沒有長度上限**。規劃階段複查 |
| 指令的 `summary`、`usage`、欄位的 `ask`、`choices` | 工具規格的說明（`src/synox/agent/tools.py:82-97`） | 沒有（工具規格本來就沒地方包） | 一行 200 字（`manifest.py:93`）；沒有樣式比對 |
| `commands[].ai.scenario` | 工具說明 | 沒有 | **有**：一行、120 字、不准網址／信箱／像對 AI 下指令／要跳過確認／分隔符（`manifest.py:467-482`）。規劃階段複查 |
| MCP 伺服器自述的工具說明 | 工具規格（`src/synox/packs/mcp.py:644`、`682`） | 沒有 | 拿掉控制字元、只留第一段、截 200 字（`mcp.py:599-603`）。**每次新連線讀到 `tools/list` 就直接換掉說明並存快取，沒有比對、沒有通知**（`mcp.py:978-988`；快取只認 pack 版本：`mcp.py:744-753`）。規劃階段複查 |
| SKILL.md 正文 | `skill_read` 的工具結果 | **有**（`loop.py:693`） | 沒有任何內容檢查 |
| 工具執行結果 | 工具結果 | **有**：每輪隨機的分隔符（`src/synox/agent/delimit.py:21-41`） | — |

執行期的結構性保護（已查證）：

- 第 4 關每次呼叫前驗參數：不認得的欄位、`-` 開頭、路徑逃逸、像密鑰的檔名、值等於或夾帶已存的 secret 都拒（`docs/security.md:182`）。
- 核准卡只在 `effect == DANGER`、要 /sudo、有驗證碼欄位（`loop.py:96-98`），或作者自己寫 `confirm: true`（`loop.py:803`）時出。**`WRITE` 與任何會連網的 `READ` 都直接執行**（`loop.py:808-816`）。規劃階段複查
- MCP 的 effect 只認 pack.json、不認伺服器的 annotations，沒寫＝DANGER（`mcp.py:769-772`）。符合 MCP 規格「annotations 不可信」[PI9]。規劃階段複查
- 文件自己承認：「真正擋住危險動作的是確認卡（結構），不是提示」（`docs/security.md:410`）。

由此看得到的缺口（**推測**：從上表推出；能不能真的騙到模型＝待實測）：

1. `pack.json` 的 `summary` 可以是多行、任意長、任意內容，原樣進系統提示、而且在分隔符**外面**。`scenario` 有管、`summary` 與 frontmatter 沒管，標準不一致。
2. 人在安裝報告上**看不到 SKILL.md 的內容**（報告只列 title、summary、種類、能力、掃描結果：`src/synox/web/static/app.html:1576-1612`）。AI 會讀的字，人沒有機會審。
3. 遠端 MCP（T0）的工具說明裝的時候不在包裡、第一次連線才拿到、之後可以無聲地換，人從頭到尾沒審過。
4. 沒有「這一輪已經讀過不可信內容 → 之後的寫入／外傳要多一道」的邏輯。私有資料＋不可信文字＋能往外送的工具三樣同時存在時，就是「致命三要素」（待查 [Y12]）。

### 4.4 安裝畫面與網頁

| # | 主 session 的認知 | 判定 | 依據 |
|---|---|---|---|
| 18 | 設定頁有分頁；專用安裝頁 `#packs` | **正確／部分** | 分頁是 ai／channels／packs／accounts／system（`app.html:1152`）；`#packs` 是 `#settings:packs` 的別名（`app.html:858-860`），不是獨立的 view。規劃階段複查 |
| 19 | `GET /api/packs/staged`、`POST /api/packs/discard` | **正確** | `src/synox/web/server.py:550-551`；只有擁有者；7 天過期（`src/synox/packs/admin.py:423`）。另有 `GET /api/pack-staged/<token>`（`server.py:547-549`）。規劃階段複查 |
| 20 | 步驟 check→report→confirm→install→done | **部分** | 步驟鍵是 `check`、`review`、`confirm`、`installing`、`done`（`app.html:1714`）；沒有叫 `report`、`install` 的步驟。規劃階段複查 |
| 21 | `synox:install-step` 事件、`#install-steps` 的 `data-step`／`data-status`、`window.SynoxInstall` | **正確** | `app.html:1734-1737`、`1724-1726`、`1978-1993`。規劃階段複查 |
| 22 | 拖放安裝（packdrop） | **有，但兩處跟想的不同** | `src/synox/web/static/packdrop.js:114-126`：(a) **不經 `SynoxInstall.reviewFile`**，是把檔塞進 `#pack-file` 再點 `#pack-upload`；(b) hash 不是 `#settings` 開頭時設成 **`#settings`**（`packdrop.js:119`），不是 `#packs`。`route()` 對沒有分頁名的 `#settings` 沿用上次的分頁、否則第一個（`app.html:859-862`、`1155-1160`）→ **從對話頁拖進來，可能停在「AI」分頁，報告在隱藏的分頁裡**。規劃階段複查（讀程式確認邏輯；畫面行為待實測） |
| 23 | `.synoxpack` 檔案關聯 | **正確** | `src/synox/__main__.py:825`；只有 Windows、HKCU；`docs/install-packs.md:20-26` |
| 24 | CSP／nonce | **正確** | 主頁每次回應一個 nonce：`server.py:395-402`（`default-src 'none'; script-src 'nonce-…'; style-src 'nonce-…'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`）。所有回應帶 `nosniff`、`no-referrer`、`no-store`（`server.py:88-89`）。規劃階段複查 |
| 25 | 靜態檔怎麼給 | **沒有靜態檔路由** | js／css 在送出前原地塞進 `app.html`、共用同一個 nonce（`server.py:102-104`、`143-166`）。全部路由只有 `/`、`/login`、`/packs/<name>/panel`、`/tutorials/<name>/`、`/api/…`（`server.py:311-337`）。**預覽要一條新的路由**。規劃階段複查 |

做預覽一定要知道的三件事（規劃階段複查）：

- **現有的 `web.panel` 是「完全信任」的反例**：iframe 是 `sandbox="allow-scripts allow-same-origin"`（`src/synox/web/static/tools.js:375`），路由的 CSP 放行 `script-src 'unsafe-inline'; connect-src 'self'`（`server.py:506-507`），而 `/api/me` 會回 session 的 CSRF token（`server.py:642`）。所以面板的 JS 能做擁有者在網頁上能做的任何事（含裝 pack）。文件有明講（`docs/security.md:74-75`、`373`）。**預覽絕對不能沿用這條路或這組 sandbox 值。**
- **第 2 關只讀得懂 `.py`**：`.html`／`.css`／`.svg` 不在任何清單裡（`src/synox/packs/scan.py:174-192`），當資料、不掃、不影響層級。「靜態掃描涵蓋預覽資料夾」**現在沒有對應的能力**。
- **已經有一條「只有 CSS 的不可信 HTML」先例**：教學頁 `/tutorials/<name>/` 用 `default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'; base-uri 'none'`（`server.py:518`）。預覽的 CSP 可以從這條長出來。

---

## 五、八個研究主題

## 主題 1：OpenClaw

### 1.1 它是什麼

| 項目 | 內容 | 標籤 |
|---|---|---|
| 一句話 | 自己架的個人 AI 助理閘道：一個常駐程式接多個聊天通道，AI 可以在你的電腦上跑指令、開瀏覽器 | 已查證 [O15] |
| repo 與規模 | `openclaw/openclaw`，394k 星、82.9k fork（2026-11-13） | 已查證 [O15] |
| 發行 | npm 套件 `openclaw`，最新 `2026.11.3`；要 Node `>=24.16.0 <25 \|\| >=26.1.0`；解開 275 MB、15,207 個檔 | 已查證 [N3] |
| 誰在管 | OpenClaw Foundation（README 寫是獨立的 501(c)(3)） | 已查證 [O15] |
| 歷史 | 2025-11 以 Clawdbot 之名推出 → 2026-01-27 因商標意見改名 Moltbot → 2026-01-30 再改名 OpenClaw | 待查 [X10] |

### 1.2 架構與格式

- **中心是一個 Gateway 程序**，通道、plugin、工具政策、session 都在它裡面；預設只聽本機。**已查證** [O2][O5][O6]
- 信任模型是「一個 gateway 一個受信任的操作者」，官方明寫不是多租戶邊界。**已查證** [O2]
- **技能**：一個資料夾＋一個 `SKILL.md`（YAML frontmatter＋Markdown 正文），必填 `name`、`description`；官方寫「OpenClaw follows the AgentSkills spec」。自己加的欄位放在 `metadata.openclaw`（`requires.bins`、`requires.env`、`os`、`install`…）。**已查證** [O3][C2]
- **技能本質上是「寫給 AI 看的操作說明」**：正文教 AI 用它手上的工具（跑指令、讀寫檔案、開瀏覽器）去做事；可以附 `scripts/`。官方提醒：「Treat third-party skills as untrusted code.」**已查證** [O3]
- **原生 plugin**＝`openclaw.plugin.json`＋一個在 Gateway 程序裡載入的執行模組；能註冊通道、模型供應商、工具、技能、hook、HTTP route、CLI 指令。SDK 是 `openclaw/plugin-sdk/*`，npm 套件的 `exports` 一共 352 個子路徑；官方說「All OpenClaw plugin APIs are experimental.」「These contracts can change between OpenClaw releases.」**已查證** [O4][O9][O11][N3]
- **相容包（bundle）**：別家格式（Claude、Codex、Cursor 的 plugin 目錄）可以直接裝，但 OpenClaw 只「挑內容對應進來」（技能、指令、MCP 設定），**不在程序裡跑它們的執行模組**；Claude 的 `hooks/hooks.json` 只偵測、不執行。**已查證** [O10]

### 1.3 MCP 支援

| 方向 | 內容 | 標籤 |
|---|---|---|
| 當 MCP 用戶端 | 設定在 `mcp.servers`；支援 stdio、SSE／HTTP、streamable HTTP | 已查證 [O7] |
| 當 MCP 伺服器 | `openclaw mcp serve`：把**聊天對話**開給外面的 MCP 用戶端。**不是**把 plugin 的工具開出去 | 已查證 [O7] |
| 把 plugin 工具用 MCP 開出去 | 有一個 `openclaw-plugin-tools` 橋，但只在 ACPX session 注入、預設關；官方寫「Treat this as the same trust boundary as letting those plugins execute in OpenClaw itself」 | 已查證 [O13] |
| 這個橋能不能單獨拿來給 SYNOX 連 | — | 待實測 |

### 1.4 安全機制與預設值

**結論：預設是寬鬆的。** 官方的立場是「你裝了、開了，就是你信任它」。

| 機制 | 預設 | 官方原話或說明 | 標籤 |
|---|---|---|---|
| 沙盒（把工具執行丟進容器） | **關** | 「Sandboxing is off by default.」後端有 Docker（預設）、Podman、SSH、OpenShell、Crabbox；官方自己說「This is not a perfect security boundary」 | 已查證 [O2][O5] |
| Gateway 本身 | 不在沙盒裡 | 「The Gateway process always stays on the host」 | 已查證 [O5] |
| 跑指令前要不要問人 | **不問** | gateway 與 node 主機的 exec 預設 `security: full`、`ask: off` | 已查證 [O8] |
| Plugin | 程序內、完全信任 | 「Installing or enabling a plugin grants it the same trust level as local code」 | 已查證 [O2] |
| 模型 | 不被信任 | 「The model/agent is **not** a trusted principal.」但「只有 prompt injection、沒有繞過邊界」不算漏洞 | 已查證 [O2] |
| 惡意 plugin | 不算漏洞 | 操作者裝了之後 plugin 做壞事，不在回報範圍 | 已查證 [O2] |

**ClawHub（技能市集）現在的機制：**

| 機制 | 內容 | 標籤 |
|---|---|---|
| 誰能發佈 | 任何人；GitHub 帳號要滿 14 天（威脅模型文件寫的） | 已查證 [O14][C6]；1 週的說法待查 [X19] |
| 自動掃描 | 三個元件：SkillSpector、A.I.G、ClawScan；含 `.pyc`／`.pyo`／`.pyd` 的直接拒收 | 已查證 [C5] |
| 安裝時 | 判定為惡意的社群版本**拒裝**；`Review` 印出稽核連結後繼續裝。**官方發行者與內建來源跳過這項檢查** | 已查證 [O12] |
| 官方對掃描的定位 | 「Audits are strong safety signals, but they are not a guarantee that a release is risk-free.」 | 已查證 [C5] |
| 檢舉與處置 | 可暫扣、隱藏、隔離、撤銷；帳號可封鎖；有申訴 | 已查證 [C4] |
| 來源釘選 | 經 skills.sh 來的 GitHub 技能會釘到確切的 commit | 已查證 [O12] |
| 簽章 | 文件裡沒有提到對技能或 plugin 做簽章 | 查不到 [C1][C3][C5] |
| 官方自己認的缺口 | 「No runtime execution sandbox isolates a skill from the agent's own privileges once installed.」；把「裝到惡意技能」評為 Critical／P0 | 已查證 [O14] |

### 1.5 資安事件

| 時間 | 事件 | 手法與影響 | 標籤 |
|---|---|---|---|
| 2026-01-31 公開 | **CVE-2026-25253**（GHSA-g8p2-7wf7-98mq），CVSS 8.8 | Control UI 不驗證網址列的 `gatewayUrl` 就自動連線，把存著的 gateway token 送給攻擊者；點一個連結就中，gateway 只聽本機也沒用。`2026.1.29` 修掉 | 已查證 [O17] |
| 2026-01 底～03 | 大量 gateway 直接暴露在網際網路 | 使用者自己把埠開出去；Censys 01-31 算到 21,639 台 | 待查 [X9] |
| 2026-02 初 | **ClawHavoc**（Koi Security） | 技能的「Prerequisites」段叫使用者或 AI 下載加密壓縮檔、或貼一段指令，實際上裝 macOS 竊資軟體。抽查 2,857 個技能，341 個惡意（335 個同一波）；後來更新為 1 萬多個技能中 824 個 | 待查 [X1][X2][X5]；手法已查證於 OWASP 的轉述 [PI3] |
| 2026-02 | 排行第一的技能是惡意的（Cisco） | 排名被灌水；內含指令注入與外洩資料 | 待查 [X8] |
| 2026-02-05 | **ToxicSkills**（Snyk） | 掃 3,984 個技能：36.82% 有安全問題、13.4% 有嚴重問題、人工確認 76 個惡意 | 數字已查證於 OWASP 的轉引 [PI4]；Snyk 原文待查 [X7] |
| 2026-02～05 | **掃描被繞過**（Unit 42） | 5 個惡意技能通過 VirusTotal 與 ClawScan：把 README 灌到約 22 MB 超過掃描上限；把 AI 引到貼文網站拿 Base64 指令；不帶惡意程式、純粹濫用 AI 權限 | 待查 [X3][X4] |
| 持續中 | 官方 advisory 數量很大 | advisory 列表頁分到第 73 頁（每頁 10 筆） | 已查證 [O16]（確切總數查不到） |

這個 CVE 對 SYNOX 的提醒：SYNOX 的網頁也是只聽本機＋擁有者點連結登入。任何「從網址列參數決定連去哪裡」「從外面的頁面帶 token 進來」的新功能（市集一鍵安裝、`?pack=` 參數）都要比照這個案例審。**推測**

### 1.6 對 SYNOX 的意義

- OpenClaw 的技能假設 AI 手上有「跑任意指令」的工具。SYNOX 的 AI 只有「pack 宣告過的指令」加 `skill_read` 和 `cannot_do`（`src/synox/agent/loop.py:101-106`）。所以大部分 ClawHub 技能搬過來，文字讀得懂、但做不了事。**推測**
- OpenClaw 的 plugin 是綁主程式內部介面的 TypeScript 模組，沒有不重做主程式就能跑的方法。**推測**（依據 [O4][O11][N3]）

---

## 主題 2：Hermes

### 2.1 擁有者說的是哪一個 Hermes

| 候選 | 是什麼 | 判定 |
|---|---|---|
| **Nous Research 的 Hermes Agent**（`NousResearch/hermes-agent`） | 開源個人 AI 助理，有終端機介面、聊天通道、桌面版、本機網頁 dashboard。SYNOX `docs/ui/redesign-notes.md` 寫「Hermes Agent（web dashboard）」、取了「側欄分頁、設定拆成卡、金鑰只顯示有填」、沒取「8 套主題和字型選擇器、網頁終端機」；Hermes 的 dashboard 文件：八個內建主題、獨立的 Font 區、Chat 分頁用 xterm.js 把終端機嵌進瀏覽器、API Keys 頁只顯示遮過的預覽。四項全對上 | **就是這個**。已查證 [SX1][H9] |
| Nous Research 的 Hermes 模型系列 | 語言模型，不是代理人框架，沒有 dashboard | 排除。待查 [X16] |
| Cossack Labs 的 Hermes | 密碼學存取控制函式庫（PyPI `hermes-core`） | 排除。已查證 [N5] |

### 2.2 它是什麼

| 項目 | 內容 | 標籤 |
|---|---|---|
| 一句話 | 「The self-improving AI agent built by Nous Research」：會把做過的事自己寫成技能、之後自己改進 | 已查證 [H2] |
| 規模 | 263k 星、59.2k fork（2026-11-13） | 已查證 [H11] |
| 語言與發行 | Python；PyPI `hermes-agent` 最新 0.19.0 | 已查證 [N6] |
| 平台 | Linux、macOS、WSL2、原生 Windows；但 dashboard 的 Chat 分頁要 POSIX，原生 Windows 被導去 WSL2 | 已查證 [H2][H9] |
| 從 OpenClaw 搬家 | 有現成指令 `hermes import-agent openclaw` | 已查證 [H10] |

### 2.3 技能與 Skills Hub

- 格式同樣是 `SKILL.md`，README 寫「Compatible with the agentskills.io open standard」；自己的欄位放在 `metadata.hermes`。**已查證** [H2][H4]
- AI 可以用 `skill_manage` 工具**自己建立、修改技能**；`skills.write_approval` 開了才會先暫存等人核准。**已查證** [H4]
- **Skills Hub 不是一個自己的市集，是一個「多來源安裝器」**：官方、skills.sh、發佈 `/.well-known/skills/index.json` 的網站、GitHub repo、ClawHub、LobeHub、直接給網址。**已查證** [H4]
- **裝之前一定過內建掃描器 Skills Guard**，而且有一張「信任等級 × 判定」的表決定裝不裝。**已查證** [H8]

  | 信任等級 | safe | caution | dangerous |
  |---|---|---|---|
  | builtin（內建） | 放行 | 放行 | 放行 |
  | trusted（白名單 repo，只有 10 個） | 放行 | 放行 | **擋** |
  | community（其他全部） | 放行 | **擋** | **擋** |
  | agent-created（AI 自己寫的） | 放行 | 放行 | 問 |

- `--force` 壓不過 `dangerous`；新加的來源預設是 community。下載的內容先放 `.hub/quarantine/`；有 `.hub/audit.log`；`lock.json` 記每次安裝的來源網址、內容雜湊、掃描器版本、發現、時間。**已查證** [H4]
- 官方對掃描器的定位：Skills Guard 是「review aid」，繞過它不算漏洞；「Reviewing a skill means reading its Python code and scripts, not just its SKILL.md description」。**已查證** [H3]

### 2.4 Plugin 與 MCP

- Plugin＝`plugin.yaml`＋`__init__.py` 裡的 `register(ctx)`；能註冊工具、27 種 hook、指令、技能、通道、供應商、記憶體後端。**第三方 plugin 預設停用**；安裝時問要不要啟用，預設「否」。有能力宣告，但官方明寫：「Capabilities are a **consent and audit layer**, not isolation.」「a malicious plugin can ignore every gate here」。目錄的定位：「Cataloged ≠ audited.」**已查證** [H6]
- MCP 用戶端：stdio 與 HTTP（含 OAuth 2.1、mTLS）；sampling（伺服器反過來要 Hermes 幫它叫模型）**預設開**；給 stdio 伺服器的環境變數只給安全的基本幾個＋設定檔明寫的。**已查證** [H5][H7]
- MCP 伺服器：以官方 plugin `mcp-serve` 提供。它開出去的「工具」包不包含第三方 plugin 註冊的工具：**待實測**。[H7]

### 2.5 它怎麼接 OpenClaw（假設 B 最直接的旁證）

- `hermes import-agent openclaw`：**一次性匯入**人格與記憶檔、技能（放到 `openclaw-imports/`）、模型設定、MCP 伺服器設定、通道設定；金鑰要加 `--migrate-secrets` 才搬，而且只搬白名單上的。永遠先顯示完整預覽。**已查證** [H10]
- **不搬的**：plugin、hook、cron、heartbeat——存到一個 `archive/` 資料夾「給人自己看」。**已查證** [H10]
- 匯入的技能會不會過 Skills Guard：文件沒寫，**查不到**。[H10]

### 2.6 安全機制與資安事件

官方的總綱：「The only security boundary against an adversarial LLM is the operating system.」**已查證** [H3]

| 機制 | 預設 | 說明 | 標籤 |
|---|---|---|---|
| 指令在哪裡跑 | **直接在主機上** | 可換成 docker、singularity、modal、daytona、vercel sandbox、ssh | 已查證 [H2][H3] |
| 危險指令核准 | `smart` | 另一個小模型判斷風險：低的自動過、明顯危險的自動擋、不確定的問人；`--yolo` 可以整個關掉 | 已查證 [H5] |
| 容器包得到什麼 | 只有 shell 指令與檔案工具 | **包不到**：程式執行子程序、MCP 子程序、plugin 載入、hook、技能載入 | 已查證 [H3] |
| 惡意技能／plugin | 不算漏洞 | 「A skill or plugin doing something malicious is the expected failure mode of one that wasn't reviewed」 | 已查證 [H3] |

| 資安項目 | 內容 | 標籤 |
|---|---|---|
| repo 自己的 advisory 頁 | 「There aren't any published security advisories.」 | 已查證 [H12] |
| CVE-2026-9353 | **掃描器 Skills Guard 自己的注入漏洞**；影響 `< 0.15.0` | 已查證 [H13] |
| CVE-2026-9366、-14628、-14783、-71963 | prompt builder 的注入、兩個路徑穿越、惡意 repo 透過 `.git/config` 執行指令 | 待查 [X17] |
| 專門針對 Hermes 的惡意技能事件 | 查不到。但它的 Skills Hub 會從 ClawHub、skills.sh 拉技能，等於吃同一個供應鏈（推測） | 查不到 |

值得記住的一點：**掃描器本身變成了被打的地方**。多加一個解析器或掃描器，就多一個攻擊面。

### 2.7 兩邊的沙盒比較

| 比較 | OpenClaw | Hermes | SYNOX 現況 |
|---|---|---|---|
| 沙盒是什麼 | 把工具執行丟進 Docker 等後端 | 把 shell 與檔案工具丟進 docker 等後端 | 每個 pack 自己的子程序包一層（bwrap／systemd／容器） |
| 預設 | 關 [O5] | 關（主機上直接跑）[H3] | 個人版與 Windows：`none`（`src/synox/sandbox.py:465-467`） |
| 包得到 plugin／技能嗎 | 包不到 [O2][O5] | 包不到，官方明寫 [H3] | python pack 包不到；cli 與 mcp stdio 包得到（有真後端時） |
| 跑指令前問人 | 預設不問 [O8] | 預設由小模型判斷 [H5] | DANGER 一定出確認卡（`src/synox/agent/loop.py:96-98`） |
| 更強的建議 | 後端選 OpenShell [O5] | 整個程序樹放進 Docker 或 OpenShell [H3] | — |

兩邊給的最終建議都是「把整個代理人關進容器」；NVIDIA OpenShell 在 Windows 上要 WSL 2 而且標「experimental」（已查證 [M11]），SYNOX 是 Windows 優先，直接沿用不合。SYNOX「每個 pack 一個牆」的設計在粒度上比兩個上游細，差在還沒真機驗證。**推測**

---

## 主題 3：其他值得學的技能市集

### 3.1 一覽

| 生態 | 是什麼 | 信任與審查 | 簽章與釘選 | 檢舉與下架 | 標籤 |
|---|---|---|---|---|---|
| **Agent Skills 規格** | `SKILL.md` 格式的公開標準。`name`（1–64 字、要跟資料夾同名）、`description`（1–1024 字）、選填 `license`、`compatibility`、`metadata`、實驗性的 `allowed-tools` | **規格本身沒有**簽章、信任等級、權限、沙盒 | 沒有 | 沒有（它只是格式） | 已查證 [M1][M2] |
| **ClawHub** | OpenClaw 的技能與 plugin 市集 | 開放上傳＋帳號年齡門檻＋自動掃描 | 沒有簽章；有 commit 釘選 | 檢舉、暫扣、隱藏、封鎖、申訴 | 已查證（主題 1） |
| **Hermes Skills Hub** | 多來源安裝器 | **來源白名單決定信任等級**，等級與掃描結果一起決定裝不裝 | 沒有簽章；鎖檔記內容雜湊 | 本機隔離區與稽核檔；沒有中央下架 | 已查證（主題 2） |
| **skills.sh**（Vercel） | 技能目錄，內容是 GitHub repo | 顯示三家第三方稽核結果，三家可能意見不同 | — | — | 待查 [X14] |
| **Claude Code plugin 市集** | 市集＝一份 Git 上的目錄 | 三層：官方（保留名稱）、社群、第三方。**每一層都顯示同一段警告** | 社群目錄幾乎每項都釘 commit SHA；`archive` 來源可釘 `sha256`，對不上拒裝 | 冒用官方名稱的市集整個拒載；企業可用受管設定做白名單 | 已查證 [M4] |
| **官方 MCP Registry** | MCP 伺服器的中繼資料目錄，仍在 preview | 驗「命名空間是你的」（GitHub OAuth、DNS、HTTP）。**不審內容**：使用者「should assume minimal-to-no moderation」 | 版本中繼資料發佈後不可改 | 只下架違法、惡意程式、垃圾、壞掉的 | 已查證 [M5][M6][M7] |
| **VS Code Marketplace** | 編輯器擴充功能 | 發佈時掃惡意程式、在沙盒裡跑一次看行為；「已驗證發行者」＝證明擁有網域；第一次裝某發行者的東西會問你信不信任 | **市集對所有擴充功能簽章，安裝時驗** | 惡意的下架並列入封鎖清單，**已經裝的會自動移除** | 已查證 [M9] |
| **npm provenance** | 套件來源證明 | 證明「這個套件是從哪個 repo、哪個建置流程出來的」。**不代表沒有惡意程式** | `npm audit signatures` 可驗 | — | 已查證 [M10] |
| **MCP Bundles（.mcpb）** | Claude Desktop 的擴充格式 | manifest 的展示內容只有圖示、截圖、markdown 長說明，**沒有作者自帶的 HTML／JS**；`node_modules` 打包在裡面、Node 隨宿主出貨 | 有 `sign`／`verify` 指令 | — | 已查證 [WB9][WB13][WB14] |

### 3.2 MCP 生態自己出過的事

| 事件 | 手法 | 教訓 | 標籤 |
|---|---|---|---|
| `postmark-mcp`（npm，2025-09） | 前 15 版正常，第 1.0.16 版加一行把每封信密件副本給攻擊者 | **更新就是重新信任一次**；釘版本、升級要人看差異 | 待查 [X11] |
| `mcp-remote` CVE-2025-6514 | 惡意的遠端 MCP 伺服器在 OAuth 回應裡塞指令 | 連遠端 MCP 的橋接程式本身是攻擊面 | 待查 [X12] |
| 工具說明下毒／事後換說明 | 伺服器在工具說明裡藏指令，或核准後偷換說明 | 用戶端要比對「當初核准的工具定義」 | PoC 已查證 [PI1][PI2]；部落格待查 [Y1] |
| MCP 規格自己的要求 | 「clients MUST consider tool annotations to be untrusted unless they come from trusted servers」；敏感操作要人確認 | SYNOX 現在的做法（effect 只看 pack.json）符合 | 已查證 [M8][PI9] |

### 3.3 掃描到底擋不擋得住

- ClawHub 加了 VirusTotal 與 ClawScan 之後，Unit 42 仍找到通過兩者的惡意技能。**待查** [X3]
- Trail of Bits（2026-06）：測過的技能掃描器**全部繞過**，各不到一小時；手法含「前面墊 10 萬個換行讓掃描器截斷」「藏在 `.pyc`」。OWASP 的轉述**已查證** [PI5]；原文**待查** [Y6]
- 馬里蘭大學的論文：只改 `SKILL.md` 的文字，就能讓惡意技能在 36.5%–100% 的情況下避開擋下的判定。**待查** [X13]
- 兩個上游的官方文件都說掃描只是輔助。**已查證** [C5][H3]　SYNOX 自己的文件也這樣寫（`docs/security.md:16`）。

**結論（推測）**：掃描只能當「多一個拒絕的理由」，不能當「放行的理由」。

### 3.4 可以直接學的做法

| 做法 | 學誰 | SYNOX 現在有沒有 |
|---|---|---|
| 信任等級 × 掃描結果的表，最低等級連「可疑」都擋 | Hermes [H8] | 有 T0／T1／T2 與 `trust`，但沒有「來源」這個維度 |
| 來源白名單寫死在程式裡，其他一律最低信任 | Hermes [H8]、Claude Code [M4] | 沒有（`publisher` 只是一個字串：`src/synox/packs/tier.py:27-28`） |
| 目錄釘 commit 或 sha256，對不上拒裝 | Claude Code [M4] | 有（`index.json` 的 sha256） |
| 市集簽章、安裝時驗 | VS Code [M9] | 沒有，列在「之後的路」（`docs/ecosystem.md:101`） |
| 發行者身分驗證（網域或 GitHub 帳號） | VS Code [M9]、MCP Registry [M5] | 沒有 |
| 遠端封鎖清單，已裝的自動停用 | VS Code [M9] | 沒有 |
| 下載先進隔離區、鎖檔記掃描器版本與發現 | Hermes [H4] | 部分有（暫存→報告→確認→鎖） |
| 升級時權限變大要重新同意 | Hermes plugin [H6] | 有（升級報告紅字） |
| 第三方預設停用，安裝時問、預設「否」 | Hermes plugin [H6] | 部分有（安裝要按確認） |
| 安裝前的展示只收圖與 markdown | MCPB [WB9]、VS Code Marketplace [WB10] | 沒有預覽功能 |

---

## 主題 4：Windows 沙盒（含 Linux 已實測的部分、網域白名單、Ollama）

### 4.1 每個機制的事實

**AppContainer／LPAC**

- Windows 8 起內建的程序隔離；存取權是「使用者的權限」與「AppContainer 的權限」的**交集**，一律 Low 完整性層級。**已查證** [MS2]
- **檔案**：預設拿不到檔案與登錄檔；要對資料夾的 DACL 明確加 AppContainer SID 的 ACE。Windows 系統檔本來就有給應用程式套件的 ACE，其他要用到的執行檔和資料檔都得自己鋪 ACL（Chromium 是安裝程式做的）。**已查證** [MS2][CR1]
- **網路**：沒有網路 capability 就連不了網路；粒度是「Internet 用戶端／內部網路／當伺服器」三種，**沒有網域或 IP 級的過濾**。**已查證** [MS1][MS2]
- **Loopback**：預設連不到本機 loopback；豁免要用 `CheckNetIsolation LoopbackExempt`，文件寫要系統管理員。**已查證（搜尋摘要）** [MS7]；MXC 文件佐證 [MX3]
- **沒打包的程式也能用**，但要自己呼叫 `CreateAppContainerProfile` 等 API，Microsoft 自己說「可能很複雜」。**已查證** [MS3]
- **要不要管理員**：文件沒寫要。**推測不需要，待實測**（腳本 F1–F5）。
- **Python／Node 在裡面能不能啟動**：取決於直譯器的安裝位置有沒有給應用程式套件的讀取 ACE。裝在使用者資料夾底下（per-user 安裝）的**推測讀不到**。**待實測**（腳本 P1、P2）。
- 同類專案的評價：OpenAI 評估過 AppContainer、Windows Sandbox、Mandatory Integrity Control，結論是都不完全合用（已查證（搜尋摘要）[OA3]）；Anthropic 的 sandbox-runtime 也沒有用 AppContainer（已查證 [AN2]）。SYNOX 的工具是單一用途的小程式，比 coding agent 窄，適配度應該比較好——**推測**。

**Job Object＋受限 token**

- Job Object 管的是資源與 UI，不是檔案與網路。**已查證** [CR1]；SYNOX 自己的實作也是這樣（`src/synox/sandbox.py:124`、`825-832`）。
- 受限 token 能收窄**檔案寫入**（只有列出的根目錄可寫），**讀取不受影響**；**擋不了網路**。**已查證** [AN2]；網路那一點是已查證（搜尋摘要）[OA4]
- 副作用：受限 token 下 Schannel 不能用，`System32\curl.exe`、PowerShell 的 `Invoke-WebRequest`、.NET `HttpClient` 的 HTTPS 都會失敗；Node、Python（自帶 TLS）不受影響。**已查證** [AN2]

**專用本機帳號＋WFP＋ACL**（sandbox-runtime Windows alpha、Codex elevated）

- 一次性提權安裝（一個 UAC），建一個本機帳號、全機的 WFP 過濾器（以該帳號的 SID 為鍵）；之後不用登出、不用再提權。**已查證** [AN2]
- 檔案：沙盒帳號對使用者的檔案本來就沒有權限，要用的資料夾加繼承式 ACE。**已查證** [AN2]
- 網路：擋掉該帳號的所有對外連線，只放行到 loopback 上 proxy 的埠範圍；網域白名單由 proxy 判斷。**已查證** [AN2]
- **已知缺口（文件自己寫的）**：程序換上 anonymous token 再開 socket 就不受過濾；SMB、WSL 這類由系統服務代送的流量不擋；DNS 解析不擋。文件原話是「把網路過濾當成擋直接連線的指令，不是擋專門寫來繞過它的程式」。**已查證** [AN2]
- sandbox-runtime 整包是 npm 套件（Apache-2.0，0.0.83），Windows 支援標 **alpha**。**已查證** [AN2]
- Codex：`[windows] sandbox = "elevated"`（專用低權限帳號＋檔案權限＋防火牆規則）或 `"unelevated"`（受限 token＋ACL）。**已查證（搜尋摘要）** [OA4]；repo 佐證 [OA1][OA2]

**MXC（Microsoft eXecution Container）**

- 嵌進應用程式的 SDK（Rust／.NET／Node），Windows 11 的預設後端是 `processcontainer`。**已查證** [MX1]
- 最低版本：Windows 11 24H2 build 26100.9278（2026-08 更新）、25H2 是 26200.9278。**已查證** [MX2]；規劃階段再讀一次同一頁：**完全沒有提到 Windows 版別（Home／Pro）與 Windows 10**（第九節）。
- 網路：每個容器自己的 WFP egress 過濾（預設擋，可照 IP／範圍、協定、埠放行），**每次啟動不用 UAC**；另外可指定一個 loopback proxy。**網域白名單要靠呼叫端自己提供的 proxy**，WFP 本身只認 IP。**已查證** [MX3]
- 檔案：`readonlyPaths`／`readwritePaths`／`deniedPaths` 政策。**已查證** [MX4]
- 2026-10-07 GA。**已查證（搜尋摘要，多家媒體一致）** [MX6]
- Node SDK `@microsoft/mxc-sdk` 1.0.1：MIT、要 Node ≥ 24、解開約 108 MB、相依 `node-pty`。**已查證** [MX5]　**沒有 Python SDK**；有獨立執行檔 `wxc-exec.exe` 吃 JSON 請求，但 README 沒有寫去哪裡下載（只說「用套件管理員裝 SDK」或從原始碼建）。**已查證** [MX1]（規劃階段補查，第九節）
- README 連到一個「streaming standard-I/O」範例（`samples/run-with-io-stdio-streaming/`），代表標準輸入輸出串流有被考慮到；長駐（MCP stdio 伺服器那種）行不行沒有寫。**已查證**（範例存在）[MX1]；長駐**待實測**
- sandbox-runtime 的實驗性 `mxc` 後端記錄的實際限制：MSYS2 程式（Git Bash）一啟動就當掉、沙盒內的程式可以在桌面開視窗、`%TEMP%`／`%LOCALAPPDATA%` 是每個指令一份用完即丟、子程序環境是封死的（拿不到使用者的環境變數）。**已查證** [AN2]
- **Home 版能不能用、`wxc-exec.exe` 怎麼取得與散布、長駐 stdio 行不行**：查不到／待實測。

**Windows Sandbox**

- 支援 Pro、Enterprise、Education；**Home 不支援**。`.wsb` 設定檔可以關網路、把資料夾唯讀對應進去；網路**預設是開的**。**已查證（搜尋摘要）** [MS4][MS5]
- 是用完即丟的輕量 VM；接不了 stdio 就當不了 MCP 的長駐管線——**推測**。

**Docker Desktop／WSL 2**

- 需求：Windows 10 22H2 或 Windows 11 23H2 以上、WSL 2.1.5 以上、8 GB RAM、BIOS 開虛擬化。Home 只能跑 Linux 容器（SYNOX 只要這個）。**已查證** [D1]
- 現在有 per-user 安裝模式，安裝與更新不用管理員；但「第一次啟用 WSL 2」要管理員，每台機器一次。**已查證** [D1][D2]
- 授權：超過 250 人或年營收超過 1000 萬美元的商用要付費。**已查證** [D1]
- Docker 只支援仍在 Microsoft 服務期內的 Windows 版本；Windows 10 Home／Pro 已於 2025-10-14 終止支援（已查證（搜尋摘要）[MS6]）→ Windows 10 上的 Docker Desktop 已不在官方支援範圍——**推測**（兩句合起來）。
- 隔離：檔案靠掛載；`--network none` 只剩 loopback 介面。**已查證** [D3]　免費版有沒有容器層級的網域白名單：**待查**。

### 4.2 別的專案在 Windows 上怎麼做

| 專案 | Windows 的做法 | 使用者要做什麼 | 來源 |
|---|---|---|---|
| Chromium | 受限 token＋Job Object＋替代桌面＋完整性層級，再疊 AppContainer（不給任何 capability 來斷網）。ACL 由安裝程式鋪 | 無 | 已查證 [CR1] |
| Claude Code | 原生 Windows **不沙盒**；要沙盒就在 WSL2 裡跑 | 裝 WSL2 | 已查證 [AN1] |
| Anthropic sandbox-runtime | Windows alpha：專用帳號＋WFP＋write-restricted token＋ACE；另有實驗性 MXC 後端 | 一次 UAC | 已查證 [AN2] |
| OpenAI Codex CLI | `elevated`（專用沙盒帳號＋防火牆＋ACL）優先，`unelevated`（受限 token＋ACL）退路 | elevated 要一次管理員設定 | 已查證（搜尋摘要）[OA4]；repo 佐證 [OA1][OA2] |
| VS Code agent sandbox | Windows 11 的 MXC，標 **Experimental**；要用網域過濾得開「本機網路存取」（proxy 在主機 loopback） | 只要 Windows Update 到指定 build | 已查證 [VS1] |
| Claude Desktop（MCPB 擴充） | 不是沙盒，但值得參考：`.mcpb` 把 `node_modules` **打包在裡面**，Node 執行環境**隨 Claude Desktop 出貨** | 無 | 已查證 [WB14] |

Gemini CLI、Cursor 在 Windows 的沙盒：這次沒查到官方文件（待查）。

### 4.3 選項比較表

| 選項 | 使用者要另外裝東西嗎 | 要管理員嗎 | 檔案隔離 | 網路隔離 | 網域白名單 | Home 版 | Windows 10 | SYNOX 工程量 | 狀態 |
|---|---|---|---|---|---|---|---|---|---|
| `none`（現況預設） | 否 | 否 | 無 | 無 | 無 | 可 | 可 | 0 | 已查證 |
| Job Object（現有，選用） | 否 | 否 | 無 | 無 | 無 | 可 | 可 | 已有 | 已查證 |
| Job＋受限 token | 否 | 否 | 只限寫入；讀不擋 | **無** | 無 | 推測可 | 推測可 | 中 | 已查證 [AN2]；待實測 |
| AppContainer（自製） | 否 | 推測否 | 有（要鋪 ACL） | 全開／全關 | **做不到** | 推測可 | 推測可 | 高（ctypes＋ACL 管理＋直譯器位置） | 待實測 |
| **MXC ProcessContainer** | **否**（SYNOX 要帶 MXC 執行檔或 SDK） | 每次啟動不用 | 有（政策） | 有（每容器 WFP） | 有（WFP 認 IP；網域要 SYNOX 自己起 loopback proxy） | **查不到** | **不行** | 中（沒有 Python SDK） | 已查證 [MX1][MX2][MX3]；整合待實測 |
| 專用帳號＋WFP | 否（SYNOX 帶 helper） | **一次 UAC** | 有（NTFS ACL） | 有（WFP，以 SID 為鍵） | 有（proxy）；有文件記載的繞過缺口 | 查不到 | 查不到 | 高（自製）／中（借用 sandbox-runtime，但它是 alpha 的 npm 套件） | 已查證 [AN2]；待實測 |
| Windows Sandbox | 否，但要啟用選用功能 | 推測要（啟用時） | 強（VM） | 可整個關 | 無內建 | **不行** | Pro 以上可 | 中；接 stdio 推測不行 | 已查證（搜尋摘要）[MS4][MS5] |
| Docker Desktop（WSL 2） | **要** | 啟用 WSL 2 那一次要 | 強 | `--network none` | 待查 | 可（Linux 容器） | 已不在官方支援 | 後端已有（只組 argv、未驗） | 已查證 [D1][D2][D3] |

### 4.4 「使用者什麼都不用裝」到得了嗎

| 使用者的機器 | 不用裝東西能拿到什麼 | 判斷 |
|---|---|---|
| Windows 11 24H2／25H2，已更新到 2026-08（網路的 loopback 伺服器功能要 2026-09）之後 | MXC：檔案＋網路＋（配 SYNOX 自己的 proxy）網域白名單，不跳 UAC | 文件上成立 [MX2][MX3]；Home 版、Python 整合、長駐 stdio 都**待實測** |
| Windows 11 但沒更新、或 Windows 10 | AppContainer 自製：檔案隔離＋「全斷網或全開網」 | **推測**可行，全部待實測 |
| 同上，願意按一次 UAC | 專用帳號＋WFP：檔案＋網域白名單（有已知缺口） | 文件上成立 [AN2]；最低 Windows 版本查不到 |
| 任何 Windows，願意裝 Docker Desktop | 容器：最接近 Linux 伺服器版的行為 | 不符合「不用裝」 |

**到得了一部分，而且取決於 Windows 版本。** 擁有者自己的開發機是 Windows 10 Home（`docs/lab/discussions/2026-11-10-sandbox-and-skill-containers.md:73`），MXC 與 Windows Sandbox 都用不了。

### 4.5 Windows 實測計畫

三個檔在 [tools/windows-sandbox-probe/](tools/windows-sandbox-probe/)，**都沒在 Windows 跑過**。怎麼跑、結果怎麼讀寫在那個資料夾的 README。預期（都是待實測的假設）：F1、F2 允許；F3、F4、F5 拒絕；N1、N2 拒絕；N3 允許；N4 拒絕；P1、P2 看安裝位置。

還沒寫腳本的：(a) MXC（`wxc-exec.exe` 怎麼取得還沒查到）；(b) 專用帳號＋WFP（會動到全機設定，要擁有者先同意）；(c) Docker Desktop（照既有的 `docs/handoff/container-verification.md`）。

### 4.6 Linux 這邊已實測的

機器：Ubuntu 24.04.5、核心 6.18、root、PID 1 不是 systemd。

| 項目 | 結果 | 標示 |
|---|---|---|
| `bwrap`、`podman` | 沒裝 | 已實測 |
| `systemd-run` | 有執行檔，但系統不是用 systemd 開機，用不了 | 已實測 |
| `unshare --net` | 新的 network namespace 裡只有 `lo`；連 `1.1.1.1:443` 和主機的 `127.0.0.1:<埠>` 都是 `Network is unreachable` | 已實測 |
| **網域白名單** | 主機上跑一個白名單 CONNECT proxy（聽 unix socket），namespace 裡用一個轉接程式把 `127.0.0.1:3128` 接到那個 socket：`registry.npmjs.org` 回 200；`example.com`、`pypi.org` 被 proxy 回 403；直連 `1.1.1.1` 不通 | 已實測 |

限制：這次是 root 建 namespace。一般使用者要靠非特權 user namespace，而 Ubuntu 24.04 預設用 AppArmor 限制它，bwrap 會出現 `setting up uid map: Permission denied`（已查證（搜尋摘要）[UB1]）。研究機器上那個 sysctl 不存在，所以這個坑沒踩到，**伺服器驗證時要查**。

### 4.7 網域白名單實際上怎麼強制

共通原理（sandbox-runtime、MXC、VS Code 一致）：**先把直連的路全部封死，只留一條通到「在沙盒外、由宿主控制」的 proxy，由 proxy 照主機名決定放不放。** 只設 `HTTPS_PROXY` 而不封直連，不算強制。

| 平台 | 封直連的手段 | 通到 proxy 的路 | 狀態 |
|---|---|---|---|
| Linux（bwrap／unshare） | 拿掉 network namespace | unix socket 掛進沙盒，裡面再轉成本機埠 | **已實測**；sandbox-runtime 同做法 [AN2] |
| Linux（容器） | `--network none` [D3] | 把 proxy 的 unix socket 掛進容器 | 推測，待實測 |
| Linux（systemd） | `PrivateNetwork=yes`（現有） | 同上；`IPAddressAllow` 類的設定只認 IP | 待查 |
| Windows 11（MXC） | 每容器 WFP egress 預設擋 | 指定 loopback proxy；要開主機 loopback 存取 | 已查證 [MX3]；待實測 |
| Windows（專用帳號＋WFP） | 全機 WFP 規則擋該帳號，只放行 loopback 的 proxy 埠範圍 | loopback | 已查證 [AN2]；要一次 UAC；待實測 |
| Windows（AppContainer 自製） | 不給 `internetClient` | **沒有路**：loopback 也被擋，豁免要管理員 | 只能全斷或全開；推測，待實測 |

不管哪個平台都有的限制：

- proxy 只看用戶端自報的主機名、不解 TLS，所以有 domain fronting 的空間；放行 `github.com` 這類大網域等於開了外洩的路。**已查證** [AN1]
- 不走 proxy 環境變數的程式連允許的主機也連不上；UDP、QUIC、ICMP 出不去。**已查證** [AN1]
- Windows 上 DNS 解析由系統服務代做，擋不住（可當低頻寬外洩通道）。**已查證** [AN2]
- 建置期（`npm ci`）也該套白名單：至少 `registry.npmjs.org`；要跑 `npm audit signatures` 還得加 Sigstore 的 TUF 主機（已實測，主題 7）。

### 4.8 假設 F 逐條

| 假設 | 判定 | 理由 |
|---|---|---|
| F(1) 技能的環境不繼承使用者的環境變數 | 推翻（就現況） | 現在會繼承，只過濾名字像密鑰的（第四節第 11 列）。當成目標是對的：MXC 的子程序環境本來就是封死的、sandbox-runtime 在 Windows 也只帶 `PATH` 與 proxy 變數 [AN2] |
| F(2) 讀不到別的 pack 的資料夾 | 部分 | 只有 bwrap／container 成立。`none`、jobobject 下什麼都讀得到，而 Windows 預設就是 `none` |
| F(3) 預設斷網＋宣告網域的 egress 白名單 | 推翻（就現況）；可行性見 §4.7 | 現在只有「有／沒有 network」；而且斷網只在真沙盒後端生效 |
| F(4) 帳號連接走工具頁的「連接」表單，密碼不進技能 | 確認 | `data/pack_secrets.json.enc`、網頁永遠不回傳值（`docs/security.md:46`）；secret 只經環境變數名單進子程序（`src/synox/packs/loader.py:585-607`）。但技能程序本身**拿得到**那個 token 的值——要做到看不到得由 proxy 代填（sandbox-runtime 的 credential masking 是這個思路 [AN1]） |

### 4.9 擁有者的範圍外想法（把 Ollama／SYNOX 開給別人）：會衝突的沙盒設計

只標衝突，不展開。

| 事實 | 來源 |
|---|---|
| Ollama 本機 API（`http://localhost:11434`）**不需要驗證** | 已查證 [OL2] |
| Ollama 預設只綁 `127.0.0.1:11434`；設 `OLLAMA_HOST` 才對外 | 已查證 [OL1] |
| SYNOX 網頁只綁 `127.0.0.1`，寫死、config 改不了，預設埠 8830 | 已查證（`docs/security.md:59`） |

1. **給技能 loopback 的設計＝把 Ollama 交給技能。** sandbox-runtime 在 Windows 的 `--allow-loopback` 是全機設定 [AN2]；VS Code 在 Windows 要用網域過濾就得開本機網路 [VS1]；MXC 的 proxy 模式也要主機 loopback [MX3]。選這些路時，要確認放行的只有 proxy 的埠。
2. **SYNOX 現有的 bwrap 後端：宣告了 `network` 就不加 `--unshare-net`**（`src/synox/sandbox.py:173-174`），技能直接在主機的網路裡，連得到 11434 和 8830。改成「namespace＋proxy」後主機 loopback 預設連不到（已實測），這個洞順便補上。
3. Docker Desktop 的容器可以用 `host.docker.internal` 連回主機 [D2]；只有 `--network none` 的容器不行。
4. 如果之後把 Ollama 設成 `0.0.0.0`，區網上任何人都能不經驗證使用；SYNOX「只綁 127.0.0.1」的寫死規則也得改。兩件都是政策變更，不在這份範圍內。
5. 技能若要用本機模型，應該經 SYNOX 轉（由 SYNOX 決定誰能叫、叫多少），不要讓技能直連 11434——**推測**（設計建議）。

---

## 主題 5：技能與工具文字裡的提示注入

SYNOX 的文字怎麼進 AI、現在有哪些結構性保護，在第四節 §4.3。

### 5.1 真實事件與公開示範

| 事件 | 重點 | 標籤／來源 |
|---|---|---|
| **MCP Tool Poisoning**（Invariant Labs，2025-04） | 惡意指令藏在工具說明裡，使用者看不到、模型看得到。PoC：`add(a, b, sidenote)` 的說明第二段用 `<IMPORTANT>` 叫模型先讀使用者的設定檔與 SSH 公鑰、塞進 `sidenote`，並交代「不要提到你讀了檔」 | PoC 原始碼**已查證** [PI1]；部落格原文**待查** [Y1] |
| **Shadowing＋sleeper rug pull**（同上） | 惡意伺服器的說明去改寫**別的**可信伺服器（寄信、通訊軟體）的行為；「第二次載入才把工具介面換成惡意的」；外洩的資料接在一長串空白後面，UI 不捲到最右邊看不到 | **已查證** [PI2] |
| **postmark-mcp**（2025-09） | npm 上的 MCP 伺服器，前 15 版乾淨，1.0.16 加一行把每封信密件副本給攻擊者。這是**程式碼型**的更新夾帶 | **待查** [X11] |
| **ClawHavoc**（Koi，2026-02） | SKILL.md 的「Prerequisites」叫人／代理去下載執行外部腳本 | 數字**待查** [X2]；OWASP 轉述的手法**已查證** [PI3] |
| **Snyk ToxicSkills**（2026-02） | 掃 3,984 個技能：36.82% 有安全問題、13.4% 有嚴重問題、人工確認 76 個惡意 | 數字**已查證於 OWASP 的轉引** [PI4]；Snyk 原文**待查** [X7] |
| **Agent Skills in the Wild**（arXiv 2601.10338） | 31,132 個技能中 26.1% 至少一個弱點；**附可執行腳本的技能有弱點的勝算是純指令型的 2.12 倍** | **待查** [Y5] |
| **Trail of Bits**（2026-06-03） | 測過的技能掃描器**全部繞過**，各不到一小時 | OWASP 的轉述**已查證** [PI5]；原文**待查** [Y6] |

對 SYNOX 的對照（已查證＋推測）：

- Invariant 的 PoC 把指令放在說明的**第二段**；SYNOX 的 `clean_text` 只留第一段、截 200 字（`src/synox/packs/mcp.py:599-603`），這個**原樣的** PoC 會被切掉。但攻擊者只要把指令放進前 200 字就過了（推測）。
- 「多一個參數夾帶資料」：SYNOX 的參數來自 `inputSchema`，`tools_allow` 的工具有什麼參數就給什麼，沒有「這個參數可疑」的判斷；第 4 關會擋的是已存 secret 與路徑，不擋筆記內容（`docs/security.md:182`）。
- 「Prerequisites 叫人貼指令」這一型，**沙盒與 AI 權限控制都擋不到**——它騙的是人。SYNOX 的 AI 沒有 shell 工具，所以「叫代理去跑 curl」不成立，但「在 README／預覽／SKILL 裡叫擁有者自己去跑」成立（推測）。

### 5.2 業界的防禦手法，與各自的極限

| 手法 | 內容 | 極限 | 標籤／來源 |
|---|---|---|---|
| **標示／隔離不可信輸入**（spotlighting） | Microsoft 的三種：delimiting、datamarking、encoding | 2025-10《The Attacker Moves Second》：12 種已發表的防禦在自適應攻擊下都被打穿 | 兩篇都**待查** [Y7][Y8] |
| 同上，OWASP 的講法 | 「Keep trusted instructions separate from untrusted data, but **do not treat text labels or prompt wording as an enforcement boundary**.」 | — | **已查證** [PI6] |
| **樣式掃描／過濾** | 掃「ignore previous instructions」之類 | OWASP：「Screening does not stop an injection that it fails to detect…Enforce permissions and parameter validation at the tool boundary」；「Pattern lists and normalization do not translate text」（換語言就漏）；AST08：正規表示式抓得到 `curl`，抓不到一句叫代理「把上面那個路徑的檔案送到下面那個位址」的話 | **已查證** [PI6][PI5] |
| **能力分離：Dual LLM** | 有權限的模型只看可信輸入；隔離的模型處理不可信內容、沒有工具 | 作者自己後來說它沒有完全解決 | **待查** [Y9] |
| **能力分離：CaMeL**（2025） | 把使用者的要求轉成程式、用 capability 追蹤資料流 | 官方 repo 自己標「research artifact…might not be fully secure」 | repo **已查證** [PI17]；論文**待查** [Y10] |
| **設計模式**（2025-06） | 代理一旦吃進不可信輸入，就要被限制到「那個輸入不可能觸發有後果的動作」 | 通用型代理做不到可靠保證 | **待查** [Y11] |
| **致命三要素／Rule of Two** | 私有資料＋不可信內容＋對外通訊三樣同時有就會被偷；一個 session 裡三樣最多兩樣 | 提出者自己說這不是終點 | **待查** [Y12] |
| **人按確認** | 見 5.3 | 卡出太多人會亂按（Claude Code 文件把「prompt fatigue mitigation」列成一項設計） | **已查證** [PI13] |
| **釘住工具定義** | 雜湊整個工具定義（含 schema、annotations），變了就要重新審 | 只偵測定義變了，偵測不到定義沒變、伺服器行為變了 | **已查證** [PI7] |

### 5.3 各家怎麼建議

**MCP 規格 2025-11-25**（已查證 [PI9][PI10]）：

- 「there **SHOULD** always be a human in the loop with the ability to deny tool invocations.」
- 用戶端 SHOULD：「Prompt for user confirmation on sensitive operations」「Show tool inputs to the user before calling the server, to avoid malicious or accidental data exfiltration」。
- 「clients **MUST** consider tool annotations to be untrusted unless they come from trusted servers.」
- 規格的「Security Best Practices」獨立頁：**查不到**。

**OWASP**（已查證）：

- LLM01:2025：「it is unclear if there are fool-proof methods of prevention for prompt injection」；七項緩解裡有 ④最小權限（功能在程式裡做，不交給模型）⑤高風險動作要人核准 ⑥**隔離並標明外部內容**。[PI8]
- MCP Security Cheat Sheet：「Trust tool descriptions blindly — they are a prompt injection vector」（列在不要做的事）；「Pin reviewed tool definitions using cryptographic hashes and require review when they change」；「Never auto-approve tool calls」；「Use tag stripping and instruction-pattern detection only as additional filtering or alerting measures. They cannot establish that the remaining text is safe」；「Never allow web content or untrusted data to trigger MCP server installation」。[PI7]
- Agentic Skills Top 10（incubator）：AST01 明寫惡意技能同時利用「code layer」與「natural language instruction layer」，並建議「Never auto-execute "Prerequisites" sections without explicit user review」。[PI3][PI4]
- Top 10 for Agentic Applications 2026：**待查** [Y15]。

**Anthropic**（已查證）：

- Skills：「Use Skills only from trusted sources」「a malicious Skill can direct Claude to call tools or run code in ways that don't match the Skill's stated purpose」「Treat like installing software」。[PI11]
- 企業審查的風險表：**Code execution＝High**、**Instruction manipulation＝High**、MCP server references＝High、Network access patterns＝High、**Tool calls＝Medium**。審查清單第 1 項「Read all Skill directory content」、第 3 項「Check for adversarial instructions」；「Treat every update as a new deployment requiring full security review」「Compute checksums of reviewed Skills」。同頁的自動掃描明講「Scanning complements, but doesn't replace, the review checklist」。[PI12]
- frontmatter 的限制：`name` ≤64 字、不得含 XML 標籤與保留字；`description` ≤1,024 字、不得含 XML 標籤。[PI11][M1]
- Claude Code：連網指令預設不自動核准、抓網頁用另一個模型先摘要再給主模型、「no system is completely immune to all attacks」。[PI13]
- 瀏覽器代理（2025-11-24）：加了防護之後攻擊成功率仍約 1.4%，「prompt injection is far from a solved problem」。[PI14]（經摘要工具讀到，數字建議再對原頁）

**OpenAI**：

- Model Spec（已查證 [PI15]）：引用的文字、附件、工具輸出「are assumed to contain untrusted data and have no authority by default」；建議把不可信資料放進 YAML、JSON 或 XML 格式，並把每個工具的可信度、副作用告訴模型。
- 「Safety in building agents」指南（「Keep tool approvals on」）與 Atlas 強化文（「unlikely to ever be fully 'solved'」）：**待查** [Y13][Y14]。
- Agents SDK 有 tool guardrails 與人工核准：已查證其存在 [PI16]。

**OpenClaw**（最像 SYNOX 的同類；已查證 [O3]）：「Treat third-party skills as **untrusted code**. Read them before enabling.」

### 5.4 小結

1. 各家的共識是**分層**，而且把重心放在結構：最小權限＋執行前驗參數＋高風險動作人按確認＋釘住定義。提示層的標示與樣式掃描都被明講「不是邊界」。SYNOX 的第 4、5 關方向跟這個一致（`docs/security.md:182-183`、`410`）。
2. SYNOX 還沒做、而來源明確建議的：**釘住 MCP 工具定義**（[PI7]）、**安裝前讓人讀到會給 AI 的全部文字**（[PI12] 審查清單第 1 項）、**frontmatter／summary 的長度與字元限制**（[PI11][M1]）、**把資料外傳也當成要確認的動作**（[PI9]「Show tool inputs…to avoid…data exfiltration」）。

---

## 主題 6：授權相容性與名稱

**先聲明：這不是法律意見。**（`LICENSING.md` 也這樣寫。）

### 6.1 能不能匯入、轉換、當成 SYNOX pack 再散布

| 上游的東西 | 授權 | 可以改、再散布嗎 | 要做什麼 | 標籤 |
|---|---|---|---|---|
| OpenClaw 主程式 | MIT | 可以 | 保留著作權行與授權全文 | 已查證 [O1] |
| ClawHub 上的**技能** | MIT-0（「ClawHub does not support per-skill license overrides」） | 可以，含商用 | 不用署名 | 已查證 [C2][L1] |
| ClawHub 上的 **plugin／package** | 查不到 | 逐一看每個套件自己的授權 | — | 查不到 [C1] |
| Hermes 主程式（含 repo 裡的技能） | MIT | 可以 | 保留著作權行與授權全文 | 已查證 [H1] |
| `anthropics/skills` | Apache-2.0 | 可以 | 附授權、改過的檔標示、保留 NOTICE；不含商標權 | 已查證 [M3] |
| Agent Skills 規格 | 程式 Apache-2.0、文件 CC-BY-4.0 | 可以 | 引用文件要署名 | 已查證 [M2] |
| GitHub 上其他人的技能 repo | 各自不同，可能沒有授權 | **沒寫授權＝不能散布** | 匯入器要讀 `SKILL.md` 的 `license` 欄位與 repo 的 LICENSE，沒有就擋或標紅 | 推測（依據 [M1]） |

跟 SYNOX 自己的授權合不合：

- MIT、MIT-0、Apache-2.0 的東西都可以放進 AGPL-3.0 的專案。**待查**（gnu.org 開不到，依搜尋摘要）[X15]
- 反方向不行：AGPL 的程式不能放進 Apache-2.0 的 SDK。所以**匯入器如果放在 SDK 那一側（`src/synox/sdk/`，Apache-2.0），不能抄核心（AGPL）的程式碼**；核心反過來呼叫 SDK 側的程式可以。**推測**（依據 `LICENSING.md` 的範圍表）
- 轉出來的 pack 是上游技能的衍生作品，授權跟著上游；它不會因為被 SYNOX 載入就變成 AGPL（`LICENSING.md`：「你的工具若只是透過 pack.json 與 SDK 被 SYNOX 載入，不會因此變成 AGPL」）。**已查證**
- 收進 SYNOX_Libs（那個 repo 是 AGPL-3.0）的話，每個 pack 資料夾要帶自己的授權聲明，MIT 的部分要留著原本的著作權行。**推測**
- **MIT-0 只保證「上傳的人給了你權利」**。上傳的人如果是抄別人的，ClawHub 的 MIT-0 聲明救不了你。這是策展時要人看的理由之一。**推測**

### 6.2 名稱與商標

| 事實 | 標籤 |
|---|---|
| MIT 與 MIT-0 的條文沒有授予商標權；Apache-2.0 第 6 條明寫不授予 | 已查證 [O1][L1][M3] |
| npm 的 **`openclaw-core` 已經被不相干的第三方註冊**（2026-04-05 建立，Apache-2.0，自稱某個 Agent OS 的底層） | 已查證 [N1] |
| npm 的 **`hermes-core` 被 npm 官方帳號持有**（2018 年的 `0.0.2-alpha.0`） | 已查證 [N2] |
| PyPI 的 `hermes-core` 是 Cossack Labs 的另一個 Hermes；PyPI 的 `openclaw` 是第三方的安裝器；npm 的 `hermes-agent` 是第三方做的「Unofficial npm bridge」；PyPI 的 `openclaw-core` 目前沒人註冊 | 已查證 [N5][N7][N8][N9] |
| OpenClaw 自己就是因為商標意見被迫改名兩次的專案 | 待查 [X10] |
| OpenClaw、Hermes 官方的商標使用規範；npm 對名稱爭議的政策 | 查不到（OpenClaw repo 根目錄沒有 `TRADEMARK.md` [O19]） |

**建議（推測）**：不要用 `openclaw-core`、`hermes-core` 當套件名或模組名；用敘述句講相容性：「可匯入 OpenClaw／Hermes／Agent Skills 格式的技能」——這跟 SYNOX 自己的 `TRADEMARK.md` 對別人的要求一致；功能用中性的名字（例如 `synox-sdk import`）。

---

## 主題 7：npm 供應鏈

### 7.1 `--ignore-scripts` 的相容性現實

- 全體：一篇 2022 年的研究量到 **2.2%（33,249 個）套件定義了安裝腳本**。**待查**（二手：Semgrep 2026 年的文章引述；原論文沒讀到）[R1]
- 熱門套件裡的比例：**查不到**專門的量測。替代指標：Bun 內建一份「預設允許跑 lifecycle script」的清單，共 367 行，裡面有 esbuild、sharp、better-sqlite3、sqlite3、bcrypt、node-pty、canvas、puppeteer、electron。**已查證** [BN1]
- npm 官方文件：安裝腳本「唯一正當的用途是必須在目標架構上做的編譯」。**已查證** [NP3]

**實測**（Linux x64、Node 22.23.4、npm 10.9.9；`npm ci --ignore-scripts`，只檢查檔案在不在，**沒有載入或執行任何第三方套件**）：

| 套件 | 鎖檔裡 `hasInstallScript` | `npm ci --ignore-scripts` 結束碼 | 裝完的狀態 | 判斷 |
|---|---|---|---|---|
| esbuild 0.25.0 | 有 | 0 | 平台執行檔在（走 optionalDependencies） | 不受影響 |
| sharp 0.33.5 | 有 | 0 | 預編譯的 `.node` 在（同上） | 不受影響 |
| better-sqlite3 11.8.1 | 有 | 0 | 只有 `binding.gyp`，**沒有 `.node`** | 壞 |
| sqlite3 5.1.7 | 有 | 0 | 同上 | 壞 |
| bcrypt 5.1.1 | 有 | 0 | 同上 | 壞 |
| node-pty 1.0.0 | 有 | 0 | 同上 | 壞 |
| puppeteer 24.2.0 | 有 | 0 | 沒有下載瀏覽器 | 壞 |
| @modelcontextprotocol/server-filesystem 2025.8.21 | 135 個相依都沒有 | 沒跑 ci | — | 純 JS，不受影響 |

三個結論：

1. **壞的時候是無聲的**：結束碼都是 0，SYNOX 會寫「環境建好了」（`src/synox/packs/envs.py:627-628`），要到工具第一次被呼叫才出錯。**已實測＋已查證**
2. **鎖檔本身就標了誰有安裝腳本**：`hasInstallScript` 是 lockfile 的正式欄位（已查證 [NP2]）。SYNOX 讀 JSON 就能在第 2 關列出來，不用連網。
3. 壞的集中在：原生資料庫與加密模組、要下載瀏覽器的、Electron。常見的純 JS MCP 伺服器不受影響。

**生態系的方向**（對 SYNOX 有利）：

- npm 12.0.0（2026-07-08）：「相依套件的 lifecycle script 預設被擋，除非根套件的 `allowScripts` 政策允許」；配套指令 `npm approve-scripts`。**已查證** [NP4][NP5][NP6]
- pnpm：不跑相依套件的建置腳本，除非列在 `allowBuilds`。Bun：只跑白名單裡的。**已查證** [PN1][BN1]
- 但使用者機器上的 npm 版本不一：Node 22 → npm 10.9.x、Node 24.22.3 → npm 11.19.1、Node 26.13.1 → npm 11.20.0；npm 12 只隨 Node 27 alpha 出貨（已查證 [ND1]）。所以 SYNOX **不能假設**系統 npm 認得 `allowScripts`；`--ignore-scripts` 在各版都有效，且優先於 `allowScripts`（已查證 [NP4]）。

**解法（由輕到重）**：

| 解法 | 內容 | 代價 | 標示 |
|---|---|---|---|
| a. 先講清楚 | 第 2 關讀鎖檔的 `hasInstallScript`，報告列出「這幾個套件有安裝腳本，不會跑」；建完環境後檢查這些套件有沒有 `.node`／執行檔 | 小，離線 | 推測可行（欄位已查證 [NP2]） |
| b. 逐套件白名單 | pack.json 宣告「這幾個釘版本的套件要跑安裝腳本」，報告紅字列出、擁有者確認後才 `npm rebuild <那幾個>` | 等於在使用者機器上執行第三方程式碼，**沒有沙盒時就是 T2 的風險本身**；node-gyp 還需要編譯器 | 推測；待實測 |
| c. 作者預先打包 | pack 直接帶 `node_modules`（含預編譯檔）。packs.lock 會把每個檔都算進雜湊（`src/synox/packs/lock.py:88-92`） | 每個平台一份、檔案大；MCPB 就是這樣 [WB14] | 已查證（機制）；推測（適用性） |
| d. 換套件 | 選有預編譯檔或純 JS／WASM 的替代品 | 作者的事 | 推測 |
| e. 容器 | 安裝腳本在建映像時跑 | 要容器引擎 | 已查證（現有 `runtime.container`） |

### 7.2 從「只有一個套件名」產生並驗證鎖檔

**已實測的流程**（空資料夾裡只有一個最小的 `package.json`）：

```
npm install --package-lock-only --ignore-scripts --no-audit --no-fund --save-exact \
    --registry=https://registry.npmjs.org/ <名字>@<版本>
```

| 觀察 | 結果 |
|---|---|
| 時間 | 10 個套件各 0.5–3.5 秒 |
| 有沒有下載套件本體／建 `node_modules` | 沒有 |
| 產出 | `lockfileVersion: 3`；每個套件都有 `resolved`（全是官方 registry）與 `integrity`（sha512）；`package.json` 寫入精確版本 |
| 跨平台 | 在 Linux 產的鎖檔含所有平台的 optional 套件 |

- **已實測的缺口**：把鎖檔的 `integrity` 全刪掉，`npm ci` 照裝、結束碼 0；連 `resolved` 一起刪也照裝。只有 `integrity` **寫錯**時才 `EINTEGRITY`。SYNOX 現在不要求 `integrity` 存在（第四節第 3 列）。
- 避開「剛發佈就被下毒」的版本：npm 有 `--before <日期>`，11.10.0 起有 `min-release-age <天數>`；pnpm 的 `minimumReleaseAge` 預設就是 1 天。**已查證** [NP4][NP5][PN1]

**誰來產生鎖檔**——兩種做法：

- 工具庫維護者產生（鎖檔包在 `.synoxpack` 裡，sha256 進 `index.json`）：使用者永遠不解析套件名，最安全；跟現有的工具庫機制同形。
- 使用者機器上產生（「輸入套件名就裝」）：最方便，但要在安裝當下做名字、年齡、來源的檢查，而且等於讓使用者決定信任哪個 npm 套件。

### 7.3 typosquatting 與惡意套件的偵測做法

| 做法 | 它保證什麼 | 它不保證什麼 | 來源 |
|---|---|---|---|
| `npm audit signatures` | 驗 registry 對每個版本的簽章（防鏡像或 proxy 竄改），也驗 provenance | 不看套件內容。**已實測**：研究機器上跑失敗，因為它要連 Sigstore 的 TUF 來源，不只 `registry.npmjs.org` | 已查證 [NP7][NP9] |
| provenance（Sigstore） | 把套件連到原始碼 repo 與 CI 建置 | 「不保證套件沒有惡意程式碼」；要發佈者自己開 | 已查證 [NP8] |
| 發佈年齡冷卻 | 惡意版本通常幾小時內被下架，晚一天裝就避開 | 潛伏久的 | 已查證 [PN1][NP4] |
| OpenSSF package-analysis／malicious-packages | 動態分析；已通報惡意套件的資料庫（OSV 格式） | 研究專案，不是安裝時的門；只有已通報的 | 已查證 [OS1][OS2] |
| Socket 類的啟發式 | 名字像熱門套件就警告、新增安裝腳本就標記 | 商業服務；確切規則沒查到原始文件 | 已查證（搜尋摘要）[SK1] |
| 預設不跑安裝腳本 | 2025-09 的 Shai-Hulud 蠕蟲就是靠惡意 post-install 腳本散播 | 惡意程式碼寫在主程式裡的（一被 `require` 就跑） | 已查證（搜尋摘要）[GH1][GH2] |

對 SYNOX 的含意（**推測**）：這些檢查放在**工具庫上架時**最有效；使用者端只做便宜、離線的（來源、`integrity` 齊不齊、`hasInstallScript`、套件數）。不管哪一種都只降低機率——npm 套件一被載入就在技能的權限下跑，**真正的防線是執行期沙盒**。

### 7.4 誰提供 Node

| 做法 | 對非工程師的安裝體驗 | 安全／可控 | 事實 |
|---|---|---|---|
| a. 系統的 Node（現況） | 最差：要自己去裝 Node.js，否則 pack 不載入 | 版本不受控（npm 10／11／12 行為不同）；`{node}` 不在鎖裡（`src/synox/packs/scan.py:1552`） | 已查證 |
| b. SYNOX 自己管一份可攜版 Node | 好：使用者無感。官方 `node-v24.22.3-win-x64.zip` 37.8 MB，有 `SHASUMS256.txt` 與簽章檔可驗 | SYNOX 釘版本、驗雜湊；但要跟 Node 的安全更新（24.x 維護到 2028-04-30） | 已查證 [ND1][ND2][ND3]；Node 核心是 MIT、可再散布（規劃階段補查，第九節） |
| c. 容器裡的 Node | 差：要 Docker Desktop | 最好 | 已查證 |
| d. 作者把 `node_modules` 打包、執行環境由宿主提供 | 好 | 等於 b＋7.1 的解法 c；Claude Desktop 的做法 | 已查證 [WB14] |

注意：b 的 Node 會放在使用者資料夾底下，AppContainer 或專用帳號預設讀不到那裡，沙盒與「自己管 Node」要一起設計。**待實測**

---

## 主題 8：隔離瀏覽器內容（套件預覽）

### 8.1 規格上確定的事（已查證）

| 事實 | 來源 |
|---|---|
| `sandbox`（空值）＝全部限制：內容被當成唯一的 **opaque origin**，表單、腳本、各種擾人的 API 關掉，連結不能指向別的 navigable | [WB1] |
| **`allow-scripts`＋`allow-same-origin` 同時給、而且內嵌頁跟外層同源** →「allows the embedded page to simply remove the `sandbox` attribute and then reload itself, effectively breaking out of the sandbox altogether」 | [WB1]；MDN 也寫「strongly discouraged」[WB2] |
| 「Potentially hostile files should not be served from the same server as the file containing the `iframe`…it should be served from a separate dedicated domain」——因為使用者被騙去**直接開**那個網址時，沒有 iframe 的 sandbox 保護 | [WB1] |
| opaque origin 讀寫不到 `document.cookie`、`localStorage` | [WB1] |
| 沒給 `allow-scripts` 時，「sandboxed automatic features」旗標也開著：自動播放關掉，**`<meta http-equiv="refresh">` 不會導頁** | [WB1] |
| **CSP 的 `sandbox` 指令**：對「被請求的那個資源」套跟 iframe sandbox 一樣的限制（含 opaque origin）；`<meta>` 與 Report-Only **不支援**，只能用 HTTP 標頭 | [WB3] |
| `default-src` 是所有 fetch 指令的後備；`frame-src` 管「可以載進子 navigable 的網址」 | [WB4][WB5] |
| **`srcdoc`／`blob:`／`data:` 文件會繼承來源文件的 CSP** | [WB5] |
| **沙盒頁（沒有 `allow-same-origin`）發出的請求一律算 cross-site**，所以帶不了 `SameSite=Lax/Strict` 的 cookie | Chrome 團隊的 explainer [WB6] |
| **cookie 不照 port 隔離**：「Cookies do not provide isolation by port」 | [WB7] |
| SVG 只有在**圖片情境**（`<img>`、CSS 背景）才關 JS 與外部資源；直接開或用 `<iframe>`／`<object>` 嵌就不受限 | [WB8] |

### 8.2 同類產品怎麼處理「作者給的展示內容」

| 產品 | 做法 | 標籤／來源 |
|---|---|---|
| **MCP Bundles（.mcpb）** | manifest 只有 `icon`（png）、`icons`、`screenshots`（圖片路徑）、`long_description`（markdown）。**沒有作者自帶的 HTML／JS** | 已查證 [WB9] |
| **VS Code Marketplace** | 「Due to security concerns, `vsce` will not publish extensions that contain user-provided SVG images」；icon 不能是 SVG | 已查證 [WB10] |
| **VS Code webview**（已安裝的擴充套件畫 UI） | 「JavaScript is disabled in webviews by default」；建議從 `default-src 'none'` 開始加 | 已查證 [WB11] |
| **MCP Apps**（MCP 的 UI 延伸，草案；伺服器給 HTML、host 畫出來，**有 JS**） | Host 與 iframe **MUST 不同源**；文件 MUST 由 host 自己控制的伺服器送出；沒宣告 CSP 時 MUST 用一組 `default-src 'none'` 起跳、`connect-src 'none'` 的預設；威脅模型明列「View performs phishing or social engineering」 | 已查證 [WB12] |
| **Google 的使用者內容** | 傳統做法是放到獨立網域；非 HTML 的內容用 `nosniff`＋`Content-Disposition: attachment`＋`default-src 'none'` | 待查 [Y16] |

觀察（推測）：**安裝前**的套件展示，業界的常態是靜態圖＋markdown；會跑作者 JS 的（MCP Apps、webview）都是**已經信任、已經安裝**之後的事，而且要求不同源。

### 8.3 套到 SYNOX：嵌法比較

| 嵌法 | 在 SYNOX 行不行 | 理由 |
|---|---|---|
| `srcdoc` | **不建議** | 會繼承主頁的 CSP：主頁是 `style-src 'nonce-…'`（`src/synox/web/server.py:398`），預覽裡沒有 nonce 的 `<style>` 與 `style=""` 全被擋 → 預覽沒有樣式（推測自規格；待實測） |
| `blob:` URL | **不建議** | 同樣繼承 CSP；而且主頁 `frame-src 'self'`（`server.py:399`）不含 `blob:`，要改主頁 CSP（推測；待實測） |
| 另一個 port 當「別的來源」 | **沒有用** | 不同 port 是不同 origin，但 cookie 不照 port 隔離 [WB7]；而且要多開一個埠，跟「只綁一個 127.0.0.1 埠」的現況（`docs/security.md:59`）不合 |
| **`<iframe sandbox="" src="同源的唯讀路由">`＋那條路由自己的 CSP 標頭（含 `sandbox`）** | **建議** | 主頁的 `frame-src 'self'` 本來就允許；路由自己帶 CSP 不受主頁 nonce 影響；回應標頭的 `sandbox` 讓「被騙去直接開網址」時也是 opaque origin、沒有腳本——補上「hostile files 不要同站」在 localhost 做不到獨立網域的缺口 |

### 8.4 什麼擋住它碰 SYNOX 的 cookie／API／網路

| 預覽想做的事 | 擋它的東西 | 標籤 |
|---|---|---|
| 跑 JS | iframe `sandbox`（沒有 `allow-scripts`）＋回應 CSP 沒有 `script-src`（`default-src 'none'`）＋回應 CSP 的 `sandbox` | 已查證（規格） |
| 讀 `document.cookie`／localStorage、碰父頁 DOM | 沒有 JS；就算有也是 opaque origin。另外 session cookie 本來就是 HttpOnly（`server.py:367`） | 已查證 |
| 用 `<img>`／CSS `url()`／`@import`／字型去打 `/api/…` 或外面的主機 | 回應 CSP：`default-src 'none'; img-src data:; style-src 'unsafe-inline'`——沒有任何網路來源被放行 | 已查證（規格）；各瀏覽器實際行為待實測 |
| 就算請求真的發出去，帶著擁有者的 session | 沙盒頁的請求算 cross-site，`SameSite=Lax` 的 cookie 不會帶（SYNOX 的 cookie 是 Lax：`server.py:367`） | 已查證（Chrome 的說明 [WB6]）；Firefox／Safari 待實測 |
| 送表單 | `sandbox` 沒有 `allow-forms`；CSP 再加 `form-action 'none'` | 已查證 |
| 自動轉址（meta refresh） | 沒有 `allow-scripts` 就不轉 | 已查證 [WB1] |
| 開新視窗、把整個 SYNOX 頁導走 | `sandbox` 沒有 `allow-popups`、`allow-top-navigation` | 已查證 |
| **使用者點預覽裡的連結，iframe 自己導到外站** | 主頁 `frame-src 'self'` **可能**會擋；規格上沒找到能確定的句子 | **待實測**。保守做法：預覽檢查器直接不收外部網址的 `<a href>` |
| 用 CSS 屬性選擇器偷同頁資料 | 預覽頁裡只有作者自己的內容，沒有 SYNOX 的資料可偷；外送管道也被 CSP 關掉 | 推測 |
| **在預覽裡畫假的「SYNOX 已驗證 ✅」或假的確認鈕騙人** | **瀏覽器擋不了** | 已查證（威脅存在 [WB12]）；對策是推測 |

**一個實作上的後果**（推測）：預覽頁裡如果引用同包的 `style.css`、`cover.png`，這些子請求**帶不到 session cookie**，而 SYNOX 的路由都要登入（`server.py:322-324`、`329-330`）→ 會 401。所以預覽要嘛是**單一自足的 HTML**（CSS 內嵌、圖用 `data:`，跟教學頁一樣），要嘛子資源走「token 就是鑰匙」的網址。前者簡單得多。

### 8.5 研究階段的設計建議（推測；定案在 ADR 0022 §7）

- **manifest**（選填）：`preview.entry`（一個 `.html`）、`preview.cover`（一張圖）、`preview.title`、`preview.summary`；路徑規則照 `web.panel` 現成的那套（`src/synox/packs/manifest.py:369-377`、`152-184`）；`title`／`summary` **只給人看、不進 AI 的提示**。
- **路由**：暫存的 `GET /api/pack-staged/<token>/preview`、`…/cover`；已安裝的 `GET /packs/<name>/preview`、`…/cover`。只讀檔、不寫、不執行。
- **預覽頁的回應標頭**：`Content-Security-Policy: sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'`，加上現成的 `nosniff`、`no-referrer`、`no-store`。
- **封面**：`Content-Type` 由伺服器照檔頭判定後從白名單給，不信副檔名；`Content-Security-Policy: default-src 'none'; sandbox`；**不收 SVG**。主頁 CSP 的 `img-src 'self'` 已經允許 `<img>` 載它。
- **頁面**：`<iframe sandbox="" src="…/preview" loading="lazy" referrerpolicy="no-referrer">`；外框由 SYNOX 自己畫一條「以下是作者提供的內容，SYNOX 沒有驗證」；**確認安裝的按鈕不跟預覽同時出現**。
- **安裝時的檢查**（新的，只是提醒＋擋明顯的）：大小上限（建議 entry ≤ 256 KB、cover ≤ 512 KB，無外部來源，請擁有者定）；HTML 用**白名單**解析，出現 `<script>`、`on*=`、`<iframe>`、`<object>`、`<embed>`、`<form>`、`<base>`、`<meta http-equiv>`、`<link>`、外部網址的 `src`／`href`／CSS `url()`／`@import` → 拒裝並列行號。
- **作者端 `preview` 指令**：不要直接用瀏覽器開 `file://`（CSP 的 `sandbox` 指令 `<meta>` 不支援 [WB3]，本機檔看到的行為會跟裝的人看到的不一樣）；起一個只綁 127.0.0.1 的臨時伺服器、送同一組標頭、包在同一個 `sandbox=""` 的 iframe 裡。

### 8.6 要不要一開始就開放 JS：研究的建議是不要

1. **跟 SYNOX 自己的承諾衝突**：預覽在按確認**之前**就顯示。對使用者的說法是「沒按確認，什麼都不會進 `packs/`」（`docs/install-packs.md:4`）；維護者開發機的家規也是「第三方的…一律不在這台電腦上跑」（`docs/security.md:314`；這一句是家規，不是對使用者的承諾）。在擁有者的瀏覽器裡跑作者的 JS，就算有沙盒，也是「同意之前先執行第三方程式」。
2. **業界沒有人在安裝前跑作者的 JS**（§8.2）；會跑的都要求不同源，而 SYNOX 在 127.0.0.1 上拿不到真正獨立的來源。
3. **開了 JS 之後，邊界只剩 CSP 一層**：`allow-scripts` 的 opaque-origin 頁仍然可以發網路請求（要靠 `connect-src 'none'` 等一條一條關）、可以把 iframe 自己導到任意網址、可以吃 CPU、可以用時間差探測本機的埠（最後兩項是推測）。
4. **騙人的畫面會從靜態變成動態**（假進度條、假掃描結果），更難用版面壓住（推測）。
5. **需求面**：要「會動」，CSS 動畫與轉場在沒有 JS 的條件下照常能用（待實測各瀏覽器），教學頁已經是這個模式。

---

## 六、SDK 現況（假設 I 的事實基礎）

| 提案的指令 | 現在有沒有 | 依據 |
|---|---|---|
| `synox new` | 沒有這個名字；對應的是 `synox-sdk init <資料夾> --kind cli\|python --name x`（範本）與 `synox-sdk init --from tool.py --name x`（從 `@tool` 函式產生 pack.json＋SKILL.md） | `src/synox/sdk/__init__.py:672-677`；`docs/sdk.md:259`。規劃階段複查 |
| `synox pack test` | 對應 `synox-sdk run <指令>`（本機試跑，照 loader 的代換與第 4 關）＋`synox-sdk check <資料夾>`（第 1、2 關、印 T0／T1／T2，一定裝不了＝結束碼 2） | `sdk/__init__.py:678-686`。規劃階段複查 |
| `synox pack build` | 對應 `synox-sdk zip <資料夾>`（先跑 check、算每個檔的雜湊、出 `dist/<name>-<version>.synoxpack`） | `sdk/__init__.py:687-689`。規劃階段複查 |
| `synox pack preview` | **沒有** | `src/` 裡沒有任何套件預覽的程式 |
| 一頁式入門 | 沒有獨立的一頁。最接近的是 `docs/tools.md:69`「十行入門」與 `docs/sdk.md` 開頭；兩份文件分別 421、346 行 | 規劃階段複查 |
| 範本 repo | **查不到**（repo 裡只有 `examples/` 五個範例：hello、any-language-cli、node-mcp-tool、mcp-remote-notion、mcp-remote-todoist） | 規劃階段複查 |

實際的缺口（已查證）：

1. **`synox-sdk` 指令只有裝了整個 SYNOX 才有**：進入點寫在主套件的 `pyproject.toml:21-23`；單獨的 `sdk/pyproject.toml` 只有 `py-modules = ["synox_sdk"]`、沒有 scripts。`docs/sdk.md:346` 自己寫「要 `pip install -e .` 才會出現」。規劃階段複查
2. `synox-sdk run` **只跑 kind=cli**（`docs/tools.md:324`）；MCP 要手動餵 JSON-RPC、kind=python 沒有本機試跑（`docs/tools.md:61`）。規劃階段複查
3. 命名：`synox init` 已經是「文字版安裝引導」（`src/synox/__main__.py:786`）、`synox packs` 已經是鎖／退回／環境（`__main__.py:827`）。新加單數的 `synox pack …` 會跟複數的 `synox packs …` 只差一個字（推測：容易打錯）。
4. `init_pack` 產生的範本會帶一份 `panel.html`（`sdk/__init__.py:316`、`336`）——等於預設教新作者做「同源、能跑 JS」的面板。規劃階段複查

同類的最短路徑（已查證）：MCPB 是 `mcpb init`（互動問答產生 manifest）→ `mcpb pack`，另有 `validate`／`sign`／`verify`／`info` [WB13]；Agent Skills 規格附 `skills-ref validate ./my-skill` [M1]。「第一次做工具要幾分鐘」**沒有任何量測**——現況是不是 5 分鐘＝待實測。

---

## 七、要擁有者決定的事

三份報告的待決事項去重後共 34 題，規劃階段對程式時多出 1 題（決定 35），一共 35 題。編號在三份文件（這份、[ADR 0022](../adr/0022-ecosystem-bridge-and-sandbox.md)、[實作計畫](2026-11-13-ecosystem-implementation-plan.md)）裡一致。「建議」是規劃階段的建議；擁有者的固定想法（能裝 npm 工具接上兩個生態、之後收技能市集、把 SDK 做好、容易安裝、安全的隔離）不在可選範圍內，下面只對它們提風險。

### 甲、生態與匯入

| # | 要決定什麼 | 選項 | 建議 | 各選項的後果 |
|---|---|---|---|---|
| 1 | 「Hermes」是不是 Nous Research 的 Hermes Agent | 是／不是 | **是**（主題 2 §2.1，四項特徵全對上） | 是→照這份的主題 2。不是→主題 2 要重查；匯入器的技能部分不受影響（Agent Skills 是共同格式） |
| 2 | 做一個 core，還是只做匯入器＋MCP | 甲：只做匯入器＋MCP／乙：再做 core（讓上游原生 plugin 原封不動能跑） | **甲** | 甲→上游的原生 plugin 用不了（真的要用就跑真的上游程式、用 MCP 跟它講話，待實測）；維護量不隨上游數量增加。乙→要追 352 個子路徑、官方自稱 experimental 的介面；Node ≥ 24.16＋275 MB 相依；所有東西變 T2；繼承上游的安全更新節奏 |
| 3 | 有程式的技能，匯入器在哪裡跑 | (a) 只在作者／工具庫維護者那一端（離線，產出草稿，人補完再打包）／(b) 使用者安裝時自動轉 | **(a)**。使用者端只開放兩種不用「猜」的匯入：純文字技能（決定 4）與 MCP 伺服器（決定 6） | (a)→上游技能要有人整理過才進得來，數量成長慢。(b)→機器猜危險程度，猜錯等於拿掉確認卡；核心多一個吃不可信 YAML 與壓縮檔的解析器（Hermes 的掃描器出過 CVE） |
| 4 | 要不要加「純文字技能」這個種類 | 加／不加 | **加**；不標「低風險」；報告顯示 AI 會讀到的全文、仍要按確認；不准帶程式檔 | 不加→三家的純說明技能沒地方放。加→AI 的系統提示多一類第三方文字，要跟決定 19、20 一起做 |
| 5 | `kind=mcp` 要不要支援鎖檔安裝（取代 `npx`） | 開／不開 | **開** | 不開→npm 上的 MCP 伺服器只能每次從網路抓、沒鎖，「更新後才變壞」擋不到。開→第 1 關、環境建置、MCP 啟動三處要改 |
| 6 | 使用者端「輸入套件名就裝」開不開；鎖檔誰產生 | (a) 只收工具庫維護者產好鎖檔的／(b) 也讓使用者輸入套件名、現場產生／(c) 兩個都做，(b) 放「進階」 | **(c)**：同一條管線，先給作者與工具庫用；使用者入口放安裝頁的「進階」，一律當 T2（要打出套件名確認），報告明講「這個工具的程式來自網路上的公開套件庫，SYNOX 看不到內容」 | 只 (a)→最安全，但接上兩個生態要等維護者一個一個收。有 (b)→等於把「信不信這個套件」交給非工程師；沒有執行期隔離的電腦上，風險就是 T2 本身（**這是擁有者的固定想法，這裡只提風險**） |
| 7 | 需要安裝腳本的 npm 套件怎麼辦 | a 講清楚、明確不支援／b 逐套件白名單、擁有者確認後才跑／c 只收作者預先打包的 | **a 立刻做；c 當替代路；b 等執行期隔離做好再開** | 只 a→原生資料庫、要下載瀏覽器的工具用不了，但失敗會說原因。開 b→在使用者電腦上執行第三方的安裝腳本，還需要編譯器 |
| 8 | Node 由誰提供 | a 系統的（現況）／b SYNOX 自己管一份可攜版／c 系統有且版本夠就用，否則下載／d 容器 | **b**（第一次需要時才下載、驗官方雜湊；不放進安裝程式） | a→非工程師要自己裝 Node，是最大的安裝門檻；版本不受控。b→多一次約 38 MB 的下載；SYNOX 要跟 Node 的安全更新；隔離要讀得到那個位置。c→兩條路都要測、行為不一致。d→要 Docker Desktop |
| 9 | 名字 | 用 `openclaw-core`／`hermes-core`／用中性名字 | **中性名字**：功能叫「匯入」（指令 `synox-sdk import`；畫面上寫「從其他助理的技能匯入」） | 用上游名字→兩個名字在 npm 已被佔；名字裡放別人的專案名容易被當成官方或被要求改名 |
| 10 | 轉出來的 pack 掛誰的名字；沒有授權聲明的上游技能收不收 | — | `publisher` 寫轉換的人；另外記「原作者、來源網址、上游授權、上游版本或 commit」；**工具庫不收沒有授權聲明的**；使用者自己匯入自用的，標紅字但可以裝 | 收沒授權的→再散布有侵權風險。publisher 寫原作者→看起來像原作者背書了這份轉換 |

### 乙、隔離

| # | 要決定什麼 | 選項 | 建議 | 各選項的後果 |
|---|---|---|---|---|
| 11 | Windows 10 的支援等級 | 一級（完整隔離都要有）／基本（只保證檔案隔離＋「全斷網或全開網」，畫面明講）／新功能不支援 | **基本** | 一級→只剩「專用帳號＋防火牆」一條路，一定要一次 UAC。基本→Windows 10 上宣告連網的工具拿不到網域白名單。不支援→擁有者自己的開發機（Windows 10 Home）用不了新功能。背景：Windows 10 已於 2025-10-14 終止支援 |
| 12 | 接不接受「第一次要按一次 UAC」 | 預設要求／不接受／做成選配的「加強保護」 | **預設不要求；之後做成選配** | 預設要求→多一個非工程師會卡住的畫面，但每台 Windows 都拿得到網域白名單。不接受→Windows 10 永遠沒有網域白名單 |
| 13 | Windows 的主路線 | A：MXC 為主，舊系統退回 AppContainer 自製／B：專用帳號＋防火牆一條走到底／C：只做 AppContainer／D：維持現況，只推 Docker Desktop | **A**，但要等決定 14 的實測 | A→跟 VS Code 同一條路、不用裝、不用 UAC；Home 版查不到、沒有 Python SDK。B→一條路全包，但一定要 UAC、文件自己寫了繞過缺口。C→工程量高、沒有網域白名單。D→不符合「容易安裝」 |
| 14 | 要不要先花一輪做 Windows 實測再定決定 13 | 先測／直接選 | **先測**（兩個腳本約半小時） | 直接選→Windows 的每一條都是文件上的說法，選錯要重做 |
| 15 | 宣告了「要連網」但沒列網域 | 視為全開並標紅／拒裝 | **新裝的拒裝；已經裝的照跑、標紅，給一個版本的相容期** | 拒裝→現有宣告 `network` 的工具都要補網域才能重新打包。全開→網域白名單形同選配 |
| 16 | 執行期環境變數要不要改成白名單（不再繼承整份） | 改／不改 | **改**，先警告一個版本 | 改→依賴 `PATH` 以外變數的現有工具可能壞。不改→技能讀得到擁有者啟動 SYNOX 時的所有環境變數（名字不像密鑰的） |
| 17 | 隔離做好之後，這台電腦用不了隔離時，第三方 T2 工具怎麼辦 | 照跑＋紅字／預設不執行，擁有者可在「進階」逐個放行／一律不執行 | **預設不執行，可逐個放行**；畫面說下一步 | 照跑→隔離形同選配。一律不執行→舊電腦上第三方工具全部不能用 |
| 35 | 第三方的 `kind=python` 工具，市集收不收（規劃階段新增：它在 SYNOX 自己的程序裡跑，任何隔離後端都包不到，`src/synox/packs/tier.py:20-21`） | (a) 市集只收官方的 `kind=python`，第三方只收 cli、mcp、純文字技能／(b) 照收，報告紅字／(c) 把 `kind=python` 改成在子程序裡跑 | **(a)**；(c) 是另一個大工程，這一輪不做 | (a)→第三方作者要把 Python 工具寫成 `kind=cli`（SDK 的 `@tool` 產生的就是 cli）。(b)→第三方的 Python 程式拿得到 SYNOX 程序裡的一切，「用隔離保護使用者」對它不成立。(c)→現有的 python 工具都要改、要重測 |

### 丙、確認與提示注入

| # | 要決定什麼 | 選項 | 建議 | 各選項的後果 |
|---|---|---|---|---|
| 18 | `WRITE` 與「會把資料送出去」的動作要不要出確認卡 | (a) 全部出／(b) 只對第三方工具的 `WRITE`／(c) 這一輪讀過不可信內容之後的寫入與外傳才出／(d) 維持現狀 | **(b)＋(c)** | (a)→卡太多，人會亂按。(d)→私有資料＋不可信文字＋能往外送的工具同時存在時，沒有結構性的擋 |
| 19 | pack 給的字進系統提示的規則 | (a) 限長度、擋換行與控制字元／(b) 套 `scenario` 那組樣式檢查／(c) 搬進有分隔符的區塊 | **(a) 立刻做（新裝的擋、已裝的截斷）；(b) 只當提醒不擋；(c) 做，但先用現有評測量本地小模型選工具的準度** | (b) 當門→會誤擋（工具本來就要「寄到」）。(c) 不量就做→可能影響小模型選工具 |
| 20 | 安裝報告要不要顯示 AI 會讀到的全部文字（SKILL.md、指令說明、MCP 工具說明） | 顯示／不顯示 | **顯示**（收合的區塊，標題「AI 會讀到的內容」） | 不顯示→AI 會讀的字，人沒有機會審 |
| 21 | MCP 工具定義要不要釘雜湊 | 做／不做 | **做**：第一次連線記下，之後變了就停用那個工具並請擁有者重新核准 | 不做→遠端工具可以在核准之後無聲換說明 |
| 22 | 要不要用另一個 AI 掃技能文字 | 做／不做 | **這一輪不做** | 做→多 token 成本、把 pack 內容送去 AI 來源（跟本機優先有張力）、掃描器本身也會被注入 |
| 23 | `web.panel`（工具自帶的面板）的定位 | (a) 有面板就算 T2／(b) 改成不同來源的沙盒／(c) SDK 範本不再預設產生面板 | **(c) 立刻；(a) 對新安裝生效，報告明講；(b) 之後** | 不動→面板的 JS 能做擁有者在網頁上能做的任何事，而且不被掃、不影響層級；做預覽時會被拿來比 |

### 丁、市集

| # | 要決定什麼 | 選項 | 建議 | 各選項的後果 |
|---|---|---|---|---|
| 24 | 市集的形態 | 策展式（開 PR、有人看、寫進簽過的目錄）／開放上傳 | **策展式** | 開放上傳→ClawHub 的經驗是抽查約 12% 惡意（待查）；`docs/security.md` 對「收陌生人的 pack」寫的是「現在不要這樣用」 |
| 25 | 要不要允許 SYNOX 自己連網抓工具目錄、下載工具 | 不連（維持現況：使用者自己用瀏覽器下載整個資料夾）／只在使用者按下按鈕時連寫死的官方來源／可以加自訂來源 | **只在按下按鈕時連官方來源**；自訂來源放「進階」，一律最低信任 | 不連→「容易安裝」做不到。連→多一條出門的路（要驗簽、限主機、限大小），要比照 CVE-2026-25253 審「網址決定連去哪」 |
| 26 | 簽章金鑰：誰保管、怎麼輪換、第三方作者的公鑰怎麼進來 | — | ed25519（`cryptography` 已經是相依，不用加套件）；擁有者離線保管；SYNOX 內建兩把公鑰（現用＋備用）以便輪換；第三方作者的公鑰這一輪不收（第三方走 PR 進官方目錄） | 不簽→sha256 只擋「下載壞了、被換過」，擋不了一開始就是假的目錄 |
| 27 | 撤銷清單要不要連網抓 | 定時自動抓／跟目錄一起發，使用者按「檢查更新」時才更新／不做 | **跟目錄一起發** | 自動抓→背景連網，跟「沒有隱藏的背景程式」的精神有張力。不做→下架的工具已經裝的人不會知道 |
| 28 | 新發行者的「低信任」限制到哪 | 只能上架沒有程式在你電腦上跑的／有程式也行但一定要在隔離裡跑／不限制 | **新發行者只能上架「沒有程式在你電腦上跑」的**（遠端工具、純文字技能）；有程式的要「看過程式」等級 | 不限制→新帳號上架帶程式的工具，是 ClawHavoc 的形狀 |

### 戊、預覽

| # | 要決定什麼 | 選項 | 建議 | 各選項的後果 |
|---|---|---|---|---|
| 29 | 預覽能不能跑 JS | 不行／可以／第一版不行，之後只在「裝好之後、另外同意」才行 | **第一版不行**；後路這一輪不做 | 可以→按確認之前就在擁有者的瀏覽器裡跑作者的程式；邊界只剩 CSP 一層；業界沒有先例 |
| 30 | 預覽裡的外部連結 | 一律不准／准，點了由 SYNOX 攔下來問 | **一律不准**（檢查器擋） | 准→「iframe 內導頁會不會被擋」待實測；多一個釣魚出口 |
| 31 | 封面格式與上限 | — | PNG／JPEG／WebP；不收 SVG；動圖先不收；預覽頁 ≤ 256 KB、封面 ≤ 512 KB | 收 SVG→被直接開時不受圖片情境的限制 |
| 32 | T2 工具的預覽何時顯示 | 打發行者名字之前／之後 | **之前就可以看**，但外框警語固定、確認鈕不在同一個畫面 | 之後才顯示→預覽失去「先看看再決定」的用途 |

### 己、SDK 與流程

| # | 要決定什麼 | 選項 | 建議 | 各選項的後果 |
|---|---|---|---|---|
| 33 | SDK 指令的名字；獨立的 SDK 套件要不要帶指令 | 另做一套 `synox new`／`synox pack …`／只留 `synox-sdk`、加別名 | **只留 `synox-sdk`**，加 `new`／`test`／`build`／`preview` 四個別名；不加 `synox pack …`；獨立套件也帶指令 | 另做一套→`synox pack` 與現有的 `synox packs` 只差一個字。獨立套件帶指令→它的檢查只能做格式檢查（核心的掃描是 AGPL，不能搬進 Apache 的 SDK），完整檢查要裝 SYNOX |
| 34 | 研究找到的小修要不要先做（跟上面的決定無關） | 先做／等大功能一起 | **先做**（清單在實作計畫「可以單獨核准的小修」） | 等→已實測的洞（鎖檔沒有 `integrity` 照樣過）繼續開著 |

---

## 八、沒能查證的清單

### 被擋的網站（只有搜尋摘要，一律「待查」）

| 項目 | 狀況 |
|---|---|
| ClawHavoc、Unit 42、Snyk、Cisco、Censys、Trail of Bits、Invariant Labs 的原始報告與確切數字 | 網站開不到 |
| OpenClaw 官方對 ClawHavoc 的聲明、VirusTotal 合作公告；ClawHub 檢舉門檻的數字 | `openclaw.ai` 開不到；官方 repo 的文件沒寫數字 |
| CVE-2026-25253 的 NVD 頁 | 改用 GitHub Advisory（已查證） |
| FSF 授權相容清單的原文 | `gnu.org` 開不到 |
| arXiv 論文：2403.14720、2503.18813、2506.08837、2510.09023、2601.10338、2605.11418、2604.06550 | `arxiv.org` 開不到 |
| Simon Willison 的 dual LLM／lethal trifecta、Meta 的 Rule of Two、OpenAI 的「Safety in building agents」與 Atlas 強化文、OWASP Top 10 for Agentic Applications 2026、Google「Securely hosting user data」 | 只有搜尋摘要 |
| Windows Sandbox 的版本與 `.wsb` 設定、Windows 10 生命週期、AppContainer loopback 豁免、OpenAI 的 Codex Windows 沙盒文章、GitHub 的 npm 安全計畫、CERT/CC 的 Shai-Hulud 通報、Socket 的 typosquat 規則、「2.2% 套件有安裝腳本」的原始論文 | 只有搜尋摘要 |
| Anthropic 瀏覽器代理的數字（約 1.4%） | 經摘要工具讀到，建議再對原頁 |

### 查不到

| 項目 | 狀況 |
|---|---|
| ClawHub 上 plugin／package 的授權；OpenClaw、Hermes 的官方商標規範；npm 的名稱爭議政策 | 文件沒寫／開不到 |
| OpenClaw advisory 的確切總數；Hermes 首次發佈的確切日期；Hermes 匯入 OpenClaw 技能時會不會掃描 | 頁面沒寫／來源差一天／文件沒寫 |
| MXC：Home 版支援、`wxc-exec.exe` 的取得與散布方式 | 官方 README 與版本支援頁都沒寫（規劃階段再查一次，仍然沒有） |
| 專用帳號＋WFP 的最低 Windows 版本、Home 版 | 文件沒寫 |
| 熱門 npm 套件裡有安裝腳本的比例 | 沒有專門的量測 |
| MCP 規格獨立的「Security Best Practices」頁 | GitHub 路徑 404、正式站連不到 |
| 「iframe 內由內容發起的導頁，套的是父頁還是子頁的 `frame-src`」的明確規格句子 | 沒找到 |
| SYNOX 的範本 repo；任何「做第一個 SYNOX 工具要幾分鐘」的量測 | 沒有 |

### 待實測

| 項目 | 怎麼測 |
|---|---|
| **Windows 上的所有行為**：AppContainer 的 ACL、斷網、loopback、Python／Node 啟動、不用管理員建 profile | [tools/windows-sandbox-probe/](tools/windows-sandbox-probe/)（腳本沒在 Windows 跑過） |
| MXC：Home 版、長駐 stdio、跟 Python 的整合 | 還沒有腳本 |
| 專用帳號＋WFP | 會動全機設定，要擁有者先同意 |
| Linux：一般使用者的 user namespace（Ubuntu 24.04 的 AppArmor 限制）；bwrap／systemd／容器後端真機 | 伺服器驗證（`docs/security.md:321-322`） |
| `npm audit signatures` 的成功路徑 | 研究機器連不到 Sigstore 的 TUF 來源 |
| 使用者的 `~/.npmrc` 對 `npm ci` 的其他影響（例如關掉 TLS 驗證的設定） | 建置環境保留了 `HOME`／`USERPROFILE`（`src/synox/packs/envs.py:56-59`） |
| 上游技能裡腳本的語言分布（決定有多少會是 T2） | 從 ClawHub 與 Hermes 官方技能各抽 30 個分類 |
| 常見 MCP 伺服器經 `kind=mcp` 實際能用到什麼程度（SYNOX 對伺服器反問一律回 -32601：`src/synox/packs/mcp.py:10`） | 挑 3 個（一個遠端、兩個 stdio）裝起來 |
| OpenClaw 的 `openclaw-plugin-tools` 橋、Hermes 的 `mcp-serve` 能不能給外部 MCP 用戶端單獨使用 | 實測 |
| 從對話頁拖 `.synoxpack` 進來，是不是停在錯的分頁 | 真的瀏覽器（程式邏輯已讀過，第四節第 22 列） |
| `<iframe sandbox="">` 載同源路由時，第一次導頁會不會帶 session cookie；沙盒頁的子請求在 Firefox／Safari 帶不帶 Lax cookie；預覽裡點外部連結會不會被擋；`srcdoc`／`blob:` 在 nonce CSP 下的行為；沒有 JS 時 CSS 動畫能不能用 | 真的瀏覽器 |
| 多行的 `summary`、長的 frontmatter `description` 能不能真的帶偏模型；把 pack 的字搬進分隔符之後選工具的準度有沒有掉 | 真的模型（尤其本地小模型） |

### 待查（這次沒查）

Docker Desktop 的安裝檔大小、免費版有沒有容器層級的網域白名單；systemd 的網域級過濾；Gemini CLI、Cursor 在 Windows 的沙盒；Windows Sandbox 的 `wsb` 命令列官方文件、啟用要不要管理員。

---

## 九、規劃階段自己補查的

1. **程式事實**：第四節每一列標「規劃階段複查」的，都在 commit `30f32a4` 上重新開檔對過。跟三份報告不同的地方：
   - 報告 C 引的 `docs/tools.md:420`（`run` 只跑 kind=cli）實際在 `docs/tools.md:324`；
   - 報告 C 列的 `index.json` 欄位少了 kind、group、access、capabilities、bundles（SYNOX_Libs `scripts/build.py:105-111`）；
   - 報告 B 說「擁有者的開發機是 Windows 10 Home」引的是 isolation-howto，實際寫在 `docs/lab/discussions/2026-11-10-sandbox-and-skill-containers.md:73`；
   - 報告 A 標「待查」的兩件事有答案了：MCP 工具說明事後改變**不會**提醒（`src/synox/packs/mcp.py:978-988`）；pack **沒有**獨立的生命週期稽核紀錄（第四節第 16 列）。
2. **報告之間的衝突**：MCPB 的 repo，報告 B 寫 `anthropics/mcpb`、報告 C 寫 `modelcontextprotocol/mcpb`。查了：前者 301 轉到後者，是同一個 repo 搬了家。README 寫「Bundle the entire `node_modules` directory with your bundle」「Node.js ships with Claude for macOS and Windows」。**已查證** [WB14]
3. **MXC 能不能在 Home 版用、`wxc-exec.exe` 去哪裡拿**：再讀一次官方的版本支援頁與 README。版本支援頁只列 build（24H2 `26100.9278`、25H2 `26200.9278`、26H2 `26300.9550`、26H1 `28000.2804`），**完全沒提版別與 Windows 10**；README 只說「Install an SDK through your package manager」（Rust／.NET／Node），獨立執行檔沒有寫下載來源；有一個 streaming standard-I/O 的範例。結論不變：**查不到**，要實測。[MX1][MX2]
4. **Node 能不能再散布**：Node.js 的 LICENSE 開頭是 MIT 條款（授予 use、copy、modify、merge、publish、distribute、sublicense），後面列了內含的第三方元件各自的授權（Acorn、c-ares、libuv、llhttp、undici、OpenSSL、V8、ICU、zlib…）。所以 SYNOX 下載官方 zip 給使用者用沒有授權問題；如果之後要把 Node **放進安裝程式一起發**，要附上那份 LICENSE。**已查證** [ND4]（檔案很長，只讀了前 10 萬字）

---

## 十、來源清單（全部於 2026-11-13 查閱）

SYNOX 自己的檔案在文中直接寫 `路徑:行號`（相對於 repo 根目錄，commit `30f32a4`）。

| 代號 | 檔案 |
|---|---|
| SX1 | `docs/ui/redesign-notes.md`（「三個參考對象各取什麼」表） |
| SX2 | `docs/pack-format.md`（kind、信任層級、`runtime.node` 只給 cli、`mcp` 兩節、`SKILL.md`） |

### OpenClaw（一手）

| 代號 | 網址 |
|---|---|
| O1 | https://raw.githubusercontent.com/openclaw/openclaw/main/LICENSE |
| O2 | https://raw.githubusercontent.com/openclaw/openclaw/main/SECURITY.md |
| O3 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/tools/skills.md |
| O4 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/tools/plugin.md |
| O5 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/sandboxing.md |
| O6 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/security/index.md |
| O7 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/cli/mcp.md |
| O8 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/tools/exec-approvals.md |
| O9 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/plugins/manifest.md |
| O10 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/plugins/bundles.md |
| O11 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/plugins/sdk-overview.md |
| O12 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/cli/skills.md |
| O13 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/tools/acp-agents-setup.md |
| O14 | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/security/THREAT-MODEL-ATLAS.md |
| O15 | https://github.com/openclaw/openclaw |
| O16 | https://github.com/openclaw/openclaw/security/advisories |
| O17 | https://github.com/advisories/GHSA-g8p2-7wf7-98mq |
| O19 | https://raw.githubusercontent.com/openclaw/openclaw/main/TRADEMARK.md （回 404） |
| C1 | https://raw.githubusercontent.com/openclaw/clawhub/main/README.md |
| C2 | https://raw.githubusercontent.com/openclaw/clawhub/main/docs/skill-format.md |
| C3 | https://raw.githubusercontent.com/openclaw/clawhub/main/docs/security.md |
| C4 | https://raw.githubusercontent.com/openclaw/clawhub/main/docs/moderation.md |
| C5 | https://raw.githubusercontent.com/openclaw/clawhub/main/docs/security-audits.md |
| C6 | https://raw.githubusercontent.com/openclaw/clawhub/main/docs/clawhub.md |

### Hermes（一手）

| 代號 | 網址 |
|---|---|
| H1 | https://raw.githubusercontent.com/NousResearch/hermes-agent/main/LICENSE |
| H2 | https://raw.githubusercontent.com/NousResearch/hermes-agent/main/README.md |
| H3 | https://raw.githubusercontent.com/NousResearch/hermes-agent/main/SECURITY.md |
| H4 | https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/features/skills.md |
| H5 | https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/security.md |
| H6 | https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/features/plugins.md |
| H7 | https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/features/mcp.md |
| H8 | https://raw.githubusercontent.com/NousResearch/hermes-agent/main/tools/skills_guard.py |
| H9 | https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/user-guide/features/web-dashboard.md |
| H10 | https://raw.githubusercontent.com/NousResearch/hermes-agent/main/website/docs/guides/migrate-from-openclaw.md |
| H11 | https://github.com/NousResearch/hermes-agent |
| H12 | https://github.com/NousResearch/hermes-agent/security/advisories |
| H13 | https://github.com/advisories/GHSA-238w-f66p-w349 |

### 市集、協定、授權（一手）

| 代號 | 網址 |
|---|---|
| M1 | https://raw.githubusercontent.com/agentskills/agentskills/main/docs/specification.mdx |
| M2 | https://github.com/agentskills/agentskills |
| M3 | https://raw.githubusercontent.com/anthropics/skills/main/README.md ；https://raw.githubusercontent.com/anthropics/skills/main/skills/pdf/LICENSE.txt |
| M4 | https://code.claude.com/docs/en/plugins/security.md |
| M5 | https://raw.githubusercontent.com/modelcontextprotocol/registry/main/README.md |
| M6 | https://raw.githubusercontent.com/modelcontextprotocol/registry/main/docs/modelcontextprotocol-io/moderation-policy.mdx |
| M7 | https://raw.githubusercontent.com/modelcontextprotocol/registry/main/docs/modelcontextprotocol-io/faq.mdx |
| M8 | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2025-06-18/server/tools.mdx |
| M9 | https://raw.githubusercontent.com/microsoft/vscode-docs/main/docs/configure/extensions/extension-runtime-security.md |
| M10 | https://raw.githubusercontent.com/npm/documentation/main/content/packages-and-modules/securing-your-code/generating-provenance-statements.mdx |
| M11 | https://raw.githubusercontent.com/NVIDIA/OpenShell/main/README.md |
| L1 | https://raw.githubusercontent.com/spdx/license-list-data/main/text/MIT-0.txt |

### 套件 registry（一手，直接查 API）

| 代號 | 網址 | 查到什麼 |
|---|---|---|
| N1 | https://registry.npmjs.org/openclaw-core | 第三方，1.0.1，2026-04-05 建立 |
| N2 | https://registry.npmjs.org/hermes-core | 維護者是 npm 官方帳號 |
| N3 | https://registry.npmjs.org/openclaw | 2026.11.3、engines、352 個 exports、275 MB |
| N4 | https://registry.npmjs.org/clawhub | 0.26.0，MIT |
| N5 | https://pypi.org/pypi/hermes-core/json | Cossack Labs |
| N6 | https://pypi.org/pypi/hermes-agent/json | 0.19.0，Nous Research |
| N7 | https://pypi.org/pypi/openclaw/json | 第三方 |
| N8 | https://registry.npmjs.org/hermes-agent | Unofficial npm bridge |
| N9 | https://pypi.org/pypi/openclaw-core/json | 404 |

### Windows、容器、其他專案的沙盒

| 代號 | 網址 | 怎麼讀到的 |
|---|---|---|
| MS1 | https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation | 原始檔 https://raw.githubusercontent.com/MicrosoftDocs/win32/docs/desktop-src/SecAuthZ/appcontainer-isolation.md |
| MS2 | https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer | 原始檔 https://raw.githubusercontent.com/MicrosoftDocs/win32/docs/desktop-src/SecAuthZ/implementing-an-appcontainer.md |
| MS3 | https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-for-legacy-applications- | 同一個 repo 的原始檔 |
| MS4 | https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/ | 只有搜尋摘要 |
| MS5 | https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file | 只有搜尋摘要 |
| MS6 | https://learn.microsoft.com/en-us/lifecycle/products/windows-10-home-and-pro | 只有搜尋摘要 |
| MS7 | https://learn.microsoft.com/en-us/previous-versions/windows/apps/hh780593(v=win.10) | 只有搜尋摘要 |
| MX1 | https://github.com/microsoft/mxc | README（規劃階段再讀一次） |
| MX2 | https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/os-version-support.md | 原始檔（規劃階段再讀一次） |
| MX3 | https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/networking.md | 原始檔 |
| MX4 | https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/filesystem.md | 原始檔 |
| MX5 | https://registry.npmjs.org/@microsoft%2fmxc-sdk | registry API |
| MX6 | https://windowsreport.com/microsoft-execution-containers-mxc-is-now-generally-available-on-windows-11/ | 二手，搜尋摘要 |
| D1 | https://docs.docker.com/desktop/setup/install/windows-install/ | 原始檔 https://raw.githubusercontent.com/docker/docs/main/content/manuals/desktop/setup/install/windows-install.md |
| D2 | https://docs.docker.com/desktop/setup/install/windows-permission-requirements/ | 同 repo 原始檔 |
| D3 | https://docs.docker.com/engine/network/drivers/none/ | 同 repo 原始檔 |
| CR1 | https://chromium.googlesource.com/chromium/src/+/main/docs/design/sandbox.md | GitHub 鏡像 https://raw.githubusercontent.com/chromium/chromium/main/docs/design/sandbox.md |
| AN1 | https://code.claude.com/docs/en/sandboxing | 原頁 |
| AN2 | https://github.com/anthropic-experimental/sandbox-runtime | README（0.0.83，Apache-2.0） |
| OA1 | https://github.com/openai/codex/blob/main/codex-rs/core/README.md | 原始檔 |
| OA2 | https://github.com/openai/codex/blob/main/codex-rs/windows-sandbox-rs/Cargo.toml | 原始檔 |
| OA3 | https://openai.com/index/building-codex-windows-sandbox/ | 只有搜尋摘要 |
| OA4 | https://developers.openai.com/codex/windows | 只有搜尋摘要；部分細節來自第三方轉述 |
| VS1 | https://code.visualstudio.com/docs/agents/run/agent-sandboxing | 原始檔 https://raw.githubusercontent.com/microsoft/vscode-docs/main/docs/agents/run/agent-sandboxing.md |
| UB1 | https://discourse.ubuntu.com/t/understanding-apparmor-user-namespace-restriction/58007 | 只有搜尋摘要 |
| OL1 | https://github.com/ollama/ollama/blob/main/docs/faq.mdx | 原始檔 |
| OL2 | https://github.com/ollama/ollama/blob/main/docs/api/authentication.mdx | 原始檔 |

### npm 與供應鏈

| 代號 | 網址 | 怎麼讀到的 |
|---|---|---|
| NP2 | https://docs.npmjs.com/cli/configuring-npm/package-lock-json | 原始檔 https://raw.githubusercontent.com/npm/cli/latest/docs/lib/content/configuring-npm/package-lock-json.md |
| NP3 | https://docs.npmjs.com/cli/using-npm/scripts | 同 repo 原始檔 |
| NP4 | https://github.com/npm/cli/blob/latest/workspaces/config/lib/definitions/definitions.js | 原始檔（12.2.2） |
| NP5 | https://github.com/npm/cli/blob/latest/CHANGELOG.md | 原始檔 |
| NP6 | https://github.com/npm/cli/blob/latest/docs/lib/content/commands/npm-approve-scripts.md | 原始檔 |
| NP7 | https://docs.npmjs.com/cli/commands/npm-audit | 同 repo 原始檔 |
| NP8 | https://docs.npmjs.com/generating-provenance-statements | 原始檔（同 M10） |
| NP9 | https://docs.npmjs.com/about-registry-signatures | 同 repo 原始檔 |
| PN1 | https://pnpm.io/supply-chain-security | 原始檔 https://raw.githubusercontent.com/pnpm/pnpm.io/main/docs/supply-chain-security.md |
| BN1 | https://bun.sh/docs/pm/lifecycle ；https://github.com/oven-sh/bun/blob/main/src/install/default-trusted-dependencies.txt | 原始檔 |
| R1 | https://semgrep.dev/blog/2026/rip-npm-postinstall-scripts-npm-v12-default-change | 二手，搜尋摘要 |
| GH1 | https://github.blog/security/supply-chain-security/our-plan-for-a-more-secure-npm-supply-chain/ | 只有搜尋摘要 |
| GH2 | https://kb.cert.org/vuls/id/534320 | 只有搜尋摘要 |
| OS1 | https://github.com/ossf/package-analysis | README |
| OS2 | https://github.com/ossf/malicious-packages | README |
| SK1 | https://socket.dev/npm/issue/didYouMean | 只有搜尋摘要 |
| ND1 | https://nodejs.org/dist/index.json | 原頁 |
| ND2 | https://nodejs.org/dist/v24.22.3/SHASUMS256.txt | 原頁 |
| ND3 | https://github.com/nodejs/Release | 原頁 |
| ND4 | https://raw.githubusercontent.com/nodejs/node/main/LICENSE | 原始檔（規劃階段補查） |

### 提示注入（一手）

| 代號 | 網址 |
|---|---|
| PI1 | https://github.com/invariantlabs-ai/mcp-injection-experiments/blob/main/direct-poisoning.py |
| PI2 | https://github.com/invariantlabs-ai/mcp-injection-experiments/blob/main/README.md |
| PI3 | https://github.com/OWASP/www-project-agentic-skills-top-10/blob/main/ast01.md |
| PI4 | https://github.com/OWASP/www-project-agentic-skills-top-10/blob/main/README.md |
| PI5 | https://github.com/OWASP/www-project-agentic-skills-top-10/blob/main/ast08.md |
| PI6 | https://github.com/OWASP/CheatSheetSeries/blob/master/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.md |
| PI7 | https://github.com/OWASP/CheatSheetSeries/blob/master/cheatsheets/MCP_Security_Cheat_Sheet.md |
| PI8 | https://github.com/OWASP/www-project-top-10-for-large-language-model-applications/blob/main/2_0_vulns/LLM01_PromptInjection.md |
| PI9 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/server/tools.mdx |
| PI10 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/index.mdx |
| PI11 | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview |
| PI12 | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/enterprise |
| PI13 | https://code.claude.com/docs/en/security |
| PI14 | https://www.anthropic.com/research/prompt-injection-defenses |
| PI15 | https://github.com/openai/model_spec/blob/main/model_spec.md |
| PI16 | https://github.com/openai/openai-agents-python/blob/main/docs/guardrails.md |
| PI17 | https://github.com/google-research/camel-prompt-injection |

### 瀏覽器隔離與同類產品（一手）

| 代號 | 網址 |
|---|---|
| WB1 | https://github.com/whatwg/html/blob/main/source （正式頁 https://html.spec.whatwg.org/multipage/iframe-embed-object.html#attr-iframe-sandbox ） |
| WB2 | https://github.com/mdn/content/blob/main/files/en-us/web/html/reference/elements/iframe/index.md |
| WB3 | https://github.com/mdn/content/blob/main/files/en-us/web/http/reference/headers/content-security-policy/sandbox/index.md |
| WB4 | https://github.com/mdn/content/blob/main/files/en-us/web/http/reference/headers/content-security-policy/default-src/index.md ；https://github.com/mdn/content/blob/main/files/en-us/web/http/reference/headers/content-security-policy/frame-src/index.md |
| WB5 | https://github.com/w3c/webappsec-csp/blob/main/index.bs |
| WB6 | https://github.com/explainers-by-googlers/csp-sandbox-allow-same-site-none-cookies |
| WB7 | https://github.com/httpwg/http-extensions/blob/main/draft-ietf-httpbis-rfc6265bis.md |
| WB8 | https://github.com/mdn/content/blob/main/files/en-us/web/svg/guides/svg_as_an_image/index.md |
| WB9 | https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md |
| WB10 | https://github.com/microsoft/vscode-docs/blob/main/api/working-with-extensions/publishing-extension.md |
| WB11 | https://github.com/microsoft/vscode-docs/blob/main/api/extension-guides/webview.md |
| WB12 | https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/draft/apps.mdx |
| WB13 | https://github.com/modelcontextprotocol/mcpb/blob/main/CLI.md |
| WB14 | https://github.com/modelcontextprotocol/mcpb/blob/main/README.md （`https://github.com/anthropics/mcpb` 會 301 轉到這裡；規劃階段補查） |

### 二手來源（原文這次開不到，只有搜尋摘要；一律「待查」）

| 代號 | 網址 |
|---|---|
| X1 | https://thehackernews.com/2026/02/researchers-find-341-malicious-clawhub.html |
| X2 | https://www.koi.ai/blog/clawhavoc-341-malicious-clawedbot-skills-found-by-the-bot-they-were-targeting |
| X3 | https://unit42.paloaltonetworks.com/openclaw-ai-supply-chain-risk/ |
| X4 | https://cybersecuritynews.com/openclaw-skill-marketplace-exposes-ai-agents/ |
| X5 | https://www.antiy.net/p/clawhavoc-analysis-of-large-scale-poisoning-campaign-targeting-the-openclaw-skill-market-for-ai-agents/ |
| X6 | https://openclaw.ai/blog/virustotal-partnership ；https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html |
| X7 | https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/ |
| X8 | https://blogs.cisco.com/ai/personal-ai-agents-like-openclaw-are-a-security-nightmare |
| X9 | https://censys.com/?p=3946 ；https://hunt.io/blog/cve-2026-25253-openclaw-ai-agent-exposure ；https://blog.cyberdesserts.com/openclaw-exposure-numbers-explained/ |
| X10 | https://www.morphllm.com/clawdbot ；https://catalaize.substack.com/p/openclaw-from-viral-prototype-to |
| X11 | https://www.koi.ai/blog/postmark-mcp-npm-malicious-backdoor-email-theft ；https://thehackernews.com/2025/09/first-malicious-mcp-server-found.html ；https://www.theregister.com/2025/09/29/postmark_mcp_server_code_hijacked/ |
| X12 | https://cvefeed.io/vuln/detail/CVE-2025-6514 ；https://tianpan.co/blog/2026-04-10-mcp-server-supply-chain-risk |
| X13 | https://arxiv.org/pdf/2605.11418 ；https://arxiv.org/pdf/2604.06550 |
| X14 | https://snyk.io/blog/snyk-vercel-securing-agent-skill-ecosystem ；https://www.skills.sh/audits |
| X15 | https://www.gnu.org/licenses/license-list.html ；https://www.gnu.org/licenses/license-compatibility.html |
| X16 | https://www.producthunt.com/products/hermes-4/launches ；https://kanerika.com/blogs/hermes-agent/ |
| X17 | https://github.com/advisories/GHSA-pgp4-xr4j-h5cg ；https://github.com/advisories/ghsa-85cr-q769-68x2 ；https://www.sentinelone.com/vulnerability-database/cve-2026-14783/ ；https://vuldb.com/vuln/398458 |
| X19 | https://docs.openclaw.ai/clawhub/moderation.md （官方網域開不到；搜尋摘要引用的是第三方鏡像） |
| Y1 | https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks |
| Y5 | https://arxiv.org/abs/2601.10338 |
| Y6 | https://blog.trailofbits.com/2026/06/03/the-sorry-state-of-skill-distribution/ |
| Y7 | https://arxiv.org/abs/2403.14720 |
| Y8 | https://arxiv.org/abs/2510.09023 |
| Y9 | https://simonwillison.net/2023/Apr/25/dual-llm-pattern/ ；https://simonwillison.net/2025/Apr/11/camel/ |
| Y10 | https://arxiv.org/abs/2503.18813 |
| Y11 | https://arxiv.org/abs/2506.08837 |
| Y12 | https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ ；https://ai.meta.com/blog/practical-ai-agent-security/ |
| Y13 | https://developers.openai.com/api/docs/guides/agent-builder-safety |
| Y14 | https://venturebeat.com/security/openai-admits-that-prompt-injection-is-here-to-stay |
| Y15 | https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026 |
| Y16 | https://security.googleblog.com/2023/04/securely-hosting-user-data-in-modern.html ；https://web.dev/articles/securely-hosting-user-data |

（X18、Y2–Y4 沒有使用：報告之間重複的來源併到同一個代號。）
