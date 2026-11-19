# 交辦單：Windows 上「隔離工具執行」——階段 0（禁寫範圍）與階段 1（環境變數白名單、保護等級），加上階段 1.5～3 的設計草案與實測清單

> 這份是**交辦單**：給一個完全空白的 session（另一台電腦、docker、雲端都可以），沒有對話紀錄、沒有開發機上的檔案，**只讀這份就能開工**。
> 它是 [ADR 0022](../adr/0022-ecosystem-bridge-and-sandbox.md) §6（隔離）的延伸。階段 2（AppContainer）與階段 3（MXC）的**實作**不在這張單，另開交辦單（§6 的「後續」）。

---

## 1. [狀態]

**待做**（2026-11-19 寫；今天只寫交接，沒有人開工）。

| 項目 | 值 |
|---|---|
| 基底（SYNOX 核心） | `origin/dev`；寫這份時是 `bb465f5` |
| 另一個 repo（工具庫） | 階段 0 有一小段要改工具庫的 workspace 工具與它的 ADR 0009（§3.2 第 5 條）。**寫這份時，workspace 與 ADR 0009 只在維護者本機的工具庫 `main`（`f312ac0`），還沒推到遠端**——接手時先檢查，沒有就把那一條標「卡住：等工具庫推送」，其他照做 |
| 誰在做 | 還沒有人接 |
| 卡住的地方 | 無（工具庫那一條見上一列）。有一題要維護者決定（環境變數白名單怎麼上線，§2.6），沒決定照預設 |

接手後把這一段改成「進行中：做到 §3 第幾條；分支 `feat/isolation-stage0-1-<YYYYMMDD>`；最新 commit `<hash>`」，卡住就寫「卡住：卡在哪、為什麼」。

## 2. [前情提要]

標籤：**已查證**＝讀了程式或一手文件；**已實測**＝在真機上跑過（目前只有一台 Windows 11 Home 的結果，見 `docs/lab/2026-11-16-windows-sandbox-probe-results.md`）；
**推測**＝推出來、還沒驗證；**待實測**＝要在目標電腦上跑過才知道。

### 2.1 現況（技術事實）

| 事實 | 標籤 | 在哪 |
|---|---|---|
| Windows 上沙盒預設後端是 `none`：工具用使用者帳號的全部權限跑 | 已查證 | `src/synox/sandbox.py` 的 `resolve()`；[ADR 0022 §6.1](../adr/0022-ecosystem-bridge-and-sandbox.md) |
| `jobobject` 只限記憶體與程序數（`isolates = False`）；`appcontainer` 只有介面（`wrap` 丟 `NotImplementedError`，`resolve()` 退回 `none`） | 已查證 | `sandbox.py` 的 `JobObjectSandbox`、`AppContainerSandbox` |
| `kind=python` 的工具在 SYNOX 自己的程序裡跑，**任何沙盒後端都包不到** | 已查證 | [ADR 0022 §6.6](../adr/0022-ecosystem-bridge-and-sandbox.md)、[ADR 0041 §5](../adr/0041-pack-warnings.md) |
| 子程序的環境＝SYNOX 整份環境變數，只拿掉名字像密鑰的（`*API_KEY`、`*SECRET`、`*PASSWORD`、`*_TOKEN`…）；`Sandbox.wrap()` 回的 env 只是「額外的」，會被疊在整份環境上 | 已查證 | `vendor/isdtelekit/jobs/runner.py` 的 `child_env()`、`jobs/cli.py` 的 `clean_env()`；`src/synox/packs/loader.py`（`box.wrap` 在 `make_cli`）、`src/synox/packs/mcp.py`（`box.wrap`） |
| **`vendor/isdtelekit/` 不能改**（`AGENTS.md`） | 已查證 | `AGENTS.md` |
| 保護等級（完整／基本／沒有）的白話草稿已經在 ADR 0022 §6.2；警告下面「這台實況」那一行已經有（`isolation_note`、`isolation_line`），規則是**任何狀態都不說「已在 sandbox／已隔離／安全」** | 已查證 | [ADR 0022 §6.2](../adr/0022-ecosystem-bridge-and-sandbox.md)、[ADR 0041 §5.5](../adr/0041-pack-warnings.md)、`sandbox.py` |
| 設定頁的「沙盒模式」卡（`set-sandbox`）是預留位置：開關 `disabled`、標「尚未完成」 | 已查證 | `src/synox/web/static/app.html`、[../sandbox-roadmap.md](../sandbox-roadmap.md) 第二節 |
| AppContainer（自己寫）：一般帳號建得起來；檔案隔離成立；網路只有全斷或全開；**loopback 一律擋**（接不了代理，做不出網域名單）；裝在使用者資料夾的 Python／Node 讀不到，要複製到有給權限的資料夾；**父程序整份環境會傳進去** | 已實測（只有 Windows 11 Home 一台） | `docs/lab/2026-11-16-windows-sandbox-probe-results.md` §3.1 |
| AppContainer 在 Windows 10 上一樣嗎 | **待實測** | 同上 §6 |
| MXC（Windows 11 內建）：檔案政策、預設擋外連、只放行到本機代理的埠、長駐 stdio、不用管理員；用 `wxc-exec.exe`（官方 npm 套件裡、MIT、Microsoft 簽章）可以直接從 Python 驅動；Node 與 Python 的 `ssl` 要開 UI（Win32k）；有 4 種關不掉的必要遙測 | 已實測（一台）／遙測已查證 | 同上 §3.3、§4 |
| MXC **本體**的最低 build（24H2 `26100.9278`、25H2 `26200.9278`）和「只連白名單代理」需要的 loopback 功能的 build（`26200.9550`）**不同** | 已查證（官方文件） | 同上 §2、§6；[ADR 0022 §6.3](../adr/0022-ecosystem-bridge-and-sandbox.md) |
| MXC 在兩個 build 之間能不能用代理模式；代理的正式模式（有身分的 `allowedProxyPeer`）；放外連；UDP／IPv6／DNS 外洩；孫程序（子程序再開子程序） | **待實測** | 同上 §3.4、§8 |
| 不需要系統管理員（UAC）的只有 MXC 與 AppContainer；WSL2、Docker、Podman、專用帳號＋WFP、Sandboxie 第一次都要管理員；Windows Sandbox 在 Home 版沒有 | 已查證（MXC、AppContainer 已實測不用管理員；其餘讀文件）／Sandboxie 推測 | [../sandbox-roadmap.md](../sandbox-roadmap.md) 第三節 |

