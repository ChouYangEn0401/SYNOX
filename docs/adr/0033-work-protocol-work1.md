# ADR 0033：工作協定 `work/1`——核心與「會一次改好幾筆的工具」之間的七個動作

- 日期：2026-11-17
- 狀態：**提案（契約定稿，還沒有程式）**。分支 `docs/core-unification-adr`。
- 基準：分支 `dev`，commit `86a930d`。文中的檔名都是這個 commit 的。
- 來源：合一規劃（維護者的私有文件庫，2026-11-17）第 11.1 節。這份是它的定稿；兩邊不一樣的地方列在最後一節。
- 編號：0031、0032 留給同時進行的兩個實作分支（給 AI 結構化結果與核准後叫醒、SOUL 習慣）各自的 ADR；這一批設計用 0033–0040。
- 同一批：[0034](0034-pack-agent-work.md)（pack.json 怎麼宣告）、[0035](0035-workmode-core.md)（核心怎麼把關）、
  [0036](0036-triangle-review.md)（三角審查）、[0037](0037-approval-cards-upgrade.md)（核准卡）、
  [0038](0038-wake-ai-after-card.md)（核准後叫醒 AI）、[0039](0039-local-project-link.md)（接本機專案）、[0040](0040-notify-lanes.md)（通知分流）。
- 標籤（沿用 0022）：**已查證**（讀過程式）／**推測**／**待實測**／**提案值**（數字可以改）。

## 背景

一次真實的失誤：AI 要把十幾筆行程往後重排，做法是逐筆新增、再逐筆刪除，時間是它自己心算的。四個原因：

1. 沒有計算工具，AI 心算；
2. AI 拿到的是給人看的文字，不是資料；
3. 沒有人強制「先查、再算、再給人看、再套用」的順序；
4. 套用之後沒有人重讀資料核對，也沒有退路。

核心不可能認得每一個工具的資料長什麼樣子（工具是可以安裝的）。所以「算方案、整批套用、核對、退回」做在**工具自己**裡面；
核心只規定一份協定，照協定把關（[0035](0035-workmode-core.md)）、畫卡（[0037](0037-approval-cards-upgrade.md)）、找人挑錯（[0036](0036-triangle-review.md)）。

## 決定

| # | 題目 | 決定 |
|---|---|---|
| 1 | 誰算、誰套用 | 工具自己。核心不算方案、不一筆一筆替工具寫入、不記「怎麼退」 |
| 2 | 介面 | 七個**角色**：`query`、`plan`、`check`、`show`、`apply`、`verify`、`revert`。每個角色是工具的一個指令（kind=cli 的 `commands[]`、kind=mcp 的工具、kind=python 的指令），回 SYNOX 的 JSON 信封 |
| 3 | 哪個指令扮哪個角色 | 在 pack.json 的 `agent.work` 宣告（[0034](0034-pack-agent-work.md)）。指令叫什麼名字由工具決定 |
| 4 | 必備與選配 | 必備：`query`、`plan`、`show`、`apply`、`verify`、`revert`。選配：`check`（沒有就用方案自己帶的 `violations`）。`query` 與 `plan` 可以是同一個指令（比對本身就是計算的那一類，例如對帳） |
| 5 | 方案是不可變的 | `plan` 每次產生一個新的 `plan_id`；已經產生的方案不再改。一個方案最多套用一次，產生一個 `batch_id` |
| 6 | 新鮮度 | `fingerprint`＝範圍內每一筆的雜湊。`apply` 時現況跟方案記的不一樣就拒絕（`stale`） |
| 7 | 整批 | `apply` 先留快照；任何一步失敗就還原、回報哪一步 |
| 8 | 失敗的碼 | 協定自己的碼（下面第 4 節）直接放在信封的 `code`；屬於「流程上的拒絕」的那幾種一定帶 `failure.scope = "input"`，不算進工具健康的暫停門檻 |
| 9 | 版本 | 協定本身叫 `work/1`。每個回傳另外帶工具自己的 `contract`（`<工具>.<動作>/1`）。不相容的改動開 `/2` |

