# 版本與發佈規則

- 狀態：**已採用**（擁有者 2026-11-14；2026-11-19 補齊排序、升級矩陣、錯版補救、通道與相容欄位：[adr/0043](adr/0043-version-order-and-upgrade-matrix.md)）。
  工具：`scripts/release.py`（升號、檢查、發佈說明、簽章）、`scripts/check_version_consistency.py`（發佈前的版本一致檢查）。
- 目前版本：`0.2.2-alpha.1`（`dev` 上的號碼＝下一個要發的版本，還沒發；最新的 tag 是 `v0.2.1-beta.2`，見 §13）
- 自己會更新：**有**（[adr/0023](adr/0023-updates-and-hotfixes.md)）：「檢查更新」（按了才查；每週檢查要自己打開）、ZIP 裝的用 `Update.bat`、退回用 `Update.bat -Rollback`。

---

## 一般人看這段

**版本號長這樣：`0.2.2`。** 三個數字，越大越新（`0.2.10` 比 `0.2.9` 新）。後面有沒有尾巴，意思不一樣：

| 長相 | 叫什麼 | 給誰 | 你該不該裝 |
|---|---|---|---|
| `0.2.2` | **正式版** | 所有人 | ✅ 裝這個。有了正式版之後，介紹頁的「⬇ 下載 SYNOX」、GitHub 的 `main` 就是最新的正式版（還沒有正式版的現在，它們是最新發佈的預覽版，見 §8） |
| `0.2.2-beta.1` | **測試版（beta）** | 願意幫忙試用、回報問題的人 | 想先試新東西再裝；平常在用、不想遇到問題就等正式版 |
| `0.2.2-alpha.1` | **內部測試版（alpha）** | SYNOX 團隊自己 | ❌ 一般人不要裝 |

同一個號碼的順序是 **alpha → beta → 正式版**；下一個號碼的 alpha 又比上一個號碼的任何版本新：
`0.2.1-beta.2 < 0.2.2-alpha.1 < 0.2.2-beta.1 < 0.2.2 < 0.2.3-alpha.1`。

**我裝的是不是最新版？**

1. 看自己的版本：在 SYNOX 資料夾打 `.venv\Scripts\synox about`（或 `synox doctor`），第一行就是版本，下面一行是發佈頁的網址。
2. 打開發佈頁 <https://github.com/ChouYangEn0401/SYNOX/releases>，標著 **Latest** 的就是最新正式版。數字一樣＝你是最新的。
3. 每一版的發佈頁都有三段：**這版改了什麼**、**要不要更新**、**怎麼更新**。寫「強烈建議更新」的是修了安全問題，請盡快更新。

**看有沒有新版最快的方法**：網頁「設定 → 💻 電腦與備份 → 檢查更新」，或在 SYNOX 資料夾打 `.venv\Scripts\synox update --check`。SYNOX **只有你按了才去問 GitHub**；想要它每週自己看一次（只看，不會自己裝），在安裝精靈最後一頁或同一張卡片勾「每週幫我看一次有沒有新版」（預設不勾：沒勾的話，有安全更新也要你自己來按才會知道）。一般人只會看到**正式版**，beta 不會跳出來。更新**一定先問你**，SYNOX 不會自己換掉自己（[adr/0023](adr/0023-updates-and-hotfixes.md)）。

**我裝的是測試版（alpha／beta）**：「檢查更新」還是只告訴你**正式版**（同號或更新的正式版出來時會說有新版；比你舊的正式版會說「你裝的比較新」，不會叫你降級）。
下一個 alpha／beta 要自己到發佈頁看（或 `synox update --check --include-prerelease`），下載它的 `SYNOX-<版本>.zip`＋`SHA256SUMS.txt`
放同一個資料夾，再 `Update.bat -FromZip <那個 ZIP>`（還沒有簽章時加 `-AllowUnsigned`）。alpha → beta → 下一版都這樣升，設定、資料、工具都不動。

### 我要怎麼更新？

更新**不會**動到你的設定（`config.json`）、資料（`data` 資料夾：筆記、記帳、保管箱、金鑰）和裝好的工具（`packs` 資料夾）。