### 2.2 已決定的方向（**不要再問**）

- **(a) workspace 工具包不到**：工具庫的 workspace 工具是 `kind: python`，在 SYNOX 程序內跑，任何沙盒包不到；而且工具庫 ADR 0009 決定 #1 禁止它用 `subprocess`。
  所以要先在核心提供「把一組**固定 argv** 丟進沙盒跑」的介面（階段 1.5），再改寫 ADR 0009 #1（改成「只能呼叫核心的固定 argv 介面，自己仍然不 import subprocess」）。
  **這張單只寫這兩件事的設計草案，不實作、不改 ADR 0009 #1。**
- **(b) 禁寫範圍兩層都寫**：沙盒政策本身也要禁寫 `.git/`、`.gitattributes`、`.gitmodules`、`.vscode/`、`.github/workflows/`、`.idea/`。
  理由：工具自己的路徑檢查擋得住「工具」，擋不住「沙盒裡的程式」——它可以寫 `.git/config`（例如 `core.fsmonitor`、`core.hooksPath`）、`.vscode/tasks.json`、工作流程檔，之後由**沙盒外**的 git、編輯器、CI 觸發執行。所以 ADR 與沙盒政策兩層都要寫。
- **(c) `pytest` 最後才開**：要等「基本隔離＋核心固定 argv 介面＋環境變數白名單」都有了才開。pytest 會自動載入 `conftest.py`、讀設定檔的 `addopts`、環境變數 `PYTEST_ADDOPTS`、`PYTEST_PLUGINS`（等於執行專案裡任何人寫的程式）。
- **(d) v1 的 git 唯讀**：先研究純 Python 讀取（新相依要另外審；要查讀取時會不會跑 `.gitattributes` 的 filter／textconv）；不可行才用 `git.exe`＋固定參數
  （`-c core.hooksPath=/dev/null`、`--no-optional-locks`、`-c log.showSignature=false`、`--ignore-submodules` 等）＋禁寫＋在 ADR 0009 #1 開例外。
- **(e) Windows 10 只開離線版 v2**：AppContainer 斷網（**待實測**）；要連網的指令回報「這台做不到」，不要假裝。Windows 11 新版可以走 MXC（§2.1 的待實測項目要先測）。
- **(f) UAC**：預設只走不用管理員的路（MXC、AppContainer）；其他當選配。
- **(g) 分階段**：

  | 階段 | 內容 | 這張單 |
  |---|---|---|
  | 0 | 補禁寫範圍（ADR、沙盒政策、工具庫 ADR 0009 與 workspace 的禁寫清單） | **做** |
  | 1 | 共用零件：環境變數白名單、保護等級偵測與顯示（連外代理也屬於這一階段，但這張單**不做**，因為要開本機埠，另開單） | **做**（不含代理） |
  | 1.5 | 核心「固定 argv 進沙盒」介面 | 只寫設計草案 |
  | 2 | AppContainer 基本隔離（先於 MXC；**除非**接手者偵測到只有 Windows 11 新版的環境，才可以先做 MXC） | 只寫設計草案與實測清單；實作另開單 |
  | 3 | MXC 完整隔離 | 同上 |
  | 4 | 選配 WSL2／容器 | 草案裡提一段 |
  | 另路 | 高風險工作交給雲端或別台電腦 | 草案裡提一段 |

