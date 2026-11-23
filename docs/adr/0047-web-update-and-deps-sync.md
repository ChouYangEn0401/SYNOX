# ADR 0047：在網頁上一鍵更新 SYNOX、啟動時把套件補齊

- 日期：2026-11-23
- 狀態：**提案，已照「建議」實作**（分支 `feat/ui-update-deps-sync`）。第 6 節的 W1～W4 等擁有者決定；決定跟建議不一樣時，改的地方都很小（寫在每一題）。
- 修訂：[0023](0023-updates-and-hotfixes.md)（「網頁的『更新…』只打開 Update.bat 的視窗」→ 簽過章的版本可以直接在網頁換；換檔仍然是 `setup/update.ps1`）。
  不改 [0045](0045-update-channels.md) 的通道規則。
- 程式：`src/synox/update/web_api.py`（`/start`、`/rollback`、`/deps`）、`src/synox/update/deps.py`（新）、`src/synox/update/prepare.py`（`expect`、`deps_fingerprint`）、
  `setup/update.ps1`（`-Apply`、`-FromWeb`）、`src/synox/__main__.py`（`synox run` 開頭的套件檢查、`synox deps`）、`web/static/app.html`（「SYNOX 更新」卡片）、`guard/stepup.py`（動作名）。
- 測試：`tests/test_update_web.py`、`tests/test_update_deps.py`（另外 `test_update.py` 跟著改 `update.ps1` 的參數）。

## 背景（擁有者的需求，轉述）

1. **在網頁就能把 SYNOX 本體換成新版**。現在網頁只會「檢查更新」，真的要換得自己跑 `Update.bat`（測試版還要記得加 `-IncludePrerelease`）。
   要的是：看到「有新版」→ 按一下 → 換好。測試版照既有的通道設定（stable／preview），畫面上要看得出是哪一種。
2. **換了版本之後，啟動時要把套件補齊**。實際發生過：程式已經是 0.2.2-alpha.3，`.venv` 裡的 `ntu_easy_llm` 還是 0.5，設定頁就說
   「這個來源要 ntu_easy_llm 0.6 以上」。原因是 `pyproject.toml` 的選裝組（`[llm]`、`[llop]`）換了版本（指到 0.6.0a2 的 wheel），但沒有人重裝。
   要記得使用者裝過哪些選裝組；補裝失敗也不能讓 SYNOX 起不來，要用一句白話說哪個套件沒補到、怎麼補。

## 0. 現況（2026-11-23，讀程式確認）

