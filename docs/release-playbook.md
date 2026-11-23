# 發佈手冊：SYNOX 與工具庫要發新版時，照這一頁做

給**人**和**另一個 Claude session** 用的單一頁面。規則（版本號、分支、每版要有什麼）在 [versioning.md](versioning.md)；
自己更新的設計在 [adr/0023](adr/0023-updates-and-hotfixes.md)；安裝程式的建置與簽章金鑰在 [release-build.md](release-build.md)。
這一頁只講「實際怎麼發、怎麼先測、出事怎麼退」，指令可以照抄。

現況（2026-11-19；以 `gh release list` 為準）：

| | 版本 | GitHub 發佈 | 會影響什麼 |
|---|---|---|---|
| SYNOX | `release/0.2.2`：`0.2.2-alpha.1`（2026-11-19，要打 tag `v0.2.2-alpha.1`；[versioning.md](versioning.md) §13） | tag `v0.2.1-alpha.1`、`v0.2.1-beta.1`（沒發佈）、`v0.2.1-beta.2`，都是預覽版；**沒有正式版** | `Update.bat`／「檢查更新」問 `releases/latest`：現在一律「還沒有正式版」 |
| SYNOX_Libs（工具庫＋衣櫃） | `v0.3.1`（安裝程式帶它的 `tools-0.3.1.zip`） | `v0.2.0`、`v0.3.0`、`v0.3.1` 都是 pre-release，還沒有標成 Latest 的 | SYNOX 網頁工具庫的 `catalog.OFFICIAL_INDEX_URL` 釘在 `v0.3.1`（第 2 節）、Libs 的 `LINK_MODE = "tag"` |
| 發佈簽章公鑰 | 沒有（`signing.RELEASE_PUBLIC_KEYS` 是空的） | — | 每一版都算「沒有簽章」：使用者要明確 `Update.bat -AllowUnsigned` |

---

## 0. 先測更新（還沒有真的發佈之前就能做）

真的發佈之前，先在 Windows 上把 `Update.bat` 整條路走一次。三個工具，都**只給測試**，一般人的 SYNOX 不會碰到：

| 工具 | 做什麼 | 安全限制 |
|---|---|---|
| `python scripts/make_update_testkit.py` | 做測試包：舊版 ZIP（現在的程式）、假的新版 ZIP（版本改成 `下一個 patch-test.1`，例 `0.2.1-test.1`）、`SHA256SUMS.txt`、`release.json`＋`.sig`（**這次才產生的拋棄式金鑰**）、假的 `releases.json`、中文 README | 只寫到 repo 以外（預設系統暫存資料夾）；repo 一個檔都不改（版本只在 ZIP 裡改） |
| `Update.bat -FromZip <ZIP> [-AllowUnsigned]`（＝`synox update --prepare --from-zip`） | 用這台電腦上的 ZIP 更新，不連網；之後的停 SYNOX、換檔、`_previous\`、出事自動退回、`-Rollback` 都跟正式更新**同一段**（`update.ps1` 的 `Invoke-Swap`） | 旁邊有 `SHA256SUMS.txt` 就一定要對（有檔但沒有這行＝拒絕）；旁邊有簽章且有公鑰就一定要驗過；沒有簽章只有加 `-AllowUnsigned` 才換；版本一樣要比裝著的新 |
| 環境變數 `SYNOX_UPDATE_API=<本機 releases.json>` | 正式那條路（`update --check` → `--prepare` 下載、驗證）照跑，只是「GitHub」換成本機的檔 | **只從環境變數讀**（`config.json`、網頁都改不到）；只收本機路徑、`file://`、`http://127.0.0.1／localhost`，指到別台主機＝拒絕；附檔也只能是本機的；每段輸出、每個通知最上面印「⚠️⚠️ 測試模式」；結果不存、不出網頁橫幅 |
| 環境變數 `SYNOX_UPDATE_TEST_PUBKEY=<公鑰>` | 讓測試包的拋棄式簽章算數 | **只在** `-FromZip` 與 `SYNOX_UPDATE_API` 測試模式才加進來；GitHub 上的正式更新從來不看它；用的時候大聲說 |
| `synox update --check --include-prerelease` | 連 beta／alpha 一起看（問 `releases?per_page=20`） | 只有命令列、只有明確加旗子；只看，不存結果；`Update.bat` 從來不裝預覽版 |

