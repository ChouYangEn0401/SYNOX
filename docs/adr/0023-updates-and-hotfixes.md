# ADR 0023：SYNOX 自己更新——檢查更新、`synox update`、hotfix、退回

- 日期：2026-11-13
- 狀態：**提案，等擁有者核准**。這份只寫設計；程式只動了一行：`synox about`／`synox doctor` 多印「有沒有新版：到發佈頁看」（`brand.latest_hint`）。
- 版本規則（號碼怎麼升、分支、tag、每版要有什麼）在 [../versioning.md](../versioning.md)，這份不重複。
- 相關：[0003](0003-distribution-git-clone-and-installer.md)（ZIP／git／安裝程式三種裝法）、[0022](0022-ecosystem-bridge-and-sandbox.md) R8（只在使用者按按鈕時連網、目的地寫死）、
  `src/synox/packs/catalog.py`（工具庫已經這樣做了）、`src/synox/packs/upgrade.py`（工具的升級與退回）。

## 擁有者的要求（轉述）

SYNOX 公開了。在 `dev` 開發，合進 `main` 時升小版本；alpha＝內部測試、beta＝外部測試。之後 SYNOX 要能**自己更新**（架構改了、hotfix），
本體、工具、SDK 都要讓人清楚知道怎麼升級——「像吃飯喝水一樣簡單」，沒有技術上的痛苦。

## 0. 現在有什麼（2026-11-13，讀程式確認）

| | 現況 |
|---|---|
| 發佈 | SYNOX **沒有任何 tag、release**。介紹頁的「⬇ 下載」是 `main` 分支的 ZIP。工具庫 SYNOX_Libs 有 `v0.2.0`（標 pre-release） |
| 知道有新版 | 沒有。這次加了：`synox about`、`synox doctor` 印發佈頁網址（只印，不連網） |
| 更新本體 | 手動：ZIP 蓋過去＋`Setup.bat`、`git pull`＋`Setup.bat`（[versioning.md](../versioning.md)「我要怎麼更新？」）。`Setup.bat` 重跑是安全的（只更新套件，最後開精靈，關掉即可） |
| 更新工具 | **已經有**：網頁「工具庫（官方）」按「載入工具清單」才連網，卡片標「有新版」（`catalog.card` 的 `newer`）；按「安裝」＝下載（只跟 GitHub 的主機、大小上限、sha256 要等於清單）→ 跟上傳一樣的報告 → 人按確認 → 升級；`synox packs rollback` 退回 |
| 相容性 | pack.json 的 `requires.synox`／`requires.sdk`，`manifest.synox_problem` 在安裝、載入、doctor 檢查 |

所以要補的是**本體**（與 SDK）的「知道有新版 → 看說明 → 確認 → 更新 → 出事能退回」，工具那條照現在的做法延伸就好。

## 1. 怎麼知道有新版

**規則：只有使用者按了才查；或使用者自己打開「每週看一次」。查到了只顯示，不下載、不安裝。**

- 入口：網頁設定「電腦與備份」分頁一顆 **「檢查更新」**；終端機 `synox update --check`；（打開每週檢查的話）網頁頂端一條橫幅。
- 每週檢查（選用，`config.json` 的 `"updates": {"check": "manual" | "weekly"}`，預設 `manual`）：runtime 每次啟動時看 `data/update_check.json`
  的上次時間，超過 7 天才查一次；失敗就安靜地下週再試，不重試、不打擾。
- **查哪裡（寫死在程式裡）**：`https://github.com/ChouYangEn0401/SYNOX/releases/latest/download/release.json`。
  `latest` 只指向最新的**正式版**（GitHub 不把 pre-release 當 latest），所以一般人永遠只看到正式版。轉址只跟 GitHub 自己的主機
  （跟 `catalog._allowed` 同一套，路徑限 SYNOX repo 的 releases）。不從 `config.json`、網址參數、release 說明裡讀網址。
