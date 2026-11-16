# ADR 0029：提醒必達——疊在通知中心上的資料格式、排程回執、送達介面

- 日期：2026-11-16
- 狀態：**提案（契約已定，實作分三包）**。分支 `feat/core-w0-remind-contract`。
- 基準：通知中心（`docs/notifications.md`、`src/synox/notify/`）與排程（`src/synox/schedule/`）在 `c132b4c` 的樣子。
- 契約程式（只有型別、常數、純函式；要動檔案或管道的本體是 `NotImplementedError`）：
  `src/synox/schedule/reminder.py`（一筆提醒／待辦）、`src/synox/schedule/receipt.py`（排程回執）、
  `src/synox/notify/delivery.py`（送達介面）、`src/synox/notify/desk.py`（電腦提醒視窗與哨兵的檔案溝通）。
- 測試：`tests/test_remind_contract.py`
- 編號：工具登記與索引的 ADR 請用 0030。

## 背景

「幫我記得…」答應了卻沒響，是助理最傷信任的失敗。通知中心（網頁 🔔、Telegram／Discord 分送、去重、分類靜音、
鬧鐘的「知道了／5 分鐘後再提醒」、晚 60 分鐘內照響、更早的說「你錯過了」、設好時說何時何處會響）已經補掉一大半；
還沒補的是：**送出去有沒有成功沒人管**（一次性的提醒不管成敗都刪掉）、**只有 SYNOX 開著才會響**、
**沒有電腦上的提醒視窗**、**時間只存「HH:MM＋日期」字串**、**沒有待辦**、**AI 說「會提醒你」沒有依據可查**。

原則：**疊在通知中心上，不另做一套、不拆掉重寫**；不破壞現有測試與行為；數字衝突時取「對使用者最不意外」的。

## 1. 差距表（設計目標 × 現在的通知中心）

「已有」＝現在的程式就做到；「部分」＝做了一部分；「沒有」＝要新做。「誰補」對應第 5 節的包。

### 1.1 提醒的資料與到點

| 項目 | 現況 | 程度 | 怎麼補 | 誰補 |
|---|---|---|---|---|
| 絕對的到點時間 | `time`（HH:MM）＋`date`（YYYY-MM-DD 或空）字串 | 部分 | 加 `due`（ISO、帶時區），舊欄位照寫（§3.1） | W1 |
| 重複方式（一次／每天） | 有（`date` 空＝每天） | 已有 | 改成明寫 `repeat` | W1 |
| 狀態（排著／響著／延後／完成／錯過／取消／沒人回） | 沒有：一次性的響完就刪，每天型只記 `last_run` | 沒有 | `status` 七種（§3.1） | W1 |
| 延後 | 「5 分鐘後再提醒」＝另加一筆一次性的提醒，只能按一次、沒有次數 | 部分 | 同一筆改 `snooze_until`、`snooze_count`；可延後多次；再響時寫「延後第 N 次之後」 | W1（邏輯）、W2（按鈕、視窗） |
| 每個管道的送達紀錄 | `hub.notify` 回 `{"telegram": bool…}`，沒人存、沒人看 | 沒有 | `deliveries[管道] = DeliveryRecord`（§3.3） | W2 產生、W1 存 |
| 舊資料自動轉換 | — | 沒有 | `reminder.upgrade_item`：讀到就轉，冪等，讀不懂的原樣留著 | W1 |
| 到點判斷：「到點 ≤ 現在、這一次還沒處理」 | `_late_min`：時間過了、今天還沒跑、建立之後才到的，就算到點（不只剛好那一分鐘） | 部分 | 改用 `due` 比對；沒送成功不算處理完 | W1 |
| 晚了照響 | 60 分鐘內照響並寫晚幾分鐘 | 已有 | 沿用 60 分鐘（§2） | — |
| 補送界線與彙整 | 超過 60 分鐘一則一則說「你錯過了」，沒有上限 | 部分 | 60 分鐘～6 小時：一則一則說錯過；超過 6 小時：併成一則「有 N 個提醒在沒開的時候過了」 | W1 |
| 每天型的補送 | 只看今天那一次 | 已有 | 沿用；更早的不補、在彙整那一則提一句 | W1 |
| 過去的時間擋下 | `/remind_add` 擋「今天已經過了」，叫你填明天的日期 | 部分 | 解析時間用語後才判斷；擋下時問「是要明天嗎？」 | W1 |
| 時間用語解析（「等等」「12.51」「半小時後」「明早」） | 沒有：AI 自己換算成 HH:MM | 沒有 | 新 `schedule/timeparse.py`，兩種可能差很多時回「要問」 | W1 |
| 待辦（沒有時間的） | 沒有 | 沒有 | 同一份清單，`due=None`、`repeat="none"`；視窗下半部 | W1（資料、指令）、W2（視窗） |
| 引擎自己壞掉 | 排程任務走 runtime 的失敗退避，連續失敗會拉長到 30 分鐘 | 沒有 | 系統提醒任務的退避上限 1 分鐘，連續失敗直接通知「提醒引擎停了」 | W1（需要 runtime 登記多一個參數） |

