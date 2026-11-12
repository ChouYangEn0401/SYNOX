# tests/fixtures/packs：host 測試用的 pack（不是出廠功能）

`money`、`notes` 是 2026-11-12 下架前內建版本的**凍結複本**，只給 SYNOX 自己的測試當「隨便一個 python pack」用
（AI 工具清單、網頁、權限、伺服器版每人一份資料、排程……很多測試拿 `/money 120 午餐`、`/note …` 當例子）。
以前還有 `remind`：提醒在 2026-11-12 回到核心當系統指令（「⏰ 提醒（系統）」，QuestionToUser QL5），測試直接用核心的 `/remind_*`，
所以這份複本拿掉了（最後一版在 git 歷史；工具庫那份在 SYNOX_Libs 的 `legacy/remind/`）。

- 正本在 **SYNOX_Libs**（工具庫）的 `packs/`，功能改在那裡、測試也在那裡。這裡**不要加功能**，也不用跟著同步。
- `tests/conftest.py` 的 `make_bot` 沒指定 `pack_dirs` 時載入這裡＋`connectors/`；伺服器版的測試會先用 `trust_core` 把它們鎖成 core
  （等於擁有者安裝時選了「核心」）。
- 為什麼內建工具下架：[../../../legacy/builtin-packs.md](../../../legacy/builtin-packs.md)。