### 2.3 相關文件

| 東西 | 在哪 |
|---|---|
| 隔離的設計與決定 | [ADR 0022 §6](../adr/0022-ecosystem-bridge-and-sandbox.md)（6.2 共用抽象與保護等級、6.3 Windows 路線、6.4 連外名單、6.5 密鑰、6.6 `kind=python`） |
| pack 警告與沙盒的關係 | [ADR 0041 §5](../adr/0041-pack-warnings.md) |
| 公開的路線圖 | [../sandbox-roadmap.md](../sandbox-roadmap.md) |
| Windows 探測紀錄與腳本 | `docs/lab/2026-11-16-windows-sandbox-probe-results.md`、`docs/lab/tools/windows-sandbox-probe/`（README 有 MXC 的取得與驗證方式） |
| 真機驗證的交辦 | [20261119-134608-sandbox-real-machine.md](20261119-134608-sandbox-real-machine.md)、[sandbox-real-machine.md](sandbox-real-machine.md) |
| 相關的待決定題目 | [S3](open-questions/20261119-121055-s3-warning-default-off-without-isolation.md)、[MXC 探針能不能在驗證機上跑](open-questions/20261119-134611-mxc-probe-on-verification-machine.md) |
| 程式 | `src/synox/sandbox.py`（`Grants`、各後端、`resolve`、`isolation_note`）、`src/synox/packs/loader.py`（`cli_env`、`context_env`、`make_cli`）、`src/synox/packs/mcp.py`、`src/synox/doctor.py` |
| 工具庫（另一個 repo） | workspace 工具 `packs/workspace/pack.py`（`DENY_NAMES` 等禁區）、`docs/adr/0009-workspace-tool.md`、`tests/test_workspace.py` |

### 2.4 這張單沒有要做的決定

保護等級三個名字與白話（ADR 0022 §6.2）、白名單的方向（ADR 0022 決定 16）、禁寫清單（上面 (b)）都已經決定。

### 2.5 測試與埠

這張單的東西全部可以用假後端、假 `which`、假的平台資訊測；**不需要開任何埠**。真的要開（例如看設定頁），照 §4.5。

### 2.6 要維護者決定的事

| 題目 | 沒決定時的預設 |
|---|---|
| [環境變數白名單怎麼上線（一次擋，或先一版只記錄）](open-questions/20261119-153433-env-allowlist-rollout.md) | 照建議：一次套用＋一版內可退回的設定開關 |

## 3. [任務]

### 3.1 先讀、先記基準

1. 照 §4 建環境、跑基準。讀 §2.3 的 ADR 與程式。

### 3.2 階段 0：禁寫範圍

2. **核心 ADR**：寫一份新 ADR（編號用當時下一個空號，寫這份時是 0043；另一張交辦單也可能用到，撞號照 [../adr/README.md](../adr/README.md) 處理），
   標題類似「沙盒裡禁寫的版控與編輯器設定」：禁寫清單（§2.2 (b) 的六項）、為什麼（沙盒外的程式會執行它們）、每個後端做得到幾成、做不到的怎麼在保護等級上反映。
   同時在 ADR 0022 §6.2 加一行指向新 ADR；更新 `docs/adr/README.md` 索引。
3. **沙盒政策**：`Grants`（或旁邊的常數）加上禁寫清單，預設就有、pack 不能拿掉；
   - 做得到的後端（bwrap、systemd、容器）在**組 argv 時**套上（例如唯讀掛載、`ReadOnlyPaths=`）；**還不存在的路徑怎麼擋**（例如先放一個唯讀的空掛載、或在可寫的資料夾裡預先建好唯讀的）是實作時要定的，寫進 ADR 並有測試；
   - 做不到的後端（`none`、`jobobject`）不要假裝：在後端的能力屬性上標「擋不住禁寫範圍」，保護等級（第 7 條）照實算。
   - 測試：每個後端組出來的 argv 都含禁寫的設定；`none`／`jobobject` 的能力屬性正確。**不在本機實際執行 bwrap、容器**（這台多半沒有；真機驗證在 [20261119-134608](20261119-134608-sandbox-real-machine.md) 那條線）。