### 1.2 送達

| 項目 | 現況 | 程度 | 怎麼補 | 誰補 |
|---|---|---|---|---|
| 多個管道同時送 | 網頁、Telegram、Discord 各自 try，一條壞掉不影響別條 | 已有 | 沿用，包成 ChannelAdapter | W2 |
| 送達確認 | Telegram／Discord 看回傳的 `ok`，但結果沒人用；網頁存進清單就算 | 部分 | 管道回 `DeliveryResult`；SENT 才算送到 | W2 |
| 失敗重試（30 秒、1、2、5、10 分，之後每 15 分，最多 6 小時） | 沒有 | 沒有 | `RetryPolicy`＋存檔的佇列（重開照樣重試） | W2 |
| 佇列存在哪 | — | 沒有 | `data/notifications/outbox/<id>.json(.enc)`，跟通知清單同一套加密 | W2 |
| 任一邊成功就算通知到、另一邊繼續試 | 沒有 | 沒有 | `DeliveryTicket.notified`／`settled` | W2 |
| 去重 | 12 小時內同一個 key 只送一次 | 已有 | 提醒那一次用 `message_key(rid, occurrence, owner)` 當 key | W1 |
| 按鈕：完成／延後 | Telegram／Discord／網頁有「知道了」「5 分鐘後再提醒」 | 部分 | 按鈕改成回頭叫 `ReminderActions.act`；文字「知道了」不變 | W2 |
| 兩邊同步（一處按了、其他處收掉） | 只拿掉自己那則的按鈕 | 沒有 | `Outbox.resolve` → 其他管道 `retract(note)`：「✅ 在電腦上做完了」 | W2 |
| 24 小時沒人理自動收掉 | 網頁小卡一直留著 | 沒有 | 引擎把 `ringing` 超過 24 小時的改 `expired`，再 `resolve` | W1 |
| 電腦提醒視窗（不靠網頁、不開埠） | 沒有（只有網頁小卡、瀏覽器通知） | 沒有 | 獨立的小程式＋資料夾溝通（§3.4） | W2 |
| SYNOX 沒開也會響 | 沒有（鬧鐘頁會建議設開機自動啟動整個 SYNOX） | 沒有 | 提醒哨兵（§3.5） | W2 |
| 安靜時段不擋提醒 | 沒有安靜時段；每類送到哪裡由使用者設 | 已有 | 沿用 | — |
| 設好時說何時何處會響 | `ring_line`：何時、在哪裡、「只有 SYNOX 開著才會響」 | 部分 | 改成排程回執（§3.2），字由程式產生 | W1 |
| 自我檢查 | 網頁「試響一下」 | 部分 | 加 `/remind_test`（一分鐘後響、每個管道都要有紀錄）；健康檢查一行「提醒引擎上次檢查是幾秒前、誰在跑、有沒有卡住的」 | W1（指令）、W2（健康檢查的送達部分） |
| AI 的未來承諾要有依據 | 沒有 | 沒有 | 回執交給 `CaptureApi.note_receipt`，承諾把關看這一輪有沒有回執 | W4 |

