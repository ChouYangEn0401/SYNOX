# 版本與發佈規則

- 狀態：**已採用**（擁有者 2026-11-14；工具：`scripts/release.py`、`tests/test_release_script.py`）。**SYNOX 還沒有發過任何一個 GitHub release、
  也還沒打過 tag**（2026-11-13 查過）；第一版怎麼發見最後一節「第一次照這份規則發版」。
- 自己會更新：**有**（2026-11-14，[adr/0023](adr/0023-updates-and-hotfixes.md) 已採用）：「檢查更新」（按了才查；每週檢查要自己打開）、ZIP 裝的用 `Update.bat`、退回用 `Update.bat -Rollback`。下一版是 **`0.2.1-beta.1`**（擁有者定的，決定 U1）。

---

## 一般人看這段

**版本號長這樣：`0.2.1`。** 三個數字，越大越新（`0.2.10` 比 `0.2.9` 新）。後面有沒有尾巴，意思不一樣：

| 長相 | 叫什麼 | 給誰 | 你該不該裝 |
|---|---|---|---|
| `0.2.1` | **正式版** | 所有人 | ✅ 裝這個。介紹頁的「⬇ 下載 SYNOX」、GitHub 的 `main` 永遠是最新的正式版 |
| `0.2.1-beta.1` | **測試版（beta）** | 願意幫忙試用、回報問題的人 | 想先試新東西再裝；平常在用、不想遇到問題就等正式版 |
| `0.2.1-alpha.1` | **內部測試版（alpha）** | SYNOX 團隊自己 | ❌ 一般人不要裝 |

**我裝的是不是最新版？**

1. 看自己的版本：在 SYNOX 資料夾打 `.venv\Scripts\synox about`（或 `synox doctor`），第一行就是版本，下面一行是發佈頁的網址。
2. 打開發佈頁 <https://github.com/ChouYangEn0401/SYNOX/releases>，標著 **Latest** 的就是最新正式版。數字一樣＝你是最新的。
3. 每一版的發佈頁都有三段：**這版改了什麼**、**要不要更新**、**怎麼更新**。寫「強烈建議更新」的是修了安全問題，請盡快更新。

**看有沒有新版最快的方法**：網頁「設定 → 💻 電腦與備份 → 檢查更新」，或在 SYNOX 資料夾打 `.venv\Scripts\synox update --check`。SYNOX **只有你按了才去問 GitHub**；想要它每週自己看一次（只看，不會自己裝），在安裝精靈最後一頁或同一張卡片勾「每週幫我看一次有沒有新版」（預設不勾：沒勾的話，有安全更新也要你自己來按才會知道）。一般人只會看到**正式版**，beta 不會跳出來。更新**一定先問你**，SYNOX 不會自己換掉自己（[adr/0023](adr/0023-updates-and-hotfixes.md)）。

### 我要怎麼更新？

更新**不會**動到你的設定（`config.json`）、資料（`data` 資料夾：筆記、記帳、保管箱、金鑰）和裝好的工具（`packs` 資料夾）。