4. 文件：`docs/security.md` 的沙盒一節、[../sandbox-roadmap.md](../sandbox-roadmap.md) 第二節補一句禁寫範圍；`CHANGELOG.md` 的「未發佈」。
5. **工具庫**（另一個 repo；先確認遠端有 workspace，沒有就標卡住、跳過這條）：在工具庫開自己的分支（`fix/workspace-deny-write-<YYYYMMDD>`），
   - ADR 0009 第 3 節 #4／#6 補上禁寫範圍（`.git/` 本來就整個禁；加 `.gitattributes`、`.gitmodules`、`.vscode/`、`.github/workflows/`、`.idea/`），第 4 節的攻擊清單補對應的案例；
   - `packs/workspace/pack.py` 的寫入類動作拒絕這些位置（讀要不要也擋：照 ADR 0009 現有的禁區規則判斷，寫進 ADR）；
   - `tests/test_workspace.py` 每一項各至少一個案例（大小寫變化、路徑分隔、`a/../.vscode` 這類也要），斷言被拒、而且沒有檔案被建立；
   - **不改 ADR 0009 決定 #1**（那是 1.5 的事，這張單只寫草案）。

### 3.3 階段 1：共用零件（不含連外代理）

6. **環境變數白名單**（ADR 0022 決定 16；上線方式見 §2.6 的題目，沒決定照建議）：
   - 子程序（cli、mcp stdio，以及之後的固定 argv 介面）的環境改成**白名單**：系統必要的幾個（例如 Windows 的 `SYSTEMROOT`、`WINDIR`、`TEMP`、`TMP`、`PATHEXT`、`PATH`；POSIX 的 `PATH`、`HOME`、`LANG`、`LC_*`、`TMPDIR`——**實際清單實作時定、寫進 ADR**）
     ＋ pack 宣告的（`requires.env` 的密鑰名、`cli.env`）＋ SYNOX 自己給的（`SYNOX_*` 那組 context、`PYTHONIOENCODING`）＋（之後的）代理設定；
   - 一定要拿掉的例子（測試要涵蓋）：`PYTEST_ADDOPTS`、`PYTEST_PLUGINS`、`GIT_*`、`PYTHONPATH`、`PYTHONSTARTUP`、`NODE_OPTIONS`、任何不在白名單上的使用者變數；
   - **`vendor/isdtelekit/` 不能改**，而它會把 `os.environ` 整份疊上去（§2.1）：要在 SYNOX 這一層做到（例如沿用 `jobobject` 的作法，經一個 `python -I` 的小 launcher 重建環境再啟動；或其他不改 vendor 的方式）——選哪個寫進 ADR、附理由；
   - 白名單在**每一個後端都生效**（包括 `none`），因為它不需要隔離就做得到；
   - 測試：用假程式印出自己的環境，斷言只剩白名單上的；mcp stdio 也一樣；既有工具（測試裡的假 pack）照常能跑。
7. **保護等級偵測與顯示**：
   - 一個函式（例如 `sandbox.protection(config)`）回：等級（`full`／`basic`／`none`，白話用 ADR 0022 §6.2 的三句）、用的後端、偵測到的環境（作業系統、Windows build、版別、有沒有 bwrap／podman／docker 等）、**做不到的項目**（檔案、直連網路、網域名單、禁寫範圍）；
   - 偵測**只讀**：讀版本、讀登錄機碼、`shutil.which`；**不執行下載來的東西**（不跑 `wxc-exec.exe`）、不需要管理員、不連網、不開埠。Windows 的 build 要看 `CurrentBuild`／`UBR`，**不要看 `ProductName`**（Windows 11 上常寫成 Windows 10，探測紀錄有記）；
   - 現在 Windows 一律是「沒有」（AppContainer、MXC 都還沒有後端）；偵測到「這台的 build 夠 MXC」可以顯示成「這台之後可以支援」，**不能**顯示成有保護；
   - 顯示在：`doctor`、設定頁的 `set-sandbox` 卡（把預留位置換成「這台的保護等級＋做不到什麼」，開關照舊不能開）、對應的 API；
   - 跟 `isolation_note` 一致：任何狀態都不說「已在 sandbox／已隔離／安全」；
   - 測試：假平台（Windows 10、Windows 11 不同 build、Linux 有／沒有 bwrap、容器）各一個案例，等級與文字對；深淺色、手機寬度下設定卡不破版。
8. 文件：新 ADR（或第 2 條那份的另一節）寫白名單與保護等級；`docs/security.md`、[../sandbox-roadmap.md](../sandbox-roadmap.md) 第二節更新；`CHANGELOG.md`。

