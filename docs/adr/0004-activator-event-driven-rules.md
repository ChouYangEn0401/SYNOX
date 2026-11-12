# ADR 0004：連動（activator）——任務做完就馬上觸發下一件，防無限連動

- 日期：2026-11-12
- 狀態：已採用（分支 `feat/activator`）
- 網頁 API 合約：[../runtime-api.md](../runtime-api.md)（`activator` 那一節）
- 前一份：[ADR 0001](0001-runtime-loop-heartbeat-mother-session.md)（runtime loop、心跳、任務狀態回報）

## 背景

ADR 0001 之後，背景任務照**間隔**跑，心跳每 45 分鐘「看一輪」。要接著做的事（「A 做完了 → 做 B」）只能等下一次排程或心跳，
最慢要等 45 分鐘；工具之間也沒辦法說「我做完了，你接著做」。

要的是一層**事件驅動**的連動：

- 任務做完（ok／failed）、pack 回報狀態時，記一筆快速、會存檔的「狀態變了」；符合規則的動作**馬上**做，可以一串接一串。
- 不急的可以留成「待處理」，下一次心跳（或主控面板按一下）再做；主控面板與狀態 API 看得到。
- **一定要防無限連動**：A→B→A 的循環、自己觸發自己、一個事件觸發一大片。被擋下的規則要看得到原因、可以重設。
- 規則可以由系統程式與 pack 定義，也可以寫在 `config.json`；不另做一套權限。

用得到的例子（另一個 Telegram bot 會照這個形狀做，這裡只放成測試與示範 pack）：
**每日日記的圖片產生成功 → 馬上再問使用者一次要不要打卡**。

## 參考：成熟的系統怎麼做事件觸發與防循環（2026-11-12 查）

| 系統 | 做法 | 拿來用的 |
|---|---|---|
| Home Assistant automations | 每個 automation 有 `mode`：`single`（預設；還在跑時新的觸發**不開**、記警告）、`restart`、`queued`、`parallel`；後兩種有 `max`（預設 10）。事件帶 `context`（id＋parent_id），看得出是誰引起的 | 預設 `single`；事件帶因果（串 id＋上一層） |
| GitHub Actions | 用 `GITHUB_TOKEN` 做的事件**不會**再觸發新的 workflow（防遞迴）；reusable workflow 最多串 4 層 | 連動串有層數上限；同一串裡同一條規則不能再出現 |
| Airflow | DAG 一定無環，解析時就檢查循環；trigger rule（`all_success`、`one_failed`…）決定下游什麼時候跑 | **登記時**靜態找循環；條件寫成「變成哪個狀態、從哪個狀態變過來」 |
| Zapier | flood protection：一次來太多觸發（預設 100 筆）就**先扣住**、讓人決定要不要放行（不是自動丟掉） | 全部連動有總量上限，超過就整個暫停、通知、等人按「恢復」 |
| 斷路器模式（circuit breaker） | 一直失敗就斷開，不再呼叫，等條件好了再接 | 規則被擋＝暫停（斷開）、通知一次、手動重設才恢復 |

參考網址：Home Assistant「Automation modes」（home-assistant.io/docs/automation/modes）、GitHub Docs「GITHUB_TOKEN」與「Reusing workflows」
（docs.github.com）、Zapier Help「Choose your Zaps' flood protection limit」（help.zapier.com）。Airflow 的無環檢查與 trigger rule 是它的核心概念（airflow.apache.org 的 DAG 文件）。

**不照抄的**：Home Assistant 的 `queued`／`parallel`（要排隊與同時跑的上限管理，現在沒有需要）；Zapier 的「扣住等人放行每一筆」
（這裡改成整條規則暫停＋待處理項目留著，比較好懂）；Temporal 那種完整的工作流程引擎（太大，這裡只要「做完 → 做下一件」）。

## 決定

### 1. 事件（`src/synox/runtime/loop.py`、`activator.py`）