## 1. 七個角色

`effect` 是 pack.json 裡那個指令的風險等級（[0034](0034-pack-agent-work.md) 在安裝時檢查）。「輸入」只列協定規定的；工具可以有自己的參數。

| 角色 | effect | 輸入 | 做什麼 | 核心怎麼用 |
|---|---|---|---|---|
| `query` | READ | 範圍、篩選、`prefs` | 讀現況，回機器讀的資料與 `fingerprint` | AI 的第一步 |
| `plan` | READ | 排哪些、參數、`prefs`、`waive[]` | **只算**。寫的只有工具自己的方案紀錄，不碰使用者的資料 | AI 的第二步 |
| `check` | READ | `plan_id`，或一份動作清單＋`prefs` | 對方案（或清單）跑規則檢查 | 開卡前核心叫；卡片最上面的 ⚠ |
| `show` | READ | `plan_id` | 讀一份已存的方案 | 畫卡、給挑錯者、判斷新不新鮮 |
| `apply` | DANGER | `plan_id`（選配 `fingerprint`） | 整批套用 | AI 呼叫＝開卡；人按了才真的執行 |
| `verify` | READ | `plan_id` 或 `batch_id` | 重讀真的資料、逐筆對方案 | 套用後核心一定叫 |
| `revert` | DANGER | `batch_id`、`force` | 整批退回 | 「↩ 整批退回」；不給 AI（`ai=false`） |

`plan` 的 effect 是 READ：它寫的是工具自己的方案紀錄（放在工具自己的資料夾），不是使用者的資料。

## 2. 信封與欄位

沿用現有的信封（[sdk.md](../sdk.md)）：成功 `{"ok": true, "message": "…", "data": {…}}`；失敗 `{"ok": false, "code": "…", "error": "…"}`。
下面是各角色 `data` 的欄位。**必**＝一定要有；其他選填。工具可以多帶自己的欄位，核心忽略不認得的。

共同規則：

- 時間一律 ISO 8601、帶時區位移（`2026-11-22T09:00:00+08:00`）。`id` 一律字串。
- 給人看的字（`summary`、`say`、`show.*`、`notes[]`、`label`）是**純文字、一行、最多 200 字**。核心把它們當資料：
  畫卡時逐字顯示（照通道跳脫），給 AI 時包在這一輪的分隔符裡（第 5 關）。
- `contract`（必）：`<工具>.<動作>/1`，例如 `cal.plan.make/1`。

### 2.1 `query`

| 欄位 | 必 | 說明 |
|---|---|---|
| `contract` | ✅ | |
| `fingerprint` | ✅ | 字串，最多 128 字。範圍內每一筆的（id、開始、結束、標題、狀態——或這個領域等價的欄位）的雜湊。同樣的資料算出同樣的值 |
| `items[]` | ✅ | 每筆有 `id` 與機器讀的欄位（領域自己定） |
| `total` | ✅ | 範圍內總筆數 |
| `truncated` | | `true`＝超過工具自己的上限：`items` 是空的，只回統計，`message` 請呼叫端縮小範圍 |
| `stats` | | 統計（領域自己定） |

### 2.2 `plan`

| 欄位 | 必 | 說明 |
|---|---|---|
| `contract`、`plan_id` | ✅ | `plan_id`：`[A-Za-z0-9_-]{1,64}` |
| `expires` | ✅ | 這份方案到什麼時候為止可以套用 |
| `fingerprint` | ✅ | 算方案時的現況 |
| `summary` | ✅ | 一行：這份方案做什麼 |
| `changes[]` | ✅ | 每一筆改動（下表）。最多 200 筆；超過＝失敗 `bad_input`，請呼叫端縮小範圍 |
| `unplaced[]` | ✅ | 排不進去的：`{"id", "label", "why"}`。沒有就是 `[]` |
| `violations[]` | ✅ | 還違反的規則（下表）。沒有就是 `[]` |
| `loosened[]` | ✅ | 這次放寬了什麼：`{"rule", "from", "to", "say"}`。沒有就是 `[]` |
| `notes[]` | | 給人看的補充，例如「用的是預設值」 |
| `timeline[]` | | 動到的每一天的**完整**時間軸（下表）。有時間概念的領域要給；最多 31 天 |
| `table` | | 給寬畫面看的表：`{"columns": ["…"], "rows": [["…"]]}`，最多 60 列 |