### 3.4 階段 1.5～3 的設計草案與實測清單（只寫文件）

9. 寫 **`docs/design/windows-isolation-stages.md`**（`docs/design/` 不存在就建），內容至少：
   - **1.5 固定 argv 介面**：介面草稿（參數只收常數模板＋有型別的格子、不經 shell、逾時、輸出上限、環境白名單、走當時的沙盒後端）、誰可以叫（只有核心與審過的工具）、怎麼防止它變成「執行任意指令」；
     **ADR 0009 #1 的改寫草稿**（只寫在這份草案裡，不去改工具庫的 ADR）。
   - **git 唯讀（v1）**：純 Python 讀取的候選（新相依要另外審）、讀取時會不會碰到 filter／textconv／hooks 的查證清單；退路 `git.exe` 的固定參數清單（§2.2 (d)，再補 `--no-ext-diff`、`--no-textconv`、清掉 `GIT_*` 與全域／系統設定等，逐項說明為什麼）。
   - **pytest**：開放的前提（§2.2 (c)）、怎麼關掉自動載入（逐項列出要處理的入口）。
   - **階段 2 AppContainer**：Windows 10／11 都走的「基本」等級；斷網；直譯器放在 SYNOX 管的資料夾並加權限；環境自己組；要連網的指令回「這台做不到」。
   - **階段 3 MXC**：build 門檻（本體與代理功能分開判斷）、`wxc-exec.exe` 怎麼取得與驗簽（出貨或第一次需要時下載，待維護者決定）、UI 開關的代價、遙測要寫進隱私說明。
   - **階段 4 與另路**：WSL2／容器當選配（第一次要管理員）；高風險工作交給雲端或別台電腦。
   - **實測清單**：每一項寫「在什麼環境做（由執行的人自己偵測：版本、build、版別、有沒有管理員、有沒有 docker／podman）」「做什麼」「預期」「標籤」；
     至少涵蓋 §2.1 所有「待實測」：Windows 10 上的 AppContainer、MXC 兩個 build 之間的代理模式、代理正式模式、放外連、UDP／IPv6／DNS 外洩、孫程序、長時間 stdio；
     每一項都註明「要執行下載來的程式（例如 `wxc-exec.exe`）的，**先取得維護者同意**，在拋棄式環境做」（見 [MXC 探針的題目](open-questions/20261119-134611-mxc-probe-on-verification-machine.md)）。
   - 每一段標**已查證／已實測／推測／待實測**，引用 §2.3 的文件。
10. 在 [../sandbox-roadmap.md](../sandbox-roadmap.md) 第五、七節加這份草案的連結。

### 3.5 範圍邊界與不要做的事

- **不實作**階段 1.5、2、3、4；不寫 AppContainer、MXC 的程式；不改工具庫 ADR 0009 決定 #1；不開 pytest、git 指令給工具。
- **不做連外代理**（要開本機埠，另開單）。
- **不在本機跑任何下載來的探針或可執行檔**（包括 `wxc-exec.exe`、別人的腳本）；探針類的實測只寫進 §3.4 的清單，交給「在目標電腦上、執行的人自己偵測環境」的步驟。
- **不改防火牆**；**不開對外的埠**；需要在本機開埠時只綁 `127.0.0.1`、記下自己開的程序（pid）與埠、測完關掉並確認放掉（§4.5）。
- 不用系統管理員權限、不改系統設定（群組原則、登錄、WFP 規則、AppContainer 的 loopback 豁免）。
- **不改 `vendor/isdtelekit/`**。
- 不改「這台實況」那一行的規則（ADR 0041 §5.5）；不把任何狀態寫成「已隔離」「安全」。
- 不放寬既有的檢查（第 1 關的 `safe_env`、五關、簽章）。
- 不跑重負載：測試用假後端；不要同時開好幾個 SYNOX；同時最多 5 個背景 agent。
- 不合併、不推送（兩個 repo 都一樣）。

## 4. [安裝流程與環境確認]

### 4.1 自己偵測環境（寫進回報；不寫電腦名稱、帳號名、路徑）

```sh
# 作業系統（bash／zsh）
uname -srm; head -3 /etc/os-release 2>/dev/null
# Windows（PowerShell）
#   [System.Environment]::OSVersion.VersionString
#   Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' | Select-Object CurrentBuild, UBR, EditionID, DisplayVersion
python --version || python3 --version       # 要 3.11 以上
git --version
command -v bwrap podman docker 2>/dev/null   # 有什麼就記什麼；Windows：Get-Command podman, docker -ErrorAction SilentlyContinue
```