在 Windows（擁有者的電腦，有 git clone 的那份 SYNOX）：

```
cd <SYNOX 的 git clone>
.venv\Scripts\python.exe scripts\make_update_testkit.py --out C:\synox-kit
```

然後照 `C:\synox-kit\README.md` 做（解壓舊版到 `C:\SYNOX-test\` → Setup → 做點事 → `Update.bat -FromZip … -AllowUnsigned`
→ `synox about` 看版本、`config.json`／`data\`／`packs\` 都在 → `Update.bat -Rollback`；選做：測試公鑰、`SYNOX_UPDATE_API`、改壞
`SHA256SUMS.txt` 要被拒絕）。**測試包要在測試的那台電腦上產生**：`releases.json` 裡寫的是那台的絕對路徑。

beta 測試者裝 beta 也用同一招：從 pre-release 頁下載 `SYNOX-<版本>.zip` 和 `SHA256SUMS.txt`（放同一個資料夾）→
`Update.bat -FromZip <那個 ZIP> -AllowUnsigned`（還沒有公鑰之前）。

---

## 1. SYNOX 發一版（預覽版先，正式版後）

前提：`gh auth status` 有 SYNOX repo 的寫入權限；`dev` 是乾淨的；SYNOX_Libs 要一起發的話先做第 3 節（ZIP 要帶新的工具庫）。

```bash
REPO=ChouYangEn0401/SYNOX
git switch dev && git pull
git switch -c release/0.2.2

# 1. 升號＋CHANGELOG：bump 印 diff、不 commit。補「這版重點」一句；「怎麼更新」第一行寫要重裝工具（從 0.2.0 來的人，versioning.md §13）
python scripts/release.py bump keep                   # dev 已經是 0.2.2-alpha.1（未發佈）：號碼不變、寫日期（換成 beta：bump beta）
python scripts/build_guide.py && python scripts/make_landing.py   # 安裝教學與介紹頁：版本、檔名、下載連結跟著這一版（第 7 節）
git commit -am "release: 0.2.2-alpha.1"

# 2. 關卡（全部要過，見第 4 節）
python scripts/release.py check --tag v0.2.2-alpha.1
python scripts/check_version_consistency.py --tag v0.2.2-alpha.1   # CHANGELOG 最上面、安裝器、文件、比每個 tag 新
PYTHONPATH=$PWD/src python -m pytest -q -p no:cacheprovider     # Linux 基準線：14 個已知失敗，不能多
python scripts/prepublish_check.py --worktree-only

# 3. tag（有註解、不移動、不刪）→ 推 → build-installer.yml 建「草稿」release＋exe（失敗也可以照發，只是沒有 exe）
git tag -a v0.2.2-alpha.1 -m "SYNOX 0.2.2-alpha.1"
git push origin release/0.2.2 v0.2.2-alpha.1

# 4. 附檔：ZIP（帶工具庫）＋ SHA256SUMS.txt ＋ release.json(.sig)
python scripts/make_zip.py --tools <SYNOX_Libs>/dist
gh release download v0.2.2-alpha.1 -R $REPO -p 'SYNOX-Setup-*.exe' -D dist || true   # 有 exe 就一起簽進去
python scripts/release.py sign --dist dist --key <repo 以外的私鑰檔> [--security] [--summary "一句白話"]
#   還沒有私鑰（創始維護者還沒 keygen）：照樣要 SHA256SUMS.txt。沒有 sign 時自己做：
#   (cd dist && sha256sum SYNOX-0.2.2-alpha.1.zip > SHA256SUMS.txt)
#   Windows：certutil -hashfile dist\SYNOX-0.2.2-alpha.1.zip SHA256

# 5. 說明：草稿 → 改成白話（這版改了什麼／要不要更新／怎麼更新）
python scripts/release.py notes --version 0.2.2-alpha.1 [--exe] > dist/notes.md   # 改寫 dist/notes.md

