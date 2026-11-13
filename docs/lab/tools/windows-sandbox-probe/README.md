# Windows 沙盒探測腳本（第 3 階段研究的附件）

> **這三個檔從來沒有在 Windows 上跑過。** 它們是在 Linux 上寫的；Python 檔只做過語法檢查（`py_compile` 通過，在 Linux 上執行會印「只能在 Windows 跑」後結束）。
> 腳本本身出錯＝腳本的 bug，不是研究發現；請把錯誤訊息原樣帶回來。

- 日期：2026-11-13
- 用途：回答 [研究文件](../../2026-11-13-ecosystem-security-research.md) 主題 4 裡標「待實測」的項目，讓擁有者決定 Windows 沙盒走哪一條路（[ADR 0022](../../../adr/0022-ecosystem-bridge-and-sandbox.md) 的決定 11–14）。
- 對象：SYNOX 的擁有者（在自己的 Windows 11 電腦上跑）。

## 三個檔各做什麼

| 檔案 | 做什麼 | 會動到什麼 | 要管理員嗎 |
|---|---|---|---|
| `win-env-probe.ps1` | **只讀**盤點：Windows 版本與 build、是不是 Home 版、記憶體、虛擬化有沒有開、node／npm／python／docker／wsl 裝在哪、Windows Sandbox 開了沒、build 夠不夠用 MXC | 只在腳本旁邊寫一個 `win-env-probe-result.json`。不安裝、不改設定、不連網 | 不用 |
| `win_appcontainer_probe.py` | 用 ctypes 建一個暫時的 AppContainer，在裡面跑 `cmd.exe`／`curl.exe`／Python／Node，做 11 項測試（下表） | 建 `%TEMP%\synox-research-<亂數>\`、一個名為 `synox.research.probe` 的 AppContainer profile、一個 127.0.0.1 的監聽埠；最多 2 次連 `example.com`；只對暫存資料夾跑 `icacls`。結束時全部刪掉。腳本旁邊寫一個 `win_appcontainer_probe_result.json` | 不用（這一點本身也是待實測的假設） |
| `synox-research.wsb` | 開一個**關網路**、唯讀掛一個資料夾的 Windows Sandbox（選做） | 開一個用完即丟的桌面；關掉視窗後裡面的東西都不見 | 啟用「Windows 沙箱」功能那一次推測要（待查） |

`win_appcontainer_probe.py` **不讀你的文件**：「列出使用者資料夾」那一項只記成功或失敗，輸出丟掉。

## 怎麼安全地跑

1. **不要在 SYNOX 的資料夾裡跑。** 開一個空的暫存資料夾（例如 `C:\synox-probe\`），把這三個檔複製進去。結果檔會寫在腳本旁邊，放在暫存資料夾才不會混進 repo。
2. 用**一般的**（不是系統管理員的）PowerShell：

   ```
   cd C:\synox-probe
   powershell -ExecutionPolicy Bypass -File .\win-env-probe.ps1
   python win_appcontainer_probe.py
   ```

   不想讓它連外面的網站：`python win_appcontainer_probe.py --no-net`（跳過 N1、N3 兩項）。
3. （選做，只有 Windows 11 Pro／Enterprise／Education，而且已經啟用「Windows 沙箱」）先建 `C:\synox-research-wsb\`、放一個無害的文字檔進去，再點兩下 `synox-research.wsb`。
4. 跑完把兩個 `*-result.json` 帶回來。`win-env-probe-result.json` 裡只有 node／python／docker 的安裝路徑，沒有使用者名稱以外的個人資料；**路徑裡會有你的 Windows 帳號名，貼出去前先看一眼**。
5. 清理：刪掉 `C:\synox-probe\`（與 `C:\synox-research-wsb\`）。AppContainer profile 與暫存資料夾由腳本在結束時刪掉（寫在 `finally` 裡）。如果腳本是被強制關掉的：`%TEMP%\synox-research-*` 資料夾請手動刪；profile 再跑一次腳本就會沿用並在結束時刪掉（腳本認得「已經存在」）。

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
- `win_appcontainer_probe.py`：一個位元組都沒改。

## 還沒有腳本的

| 項目 | 為什麼還沒有 |
|---|---|
| MXC（Windows 11 內建的程序級容器） | `wxc-exec.exe` 怎麼取得還沒查到（官方 README 只說「用套件管理員裝 SDK」，SDK 只有 Rust／.NET／Node） |
| 專用帳號＋防火牆過濾 | 會建一個本機帳號、改全機的防火牆過濾，要擁有者先同意才寫 |
| Docker Desktop | 照既有的 [container-verification.md](../../../handoff/container-verification.md) |