這張單的程式部分在任何作業系統都能做（用假平台測）。有沒有 docker／podman、是不是 Windows 都不影響開工；**只是記下來**，§3.4 的實測清單要用。
**不需要任何祕密**：不用模型 token、不用雲端帳號。

### 4.2 取得程式

```sh
git clone <SYNOX 的 repo 網址（見 docs/handoff/README.md 的「最短路徑」）> synox-isolation
cd synox-isolation
git fetch origin
git switch -c feat/isolation-stage0-1-<YYYYMMDD> origin/dev     # 同名已存在就換名字
git log --oneline -1
python -m venv .venv
# Windows： .venv\Scripts\python -m pip install -e ".[dev]"
# Linux／macOS： .venv/bin/python -m pip install -e ".[dev]"
python -c "import synox; print(synox.__file__)"                 # 要在這個資料夾的 src/synox/ 底下
```

工具庫（§3.2 第 5 條才要）：

```sh
git clone <工具庫的 repo 網址（SYNOX 的 README.md 開頭有連結）> synox-libs
cd synox-libs && git fetch origin
git ls-tree -r origin/main --name-only | grep -E 'docs/adr/0009-workspace-tool.md|packs/workspace/pack.py'
#   → 兩行都有才做第 5 條；沒有＝卡住（等推送），回報寫明
git switch -c fix/workspace-deny-write-<YYYYMMDD> origin/main
```

工具庫的測試用 SYNOX 的 `.venv`（它要 import `synox` 與 `isdtelekit`）：在 `synox-libs` 裡跑 `<synox-isolation 的 .venv 的 python> -m pytest -q -p no:cacheprovider tests/test_workspace.py`。

### 4.3 開工前先跑測試記基準（**還沒改任何東西時**）

```sh
python -m pytest -q -p no:cacheprovider tests/test_sandbox.py tests/test_sandbox_ready.py tests/test_container_sandbox.py tests/test_envs.py
python -m pytest -q -p no:cacheprovider tests/test_security.py tests/test_mcp_stdio.py tests/test_perm2.py tests/test_container.py tests/test_container_install.py
python -m pytest -q -p no:cacheprovider tests/test_web.py
```

**參考基準**（來源：2026-11-19 在暫時 worktree 實際跑出來；Windows、Python 3.11.9、pytest 9.2.0；`PYTHONPATH` 指向那個 worktree 的 `src`）：

| 範圍 | 基底 | 結果 |
|---|---|---|
| `test_sandbox.py`＋`test_sandbox_ready.py`＋`test_container_sandbox.py`＋`test_envs.py` | SYNOX `origin/dev`＝`bb465f5` | **100 passed**（0 failed） |
| `test_security.py`＋`test_mcp_stdio.py`＋`test_perm2.py`＋`test_container.py`＋`test_container_install.py` | 同上 | **168 passed**（0 failed） |
| `test_web.py` | 同上 | **58 passed**（0 failed） |
| 工具庫 `tests/test_workspace.py` | 工具庫本機 `main`＝`f312ac0`（含 workspace；寫這份時還沒推到遠端） | **130 passed, 1 skipped** |

- 你那台的數字**以自己跑出來的為準**；不同就寫差在哪（平台不同時有測試被略過是正常的）。
- 有 failed：記成「本來就壞的」，不修（不在範圍），回報列出。
- 全部測試（`python -m pytest -q -p no:cacheprovider`）交回前跑一次。

### 4.4 開工前確認（全部是「是」才開始）

- [ ] 分支從最新的 `origin/dev` 開，基底 commit 記下來了。
- [ ] `synox.__file__` 在自己的資料夾底下。
- [ ] §4.3 的基準跑過，數字記下來了。
- [ ] §4.1 的環境記下來了（沒有電腦名稱、帳號名、路徑）。
- [ ] 讀過 §3.5（不要做的事）。

### 4.5 要開本機埠時（例如看設定頁）

只綁 `127.0.0.1`（SYNOX 預設，不要改）；開之前記下自己開的程序 pid 與埠號；看完關掉並確認埠已放掉
（Windows：`Get-NetTCPConnection -LocalPort <埠>` 沒有東西；Linux／macOS：`ss -ltnp | grep <埠>` 或 `lsof -i :<埠>` 沒有東西）。
那台電腦上別人開的服務一律不碰；分不清是不是自己開的，就當成別人的。

## 5. [驗證清單集]

給高水準模型（驗收者）在 merge 前逐項確認。`<base>`＝`git merge-base origin/dev <branch>`，`<branch>`＝接手者在 SYNOX 的分支；
工具庫的分支另記 `<libs-branch>`，基底 `<libs-base>`。**每一項都要實際跑或實際看；有任何一項不通過就不 merge。**