`changes[]` 的一筆：

```json
{"op": "move", "id": "ev_102",
 "before": {"start": "2026-11-20T20:00:00+08:00", "end": "2026-11-20T21:30:00+08:00", "title": "學A觀念（第 3 部）"},
 "after":  {"start": "2026-11-22T09:00:00+08:00", "end": "2026-11-22T10:30:00+08:00", "title": "學A觀念（第 3 部）"},
 "show": {"title": "學A觀念（第 3 部）", "before": "11/20（四）20:00–21:30", "after": "11/22（六）09:00–10:30"}}
```

- `op`（必）：`move`｜`edit`｜`add`｜`delete`。`add` 的 `id` 與 `before` 是 `null`；`delete` 的 `after` 是 `null`。
- `before`、`after`（必）：機器讀的欄位，領域自己定。
- `show`（必）：工具自己排好的人話（`title`、`before`、`after` 各一行）。**核心不替任何領域排版**：卡片上的「之前 → 之後」就是這三個字串。

`violations[]` 的一筆：`{"rule": "schedule.class.after_minutes", "where": "11/22（六）", "ids": ["ev_102"], "say": "課後 90 分鐘內排了東西"}`。
`rule` 是穩定的規則鍵（有對應的習慣鍵就用它）；`waive[]` 用的就是這個鍵。

`timeline[]` 的一天：

```json
{"day": "2026-11-22",
 "entries": [{"start": "09:00", "end": "10:30", "title": "學A觀念（第 3 部）", "id": "ev_102", "tag": "moved"},
             {"start": "13:00", "end": "15:00", "title": "學B觀念", "id": "ev_007", "tag": "fixed", "kind": "class"}]}
```

`tag`：`fixed`（沒動）｜`new`｜`moved`｜`edited`。`kind` 是領域自己的分類（選填）。

### 2.3 `check`

輸入是 `plan_id`，或一份動作清單（`changes[]` 的 `op`／`id`／`after`）＋`prefs`。
回 `contract`、`violations[]`（同上）、`checked`（看了幾筆）。只講**這次新排或改到的**，不把原本就有的舊問題全倒出來。

### 2.4 `show`

回 `plan` 的 `plan_id`、`expires`、`fingerprint`、`summary`、`changes[]`、`unplaced[]`、`violations[]`、`loosened[]`、`timeline[]`、`table`，再加：

| 欄位 | 必 | 說明 |
|---|---|---|
| `state` | ✅ | `open`（還沒套用）｜`applied`｜`reverted`｜`expired` |
| `fresh` | ✅ | 現況的 `fingerprint` 是不是還等於方案記的 |
| `batch_id` | | `state` 是 `applied`／`reverted` 時 |

### 2.5 `apply`

輸入 `plan_id`。`fingerprint` 選填：有給就多比一次（要等於方案記的）。

- 成功：`{"contract", "plan_id", "batch_id", "steps": <總步數>, "applied": <做了幾步>}`。`batch_id`：`[A-Za-z0-9_-]{1,64}`。
- 失敗：信封的 `code` 是第 4 節的碼；`data` 帶 `{"failed_step": <第幾步，從 1 起>, "steps", "rolled_back": true|false}`。

`apply` 的指令**不要**再用 `needs_confirm` 要求確認：開卡是核心的事（AI 呼叫＝開卡），兩層確認只會讓人按兩次。

### 2.6 `verify`

