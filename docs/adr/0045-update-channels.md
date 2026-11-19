# ADR 0045：更新檢查同時顯示正式版與測試版、更新通道

- 日期：2026-11-19
- 狀態：**已採用**（分支 `release/0.2.2-alpha.2`；擁有者的需求：檢查更新要看得到正式版和測試版，並說明測試版的號碼比同號的正式版小）。
- 修訂：[0023](0023-updates-and-hotfixes.md) 的 U3（App 只看正式版）；決定 [0043](0043-version-order-and-upgrade-matrix.md) 的「待決定」題（選 C）並取代它的第 6 點。
- 規則全文：[docs/versioning.md](../versioning.md) §7。
- 程式：`src/synox/update/check.py`（`fetch_channels`、`pick`、`channel`、`set_channel`、`CheckResult.stable／preview`）、
  `update/prepare.py`（`include_prerelease`）、`update/web_api.py`（`/api/settings/update/channel`）、`web/static/app.html`（「也提醒我有測試版」）、
  `__main__.cmd_update`（`--channel`、`--include-prerelease`）、`setup/update.ps1`（`-IncludePrerelease`）。
- 測試：`tests/test_update_channels.py`（另外 `test_update.py`、`test_update_testpath.py` 跟著改了連線次數與文字）。

## 背景

`0.2.2-alpha.1` 發佈時被標成 GitHub 的 Latest（還沒有任何正式版）。「設定 → SYNOX 更新」卡片只問 `releases/latest`、只收正式版，
所以顯示「❌ GitHub 上還沒有 SYNOX 的正式版」，而且完全看不到已經發佈的測試版。擁有者要卡片同時看得到正式版與測試版，
並說清楚測試版的號碼比同號的正式版小。

## 決定

1. **每次檢查問兩件事**（只在按「檢查更新」、`synox update --check`、使用者打開的每週檢查時連網；目的地寫死；不新增背景抓取）：
   (a) 最新正式版：`releases/latest`，再擋一次 pre-release／草稿／有尾巴的版本號——Latest 指到 alpha／beta 時算「還沒有正式版」，不是「看不懂」；
   (b) 最新測試版：`releases?per_page=20`，排除草稿，只看預覽版（有尾巴或標了 pre-release），**用 SemVer（`semver_key`）挑最大的**，不用 GitHub 的時間順序。
2. **卡片、`synox update --check` 一定顯示兩行**：「最新正式版：X（比你裝的新／跟你裝的一樣／比你裝的舊）」或「還沒有正式版」；
   「最新測試版：Y（…）」或「沒有測試版」；附一句「測試版的號碼比同號的正式版小：0.2.2-alpha.1 < 0.2.2-beta.1 < 0.2.2」。
   一邊連不上或回應格式不對（欄位缺、版本號不是 SemVer），那一行寫「無法判斷（原因）」，另一行照常；整個檢查從不丟例外。
3. **更新通道** `config.json` `"updates": {"channel": "stable" | "preview"}`，**預設 stable**：
   - stable：「有新版」（卡片、橫幅、每週通知、`--check` 結束碼 10、`Update.bat`）只算正式版；有比你新的測試版時卡片多一句怎麼打開。
   - preview：正式版與測試版取 SemVer 較大的。
   - 卡片一個勾選「也提醒我有測試版」（預設不勾）、`synox update --channel stable|preview`。
   - `--include-prerelease`（命令列）＝這一次當 preview：結果不存、不出橫幅（跟以前一樣）；設定選了 preview 的結果照常存。
   - 新鍵是**選填**：缺鍵、寫錯＝stable。照 [0044](0044-data-versions-and-migrations.md) 的規則，新增選填鍵、舊檔缺鍵＝預設值，**不需要遷移步驟**，
     `config.json` 的 `schema_version` 不變（測試守著：舊檔升級後照樣是 stable；帶新鍵的目前版本檔不會被改）。
4. **`Update.bat -IncludePrerelease`**：把 `--include-prerelease` 同時傳給 `--check` 與 `--prepare`（設定選了 preview 時不用加，Python 自己讀設定）。
   下載與驗證跟正式版**同一條**：`SHA256SUMS.txt` 必須有、有 `release.json`＋簽章就一定要驗過、沒有簽章要明確 `-AllowUnsigned`、不降級。
   版本比較只在 Python（SemVer）；`update.ps1` 不比版本號，只在換完檔確認「裝著的＝要裝的」（字串相等，這是對的）。
5. 狀態多一種 `none`：通道上一個版本都沒有（例如 stable 而 GitHub 上還沒有正式版）——不是錯誤，不出 ❌，結束碼 0。

## 為什麼不選別的

- **只問 `releases?per_page=20` 一次**（從清單裡同時挑正式版與測試版）：少一次連線，但 GitHub 自己標的 Latest 是「正式版」最直接的來源，
  而且清單只有最近 20 筆；照擁有者的要求兩個都問。代價：每次檢查多一個 GET（GitHub 匿名每小時 60 次，夠用）。
- **裝了預覽版就自動看預覽版**（0043 的 B）：使用者不知道自己為什麼收到測試版；改成明確的開關。
- **用 GitHub 的時間順序**：補發、重發會讓舊號碼排在前面（`alpha.2` 晚於 `alpha.10` 發）；一律 SemVer。

## 已知代價與不做

- 「更新…」按鈕在切換通道後要再按一次「檢查更新」才會跟著變（不為了切換通道自動連網）；切回 stable 時，上次查到的測試版不再出橫幅、不給「更新…」。
- 安裝程式（`.exe`）與 git 裝法不受影響（照舊各自的路）。
- `update.ps1` 的實際換檔只能在 Windows 上跑；這次只加了一個旗標的轉交，測試是靜態檢查（同 0023 的做法）。

## 測試怎麼守

`tests/test_update_channels.py`（全部用假的 GitHub，不連網）：只有預覽版、只有正式版、兩者都有、兩者都沒有；Latest 指到 alpha；
`0.2.2-alpha.1 < 0.2.2`、`alpha.2 < alpha.10`（清單順序故意打亂、草稿不算）；stable／preview 的「有新版」；設定缺鍵、寫錯、舊檔升級；
每週檢查照通道通知；卡片兩行文字與切換通道的 API、橫幅；`--include-prerelease` 與設定 preview 的輸出一樣；回應格式異常顯示「無法判斷」；
`prepare` 下載測試版一樣要 `SHA256SUMS.txt`、沒簽章要明確同意、不降級；`update.ps1` 把旗標傳給 `--check` 與 `--prepare`。
