# Windows 沙盒實測結果（第一次在真機上跑）

> **English summary.** First real-Windows run of SYNOX's sandbox probes, on Windows 11 **Home** 25H2 (build 26200.9974),
> normal user, no admin. **MXC (Microsoft eXecution Containers) ProcessContainer works on this Home PC** with the
> Microsoft-signed `wxc-exec.exe` taken from the official `@microsoft/mxc-sdk` npm tarball (MIT): file policy,
> per-container egress deny, an "identityless" loopback proxy that lets the box reach only SYNOX's proxy port
> (Ollama 11434 and SYNOX 8830 stay blocked), per-user Python/Node readable through `readonlyPaths`, and a
> long-running stdio round-trip all passed, ~0.1 s per container. Caveats: Node and Python's `ssl` need UI (Win32k)
> enabled; MXC sends four "Required" telemetry events that cannot be turned off; the proxy mode we used is documented
> as "primarily for development". The hand-built AppContainer also works without admin (files isolated; network all-or-
> nothing; loopback always blocked so no proxy; per-user interpreters unreadable unless copied; it inherits the whole
> parent environment). Write-restricted token + Job Object blocks writes only. Not yet tested: Windows 10, Windows 11
> Pro, Windows 11 builds older than the MXC baseline. Recommendation (not a decision): MXC as the main route, driven
> from Python through `wxc-exec.exe`; AppContainer as the "basic" fallback.

- 狀態：**實測紀錄**（研究附件）。這份不改 ADR 0022、實作計畫、路線圖；只提供擁有者決定 11–14 的依據。
- 日期：2026-11-16。測試的人：Claude（在擁有者的電腦上，擁有者同意拿這台做沙盒測試）。
- 腳本：[`tools/windows-sandbox-probe/`](tools/windows-sandbox-probe/)（commit `6bdb70b` 起的版本；第一次跑遇到的 bug 已修，列在該資料夾 README 的「2026-11-16」一節）。
- 原始結果（帳號名已換成 `<user>`）：[`2026-11-16-windows-sandbox-probe-results/`](2026-11-16-windows-sandbox-probe-results/)。

## 怎麼讀

| 標籤 | 意思 |
|---|---|
| **已實測** | 這次在這台電腦上跑過，結果就是表上寫的 |
| **已查證** | 讀到 Microsoft 的一手文件或官方 repo（附網址） |
| **查不到** | 找過、沒找到；寫明找過哪裡 |
| **推測** | 根據上面幾種推出來的，還沒驗證 |

**只有一台電腦的結果。** 換一台（Windows 10、Pro、舊 build、公司管理的電腦）可能不一樣。

## 一、結論先講

1. **MXC 在 Windows 11 Home 上能用，不用管理員。** 檔案隔離、擋外連、只放行到 SYNOX 自己的代理、長駐的 stdio 都成立。（已實測）
2. **`wxc-exec.exe` 能合法取得**：就在官方 npm 套件 `@microsoft/mxc-sdk` 裡，MIT 授權、Microsoft 簽章；單獨一個 12.1 MB 的檔就能跑，**不需要 Node SDK、不需要 node-pty**。（已實測；授權已查證）
3. **MXC 的兩個代價**：(a) Node 與 Python 的 `ssl` 要開「UI（Win32k）」才起得來（剪貼簿、輸入注入可以另外關）；(b) **MXC 會送 4 種「必要」遙測給 Microsoft，關不掉**（官方文件寫的）。
4. **AppContainer 自製這條退路也成立，不用管理員**：檔案隔離 OK；網路只有全斷或全開；**本機 loopback 一律連不到**（所以接不了代理，做不出網域名單）；裝在使用者資料夾的 Python／Node **讀不到**，要複製到有給權限的資料夾才起得來；而且**子程序拿到父程序的整份環境變數**。（已實測）
5. **受限 token＋Job Object 只擋寫入**：讀檔、讀使用者資料夾、連本機 Ollama／SYNOX 都擋不住；`System32\curl.exe` 的 HTTPS 會壞。不能當保護。（已實測）
6. **研究文件說「擁有者的開發機是 Windows 10 Home、MXC 用不了」，跟這台不符**：這台是 Windows 11 Home 25H2，只是註冊表的 `ProductName` 還寫「Windows 10 Home」。原說法很可能是被這個欄位誤導（推測）。