# 6. 發佈成 pre-release（草稿已經在：上傳＋改說明＋公開；沒有草稿：gh release create）
gh release upload v0.2.2-alpha.1 -R $REPO --clobber dist/SYNOX-0.2.2-alpha.1.zip dist/SHA256SUMS.txt \
    dist/release.json dist/release.json.sig          # 沒有簽章就不傳後兩個
gh release edit v0.2.2-alpha.1 -R $REPO --title "SYNOX 0.2.2-alpha.1" --notes-file dist/notes.md \
    --prerelease --draft=false
#   沒有草稿時：gh release create v0.2.2-alpha.1 -R $REPO --verify-tag --prerelease \
#       --title "SYNOX 0.2.2-alpha.1" --notes-file dist/notes.md dist/SYNOX-0.2.2-alpha.1.zip dist/SHA256SUMS.txt
```

驗 pre-release（不會影響一般人：`releases/latest` 不含 pre-release）：

```bash
gh release view v0.2.2-alpha.1 -R $REPO --json isPrerelease,isDraft,assets -q '{pre:.isPrerelease,draft:.isDraft,assets:[.assets[].name]}'
python -m synox update --check --include-prerelease      # 要看到 0.2.2-alpha.1（預覽版）
python -m synox update --check                           # 一般人：還是「還沒有正式版」（或舊的正式版）
```

在 Windows 上：舊版 SYNOX → 下載 beta 的 ZIP＋`SHA256SUMS.txt` → `Update.bat -FromZip <ZIP> -AllowUnsigned` → 跑一陣子。

發佈、驗過之後：**重新發佈安裝教學與介紹頁這兩個線上頁面，打開確認版本與下載連結是剛發的這一版**（第 7 節；alpha、beta 也要做）。

### `main` 什麼時候動（alpha 階段）

擁有者 2026-11-19 決定：還沒有正式版的這段時間，`main` 跟著**最新的發佈**走，預覽版也算（[versioning.md](versioning.md) §8）。
`main` 就是 GitHub 上大家看到的最新版。（介紹頁與安裝教學的「⬇ 下載」從 2026-11-23 起指發佈頁上這一版的 `SYNOX-<版本>.zip`，
不再指 `main` 的 ZIP；見第 2、7 節。）預覽版發佈（上面第 6 步）、驗過之後：

```bash
git switch main && git pull
git merge --no-ff release/0.2.2 -m "Merge release/0.2.2: SYNOX 0.2.2-alpha.1 …（這版做了什麼）"
git push origin main
git switch dev && git merge --no-ff release/0.2.2 && git push origin dev     # 發版的 commit 一定要合回 dev
```

有了正式版之後要不要回到「`main` 只在正式版動」由維護者決定；決定之前照這一段。

### 正式版

```bash
python scripts/release.py bump final               # 0.2.2-beta.N → 0.2.2；commit
python scripts/release.py check --tag v0.2.2
python scripts/check_version_consistency.py --tag v0.2.2
git switch main && git merge --no-ff release/0.2.2
git tag -a v0.2.2 -m "SYNOX 0.2.2" && git push origin main v0.2.2
#   → 等 build-installer.yml 的草稿；照上面第 4～6 步做附檔與說明，但先「pre-release」發佈、自己再驗一次附檔：
gh release edit v0.2.2 -R $REPO --title "SYNOX 0.2.2" --notes-file dist/notes.md --prerelease --draft=false
gh release download v0.2.2 -R $REPO -p 'SYNOX-*.zip' -p SHA256SUMS.txt -D /tmp/check && (cd /tmp/check && sha256sum -c SHA256SUMS.txt)
# 驗過了才標成 Latest（這一刻起，每個人的「檢查更新」與 Update.bat 都會看到它）
gh release edit v0.2.2 -R $REPO --prerelease=false --latest
gh api repos/$REPO/releases/latest -q .tag_name       # 要是 v0.2.2
git switch dev && git merge --no-ff release/0.2.2
python scripts/release.py bump alpha --planned     # dev → 下一版（未發佈），versioning.md §3；commit、push
```

標成 Latest 之後：真的在 Windows 上從上一個正式版按一次 `Update.bat`（不是 `-FromZip`）；安裝教學與介紹頁照第 7 節重新發佈；
[ecosystem.md](ecosystem.md)「文件維護清單」的版本號。

---

## 2. 下載連結怎麼保持最新

| 連結 | 在哪 | 怎麼跟著新版 |
|---|---|---|
| SYNOX「⬇ 下載」（介紹頁、安裝教學） | `docs/landing/page.html`、`docs/guide/index.html` | 指**這一版**發佈頁上的 `SYNOX-<版本>.zip`（`…/releases/download/v<版本>/SYNOX-<版本>.zip`）與 `SYNOX-Setup-<版本>.exe`；版本、檔名、網址是組頁面時從 `pyproject.toml` 算的（`scripts/release.py` 的 `download_info`），不手改。**每次發版重組＋重新發佈**（第 7 節）。不用 `releases/latest`：GitHub 標成 Latest 的不一定是最新的測試版 |
| `Update.bat`、「檢查更新」 | `update/check.py` 寫死 `api.github.com/repos/…/SYNOX/releases/latest` | GitHub 的 Latest 標記；**不用改程式**。只有標成 Latest、不是 pre-release、不是草稿的才算 |
| 工具庫的公開頁、README | SYNOX_Libs `scripts/links.py` 的 `LINK_MODE` | `"tag"`（現在）：`releases/download/v<VERSION>/<name>-<版本>.synoxpack`（現在是 `v0.3.1`）；`"latest"`：`releases/latest/download/<name>.synoxpack`（別名，網址不用再改） |
| SYNOX 網頁的工具庫、`synox tools check／update`、每週檢查 | SYNOX `src/synox/packs/catalog.py` 的 `OFFICIAL_INDEX_URL` | 現在釘 `…/releases/download/v0.3.1/index.json`（見下） |
| 安裝程式帶的工具庫 | `.github/workflows/build-installer.yml` 的 `LIBS_TAG`＋sha256 | 每次換工具庫 tag 都要改（[release-build.md](release-build.md)「釘住的版本與 sha256」） |

**SYNOX 的 `OFFICIAL_INDEX_URL` 什麼時候要改**：SYNOX_Libs 有一個**不是 pre-release、標成 Latest** 的發佈之後
（`curl -sI https://github.com/ChouYangEn0401/SYNOX_Libs/releases/latest/download/index.json` 回 302）：