- `RuntimeLoop` 的任務狀態一變（排程的一次執行做完、逾時、pack 回報）就叫 `loop.listeners`（**在鎖外**；例外只記 log，不弄壞任務或回報）。
  `Activator.observe` 掛在那裡。
- 一個事件：`task`（任務 id）、`state`、`prev`（變之前的；排程任務＝開始跑之前的）、`tag`（選填標籤）、`owner`、`at`、
  `chain`（連動串 id）、`depth`（第幾層）、`path`（這一串走過的規則）、`message`（**只在記憶體**）。
- **標籤（tag）**：pack 回報時可以多帶一個短標籤（小寫英數字與 `. _ -`，32 字內），讓規則分得出「是哪一件事做完了」。
  一個 pack 只有一個任務 `pack.<名字>`，標籤就是用來區分「日記圖片好了」（`diary-image`）和「問過打卡了」（`checkin-asked`）。
  python pack：`pack.report_status(state, message, tag=)`；SDK：`report_status(state, message, tag=)`（信封 `status.tag`）。不合格式＝當作沒有。
- **因果**：連動叫 `run_now(task, cause=…)` 時，那個任務做完的事件接在同一串（層數＋1）；程式動作在 `caused_by(cause)` 裡執行，
  裡面回報的狀態、叫的 `run_now` 也自動接上（執行緒區域變數）。程式自己另開執行緒就接不上——那時靠每條規則的次數上限與全部的總量擋。
- 沒有規則在聽的事件**不記**（任務狀態本來就存在 `tasks`；不然每 30 秒一次的排程會把紀錄洗掉）。

### 2. 規則

一條規則＝「任務 `on` 變成 `state`（可加：從 `from` 變過來、標籤 `tag`、程式條件 `when`）→ 做一件事」：

| 動作 | 意思 | 誰能用 |
|---|---|---|
| `run_task` | 跑一個登記了 fn 的任務（`loop.run_now`，不是手動、帶因果） | config.json、系統；pack 只能跑**自己的**任務（`pack.<名字>`） |
| `notify` | 通知擁有者一句話（前面加 🔗；可以用 `{task}`、`{state}`、`{tag}`） | config.json、系統、pack |
| `do` | 呼叫程式 `do(event)` | 系統、python pack（`pack.on_event`）；**config.json 不收程式** |

其他欄位：`timing`（`now`＝馬上，在自己的執行緒做；`heartbeat`＝留成待處理）、`cooldown_s`（預設 0）、`max_per_hour`（預設 30）、
`enabled`、`name`（給人看）、`emits`（只有程式：`do` 會讓哪些任務有新狀態，寫成 `"pack.x"` 或 `"pack.x#標籤"`，給靜態找循環用）。

**三種定義方式**：

```json
// config.json（擁有者寫的；只收資料）
"runtime": {"activator": {"rules": [
  {"id": "weather-back", "on": "pack.weather", "state": "ok", "from": "failed", "notify": "天氣恢復了"},
  {"id": "after-sync", "on": "pack.syncer", "tag": "nightly", "run_task": "system.schedule", "timing": "heartbeat"}
]}}
```

```python
# python pack 的 install(app, pack)（規則 id 會是 pack.<名字>.<rule_id>）
def ask_checkin(event):
    app.notify_owner("今天的日記圖片好了。要打卡今天的日記嗎？")
    pack.report_status("ok", "問過打卡了", tag="checkin-asked")

pack.on_event("pack.diarydemo", "ask-checkin", ask_checkin, state="ok", tag="diary-image",
              emits=["pack.diarydemo#checkin-asked"], cooldown_s=60)

# 系統程式（規則 id 要用 system. 開頭）
from synox.runtime.activator import Rule
runtime.of(app).activator.add(Rule(id="system.x", on="pack.weather", states=("failed",), do=fn))
```