## 二、機器摘要（已實測，`win-env-probe.ps1`）

| 項目 | 值 |
|---|---|
| 版本 | Windows 11 Home（`EditionID=Core`）25H2，build **26200.9974**（≥ MXC 最低的 26200.9278，也 ≥ loopback 伺服器功能的 26200.9550） |
| 註冊表 `ProductName` | 「Windows 10 Home」——已知怪象，看 build 不要看這個 |
| 帳號 | 一般帳號，`IsAdminShell=False`；整個過程沒有跳過 UAC |
| 記憶體／虛擬化 | 31.4 GB；`HypervisorPresent=True` |
| Python | 3.11.0，per-user 安裝在 `C:\Users\<user>\AppData\Local\Programs\Python\Python311\`（不是 Store 別名）。這次全部用這個 `python.exe` 跑 |
| Node | 沒裝。測 P2 用官方免安裝版 `node-v24.22.3-win-x64.zip`（nodejs.org，SHA-256 對過 `SHASUMS256.txt`），放在暫存資料夾 |
| WSL／Docker／Windows Sandbox | 都沒有（Home 版沒有 Windows Sandbox，`synox-research.wsb` 沒跑） |
| 本機服務 | Ollama 在 127.0.0.1:11434、SYNOX 在 127.0.0.1:8830（拿來測 N6／X2，只送 `GET /`） |

## 三、結果表

### 3.1 AppContainer 自製（`win_appcontainer_probe.py`）

profile `synox.research.probe` 由一般帳號建立成功（沒有 `HRESULT` 錯誤），結束時 `DeleteAppContainerProfile` 回 `0x00000000`。跑了兩次（`--no-net` 一次、連網一次），結果相同。

| # | 測什麼 | 預期 | 實際 | 標籤 |
|---|---|---|---|---|
| F1 | 讀有給 ACL 的資料夾 | 允許 | 允許 | 已實測 |
| F2 | 寫有給 ACL 的資料夾 | 允許 | 允許 | 已實測 |
| F3 | 讀沒給 ACL 的資料夾 | 拒絕 | 拒絕 | 已實測 |
| F4 | 寫沒給 ACL 的資料夾 | 拒絕 | 拒絕 | 已實測 |
| F5 | 列出使用者資料夾 | 拒絕 | 拒絕 | 已實測 |
| E1 | 子程序的 `TEMP`／`LOCALAPPDATA` | — | 都被改到 `%LOCALAPPDATA%\Packages\synox.research.probe\AC(\Temp)` | 已實測 |
| E2 | 父程序的環境變數會不會傳進去 | — | **會，整份**（84 個變數，含測試用的標記變數） | 已實測 |
| N1 | 沒給能力，HTTPS 到 example.com | 拒絕 | 拒絕（curl exit 6：連 DNS 都解析不了） | 已實測 |
| N2 | 沒給能力，連本機 127.0.0.1 | 拒絕 | 拒絕（監聽埠 0 次連線） | 已實測 |
| N3 | `internetClient`，HTTPS 到 example.com | 允許 | 允許 | 已實測 |
| N4 | `internetClient`，連本機 | 拒絕 | 拒絕 | 已實測 |
| N5 | `privateNetworkClientServer`，連本機 | 拒絕 | 拒絕 | 已實測 |
| N6 | 三種能力設定下連 Ollama 11434、SYNOX 8830 | 拒絕 | 6 次全部拒絕 | 已實測 |
| P1 | per-user Python 3.11 | 看位置 | **起不來**（「存取被拒。」exit 1） | 已實測 |
| P2 | 暫存資料夾裡的免安裝 Node 24 | 看位置 | **起不來**（「存取被拒。」exit 1） | 已實測 |
| P1b | 把 Python（標準庫，不含 site-packages）複製到有給 ACL 的資料夾 | 允許 | 允許，`import ssl` 也成功 | 已實測 |
| P2b | 把 `node.exe` 複製到有給 ACL 的資料夾 | 允許 | 允許 | 已實測 |

旁證（已實測，`icacls`）：`C:\Program Files` 有 `ALL APPLICATION PACKAGES:(RX)`，per-user 的 Python 資料夾只有 SYSTEM、Administrators、使用者本人——這就是 P1／P2 讀不到的原因。

### 3.2 受限 token＋Job Object（`win_restricted_token_probe.py`，新寫的）

限制 SID＝一個自訂 SID（`S-1-9-1-<亂數>`，只對 `inside` 加 ACE）＋ Everyone ＋登入 SID；Job 設 `KILL_ON_JOB_CLOSE`。

| # | 測什麼 | 預期 | 實際 | 標籤 |
|---|---|---|---|---|
| R1 | 寫有給 ACE 的資料夾 | 允許 | 允許 | 已實測 |
| R2 | 寫沒給的資料夾 | 拒絕 | 拒絕 | 已實測 |
| R3 | 讀沒給的資料夾 | 允許（讀不擋） | 允許 | 已實測 |
| R4 | 列出使用者資料夾 | 允許（讀不擋） | 允許 | 已實測 |
| R5 | 寫使用者 `%TEMP%` 根目錄 | 拒絕 | 拒絕 | 已實測 |
| R6／R7 | 連本機監聽埠、Ollama 11434、SYNOX 8830 | 允許（網路不擋） | 全部連得到 | 已實測 |
| R8 | `System32\curl.exe` 起不起得來（明文 HTTP 到本機） | — | 起得來 | 已實測 |
| R9 | `System32\curl.exe` HTTPS（Schannel） | 研究說會壞 | **壞**（curl exit 35，TLS 握手失敗） | 已實測 |
| J1 | Job 程序數上限＝1，再開子程序 | 拒絕 | 拒絕 | 已實測 |
| J2 | 對照組（不設上限） | 允許 | 允許 | 已實測 |

做的過程中量到的（已實測）：
- 能力 SID（`S-1-15-3-…`）不能當限制 SID：`CreateRestrictedToken` 回 87。
- 限制清單裡**沒有 Everyone**時，`python.exe`、`curl.exe` 一啟動就死（`0xC0000142`，DLL 初始化失敗），`cmd.exe` 卻沒事；加了 Everyone 才正常。
  代價：任何「Everyone 可寫」的地方又變成可寫（這次沒有去列舉這種地方）。
- 寫入受限下 `> NUL` 也會失敗（NUL 裝置的 ACL 只認 Everyone），要另外處理。

### 3.3 MXC ProcessContainer（`win_mxc_probe.py`，新寫的，H4）

`wxc-exec.exe` 1.1.0（`@microsoft/mxc-sdk@1.1.0`，2026-11-14 發佈），`--probe` 回 `"tier": "base-container"`、`baseContainerApiPresent: true`、
`baseContainerSupportsIdentitylessLoopbackProxy: true`、`needsDaclAugmentation: false`。每個容器從建立到結束約 **0.1–0.4 秒**。
跑完 `%LOCALAPPDATA%\Packages` 沒有多出任何資料夾、AppContainer 對應表數量不變、Python 與 Node 資料夾的 ACL 沒被改。

| # | 測什麼 | 預期 | 實際 | 標籤 |
|---|---|---|---|---|
| M0 | 一般帳號能不能用 MXC | — | 能 | 已實測 |
| F1 | 讀 `readonlyPaths` 裡的檔 | 允許 | 允許 | 已實測 |
| F2 | 寫 `readwritePaths` | 允許 | 允許 | 已實測 |
| F2b | 寫 `readonlyPaths` | 拒絕 | 拒絕 | 已實測 |
| F3／F4 | 讀／寫政策外的資料夾 | 拒絕 | 拒絕 | 已實測 |
| F5 | 列出使用者資料夾 | 拒絕 | 拒絕 | 已實測 |
| F6 | 同一個資料夾同時在 `deniedPaths` 與 `readonlyPaths` | 拒絕 | 拒絕（deny 優先） | 已實測 |
| E1 | 預設環境變數 | — | **不繼承父程序**（標記變數沒進去）；是「使用者預設環境」42 個變數，**含使用者層級的環境變數**（例如這台的 `OLLAMA_*`）；`TEMP` 在 `Packages\sandbox.{guid}\AC\Temp`，用完即刪 | 已實測 |
| N1 | 擋外連（`egress.default=deny`），HTTPS 到 example.com | 拒絕 | 拒絕（exit 6，DNS 都不通） | 已實測 |
| N2 | 擋外連，連本機監聽埠 | 拒絕 | 拒絕 | 已實測 |
| N3 | 放外連，HTTPS 到外面 | 允許 | **沒跑**（外部連線的次數已用完，見第七節） | — |
| N4 | 放外連、沒開 `hostLoopback`，連本機 | 拒絕 | 拒絕 | 已實測 |
| N4b | `ingress.hostLoopback=allow`，連本機監聽埠 | 允許 | 允許 | 已實測 |
| N6 | 放外連，連 Ollama 11434／SYNOX 8830 | 拒絕 | 拒絕 | 已實測 |
| N6b | `hostLoopback=allow`，連 11434／8830 | — | **連得到**：一般的 `hostLoopback` 是整個本機都開，不能用 | 已實測 |
| X1 | 代理模式（見下），直連代理的埠 | 允許 | 允許 | 已實測 |
| X2 | 代理模式，直連 11434／8830 | 拒絕 | 拒絕 | 已實測 |
| X3 | 代理模式，直連本機另一個埠 | 拒絕 | 拒絕 | 已實測 |
| X4 | 代理模式，`curl` 連一個主機名（不指定代理） | 走代理 | 走代理（MXC 自動設了 `HTTP(S)_PROXY`） | 已實測 |
| P1 | per-user Python，資料夾不在政策裡 | — | 起不來（`0xC0000135`） | 已實測 |
| P1c | 把 Python 安裝資料夾放進 `readonlyPaths` | 允許 | 允許（不用改 ACL、不用複製） | 已實測 |
| P1d | 同上，但 `import ssl`（UI 預設關） | — | **失敗**：`_ssl` 的 DLL 初始化失敗 | 已實測 |
| P1e | `import ssl`，`ui.disable=false`（剪貼簿 `none`、輸入注入關） | 允許 | 允許 | 已實測 |
| P2 | Node 24，資料夾不在政策裡 | — | 起不來（`0xC0000142`） | 已實測 |
| P2c | Node 資料夾放進 `readonlyPaths`，UI 預設關 | — | **起不來**（`0xC0000142`；wxc-exec 自己的錯誤訊息說要開 UI） | 已實測 |
| P2e | 同上，`ui.disable=false` | 允許 | 允許 | 已實測 |
| S1 | 長駐 stdio：容器裡的 Python 逐行回聲，送 3 行（間隔 2 秒），最後關 stdin | 允許 | 允許：3 行都回來，第一行約 0.1 秒、之後幾乎 0；關 stdin 後正常結束（exit 0），全程 6.2 秒 | 已實測 |

「代理模式」是 MXC 文件叫做 *identityless loopback proxy* 的設定：`runtimeConfig.networkProxy=http://127.0.0.1:<埠>`、
`egress.default=deny`、`ingress.default=allow`、`ingress.hostLoopback=allow`、不設 `allowedProxyPeer`。
少了 `ingress.default=allow` 或 `hostLoopback=allow`，`wxc-exec` 1.1.0 直接拒收這個設定（已實測）。
設了 `allowedProxyPeer`＝`127.0.0.1:<埠>` 的寫法則什麼都連不到（已實測）——文件說這個欄位要填「代理的套件家族名或 AppContainer profile 名」，也就是代理本身要有身分（已查證 [MXN]），這次沒做。