輸入 `plan_id` 或 `batch_id`。

| 欄位 | 必 | 說明 |
|---|---|---|
| `contract`、`ok` | ✅ | `ok`＝`missing`、`extra`、`changed`、`violations` 全空 |
| `matched`、`total` | ✅ | 方案的目標裡對上幾筆、共幾筆 |
| `missing[]` | ✅ | 方案說該有、現在沒有的 |
| `extra[]` | ✅ | 方案的範圍內現在有、算方案時沒有、方案也沒說要加的 |
| `changed[]` | ✅ | 在，但欄位跟方案的 `after` 不一樣 |
| `violations[]` | ✅ | 對**真的資料**再跑一次規則檢查的結果 |

`missing`／`extra`／`changed` 的一筆：`{"id", "show": {"title", "expected", "actual"}}`（同樣是工具排好的人話）。

### 2.7 `revert`

輸入 `batch_id`、`force`（布林，預設 `false`）。

- 回 `{"contract", "batch_id", "reverted": <退回幾筆>, "skipped": [{"id", "why", "show": {…}}]}`。
- 套用之後**又被改過**的那幾筆，預設不動、列在 `skipped`；`force=true` 才連它們一起退。
- 退回用的是 `apply` 當時留的快照，不是「把方案反過來算一次」。

## 3. 規則

1. **同輸入同輸出**：`plan` 不用亂數、不用模型、不看現在幾點以外的外部狀態。同樣的資料與參數跑兩次，`changes[]` 一樣（`plan_id` 可以不同）。
2. **新鮮度**：`apply` 時重算現況的 `fingerprint`，跟方案記的不一樣就拒絕（`stale`），什麼都不寫。
3. **整批**：`apply` 先留快照；任何一步失敗就還原到快照、回報哪一步（`apply_failed`、`rolled_back: true`）。還原也失敗＝`rollback_failed`、`rolled_back: false`（核心會用紅字告訴使用者資料停在半路）。
4. **習慣由呼叫端帶**：`prefs` 一律由核心帶進來，工具自己只有通用預設。沒帶就用預設，並在 `notes[]` 寫「用的是預設值」。
5. **方案先自己檢查**：`plan` 內部先跑一次 `check`，結果放 `violations[]`。核心之後再叫 `check`，兩邊對不上照樣回報。
6. **放寬要寫出來**：呼叫端用 `waive[]` 放寬的規則，不再出現在 `violations[]`，但一定出現在 `loosened[]`（核心會把它寫在卡片最上面給人看）。
   保留的放寬鍵 `unplaced`＝「排不進去的那幾筆這次先不管」。
7. **失敗一律是失敗信封**：`ok: false`、`code`、`error`（一句可以直接給人看的話）。不可以回成功信封再在 `message` 裡說失敗。
8. **方案不可變**：重算＝新的 `plan_id`。一個方案只能套用一次；再套用一次＝`already_applied`（`data.batch_id` 帶上次那個）。
9. **留多久**：方案與批次紀錄至少留最近 20 份；方案的 `expires` 至少是產生後 1 小時。過期的方案 `show` 仍然讀得到（`state: "expired"`），`apply` 拒絕（`plan_expired`）。
10. **一次只有一個寫入者**：`apply`／`revert` 等不到工具自己的寫入鎖＝`busy`，什麼都不做。不可以排隊到背景晚點再寫。
11. **`query` 與 `plan` 同一個指令時**：那個指令回的 `data` 同時滿足 2.1 與 2.2（`items[]` 可以省略）。

## 4. 失敗的碼