pack 比 runtime 早載入：`pack.on_event` 先排在 `app.extras`，`runtime.install` 再登記。形狀錯當場丟 `RuleError`（給寫的人看）；
會繞回自己＝**不收**、記在主控面板「沒有收的規則」，**不讓整個 pack 載入失敗**。config.json 的規則有循環＝啟動時 `ConfigError`（跟其他設定錯一樣）。

### 3. 防無限連動（每一條都有測試，`tests/test_activator.py`）

| 機制 | 預設 | 碰到時 |
|---|---|---|
| 登記時靜態找循環（規則 A 會讓任務 T 有新狀態、規則 B 聽 T 而且標籤對得上＝A 接 B；有環） | — | 不收（config＝啟動錯誤、系統程式＝`RuleError`、pack＝記在「沒有收的規則」） |
| 同一串裡同一條規則第二次（執行時的循環，含自己觸發自己） | — | **暫停那條規則** |
| 連動串的層數 | `max_depth` 5 | 暫停那條規則 |
| 同一串做的總件數（擋「一個觸發十個、十個再觸發十個」） | `max_chain_actions` 20 | 暫停那條規則 |
| 一個事件最多觸發幾條規則 | `max_fanout` 10 | 多的那幾條這次略過（不暫停） |
| 每條規則的冷卻 | `cooldown_s` 0 | 安靜略過 |
| 每條規則一小時最多幾次 | `max_per_hour` 30 | 暫停那條規則 |
| 上一次還沒做完（Home Assistant `single`） | — | 這次略過 |
| 動作連續失敗（跟 loop.py「連續失敗 5 次」一樣） | 5 次 | 暫停那條規則 |
| 全部規則加起來的總量 | `budget_max_actions` 60 件／`budget_window_min` 10 分鐘 | **全部暫停** |
| 留給心跳的待處理最多幾件 | 100 件；超過一天的丟掉 | 新的略過 |

- **暫停（斷路器）**：不再做；通知擁有者**一次**（10 分鐘內有好幾條被暫停只說一則，下一則會說「另外還有 N 條」）；
  主控面板與 `GET /api/runtime/status` 看得到原因與時間；**要人按「重設」才恢復**（時間過了不會自己恢復）。全部暫停一樣，按「恢復」。
- 暫停狀態存檔：重開 SYNOX 還是暫停的。
- 寧可多擋：靜態檢查不看 state（ok／failed 都可能），沒宣告 `emits` 的程式動作靜態看不到，交給執行時的檢查。

### 4. 留給心跳（`timing: "heartbeat"`）

- 規則符合時不馬上做，記成**待處理**（存檔，沒有訊息）。主控面板列出來，可以「現在處理」或「不用做了」。
- 每次心跳（`system.heartbeat`）一開始先把待處理做掉（在背景開始做，不等），結果那句多「另外處理了 N 件留給心跳的連動」。
  **不放進給 AI 的快照**（不然每處理一件就多叫一次 AI，跟 ADR 0001「沒變就不叫 AI」衝突）。
- 規則暫停中、或全部暫停中：待處理**留著**，重設／恢復後下一次再做；規則不見了或關掉了＝丟掉；超過一天＝丟掉（心跳關著時不會一直堆）。

### 5. 權限（沿用既有的，不另做一套）

- config.json 是擁有者自己寫的：可以跑任何任務、通知；不收程式。
- pack 本來就只能碰自己的任務（`report_status` 只能回報 `pack.<自己>`）：規則 id 要用 `pack.<自己>.` 開頭、`run_task` 只能跑自己的。
  pack 的 `do` 是它自己的程式，跟它在 `install` 裡能做的一樣，沒有多給權限。伺服器版第三方 python pack 的限制（owner_only）照舊。
- **別人的訊息不給**：交給 pack 程式的事件，不是它自己的任務時 `message` 是空的——跟 `peer_status` 只給狀態與時間一樣（pack 之間不互相讀資料）。
- 網頁 API 跟其他 `/api/runtime/*` 一樣只給擁有者、寫入要 CSRF。