### 3.4 沒跑的

| 項目 | 為什麼 |
|---|---|
| Windows Sandbox（`synox-research.wsb`） | Home 版沒有這個功能；啟用選用功能要管理員，也超出這次的限制 |
| 專用帳號＋WFP | 要建本機帳號、改全機防火牆，**要管理員——沒跑** |
| `CheckNetIsolation LoopbackExempt` | 要管理員——沒跑 |
| MXC 的 IsolationSession／WSLC／MicroVM 後端 | 不在範圍；WSL 沒裝；`--probe` 說 `isolationSessionAvailable: true`，但沒試 |
| MXC 的 `allowedProxyPeer`（代理有身分的正式模式） | 要先把代理放進 AppContainer 或打包，這次沒做 |
| MXC 放外連（N3） | 外部連線次數已用完 |

## 四、H3：MXC 的三個問題

| 問題 | 答案 | 標籤與來源 |
|---|---|---|
| Home 版能不能用？ | **這台 Windows 11 Home 25H2（26200.9974）能用**，一般帳號、不用管理員 | **已實測**。官方文件**查不到**版別的說法：找過 [MXC README][MX1]、[os-version-support.md][MX2]（只列 build：24H2 `26100.9278`、25H2 `26200.9278`、26H2 `26300.9550`、26H1 `28000.2804`）、[networking.md][MXN]、[telemetry.md][MXT]、[Windows 部落格 2026-10-07 GA 文][MXB]（沒有版別、沒有 build）、learn.microsoft.com 搜尋（沒有 MXC 的頁面） |
| Windows 10？ | 版本支援頁只列 Windows 11 | **已查證** [MX2]；沒實測（沒有 Windows 10 機器） |
| `wxc-exec.exe` 怎麼合法取得？ | 在 npm 套件 `@microsoft/mxc-sdk` 的 `bin\x64\`（與 `bin\arm64\`）裡。README 寫「The Node and .NET packages include the native runtime assets」；GitHub Releases 是空的 | **已查證** [MX1]。**已實測**：1.1.0 的 tarball sha512 與 registry 的 `integrity` 相符；`wxc-exec.exe`、`mxc_ffi.dll` 的 Authenticode 是 `Valid`、簽署者 Microsoft Corporation；只複製 `wxc-exec.exe` 一個檔到別的資料夾也能跑完整組測試 |
| 能不能再散布？ | 套件內的 `LICENSE.md` 是 MIT（Copyright Microsoft Corporation），允許再散布，條件是附上著作權與授權聲明 | **已查證**（套件內 `LICENSE.md`、[MX1] 標 MIT）。套件裡沒有另外的 EULA 或「redistributable」條款——**推測**沒有額外限制，但正式散布前建議擁有者自己讀一次 |
| 長駐 stdio 行不行？ | **用 `wxc-exec.exe` 直接跑：行**（S1） | **已實測**。文件：README「Native executors normally reserve standard input, output, and error for the workload」（**已查證** [MX1]）。注意：Node SDK 的 README 說 `spawn()` 只有 WSLC 後端的 stdin 可寫（**已查證**，套件內 README）——所以**用 Node SDK 可能反而不行**，SYNOX 直接驅動 `wxc-exec.exe` 才行（推測，沒用 SDK 驗證） |
| 遙測 | `MXC.ExecutionStart`、`ExecutionEnd`、`Error`、`ProcessExited` 四種「必要」事件，在支援的 build 上不論 `telemetry.enabled`、同意與否、管理原則都會收；不受 MXC 設定或登錄機碼控制。傳輸方式文件沒寫 | **已查證** [MXT] 與套件內 README。實際送了什麼、走哪條路：**沒驗證** |

## 五、對 ADR 0022 決定 11–14 的意義

以下是**建議**，不是決定；決定權在擁有者。只根據這一台的結果。

| 決定 | 這次的結果代表什麼 | 建議 |
|---|---|---|
| **13 Windows 主路線** | MXC 在 Windows 11 Home 上把 ADR 想要的都做到了：檔案政策、預設擋外連、**只放行到 SYNOX 自己代理的埠**（Ollama、SYNOX 本身碰不到）、長駐 stdio、per-user 直譯器用 `readonlyPaths` 就讀得到、不用管理員、每次啟動約 0.1 秒。ADR 擔心的「沒有 Python SDK」「Node SDK 要 node-pty」都可以繞開：**SYNOX 用 Python 的 `subprocess` 直接驅動 `wxc-exec.exe`**（JSON 設定用 `--config-base64` 傳） | **建議：MXC 為主路線，以 `wxc-exec.exe` 驅動，不用 Node SDK。** 要寫進設計的代價：(1) 跑 Node／用到 Python `ssl` 的工具要開 UI（`ui.disable=false`，剪貼簿 `none`、輸入注入關），工具因此能在桌面開視窗；(2) 代理模式這次用的是文件標「主要給開發與除錯」的 identityless 模式，正式版要評估做有身分的代理（`allowedProxyPeer`）；(3) **必要遙測關不掉**，要在隱私說明裡寫清楚——這可能需要擁有者另外決定；(4) `wxc-exec.exe` 12 MB、MIT，要決定是隨 SYNOX 出貨還是第一次需要時下載（比照決定 8 的 Node）；(5) MXC 的預設環境含使用者層級的環境變數，SYNOX 要自己給 `process.env` 白名單（決定 16） |
| **退路：AppContainer 自製** | 一般帳號能建 profile；檔案隔離成立；網路全斷或全開；loopback 全擋（所以**沒有網域名單**，也碰不到 Ollama／SYNOX）；per-user 直譯器讀不到，要複製到有 ACL 的資料夾（或對 SYNOX 自己管的 Node／Python 資料夾加 ACE）；**整份環境變數會傳進去** | **建議維持「基本」等級**（檔案隔離＋全斷或全開）。實作時必須：自己組環境變數區塊、把直譯器放在 SYNOX 管的資料夾並加 ACE、Node 不需要開 UI（P2b 直接起得來） |
| **11 Windows 10 的支援等級** | MXC 文件只列 Windows 11；AppContainer API 在 Windows 8 起就有 | **建議不變：「基本」（AppContainer）。** 但這次**沒有在 Windows 10 上驗證**，要另一台機器 |
| **12 接不接受一次 UAC** | MXC 與 AppContainer 兩條都不需要管理員就做到了檔案隔離；MXC 連網域名單也不用 | **建議：預設不要求**；專用帳號＋WFP 的「加強保護」優先度可以往後放（Windows 11 已經有 MXC） |
| **14 先測再定** | 一台 Windows 11 Home 的實測已完成 | **建議**：主路線可以先定 MXC；退路的細節等 Windows 10 與 Windows 11 Pro 的結果。受限 token＋Job Object 不列為保護（只擋寫入） |

另外兩件要更正或補充的：
- 研究 4.4 與 ADR 6.3 說「擁有者自己的開發機是 Windows 10 Home、MXC 用不了」，**這台實際上是 Windows 11 Home 25H2，MXC 可以用**。
- 研究說 AppContainer 的 Python／Node「推測讀不到」：**已實測讀不到**；MXC 則可以透過政策讀到，不用改 ACL。

## 六、還要別台機器才能回答的

| 要什麼機器 | 要回答什麼 |
|---|---|
| **Windows 10**（Home 或 Pro，22H2） | AppContainer 腳本在 Windows 10 上跑不跑得完、結果是否一樣；確認 `wxc-exec --probe` 在 Windows 10 回什麼（預期不支援） |
| **Windows 11 Pro** | MXC 與 AppContainer 結果是否跟 Home 一樣；`synox-research.wsb`（Windows Sandbox）能不能開、要不要管理員 |
| **Windows 11，build 低於 MXC 基準**（例如 26100.9278 之前） | `wxc-exec --probe` 怎麼回報不支援——SYNOX 要靠這個決定退到 AppContainer |
| **Windows 11，build 在 .9278 與 .9550 之間** | 代理模式（X1–X4）在 loopback 伺服器功能出現之前能不能用 |
| **公司管理的電腦**（Intune／群組原則） | MXC 會不會被原則擋；遙測原則的影響 |
| **ARM64** | `bin\arm64\wxc-exec.exe` |

## 七、怎麼重現

一般（非管理員）PowerShell，在一個 repo 以外的空資料夾（這次用的是 Claude 的暫存資料夾，下面以 `C:\synox-probe` 代替）：

```
mkdir C:\synox-probe & cd C:\synox-probe
copy <repo>\docs\lab\tools\windows-sandbox-probe\*.* .
set PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe

:: 1. 盤點
powershell -NoProfile -ExecutionPolicy Bypass -File .\win-env-probe.ps1

:: 2. 免安裝 Node（只放在這個資料夾，不加 PATH）
curl.exe -sSfL -o SHASUMS256.txt https://nodejs.org/dist/latest-v24.x/SHASUMS256.txt
curl.exe -sSfL -o node.zip https://nodejs.org/dist/latest-v24.x/node-v24.22.3-win-x64.zip
certutil -hashfile node.zip SHA256          &:: 跟 SHASUMS256.txt 裡 node-v24.22.3-win-x64.zip 那一行比
tar -xf node.zip
set NODE=C:\synox-probe\node-v24.22.3-win-x64\node.exe

:: 3. AppContainer（--no-net 一次、連網一次）
%PY% -I win_appcontainer_probe.py --no-net --node %NODE% --copy-interpreters --ports 11434,8830
%PY% -I win_appcontainer_probe.py --node %NODE% --copy-interpreters --ports 11434,8830

:: 4. 受限 token＋Job Object
%PY% -I win_restricted_token_probe.py

:: 5. MXC：wxc-exec.exe 的取得與驗證見 tools\windows-sandbox-probe\README.md「MXC 的 wxc-exec.exe 怎麼拿」
%PY% -I win_mxc_probe.py --wxc C:\synox-probe\mxc\package\bin\x64\wxc-exec.exe --node %NODE% --ports 11434,8830 --net
```

這次連到外部網站的次數：AppContainer N3 一次、受限 token R9 一次（都是 `https://example.com`）；AppContainer N1 與 MXC N1 在 DNS 就失敗，沒有連出去。
另外下載了：Node 的 `SHASUMS256.txt` 與 zip（nodejs.org）、`@microsoft/mxc-sdk` 的 metadata 與 tarball（registry.npmjs.org）、MXC 的設定 schema（raw.githubusercontent.com），都只放在暫存資料夾。