| 你是 | 怎麼更新 | 備註 |
|---|---|---|
| **用 ZIP 的人**（從介紹頁或發佈頁下載、解開、點 `Setup.bat`） | **點兩下 SYNOX 資料夾裡的 `Update.bat`**（或網頁「檢查更新」之後按「更新…」）：它先給你看這版改了什麼、問你一次，再下載、核對檔案、關掉 SYNOX、換好、重新打開。舊版的程式留在 `_previous` 資料夾（最近 2 份），出問題點 `Update.bat -Rollback` 就回到上一版。那一版**沒有簽章**時（現在都還沒有，見 [release-build.md](release-build.md)「發佈簽章金鑰」），Update.bat 會說明，你要明確打 `Update.bat -AllowUnsigned` 才換。<br>舊版（還沒有 Update.bat）或想自己來：① 點兩下 `Stop.bat` 關掉 SYNOX ② 到發佈頁下載新的 `SYNOX-<版本>.zip`（或介紹頁的「⬇ 下載 SYNOX」）③ 解開 ④ 把裡面 `SYNOX`（或 `SYNOX-main`）資料夾的**全部內容**複製到你原本的 SYNOX 資料夾，問要不要取代就選「**取代**」⑤ 點兩下 `Setup.bat` | 新的 ZIP 裡沒有 `config.json`、`data`、`packs`，所以蓋不掉你的東西。`Setup.bat` 重跑是安全的：只更新套件、最後打開精靈——直接關掉精靈就好，設定都還在。舊的 ZIP 帶的開發用檔案（`tests`、`evals`、`docs\lab`、`docs\ui`、`docs\installer`…）和 `Connect-Apple.bat`、根目錄的 `GOVERNANCE.md`／`MAINTAINERS.md`／`TRADEMARK.md`（搬進 `.github`），新的 ZIP 不帶了：留著不會被讀，想清就自己刪（Apple 帳號改用 `.venv\Scripts\python.exe -m synox connect apple-reminders`） |
| **用 git 的人** | `Stop.bat` → `git pull`（在 `main` 上）→ `Setup.bat` | 只要某一版：`git fetch --tags` → `git checkout v0.2.1`。用 Docker：`git pull` → `docker compose build` → `docker compose up -d`（[docker.md](docker.md)） |
| **用安裝程式（.exe）的人** | ⏳ 安裝程式還沒正式發佈。發佈之後：下載新的 `SYNOX-Setup-<版本>.exe`，裝在原本的位置（預設就是） | 設計上會保留 `config.json`、`data`、`packs`（[adr/0003](adr/0003-distribution-git-clone-and-installer.md) B），舊版才有的開發用檔案會自動刪掉；**還沒在真機驗證過** |
| **工具（工具庫的 pack）** | 網頁「設定 → 功能與安裝 → 工具庫（官方）」按「載入工具清單」：有新版的工具會標出來，按「安裝」就是更新。或拿到新的 `.synoxpack` 再裝一次 | 同名再裝＝升級：先給你看「改了什麼」（權限變大是紅字），你按確認才換。不滿意：`synox packs rollback <工具名>` 退回上一版。工具自己的資料不會動 |
| **寫工具的人（SDK）** | 先照上面更新 SYNOX → `pip install -U <SYNOX 資料夾>/sdk`（或重新複製 `sdk/synox_sdk.py` 到你的工具旁邊）→ `synox-sdk check .` | 看 [sdk.md](sdk.md)「SDK 版本」：SDK 第二個數字變了（例如 0.2 → 0.3）才要改 `requires.sdk` 並重新測；只變最後一個數字不用改 |

更新完可以跑 `synox doctor` 看一次（版本對了、沒有紅字就好）。出問題想回到上一版：用 Update.bat 更新的點兩下 `Update.bat -Rollback`；手動蓋的人先別刪舊的 ZIP、照同樣方法蓋回去；
git 的人 `git checkout v<上一版>` 再跑 `Setup.bat`。**從 0.2.0 更新到 0.2.1 的人**：內建工具都搬進工具庫了，更新完到「設定 → 🧩 功能與安裝 → 工具庫」把要用的工具裝回來（資料還在）。

---

## 維護者

### 1. 版本號：0.x 的 SemVer

格式只有三種（`scripts/release.py` 的 `VERSION_RE`，別的一律不收）：

```
X.Y.Z              正式版           例 0.2.1
X.Y.Z-beta.N       外部測試         例 0.2.1-beta.1（N 從 1 開始）
X.Y.Z-alpha.N      內部測試         例 0.2.1-alpha.1
```

排序：`0.2.1-alpha.1 < 0.2.1-alpha.2 < 0.2.1-beta.1 < 0.2.1 < 0.2.2`（跟工具升級用的 `packs/upgrade.semver_key` 一樣）。
`pip` 會把它正規化成 `0.2.1a1`／`0.2.1b1`，是同一個版本；`synox.__version__` 照原樣寫。

**升哪一個數字**——只問一句：「使用者更新之後，要不要多做事，或舊的工具會不會壞？」

