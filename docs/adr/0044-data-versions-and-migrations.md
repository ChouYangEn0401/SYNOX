# ADR 0044：每份持久化資料都有版本號，升級時逐版連續遷移（核心與工具同一套）

- 日期：2026-11-19
- 狀態：提案（框架、核心三個檔、工具契約、doctor／設定頁／`data` 指令已實作；待擁有者確認下面「待決定」幾題）
- 分支：`feat/data-migrations`

## 背景

SYNOX 本體與工具都會一直升版。以前資料格式要不要轉換是各自的事（`docs/pack-format.md` 寫「pack 自己的事」），
大部分檔案沒有版本號：新版程式讀到舊格式只能猜，猜錯就把使用者的資料用壞；退回舊版之後，舊程式也可能用舊格式把新資料蓋掉。
維護者的要求：正常升級不能壞；每份檔案都有版本數值；升級要一版一版連續做；不特別服務降級；核心與工具走同一套。

## 決定

1. **版本號**（每種檔案各自計，整數 ≥ 1，**沒有＝0**）：JSON 頂層 `schema_version`；早就有版本鍵的沿用（`packs.lock` 的 `version`）；
   SQLite `PRAGMA user_version`；其他格式用旁檔 `<檔名>.schema`；工具的資料記在 `data/pack_data.json` 登記表。
2. **逐版連續升級**（`synox/datastore/migrate.py` 的 `Chain`）：登記 `v→v+1` 的步驟，框架從檔案版本一路跑到目前版本；
   缺任何一步＝`GapError`，不跳過、不動檔案。步驟是純函式、冪等、各自有測試。
3. **安全**：升級前備份（`_migration_backups/`，每檔留最近 3 份）；全部在記憶體跑完、暫存檔＋原子取代寫回、重讀驗證；
   跨程序檔案鎖；任何失敗＝原資料不動或已還原。核心的檔失敗＝SYNOX 不開；工具的資料失敗＝那個工具不載入（狀態寫原因）。
4. **不服務降級**：檔案版本 > 支援版本＝不讀成舊格式、不寫、不動檔案，講人話（升級或從備份還原）。核心的寫入點一律先過
   `Chain.upgrade_data`（寫出去的永遠是目前格式；檔案比較新丟 `TooNewError`）。
5. **時機**：啟動時先升 `config.json` 再升 `data/`；工具在**載入前**（新版第一次執行之前）升；doctor、網頁設定頁（`GET /api/settings/data`，只看）、
   `python -m synox data status|upgrade [--dry-run]` 顯示每份資料的版本。
6. **工具契約**（pack.json 新欄位 `data_schema: {"version", "files"}`，`files`＝`store`／`store:<key>`／`dir`）：
   python 工具放 `migrations.py` 的 `migrate_<n>_to_<n+1>(data)`／`…_dir(path)`（照 packs.lock 對過雜湊才執行，只讀原始碼）；
   cli 工具實作 `<cli.argv> migrate --from N --to N+1 --data <資料夾>`（同一套沙盒、環境變數；只支援 `dir`）；
   mcp／connector／theme 不支援（安裝時拒）。第 1 關（安裝）與 `synox-sdk check` 用 AST 擋有洞的步驟序列；升級報告寫資料會從幾版升到幾版。
7. 規則寫進 `AGENTS.md`：**所有持久化資料都有版本；改資料格式＝加一個遷移步驟＋測試。**

## 為什麼不選別的

- **欄位叫 `data`**：`pack.json` 的 `data` 早就是權限宣告（none｜user｜shared，PERM-2），改成物件會讓舊版 SYNOX 拒收所有新工具。所以叫 `data_schema`。
- **把 `packs.lock` 的 `version` 改名成 `schema_version`**：改名本身就是一次不相容的格式改動，讀它的程式（含舊版 SYNOX）全部要跟著改；沿用舊鍵沒有任何代價。
- **在工具的資料檔裡塞版本號**：工具的資料形狀是工具決定的（可能是清單、可能是密文），塞進去會改到工具讀到的內容。改由核心的登記表記。
- **每一步都寫檔**：中途失敗會留下半升級的資料。改成全部在記憶體跑完一次寫回（資料夾：整份備份、失敗整份換回）。
- **自動降級**：要每個工具寫反向步驟，且很難測對；維護者明說不服務降級。改成拒絕並保留備份。
- **新增相依套件（例如檔案鎖、遷移框架）**：標準函式庫就做得到（`O_EXCL` 鎖檔、`os.replace`、`sqlite3`），不加。