## 2. 數字怎麼取

| 數字 | 現況 | 設計初稿 | 定案 | 理由 |
|---|---|---|---|---|
| 晚多久照常響（帶按鈕） | 60 分鐘 | 6 小時 | **60 分鐘** | 現有測試與文件都是 60；晚好幾個小時才跳出「該吃藥了」反而誤導 |
| 晚多久一則一則說錯過 | 無上限 | — | **6 小時** | 6 小時內的錯過值得個別講；更早的併成一則，不轟炸 |
| 送失敗重試多久 | 不重試 | 6 小時 | **6 小時** | 跟補送界線一致 |
| 響了沒人理多久收掉 | 永遠留著 | 24 小時 | **24 小時** | 照初稿 |
| 一次性提醒處理完 | 刪掉 | — | **處理完（完成／錯過／沒人回／取消）且沒有管道還在重試才從清單拿掉** | `/remind_list` 看到的跟現在一樣；但「還沒送到」的不會再被刪 |
| 電腦視窗的延後按鈕 | — | 10 分、1 小時、自己打 | **同初稿**；聊天的按鈕維持「5 分鐘後再提醒」 | 不改現有按鈕的字與測試 |

## 3. 契約

### 3.1 一筆提醒／待辦（`schedule/reminder.py`）

存在原本的 `data/schedule.json(.enc)`（伺服器版每人一份），`kind` 仍是 `remind`；`/schedule_*` 的 `kind="command"` 不在這份契約內。

```json
{"v": 2, "id": 3, "kind": "remind", "owner": 1001, "text": "倒垃圾", "created": 1763225400,
 "repeat": "once", "due": "2026-11-16T00:51:00+08:00", "status": "ringing",
 "occurrence": "2026-11-16T00:51:00+08:00", "snooze_until": null, "snooze_count": 0,
 "deliveries": {"telegram": {"channel": "telegram", "state": "sent", "tries": 1, "first_try": 1763225460.0,
                             "last_try": 1763225460.0, "next_try": null, "ok_at": 1763225460.0, "error": "",
                             "ref": {"chat_id": 1001, "message_id": 77}}},
 "history": [], "source": "ai", "done_at": null, "done_via": "",
 "time": "00:51", "date": "2026-11-16", "last_run": "", "command": ""}
```

| 欄位 | 型別 | 意思 |
|---|---|---|
| `v` | int | 固定 2；沒有 `v` 的是舊格式 |
| `id`、`owner`、`text`、`created` | int、int、str、int | 跟以前一樣 |
| `repeat` | `once`／`daily`／`none` | `none`＝待辦 |
| `due` | ISO 字串或 null | **絕對的**下一次到點時間；null＝待辦 |
| `status` | 七種 | `pending` 排著、`ringing` 響著（送出或重試中，等人按）、`snoozed` 延後中、`done`、`missed`、`cancelled`、`expired`（24 小時沒人回） |
| `occurrence` | ISO 或 null | 正在響的那一次原本的到點時間；按鈕、送達紀錄、視窗都用 (`id`, `occurrence`) 認這一次 |
| `snooze_until`、`snooze_count` | ISO 或 null、int | 延後到何時、第幾次延後 |
| `deliveries` | 管道 → DeliveryRecord | 這一次每個管道的送達紀錄（§3.3） |
| `history` | list | 每天型最近 10 次的結果 `{"occurrence", "status", "via"}` |
| `source` | str | `command`／`ai`／`web`／`snooze`／`legacy`／`test` |
| `done_at`、`done_via` | ISO、str | 誰在哪裡按掉的（`telegram`、`desktop`、`auto`…） |
| `time`、`date`、`last_run`、`command` | str | **舊欄位照寫**（由 `due` 推），舊的讀法不用一起改；兩者不一致以 `due` 為準 |

**舊資料轉換**（`upgrade_item`，讀到就轉、可以重複呼叫）：

