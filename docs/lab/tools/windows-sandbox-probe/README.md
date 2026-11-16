# Windows 沙盒探測腳本（第 3 階段研究的附件）

> **2026-11-16 第一次在真的 Windows 上跑**（Windows 11 Home 25H2，build 26200.9974，一般帳號，Python 3.11）。跑的時候遇到的 bug 已經修掉（見「跟研究原稿的差別」），
> 也加了兩個新腳本（受限 token＋Job Object、MXC）。結果在 [2026-11-16 實測結果](../../2026-11-16-windows-sandbox-probe-results.md)。
> **Windows 10、Windows 11 Pro 還沒有人跑過**；腳本本身出錯＝腳本的 bug，不是研究發現，請把錯誤訊息原樣帶回來。

- 日期：2026-11-13
- 用途：回答 [研究文件](../../2026-11-13-ecosystem-security-research.md) 主題 4 裡標「待實測」的項目，讓擁有者決定 Windows 沙盒走哪一條路（[ADR 0022](../../../adr/0022-ecosystem-bridge-and-sandbox.md) 的決定 11–14）。
- 對象：SYNOX 的擁有者，以及**願意幫忙的志願者**（任何 Windows 10／11 電腦都有用：Home、Pro、沒更新的都是有價值的資料點）。為什麼需要、要回報什麼、怎麼分享，見 [docs/sandbox-roadmap.md](../../../sandbox-roadmap.md)。

## 各個檔做什麼