| | ZIP 裝的 | 安裝程式（.exe）裝的 | git clone 的 |
|---|---|---|---|
| 怎麼認（`check.install_kind`） | 其他都不是 | `installer-choices.json` 的 `source` 是 `exe-installer` | 有 `.git` |
| 怎麼更新 | `Update.bat`：Python `synox update --prepare` 下載、對 `SHA256SUMS.txt`、驗 `release.json.sig`、解到 `data/update/<版本>/stage` → `update.ps1` 停 SYNOX、舊檔搬到 `_previous\`、新檔搬進來、相依變了才 `bootstrap.ps1 -Update`、確認版本、開 SYNOX；出事自動退回 | 下載新的 `SYNOX-Setup-<版本>.exe` 裝在原位（`{localappdata}\Programs\SYNOX`、不要管理員） | `Stop.bat` → `git pull` → `Setup.bat` |
| Update.bat | 可以 | 拒絕（說去下載安裝程式） | 拒絕（說 `git pull`） |
| 網頁 | 「檢查更新」＋「更新…」＝打開 Update.bat 的視窗，在視窗裡再問一次 | 只顯示怎麼做 | 只顯示怎麼做 |

- 簽章：`signing.RELEASE_PUBLIC_KEYS` 已經有兩把公鑰（現用＋備用），所以簽過章的版本 Update.bat 不用 `-AllowUnsigned`。
- `release.json` 的 `rebuild_venv`：維護者在發佈時說「這版一定要重裝套件」；`prepare` 另外比 `deps_fingerprint`（requirements、pyproject 的相依那幾行），
  兩個有一個是真的，`update.ps1` 才叫 `bootstrap.ps1 -Update`。
- **為什麼 ntu_easy_llm 會停在 0.5**（三個洞疊在一起）：
  1. `bootstrap.ps1` 的 `Install-Packages`：有 `requirements.lock` 時只裝鎖定的版本＋`--no-deps -e .`（**沒有選裝組**）；沒有鎖時裝 `-e .[llm]`（**只有 llm，沒有 llop**）。
     使用者自己用 `pip install -e .[llop]` 裝過的，重裝套件時沒有人記得。
  2. `deps_fingerprint` 只看 `dependencies|requires-python|llm|dev` 開頭的行：新加的 `llop` 組變了也不會觸發重裝。
  3. 手動蓋 ZIP、`git pull` 的人根本不會經過 `update.ps1`；之後跑 `Start.bat` 也沒有人檢查套件。

## 1. 網頁一鍵更新（ZIP 裝法、Windows）

**流程**（換檔的那一半跟 Update.bat 是同一條，不另外發明）：

1. 擁有者按「檢查更新」（照舊：按了才連網；通道照 `updates.channel`）。結果是「有新版、而且這一版有簽章」時，卡片出現 **「更新到 X」**
   （測試版會寫「更新到 X（測試版）」；卡片上一行寫目前的更新通道）。
2. 按下去先出一張確認卡：要換成哪一版、這版改了什麼（`summary`）、會暫時關掉 SYNOX、設定／資料／工具不會動、可以退回。按「開始更新」。
3. `POST /api/settings/update/start {"version": "X"}`（只有擁有者；開了手機驗證器要先解鎖；`version` 必須等於上次檢查看到、而且有簽章的那一版）。
   SYNOX 在背景執行緒跑 **`prepare()`**（跟 `Update.bat` 同一個函式）：查 GitHub（同一個通道）→ 最新版要**正好是 X**（中間又發了新版＝停下來，請重新檢查）→
   下載 → `SHA256SUMS.txt`（必須有）→ **簽章（網頁這條一定要有、一定要驗過；沒有 `-AllowUnsigned` 這個選項）** → 解到 `data/update/X/stage` → 寫 `ready.json`。
   這段時間 SYNOX 照常可以用；卡片每 1.5 秒問一次進度（`GET /api/settings/update` 的 `job`）。
4. 驗完 → SYNOX 用跟現在「更新…」一樣的方式（`cmd /c start`，跟 SYNOX 脫鉤）打開 **`Update.bat -Apply -FromWeb`**：
   `update.ps1` 讀 `ready.json`（用一次就丟、暫存資料夾一定在 `data\update\` 裡、`signed` 一定要是真的）→ **`Invoke-Swap`**（停 SYNOX → 舊檔到 `_previous\` →
   新檔搬進來 → 套件有變才 `bootstrap.ps1 -Update` → 確認 `synox.__version__` → 不對就自動退回）→ 用 `Start.bat --no-browser` 開回來。不再問、不再查。
5. 網頁拿到 `job.state = launched` 之後，跟「🔄 重新啟動 SYNOX」一樣問 `/alive`，開機代號換了就重新整理、跳到「💻 電腦與備份」。
   卡片顯示 `data/update_last.json`（`update.ps1` 寫的）：「✅ 已更新：A → X」或「⚠️ 沒更新成，已經自動退回 A」。最多等 10 分鐘（套件有變時要下載）。
6. **回到上一版**：`_previous\` 裡有舊版時，卡片多一顆「回到上一版（<資料夾名>）」→ 確認卡 → `POST /api/settings/update/rollback {"confirm": true}` →
   `Update.bat -Rollback -FromWeb`（既有的 `Restore-Previous`），一樣等 `/alive`。

**不變的**：沒有簽章的版本網頁不換（卡片照舊給「打開更新視窗…」，在 Update.bat 視窗裡自己決定要不要 `-AllowUnsigned`）；不降級；`config.json`、`data\`、`packs\`、`.venv\`、`runtime\` 不動；
`Update.bat` 照樣能單獨用；`update.ps1` 不自己比版本號。

**三種裝法**：

| 裝法 | 這次怎麼做 |
|---|---|
| ZIP（Windows） | 上面那條 |
| ZIP（不是 Windows） | 不給按鈕（`update.ps1` 是 PowerShell）；照舊說明手動 |
| git clone | 不給按鈕，照舊說「`git pull`」（自動蓋檔會蓋掉使用者改過的檔）。**但第 2 節的套件同步對它一樣有效**：`git pull` 之後下次啟動就補齊 |
| 安裝程式（.exe） | **這次不改**（只顯示「下載新的安裝程式」），見決定 W3 |
| Docker | 不改（compose 三行） |

## 2. 啟動時把套件補齊（`synox run` 一開始、讀完設定、開 bot 之前）

`src/synox/update/deps.py`：

1. **這版要什麼**：讀 SYNOX 資料夾的 `pyproject.toml`（`tomllib`）：`[project] dependencies` ＋ 選裝組（`dev` 不算）。
   `name @ <wheel 網址>` 的版本從 wheel 檔名讀（`ntu_easy_llm-0.6.0a2-…whl` → `0.6.0a2`）；`name>=x` 照範圍。
2. **要哪幾組選裝組**：記在 **`data/deps.json`**（`{"schema_version": 1, "extras": [...], "last": {...}}`），換版本、重建 `.venv` 都不會不見。
   每次啟動＝**記著的 ∪ 現在 `.venv` 裡看得出來有裝的**（那一組的每個套件都在；`ntu_easy_llm[llop]` 要它的 llop 那幾個相依也都在），再寫回去。
   所以 Setup.bat 裝的 `[llm]`、自己手動 `pip install -e .[llop]` 的，第一次啟動就記住了。不要某一組：`synox deps sync --remove llop`。
3. **比**：每個要的套件，`.venv` 裡沒有＝要裝；版本比要的**舊**＝要升；比要的**新**＝不動（不降級，例如自己裝了更新的 ntu_easy_llm）；
   帶選裝組的（`ntu_easy_llm[llop]`）它的那幾個相依沒有＝要裝。只讀套件的版本資訊，不連網、不 import 那些套件，平常啟動多花不到一秒。
4. **補**：有要補的才叫 `.venv` 的 pip：`python -m pip install --timeout 20 --retries 1 "<要求>"…`（同一個套件的好幾組合成一行，例如
   `ntu_easy_llm[llop] @ <網址>`），最多 10 分鐘；裝完再比一次。視窗裡印一行「🔧 這版要的套件跟裝著的不一樣，補裝：ntu_easy_llm 0.5.0 → 0.6.0a2 …」。
   pip 的完整輸出寫 `data/logs/deps-pip.log`。
5. **失敗也照常啟動**：每個沒補到的套件一句白話（「ntu_easy_llm 沒有更新到 0.6.0a2（現在是 0.5.0）：連不到網路。」）＋怎麼補
   （網頁「SYNOX 更新」卡片按「再試一次」、或在 SYNOX 資料夾打 `.venv\Scripts\python.exe -m synox deps sync`；下次啟動也會再試）。
   印在視窗、記 log、存進 `data/deps.json`，網頁卡片顯示。**同一組要求失敗後 6 小時內啟動不再自動重試**（不然沒網路時每次啟動都卡在 pip）；
   按「再試一次」、`synox deps sync` 不受這個限制。
6. **什麼時候只看不裝**：不是用 SYNOX 自己的 `.venv` 跑的（開發者的環境、測試）、Docker、環境變數 `SYNOX_DEPS_SYNC=off`、沒有 `pyproject.toml`、
   讀不出版本規則（沒有 `packaging`）。這時只把差異寫進 log 與卡片，叫使用者自己裝。
7. 網頁卡片的「再試一次」＝`POST /api/settings/update/deps`（只有擁有者、要解鎖）：背景跑同一個函式；裝好了提示「重新啟動 SYNOX 才會用新版」＋按鈕。
8. `prepare.deps_fingerprint` 改成讀整份相依（`dependencies`、`requires-python`、**全部**選裝組），讀不了才退回原本的逐行比對。

## 3. 安全界線

| 規則 | 做法 |
|---|---|
| 只有擁有者能按 | `/api/settings/update/*` 一律 `_owner_only`；`start`、`rollback`、`deps` 是改東西的 POST，照 `guard/stepup.py` 要先解鎖（動作名「更新 SYNOX」「退回上一版 SYNOX」「補裝 SYNOX 的套件」） |
| 簽章不過就不換 | 網頁這條**只收有簽章、驗過的**版本（`prepare(allow_unsigned=False)`；`update.ps1 -Apply` 再看一次 `ready.json` 的 `signed`）。簽章不對＝跟以前一樣拒絕 |
| 換的就是使用者看到的那一版 | `start` 要帶版本；`prepare(expect=X)` 查到的不是 X 就停 |
| 不偷連網 | 只在擁有者按了才連 GitHub；套件同步只在「要的跟裝的不一樣」時才叫 pip（目的地是 `pyproject.toml` 寫死的，跟 Setup.bat 一樣） |
| 能退回 | 舊版留在 `_previous\`（2 份）；網頁「回到上一版」＝`Update.bat -Rollback`；換完版本不對自動退回 |
| 一次一個 | 更新、補裝套件各自一次只能有一個在跑（第二次按＝「已經在跑了」） |
| 不自動安裝 | 「有新版」只顯示；**一定要擁有者按**（見 W1） |

## 4. 為什麼不選別的

- **在 SYNOX 自己的程序裡換檔**：Windows 會鎖住 `.venv` 的 `python.exe` 與已經 import 的檔；而且換到一半當掉就沒有人退回。換檔留給 `update.ps1`（0023 決定 U4）。
- **網頁只打開 Update.bat（現況）**：視窗還要再問一次 Y，跟擁有者要的「按一下」不一樣；下載、驗證的進度網頁也看不到。
- **套件同步放在 Start.bat**：.bat 讀不了 pyproject、比不了版本；放在 Python 可以測，`git pull`、手動蓋 ZIP、Update.bat 三條路都會經過 `synox run`。
- **每次啟動都 `pip install -e .[llm,llop]`**：要網路、慢、而且 pip 對網址形式的要求不一定會換版本；先比再裝只在需要時連網。
- **把選裝組記在 config.json**：那是使用者的設定，啟動時自動改它不好；`.venv` 旁邊又會在重建 `.venv` 時不見。所以放 `data/deps.json`（有 `schema_version`）。

## 5. 沒有驗證的（要在 Windows 真機試，寫進 HumanTestList.md）

- 網頁按「更新到 X」→ `Update.bat -Apply -FromWeb` 的視窗、停 SYNOX、換檔、`Start.bat --no-browser` 開回來、網頁自己重新整理。
- 網頁「回到上一版」。
- 換完之後第一次啟動時 pip 真的把 ntu_easy_llm 0.5 升到 0.6.0a2（含 `[llop]`），以及沒網路時照常啟動、卡片說哪個沒補到。
- 這台是 Windows，但**測試不連網、不跑 pip、不換自己的安裝**；PowerShell 只做靜態檢查。

## 6. 擁有者要決定的

| # | 問題 | 選項 | 建議（現在照這個做） |
|---|---|---|---|
| W1 | 自動更新，還是只能手按 | A 只能手按（每週檢查照舊只通知）／B 每週檢查查到新的**正式版**就自動換／C 只有安全更新自動換 | **A**。0023 第 7 節「沒有自動安裝」；換版本會關掉 SYNOX、可能要下載套件，不該在使用者不知道時發生。要改 B／C：`weekly_tick` 查到新版時呼叫 `web_api` 的同一個 `start`，加一個設定開關 |
| W2 | 啟動時補裝套件要不要先問 | A 自動補（失敗照常啟動、說怎麼補）／B 先問（網頁卡片列出來、按了才裝）／C 只提醒、不裝 | **A**（擁有者說「要自動補裝或升級」）。補的只會是這版 `pyproject.toml` 寫死的套件與網址，跟 Setup.bat 裝的一樣。要改 B／C：`SYNOX_DEPS_SYNC=off` 已經是 C；B 要在 `deps.sync_at_start` 前面加一個設定開關 |
| W3 | 安裝程式（.exe）裝的怎麼辦 | A 照舊：卡片說「下載新的安裝程式」＋發佈頁連結／B 網頁下載、驗過簽章的 `SYNOX-Setup-X.exe` 之後**打開讓人自己按下一步**／C 也走 ZIP 換檔 | **A（這次）→ B（之後）**。B 要先在真機確認「同一個 AppId 覆蓋安裝」會保留 `config.json`、`data`、`packs`，安裝程式也要能先關掉 SYNOX；`release.json` 也要簽 exe 的指紋（現在有）。C 不建議：「應用程式與功能」裡的版本號不會變、`unins000.*` 會被搬進 `_previous`、解除安裝會漏刪新檔 |
| W4 | 測試版在網頁上能不能直接換 | A 照通道：打開「也提醒我有測試版」的人，網頁的「更新到 X（測試版）」也能直接換／B 網頁只換正式版，測試版一律用 Update.bat | **A**（擁有者說「測試版的通道照既有設定」）。卡片上寫目前的通道，按鈕寫「（測試版）」 |