| # | 檢查什麼 | 指令／怎麼看 | 預期 |
|---|---|---|---|
| V1 | 分支與基底 | `git log --oneline -1 <base>`；`git branch -r --contains <base>` | SYNOX 分支 `feat/isolation-stage0-1-<YYYYMMDD>`，基底在 `origin/dev`；工具庫分支（有的話）基底在 `origin/main` |
| V2 | 任務逐條都做了 | 對照 §3 第 1～10 條與回報的逐條結果 | 每一條有「做了什麼＋commit」；第 5 條沒做的，回報寫「卡住：工具庫遠端沒有 workspace」並附 §4.2 的檢查輸出 |
| V3 | 沒做範圍外的事 | `git diff --stat <base> <branch>`；搜 `AppContainer`、`wxc`、`CreateAppContainerProfile`、`proxy` 的新程式 | 沒有 AppContainer／MXC／代理的實作；沒有改 `vendor/isdtelekit/`（`git diff --stat <base> <branch> -- vendor/` 沒有輸出） |
| V4 | 新 ADR | `ls docs/adr/`；讀新 ADR；看 `docs/adr/README.md` | 號碼不撞、索引有它；有禁寫清單的六項、理由、每個後端做得到幾成、做不到怎麼反映；白名單與保護等級有寫（同一份或另一份） |
| V5 | 禁寫清單在程式裡 | `grep -n "gitattributes\|gitmodules\|workflows\|\.idea\|\.vscode" src/synox/sandbox.py` | 六項都在；pack 拿不掉（有測試） |
| V6 | 做得到的後端有套上禁寫 | 跑新測試（bwrap、systemd、容器組出來的 argv） | 每個後端的 argv 都有禁寫設定；「還不存在的路徑」的做法有測試 |
| V7 | 做不到的後端不假裝 | 新測試：`none`、`jobobject` 的能力屬性 | 標「擋不住禁寫範圍」；保護等級不是 `full`／`basic` |
| V8 | 環境變數白名單 | 新測試：假程式印出環境 | 只剩白名單上的；`PYTEST_ADDOPTS`、`PYTEST_PLUGINS`、`GIT_*`、`PYTHONPATH`、`PYTHONSTARTUP`、`NODE_OPTIONS` 都不在；cli 與 mcp stdio 兩條路都測到；`none` 後端也生效 |
| V9 | 既有工具沒被白名單弄壞 | §4.3 三行測試 | 0 failed；passed 數 ≥ 基準（100、168、58）＋新增的 |
| V10 | 保護等級偵測 | 新測試：假平台各案例 | Windows 一律 `none`；build 夠 MXC 時只說「之後可以支援」；看 `CurrentBuild` 不看 `ProductName`；Linux 有 bwrap 時等級與做不到的項目正確 |
| V11 | 偵測是唯讀的 | 讀偵測的程式碼 | 沒有 `subprocess` 執行下載的東西、沒有網路、沒有寫檔、沒有要求管理員 |
| V12 | 顯示的字沒有說成已隔離 | `git diff <base> <branch> \| grep -nE '^\+.*(已隔離\|已在 sandbox\|安全了\|受到保護)'` | 沒有輸出（否定句、文件裡說明規則的除外，要逐條看） |
| V13 | 設定頁與 doctor | 測試或看畫面：`set-sandbox` 卡、`doctor` 輸出 | 顯示保護等級＋做不到什麼；開關仍不能開；深淺色、手機寬度不破版 |
| V14 | 工具庫的禁寫（有做的話） | 在工具庫：`git diff <libs-base> <libs-branch>`；跑 `tests/test_workspace.py` | ADR 0009 #4／#6 與第 4 節有補；**#1 沒改**；新案例涵蓋六項與大小寫、`..` 變化；0 failed，passed ≥ 130＋新增 |
| V15 | 設計草案 | 讀 `docs/design/windows-isolation-stages.md` | 有 §3.4 第 9 條列的每一段；每段有標籤；ADR 0009 #1 改寫只是草稿 |
| V16 | 實測清單 | 同上的實測清單一節 | 涵蓋 §2.1 每一個「待實測」；每項有「環境由執行的人自己偵測」「做什麼」「預期」；要執行下載程式的項目寫「先取得維護者同意、拋棄式環境」 |
| V17 | 全部測試沒比基準多壞 | 在 `<base>` 與 `<branch>` 各跑 `python -m pytest -q -p no:cacheprovider` | `<branch>` 的 failed 不多於 `<base>` |
| V18 | 文件已更新 | `git diff --name-only <base> <branch>` | 有新 ADR、`docs/adr/README.md`、ADR 0022（§6.2 加指向）、`docs/security.md`、`docs/sandbox-roadmap.md`、`CHANGELOG.md`、設計草案 |
| V19 | 沒有 TODO／半成品 | 指令 C | 沒有輸出 |
| V20 | 整棵樹與所有 commit 訊息沒有私人資訊 | 指令 A、A2（SYNOX 與工具庫各跑一次） | 沒有新增的結果 |
| V21 | 沒有密鑰 | 指令 B | 沒有輸出 |
| V22 | 公開前檢查腳本 | `python scripts/prepublish_check.py --worktree-only`（沒有私人詞清單時加 `--allow-no-terms` 並在回報寫明） | 跟 `<base>` 上跑的結果相比沒有新的問題 |
| V23 | 沒在本機執行下載的東西、沒開對外埠 | 看回報的「收拾」與「執行過什麼」 | 沒有下載或執行任何外部可執行檔；開過的本機埠（如果有）有 pid、埠號、關掉的確認輸出 |
| V24 | commit 訊息 | `git log <base>..<branch>`（工具庫同） | 每個 commit 寫做了什麼、為什麼；agent 做的結尾有共同作者行 |

