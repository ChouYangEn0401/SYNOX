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
| 安裝程式用什麼做 | **Inno Setup 6＋SYNOX 自己的 CPython（python-build-standalone，跟 ZIP 同一個檔案，有 tkinter）＋離線套件（wheelhouse）**；不用 PyInstaller／Nuitka（理由見 B）。原本是官方可攜版（embeddable），2026-11-13 改，見文末附記之二 |
| 參數在哪裡設 | 安裝最後一步一律進「設定引導」：有視窗用原本的精靈（tkinter），沒有視窗就用文字版 `python -m synox init`。兩個寫同一份 `config.json` |
| 工具庫（QL4 原題） | 發佈物旁邊附 `tools/`（SYNOX_Libs 打包好的 `.synoxpack`＋`index.json`）；`packs.library` 沒寫時就找 `<SYNOX>/tools`（**相對於 SYNOX 資料夾**）；init 列出來、**使用者自己挑**，不自動全裝 |
| hidden dependency | 路徑一律相對於 SYNOX 資料夾或可設定；「剛好在旁邊的兄弟資料夾」只能當有標記的後備；`scripts/clean_room_check.py` 在這台模擬；真的空白電腦由擁有者實測 |

## A. git clone 路徑：clone 之後怎麼一路到可用

**需要什麼**：Windows 10／11 64 位元、能上網（裝 Python 與套件時）。Python 不用先裝：`Setup.bat` 預設裝 SYNOX 自己的一份
（放在 SYNOX 資料夾的 `runtime\`，不用、也不動這台電腦原本的 Python；見文末附記）。
git 也不是必要的：沒有 git 的人用 GitHub 的「Code → Download ZIP」解開，效果一樣。

1. `git clone <SYNOX repo>`（或解開 zip）到任何資料夾，路徑可以有中文、空白。
2. 雙擊 `Setup.bat` → `setup/bootstrap.ps1`：
   1. **Python ≥ 3.11**（2026-11-13 改，見文末兩則附記）：預設只用 SYNOX 資料夾裡的 `runtime\python`——安裝程式附的，或
      `Setup.bat` 照釘死的網址＋SHA256 下載的 python-build-standalone CPython 3.12.16（兩邊同一個檔案；有 tkinter）。不用 uv、
      不改 PATH、不寫登錄檔、不用 winget。進階的 `Setup.bat -UseSystemPython` 才照舊的順序找這台電腦的
      Python（`py` 啟動器 → PATH 上的 `python` → `%LOCALAPPDATA%\Programs\Python\Python31x` → `winget install Python.Python.3.12` →
      都沒有才用 SYNOX 自己的），而且絕不挑 Microsoft Store 的 `python` 捷徑。
   2. `python -m venv .venv`。
   3. **裝相依**（由嚴到寬）：有 `wheelhouse\` → 完全離線（`--no-index --find-links wheelhouse`）；有 `requirements.lock` →
      照鎖定的版本裝（有雜湊就驗雜湊）；都沒有 → 照 `pyproject.toml` 的範圍裝。最後 `pip install --no-deps -e .`。
      鎖檔由 `scripts/lock_deps.py` 在發佈機產生（從「剛裝好的乾淨 venv」讀版本，不下載；加 `--wheelhouse` 會寫進每個 wheel 的 sha256）。
   4. **設定引導**：這個 Python 有 tkinter → 開視窗精靈（原本的四頁）；沒有（`-UseSystemPython` 挑到沒裝 tcl/tk 的 Python）→
      同一個視窗跑 `python -m synox init`。
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
  2. `pip download -r requirements.lock -d wheelhouse --only-binary=:all:`＋`pip`、`setuptools` 的 wheel
     （版本照附的 Python 的 X.Y 挑）→ `scripts\lock_deps.py --wheelhouse wheelhouse` 把雜湊寫進鎖；
  3. SYNOX_Libs：`scripts\build.py` → `dist\`；
  4. `scripts\stage_installer.py --fetch-python --wheelhouse wheelhouse --tools <Libs>\dist`：照 `setup\bootstrap.ps1` 釘的網址
     下載 SYNOX 自己的 Python、對 SHA256、解到 `runtime\python`，再複製其他檔案，產生 `dist\installer-stage\SYNOX\`；
  5. `ISCC.exe /DAppVersion=<版本> /DStageDir=<stage>\SYNOX setup\installer\synox.iss` → `dist\SYNOX-Setup-<版本>.exe`；
  6. 簽章（QD1）。
- **使用者那邊**：安裝程式把檔案放到 `%LOCALAPPDATA%\Programs\SYNOX`（每個使用者自己一份、不要管理員、資料夾可寫——SYNOX 的
  `config.json`、`data/` 就在安裝資料夾裡，所以**不能**裝進 Program Files）→ 最後一步跑 `Setup.bat`：bootstrap 先用
  `runtime\python`，`python -m venv .venv`、從 wheelhouse 離線裝套件 → 精靈（沒有 tkinter 才用 `synox init`）。
- **tkinter**：（2026-11-13 改）附的 Python 是 python-build-standalone 的 `install_only_stripped`，本來就有 tkinter＋Tcl/Tk 8.6，
  不用再從別的 Python 複製（原本的 `--tk-from` 拿掉了）。QD3 因此不用再選；Windows 上真的開出視窗仍待實測。
- **解除安裝**：先跑 `setup\uninstall.ps1 -Mode shortcuts -Yes`（捷徑、開機啟動、`.synoxpack` 關聯），再刪安裝的檔案與 `.venv`；
  **`config.json`、`data\`（筆記、保管箱、金鑰）、裝過的工具（`packs\`）都留著**。
- **防毒與 SmartScreen**：沒簽章的安裝程式第一次會被 SmartScreen 擋（「其他資訊 → 仍要執行」）；簽了章、下載量累積之後才會消失。
  附的 Python（python-build-standalone）沒有 Authenticode 簽章，只靠釘死的 SHA256；防毒會不會擋待實測。安裝程式不跑任何從網路
  下載的東西（全部離線）。
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

## 附記（2026-11-13）：預設用 SYNOX 自己的 Python（uv），不碰這台電腦的 Python

> 這則附記裡「用 uv 裝 Python」的做法已經被下一則附記（之二）取代：擁有者不想要 uv。其他規則（預設只用 SYNOX 資料夾裡的
> Python、`-UseSystemPython`、不碰 Conda／Store、清環境變數、解除安裝）照舊。留著當紀錄。

擁有者要的：預設「暴力安裝全部幫你裝好」——SYNOX 用自己資料夾裡的那一份 Python；有經驗的人才選用自己的 Python。

### 為什麼改

原本 `Setup.bat` 先找這台電腦已經有的 Python（`py` 啟動器 → PATH 上的 `python` → `%LOCALAPPDATA%\Programs\Python` → `winget`）。
這讓每台電腦的環境都不一樣、很難支援：

- **Conda**：PATH 上的 `python` 常常是 Conda 的；`CONDA_PREFIX`、`PYTHONHOME`、`PYTHONPATH` 會漏進 SYNOX 的 Python。
- **Microsoft Store 的 `python`**：沒裝 Python 時，`%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe` 是一個「打開商店」的捷徑，
  一執行就跳商店（陷阱）；商店版 Python 本身也在 WindowsApps 底下，有路徑重導。
- **winget**：會跳條款、可能跳 UAC，而且改了這台電腦的 PATH 與已安裝程式清單——不是「只動 SYNOX 資料夾」。
- 版本不固定（3.11～3.13、各種修補版），出問題很難重現。

### 現在怎麼做（`setup/bootstrap.ps1`）

**預設（建議）**——全部在 SYNOX 資料夾的 `runtime\` 裡，不改 PATH、不寫登錄檔（除了原本 HKCU 的 `.synoxpack` 關聯）、
不碰 Conda／其他 Python、不要管理員、不用 winget：

1. `runtime\python` 已經有（安裝程式附的）→ 用它（wheelhouse 離線那條照舊）。
2. 沒有 → 下載 **uv 0.13.6**（https://github.com/astral-sh/uv 的官方 release，`uv-x86_64-pc-windows-msvc.zip`）到 `runtime\uv\0.13.6\`，
   先核對 SHA256，對不上就不用。釘死的值 `a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f` 抄自同一個 release 的
   `uv-x86_64-pc-windows-msvc.zip.sha256`（與 `sha256.sum` 那一行相同），2026-11-13 在這台把 zip 下載下來實算也一樣。
   然後 `uv python install 3.12.16 --python-preference only-managed --no-bin --no-registry`，環境變數：
   `UV_PYTHON_INSTALL_DIR=runtime\python-uv`、`UV_CACHE_DIR=runtime\uv-cache`、`UV_PYTHON_BIN_DIR=runtime\uv\bin`、
   `UV_PYTHON_PREFERENCE=only-managed`、`UV_NO_CONFIG=1`（不讀使用者的 uv.toml）。`--no-bin`＝不在 `%USERPROFILE%\.local\bin` 放
   python.exe；`--no-registry`＝不寫 PEP 514 登錄檔。再用 `runtime\python-uv\cpython-3.12.16-windows-x86_64-none\python.exe -m venv .venv`
   建 .venv（標準的 venv＋ensurepip，自帶 pip、不連網），之後裝套件的三條路（wheelhouse 離線、requirements.lock、pyproject）不變。
   換 uv 版本時：版本、SHA256、`$UvPython`（那版 uv 內建的下載清單裡的 3.12.x）一起換，`tests/test_private_python.py` 會擋。
3. uv 失敗（下載、檢查碼、安裝任何一步）→ 直接說「用 uv 準備 Python 沒成功：…改用備用方法」，退到 python.org 的可攜版
   （embeddable zip → `runtime\python`；沒有 tkinter，設定改用文字版 `synox init`）。這一步和以前一樣沒有核對檢查碼。

**進階**：`Setup.bat -UseSystemPython`（`Setup.bat` 原樣把參數交給 bootstrap，可以和 `-Lang` 一起用）→ 舊的順序
（`runtime\python` → `py` → PATH 上的 `python` → `%LOCALAPPDATA%\Programs\Python` → winget → 可攜版），但 WindowsApps 底下的
`python` **先擋掉、不執行**；`py` 找到的若 `sys.executable` 在 WindowsApps 底下也跳過。開始前印一段警告（環境難預測、會用 winget、
怎麼換回來）。

**安裝前的提醒**（預設那條，12 種語言）：偵測到 Conda（`CONDA_PREFIX`／`CONDA_EXE`／PATH 上有 `conda`）、Store 的 python 捷徑、
或其他 Python（`py`／`python`／`python3`、`%LOCALAPPDATA%\Programs\Python`）就印「這台電腦已經有 …。SYNOX 會用自己資料夾裡的那一份
Python，不會動到它們。」只看、不動。

**不讓使用者的環境漏進來**：bootstrap 先記下上面的線索，再對自己這個程序清掉 `PYTHONHOME`、`PYTHONPATH`、`PYTHONSTARTUP`、
`PYTHONUSERBASE`、`PYTHONEXECUTABLE`、`VIRTUAL_ENV`、`__PYVENV_LAUNCHER__`、所有 `CONDA_*`、`_CE_CONDA`／`_CE_M`、
`PIP_USER`／`PIP_TARGET`／`PIP_PREFIX`、會改 uv 挑 Python 的 `UV_PYTHON`／`UV_SYSTEM_PYTHON`／`UV_NO_MANAGED_PYTHON`／`UV_CONFIG_FILE`／
`UV_OFFLINE`，並設 `PYTHONNOUSERSITE=1`（它開的精靈也繼承）。`Start.bat`、`Console.bat`、`Open-SYNOX.bat`、`Install-Pack.bat`、
`Connect-Apple.bat`、`Stop.bat` 在 `setlocal` 之後 `call setup\clean-python-env.bat` 做同一件事——只影響那個視窗。代理設定、
`PIP_INDEX_URL` 這類網路設定照留。PATH 不動。

**舊的安裝**：已經有 `.venv` 的，重跑 `Setup.bat` 照用（不會自己重建）；預設那條會看 `.venv\pyvenv.cfg` 的 `home`，在 `runtime\` 外面就印一行
「要換成 SYNOX 自己的 Python：Uninstall.bat env，再雙擊 Setup.bat」。

**解除安裝**：`Uninstall.bat env`／`all` 本來就刪 `runtime\`；現在 `runtime\` 裡有 `uv\`、`python-uv\`、`uv-cache\`，一起刪。
`python-uv\` 裡有指向同一個資料夾內的 junction（`cpython-3.12-…` → `cpython-3.12.16-…`），先拆掉連結本身再遞迴刪，不會跟著連結刪到外面。
安裝程式的 `[UninstallDelete]` 也加了 `{app}\runtime`。都只在 SYNOX 資料夾裡。

**要連的網址**：github.com（uv 的 zip；uv 抓 Python 也可能走 github.com 或 releases.astral.sh）、pypi.org／files.pythonhosted.org（套件）。
uv 失敗時：www.python.org、bootstrap.pypa.io。

### 驗證到哪裡

已實測（**Linux** 雲端機，2026-11-13；這台沒有 PowerShell）：

- uv 0.13.6 Windows x64 zip 下載實算的 SHA256＝release 公布的值；zip 裡是平放的 `uv.exe`、`uvw.exe`、`uvx.exe`。
- 0.13.6 的下載清單裡有 `cpython-3.12.16-windows-x86_64-none`。
- Linux 版 uv 0.13.6、同樣的環境變數與旗標：`uv python install 3.12.16` 裝出 CPython 3.12.16 到指定資料夾，`tkinter` 可以 import（Tk 9.0）；
  HOME 換成空資料夾，裝完 HOME 底下沒有任何檔案（沒寫 `~/.local/bin`）；`python -m venv` 建的 .venv 有 pip。用這個 .venv 裝 SYNOX、
  在 xvfb 跑 `tests/test_wizard.py`、`test_wizard_i18n.py`、`test_web_login.py`：全過（只有一個本來在 Linux 就失敗的 Windows 路徑測試）。
- 注意：`uv python find` 會先挑目前資料夾（或上層）的 `.venv`，`only-managed` 也擋不住，所以 bootstrap 不用 `uv python find`，直接用
  uv 固定的資料夾名字找 `python.exe`。
- 靜態測試：`tests/test_private_python.py`（釘死的版本與 SHA256、旗標、預設那條沒有 winget、`-UseSystemPython` 的傳遞、Store 捷徑、
  啟動器清變數、.bat 只有 ASCII＋CRLF、解除安裝、這段附記）。`test_wizard_i18n.py` 檢查每個語言的 key 都齊。

**待實測（Windows）**——這台沒跑過 `bootstrap.ps1`，連 PowerShell 語法檢查都沒做（`test_powershell_scripts_parse` 只在 Windows 跑）：

1. 乾淨的 Windows 11、一般使用者帳號：雙擊 `Setup.bat` → 下載 uv、核對 SHA256 → Python 3.12.16 進 `runtime\python-uv` → `.venv` →
   **視窗精靈打得開**（Windows 上的 tkinter／Tk 9.0 待實測）。
2. 確認沒有寫到 SYNOX 資料夾外面：使用者與系統的 PATH 不變；`HKCU\Software\Python` 沒有新的項目（`--no-registry`）；
   `%USERPROFILE%\.local\bin` 沒有 `python*.exe`；`%APPDATA%\uv`、`%LOCALAPPDATA%\uv` 沒有東西。
3. 有 Conda 的電腦：在 Anaconda Prompt（`conda activate` 之後）跑一次、在檔案總管雙擊一次：都要印 Conda 的提醒；`.venv\pyvenv.cfg` 的 `home`
   在 `runtime\python-uv`；`Start.bat` 起來之後 `sys.prefix`、`sys.path` 沒有 Conda 的路徑。Conda 的 `Library\bin` 還在 PATH 上（不動 PATH），
   Python 3.8+ 載入擴充模組的 DLL 不看 PATH，照理沒事——待實測。
4. 只有 Store 捷徑、沒裝 Python 的電腦：預設和 `-UseSystemPython` 都不能跳出商店。
5. uv 失敗的退路：擋掉 github.com 再跑 → 看到「用 uv 準備 Python 沒成功」、改用可攜版、文字版 `synox init`。
6. `Uninstall.bat env`：`runtime\` 整個刪掉、沒有錯誤（junction）。
7. 公司網路／代理：PowerShell 5.1 的 `Invoke-WebRequest` 用系統代理；uv 讀 `HTTPS_PROXY`，不一定讀系統代理。
8. 防毒軟體會不會擋 `uv.exe` 或 `runtime\python-uv` 裡的 python.exe。

## 附記（2026-11-13，之二）：不用 uv，直接下載同一份獨立版 CPython；.exe 和 ZIP 同一個 Python

擁有者：「怕你裝這個 UV 把我的本地電腦用壞」，比較喜歡單純的 `python -m venv`。決定：**uv 整個拿掉**。

### 現在怎麼做

- **哪一個 Python**：python-build-standalone（uv 本來替我們下載的就是它）的 CPython **3.12.16**、release `20261026`、
  `x86_64-pc-windows-msvc-install_only_stripped.tar.gz`（約 22 MB；python.exe、pythonw.exe、pip、`venv`、`ensurepip`、tkinter＋
  Tcl/Tk 8.6、vcruntime 都在裡面；`stripped`＝去掉除錯符號）。
  - 網址：`https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz`
  - SHA256：`1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149`
  - 三個來源一致：那個 release 的 `SHA256SUMS`、uv 0.13.6 內建的下載清單、2026-11-13 實際下載後自己算。
  - 釘在 `setup/bootstrap.ps1` 的 `$PythonVersion`、`$PythonBuild`、`$PythonSha256`、`$PythonUrl`；`scripts/stage_installer.py`
    讀同樣這四行，所以 **.exe 附的和 ZIP 下載的是同一個檔案**。`tests/test_private_python.py` 檢查值、
    `tests/test_release_layout.py` 檢查 stage 讀得到。
- **ZIP（`Setup.bat`）**：`runtime\python\python.exe` 已經有、跑得起來 → 用它。沒有 → 下載到 `runtime\python.download\` →
  `Get-FileHash` 核對；**不對就刪掉下載的檔案、停下來**（不解開、不執行、不改用別的來源）→ 用
  `%SystemRoot%\System32\tar.exe` 解開 → 搬到 `runtime\python` → `python -m venv .venv`。
  - 為什麼用 tar.exe：這個專案的 Windows 版只有 `.tar.gz`（沒有 zip）；PowerShell 5.1 的 `Expand-Archive` 只會解 zip。
    Windows 10 1803（2018）以後都內建 `tar.exe`（bsdtar，看得懂 gzip 和 GNU 長檔名）。寫完整路徑，不用 PATH 上的 tar
    （Git 附的 GNU tar 會把 `C:` 當成遠端主機）。先切到下載資料夾、只給相對檔名，SYNOX 路徑有中文也不交給 tar 處理。
    沒有 tar.exe 就停下來，說請更新 Windows 或改用 .exe。
  - `runtime\python` 裡如果是舊的 python.org 可攜版（有 `python3XX._pth`）→ 說一聲、換成新的。
- **.exe**：發佈機 `stage_installer.py --fetch-python`（或 `--python-archive <已下載的檔案>`）→ 對 SHA256 → 用 Python 的
  `tarfile` 解（擋絕對路徑、`..`、連結；只收 `python/` 底下）→ `runtime\python`。`--python-embed`、`--tk-from` 拿掉；
  wheelhouse 不再需要 virtualenv。`synox.iss` 加 `[InstallDelete]`：更新時先刪舊的 `runtime\python`（舊版附的可攜版留下的
  `python312._pth` 會讓新的 python.exe 進入隔離模式）和 `.venv`（安裝完跑的 `Setup.bat` 離線重建）。
- **python.org 的退路拿掉了**：原本 uv 失敗會退到 python.org 的可攜版（沒有 tkinter、沒核對檢查碼、`get-pip.py` 也是現抓的）。
  現在只剩一個來源、一定核對；下載不了就停下來，清楚說三條路：確認連得上 github.com 再試、改用 .exe（不用下載 Python）、
  或 `Setup.bat -UseSystemPython`。`-UseSystemPython` 那條找不到任何 Python、winget 也不行時，退到 SYNOX 自己的這一份（同樣核對），
  不再退到可攜版。
- **舊的東西**：`runtime\uv`、`runtime\python-uv`、`runtime\uv-cache`（只有開發中的版本裝過）照樣由 `Uninstall.bat env` 刪掉
  （junction 照樣先拆）。已經用 `runtime\python-uv` 建好的 `.venv` 照用（在 `runtime\` 裡，不會被當成外面的 Python）。
- 清環境變數：`UV_*` 那幾個拿掉（不再用 uv）；`setup\clean-python-env.bat` 補上 `PIP_USER`／`PIP_TARGET`／`PIP_PREFIX`，
  跟 bootstrap 的 `Clear-PythonEnv` 同一份清單。
- **要連的網址**（ZIP）：github.com（Python 檔案；會轉到 release-assets.githubusercontent.com）、pypi.org／files.pythonhosted.org（套件）。

### 驗證到哪裡（Linux 雲端機，2026-11-13；沒有 Windows、沒有 PowerShell）

- Windows 的 `install_only_stripped` 下載實算 SHA256＝`SHA256SUMS`＝uv 清單。用 `tarfile` 看內容：3348 個一般檔案、沒有連結、
  6 個超過 100 字元的檔名（GNU 長檔名）、最上層只有 `python/`；有 `python.exe`、`pythonw.exe`、`DLLs\_tkinter.pyd`、`tcl86t.dll`、
  `tk86t.dll`、`tcl\tcl8.6`、`tcl\tk8.6`、`Lib\venv`（含 `scripts\nt\python.exe` 啟動器）、`Lib\ensurepip`、vcruntime。
- `stage_installer.py --python-archive`（和 `--fetch-python`）在 Linux 上做出的 `runtime\python` 跟直接 `tar -xzf` 解出來的逐檔相同；
  換成 `install_only`（沒 strip）的檔案會因 SHA256 不對而拒絕。
- 同一個 release 的 **Linux** 版（`x86_64-unknown-linux-gnu-install_only_stripped`，SHA256 也對得上）：解開 → `python -m venv` →
  `.venv` 裡 `import tkinter`（Tcl 9.0.4）、在 xvfb 開出 Tk 視窗、`pip install -e .` 裝好 SYNOX、`import synox.wizard`。
- 靜態測試：`tests/test_private_python.py`、`tests/test_release_layout.py`、`tests/test_installer_ci.py`、`tests/test_wizard_i18n.py`。

**待實測（Windows）**——`bootstrap.ps1` 在這台沒跑過，連 PowerShell 語法檢查都沒做（`test_powershell_scripts_parse` 只在 Windows 跑）：

1. 乾淨的 Windows 11／10（1803 以後）、一般使用者帳號：雙擊 `Setup.bat` → 下載、核對 → `tar.exe` 解到 `runtime\python` →
   `.venv` → **視窗精靈打得開**（Windows 版是 Tcl/Tk 8.6）。路徑有中文的資料夾（例如桌面的「SYNOX 測試」）再做一次。
2. 沒寫到 SYNOX 資料夾外面：PATH 不變、`HKCU\Software\Python` 沒有新項目、`%LOCALAPPDATA%`／`%APPDATA%` 沒有新的 Python 資料夾。
3. 檢查碼不對（例如把 `$PythonSha256` 改一個字）→ 看到紅字、`runtime\python.download` 被刪掉、`runtime\python` 沒出現。
4. 擋掉 github.com → 看到「下載 Python 沒成功」、停下來（不再退到可攜版）。
5. 防毒軟體（Defender 等）會不會擋沒簽章的 `python.exe`；公司代理（`Invoke-WebRequest` 用系統代理）。
   有 Conda 的電腦：照上一則附記第 3 項做一次，只是 `.venv\pyvenv.cfg` 的 `home` 現在要在 `runtime\python`。
6. 舊版 .exe 裝過的電腦裝新版 .exe：`runtime\python` 與 `.venv` 換新、`config.json`／`data\` 還在。
