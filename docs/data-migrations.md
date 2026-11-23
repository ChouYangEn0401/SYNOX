# 資料版本與自動升級

給核心開發者與工具作者看。決定與理由在 [ADR 0044](adr/0044-data-versions-and-migrations.md)；程式在 `src/synox/datastore/`。

一句話：**每一份持久化資料都帶版本號；改資料格式＝加一個遷移步驟＋測試；SYNOX 啟動、工具載入前自動逐版升級；不服務降級。**

## 規則

1. **版本號放哪裡**（每種檔案各自計，整數，從 1 開始）

   | 格式 | 版本號 |
   |---|---|
   | JSON（頂層是物件） | 頂層 `"schema_version"`。早就有自己版本鍵的舊檔沿用舊鍵（`packs.lock` 的 `"version"`）——改名本身就會讓舊的讀取程式壞掉 |
   | SQLite | `PRAGMA user_version` |
   | 其他（YAML、純文字、頂層是清單的 JSON） | 旁檔 `<檔名>.schema`（`{"schema_version": N}`），或改成物件的那一步就是 0→1 |
   | 工具的資料 | `data/pack_data.json` 登記表（工具的資料形狀由工具決定，可能是清單） |

   **沒有版本號＝0（legacy）**。

2. **向上逐版連續升級**：一個步驟只跨一版（`v → v+1`）；框架從檔案的版本一路跑到目前支援的版本（`1→2→3→4`），
   **中間缺任何一步＝拒絕**（不跳過、不動檔案）。步驟是純函式（拿深拷貝、回新內容，不碰檔案），要**冪等**（新格式再跑一次結果一樣），
   每一步各自有測試（用舊格式的假資料）。

3. **安全措施**
   - 升級前自動備份原檔：`<資料夾>/_migration_backups/<檔名>.v<升級前版本>.<時間>.bak`；一次升級（不管跨幾版）只備份一份；
     每個檔留最近 **3** 份（`versioned.KEEP_BACKUPS`）。
   - 全部步驟在記憶體跑完才寫回；寫回＝暫存檔＋`fsync`＋`os.replace`；寫回後重讀驗證，不對就從備份換回。
   - 檔案鎖 `<檔名>.migrate.lock`（`O_EXCL`）：兩個程序同時升級同一份資料只有一個動手，另一個等完重讀版本（通常已經不用做）；
     超過 10 分鐘而且寫鎖的程序已經不在＝殘骸，清掉。
   - 任何一步失敗：原資料原封不動（或已從備份還原）；核心的檔＝SYNOX 不開並說原因；工具的資料＝那個工具不載入，狀態寫原因。

4. **不服務降級**：檔案版本 > 這支程式支援的版本 → 不讀成舊格式、**不寫、不動檔案**，訊息：
   「這份資料是較新版本寫的…請升級 SYNOX 或這個工具，或從備份還原。」核心的檔照樣開 SYNOX（那份檔不會被寫，寫的程式會丟 `TooNewError`）；
   工具的資料＝不載入那個工具。

5. **什麼時候升**
   - SYNOX 啟動（`python -m synox run`）：先升 `config.json`（讀設定之前），讀完設定升 `data/` 裡登記的檔。
   - 工具載入前（每次啟動、安裝／升級後重新載入）：在工具的程式第一次執行之前升它的資料。
   - 看狀態：`python -m synox doctor`（「資料版本」一段）、網頁「設定 → 電腦與備份 → 資料版本」、`python -m synox data status [--json]`。
   - 現在就升：`python -m synox data upgrade --dry-run`（只列會做什麼）、`python -m synox data upgrade`（SYNOX 開著時拒絕）。

## 核心開發者：改一個核心檔的格式

已經接上的檔登記在 `src/synox/datastore/core.py`：

```python
CONFIG = Chain("config.json", current=2, title="設定檔 config.json")   # current +1

@CONFIG.step(1)                    # 1 → 2
def _config_1_to_2(cfg):
    cfg["web"] = cfg.pop("http", {})
    return cfg
```

- 寫這個檔的程式一律先過 `CONFIG.upgrade_data(data)`（寫出去的永遠是目前格式；檔案比較新就丟 `TooNewError`）。
- 測試：舊格式的假資料升上來、讀起來一樣；`chain.gaps() == []`（`tests/test_data_core.py`）。
- 要接一個還沒接上的檔：加一個 `Chain`、`0→1` 步驟（通常只補版本號）、放進 `DATA_FILES`（或自己的升級點）、寫的地方過 `upgrade_data`。
  頂層是清單的檔：0→1 把它包成 `{"items": [...]}`，同時改讀的程式（同一個 commit）；或用旁檔 `.schema`（`upgrade_sidecar_file`）。