指令（bash；Windows 用 Git Bash）：

```sh
# A：整棵樹的私人資訊（本機路徑、家目錄、信箱、常見的電腦名稱開頭）
git grep -nEi 'C:\\Users\\|/home/[a-z]|/Users/[a-z]|[a-z0-9._-]+@[a-z0-9-]+\.(com|net|org|tw|io)|DESKTOP-|LAPTOP-' <branch> -- .
#   → 只看這次新增或改到的檔；<base> 上本來就有的不算，但回報裡要說明
# A2：commit 訊息
git log <base>..<branch> --format=%B | grep -nEi 'C:\\Users\\|/home/[a-z]|/Users/[a-z]|@[a-z0-9-]+\.(com|net|org|tw|io)|DESKTOP-|LAPTOP-' | grep -v 'noreply@'
# B：密鑰
git diff <base> <branch> | grep -nEi 'token\s*[:=]|api[_-]?key\s*[:=]|ghp_|sk-[A-Za-z0-9]{10}|BEGIN [A-Z ]*PRIVATE KEY|AGE-SECRET-KEY'
# C：TODO／半成品
git diff <base> <branch> | grep -nE '^\+.*(TODO|FIXME|XXX|待補|未完成)'
```

驗收者回報格式：「V1～V24 逐項：通過／不通過（原因）」＋「留下的問題」。全部通過才由驗收者 `git merge --no-ff`（SYNOX 進 `dev`；工具庫進它的目標分支），
merge commit 訊息寫這個分支做了什麼、為什麼，再把這份交辦單的 [狀態] 改成「已完成：merge commit `<hash>`」。

## 6. [交回]

1. 結論一句話（全部做完／做到第幾條、卡在哪）。
2. SYNOX 的分支、最新 commit、基底；工具庫的分支、最新 commit、基底（或「卡住：遠端沒有 workspace」）。
3. 環境（§4.1 偵測到的；不寫電腦名稱、帳號名、路徑）。
4. 測試：§4.3 的基準數字、交回前同樣指令的數字、全部測試的 passed／failed（和基底比）。
5. §3 第 1～10 條逐條：做了什麼、在哪個 commit；選了哪種方式做白名單（為什麼）、「還不存在的路徑」怎麼擋。
6. §5 驗證清單集裡自己能先檢查的（V1～V16、V18～V24）逐項自查結果。
7. 「執行過什麼」：有沒有開過本機埠（pid、埠號、關掉的確認輸出）；確認沒有下載或執行外部程式。
8. 不確定的地方、想請維護者決定的事：照 `docs/handoff/open-questions/` 的格式另寫題目檔，**不要自己改已決定的事**。
9. **後續**（另開交辦單，這張不做）：
   - 階段 1 的連外代理（本機埠、只綁 127.0.0.1、每個工具一個入口）；
   - 階段 1.5 核心固定 argv 介面＋工具庫 ADR 0009 #1 改寫；
   - 階段 2 AppContainer 基本隔離（Windows 10／11）；
   - 階段 3 MXC 完整隔離（Windows 11 新版）；
   - 實測清單的執行（在目標電腦上，執行的人自己偵測環境；要跑下載程式的項目先取得維護者同意）；
   - 之後才是 workspace v1 的 git 唯讀與 pytest。

**只 commit 在自己的功能分支；不合併、不推送。** 合併由驗收者照 §5 確認後用 `git merge --no-ff` 做。
維護者另外要你推到遠端讓驗收者拿時，才推那一條分支，推之前自己跑一次 V20～V22。