- **`release.json`**（新的附檔，`scripts/release.py` 之後加一個子指令產生）：
  ```json
  {"version": "0.2.3", "date": "2026-12-01", "severity": "normal | security",
   "summary": "一句白話", "notes_url": "https://github.com/ChouYangEn0401/SYNOX/releases/tag/v0.2.3",
   "assets": {"zip": {"file": "SYNOX-0.2.3.zip", "sha256": "…", "size": 0},
              "exe": {"file": "SYNOX-Setup-0.2.3.exe", "sha256": "…", "size": 0}},
   "rebuild_venv": false, "migrates_data": false, "min_from": "0.2.0"}
  ```
  比版本用 `packs/upgrade.semver_key`。送出去的只有一個 GET（User-Agent `synox-update-check`，不帶版本、不帶任何識別）；
  GitHub 會看到 IP，這點寫進說明。
- **畫面**（白話，不出現 sha256、json 這類字）：
  「你現在是 0.2.1，最新是 0.2.3（12 月 1 日）。這版改了什麼：…。［看完整說明］［更新］［先不要］」；
  `severity: security` → 紅色「**強烈建議更新**：修了一個安全問題」。已經是最新：「你是最新版 ✅」。

## 2. `synox update`／「更新」按鈕怎麼做

共同流程（三種裝法都一樣，只有第 5 步不同）：

1. 查 `release.json`（同上）→ 2. **先給人看這版的說明**（`summary`＋發佈頁連結；`migrates_data`／`rebuild_venv` 時多一句「這次會花比較久／會先備份資料」）
→ 3. 人按「更新」（伺服器版只有擁有者能按）→ 4. 下載附檔到 `data/update/<版本>/`，**大小與 sha256 要等於 `release.json`**，不合就刪掉、說一句人話
→ 5. 換檔（下面分三種）→ 6. `Setup.bat -Update`（新模式：只裝套件、不開精靈）→ 7. `synox doctor --offline` → 8. 重新啟動 SYNOX，
網頁顯示「已更新到 0.2.3」；doctor 有紅字就提示「要不要退回 0.2.1？」。

**誰來換檔**：SYNOX 自己正在跑時換不了（Windows 會鎖住 `.venv` 裡的 `python.exe`）。提案：SYNOX 準備好、驗完檔之後，啟動新的
`Update.bat`（→ `setup/update.ps1`）並自己結束；`update.ps1` 等 SYNOX 結束 → 換檔 → 跑第 6～8 步。`setup/` 由安裝流程的人負責，
這裡只定介面：`Update.bat <版本資料夾>`，結束碼 0＝成功、1＝失敗（已自動退回）。

