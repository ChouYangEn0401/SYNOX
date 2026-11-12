# tests/fixtures/packs：host 測試用的 pack（不是出廠功能）

`money`、`notes`、`remind` 是 2026-11-12 下架前內建版本的**凍結複本**，只給 SYNOX 自己的測試當「隨便一個 python pack」用
（AI 工具清單、網頁、權限、伺服器版每人一份資料、排程……很多測試拿 `/money 120 午餐`、`/note …` 當例子）。

- 正本在 **SYNOX_Libs**（工具庫）的 `packs/`，功能改在那裡、測試也在那裡。這裡**不要加功能**，也不用跟著同步。
- `tests/conftest.py` 的 `make_bot` 沒指定 `pack_dirs` 時只載入這裡（以前還加 `connectors/`，2026-11-12 搬到工具庫了）；
  伺服器版的測試會先用 `trust_core` 把它們鎖成 core（等於擁有者安裝時選了「核心」）。
- 為什麼內建工具下架：[../../../legacy/builtin-packs.md](../../../legacy/builtin-packs.md)、[../../../legacy/connectors.md](../../../legacy/connectors.md)。
- 4 個 connector 的測試（Notion、Todoist、Google 日曆、Apple）跟著搬到工具庫的 `tests/`；SYNOX 這邊要讀工具庫的測試
  （`test_empty_host`、`test_smoke_real`、`test_sdk_p2_secret` 的一部分）看環境變數 `SYNOX_LIBS`，找不到就跳過。
