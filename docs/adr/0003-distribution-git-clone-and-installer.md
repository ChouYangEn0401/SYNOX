# ADR 0003：發佈方式（git clone＋安裝程式）、工具庫放哪裡、乾淨安裝（沒有 hidden dependency）

- 日期：2026-11-12
- 狀態：已採用設計（分支 `feat/clean-room-dist`）。**安裝程式沒有實際打包過、也還沒在空白電腦上跑過**——實測清單：
  [../handoff/clean-machine-test.md](../handoff/clean-machine-test.md)
- 回答：[QuestionToUser.md](../../QuestionToUser.md) QL4；留給擁有者的：QD1～QD4

（編號說明：0002 已經被 `feat/core-remind-soul` 用掉，所以這份是 0003。）

## 擁有者原話（一字不改）

> QL4. 我個人的其實還是偏好 (1) git clone (2) released exe installer 這幾種。然後都會引導使用者 init 的時候架設好需要的參數與環境。我們要完全模擬使用者在空白點腦的狀況，所以不可以也有 hidden dependency 或者我這台的路徑架構。就是要讓大家"裝synox"，裝套件套 synox core 裡面的地方。然後要讓他可以 work。當然我會在別台機器測試，但我會覺得不標要先定好 !!

> 我現在就是希望把所有這邊的工具都做統一管理。所以理論上只會剩下：我電腦的原始專案(現在仍會透過 telegram-bot 服務我)，然後就是 synox_lix 裡面的工具 duplication(會做成 public 版本去掉我的隱私項目，提供給別人)

（synox_lix＝SYNOX_Libs。）

## 結論

| 問題 | 決定 |
|---|---|
| 怎麼發 | 兩條：**(A) git clone**（或 GitHub 的 Download ZIP）＋`Setup.bat`；**(B) 安裝程式** `SYNOX-Setup-<版本>.exe` |
| 安裝程式用什麼做 | **Inno Setup 6＋官方可攜版 CPython（embeddable）＋離線套件（wheelhouse）**；不用 PyInstaller／Nuitka（理由見 B） |
| 參數在哪裡設 | 安裝最後一步一律進「設定引導」：有視窗用原本的精靈（tkinter），沒有視窗就用文字版 `python -m synox init`。兩個寫同一份 `config.json` |
| 工具庫（QL4 原題） | 發佈物旁邊附 `tools/`（SYNOX_Libs 打包好的 `.synoxpack`＋`index.json`）；`packs.library` 沒寫時就找 `<SYNOX>/tools`（**相對於 SYNOX 資料夾**）；init 列出來、**使用者自己挑**，不自動全裝 |
| hidden dependency | 路徑一律相對於 SYNOX 資料夾或可設定；「剛好在旁邊的兄弟資料夾」只能當有標記的後備；`scripts/clean_room_check.py` 在這台模擬；真的空白電腦由擁有者實測 |

## A. git clone 路徑：clone 之後怎麼一路到可用

**需要什麼**：Windows 10／11 64 位元、能上網（裝 Python 與套件時）。Python 不用先裝：`Setup.bat` 會找，找不到就裝。
git 也不是必要的：沒有 git 的人用 GitHub 的「Code → Download ZIP」解開，效果一樣。

