---
name: moneybook
description: 使用者提到花了多少錢、收入、想記帳、問這個月花多少或還能花多少、要設預算、說剛剛記錯了、要匯出或匯入帳本 CSV 時使用（金流簿，每個人自己一本）。
---

# 金流簿（moneybook）

每個人的帳本是分開的（伺服器上一人一本）。工具名＝`moneybook__<指令>`；參數名就是欄位名。
所有回覆是 JSON：成功時看 `text`（給人看的一句話，可以直接轉述）與 `warnings`；失敗看 `error.message` 與 `error.hint`。

## record：記一筆

- 「午餐 120」「便當 120 現金」→ `moneybook__add`：`amount=120`、`desc=便當`；類別不確定就**不要填**（程式會依內容和時間猜）。
- 金額只放整數（元），不要帶「元」「$」或逗號。退款不能用負數：請使用者到網站或改一筆。
- 有說用哪個帳戶才填 `account`（用 `moneybook__accounts` 看名字）；沒說就用預設帳戶。
- 一定要填 `time`：使用者說了就用他說的，沒說就用他叫你記的那一刻（他所在地的當地時間，`HH:MM`）。
- 日期不是今天才填 `date`（西元 `YYYY-MM-DD`，不是民國年）。
- 收入（薪水、兼職、退款回饋）→ `moneybook__income`。
- 回覆裡有 `warnings`（例：「放待分類」「快超過預算」）要轉述給使用者。
- 一次說了好幾筆：一筆叫一次 `moneybook__add`。

## query：查詢

- 「這個月花多少」「還能花多少」→ `moneybook__summary`。
- 「最近記了什麼」「上禮拜吃了哪些」→ `moneybook__list`（`q=關鍵字`、`category=`、`period=2026-10`）。
- 「預算還剩多少」→ `moneybook__budget`；「額度還好嗎」「有沒有超支」→ `moneybook__check`。
- 有哪些類別、帳戶 → `moneybook__categories`、`moneybook__accounts`。

## budget：預算

- 「食的預算一個月 9000」→ `moneybook__budget_set`：`group=食`、`amount=9000`。`group` 是**大類**（食、衣、住、行、育、樂、醫療、其他），
  不是細項（早餐、午餐）。不確定大類名字先叫 `moneybook__categories`。

## undo：記錯了

- 「剛剛那筆記錯了」「不要了」→ `moneybook__undo`（撤銷**最近一批**寫入）。這是 DANGER：會先送確認卡，使用者按了才做。
- 撤銷之後要改成對的，就再 `moneybook__add` 一次。

## files：匯出匯入（搬家）

- 「把十月的帳匯出來」→ `moneybook__export`：`month=2026-10`；回覆的 `data.path` 是檔案位置。CSV 用 Excel、記帳城市、Moze 都打得開。
- 「匯入這個 CSV」→ `moneybook__import_csv`：`file=<檔名>`（放在使用者自己的 files 資料夾，用相對檔名）。
  第一列要是欄名，至少 `date`、`amount`；其餘 `time,type,category,account,to_account,description,merchant,note`（中文欄名「日期、金額、類別、說明、帳戶、備註」也可以）。
  `type`：expense／income／transfer（或 支出／收入／轉帳），不寫＝支出。同一個檔再匯一次只會回「已記過」，不會多。
- 帳戶找不到會失敗並告訴你是第幾列、有哪些帳戶：請使用者改 CSV 或先建帳戶（網站或 CLI `account add`）。

## setup：第一次用、選配的格子

- 第一次用不需要特別做什麼（第一筆就會開好帳本）。想先看類別再記，叫 `moneybook__init`。
- 起始的類別是食衣住行育樂醫療其他、一個「現金」一個「銀行帳戶」。
- 想記奉獻、投資、還債、薪資扣繳（勞保健保）→ `moneybook__features` 看開了沒，`moneybook__enable`（`feature=tithe|invest|debt|payroll|trading`）打開；重按不會多。

## 不要做的事

- 不要猜金額、不要把一筆拆成好幾筆、不要自己編類別名（不確定就不填）。
- 不要替使用者按撤銷；不要讀或寫別人的檔案（檔名只用相對路徑）。
- AI 檢討書在伺服器版是關的（`llm_unavailable`）：要檢討就自己用 `summary`、`list`、`check` 的數字跟使用者聊。