| 升 | 什麼時候 | 例子 |
|---|---|---|
| **PATCH**（0.2.0 → 0.2.1） | **每一次 `dev` 合進 `main` 的一般發版**；修錯、安全修正（hotfix）、小功能、文件。舊的 `config.json`、`data`、工具照用 | 修精靈的按鈕被擠掉；工具庫卡片多「有新版」 |
| **MINOR**（0.2.x → 0.3.0） | 會：`config.json` 或 `data` 的格式要轉換；pack.json 多了舊 SYNOX 讀不懂、工具開始依賴的欄位（新工具要寫 `requires.synox: ">=0.3"`）；拿掉指令或功能；換最低 Python；架構大改 | 0.1.0 → 0.2.0：pack 格式多了 surfaces／data／auth.fields／mcp… |
| MAJOR（0.x → 1.0.0） | 擁有者宣布「穩定、之後不隨便破壞相容」的那天。0.x 期間不升 | — |

拿不準就升 MINOR，並在 CHANGELOG 那一節第一行寫「更新後要做什麼」。

**alpha／beta 不是必經**：小的 PATCH 可以直接發正式版；改了安裝流程、資料格式、權限的版本，至少走一輪 beta。

**版本寫在哪**：`pyproject.toml` 的 `[project] version` 與 `src/synox/__init__.py` 的 `__version__`（兩個要一樣；`release.py bump`
一起改，`release.py check` 與 `scripts/installer_ci.py version` 都會擋不一樣的）。介紹頁 `docs/landing/page.html` 右上角的版本徽章由介紹頁的維護者跟著改
（`check` 只提醒）。`synox about`、`synox doctor` 印版本，並附一行發佈頁網址（`brand.RELEASES_URL`）。

### 2. 分支：dev → release → main

```
feat/… ──► dev ──► release/0.2.1 ──(bump final)──► main ── tag v0.2.1
                    │  tag v0.2.1-alpha.1、v0.2.1-beta.1（在 release 分支上）
                    └──► 修正同時合回 dev
main ── hotfix/0.2.2 ──(bump patch)──► main ── tag v0.2.2 ──► 合回 dev（與開著的 release/…）
```

- **`dev`**：每天開發。每個分支在 `CHANGELOG.md` 最上面加一節 `## 未發佈（分支或主題）`（現在就是這樣）。
- **`release/X.Y.Z`**：要發版時從 `dev` 切出來。之後只收修正（修正也要合回 `dev`），不收新功能。alpha／beta 的 tag 打在這條分支上。
- **`main`：只在發正式版時動**。`main` 的最新一個 commit 永遠是某個 `vX.Y.Z` tag——所以介紹頁的「⬇ 下載 SYNOX」（`main` 的 ZIP）
  一定是最新正式版。不在 `main` 上直接 commit；alpha／beta 不進 `main`。
- **`hotfix/X.Y.Z`**：正式版有急著修的問題（尤其安全）時，從 `main`（最新的 tag）切出來，只修那一件 → `bump patch` → 合進 `main`、打 tag、
  發佈 → **一定要合回 `dev`**（還有開著的 `release/…`），不然下一版會把修正弄丟。合回 `dev` 時 CHANGELOG 可能衝突：兩邊都留，
  hotfix 那一節放在 `dev` 的「未發佈」下面。
- tag 是 `vX.Y.Z`、`vX.Y.Z-beta.N`、`vX.Y.Z-alpha.N`，一定等於 `v`＋版本（`release.py check --tag`、`installer_ci.py` 都檢查）。
  用有註解的 tag（`git tag -a v0.2.1 -m "SYNOX 0.2.1"`）。**發出去的 tag 不移動、不刪**；發錯了就再發下一個號碼。

### 3. 每一版都要有

1. **版本號**：`python scripts/release.py bump <patch|minor|alpha|beta|final>`（改 `pyproject.toml`＋`__init__.py`）。
2. **CHANGELOG 一節，有日期**：`## 0.2.1（2026-11-20）`。`bump` 會把最上面所有「未發佈」收進這一節（每節變成 `### 主題`），印出 diff，
   不 commit；你再補一句「這版重點」。
3. **檢查**：`python scripts/release.py check --tag v0.2.1` 全綠（版本一致、SDK 單檔版跟正本一樣、有日期的那一節、沒有剩下的「未發佈」、tag 格式）；
   全部測試；`scripts/prepublish_check.py --worktree-only`。