| 檔案 | 做什麼 | 會動到什麼 | 要管理員嗎 |
|---|---|---|---|
| `win-env-probe.ps1` | **只讀**盤點：Windows 版本與 build、是不是 Home 版、記憶體、虛擬化有沒有開、node／npm／python／docker／wsl 裝在哪、Windows Sandbox 開了沒、build 夠不夠用 MXC | 只在腳本旁邊寫一個 `win-env-probe-result.json`。不安裝、不改設定、不連網 | 不用 |
| `win_appcontainer_probe.py` | 用 ctypes 建一個暫時的 AppContainer，在裡面跑 `cmd.exe`／`curl.exe`／Python／Node，做 11 項測試（下表） | 建 `%TEMP%\synox-research-<亂數>\`、一個名為 `synox.research.probe` 的 AppContainer profile、一個 127.0.0.1 的監聽埠；最多 2 次連 `example.com`；只對暫存資料夾跑 `icacls`。結束時全部刪掉。腳本旁邊寫一個 `win_appcontainer_probe_result.json` | 不用（這一點本身也是待實測的假設） |
| `win_restricted_token_probe.py` | （2026-11-16 新增）不用 AppContainer：只用「寫入受限的 token＋Job Object」跑 `cmd.exe`／`curl.exe`／Python，量寫入、讀取、網路、程序數上限（R1–R9、J1–J2） | 建 `%TEMP%\synox-research-rt-<亂數>\`；用 PowerShell `Set-Acl` 只對暫存資料夾加一條 ACE；一個 127.0.0.1 監聽埠；最多 1 次連 `example.com`（`--no-net` 就不連）。結束時刪掉 | 不用 |
| `win_mxc_probe.py` | （2026-11-16 新增）用 MXC 的 `wxc-exec.exe` 跑同一組項目（F1–F6、N1–N6、P1／P2）＋本機代理模式（X1–X4）＋長駐 stdio 往返（S1） | 建 `%TEMP%\synox-research-mxc-<亂數>\`；每次測試由 MXC 建一個用完即刪的容器；一個 127.0.0.1 監聽埠；`--net` 才會試連 `example.com` 一次（在「擋外連」設定下，預期連不到）。**MXC 會送 4 種「必要」遙測事件給 Microsoft，關不掉**（見下） | 不用 |
| `synox-research.wsb` | 開一個**關網路**、唯讀掛一個資料夾的 Windows Sandbox（選做） | 開一個用完即丟的桌面；關掉視窗後裡面的東西都不見 | 啟用「Windows 沙箱」功能那一次推測要（待查） |

`win_appcontainer_probe.py`、`win_restricted_token_probe.py`、`win_mxc_probe.py` **不讀你的文件**：「列出使用者資料夾」那一項只記成功或失敗，輸出丟掉。
三個 Python 腳本寫結果檔時會把路徑裡的 Windows 帳號名換成 `<user>`（`win-env-probe.ps1` 不會，貼出去前請自己換）。

## 怎麼安全地跑

1. **不要在 SYNOX 的資料夾裡跑。** 開一個空的暫存資料夾（例如 `C:\synox-probe\`），把這三個檔複製進去。結果檔會寫在腳本旁邊，放在暫存資料夾才不會混進 repo。
2. 用**一般的**（不是系統管理員的）PowerShell：

   ```
   cd C:\synox-probe
   powershell -ExecutionPolicy Bypass -File .\win-env-probe.ps1
   python win_appcontainer_probe.py
   ```

   不想讓它連外面的網站：`python win_appcontainer_probe.py --no-net`（跳過 N1、N3 兩項）。
   選用參數（2026-11-16 加）：`--node <node.exe 的路徑>`（node 不在 PATH 時用，例如免安裝版）、`--copy-interpreters`（把 Python 標準庫與 node.exe 複製到「有給權限的資料夾」再跑一次，P1b／P2b）、
   `--ports 11434,8830`（這兩個埠上已經有服務在聽的話——Ollama、SYNOX——從裡面各送一次 `GET /`，只記成敗，N6）。
   受限 token：`python win_restricted_token_probe.py`（`--no-net` 跳過 R9）。
   MXC：先照下面「MXC 的 `wxc-exec.exe` 怎麼拿」取得執行檔，再 `python win_mxc_probe.py --wxc <路徑>\wxc-exec.exe [--node <node.exe>] [--ports 11434,8830] [--net]`。
3. （選做，只有 Windows 11 Pro／Enterprise／Education，而且已經啟用「Windows 沙箱」）先建 `C:\synox-research-wsb\`、放一個無害的文字檔進去，再點兩下 `synox-research.wsb`。
4. 跑完把兩個 `*-result.json` 帶回來。`win-env-probe-result.json` 裡只有 node／python／docker 的安裝路徑，沒有使用者名稱以外的個人資料；**路徑裡會有你的 Windows 帳號名，貼出去前先看一眼**。
   **志願者**：結果請貼到 GitHub Discussions 的沙盒討論串（或開 issue），貼之前把路徑裡的 Windows 帳號名換成 `<user>`；JSON 以外再附上 Windows 版本（`winver` 視窗上那一行）與腳本印出的表格。如果你覺得你發現的是 SYNOX 的**安全漏洞**（不是探測結果），請照 `SECURITY.md` 私下寄信，不要貼在公開的地方。
5. 清理：刪掉 `C:\synox-probe\`（與 `C:\synox-research-wsb\`）。AppContainer profile 與暫存資料夾由腳本在結束時刪掉（寫在 `finally` 裡）。如果腳本是被強制關掉的：`%TEMP%\synox-research-*` 資料夾請手動刪；profile 再跑一次腳本就會沿用並在結束時刪掉（腳本認得「已經存在」）。

## MXC 的 `wxc-exec.exe` 怎麼拿（2026-11-16 實測）

`wxc-exec.exe` 就在官方 npm 套件 `@microsoft/mxc-sdk` 裡（`package\bin\x64\`），MIT 授權，有 Microsoft 的 Authenticode 簽章。**不用裝 npm**，也不跑任何安裝腳本：

```
mkdir C:\synox-probe\mxc & cd C:\synox-probe\mxc
curl.exe -sSfL -o meta.json https://registry.npmjs.org/@microsoft%2fmxc-sdk
:: 看 meta.json 裡 dist-tags.latest 的版本，與該版本 dist.integrity（sha512-…）
curl.exe -sSfL -o mxc-sdk.tgz https://registry.npmjs.org/@microsoft/mxc-sdk/-/mxc-sdk-1.1.0.tgz
:: 驗證（印出來要跟 integrity 一字不差）：
python -I -c "import hashlib,base64;print('sha512-'+base64.b64encode(hashlib.sha512(open('mxc-sdk.tgz','rb').read()).digest()).decode())"
tar -xzf mxc-sdk.tgz
powershell -c "Get-AuthenticodeSignature package\bin\x64\wxc-exec.exe | fl Status,SignerCertificate"
package\bin\x64\wxc-exec.exe --probe
```

`--probe` 印出 `"tier": "base-container"`、`"baseContainerApiPresent": true` 就代表這台的 MXC ProcessContainer 可以用。
**遙測**：MXC 的文件寫明，在支援的 Windows build 上，`MXC.ExecutionStart`／`ExecutionEnd`／`Error`／`ProcessExited` 四種「必要」事件**不論設定、同意與否都會收**（[telemetry.md](https://github.com/microsoft/mxc/blob/main/docs/telemetry.md)）。跑 `win_mxc_probe.py` 之前請知道這一點。

## 結果怎麼讀

### `win-env-probe.ps1`

| 欄位 | 值 | 代表什麼 |
|---|---|---|
| `EditionID` | `Core` | Home 版：Windows Sandbox 用不了；MXC 能不能用**查不到**，要另外試 |
| `IsWindows11` | `False` | Windows 10：MXC 用不了，只剩「AppContainer 自製」或「專用帳號＋防火牆（要按一次 UAC）」 |
| `MXC_process_isolation_build_ok` | `True` | build 達到 MXC 的最低要求（24H2 `26100.9278`、25H2 `26200.9278`…），可以進下一輪的 MXC 實測 |
| `path_node`、`node_under_program_files` | 沒有 node／不在 Program Files | 沒有 node＝現在的 SYNOX 裝不了要 Node 的工具；不在 Program Files＝沙盒裡的程式推測讀不到它 |
| `python_is_store_alias` | `True` | `python` 是 Microsoft Store 的別名：`win_appcontainer_probe.py` 的 P1 可能失敗，請改用真的 python.exe 的完整路徑跑 |
| `HypervisorPresent`、`SLAT`、`path_wsl`、`DockerDesktop_*` | — | 容器這條路（Docker Desktop／WSL 2）走不走得通 |

### `win_appcontainer_probe.py`

每一行是 `<編號> <PASS／FAIL／INFO> expect=<預期> exit=<結束碼> <說明>`。**「預期」是文件上的說法，還沒有人量過**；跟預期不同就是有用的發現，請原樣帶回來。

| 編號 | 測什麼 | 預期 | 跟預期一樣代表什麼 | 跟預期不同代表什麼 |
|---|---|---|---|---|
| F1 | 讀「有給權限的資料夾」裡的檔 | 允許 | 用 ACL 開放單一資料夾可行 | 連開放都做不到：AppContainer 自製這條路要重新評估 |
| F2 | 寫「有給權限的資料夾」 | 允許 | 同上 | 同上 |
| F3 | 讀「沒給權限的資料夾」裡的檔 | 拒絕 | 檔案隔離成立 | **隔離不成立**：這條路不能當保護 |
| F4 | 寫「沒給權限的資料夾」 | 拒絕 | 同上 | 同上 |
| F5 | 列出使用者資料夾（只記成敗） | 拒絕 | 技能讀不到你的文件 | **讀得到**：這條路不能當保護 |
| N1 | 沒給網路能力時連 `example.com` | 拒絕 | 「預設斷網」成立 | 斷不了網 |
| N2 | 沒給網路能力時連本機 127.0.0.1 | 拒絕 | 技能碰不到 SYNOX（8830）與 Ollama（11434） | 碰得到：要另外處理 |
| N3 | 給了 `internetClient` 後連 `example.com` | 允許 | 「全開網」成立（沒有網域白名單） | 連全開都開不了 |
| N4 | 給了 `internetClient` 後連本機 127.0.0.1 | 拒絕 | 開了網路的技能仍碰不到本機服務；但也代表**接不到本機的白名單 proxy**，這條路做不出網域白名單 | 連得到本機：可以接 proxy，但也碰得到 Ollama／SYNOX，要限制埠 |
| P1 | Python 能不能在 AppContainer 裡啟動 | 看安裝位置 | exit 0＝可以直接用現在的 Python | 非 0＝SYNOX 要自己帶一份直譯器或補 ACL |
| P2 | Node 能不能在 AppContainer 裡啟動 | 看安裝位置 | 同上 | 同上（跟「Node 由誰提供」的決定一起看） |

另外看有沒有 `CreateAppContainerProfile/Derive failed: HRESULT 0x…` 這個錯誤：有＝一般使用者建不了 AppContainer，這條路就需要管理員（請把那個 HRESULT 帶回來）。

### `synox-research.wsb`

預期：開出一個桌面、桌面上看得到唯讀的 `synox-research-wsb` 資料夾、`ping 1.1.1.1` 失敗（沒有網路）、關掉視窗後什麼都不留。請記下**從點兩下到桌面出現花了幾秒**。

## 跟研究階段原稿的差別

- `win-env-probe.ps1`：開頭加了 UTF-8 BOM（repo 規則：`.ps1` 一律 UTF-8 有 BOM＋CRLF）。內容是純 ASCII，沒有改任何一行。
- `synox-research.wsb`：登入指令最後的 `dir` 從寫死的沙箱帳號桌面路徑改成 `%USERPROFILE%\Desktop`（同一個資料夾；repo 的公開前檢查不收寫死的使用者資料夾路徑）。
- `win_appcontainer_probe.py`：研究階段一個位元組都沒改。

### 2026-11-16：第一次真機執行後的修正（H2）

- `win-env-probe.ps1`：沒裝 WSL 時 `wsl --version` 什麼都不印、結束碼 1，`wsl_version` 變成空陣列（畫面上印 `System.Object[]`）→ 改成去掉 NUL、取第一個非空行，沒有就寫 `none (wsl --version exit N; …)`。
  新增 `ProductName_registry`（註冊表在很多 Windows 11 上仍寫「Windows 10 …」，看 build 不要看這個）；`SLAT` 加註「有 hypervisor 時也會讀成 False」。
- `win_appcontainer_probe.py`：
  - **結果檔寫不出來**：`sys.getwindowsversion()` 是 structseq，沒有 `_asdict()`，表格印完後在寫 JSON 時當掉 → 改成逐欄取值。
  - E1 誤報「LOCALAPPDATA 未定義」：`cmd` 的 `set NAME >file` 會去找名字是「NAME 加空白」的變數 → 拿掉 `>` 前的空白。
  - 結果檔的路徑會帶 Windows 帳號名 → 寫檔時換成 `<user>`。`note` 欄位改成同時保留錯誤與補充說明。
  - 新增：E2（父程序的環境變數有沒有傳進去，只記變數**名稱**）、N5（`privateNetworkClientServer` 能力連本機）、N6（`--ports`：連已在聽的 Ollama／SYNOX）、
    P1／P2 記下子程序印出的第一行（看得到「存取被拒」）、P1 改成 `import ssl`、`--node`、`--copy-interpreters`（P1b／P2b）。
- 新增 `win_restricted_token_probe.py`、`win_mxc_probe.py`（說明見上表）。寫的過程中量到的細節記在腳本註解裡：
  受限 token 的限制 SID 不能是能力 SID（`S-1-15-3-…`，`CreateRestrictedToken` 回 87）、`icacls` 不收解析不出名字的 SID（rc 1332）、
  沒有 Everyone 在限制清單裡時 python.exe／curl.exe 啟動就死（0xC0000142）、`> NUL` 在寫入受限 token 下會失敗；
  MXC 的 `networkProxy` 必須同時設 `ingress.default=allow` 與 `hostLoopback=allow`（或 `allowedProxyPeer`），node.exe 與 Python 的 `_ssl` 要 `ui.disable=false` 才起得來。
- `synox-research.wsb`：沒有改（這台是 Home 版，沒有 Windows Sandbox，沒跑）。

## 還沒有腳本的

| 項目 | 為什麼還沒有 |
|---|---|
| 專用帳號＋防火牆過濾 | 會建一個本機帳號、改全機的防火牆過濾，要擁有者先同意才寫 |
| Docker Desktop | 照既有的 [container-verification.md](../../../handoff/container-verification.md) |