| 舊的 | 新的 |
|---|---|
| 有 `date` | `repeat=once`，`due`＝那一天那一刻（本機時區） |
| 沒有 `date` | `repeat=daily`，`due`＝`created` 之後、`last_run` 那天之後的第一個那一刻（不看現在幾點） |
| `time` 讀不懂 | 回 None：引擎記 log、**原樣留著、不刪**、不響 |
| `kind=command` | 不動 |
| 全部 | `status=pending`、`source=legacy`、其他欄位用預設 |

舊的每天型轉出來的 `due` 可能是很久以前：引擎的補送規則「每天型只看今天那一次、更早的不補」會把它推到今天或明天，不會一次補一堆。

**到點與補送（W1 照這個做）**：

1. `due ≤ 現在`、而且這一次（`occurrence`）還沒處理 → 處理；多叫幾次結果一樣。
2. 晚 ≤ 60 分鐘：照常響（帶按鈕），寫「晚了 N 分鐘」；60 分鐘～6 小時：送「你錯過了」（一則一則）；超過 6 小時：本輪所有這種的併成一則。
3. 送出用 `delivery.deliver`，`status=ringing`；**任何管道都還沒成功之前不算處理完、不刪**。
4. 使用者按了（任何管道）→ `ReminderActions.act` → 改狀態、`delivery.resolve` 讓其他管道收掉。
5. 每天型處理完：結果記進 `history`，`due` 推到下一天、回 `pending`。一次性的處理完、沒有管道還在重試，就從清單拿掉。

### 3.2 排程回執（`schedule/receipt.py`）

只有**真的排上了**才產生；擋下來、要問的，不給回執。

| 欄位 | 型別 | 例 |
|---|---|---|
| `kind` | `remind`／`todo`／`command` | `remind` |
| `id` | int | 3 |
| `text` | str | 倒垃圾 |
| `repeat` | `once`／`daily`／`none` | `once` |
| `due` | ISO 或 null（待辦） | `2026-11-16T00:51:00+08:00` |
| `when` | 白話時間（`notify.alarms.friendly`） | 今天 00:51 |
| `channels`、`channel_labels` | 管道 id、白話 | `["telegram","desktop"]`、`["Telegram","這台電腦的視窗"]` |
| `not_when` | 代號 | `off`（關機）、`asleep`（睡著）、`app_closed`（SYNOX 沒開；有哨兵就不會出現）、`web_only`（只有網頁、網頁沒開） |
| `catch_up` | `boot`／`next_start` | `boot`＝開機後補送（有哨兵）；`next_start`＝下次打開 SYNOX 時補送 |
| `ring_late_max_min`、`missed_notice_max_h` | int | 60、6 |
| `warnings` | `notify.alarms.warnings` 的 id | `["sleep"]` |
| `ok`、`v` | bool、int | true、1 |

回給使用者的字由 `reply_text()` 產生：

```
⏰ 排好了：今天 00:51 提醒你「倒垃圾」（只一次）。
會送到：Telegram、這台電腦的視窗。
不會響的情況：電腦關機時、電腦睡著時（開機後補送）。
```

`receipt.emit(api, chat_id, receipt)`：照常 `send_message` 人看的字；`api` 有 `note_receipt` 時（W4 在 `agent/capture.py` 的
`CaptureApi` 加）把回執物件交過去。`machine_line()` 是一行 `〔排程回執〕kind=…；due=…；channels=…；not_when=…`，
W4 決定要不要放進給 AI 的工具結果；`〔排程回執〕` 只能由系統產生，AI 自己寫出來＝偽造（比照 `〔工具結果〕`）。

**W4 的承諾把關怎麼用**：這一輪的工具紀錄裡沒有回執，回覆卻說「會提醒／到時候／每天幫你」→ 退回；
有回執 → 回覆裡的時間要對得上 `when` 或 `due` 的時分，說的管道不能超出 `channel_labels`。

### 3.3 送達介面（`notify/delivery.py`）

```
W1（引擎）──deliver(Message)──▶ Outbox（W2）──send──▶ ChannelAdapter: web｜telegram｜discord｜desktop
     ▲                              │  RetryPolicy：失敗留在佇列，pump 每 15 秒重試
     └──ReminderActions.act／on_delivery◀── 按鈕、網頁、電腦視窗（W2）
```