4. **GitHub release**：標題 `SYNOX 0.2.1`；說明用白話中文，三段 **這版改了什麼／要不要更新／怎麼更新**——`python scripts/release.py notes [--exe]`
   印出草稿，把技術句子改成一般人看得懂的話（一條一句；技術細節留在 CHANGELOG）。安全修正寫「**強烈建議更新**」。
   alpha／beta 勾 **Set as a pre-release**；正式版勾 **Set as the latest release**。
5. **附檔**：`SYNOX-0.2.1.zip`（`scripts/make_zip.py --tools <SYNOX_Libs 的 dist>`，裡面帶工具庫）＋ `SHA256SUMS.txt`（每個附檔一行）＋ `release.json`／`release.json.sig`（`python scripts/release.py sign --dist dist --key <私鑰檔>` 一次寫這三個；私鑰只在創始維護者手上，[release-build.md](release-build.md)「發佈簽章金鑰」）。**Update.bat 要有 ZIP 與 SHA256SUMS.txt 才會自動更新**；
   有做好、測過的安裝程式就附 `SYNOX-Setup-0.2.1.exe`（推 tag 時 `build-installer.yml` 會做、放進**草稿** release，[release-build.md](release-build.md)）。
   GitHub 自動附的「Source code (zip)」不用管。
6. **之後**：介紹頁的版本徽章（請介紹頁維護者改）；[ecosystem.md](ecosystem.md)「文件維護清單」那一列「版本號」。

### 4. 發版步驟（照抄）

```
git switch dev && git pull
git switch -c release/0.2.1
python scripts/release.py bump beta            # 要先給外部試用；不用就直接 bump patch
#   看 diff、補 CHANGELOG 那一節 → commit
python scripts/release.py check --tag v0.2.1-beta.1
git tag -a v0.2.1-beta.1 -m "SYNOX 0.2.1-beta.1" && git push origin release/0.2.1 v0.2.1-beta.1
#   → 草稿 release 出現（有 exe 的話）→ 貼 notes、上傳 ZIP → 勾 pre-release → Publish
#   …測試、修正（修正也合回 dev）…
python scripts/release.py bump final           # 0.2.1-beta.N → 0.2.1；commit
python scripts/release.py check --tag v0.2.1
git switch main && git merge --no-ff release/0.2.1
git tag -a v0.2.1 -m "SYNOX 0.2.1" && git push origin main v0.2.1
#   → 草稿 release：python scripts/release.py notes [--exe] 改成白話貼上、上傳 SYNOX-0.2.1.zip 與 SHA256SUMS.txt → Latest → Publish
git switch dev && git merge main && git push origin dev
```

推 `v*` tag 會觸發 `build-installer.yml`：它建草稿 release 並放 exe；**已經公開的 release 它不碰**（會失敗）。所以順序是：推 tag → 等 workflow
（失敗也沒關係，沒有 exe 照樣可以發）→ 在**同一個草稿**上補說明與 ZIP → Publish。沒有 workflow 時就自己 `New release` 選那個 tag。

### 5. SYNOX、SDK、工具庫：三個各自的版本

現在的實況（讀程式碼確認過，2026-11-13）：

| 東西 | 版本寫在哪 | 現在 | 怎麼發 |
|---|---|---|---|
| **SYNOX 本體** | `pyproject.toml`＋`src/synox/__init__.py` | 0.2.0 | 這份文件；tag `vX.Y.Z`（SYNOX repo） |
| **SDK**（給工具的介面合約） | 只寫在 `src/synox/sdk/author.py` 的 `SDK_VERSION`；`sdk/synox_sdk.py`（`scripts/build_synox_sdk.py` 產生）、`sdk/pyproject.toml`（`synox-sdk` 套件）都讀它 | 0.2.2 | **跟著 SYNOX 一起發**（在 `sdk/` 裡），沒有自己的 tag／PyPI。不相容的改動升 MINOR（0.x），只加 API 升 PATCH（[sdk.md](sdk.md)「SDK 版本」） |
| **工具庫 SYNOX_Libs** | 另一個 repo；每個工具 pack.json 的 `version`；發佈頁的 `index.json`（名字、版本、sha256）與 `tools-<版本>.zip` | `v0.2.0`（GitHub 上標成 pre-release） | 自己的 tag 與 release。SYNOX 的網頁工具庫固定讀 `v0.2.0` 的 `index.json`（`packs/catalog.py` 的 `OFFICIAL_INDEX_URL`；因為是 pre-release，`latest/download` 會 404），安裝程式的 workflow 釘 `LIBS_TAG`／sha256 |

