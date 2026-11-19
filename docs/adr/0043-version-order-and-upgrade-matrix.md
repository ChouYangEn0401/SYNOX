# ADR 0043：版本號的排序、升級矩陣與錯版補救

- 日期：2026-11-19
- 狀態：**已採用**（分支 `chore/versioning-rules`；擁有者的需求：alpha 能升 beta、beta 能直接升下一版，SYNOX 與工具都能正常升級，
  版本號規則寫清楚。標 **「待決定」** 的一題要擁有者拍板，決定之前照現狀）。
- 規則全文：[docs/versioning.md](../versioning.md)（§1 排序、§2 唯一來源、§3 升號、§5 錯版、§6 矩陣與相容、§7 通道）。
- 程式：`src/synox/packs/upgrade.py`（`semver_key`）、`packs/catalog.py`（`blocked`）、`web/static/semver.js`、
  `scripts/release.py`（`next_version`、`bump keep`、`--next patch`、`--planned`）、`scripts/check_version_consistency.py`、
  `.github/workflows/build-installer.yml`、`prepublish-check.yml`。
- 前提：[0023](0023-updates-and-hotfixes.md)（自己更新、U3：App 只看正式版）。

## 背景

`v0.2.1-alpha.1`、`v0.2.1-beta.1`、`v0.2.1-beta.2` 打了 tag 之後，擁有者要下一版還是 alpha。`dev` 被手改成 `0.2.2-alpha.1`，
CHANGELOG 最上面多一個沒有日期、發版工具看不懂的 `## 0.2.2-alpha.1`，底下還掛著六節「未發佈」；`0.2.1-beta.2` 那一節不在 `dev`；
另外四節 0.2.0 之後才合進來的分支放在 `## 0.2.0` 底下。檢查程式時也發現比版本的地方不一致：網頁只看 `X.Y.Z`＋「有沒有尾巴」、
工具庫清單的 `requires` 沒人看、`release.py` 無法表達「beta 之後再一個 alpha」。

## 決定

1. **排序只有一套：SemVer 2.0.0**（數字段按數值、`alpha < beta < rc < 正式版`、`+build` 不看、不是 SemVer＝比不出來）。
   Python 的 `semver_key`、網頁的 `semver.js`、發佈前檢查各一份實作，同一組矩陣測試（含 `alpha.2 < alpha.10`、`1.0.9 < 1.0.10`）。
   不引入 `packaging`（它照 PEP 440，跟 SemVer 在預覽版的細節上不一樣，工具的版本是 SemVer）。
2. **同號發過 beta 就不能再發 alpha**：要回內部測試就換下一號（`bump alpha --next patch`：`0.2.1-beta.2 → 0.2.2-alpha.1`）。
   bump 的結果一定排在現在的後面。
3. **`dev` 帶著下一版的號碼**：CHANGELOG 最上面是 `## X（未發佈）`，發版那天 `bump keep` 寫上日期；發完在 `dev` 上 `bump … --planned`。
   所以 `dev` 的版本永遠比最新的 tag 新。
4. **錯版只能往前補**：tag 不移動、不刪；版本號不重用；發錯就發下一個更高的號碼。`check_version_consistency.py`（CI 與發版步驟）
   擋「沒有比每個 tag 新」與「重用號碼」。
5. **不相容的工具新版不算「有新版」**：工具庫清單帶 `requires.synox`／`requires.sdk`，這台不合就在卡片寫原因（跟安裝第 1 關同一句）、
   不出「更新到 v…」、不算在「全部更新」與每週檢查。`requires` 只比 `X.Y.Z`（預覽版的尾巴不看）維持不變：讓工具作者能先用 SYNOX 預覽版測。
6. **通道維持 U3**：檢查更新、每週檢查、`Update.bat` 只看正式版；裝了預覽版的人一樣會收到正式版；預覽版之間用 `-FromZip` 手動升。
   **（2026-11-19 由 [0045](0045-update-channels.md) 取代：擁有者選了下面待決定題的 C。）**
7. **安裝程式不比版本**（Inno Setup 沒有內建）：先寫成已知限制與最小修法（versioning.md §6），等能在 Windows 上建置、實裝驗證再改 `.iss`。

## 待決定（2026-11-19 已決定：C，見 [0045](0045-update-channels.md)）

- **裝了預覽版的人，要不要自動收到下一個預覽版？**（當時：不會，要自己看發佈頁、用 `-FromZip`。）
  選項：A＝維持 U3（建議，最安全、不必改程式）；B＝裝的是預覽版就也看預覽版（`releases?per_page=20`），`Update.bat` 也可以下載預覽版；
  C＝在設定加「更新通道：正式版／測試版」，預設正式版。

## 後果

- 發版多一道檢查（`check_version_consistency.py`），`release.py` 多 `keep`、`--next patch`、`--planned`。
- CHANGELOG 只動標題與位置，沒有刪內容。
- 網頁多一個內嵌的小檔（`semver.js`），`app.html` 不再有自己的比較。