清理（已實測）：`synox.research.probe` profile 已刪（`%LOCALAPPDATA%\Packages\synox.research.probe` 不在、對應表沒有 `synox`／`sandbox.` 開頭的項目）；
`%TEMP%\synox-research-*` 都不在；MXC 每個容器的 `Packages\sandbox.{guid}` 都由 MXC 自己刪掉；沒有留下監聽埠或程序；暫存資料夾整個刪掉。

## 八、這次沒有驗證的

- 只有**一台** Windows 11 Home；Windows 10、Pro、舊 build、ARM64、公司管理的電腦都沒測。
- MXC 的**正式代理模式**（`allowedProxyPeer`＋有身分的代理）沒做；identityless 模式在文件上是「主要給開發與除錯」，而且文件記載某個 build 上有已知限制。
- MXC 的 UI 開了之後，工具能做什麼（開視窗、剪貼簿是否真的擋住、輸入注入是否真的擋住）沒測。
- MXC 的遙測實際送了什麼、走哪條路沒驗證；只讀了文件。
- MXC 放外連（N3）、IPv6、UDP、DNS 外洩沒測。
- `--copy-interpreters` 只複製了標準庫；有第三方套件（site-packages）、有原生模組的工具沒測。
- 受限 token：「Everyone 可寫」的地方有哪些沒有列舉；沒有在 Job 裡測記憶體上限。
- 長駐 stdio 只測了 3 行、6 秒；沒有測幾小時、大量資料、子程序再開子程序、被強制結束時的清理。
- `wxc-exec.exe` 的 `--config-base64` 參數長度上限、Windows 命令列長度（32K）對大型政策的影響沒測。
- 沒有用 Node SDK（`@microsoft/mxc-sdk` 的 JavaScript 部分）跑過任何東西。