### 6. 存檔與隱私（照 ADR 0001：沒有個人資料的結構才落地）

`data/runtime/state.json` 多一塊 `activator`：每條規則的暫停原因與時間、上一次觸發的時間、連續失敗數；全部暫停的原因；
待處理項目（規則 id、任務 id、state、標籤、時間、串 id、層數、走過的規則）；有規則在聽的最近 50 個事件（任務 id、state、標籤、時間、串 id、
哪些規則做了／略過與原因）。**任務的訊息、規則動作的錯誤訊息只在記憶體。**暫停原因都是 SYNOX 自己寫的固定句子。

### 7. 設定（`config.json` 的 `runtime.activator`）

```json
"activator": {"enabled": true, "max_depth": 5, "max_chain_actions": 20, "max_fanout": 10,
              "budget_window_min": 10, "budget_max_actions": 60, "rules": []}
```

範圍：`max_depth` 1～10、`max_chain_actions` 1～100、`max_fanout` 1～50、`budget_window_min` 1～1440、`budget_max_actions` 1～1000；
規則最多 100 條（config）／全部 200 條；`cooldown_s` 0～86400、`max_per_hour` 1～600、`notify` 200 字內。
`enabled: false`＝事件照記、規則一律略過（主控面板顯示「關著」）。`doctor` 印開關、config 的規則數、暫停中的規則、待處理件數。

### 8. 網頁 API 與主控面板

- `GET /api/runtime/status` 多一個 `activator` 物件（規則、暫停原因、待處理、最近的事件、沒有收的規則、上限與這段時間用了多少）。
- `POST /api/runtime/activator/rules/<id>/reset`、`/activator/resume`、`/activator/pending/run`、`/activator/pending/<id>/dismiss`。
- 主控頁多一張「🔗 連動」卡：每條規則一列（狀態徽章、「當〈任務名〉變成〈狀態〉→ 動作（馬上／等心跳）」、上次、暫停原因＋「重設」）、
  全部暫停的說明＋「恢復」、待處理（每件「不用做了」、整批「現在處理」）、最近的連動紀錄。後端沒有這塊（舊版）就整張不顯示。

## 不做的（這一版）

- kind=cli／mcp 的 pack **不能定義規則**（只有 python pack 與系統）。cli pack 的回報可以帶標籤、被別人的規則聽到。
  要讓 cli pack 在 `pack.json` 宣告「做完 → 跑我的某個指令」，得決定那個指令「以誰的身分」跑、要不要過確認卡（五關），另外再決定。
- 動作沒有「跑一個 pack 指令」（同上）、沒有「叫常駐助理想一想」（會花 AI 額度，要先定上限）。
- 規則的條件只有 state／from／tag（資料）與程式的 `when`；不做運算式語言（不在 config.json 裡跑字串成程式）。
- 沒有 `queued`／`parallel` 模式、沒有自動恢復（半開）的斷路器。
- 通知不看心跳的安靜時段（要「馬上」的就馬上；不急的用 `timing: "heartbeat"`）。
- 網頁上不能新增／修改規則（改 `config.json` 或寫在 pack 裡）。

## 後果

- 好：「做完 → 馬上做下一件」不用等排程或心跳；循環在登記時就擋掉大部分，漏掉的在執行時第二圈就停；暴衝有總量上限；
  被擋下的看得到原因、一個按鈕恢復；重開不會忘記哪條被暫停。
- 代價：每次有規則在聽的狀態變化多寫一次 `state.json`（檔很小）；連動的程式在背景執行緒跑，pack 作者要自己顧好不要卡太久
  （卡住的那條規則之後的觸發會被「上一次還沒做完」略過）；程式自己開執行緒時因果接不上，只剩次數上限與總量擋。
- 測試：全部用假時鐘、同步執行、假通道（`tests/test_activator.py`、`tests/js/test_control.js`）；不連網、不開埠。