| 你是 | 怎麼更新 | 備註 |
|---|---|---|
| **用 ZIP 的人**（從介紹頁或發佈頁下載、解開、點 `Setup.bat`） | **點兩下 SYNOX 資料夾裡的 `Update.bat`**（或網頁「檢查更新」之後按「更新…」）：它先給你看這版改了什麼、問你一次，再下載、核對檔案、關掉 SYNOX、換好、重新打開。舊版的程式留在 `_previous` 資料夾（最近 2 份），出問題點 `Update.bat -Rollback` 就回到上一版。那一版**沒有簽章**時（現在都還沒有，見 [release-build.md](release-build.md)「發佈簽章金鑰」），Update.bat 會說明，你要明確打 `Update.bat -AllowUnsigned` 才換。<br>舊版（還沒有 Update.bat）或想自己來：① 點兩下 `Stop.bat` 關掉 SYNOX ② 到發佈頁下載新的 `SYNOX-<版本>.zip`（或介紹頁的「⬇ 下載 SYNOX」）③ 解開 ④ 把裡面 `SYNOX`（或 `SYNOX-main`）資料夾的**全部內容**複製到你原本的 SYNOX 資料夾，問要不要取代就選「**取代**」⑤ 點兩下 `Setup.bat` | 新的 ZIP 裡沒有 `config.json`、`data`、`packs`，所以蓋不掉你的東西。`Setup.bat` 重跑是安全的：只更新套件、最後打開精靈——直接關掉精靈就好，設定都還在。舊的 ZIP 帶的開發用檔案（`tests`、`evals`、`docs\lab`、`docs\ui`、`docs\installer`…）和 `Connect-Apple.bat`、根目錄的 `GOVERNANCE.md`／`MAINTAINERS.md`／`TRADEMARK.md`（搬進 `.github`），新的 ZIP 不帶了：留著不會被讀，想清就自己刪（Apple 帳號改用 `.venv\Scripts\python.exe -m synox connect apple-reminders`） |
| **用 git 的人** | `Stop.bat` → `git pull`（在 `main` 上）→ `Setup.bat` | 只要某一版：`git fetch --tags` → `git checkout v0.2.2`。用 Docker：`git pull` → `docker compose build` → `docker compose up -d`（[docker.md](docker.md)） |
| **用安裝程式（.exe）的人** | 下載新的 `SYNOX-Setup-<版本>.exe`，裝在原本的位置（預設就是） | 設計上會保留 `config.json`、`data`、`packs`（[adr/0003](adr/0003-distribution-git-clone-and-installer.md) B），舊版才有的開發用檔案會自動刪掉；**還沒在真機驗證過**。注意：安裝程式**不會**擋「用舊的 exe 蓋掉新版」（§6），只用比你裝的新的安裝檔 |
| **工具（工具庫的 pack）** | 網頁「設定 → 功能與安裝 → 工具庫（官方）」按「載入工具清單」：有新版的工具會標出來，按「更新到 v…」，或上面的「全部更新」（一個一個給你看報告）。命令列：`synox tools check`（只看）、`synox tools update <名字…>` 或 `--all`。或拿到新的 `.synoxpack` 再裝一次 | 同名再裝＝升級：先給你看「改了什麼」（權限變大是紅字），你按確認才換。不滿意：`synox packs rollback <工具名>` 退回上一版。工具自己的資料不會動。新版要更新的 SYNOX 才能用時，卡片寫「⛔ 這台的 SYNOX 用不了這一版」，不算在「可以更新」裡（§6） |
| **寫工具的人（SDK）** | 先照上面更新 SYNOX → `pip install -U <SYNOX 資料夾>/sdk`（或重新複製 `sdk/synox_sdk.py` 到你的工具旁邊）→ `synox-sdk check .` | 看 [sdk.md](sdk.md)「SDK 版本」：SDK 第二個數字變了（例如 0.2 → 0.3）才要改 `requires.sdk` 並重新測；只變最後一個數字不用改 |

更新完可以跑 `synox doctor` 看一次（版本對了、沒有紅字就好）。出問題想回到上一版：用 Update.bat 更新的點兩下 `Update.bat -Rollback`；手動蓋的人先別刪舊的 ZIP、照同樣方法蓋回去；
git 的人 `git checkout v<上一版>` 再跑 `Setup.bat`。**從 0.2.0 更新到 0.2.1 以後任何一版的人**：內建工具都搬進工具庫了，更新完到「設定 → 🧩 功能與安裝 → 工具庫」把要用的工具裝回來（資料還在）。

---

## 維護者

### 1. 版本號與排序：SemVer 2.0.0