## 已知代價與不做

- 只接上了 `config.json`、`packs.lock`、`pack_data.json` 與工具資料；其他核心檔（保管箱裡的使用者資料、SDK 的 `users.json`…）列在
  `docs/data-migrations.md` 的盤點表，**之後要改它們的格式時再接**（加 Chain＋0→1＋寫入點過 `upgrade_data`）。頂層是清單的檔要先包成物件或用旁檔。
- `config.json` 多一個 `schema_version` 欄位（精靈、設定頁寫入時自動帶）；`packs.lock` 第一次升級時會補 `version`。
- 舊版 SYNOX 不認得 `data_schema`：裝在舊版上的工具不會被升級資料（工具要靠 `requires.synox` 擋）。
- cli 工具的步驟 SYNOX 看不到，只能在執行時發現缺步驟；MCP 伺服器的資料不支援。
- 工具的資料夾升級是整份備份：資料夾很大時慢、佔空間（每份留 3 個）。
- 逐檔升級：同一個工具的多個檔之間沒有交叉一致性的保證（任何一個失敗會全部換回，但步驟本身看不到別的檔）。

## 待決定（擁有者）

1. 備份保留幾份（現在 3；也可以「每個版本一份、永遠留」或「留 N 天」）。
2. cli 遷移契約的細節：子命令名 `migrate`、旗標名、逾時 10 分鐘、是否需要 `--dry-run` 旗標。
3. `config.json` 加頂層 `schema_version` 是否可以（替代：放旁檔 `config.json.schema`，使用者手改設定時看不到它）。
4. 核心設定檔要不要藉這次重整結構（這次**沒有**重整，只加版本號）。
5. 其他核心檔的接入順序（建議：保管箱裡的使用者資料 → `identities.json` → 設定類 → SDK 的檔）。

## 工具庫（SYNOX_Libs）的採用計畫

這次不改工具庫。之後另開任務逐一採用，建議順序：

1. **用 `pack.store` 的 python 工具**（記帳、筆記這類）：宣告 `data_schema: {"version": 1, "files": ["store", …]}`、
   放 `migrations.py` 的 `migrate_0_to_1`（多半原樣回傳，或把頂層清單包成物件）；`requires.synox` 提到有這個功能的版本。
2. **有自己資料夾的 python 工具**（`pack.path`／`pack.path_of`）：加 `dir` 與 `migrate_0_to_1_dir`。
3. **cli 工具**（資料在 `{user_data_dir}/<name>/`、`data/packs/<name>/`）：實作 `migrate` 子命令，`data_schema.files: ["dir"]`。
4. **mcp 工具**：不採用（寫在工具的 README）。

核心端看到的工具資料型態：`pack.store`（`storage=vault` 是密文 `data/<name>.json.enc`，否則 `data/<name>.json`；
`key=` 另存 `data/<name>.<key>.json(.enc)`；伺服器版每人 `data/users/<id>/…`，頂層形狀由工具決定，可能是清單）；
`pack.path(...)`＝`data/packs/<name>/`（大家共用）；`pack.path_of(user, ...)`＝`data/<name>/files/`（個人版）或 `data/users/<id>/<name>/files/`；
cli 工具的 `{user_data_dir}/<name>/`（`data=user`）與 `data/packs/<name>/`（`data=shared`）；`{prefs_file}` 是暫存檔（不用遷移）；
`connect` 存的 `data/<name>.auth.json(.enc)`（核心寫的，之後跟著核心接）。

## 測試怎麼守

`tests/test_data_migrate.py`（框架：連續升級、單步多步、缺步驟、冪等、失敗還原、降級拒絕、無版本＝0、兩個執行緒與兩個真程序的鎖、
原子寫入中斷、備份保留、旁檔、SQLite、資料夾）、`tests/test_data_core.py`（核心三個檔、啟動時升級、失敗停下、doctor、`data` 指令、
設定頁 API）、`tests/test_data_packs.py`（契約解析、AST 步驟檢查、安裝與 SDK 擋有洞、python／cli／伺服器版／資料夾、雜湊不符拒執行、
沙盒包裝、工具升級後新版載入前先升資料、資料比工具新＝不載入、升級報告）。