## 工具作者：data-adapter 契約

`pack.json`（選填；沒有持久化資料的工具不用寫）：

```json
"data_schema": {"version": 2, "files": ["store", "store:history", "dir"]}
```

| `files` | 是什麼 | 在哪 |
|---|---|---|
| `store` | `pack.store` 的主檔 | `data/<name>.json(.enc)`；伺服器版 `data/users/<id>/<name>.json(.enc)` |
| `store:<key>` | `pack.store.save(x, key="<key>")` | `data/<name>.<key>.json(.enc)`（伺服器版同上） |
| `dir` | 工具自己的資料夾 | `data/packs/<name>/`、`data/<name>/`、`data/users/<id>/<name>/`（有的才算） |

### kind=python

工具資料夾放 `migrations.py`（或 `migrations/` 裡的 `*.py`）：

```python
def migrate_0_to_1(data):          # 宣告 data_schema 以前就有的資料＝0 版
    if isinstance(data, list):     # 舊版頂層是清單
        data = {"items": data}
    return data

def migrate_1_to_2(data):          # store：拿到解開的 JSON（保管箱的會先解密），回新的
    for item in data.get("items", []):
        item.setdefault("done", False)
    return data

def migrate_1_to_2_dir(path):      # dir：就地改這個資料夾（SYNOX 先整份備份，失敗整份換回）
    ...
```

- 一步只升一版；不要跳號；重跑同一步結果要一樣；只用標準函式庫（不能 import 工具自己的模組）；不要連網。
- SYNOX 照 `packs.lock` 對過 `migrations` 檔的 sha256 才編譯執行（不讀 `.pyc`）。
- 安裝時（第 1 關）與 `synox-sdk check` 用 AST 檢查（不執行）：有洞、超過 `version`、`version ≥ 2` 卻一個步驟都沒有、`migrate_1_to_3` 這種跨版的名字＝擋；
  最低的步驟不是 `0→1`＝提醒（更舊的資料升不上來，工具會停用並說明）。
- `synox-sdk init --kind python` 產生的範本已經帶 `data_schema`（version 1）和 `migrations.py` 說明。

### kind=cli

實作子命令（每一步叫一次）：

```
<cli.argv> migrate --from 1 --to 2 --data <資料夾>
```

- 環境變數跟一般指令一樣（`SYNOX_PACK_NAME`、`SYNOX_USER_DATA_DIR`…），另外 `SYNOX_MIGRATE=1`；走同一個沙盒後端
  （可寫的只有工具自己的資料夾；容器裡跑時 `--data` 是容器裡的路徑）。逾時 10 分鐘。
- 結束碼 0＝成功；非 0、或最後一行 JSON 是 `{"ok": false, "error": "…"}`＝失敗（`error` 會顯示給擁有者）。
- 只支援 `dir`。SYNOX 看不到 cli 工具有哪些步驟：請自己用舊版資料測過每一步。

### 其他種類

`mcp`、`connector`、`theme` 宣告 `data_schema`＝安裝時拒。MCP 伺服器自己的資料由它自己管（SYNOX 沒有可靠的方式在它啟動前叫它升級）。

### 版本怎麼記、什麼時候升

- 版本記在 `data/pack_data.json`：`{"schema_version": 1, "packs": {"<name>": {"version": N, "pack_version": "…", "at": "…"}}}`。
- 沒有紀錄：有資料＝0 版；沒有資料（新裝的）＝直接記成目前版本，不跑步驟。
- 每次載入工具前檢查；升級報告會先寫「資料會在新版第一次啟動前從 N 升到 M」；新版認得的版本比現在的舊（退回、或拿掉了 data_schema）＝紅字。
- 退回舊版（`packs rollback`）之後資料比工具新＝工具不載入、資料不動：再升回新版，或從 `_migration_backups/` 的備份還原。

## 盤點（2026-11-19，核心會寫到磁碟的資料；日誌除外）

`D`＝`data/`，`R`＝SYNOX 資料夾。「接上了」＝已經登記在框架裡。