## 來源

| 代號 | 網址 | 讀了什麼 |
|---|---|---|
| MX1 | https://github.com/microsoft/mxc | README（2026-11-16 再讀）：SDK 套件名、「Node and .NET packages include the native runtime assets」、Releases 是空的、stdio 那句 |
| MX2 | https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/os-version-support.md | build 表；沒有版別、沒有 Windows 10 |
| MXN | https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/networking.md | `networkProxy`、`allowedProxyPeer`、identityless loopback proxy、需要的 build |
| MXT | https://github.com/microsoft/mxc/blob/main/docs/telemetry.md | 四種必要事件、關不掉 |
| MXS | https://raw.githubusercontent.com/microsoft/mxc/main/schemas/stable/mxc-config.schema.1.0.0.json | 設定格式 1.0.0 |
| MXB | https://blogs.windows.com/windows/2026/10/07/microsoft-execution-containers-policy-driven-containment-for-ai-agents/ | GA 公告；沒有版別、build、授權、遙測的說法 |
| MX5 | https://registry.npmjs.org/@microsoft%2fmxc-sdk | 1.1.0（2026-11-14）、MIT、`engines.node >=24`、相依 `koffi`、`semver`、`node-pty`、`integrity` |
| ND1 | https://nodejs.org/dist/latest-v24.x/SHASUMS256.txt | Node 24.22.3 的 SHA-256 |

[MX1]: https://github.com/microsoft/mxc
[MX2]: https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/os-version-support.md
[MXN]: https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/networking.md
[MXT]: https://github.com/microsoft/mxc/blob/main/docs/telemetry.md
[MXB]: https://blogs.windows.com/windows/2026/10/07/microsoft-execution-containers-policy-driven-containment-for-ai-agents/