| `code` | 哪個角色 | 意思 | `failure.scope` | 核心接著做什麼 |
|---|---|---|---|---|
| `stale` | `apply` | 現況跟方案記的不一樣 | `input` | 回到查詢（重新 `query`＋`plan`） |
| `plan_expired` | `apply`、`check` | 方案過期 | `input` | 回到計算 |
| `violations` | `apply` | 方案還有沒放寬的違規（工具自己的防線） | `input` | 回到計算 |
| `already_applied` | `apply` | 這份方案套用過了 | `input` | 直接去核對 |
| `already_reverted` | `revert` | 這一批退回過了 | `input` | 告訴使用者 |
| `busy` | `apply`、`revert` | 等不到寫入鎖，什麼都沒做 | `input`，`retry.ok = true` | 告訴使用者，可以再按一次 |
| `not_found` | 全部 | 沒有這個 `plan_id`／`batch_id` | （既有的碼） | 回到計算 |
| `bad_input` | 全部 | 參數不對、範圍太大 | （既有的碼） | AI 改參數 |
| `apply_failed` | `apply` | 中途失敗，已經整批還原 | `tool` | 回報哪一步；可以重算 |
| `rollback_failed` | `apply`、`revert` | 中途失敗，還原也失敗 | `tool` | 紅字警告，不再自動做任何事 |

跟工具健康（[tool-health.md](../tool-health.md)）的關係（**已查證** `src/synox/health/failure.py`）：

- 現在不認得的碼一律變成 `unclassified`（scope 預設 `tool`、算進暫停門檻）。所以上表前六個**一定要自己帶** `"failure": {"v": 1, "scope": "input"}`——
  它們是流程上的正常拒絕，不該讓工具被暫停。
- 實作 PR 把這八個新碼加進 `health/failure.py` 的 `CODES` 與 SDK 的 `FAILURE_CODES`（給 AI 的那一行才會是對的提示，例如 `stale`＝「資料變了，重新查詢再規劃」）。
- 工作模式（[0035](0035-workmode-core.md)）讀的是**工具回的原始信封**，不是正規化之後的；所以舊版 SYNOX 遇到這些碼只是少了提示，不會誤判流程。

## 5. 兩個例子對一次

一份協定只有一個實作就定案，容易長成那個實作的樣子。所以拿兩個性質不同的領域對一次。

| 協定 | 排程（行事曆專案） | 對帳（帳本專案） |
|---|---|---|
| `query` | 一段日期內的行程（每筆的起訖、分鐘、系列、狀態） | 跟 `plan` 同一個指令 |
| `plan` | 把沒做完的往後排：每筆 `move`；排不進去的進 `unplaced` | 帳單 vs 記帳的比對：少記的＝`add`、金額不同＝`edit`；帳單沒有而帳上有的**不動**，寫在 `notes[]` |
| `check` | 課後緩衝、吃飯時窗、系列順序、連續太久、太晚 | 可以不做（重複檢查放在 `plan` 的 `violations`） |
| `show` | 方案表＋動到的每一天的時間軸 | 方案表（沒有 `timeline`） |
| `apply` | 整批改期 | 只補少記與金額不同 |
| `verify` | 每筆都在、時間標題一樣；範圍內沒有多的；規則檢查 0 條 | 再比一次：少記與金額不同應該是 0（原本就多的那幾筆不算 `extra`，因為算方案時就在了） |
| `revert` | 回到快照；之後被改過的不動 | 同 |
| `fingerprint` | 範圍內每筆的（id、開始、結束、標題、狀態） | 那張帳單的每一列＋那段期間每筆帳的（id、日期、金額、對象） |

對下來的結論：`timeline`、`check` 要是選配；`show` 要是必備（核心畫卡只認它）；`extra` 的定義要寫成「算方案時沒有的」。

## 不做的事

- **核心不替工具做整批**：沒有宣告 `agent.work` 的工具，核心不會把它的十筆寫入「包成一批」。那是寫入日誌與退回（另一份 ADR）的事。
- **不規定領域欄位**：`items[]`、`before`、`after` 裡有什麼，由工具的 `contract` 自己定。
- **不做跨工具的方案**（一份方案同時改行事曆與記帳）。
- **不自動套用**：`apply` 永遠在卡片後面。**不自動退回**：核對沒過只列差異＋給按鈕。
- **不做背景排隊的套用**（規則 10）。
- **這一版不把檢查器放進單檔 SDK**：`synox-sdk check` 只做 [0034](0034-pack-agent-work.md) 的宣告檢查。