1. `src/synox/packs/catalog.py`：`OFFICIAL_INDEX_URL = "https://github.com/ChouYangEn0401/SYNOX_Libs/releases/latest/download/index.json"`，
   拿掉上面那段「先釘在這一版」的註解；
2. `tests/test_pack_library.py::test_constants_are_the_fixed_official_source` 改成新網址（`_web()` 的假網路本來就是「latest → 轉到該版」）；
3. [versioning.md](versioning.md) §11 的表格那一句；發 SYNOX 的下一版（已經裝了的人要更新 SYNOX 才會換網址）。

之後工具庫每次發新 tag 都要**標成 Latest**，SYNOX 不用再改。還沒標 Latest 之前，工具庫換 tag（例如 `v0.3.1`）就要同時改
`OFFICIAL_INDEX_URL` 到那個 tag 並發 SYNOX 新版——所以建議：工具庫下一次發佈就直接標成 Latest，SYNOX 同時改成 latest 網址。

---

## 3. SYNOX_Libs（工具庫＋衣櫃）發一版

完整步驟在 SYNOX_Libs 的 [`docs/RELEASING.md`](https://github.com/ChouYangEn0401/SYNOX_Libs/blob/links-latest/docs/RELEASING.md)
（`links-latest` 分支；合進 `main` 之後看 `main` 的同一個檔）。摘要：

1. 改版本：`packs/<name>/pack.json`（＋CHANGELOG）；開新 tag 才改 `VERSION`（tag＝`v`＋VERSION）。
2. `python scripts/build.py`（dist/：每個工具與外觀帶版本的 `.synoxpack`＋別名、`tools-<VERSION>.zip`、`index.json`、`SHA256SUMS`，
   同時把每個公開頁的連結改成現在的版本）；衣櫃頁有改再 `build_costumes.py page`；`python -m pytest -q`（`test_links.py`、`test_site_pages.py` 一定要過）。
3. 上傳：先 `sha256sum -c SHA256SUMS`；**先備份發佈頁上現在的 `index.json`**（本機＋發佈頁上帶日期的一份）；
   `gh release upload "$TAG" --clobber` 上傳 `.synoxpack`、tools zip、`SHA256SUMS`；**最後才換 `index.json`**；HEAD 每個連結。
4. 標成 Latest：`gh release edit "$TAG" -R ChouYangEn0401/SYNOX_Libs --prerelease=false --latest`，
   `curl -sI …/releases/latest/download/money.synoxpack` 回 302 → `links.py` 改 `LINK_MODE = "latest"` → `python scripts/links.py` → 測試、commit、重新發佈線上頁。
   然後做上面第 2 節「`OFFICIAL_INDEX_URL` 什麼時候要改」。

工具的版本是每個 pack 自己的 semver：SYNOX 的「有新版」只比 `index.json` 寫的版本和裝著的 `pack.json`。舊版本的檔留在發佈頁（舊連結不壞），`index.json` 只列最新版。

### 工具發了新版之後，使用者怎麼更新（給說明、客服用）

- 網頁：設定 → 🧩 功能與安裝 → 「載入工具清單」→ 上面出現「有 N 個工具可以更新」→「全部更新」：一個一個下載、給報告，
  每一個都要按「確認升級」（或「稍後再決定」跳過）才換。外觀包（衣櫃）也算在裡面。
- 命令列：`python -m synox tools check`（只看；結束碼 10＝有新版）→ `python -m synox tools update <名字…>` 或 `--all`
  （一樣印報告；`--yes`＝在終端機核准；沒有 `--yes` 而 SYNOX 開著＝打開網頁的報告）。
- 打開每週檢查的人：同一組新版本會收到一次 Telegram／Discord 通知（只看，不裝）。
- 退回：`python -m synox packs rollback <名字>`（舊版在 `packs/_removed/`）。

---

## 4. 每一道關卡在擋什麼

| 關卡 | 什麼時候跑 | 擋什麼 |
|---|---|---|
| `release.py check --tag vX` | 打 tag 之前 | 版本在每個檔都一樣、SDK 單檔版跟正本一樣、CHANGELOG 有這一節而且有日期、沒剩「未發佈」、tag＝`v`＋版本、**安裝教學與介紹頁（組出來的 `index.html`）寫的版本＝這一版**（沒重組＝不過；不帶 `--tag` 時只提醒） |
| `check_version_consistency.py --tag vX` | 打 tag 之前；`build-installer.yml` 推 tag 時、`prepublish-check.yml` 每次 push 也跑 | `__version__`＝`pyproject`、CHANGELOG 最上面就是這一版、安裝器沒寫死版本、文件的「目前版本」、**比每個本機 tag 新（SemVer）、號碼沒重用** |
| 全部測試（`pytest`） | 打 tag 之前 | Linux 基準線 14 個已知失敗，不能多；包含 Update.bat／update.ps1 的靜態檢查（Windows 上沒跑過） |
| `prepublish_check.py --worktree-only` | 打 tag 之前；workflow 也跑 | 密鑰、本機路徑、個人信箱進了 repo |
| `make_zip.py` | 做附檔 | 只帶 git 追蹤的檔，永遠不帶 `.venv`、`data`、`config.json`、`_previous`、`tests/`…（`test_release_layout.py` 對三份清單） |
| `release.py sign` | 做附檔 | 私鑰在 repo 裡＝拒絕；寫 `SHA256SUMS.txt`、`release.json`（每個附檔的 sha256＋大小）、`.sig`，簽完自己先驗一次 |
| `build-installer.yml`＋`installer_ci.py` | 推 `v*` tag | tag≠版本、外部下載的 sha256、Inno 的簽章發行者、離線裝得起來；只建**草稿**，永遠不公開發佈 |
| pre-release 先發 | 每一版 | 附檔、說明先上線但一般人看不到（`releases/latest` 不含它）；用 `--include-prerelease`／`-FromZip` 先試 |
| 使用者那邊：`update --prepare` | 每次 Update.bat | 只收正式版、版本要比較新（不降級）、`SHA256SUMS.txt` 一定要有而且要對、GitHub 的 digest 要一樣、有公鑰就一定要驗過簽章（驗不過＝拒絕，`-AllowUnsigned` 也救不了）、沒簽章要明確同意、ZIP 不能有 `..`／連結／絕對路徑、`config.json`／`data`／`packs` 就算在 ZIP 裡也不解、解出來的版本要對 |
| 使用者那邊：`update.ps1` | 換檔 | 只搬程式檔（`$Keep` 永遠不動）、舊版整份進 `_previous\`（留 2 份）、套件變了才重裝、新版版本不對＝自動退回 |
| 工具：`catalog.download`＋`admin.stage` | 每次裝／更新工具 | 網址寫死、轉址只跟 GitHub 自己的主機、大小與 sha256 要跟 `index.json` 一樣、包裡的名字／版本／種類要跟清單一樣、第 1、2 關掃描、人看報告按確認才進第 3 關（`packs.lock`） |

---

## 5. 出事怎麼退

- **使用者那台**：`Update.bat -Rollback`（`_previous\` 最新那份搬回來；設定、資料、工具都不動）。新版跑不起來時 `Update.bat` 自己會退。
  git 裝的：`git checkout v<上一版>` → `Setup.bat`。工具：`python -m synox packs rollback <名字>`。
- **發出去的 SYNOX 版本有問題**（tag 不移動、不刪）：
  ```bash
  gh release edit v0.2.1 -R ChouYangEn0401/SYNOX --prerelease          # Update.bat 不再提供它
  gh release edit v0.2.0 -R ChouYangEn0401/SYNOX --latest              # 上一個好的正式版當 Latest（有的話）
  ```
  然後修好發下一個 patch（`hotfix/0.2.3`，[versioning.md](versioning.md) §8；版本號不重用、tag 不動，§5），說明寫清楚；安全問題標題加「🔒 安全更新」、
  說明第一句「**強烈建議更新**」、`release.py sign --security`。
- **工具庫的 `index.json` 換壞了**：把第 3 節備份的 `index-backup-<時間>.json` 改名回 `index.json`，`gh release upload "$TAG" --clobber` 換回去。
- **附檔傳錯**：`gh release upload --clobber` 換掉；`release.json` 一定要重簽（sha256 變了），`SHA256SUMS.txt` 也一起換。
- **私鑰外流／弄丟**：[release-build.md](release-build.md)「發佈簽章金鑰」最後兩條。

---

## 6. 給新的 Claude session：照這張表做

開始前先讀：這一頁、[versioning.md](versioning.md)、SYNOX_Libs 的 `docs/RELEASING.md`、`CHANGELOG.md` 最上面。**不要**自己決定版本號、
不要自己標 Latest、不要刪或移動 tag：這三件事問擁有者。私鑰永遠不在 session 裡（只有擁有者在自己的電腦上 sign）。

```
□ git remote -v 是 ChouYangEn0401/SYNOX；gh auth status 有寫入權限；工作樹乾淨
□ 現況：gh release list -R ChouYangEn0401/SYNOX；gh release list -R ChouYangEn0401/SYNOX_Libs
       gh api repos/ChouYangEn0401/SYNOX/releases/latest -q .tag_name（404＝還沒有正式版）
□ 擁有者給了版本號（例：0.2.2-alpha.1；規則見 versioning.md §3）與要不要帶新的工具庫
□ （有新工具庫）SYNOX_Libs 照它的 RELEASING.md 發好；記下 tag，dist/ 在本機
□ release/<版本> 分支；release.py bump …；CHANGELOG 補白話重點；重組安裝教學與介紹頁（build_guide.py、make_landing.py）；commit
□ release.py check --tag v<版本> 與 check_version_consistency.py --tag v<版本> 全綠；pytest 只有 14 個已知失敗；prepublish_check.py --worktree-only 綠
□ （先測）make_update_testkit.py 做測試包，請擁有者在 Windows 照 README 走一次，回報 OK 才往下
□ git tag -a v<版本> -m "SYNOX <版本>"；git push origin <分支> v<版本>
□ gh run list -R ChouYangEn0401/SYNOX --workflow build-installer.yml -L 1（等它；失敗記下來，照樣可以發）
□ make_zip.py --tools <Libs dist>；請擁有者 sign（或至少產生 SHA256SUMS.txt）
□ release.py notes → 改成白話 → dist/notes.md
□ gh release upload … --clobber；gh release edit … --prerelease --draft=false（一定先 pre-release）
□ 驗：gh release view … --json assets；下載回來 sha256sum -c；synox update --check --include-prerelease 看得到
□ 重新發佈安裝教學與介紹頁兩個線上頁面（第 7 節；alpha、beta 也要），打開確認版本與下載連結是剛發的這一版
□ 正式版：擁有者說可以，才 gh release edit v<版本> --prerelease=false --latest；gh api …/releases/latest 確認
□ 合回 dev（--no-ff）並 bump … --planned；（工具庫標了 Latest 的話）改 OFFICIAL_INDEX_URL（第 2 節）
□ 回報：tag、release 網址、附檔與 sha256、哪些關卡過了、哪些沒在 Windows 上試過、兩個線上頁面重新發佈了沒
```

---

## 7. 每次發版：重組並重新發佈安裝教學與介紹頁

**每一版都要做，alpha、beta 也算。** 這兩頁上的版本號、檔名、下載連結是組頁面時從 `pyproject.toml` 的版本帶入的
（`scripts/release.py` 的 `download_info`；檔名跟 `make_zip.py`、`synox.iss`、`release.py sign` 同一個長相）。沒有重組，
頁面就會叫人下載上一版，或寫著已經過時的說明。

| 頁面 | 線上版（網址固定，重新發佈到同一個） | 本機檔 | 怎麼重組 |
|---|---|---|---|
| 安裝教學（一步一步） | <https://claude.ai/artifact/96iWvykYyUfAC5pkYUrC6F> | `docs/guide/index.html` | `python scripts/build_guide.py`（教學步驟＋版本與下載連結；有改就重蓋頁面版本） |
| 介紹頁（首頁） | <https://claude.ai/artifact/SNsSkbcVQm7BU22BBZN3gW> | `docs/landing/index.html`（原稿 `docs/landing/page.html`，不要直接改 index.html） | `python scripts/make_landing.py`（網頁介面的樣子有變才加 `--shoot`） |

順序：

1. **升號之後、打 tag 之前**（第 1 節第 1 步）：跑上面兩支，跟升號一起 commit。有裝 Node 的話再跑 `node scripts/check_guide.js`
   （不開瀏覽器，把教學的每一步、每條岔路、每個 `#step-…` 網址跑一遍；`tests/test_build_guide.py` 也會跑它）。
   `python scripts/release.py check --tag v<版本>` 會擋：兩頁寫的版本不是這一版＝不過。
2. 兩頁的字還對不對：這一版改了安裝精靈、設定頁、更新流程的畫面或字，就先改教學與介紹頁的原稿
   （畫面上的字要跟原始碼一模一樣；格式寫在 `docs/guide/index.html` 最上面的註解）。已經做完的事不要還掛著「⏳ 尚未完成」。
3. **發佈（第 1 節第 6 步）、附檔驗過之後**：把這兩個本機檔重新發佈到上表**同一個**線上網址（不要另開新網址）。
4. **打開兩個線上頁面確認**：
   - 介紹頁右上角的版本徽章、頁尾的版本是剛發的這一版；「下載 SYNOX」按鈕指 `…/releases/download/v<版本>/SYNOX-<版本>.zip`，按了真的下載得到。
   - 安裝教學「下載 SYNOX 的 ZIP」那一步的按鈕與示意圖上的檔名是這一版；按了真的下載得到。
   - 兩頁頁尾的「頁面版本」（`<span data-stamp>`）跟本機檔的一樣（＝線上的就是剛組的那一份）。
5. 檔頭／頁尾寫的「線上版」網址要是上表那兩個；「頁面版本」由腳本蓋（`build_guide.py`、`make_landing.py`；
   手改過 `docs/guide/index.html` 別的地方，重跑 `build_guide.py` 也會重蓋）。`tests/test_artifact_registry.py` 會擋「內容改了、頁面版本沒更新」。

新的 Claude session：這一步跟發版一起做（第 6 節的清單有這一格）。沒辦法重新發佈線上頁面時，在回報裡寫清楚「兩個線上頁面還沒重新發佈」，不要當成做完。