| 裝法（怎麼認） | 換檔 | 保留 |
|---|---|---|
| **ZIP**（沒有 `.git`、沒有安裝程式的標記） | 附檔 `SYNOX-<版本>.zip`。舊版的程式先整份搬到 `_previous/<舊版本>-<時間>/`，再把新 ZIP 的 `SYNOX/` 解進來（解壓規則同 `installer_ci.extract`：拒絕絕對路徑、`..`）。ZIP 裡加一份 `RELEASE-MANIFEST.txt`（`make_zip.py` 產生：每個檔的路徑＋sha256），用它判斷「舊版有、新版沒有」的檔要拿掉，也能發現使用者自己改過的檔（先問） | `config.json`、`data/`、`packs/`、`runtime/`、`.venv/`（套件由第 6 步更新；`rebuild_venv` 時才刪掉重建）、`lang.txt`、`tools/` 換成新 ZIP 附的 |
| **git**（有 `.git`） | 工作區乾淨、在 `main` 上、`origin` 是官方網址 → `git fetch --tags origin` → `git merge --ff-only v<版本>`。有改過的檔、不在 `main`、不是官方 origin → **不動**，說「你改過 SYNOX 的檔案，自動更新不會蓋掉：請自己 `git pull`」 | 同上（這些本來就不進 git） |
| **安裝程式**（安裝程式寫的標記檔 `INSTALL-KIND.txt` = `exe`，`stage_installer.py` 放） | 附檔 `SYNOX-Setup-<版本>.exe`，驗完 sha256 後**打開它讓人看見**（不用 `/VERYSILENT`）。同一個 `AppId`、同一個資料夾＝覆蓋安裝，最後一步本來就跑 `Setup.bat` | 照 ADR 0003 B：`config.json`、`data\`、`packs\` 留著（**沒在真機驗證過**） |
| Docker | 不自動：顯示 `git pull` → `docker compose build` → `up -d` | volume |

## 3. hotfix 怎麼送到大家手上

- 分支照 [versioning.md](../versioning.md)：`hotfix/X.Y.Z` 從 `main` 切 → PATCH → 合進 `main`、打 tag、發佈 → 合回 `dev`。
- 安全修正：發佈頁標題前加「🔒 安全更新」、說明第一句「**強烈建議更新**」、`release.json` 的 `severity: security`；照 SECURITY.md 開 GitHub Security Advisory；
  介紹頁放一條提示（介紹頁維護者）。
- **代價要講清楚**：預設只在按了才查，所以沒打開每週檢查、也不看發佈頁的人**不會知道**有安全更新。這是「本機優先、不偷連網」的取捨，見決定 U2。
- `min_from`：太舊的版本不能一步跳（例如中間有資料轉換）→ 畫面說「請先更新到 0.3.0，再更新到 0.4.1」，`synox update` 一次只走一步。

## 4. 退回

- 本體：`synox update --rollback`（網頁「電腦與備份」也有一顆「回到上一版」）：把 `_previous/` 最近一份搬回、跑 `Setup.bat -Update`。
  `_previous/` 只留最近 2 份（提案值）。git 裝法＝`git checkout v<上一版>`。安裝程式＝重新執行上一版的 exe（發佈頁有）。
- **資料**：版本只換程式，`data/` 不動；但 MINOR 版可能轉換資料或 `config.json`（`migrates_data: true`）。這種版本在轉換**之前**
  先把會改到的檔複製到 `data/_before-<新版本>/`（提案；或用 `backup.export_backup`），退回時放回去，並明說「更新之後新增的資料會不見」。
  轉換程式要寫成「讀得懂舊格式、不刪舊檔」，PATCH 版不准轉換資料。
- 自動退回：第 7 步 doctor 失敗、或新版啟動不了 → `update.ps1` 自動搬回舊版，下次打開網頁說明發生了什麼。
- 工具：維持現在的 `synox packs rollback <工具>`。

## 5. 工具（pack）的「有新版」

已經做好的不動（只在按「載入工具清單」時連網、卡片「有新版」、安裝＝升級報告＋人按確認、退回）。要補的：

1. **工具庫的網址**：`catalog.OFFICIAL_INDEX_URL` 釘在 `v0.2.0`（因為那一版是 pre-release，`latest/download` 會 404），工具庫發新版時 SYNOX 也得改程式。
   建議：SYNOX_Libs 發**正式版**（不勾 pre-release）之後改回 `releases/latest/download/index.json`（決定 U7）。
2. 「檢查更新」順便載入工具清單，把「有新版」的工具列在同一頁；「全部更新」仍然**每個工具一份報告、一個確認**（權限可能變大，不能悄悄裝）。
3. `index.json` 多帶每個工具的 `requires`（synox／sdk）：卡片可以先說「要先更新 SYNOX 到 0.3」，不用下載完才在第 1 關被擋。
4. `synox tools list`（本機工具庫）也比版本號、標「有新版」（[ecosystem.md](../ecosystem.md) 說還沒做）。

## 6. SDK（寫工具的人）

- SDK 跟著 SYNOX 發（`sdk/`），版本是獨立的 `SDK_VERSION`。每一版的發佈說明多一段 **「給寫工具的人」**（`SDK_VERSION` 有變才出現）：
  舊 → 新、相不相容、要做什麼（只加 API＝不用改；MINOR＝改 `requires.sdk`、`synox-sdk check`、重新打包）。`release.py notes` 之後比上一個 tag 的
  `SDK_VERSION` 自動加這段（提案）。
- 附檔加 `synox_sdk.py`（單檔版）：作者不用下載整個 SYNOX 就能更新自己工具旁邊那一份。
- 上 PyPI（`pip install -U synox-sdk`）最方便，但有搶註名字與帳號安全的問題，見決定 U6。

## 7. 安全

| 規則 | 做法 |
|---|---|
| 只認官方來源 | 網址寫死（`brand.RELEASES_URL` 與更新模組的常數），轉址只跟 GitHub 主機、路徑限 SYNOX repo；不讀設定檔、網址參數、release 說明裡的網址 |
| 檔案沒被換過 | `release.json` 的 sha256＋大小；下載、驗證都在換檔**之前**，沒過＝刪掉。第二來源：GitHub API 給每個附檔的 `digest`（工具庫已經這樣核對過） |
| 擋得住「整個 GitHub 帳號被盜」嗎 | **擋不住**（同一個人能同時換檔和換 sha256）。要擋就要簽章：維護者用 ed25519 簽 `release.json`，公鑰寫在 SYNOX 裡（跟 ADR 0022 決定 26 的工具簽章同一套）。在簽章做好之前，說明裡照實寫「信任的是 HTTPS＋GitHub 這個 repo」 |
| 先看說明再更新 | 一律先顯示這版改了什麼，人按確認才下載、才換；**沒有自動安裝**，安全更新也一樣 |
| 不降級 | `synox update` 只往新的走；回舊版只能走「退回」（明確的另一顆按鈕） |
| 不先跑下載的東西 | 換檔前不執行 ZIP 裡任何檔；`Setup.bat` 是換好之後、驗證過的那一份 |
| 伺服器版 | 只有擁有者能查、能更新 |

## 8. 做的順序（提案）

| 階段 | 內容 | 連網？ |
|---|---|---|
| P0（這次） | [versioning.md](../versioning.md)、`scripts/release.py`、about／doctor 印發佈頁網址 | 否 |
| P1 | 每版附 `release.json`、`SHA256SUMS.txt`、ZIP 裡的 `RELEASE-MANIFEST.txt`；`release.py notes` 加「給寫工具的人」 | 否 |
| P2 | `synox update --check`＋網頁「檢查更新」（只看、不下載）；選用的每週檢查 | 按了才連 |
| P3 | ZIP／git 的換檔、`Update.bat`、`Setup.bat -Update`、退回；簽章（決定 U5）做好才開放 | 按了才連 |
| P4 | 安裝程式路線、工具「全部更新」、`index.json` 帶 `requires` | 按了才連 |

## 9. 擁有者要決定的

| # | 問題 | 建議 |
|---|---|---|
| U1 | 第一次照規則發的版本號 | **0.3.0**（先 `0.3.0-beta.1`）：這批改動把內建工具搬到工具庫，更新的人要自己裝回工具，照規則是 MINOR。想從 0.2.1 開始也可以，但「怎麼更新」第一行要寫要重裝工具。不補打 `v0.2.0` |
| U2 | 預設要不要每週檢查 | **預設不查**；安裝精靈最後問一次「每週幫我看一次有沒有新版（只看，不會自己裝）」，使用者勾了才開。代價：沒勾的人收不到安全更新的提醒 |
| U3 | App 裡要不要能選 beta | **先不要**：beta 給願意幫忙的人從發佈頁手動下載；App 只看正式版 |
| U4 | 誰來換檔 | **`Update.bat`＋`setup/update.ps1`**（跟 `Setup.bat` 同一套 PowerShell；Windows 不能讓正在跑的 Python 換掉自己） |
| U5 | 簽 `release.json` | **要，且在開放 P3（真的換檔）之前做好**；私鑰由創始維護者保管、離線 |
| U6 | SDK 上 PyPI | **先不要**；附 `synox_sdk.py` 在每版發佈頁。要上的話先註冊 `synox-sdk` 名字、帳號開 2FA、用 trusted publishing |
| U7 | 工具庫網址 | SYNOX_Libs 發一個**正式版**，SYNOX 改回 `releases/latest/download/index.json`；之後工具庫發版不用改 SYNOX |
| U8 | `_previous/` 留幾份 | **2 份** |
| U9 | 安全更新怎麼通知 | 發佈頁「🔒 安全更新」＋「強烈建議更新」＋GitHub Security Advisory＋介紹頁提示 |

## 10. 沒有驗證的

- Windows 上換檔時哪些檔被鎖、`update.ps1` 的等待與換檔順序；安裝程式覆蓋安裝是否真的保留 `config.json`、`data\`、`packs\`。
- SYNOX repo 的 `releases/latest/download/…` 轉址（只在工具庫實測過）；沒有 token 時 GitHub 的流量限制對「按了才查」與「每週一次」都夠用（推測）。
- `pip` 把 `0.2.1-beta.1` 正規化成 `0.2.1b1`：`setuptools` 會印一行提醒，不影響安裝（在 Linux 用 `packaging` 確認過正規化；Windows 打包沒試過）。