| 檔案 | 格式 | 版本號 | 頂層 | 誰寫 → 誰讀 | 性質 | 接上了 |
|---|---|---|---|---|---|---|
| `R/config.json` | JSON | `schema_version`（新） | 物件 | wizard/logic.write_config → config.SynoxConfig.load | 設定 | ✅ |
| `D/packs.lock` | JSON | `version`（沿用） | 物件 | packs/lock → lock.load | 核准紀錄 | ✅ |
| `D/pack_data.json` | JSON | `schema_version` | 物件 | datastore/packdata.record → recorded | 工具資料版本 | ✅ |
| 工具的 `D/<name>[.<key>].json(.enc)`、資料夾 | 工具決定 | `pack_data.json` | 工具決定 | 工具 | 使用者資料 | ✅（工具宣告 data_schema 才有作用） |
| `D/identities.json` | JSON | `version: 2`（程式裡自己轉 v1） | 物件 | identity.Identities | 帳號對應 | 待接 |
| `D/secrets.json.enc`、`D/pack_secrets.json.enc` | 保管箱 | 無 | 物件 | vault／packs/secrets | 密鑰 | 待接 |
| `D/(users/<id>/)stepup.json.enc` | 保管箱 | 無 | 物件 | guard/store | 安全設定 | 待接 |
| `D/runtime_soul.json.enc`、`runtime_soul_ledger.json.enc`（`v: 1`） | 保管箱 | 部分有 `v` | 物件 | runtime/soul、ledger | 使用者資料 | 待接 |
| `D/runtime_soul_audit.json.enc`、`runtime_mother_memory.json.enc` | 保管箱 | 無 | **清單** | runtime/soul、mother | 使用者資料 | 待接（要包成物件或旁檔） |
| `D/health/tools.json.enc` | 保管箱 | `v: 1`（讀時只收 1） | 物件 | health/store | 狀態 | 待接 |
| `D/(users/<id>/)schedule.json(.enc)` | 保管箱｜JSON | 無（每筆 `v: 2`） | **清單** | schedule/store | 使用者資料 | 待接（要包成物件或旁檔） |
| `D/notifications/<id>.json(.enc)`、`outbox/<id>`（`v: 1`） | 保管箱｜JSON | 部分有 `v` | 物件 | notify/store、outbox | 使用者資料／佇列 | 待接 |
| `D/web_chats/<id>.json(.enc)`、`media/` | 保管箱｜JSON／二進位 | 無 | 物件 | web/chats、chatmedia | 使用者資料 | 待接 |
| `D/web_prefs/`、`D/user_prefs/`、`D/tour/<id>.json(.enc)` | 保管箱｜JSON | 巢狀 `version: 1`（版面、別名） | 物件 | web/toolpage.UserPrefs | 設定 | 待接 |
| `D/llm_usage.json`、`D/ai_budgets.json`、`D/stepup_hints.json`（**清單**）、`D/discord_last_bot.json`、`D/packs_tamper_notified.json` | JSON | 無 | 物件／清單 | agent/loop、budget、guard/commands、discord、lock | 狀態／設定 | 待接 |
| `D/apps.json`、`D/remote.json`、`D/update_check.json`、`D/remind/settings.json`、`D/runtime/state.json` | JSON | 無 | 物件 | web/apps、web/remote、update/check、notify/deskapp、runtime/loop | 設定／狀態 | 待接 |
| `D/deps.json`（2026-11-23，[adr/0047](adr/0047-web-update-and-deps-sync.md)） | JSON | `schema_version: 1`（比較新的版本寫的：不讀、不覆蓋） | 物件 | update/deps.sync → deps.sync、web 卡片 | 設定（記住的選裝組）／狀態（上次補裝的結果） | 待接 |
| `D/remind/engine.json`、`D/remind/desk/style.json`（`v: 1`） | JSON | `v: 1` | 物件 | schedule/engine、remindwin/style | 狀態／快取 | 待接 |
| `D/users.json`、`D/blocked.json`（**清單**）、`daily_usage.json`、`rate_exemptions.json`、`muted.json`、`penalties.json`、`last_update_id` | JSON／文字 | 無 | 清單／物件 | vendor SDK（`vendor/isdtelekit`，不改） | 使用者／狀態 | 待接（SDK 檔：在 SYNOX 端包一層或旁檔） |
| `D/.synox.key` | 文字 | 魔術字 `SYNOXKEY1` | – | vault/keyring | 金鑰 | 不接（自己有格式版本） |
| `R/lang.txt` | 文字 | 無 | – | wizard/i18n | 設定 | 待接（旁檔） |
| `D/agent_index.json`、`D/mcp/<pack>.tools.json`、`D/envs/<pack>/env.json` | JSON | 有／無 | 物件 | 每次重建 | 快取 | 不需要（重建） |
| `D/web_tokens.json`、`D/web_sessions.json`、`D/restart.json`、`R/keepawake_state.json`、`D/host.lock`、各種 `.lock`、`D/prefs/…`、`D/web_uploads/…`、`D/update/…`、`D/remind/desk/to_win|from_win` | JSON | 無 | 物件 | 各自 | 暫存／鎖 | 不需要（短命；格式改了丟掉重建即可，改的時候再決定） |

沒有 SQLite、沒有 YAML。日誌（`security_audit.jsonl`、`apps_audit.jsonl`、`remind/sentinel.log`、`logs/`、`job_logs/`）不在範圍內。