- `Message(key, uid, text, kind, level, actions, data, ref=ReminderRef(rid, occurrence), channels, desktop)`；
  `key` 是冪等鍵（提醒用 `message_key(rid, occurrence, owner)`）。
- `ChannelAdapter.send(msg) -> DeliveryResult(channel, state, error, ref, retry_after)`：不丟例外、不 sleep；
  `state` 只會是 `sent`／`queued`（等非同步確認，例如視窗）／`failed`／`skipped`。
- `DeliveryRecord`（每管道一筆）：`state`（`queued`／`sent`／`failed`／`gave_up`／`skipped`／`retracted`）、`tries`、
  `first_try`、`last_try`、`next_try`、`ok_at`、`error`（只有種類：`network`、`rate_limited`、`blocked`、`bad_token`、
  `duplicate_text`、`no_window`、`timeout`、`unknown`）、`ref`（管道的把手，例如 Telegram 的 chat_id＋message_id）。
- `RetryPolicy`：30、60、120、300、600 秒，之後每 900 秒；第一次試之後滿 6 小時放棄（`gave_up`）；
  管道說「幾秒後再來」（429）照它的。`blocked`、`bad_token` 不重試，健康檢查說哪一條壞了。
- 佇列：`data/notifications/outbox/<id>.json(.enc)`（跟通知清單同一套加密）；runtime 任務 `system.notify.outbox` 每 15 秒 `pump`。
- `Outbox.resolve(uid, key, note, via)`：停止重試，`via` 以外的管道 `retract(note)`（拿掉按鈕、改字、關視窗）。
- `ReminderActions`（W1 實作、登記在 `app.extras["synox_reminder_actions"]`）：
  `act(uid, rid, occurrence, action, until=, typed=, via=) -> ActionOutcome(ok, reason, text, note)`；
  `on_delivery(uid, rid, occurrence, record)`。`action`：`done`、`ack`（知道了）、`snooze`。要冪等。
- `planned_channels(app, uid, kind)`：給回執的 `channels`，跟 `hub.where` 同一套判斷、多一個 `desktop`。
- **`Hub.notify` 不變**：其他種類的通知照舊一次送完、不重試；只有走 `deliver` 的才有確認與重試。
  Telegram 的字跟上一則一模一樣會被擋成重複：算 `failed(duplicate_text)`，重試時字尾加「（第 N 次）」。

### 3.4 電腦提醒視窗的檔案溝通（`notify/desk.py`）

不開任何網路埠、不靠網頁。資料夾 `data/remind/`：

| 檔 | 誰寫 | 誰刪 | 內容 |
|---|---|---|---|
| `desk/to_win/show-<token>.json` | 引擎 | 引擎（處理掉才刪） | `ShowCard`：token、uid、rid、occurrence、text、when、late_min、snooze_count、buttons |
| `desk/to_win/close-<token>.json` | 引擎 | 視窗（關完刪） | `CloseCard`：token、reason（`done_elsewhere`／`expired`／`cancelled`）、note |
| `desk/to_win/todos-<uid>.json` | 引擎（整份覆寫） | 不刪 | `TodoList`：視窗下半部的待辦（最多 20 筆） |
| `desk/from_win/shown-<token>.json` | 視窗 | 引擎（讀完刪） | `ShownAck`：卡片真的出現了＝desktop 的送達確認 |
| `desk/from_win/act-<token>-<ms>.json` | 視窗 | 引擎（讀完刪） | `DeskAction`：action（`done`／`snooze`）、until（視窗解析得出就填）、typed（使用者打的原字） |