1. `git clone <SYNOX repo>`（或解開 zip）到任何資料夾，路徑可以有中文、空白。
2. 雙擊 `Setup.bat` → `setup/bootstrap.ps1`：
   1. **Python ≥ 3.11**：SYNOX 資料夾裡的 `runtime\python`（安裝程式附的）→ `py` 啟動器 → PATH 上的 `python` →
      `%LOCALAPPDATA%\Programs\Python\Python31x` → `winget install Python.Python.3.12` → 最後退路：python.org 的可攜版解到 `runtime\python`。
   2. 建 `.venv`。
   3. **裝相依**（由嚴到寬）：有 `wheelhouse\` → 完全離線（`--no-index --find-links wheelhouse`）；有 `requirements.lock` →
      照鎖定的版本裝（有雜湊就驗雜湊）；都沒有 → 照 `pyproject.toml` 的範圍裝。最後 `pip install --no-deps -e .`。
      鎖檔由 `scripts/lock_deps.py` 在發佈機產生（從「剛裝好的乾淨 venv」讀版本，不下載；加 `--wheelhouse` 會寫進每個 wheel 的 sha256）。
   4. **設定引導**：這個 Python 有 tkinter → 開視窗精靈（原本的四頁）；沒有（可攜版）→ 同一個視窗跑 `python -m synox init`。
3. 引導會問、寫進 `config.json` 的參數：

   | 參數 | 視窗精靈 | `synox init` | 寫到哪 |
   |---|---|---|---|
   | 這台給誰用 | 第 1 頁 | ① `--mode` | `mode` |
   | Telegram bot token、你的 Telegram id | 第 2、3 頁（配對碼） | ② 貼 token（getpass）＋數字 id；可跳過、先只用網頁 | `bot_token`、`owner_id` |
   | AI 來源 | 第 4 頁 | ③ `--llm`、`--model`、`--base-url`、`--api-key-env` | `llm`；金鑰進保管箱（`vault:llm_api_key`）或 `env:名字` |
   | 工具庫在哪 | 不用問（找 `tools/`） | ④ `--library`（預設 `tools`） | `packs.library`（相對路徑） |
   | 要裝哪些工具 | 完成後到網頁「設定 → 裝功能」 | ⑤ `--tools 名字或組合…` | `packs/<name>/`＋`data/packs.lock`（五關照舊） |

   `synox init --non-interactive` 全部用參數給（自動化、clean-room 檢查用）；`--dry-run` 只印出會寫什麼。
   金鑰**不收在命令列**（會留在 shell 歷史）：互動時用 getpass，非互動只收「金鑰放在哪個環境變數」。Telegram 只檢查格式、不連網
   （要實際測：`synox doctor`）。重跑 init 會保留沒問到的設定。
4. 之後：`Start.bat` 開 SYNOX；`python -m synox doctor` 健康檢查。

工程師不跑 Setup.bat 也可以：`py -3.12 -m venv .venv` → `.venv\Scripts\python.exe -m pip install -r requirements.lock`
（沒有鎖就略過）→ `pip install --no-deps -e .`（沒有鎖就 `pip install -e .`）→ `python -m synox init`。

## B. 安裝程式（released exe installer）

### 選哪個工具

SYNOX 不只是「一支程式」：工具（pack）要用**真的 Python 直譯器**跑——`{python}` 代換成 `sys.executable`、`runtime.python = "auto"`
用它建 `data/envs/<pack>/` 的 venv、沙盒的 jobobject 啟動器是 `python -I sandbox.py …`。凍結成單一 exe 的工具給的 `sys.executable`
是那支 exe 本身，這三件事都會壞。這是決定性的一條。

| 方案 | 要真的 Python（上面那條） | 防毒誤報 | 簽章 | 授權 | 每個使用者自己裝、不要管理員 | 結論 |
|---|---|---|---|---|---|---|
| PyInstaller（onefile／onedir） | ❌ `sys.executable` 是凍結的 exe；pack 的 venv、`{python}` 要另外帶一份 Python | 高：bootloader 常被誤判（惡意程式也常用它） | 可以 | GPL＋bootloader 例外（可商用） | 可以 | 不用 |
| Nuitka | ❌ 同上（編成 C，沒有一般的直譯器） | 中～高 | 可以 | Apache-2.0（商用版另售） | 可以 | 不用 |
| cx_Freeze／Briefcase | ❌ 同上（Briefcase 帶 Python 但打包模型跟 pack 的 venv 不合） | 中 | 可以 | PSF／BSD | 可以 | 不用 |
| WiX（MSI）／MSIX | ✅（自己帶可攜版 Python） | 低 | MSIX **一定要**簽 | MS-RL／商店規則 | MSI 預設全機、MSIX 有沙盒（寫自己的資料夾受限） | 太重，之後要上商店再說 |
| **Inno Setup 6＋可攜版 CPython＋wheelhouse** | ✅ 真的 CPython，跟 git clone 版是同一套檔案 | 低：Inno 是常見的正派安裝器；裡面的 Python 是官方簽章的 | 可以（`SignTool=`） | Inno Setup 自己的授權（免費、可商用）；CPython PSF | ✅ `PrivilegesRequired=lowest`，裝到 `%LOCALAPPDATA%\Programs\SYNOX` | **採用** |

### 怎麼做（設計；這台沒有打包過）

- **發佈機**（不是擁有者每天用的這台，也不是使用者的電腦）依序：
  1. 乾淨 venv 裡 `pip install -e .` → `scripts\lock_deps.py` 產生 `requirements.lock`（進 git）；
  2. `pip download -r requirements.lock -d wheelhouse --only-binary=:all:`＋`pip`、`virtualenv`、`setuptools` 的 wheel
     （版本照可攜版 Python 的版本挑）→ `scripts\lock_deps.py --wheelhouse wheelhouse` 把雜湊寫進鎖；
  3. SYNOX_Libs：`scripts\build.py` → `dist\`；
  4. `scripts\stage_installer.py --python-embed <解開的 python-3.12.x-embed-amd64> --wheelhouse wheelhouse --tools <Libs>\dist
     [--tk-from <同版本、裝好的 CPython>]`：只複製檔案，產生 `dist\installer-stage\SYNOX\`；
  5. `ISCC.exe /DAppVersion=<版本> /DStageDir=<stage>\SYNOX setup\installer\synox.iss` → `dist\SYNOX-Setup-<版本>.exe`；
  6. 簽章（QD1）。
- **使用者那邊**：安裝程式把檔案放到 `%LOCALAPPDATA%\Programs\SYNOX`（每個使用者自己一份、不要管理員、資料夾可寫——SYNOX 的
  `config.json`、`data/` 就在安裝資料夾裡，所以**不能**裝進 Program Files）→ 最後一步跑 `Setup.bat`：bootstrap 先用
  `runtime\python`，從 wheelhouse 離線裝 pip／virtualenv、建 `.venv`、裝套件 → 精靈或 `synox init`。
- **tkinter**：可攜版 CPython 沒有 tkinter。`--tk-from` 會把同版本 CPython 的 `_tkinter.pyd`、`tcl86t.dll`、`tk86t.dll`、`Lib\tkinter`、
  `tcl\` 一起帶，並在 `._pth` 加 `Lib`。**這招能不能在 virtualenv 建的 .venv 裡開出視窗，沒有驗證過**；不行的話自動退到文字版 init，
  功能一樣（QD3）。
- **解除安裝**：先跑 `setup\uninstall.ps1 -Mode shortcuts -Yes`（捷徑、開機啟動、`.synoxpack` 關聯），再刪安裝的檔案與 `.venv`；
  **`config.json`、`data\`（筆記、保管箱、金鑰）、裝過的工具（`packs\`）都留著**。
- **防毒與 SmartScreen**：沒簽章的安裝程式第一次會被 SmartScreen 擋（「其他資訊 → 仍要執行」）；簽了章、下載量累積之後才會消失。
  可攜版 Python 本身有 PSF 的簽章。安裝程式不跑任何從網路下載的東西（全部離線）。
- **授權義務**：安裝程式裡有 CPython（PSF）、各個 wheel（Apache／BSD／MIT／MPL-2.0 的 certifi…）。發佈前要附一份第三方授權清單（handoff 有一項）。

## C. 工具庫放哪裡（QL4 原題）

- 發佈物（zip：`scripts/make_zip.py --tools <Libs>\dist`；安裝程式：stage 時 `--tools`）旁邊附 **`tools/`**＝SYNOX_Libs `dist/` 的內容
  （每個工具一個 `.synoxpack`＋目錄 `index.json`，含每個檔的 sha256、建議組合 `bundles`）。git clone 的人另外下載這個資料夾放進去
  （`/tools/` 在 `.gitignore`；從哪裡下載：QD4）。
- **位置規則**（`src/synox/wizard/tools.py`，`packs/library.py` 用同一個）：`config.json` 的 `packs.library`（相對於 SYNOX 資料夾，或絕對路徑）
  → 沒寫就找 `<SYNOX>/tools`（有 `index.json` 才算）。init 寫進 config 的值在 SYNOX 資料夾裡面時一律是相對路徑（整個資料夾搬家也不會斷）。
  網址只顯示、不下載（下載的安全檢查另外設計，見 QL4 的選項 C）。指到 SYNOX_Libs 的**原始碼**時會明說「先打包」。
- **列出／安裝**：`python -m synox init`（第 ⑤ 步）、`python -m synox tools list`、`python -m synox tools install <名字或組合> [--yes]`。
  先對 `index.json` 的 sha256（檔名只收同一層的 `*.synoxpack`），再走原本的五關（`admin.stage_file` → 報告 → 確認 → `install_staged` 寫鎖）。
  T2（有掃不到內容的程式）要打發行者名字；非互動不裝 T2。**不支援「全部裝」**——要什麼自己挑。
- **網頁「設定 → 工具」列出可裝工具**：後端零件（`wizard/tools.py` 的 `read`／`pick`／`file_of`）已經可以用；畫面（`web/static`）這次沒做
  （另一條分支在改介面），之後接 `/api/settings` 加一個「工具庫有哪些」的清單即可。

## D. 沒有 hidden dependency：規則與這次的審計

規則（`docs/AGENT.md`「另外」也有一行）：

1. 所有路徑相對於 SYNOX 資料夾（`config.ROOT`），或可以設定（config、環境變數、命令列參數）；不寫死任何一台電腦的路徑、使用者名稱。
2. 「找旁邊的兄弟資料夾」只能是**有文件、有測試的後備**，那一行要標 `clean-room: sibling-fallback`；`tests/test_clean_room_check.py`
   擋住所有 git 追蹤的檔案裡沒標記的猜測與本機路徑。
3. 相依版本要鎖（`requirements.lock`），要能離線裝（`wheelhouse/`）。
4. 不靠這台才有的環境變數、全域套件、使用者資料夾裡的東西；Windows 專屬的呼叫要有保護。

這次的審計結果（SYNOX 與 SYNOX_Libs）：

| # | 找到什麼 | 改成什麼 | commit |
|---|---|---|---|
| 1 | `config.ROOT` 一律取 `config.py` 往上三層：`pip install .` 進 site-packages 時變成 venv 裡；`SYNOX_HOME` 相對路徑不轉絕對 | `default_root()`：SYNOX_HOME → 原始碼版面 → 目前資料夾；doctor 印出是哪一種 | `fix(config)` |
| 2 | 可攜版 Python 沒有 tkinter，bootstrap 的最後退路一定開不了精靈（只叫人手寫 config.json） | bootstrap 先檢查 tkinter，沒有就跑文字版 `synox init`；`synox wizard` 開不了視窗時也改文字版 | `build(setup)`、`feat(init)` |
| 3 | 相依只有範圍（`>=`），裝到哪一版看安裝當天的 PyPI；完全沒有離線安裝 | `requirements.lock`（`lock_deps.py`）＋`wheelhouse/` 離線安裝 | `build(setup)` |
| 4 | 工具庫位置只能手寫 `packs.library`，沒寫就只會說「去問給你 SYNOX 的人」 | 預設 `<SYNOX>/tools`（相對位置）＋init／`tools` 指令 | `feat(init)` |
| 5 | `logic.save` 把 `env:名字` 當成金鑰存進保管箱 | `env:` 原樣寫進 config | `feat(init)` |
| 6 | docs/handoffs 兩份交接單寫著這台電腦的 `C:\Users\…\Documents\…` | 改寫成 repo 名字 | `fix(audit)` |
| 7 | `scripts/vendor_sdk.py` 只找 SYNOX 旁邊的 `ISDTeleKitSDK` | `--sdk` → `ISDTELEKIT_SDK` → 才找旁邊（標記為後備）；找不到說怎麼指定 | `fix(audit)` |
| 8 | `tests/test_empty_host.py` 找 SYNOX 旁邊的 `SYNOX_Libs` | 保留（`SYNOX_LIBS` 優先、找不到就跳過），標記為後備 | `fix(audit)` |
| 9 | doctor 把 `llm.max_tokens` 當密鑰遮掉（clean-room 跑 doctor 時看到） | `NOT_SECRET` 例外 | `fix(doctor)` |
| 10 | SYNOX_Libs `scripts/_synox.py` 沒設 `SYNOX_HOME` 就只找 `../SYNOX` | SYNOX_HOME → 跑腳本的 Python 自己 import 得到的 synox → 後備 `../SYNOX`；找不到列出試過的地方 | Libs `fix(scripts)` |
| 11 | 這台的 `.venv` 沒有 `websocket-client`（pyproject 有寫）、metadata 還是 synox 0.1.0 | 不是程式的問題，是開發環境舊了；所以 `requirements.lock` **不在這台產生**（會漏），交給發佈機 | — |

查過、沒問題（不用改）：`find_claude` 看 `~/.local/bin`（官方安裝位置，有 PATH 先用 PATH）；桌面捷徑用 `GetFolderPath('Desktop')`
（OneDrive 轉向的桌面也對）；`winreg`／`ctypes.windll`／`taskkill` 都只在 Windows 分支或精靈勾選時才用；`vendor/isdtelekit` 進 git，
乾淨電腦不需要 ISDTeleKitSDK；`.bat` 一律 `%~dp0`（跟 SYNOX 資料夾走）。

留著、但要記得的：

- **ntu_easy_llm 還不在 PyPI**：用金鑰的 AI（OpenAI、Anthropic、Gemini、相容端點）在空白電腦上一定缺它；init／doctor 會說怎麼裝。
  安裝程式能不能把它的 wheel 放進 wheelhouse，看 QD2。Claude Code、不用 AI 不受影響。
- `config.example.json` 的 `vault.mode` 寫 `dpapi`（只有 Windows 有）；macOS／Linux 不在這次範圍。
- 文字版 init 只有中文（視窗精靈有 12 種語言）。
- SYNOX 資料夾同時是「程式放哪」與「資料放哪」：這就是安裝程式必須裝在使用者可寫的 `%LOCALAPPDATA%` 的原因。要分開（程式唯讀、資料在
  `%APPDATA%`）是另一個 ADR。
- SYNOX_Libs 公開前：它的 ADR 0001 引用的擁有者原話、`docs/mcp-audit-2026-11.md` 有這台的路徑（原話一字不改的規定 vs. 公開版要拿掉隱私），
  另一個工作正在做 Libs 的公開檢查，這裡不重做。

## E. 在這台能模擬多少：`scripts/clean_room_check.py`

把會發出去的檔案（跟 `make_zip.py` 同一份，git 追蹤的、不含 `.git`／`.venv`／`data`／`config.json`）複製到新的暫存資料夾，
（可選）附上 `tools/`；清掉所有 `SYNOX_*`、`PYTHON*`、AI 與聊天的金鑰環境變數，PATH 只剩 Windows 系統資料夾（沒有 py、git、claude），
使用者資料夾（USERPROFILE／APPDATA／LOCALAPPDATA）換成空的，目前資料夾換到別處，然後跑：import 來源檢查 → `doctor --offline` →
`init --dry-run` → `init --non-interactive`（裝 starter 的第一個工具）→ `tools list` → `doctor` → pytest 子集；最後確認所有輸出都沒有提到原本的資料夾。

**做不到的**：它重用這台現有的直譯器（不建 venv、不 pip、不連網），所以「缺套件」「Python 本身沒裝」「Setup.bat／bootstrap.ps1／winget」
「另一個 Windows 帳號的 DPAPI」「視窗精靈」「exe 安裝程式」都不在裡面——這些只能照 [clean-machine-test.md](../handoff/clean-machine-test.md) 在空白的
Windows 帳號或 VM 上實測。

## 後果

- 好：兩條路徑最後是同一套檔案、同一個 bootstrap、同一份 `config.json`；安裝程式只是「把網路那一段先做好」。工具庫位置不再需要問人。
- 代價：安裝程式比較大（Python＋wheel 約幾十 MB）；發佈機多幾個步驟（lock、wheelhouse、stage、ISCC、簽章）。
- 沒做：真的打包 exe、真的空白電腦、網頁的工具庫清單畫面、macOS／Linux 安裝、程式與資料分開放。