SYNOX 本體、SDK、每個工具（pack.json）、工具庫的 tag 全部用 [SemVer 2.0.0](https://semver.org/spec/v2.0.0.html)，比新舊**只照它的排序**：

1. `X.Y.Z` 三段**按數值**比：`1.0.9 < 1.0.10`、`0.9.9 < 0.10.0`。
2. 同一個 `X.Y.Z`：**預覽版 < 正式版**（`0.2.2-rc.1 < 0.2.2`）。
3. 預覽版的尾巴用 `.` 分段、逐段比：數字段**按數值**（`alpha.2 < alpha.10`）；數字段 < 文字段；文字段照 ASCII，所以 **`alpha < beta < rc`**；
   前面都一樣時段數少的較舊（`alpha < alpha.1`）。
4. `+build`（建置資訊）**不看**：`1.0.0+a` 跟 `1.0.0+b` 一樣新。
5. 不是 SemVer 的（`1.0`、`v1.0.0`、`01.0.0`、預覽版數字段前面補 0 的 `alpha.01`）＝**比不出來**：不會被當成新版，也不會被當成舊版。

```
0.2.1-alpha.1 < 0.2.1-beta.1 < 0.2.1-beta.2 < 0.2.2-alpha.1 < 0.2.2-alpha.2 < 0.2.2-beta.1 < 0.2.2-rc.1 < 0.2.2 < 0.2.3-alpha.1
```

**SYNOX 發版只用三種長相**（`scripts/release.py` 的 `VERSION_RE`，別的一律不收；`rc` 保留不用，要用先改 release.py 與這份）：

```
X.Y.Z              正式版           例 0.2.2
X.Y.Z-beta.N       外部測試         例 0.2.2-beta.1（N 從 1 開始）
X.Y.Z-alpha.N      內部測試         例 0.2.2-alpha.1
```

`pip` 會把它正規化成 `0.2.2a1`／`0.2.2b1`，是同一個版本；`synox.__version__` 照原樣寫。
工具的版本也要是 SemVer（建議同樣只用 `-alpha.N`／`-beta.N`；不要用 `+build`，工具庫的清單不收）。

**每個比版本的地方**（都照上面的規則；`tests/test_version_rules.py`、`tests/js/test_semver.js` 把整個矩陣都測過）：

| 地方 | 怎麼比 | 程式 |
|---|---|---|
| SYNOX 檢查更新、`Update.bat`、`Update.bat -FromZip`、`release.json` 的 `min_from` | 自己寫的 SemVer 排序鍵（不用 `packaging`） | `update/check.compare` → `packs/upgrade.semver_key` |
| 工具同名再裝＝升級／降級 | 同一個 `semver_key` | `packs/upgrade.compare_versions` |
| 工具庫清單「有新版」、`synox tools check／update`、每週檢查 | 同一個 `semver_key`，再看清單上的 `requires`（§6） | `packs/catalog._newer`、`catalog.blocked`、`catalog.updates` |
| 網頁的工具庫、衣櫃（裝好之後在瀏覽器重算「有新版」） | 同一套規則的 JS 版 | `web/static/semver.js`（`SynoxSemver.newer`） |
| 工具的 `requires.synox`／`requires.sdk`／`requires.packs` | **只比 `X.Y.Z`、預覽版的尾巴不看**（刻意的，§6） | `packs/manifest._version_tuple`、`_range_problem` |
| 發版小幫手：下一個號碼 | 結果一定排在現在的後面（測試擋） | `scripts/release.py next_version` |
| 發佈前：版本要比每個 tag 新 | 同一套規則（只用標準函式庫的一份） | `scripts/check_version_consistency.py` |
| 安裝程式（`.iss`） | **不比**（§6「安裝程式的限制」） | — |
| `update.ps1` 換完檔 | 只比「新版的 `__version__` 是不是剛剛準備的那一個」（字串相等） | `setup/update.ps1` |

### 2. 版本寫在哪：唯一來源與同步

| 東西 | 唯一來源 | 跟著它的（不要手改） | 誰同步、誰檢查 |
|---|---|---|---|
| **SYNOX 本體** | `pyproject.toml` 的 `[project] version` | `src/synox/__init__.py` 的 `__version__`（一定一樣）；CHANGELOG 最上面那一節；tag `v<版本>`；安裝程式 `SYNOX-Setup-<版本>.exe`（建置時 `/DAppVersion=` 從 `installer_ci.py version` 帶入，`.iss` 檔裡只留 `0.0.0` 的預設）；ZIP `SYNOX-<版本>.zip`；`release.json` 的 `version`；這份文件最上面的「目前版本」 | `release.py bump` 一起改 `pyproject.toml`＋`__init__.py`＋CHANGELOG；`release.py check`、`installer_ci.py version`、`check_version_consistency.py` 擋不一樣的 |
| 介紹頁的版本徽章 | 跟著 SYNOX 本體 | `docs/landing/page.html` | 介紹頁的維護者改；`release.py check` 與 `check_version_consistency.py` 只提醒 |
| **SDK**（給工具的介面合約） | `src/synox/sdk/author.py` 的 `SDK_VERSION` | `sdk/synox_sdk.py`（`scripts/build_synox_sdk.py` 產生）、`sdk/pyproject.toml` | `release.py check` 擋單檔版不一樣的 |
| **每個工具／外觀包** | 那個工具的 `pack.json` 的 `version`（與 `requires`） | 工具庫 `scripts/build.py` 產生的 `index.json` 那一筆（`version`、`requires.synox`、`requires.sdk`、`file`、`sha256`）、`<name>-<版本>.synoxpack` | 工具庫的 build 與測試 |
| **工具庫 SYNOX_Libs** | 那個 repo 的 `VERSION` | tag `v<VERSION>`、`index.json` 的 `library_version`、`tools-<VERSION>.zip` | 工具庫的 `docs/RELEASING.md` |
| SYNOX 讀哪一版工具庫 | 網頁：`src/synox/packs/catalog.py` 的 `OFFICIAL_INDEX_URL`；安裝程式帶的：`.github/workflows/build-installer.yml` 的 `LIBS_TAG`＋sha256 | — | 換工具庫 tag 時手改（[release-playbook.md](release-playbook.md) 第 2 節） |

### 3. 怎麼升號

**升哪一個數字**——只問一句：「使用者更新之後，要不要多做事，或舊的工具會不會壞？」

| 升 | 什麼時候 | 例子 |
|---|---|---|
| **PATCH**（0.2.0 → 0.2.1） | **每一次 `dev` 合進 `main` 的一般發版**；修錯、安全修正（hotfix）、小功能、文件。舊的 `config.json`、`data`、工具照用 | 修精靈的按鈕被擠掉；工具庫卡片多「有新版」 |
| **MINOR**（0.2.x → 0.3.0） | 會：`config.json` 或 `data` 的格式要轉換；pack.json 多了舊 SYNOX 讀不懂、工具開始依賴的欄位（新工具要寫 `requires.synox: ">=0.3"`）；拿掉指令或功能；換最低 Python；架構大改 | 0.1.0 → 0.2.0：pack 格式多了 surfaces／data／auth.fields／mcp… |
| MAJOR（0.x → 1.0.0） | 擁有者宣布「穩定、之後不隨便破壞相容」的那天。0.x 期間不升 | — |

拿不準就升 MINOR，並在 CHANGELOG 那一節第一行寫「更新後要做什麼」。**alpha／beta 不是必經**：小的 PATCH 可以直接發正式版；改了安裝流程、資料格式、權限的版本，至少走一輪 beta。

**`python scripts/release.py bump <種類>`**（改 `pyproject.toml`＋`__init__.py`＋CHANGELOG，印 diff，不 commit；`--dry-run` 只印）：

| 現在 | 想發 | 指令 | 結果 |
|---|---|---|---|
| `0.2.2` | 下一個正式版 | `bump patch`（或 `minor`） | `0.2.3`（`0.3.0`） |
| `0.2.2` | 下一輪預覽 | `bump alpha`／`bump beta`（`--next minor`＝下一個 MINOR） | `0.2.3-alpha.1`／`0.2.3-beta.1`（`0.3.0-…`） |
| `0.2.2-alpha.1` | 再一個 alpha／換 beta | `bump alpha`／`bump beta` | `0.2.2-alpha.2`／`0.2.2-beta.1` |
| `0.2.2-beta.1` | 再一個 beta | `bump beta` | `0.2.2-beta.2` |
| `0.2.2-beta.N`（或 alpha） | 它的正式版 | `bump final` | `0.2.2` |
| `0.2.1-beta.2` | **又要回內部測試** | `bump alpha --next patch` | `0.2.2-alpha.1`（**同號不能退回 alpha**：`0.2.1-alpha.3` 會排在已發的 beta 前面，檢查更新當成舊版；單打 `bump alpha` 會拒絕並給這個指令） |
| `0.2.1-beta.2` | 放棄 0.2.1 的正式版，直接下一號的 beta | `bump beta --next patch` | `0.2.2-beta.1` |
| `dev` 已經是下一版（`## X（未發佈）`） | 發這一版、號碼不變 | `bump keep` | 號碼不動；那一節寫上日期，後來的「未發佈」收進去 |

bump 出來的號碼**一定排在現在的後面**（測試擋）。

**`dev` 帶著下一版的號碼**：一版發完、合回 `dev` 之後，在 `dev` 上 `bump <種類> --planned`：版本改成下一個要發的號碼，CHANGELOG 最上面開
`## <版本>（未發佈）`（沒有日期）。之後每個分支照舊在最上面加 `## 未發佈（主題）`；發版那天 `bump keep` 把那一節寫上日期、把後來的「未發佈」
收進去。擁有者改主意（例如這一版要直接發 beta）：`bump beta` 會把還沒發的那一節**改名**，不會留一個沒發過的版本。
所以 `dev` 上的版本號永遠**比最新的 tag 新**（`check_version_consistency.py` 檢查）。

### 4. CHANGELOG

- 版本**由新到舊**，最上面一節就是 `pyproject.toml` 的版本；每個預覽版有**自己的一節**（`## 0.2.1-beta.2（2026-11-18）`、`## 0.2.1-beta.1（…）`、
  `## 0.2.1-alpha.1（…）`），正式版那一節第一行寫「也包含哪些預覽版的改動」（`bump final` 自動寫）。
- 標題只有三種：`## X.Y.Z[-alpha.N|-beta.N]（YYYY-MM-DD）`（發了）、`## X.Y.Z…（未發佈）`（`dev` 上的下一版）、`## 未發佈（主題或分支）`（分支合進來還沒收）。
  分支的小標題寫 `#### 新增`／`#### 修正`…；`bump` 收進去時分支標題變 `### 主題`，小標題留在它下面一層。
- 打了 tag 卻沒發佈的也有一節，寫清楚「tag 打了、沒有發佈、為什麼」（例：`0.2.1-beta.1`，說明在 `0.2.1-beta.2` 那一節）。
- 不刪舊內容；放錯版本的段落搬到它真正發佈的那一版，寫一句說明（例：0.2.1-alpha.1 最後那四節）。

### 5. 錯版了怎麼補救

- **發出去的 tag 不移動、不刪、不重打；版本號不重用。** 發錯（內容錯、附檔錯、號碼排錯）一律**發下一個更高的號碼**，CHANGELOG 那一節說明。
- 號碼排錯（例如在已發的 beta 之後發了同號的 alpha）：使用者的「檢查更新」會把它當成舊版、不會提供。補救：發一個排在**所有已發 tag 之後**的號碼
  （`bump alpha --next patch` 或 `bump beta`），把錯的那一版在 GitHub 標成 pre-release（或從 Latest 拿掉），不要刪。
- 附檔傳錯但號碼沒錯：`gh release upload --clobber` 換附檔、`release.json` 重簽（[release-playbook.md](release-playbook.md) 第 5 節）。
- 發版前一定跑 `python scripts/check_version_consistency.py --tag v<版本>`：號碼比每個本機 tag 新、沒有重用、各處一致，才打 tag。
- 工具也一樣：發出去的 `<name>-<版本>.synoxpack` 不換內容；修了就升工具的版本（PATCH 或下一個預覽號）。

### 6. 升級矩陣與相容

**SYNOX 本體**（「檢查更新」與 `Update.bat` 下載只看正式版，§7；`-FromZip`、安裝程式、git 可以裝任何一版）：

| 從 → 到 | 例子 | 檢查更新 | `Update.bat`（下載） | `Update.bat -FromZip` | 現況 |
|---|---|---|---|---|---|
| alpha → 同號 alpha | `0.2.2-alpha.1 → 0.2.2-alpha.2` | 不提示（預覽版） | 不裝預覽版 | ✅ 升級 | 通過 |
| alpha → 同號 beta | `0.2.2-alpha.2 → 0.2.2-beta.1` | 不提示 | 不裝預覽版 | ✅ 升級 | 通過 |
| beta → beta | `0.2.1-beta.1 → 0.2.1-beta.2` | 不提示 | 不裝預覽版 | ✅ 升級 | 通過 |
| beta → 下一號的 alpha | `0.2.1-beta.2 → 0.2.2-alpha.1` | 不提示 | 不裝預覽版 | ✅ 升級 | 通過 |
| alpha／beta → 同號正式版 | `0.2.2-beta.1 → 0.2.2` | ✅ 有新版 | ✅ | ✅ | 通過 |
| 正式版 → 下一個正式版 | `0.2.2 → 0.2.3`、`0.2.9 → 0.2.10` | ✅ 有新版 | ✅ | ✅ | 通過 |
| 正式版 → 下一號的 alpha／beta | `0.2.2 → 0.2.3-alpha.1` | 不提示 | 不裝預覽版 | ✅ 升級 | 通過 |
| 降級：正式版 → 舊的 beta／舊版 | `0.2.2 → 0.2.2-beta.1` | 「你裝的比較新」 | 拒絕（不降級） | 拒絕（不降級） | 通過；要回去用 `Update.bat -Rollback` |
| 一樣的版本 | `+build` 不同也算一樣 | 「已經是最新」 | 不做 | 不做 | 通過 |

`release.json` 可以寫 `min_from`（`release.py sign --min-from`）：比它舊的版本不能直接跳到這一版（中間有資料要轉換），會說先更新到哪一版。

**工具**（同名再裝、工具庫的「更新到 v…」、`synox tools update`）：`0.1.2 → 0.1.3-alpha.1 → 0.1.3-beta.1 → 0.1.3 → 0.1.10 → 1.0.10`
每一步都是升級；反過來是**降級**，要明確選「降級／重裝」（命令列與網頁都一樣）；`synox packs rollback` 是另一條明確的路。
工具庫清單（`index.json`）**每個工具只列一個版本**，那就是它的通道：清單上放預覽版，裝了舊版的人就會看到它是新版——要分通道就在工具庫分清單，SYNOX 不另外判斷。

**相容欄位**（每個工具的 pack.json）：

```json
"requires": { "synox": ">=0.2", "sdk": ">=0.2,<0.3" }
```

- `requires.synox`＝要多新的 SYNOX；`requires.sdk`＝照哪一版合約寫的（`synox-sdk init` 自動寫 `>=0.2,<0.3`，0.x 寫到下一個 MINOR）；
  `requires.packs`＝要先裝哪些工具（`"notes>=0.2"`）。範圍可以用 `>=`、`>`、`<=`、`<`、`==`、`!=`，逗號接好幾個；只寫 `X.Y` 或 `X.Y.Z`。
- **只比數字 `X.Y.Z`，預覽版的尾巴不看**（`manifest._version_tuple`）：`0.2.5-alpha.1` 當成 `0.2.5`。所以工具寫 `>=0.2.5`，
  0.2.5 的 alpha／beta 也裝得上——寫工具的人可以先用預覽版測。這是跟 SemVer 不一樣的刻意選擇（SemVer 的 `0.2.5-alpha.1` 比 `0.2.5` 舊）。
- 不相容時：
  - **安裝**（第 1、2 關）：不裝，一句人話「先更新 SYNOX」或「請向作者要新版」（`packs/manifest.synox_problem`）。
  - **載入**（已經裝了，SYNOX 換回舊版之類）：狀態 incompatible、不載入；`doctor`、`packs status`、`/bot_status` 都說同一句。
  - **工具庫清單**（`index.json` 帶 `requires`）：那一版的卡片寫「⛔ 這台的 SYNOX 用不了這一版」（說明是同一句），**不算「有新版」**：
    不出「更新到 v…」、不算在「有 N 個可以更新」、`synox tools update --all` 與每週檢查都跳過；先更新 SYNOX 就會出現。

**安裝程式（`.iss`）的限制**：Inno Setup 不比版本——拿舊的 `SYNOX-Setup-0.2.1-beta.2.exe` 裝在 0.2.2 上面，會直接把程式換回舊版
（`config.json`、`data`、`packs` 照樣保留）。最小修法（還沒做，要在 Windows 上建置、實際裝一次才能合；沒驗證過不要改 `.iss`）：
`[Code]` 的 `InitializeSetup` 讀已安裝那份 `{app}\installer-choices.json` 的 `"version"`（或解除安裝登錄的 `DisplayVersion`），
用跟 §1 一樣的規則比；新的比較舊就 `MsgBox`「你裝的 X 比這個安裝檔新，確定要換回舊版？」預設「否」，`/SILENT` 時直接中止（除非加 `/ALLOWDOWNGRADE`）。
在那之前，發佈說明的「怎麼更新」寫清楚：只用比自己新的安裝檔。

### 7. 通道：誰會被通知哪一種版本

| 你裝的 | 「檢查更新」／每週檢查／`Update.bat` 告訴你 | 怎麼拿到預覽版 |
|---|---|---|
| 正式版（預設） | 只有比你新的**正式版** | 不會被通知；想試就自己到發佈頁或 `synox update --check --include-prerelease` |
| alpha／beta | 一樣只有**正式版**：同號或更新的正式版出來就提示；比你舊的正式版說「你裝的比較新」 | 下一個 alpha／beta 自己看發佈頁或 `--include-prerelease`，用 `Update.bat -FromZip` 裝 |

依據 [adr/0023](adr/0023-updates-and-hotfixes.md) 決定 U3（App 只看正式版）。GitHub 的 `releases/latest` 本來就不含 pre-release，程式再擋一次。
「裝了預覽版的人要不要自動收到下一個預覽版」是擁有者的決定（[adr/0043](adr/0043-version-order-and-upgrade-matrix.md)「待決定」），決定之前照上表。

### 8. 分支：dev → release → main

```
feat/… ──► dev ──► release/0.2.2 ──(bump final)──► main ── tag v0.2.2
                    │  tag v0.2.2-alpha.1、v0.2.2-beta.1（在 release 分支上）
                    └──► 修正同時合回 dev
main ── hotfix/0.2.3 ──(bump patch)──► main ── tag v0.2.3 ──► 合回 dev（與開著的 release/…）
```

- **`dev`**：每天開發。帶著下一版的號碼與 `## X（未發佈）`（§3）；每個分支在 `CHANGELOG.md` 最上面加一節 `## 未發佈（分支或主題）`。
- **`release/X.Y.Z`**：要發版時從 `dev` 切出來。之後只收修正（修正也要合回 `dev`），不收新功能。alpha／beta 的 tag 打在這條分支上。
  **發版的 commit 一定要合回 `dev`**（不然 `dev` 的 CHANGELOG 會少那一節，像 `0.2.1-beta.2` 那次）。
- **`main`：只在發佈時動**。`main` 的內容永遠等於某個發佈出去的 tag（合進來的是打了 tag 的那個 commit）——所以介紹頁的「⬇ 下載 SYNOX」（`main` 的 ZIP）
  一定是最新的發佈。不在 `main` 上直接 commit。
  - **alpha 階段（現在，還沒有正式版）**：擁有者 2026-11-19 決定 `main` 跟著最新的發佈走，預覽版也算——每發一版（alpha／beta），
    發佈之後把 `release/X.Y.Z` 用 `git merge --no-ff` 合進 `main`（同時合回 `dev`）。所以這段時間介紹頁下載到的是最新的預覽版。
  - **有了正式版之後**：要不要回到「`main` 只在正式版動、alpha／beta 不進 `main`」由維護者決定；決定之前照上一條。
- **`hotfix/X.Y.Z`**：正式版有急著修的問題（尤其安全）時，從 `main`（最新的 tag）切出來，只修那一件 → `bump patch` → 合進 `main`、打 tag、
  發佈 → **一定要合回 `dev`**（還有開著的 `release/…`），不然下一版會把修正弄丟。合回 `dev` 時 CHANGELOG 可能衝突：兩邊都留，
  hotfix 那一節放在 `dev` 的 `## X（未發佈）` 下面（`dev` 的號碼本來就比 hotfix 新）。
- tag 是 `vX.Y.Z`、`vX.Y.Z-beta.N`、`vX.Y.Z-alpha.N`，一定等於 `v`＋版本（`release.py check --tag`、`installer_ci.py`、`check_version_consistency.py --tag` 都檢查）。
  用有註解的 tag（`git tag -a v0.2.2 -m "SYNOX 0.2.2"`）。**發出去的 tag 不移動、不刪**（§5）。

### 9. 每一版都要有

1. **版本號**：`python scripts/release.py bump <patch|minor|alpha|beta|final|keep>`（§3）。
2. **CHANGELOG 一節，有日期**：`## 0.2.2（2026-11-30）`。`bump` 會把最上面所有「未發佈」收進這一節（每節變成 `### 主題`），印出 diff，
   不 commit；你再補一句「這版重點」。
3. **檢查**：`python scripts/release.py check --tag v0.2.2` 全綠（版本一致、SDK 單檔版跟正本一樣、有日期的那一節、沒有剩下的「未發佈」、tag 格式）；
   `python scripts/check_version_consistency.py --tag v0.2.2` 全綠（CHANGELOG 最上面、安裝器、文件的「目前版本」、比每個 tag 新）；
   全部測試；`scripts/prepublish_check.py --worktree-only`。
4. **GitHub release**：標題 `SYNOX 0.2.2`；說明用白話中文，三段 **這版改了什麼／要不要更新／怎麼更新**——`python scripts/release.py notes [--exe]`
   印出草稿，把技術句子改成一般人看得懂的話（一條一句；技術細節留在 CHANGELOG）。安全修正寫「**強烈建議更新**」。
   alpha／beta 勾 **Set as a pre-release**；正式版勾 **Set as the latest release**。
5. **附檔**：`SYNOX-0.2.2.zip`（`scripts/make_zip.py --tools <SYNOX_Libs 的 dist>`，裡面帶工具庫）＋ `SHA256SUMS.txt`（每個附檔一行）＋ `release.json`／`release.json.sig`（`python scripts/release.py sign --dist dist --key <私鑰檔>` 一次寫這三個；私鑰只在創始維護者手上，[release-build.md](release-build.md)「發佈簽章金鑰」）。**Update.bat 要有 ZIP 與 SHA256SUMS.txt 才會自動更新**；
   有做好、測過的安裝程式就附 `SYNOX-Setup-0.2.2.exe`（推 tag 時 `build-installer.yml` 會做、放進**草稿** release，[release-build.md](release-build.md)）。
   GitHub 自動附的「Source code (zip)」不用管。
6. **之後**：合回 `dev` 並 `bump <種類> --planned`（§3）；這份文件最上面的「目前版本」；介紹頁的版本徽章（請介紹頁維護者改）；
   [ecosystem.md](ecosystem.md)「文件維護清單」那一列「版本號」。

### 10. 發版步驟（照抄）

完整的手冊（先在 Windows 測更新、`gh` 指令、附檔、標 Latest、工具庫那邊、下載連結、出事怎麼退、給新 session 的檢查表）在
[release-playbook.md](release-playbook.md)；下面是最短的版本（例：`dev` 上是 `0.2.2-alpha.1（未發佈）`）。

```
git switch dev && git pull
git switch -c release/0.2.2
python scripts/release.py bump keep            # 號碼不變、寫上日期（要直接發 beta：bump beta）
#   看 diff、補 CHANGELOG 那一節 → commit
python scripts/release.py check --tag v0.2.2-alpha.1
python scripts/check_version_consistency.py --tag v0.2.2-alpha.1
git tag -a v0.2.2-alpha.1 -m "SYNOX 0.2.2-alpha.1" && git push origin release/0.2.2 v0.2.2-alpha.1
#   → 草稿 release 出現（有 exe 的話）→ 貼 notes、上傳 ZIP → 勾 pre-release → Publish
#   …測試、修正（修正也合回 dev）… 要外部試：bump beta → v0.2.2-beta.1
python scripts/release.py bump final           # 0.2.2-beta.N → 0.2.2；commit
python scripts/release.py check --tag v0.2.2 && python scripts/check_version_consistency.py --tag v0.2.2
git switch main && git merge --no-ff release/0.2.2
git tag -a v0.2.2 -m "SYNOX 0.2.2" && git push origin main v0.2.2
#   → 草稿 release：python scripts/release.py notes [--exe] 改成白話貼上、上傳 SYNOX-0.2.2.zip 與 SHA256SUMS.txt → Latest → Publish
git switch dev && git merge --no-ff release/0.2.2
python scripts/release.py bump alpha --planned # dev → 0.2.3-alpha.1（未發佈）；commit、push
```

推 `v*` tag 會觸發 `build-installer.yml`：它先跑 `check_version_consistency.py --tag`，再建草稿 release 並放 exe；**已經公開的 release 它不碰**（會失敗）。
所以順序是：推 tag → 等 workflow（失敗也沒關係，沒有 exe 照樣可以發）→ 在**同一個草稿**上補說明與 ZIP → Publish。沒有 workflow 時就自己 `New release` 選那個 tag。

### 11. SYNOX、SDK、工具庫：三個各自的版本

| 東西 | 版本寫在哪 | 現在 | 怎麼發 |
|---|---|---|---|
| **SYNOX 本體** | `pyproject.toml`＋`src/synox/__init__.py` | `0.2.2-alpha.1`（2026-11-19，`release/0.2.2`，tag `v0.2.2-alpha.1`）；上一個 tag `v0.2.1-beta.2` | 這份文件；tag `vX.Y.Z`（SYNOX repo） |
| **SDK**（給工具的介面合約） | 只寫在 `src/synox/sdk/author.py` 的 `SDK_VERSION`；`sdk/synox_sdk.py`、`sdk/pyproject.toml`（`synox-sdk` 套件）都讀它 | 0.2.5 | **跟著 SYNOX 一起發**（在 `sdk/` 裡），沒有自己的 tag／PyPI。不相容的改動升 MINOR（0.x），只加 API 升 PATCH（[sdk.md](sdk.md)「SDK 版本」） |
| **工具庫 SYNOX_Libs** | 另一個 repo；`VERSION`、每個工具 pack.json 的 `version`；發佈頁的 `index.json`（名字、版本、`requires`、sha256）與 `tools-<版本>.zip` | `v0.3.1`（安裝程式帶 `tools-0.3.1.zip`；網頁工具庫讀 `v0.3.1` 的 `index.json`；都還是 pre-release） | 自己的 tag 與 release。SYNOX 的網頁工具庫固定讀 `OFFICIAL_INDEX_URL`（釘一個 tag；工具庫標成 Latest 之後改成 `latest/download`，[release-playbook.md](release-playbook.md) 第 2 節），安裝程式的 workflow 釘 `LIBS_TAG`／sha256 |

**誰改了什麼、誰要跟著升**：

| 改了 | SYNOX | `SDK_VERSION` | 工具庫 |
|---|---|---|---|
| 修 SYNOX 的錯、小功能 | PATCH | 不動 | 不動 |
| SDK 只**加**新 API | PATCH | PATCH | 用到的工具帶自己那份 `synox_sdk.py`，不用改 `requires.sdk` |
| SDK／pack.json 合約**不相容** | MINOR | MINOR，重產 `sdk/synox_sdk.py` | 每個工具改 `requires.sdk`、重新打包、發新 tag；`OFFICIAL_INDEX_URL`、`LIBS_TAG` 跟著換 |
| 工具新功能要新版 SYNOX 才有的東西 | — | — | 那個工具寫 `requires.synox: ">=新版"`、升自己的版本（舊 SYNOX 的清單會標「用不了這一版」，§6） |

### 12. 怎麼讓大家知道有新版

- 發佈頁（Latest 標記）＋每版的白話說明；網頁工具庫的卡片標「有新版」，上面一條「有 N 個工具可以更新」＋「全部更新」
  （外觀包也算；一個一個給報告、按確認才換）；命令列 `synox tools check`、`synox tools update <名字…>|--all`。
  每週檢查打開的人，工具有新版也通知一次（同一組版本只一次）。
- 「檢查更新」（網頁設定「💻 電腦與備份」、`synox update --check`）：問 GitHub 的 `releases/latest`（只有正式版），說明裡有「🔒 安全更新」或「強烈建議更新」就用紅字；順便說有幾個工具可以更新。打開每週檢查的人：網頁上方的橫幅＋Telegram／Discord 通知一次。
- 所以**安全修正一定要**：標題前加「🔒 安全更新」、說明第一句「**強烈建議更新**」、`release.py sign --security`（決定 U9）。沒打開每週檢查的人不會被通知，這是「不偷連網」的取捨（決定 U2）。

### 13. 現況與下一版

已經打的 tag（本機 `git tag`；GitHub 上有沒有發佈以發佈頁為準）：

| tag | 日期 | 備註 |
|---|---|---|
| `v0.2.1-alpha.1` | 2026-11-16 | 第一個照這份規則發的預覽版 |
| `v0.2.1-beta.1` | 2026-11-18 | tag 打了，安裝檔沒建成，沒有發佈（說明在 CHANGELOG 0.2.1-beta.2 那一節） |
| `v0.2.1-beta.2` | 2026-11-18 | 內容同 beta.1，只換安裝檔要下載的工具庫指紋；發版 commit 在 `release/0.2.1`，沒有合回 `dev` |

0.2.0 沒有 tag（不補打）；0.1.0、0.2.0 在 CHANGELOG 有日期。

**下一個要發的版本：`0.2.2-alpha.1`**（擁有者 2026-11-19 定：下一版還是 alpha）。理由：`v0.2.1-beta.2` 已經打了，
同號的 `0.2.1-alpha.N` 會排在它前面（檢查更新、`-FromZip` 都會當成舊版、不肯裝），所以 alpha 只能是下一號 `0.2.2-alpha.1`
（`0.2.1-beta.2 < 0.2.2-alpha.1`）。`dev` 已經是這個號碼、CHANGELOG 最上面是 `## 0.2.2-alpha.1（未發佈）`；發版那天 `bump keep`。
之後要給外部試就 `bump beta` → `0.2.2-beta.1`，正式版 `bump final` → `0.2.2`。

從 0.2.0 更新到 0.2.1 以後任何一版：內建工具都搬到工具庫了（`loader.BUNDLED` 清空，2026-11-12），更新的人**要自己把工具裝回來**，發佈說明「怎麼更新」**第一行**要寫清楚（資料還在）。0.2.0 沒有 Update.bat：從 0.2.0 更新只能手動（上面「我要怎麼更新？」的手動做法）。