- `token`＝`<uid>-<rid>-<到點的 YYYYMMDDHHMM>`（只有英數、`-`、`_`；檔名不含使用者的字）。
- 寫檔先寫同資料夾 `.<名字>.tmp` 再 `os.replace`；讀的人略過 `.` 開頭與 `.tmp` 結尾；壞掉的 JSON 記 log（不記內容）後刪掉。
- 視窗每 1 秒看 `to_win`；引擎每 5 秒內看 `from_win`。視窗開起來時把現有的 `show-*` 全部顯示（當機重開不漏）。
- 寫了 `show` 60 秒沒有 `shown`：desktop 這次算 `failed(no_window)`，照重試規則重開視窗程式。
- 視窗：右下角、永遠在最上層、多張往上疊、響一聲；**不處理不會自己關**；按鈕：完成、延後 10 分鐘、延後 1 小時、自己打時間。
  畫面與邏輯分開，邏輯不開視窗就能測。
- **隱私**：卡片上的提醒文字以明文放在本機 `data/` 底下，處理掉就刪；視窗程式不碰保管箱金鑰。
  要更嚴（加密 spool）是之後的事，需要視窗也能開保管箱。

### 3.5 提醒哨兵與讓位

| 檔 | 意思 |
|---|---|
| `data/remind/engine.lock` | 拿到 OS 獨占鎖（Windows `msvcrt.locking`；其他 `fcntl.flock`）＝我是提醒引擎；內容 `EngineStamp`（who、pid、since、beat）給健康檢查看。程序死掉鎖自動放掉 |
| `data/remind/yield.request` | 主程式要哨兵讓位（`YieldRequest`：pid、at） |
| `data/remind/sentinel.lock`、`popup.lock` | 哨兵、視窗程式各只能有一個 |

- **主程式啟動**：試拿 `engine.lock`；拿不到（哨兵在跑）→ 寫 `yield.request`，最多等 15 秒；還是拿不到就**先不跑引擎**
  （哨兵照樣在送，不會重複），下一輪再試，健康檢查寫「提醒引擎由哨兵在跑」。
- **哨兵**：每 30 秒試拿 `engine.lock`；拿到就用 `reminder.headless_engine(...)` 跑一輪＋處理視窗的回覆；
  看到 `yield.request` → 做完這一輪 → 放鎖 → 刪掉 request → 回到只等的狀態。
- **主程式關掉**：放鎖；哨兵 30 秒內接手。
- 哨兵只在 Windows 個人版；登記在使用者的「啟動」資料夾（跟精靈的「開機自動啟動」同一個地方，不用管理員、不動系統排程）。
  登記的函式收資料夾參數，測試一律傳假的資料夾。
- 哨兵送 Telegram 需要讀設定與保管箱金鑰（跟主程式同一個使用者帳號、同一份 `data/`）。
- 就算兩邊同時送了，同一次提醒的 key 一樣，佇列與通知清單的去重會擋下第二次。

## 4. W1 與 W2 的界線

- **W1（提醒引擎，`src/synox/schedule/`）只呼叫** `delivery.deliver`／`resolve`／`status`／`planned_channels`，
  實作 `ReminderActions` 與 `reminder.headless_engine`。**不寫任何送出的程式**（不碰 Telegram、Discord、視窗、spool 檔）。
- **W2（送達層＋視窗＋哨兵，`src/synox/notify/`、新 `src/synox/remindwin/`）只實作** `delivery.py`、`desk.py` 的本體、
  視窗程式、哨兵，並把 `hub.snooze`／按鈕改成回頭叫 `ReminderActions`。**不碰 `src/synox/schedule/`**；
  哨兵裡的引擎用 `reminder.headless_engine`。
- 契約檔（本 ADR 列的四個）只能加選填欄位；要改既有欄位或代號，先改這份 ADR、兩邊都知道。
- 合併順序：W2 的介面可以先合（`ReminderActions` 沒登記時，按鈕照舊走 `hub.snooze` 的舊路）；兩包都合併後，整合時再拿掉舊路。

## 已知代價與不做

- 電腦關機或睡著時誰都叫不了，只能開機後補送（用系統排程把電腦叫醒是之後的事）。
- spool 的提醒文字是明文（§3.4）。
- 伺服器版不跑哨兵、不跳電腦視窗（只有聊天與網頁）。
- `/schedule_*`（排程指令）這一輪不換資料格式，只受惠於引擎的到點判斷。