## 測試怎麼寫

**核心這邊**（`tests/test_work_protocol.py`；不執行任何外部程式）：

1. 新檔 `src/synox/agent/workproto.py`：只用標準函式庫、不 import `synox`（跟 `workmode.py` 同一條規則，有一個測試檢查它的 import）。
   `ROLES`、`CODES`、`validate(role, envelope) -> list[str]`（回問題清單，空的＝合格）、`flow_refusal(code) -> bool`（上表 scope 是 `input` 的那幾個）。
2. 黃金檔 `tests/fixtures/work/`：每個角色一份合格的信封（`<角色>.ok.json`），以及壞掉的各一份（缺必備欄位、`op` 不認得、`show` 不是字串、
   `changes` 超過 200 筆、`plan_id` 有不准的字元、給人看的字有換行）。`validate` 對合格的回 `[]`，對壞的回的問題要點名欄位。
3. 兩個例子各一組（排程、對帳），資料用假的（課名一律「學X觀念」這種代稱、金額用整數的假數字），證明同一個 `validate` 兩邊都過。
4. `health/failure.py`：八個新碼都在 `CODES`；`stale`、`plan_expired`、`violations`、`already_applied`、`already_reverted`、`busy` 不算進門檻；
   舊工具回不認得的碼照舊是 `unclassified`。

**工具這邊**（寫在工具自己的 repo；給實作的人照抄的清單）：

1. 假資料 → `plan` 的 `violations` 是空的、`unplaced` 列得出排不進去的。
2. 同輸入跑兩次，`changes[]` 一樣。
3. 資料改了之後 `apply` 回 `stale`，而且什麼都沒寫。
4. `apply` 中途失敗 → 資料跟套用前一模一樣、`rolled_back: true`、`failed_step` 對。
5. 少一筆時 `verify.missing` 列得出來；多一筆時 `verify.extra` 列得出來。
6. `revert` 後回到快照；套用之後又改過的那筆在 `skipped`，`force=true` 才退。
7. 沒帶 `prefs` 用預設並在 `notes[]` 說明。
8. 同一份方案 `apply` 第二次回 `already_applied`；`revert` 第二次回 `already_reverted`。
9. 前六個流程碼的信封都帶 `failure.scope = "input"`。
10. 每個成功信封拿去跑核心的 `workproto.validate`（把 `workproto.py` 與黃金檔複製過去，或在測試裡用路徑指到 SYNOX 的那一份）都回 `[]`。

## 跟規劃不一樣的地方

| 規劃 | 這份 | 為什麼 |
|---|---|---|
| 七個角色都列，沒說哪些必備 | `check` 選配，其他六個必備 | 對帳沒有獨立的檢查；但核心畫卡、挑錯、判斷新鮮度都要 `show`，所以對帳那邊要多一個「讀已存的方案」的指令 |
| `changes[]` 只有 `op`、`before`、`after` | 多一個必備的 `show`（工具排好的人話） | 核心不認得領域欄位，沒辦法替它排「之前 → 之後」 |
| `apply` 帶當時的 `fingerprint` | `fingerprint` 改成選填；方案紀錄自己記著，方案不可變 | 核心沒有「由系統填、AI 看不到」的欄位；方案不可變時再傳一次是多餘的 |
| `show` 回 `changes`、`table`、`timeline` | 多 `state`、`fresh` | 核心要知道方案還能不能套用，又不想自己算雜湊 |
| 失敗 `code: "stale"` | 多七個碼，並規定 `failure.scope` | 不規定的話，正常的拒絕會把工具推進暫停清單（**已查證**） |
| 沒寫 | `loosened[]` 一定列出放寬的；保留鍵 `unplaced` | 放寬是 AI 傳的參數，要讓人在卡片上看得到 |
