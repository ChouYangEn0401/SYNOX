# 下架：出廠內建的三個工具（money、notes、remind）

2026-11-12 起 SYNOX 出廠**不帶任何工具**，`packs/` 只剩說明。

> **後來（同一天，QuestionToUser QL5）：提醒回到核心了**，但不是回到 `packs/`：`/remind_*` 現在是 SYNOX 的**系統指令**
> 「⏰ 提醒（系統）」（跟 `/help`、`/schedule_*` 同一層，`src/synox/schedule/commands.py` 的 `install_system_remind`），不用裝、資料照舊。
> 工具庫的 `remind` 工具下架到 SYNOX_Libs 的 `legacy/remind/`。下面的表照當時記錄留著。

## 原本做什麼

| 工具 | 指令 | 做什麼 | 資料 |
|---|---|---|---|
| 💰 記帳 `money` | `/money 120 午餐`、`/money_month`、`/money_list`、`/money_budget` | 記一筆、看這個月、設每月預算；網頁工具頁有本月面板 | `data/money.json.enc`（伺服器版 `data/users/<id>/`） |
| 📒 隨手記 `notes` | `/note …`、`/note_list`、`/note_rm`、`/note_clear` | 記一筆、找、刪 | `data/notes.json.enc` |
| ⏰ 提醒 `remind` | `/remind_add 08:00 吃藥`、`/remind_list`、`/remind_rm` | 每天幾點提醒、或某一天一次（程式本體在 `src/synox/schedule`，pack 只把指令掛上去） | `data/schedule.json.enc`（跟 `/schedule_*` 同一份） |

它們放在 repo 的 `packs/`，`src/synox/packs/loader.py` 的 `BUNDLED` 把它們當成「出廠＝信任（core）」，不用安裝、不看 `packs.lock`。

## 為什麼下架

擁有者 2026-11-12：工具應該用 plugin 安裝的方式進來，host 一開始是空的，「我會提供這個主程式，和一大堆工具壓縮檔，別人要什麼再自己來安裝」。
寫死在主程式裡的工具繞過了安裝流程（五關、雜湊鎖），也讓「工具」跟「主程式」的界線不清楚。
三個工具搬到另一個專案 **SYNOX_Libs（工具庫）**，在那裡宣告依賴的 SDK 版本、打包成 `.synoxpack`、有自己的測試。
設計見 SYNOX_Libs 的 `docs/adr/0001-tool-library-and-sdk-dependency.md`。

## 從舊版更新上來的人

- 更新後 `/help` 裡記帳、筆記會不見，**資料沒有動**（`data/` 裡的檔照舊）。
- 從工具庫裝同名的工具（`money`、`notes` 的 `.synoxpack`）就回來，資料接著用。
- 提醒不會不見：它是系統指令「⏰ 提醒（系統）」，`data/schedule.json.enc` 直接接上。裝過工具庫舊 `remind` 工具的人，SYNOX 會把它標成
  「不需要了」、不載入（到網頁設定頁移除即可）。
- `/schedule_*`（排程替你跑指令）是 SYNOX 本體的功能，沒有下架。

## 怎麼救回（不建議，除非工具庫拿不到）

原始碼在 git 歷史裡，最後一版是下架前的那個 commit：

```
git log --oneline -1 -- packs/money          # 找到「搬走」的那個 commit，它的上一個就是最後一版
git show <那個 commit>^:packs/money/pack.py
git checkout <那個 commit>^ -- packs/money packs/notes
```

再把 `loader.BUNDLED` 加回 `"money", "notes"`。（提醒不用救：已經是系統指令。）測試用的凍結複本在 `tests/fixtures/packs/`（只給測試用，不要直接當正本）。