**相容性怎麼宣告**（每個工具的 pack.json）：

```json
"requires": { "synox": ">=0.2", "sdk": ">=0.2,<0.3" }
```

- `requires.synox`＝要多新的 SYNOX；`requires.sdk`＝照哪一版合約寫的（`synox-sdk init` 自動寫 `>=0.2,<0.3`，0.x 寫到下一個 MINOR）。
- 唯一的檢查在 `packs/manifest.synox_problem`（先 synox 再 sdk）：**安裝**（第 1、2 關，不合＝不裝）、**載入**（不合＝狀態 incompatible、不載入）、
  `doctor`、`packs status`、`/bot_status` 都經它，回一句人話（「先更新 SYNOX」或「請向作者要新版」）。
- 比的只有數字 `X.Y.Z`，**預覽版的尾巴不看**（`manifest._version_tuple`）：`0.2.1-alpha.1` 會被當成 `0.2.1`。所以工具寫 `>=0.2.1`，
  0.2.1 的 alpha／beta 也裝得上——寫工具的人用 beta 先測是可以的。
- 工具自己的版本要是 semver（同名再裝＝升級，`packs/upgrade.compare_versions` 比新舊，退回要明確選；`synox packs rollback`）。

**誰改了什麼、誰要跟著升**：

| 改了 | SYNOX | `SDK_VERSION` | 工具庫 |
|---|---|---|---|
| 修 SYNOX 的錯、小功能 | PATCH | 不動 | 不動 |
| SDK 只**加**新 API | PATCH | PATCH | 用到的工具帶自己那份 `synox_sdk.py`，不用改 `requires.sdk` |
| SDK／pack.json 合約**不相容** | MINOR | MINOR，重產 `sdk/synox_sdk.py` | 每個工具改 `requires.sdk`、重新打包、發新 tag；`OFFICIAL_INDEX_URL`、`LIBS_TAG` 跟著換 |
| 工具新功能要新版 SYNOX 才有的東西 | — | — | 那個工具寫 `requires.synox: ">=新版"`、升自己的版本 |

### 6. 怎麼讓大家知道有新版

- 發佈頁（Latest 標記）＋每版的白話說明；網頁工具庫的卡片標「有新版」（只對工具）。
- 「檢查更新」（網頁設定「💻 電腦與備份」、`synox update --check`）：問 GitHub 的 `releases/latest`（只有正式版），說明裡有「🔒 安全更新」或「強烈建議更新」就用紅字；順便說有幾個工具可以更新。打開每週檢查的人：網頁上方的橫幅＋Telegram／Discord 通知一次。
- 所以**安全修正一定要**：標題前加「🔒 安全更新」、說明第一句「**強烈建議更新**」、`release.py sign --security`（決定 U9）。沒打開每週檢查的人不會被通知，這是「不偷連網」的取捨（決定 U2）。

### 7. 第一次照這份規則發版

SYNOX 到 2026-11-13 都沒有 tag 和 release；0.2.0（commit `f2898ec`，2026-11-09）在 CHANGELOG 裡沒有日期，之後 `dev` 又累積了 14 節「未發佈」。

- 不補打 `v0.2.0`；CHANGELOG 的 `## 0.2.0` 補上日期 `（2026-11-09）`。
- 從 `dev` 照第 4 節發下一版，先 beta 給外部試、再正式版。**擁有者定了：下一版是 `0.2.1-beta.1`**（ADR 0023 決定 U1，2026-11-14）。這批改動裡「內建工具全部搬到工具庫」（`loader.BUNDLED` 清空，2026-11-12）會讓從舊版更新的人**要自己把工具裝回來**，所以 0.2.1 的發佈說明「怎麼更新」**第一行**要寫清楚要重裝工具（資料還在）。之後每次合進 `main` 都是 PATCH。
- 0.2.0 沒有 Update.bat：從 0.2.0 更新到 0.2.1 只能手動（上面「我要怎麼更新？」的手動做法）；0.2.1 之後才能用 Update.bat。
