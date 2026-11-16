# 通知與鬧鐘（synox/notify）

SYNOX 要「告訴你一件事」的時候（鬧鐘到了、工具的完整畫面太久沒人用、有新版、常駐助理的消息、工具裝好了、安全警告），
同一則會送到你用的**每一個地方**：

| 地方 | 什麼時候會送 | 長什麼樣子 |
|---|---|---|
| 網頁 | 網頁介面有開（`web.enabled`） | 左上角 🔔 的數字＋跳出來的小卡；清單留最近 100 則 |
| Telegram | 有 Telegram bot，而且你接得到：你本來就是用 Telegram 編號，或在網頁「設定 → 聊天通道」配對過 | 一則訊息，鬧鐘帶「知道了」「5 分鐘後再提醒」按鈕 |
| Discord | 有私訊型 Discord bot，而且你配對過 | 同上（按鈕一樣） |

一條送不出去（網路斷了、token 壞了），其他條照送；log 只記「哪一條、哪一種錯」，不記通知的內容。

## 以前（這個功能之前）實際送到哪裡

`App.notify_owner` → `App.notify` → `app.home.send_message(owner_id, text)`，`app.home` 只有一個：

- 只有 Telegram：送 Telegram。**網頁什麼都沒有**（不會出現在任何對話，也沒有小卡）。
- 有 Telegram 也有 Discord（`MultiHome`）：擁有者是一般 Telegram 編號 → **只送 Telegram，Discord 收不到**；
  擁有者是保留號段（只用網頁／Discord 安裝的）→ **只送 Discord，就算配對了 Telegram 也收不到**。
- 只有 Discord：送 Discord。
- 都沒有（只用網頁）：`LogOnlyChannel`，**只寫進 log，沒有人看得到**。

用到它的地方：鬧鐘（`schedule/runner.py` 的 `app.notify(owner, "⏰ 提醒：…")`，伺服器版是建立的那個人）、
工具完整畫面的閒置提醒與自動關閉（`web/apps/manager.py`）、每週新版檢查（`update/`）、常駐助理的心跳與
「soul 有事等你確認」（`runtime/heartbeat.py`、`runtime/ledger.py`）、背景任務一直失敗（`runtime/loop.py`）、
pack 檔案被改過（`packs/loader.py`）、工具環境建好了／沒建好（`web/server.py`）、開機的「👋 我在了」。

## 現在

`notify.install(app, …)` 在 `app.build` 一開始裝，把 `app.notify_owner` 換成 `Hub.notify_owner`（vendor 不改）。
舊的 `app.notify_owner(text)` 照樣能用；SYNOX 自己的呼叫都改成 `notify.owner(app, text, kind=…)`。
`app.notify(chat_id, …)`（送給特定一個人，例如手機驗證碼、/remind 以外的系統訊息）**不經過**通知中心。

```python
from synox import notify
notify.owner(app, "🆕 SYNOX 有新版：0.9.0 → 0.9.1", kind="update")
notify.of(app).notify(uid, "⏰ 提醒：吃藥", kind="alarm", key="alarm:3:2026-11-14:08:00")
```

- `kind`：分類（設定頁可以分類關掉）：`alarm`、`tool_idle`、`update`、`assistant`、`tools`、`safety`、`greeting`、`general`。
- `key`：同一件事不重送（12 小時內同一個 key 只送一次）。
- `actions`：網頁小卡上的按鈕；`ok`、`snooze`、`app_stop`、`app_keep` 也會變成 Telegram／Discord 的按鈕
  （`ntf:` 綁在 `remind.add`、`ntfa:` 綁在 `apps.app_close`，按的人一樣先過 authorize）。
- 兩個聊天通道都沒有時（終端機、測試的假管子），照舊交給 `app.home`。

### 資料

`data/notifications/<id>.json`；保管箱開著時是 `.json.enc`，用那個人自己的金鑰（跟網頁對話紀錄同一套）。
每人最多 100 則，有「沒讀／讀過」，還有「哪一類不送到哪裡」的設定。伺服器版每個人只看得到自己的。

### 設定

設定 → 💻 電腦與備份 →「🔔 通知要送到哪裡」：每一類 × 網頁／Telegram／Discord。沒接上的地方不能勾。
預設全部都送，只有「👋 SYNOX 開起來了」不放進網頁（網頁開著就知道它開著）。安全警告一定會出現在網頁上。

## 鬧鐘

「明天早上 8 點提醒我吃藥」（AI 會用 `remind__add`）或 `/remind_add 08:00 吃藥 date=…`：

1. **設好的時候**回一張固定的**排程回執**（程式產生，不交給 AI 自由發揮，`schedule/receipt.py`）：
   「⏰ 排好了：明天 08:00 提醒你「吃藥」（每天）。會送到：網頁、Telegram。不會響的情況：…」。只列真的接上的；
   一個地方都沒有就**不排**、直說要去哪裡打開。
   時間可以寫 `HH:MM`（沒給日期＝每天，跟以前一樣），也可以照人說的話寫：「半小時後」「明天 9 點」「明早」「+2h」「12.51」
   （`schedule/timeparse.py`）。兩種讀法差很多時**反問**（13:00 說「12.51」→ 問明天 00:51 還是 12:51；「等等」→ 問多久之後）；
   已經過了的時間擋下來，問「00:51 已經過了，是要明天 00:51 嗎？」。`repeat=daily|once` 可以指定每天或只一次。
2. **網頁一直看得到**：🔔 旁邊「⏰ 下一個：明天 08:00 吃藥」；🔔 →「鬧鐘」分頁列出全部（刪除、試響一下）。
3. **可能漏掉時先說**（鬧鐘分頁的黃色框）：只有網頁（網頁沒開就看不到，建議接 Telegram／Discord）、
   沒有任何地方會叫你、Windows 上「保持清醒」沒開（一鍵打開：`POST /api/runtime/keep-awake`）、
   沒設開機自動啟動（說怎麼設，不替你改）。
4. **時間到**：每個接上的地方都送「⏰ 提醒：吃藥」＋「知道了」「5 分鐘後再提醒」。網頁的小卡**一直留著**直到你按；
   「5 分鐘後再提醒」在原本的提醒清單加一個只響一次的（date＝那一天）。
5. **網頁沒開**：通知留在清單裡，下次打開時還沒看的鬧鐘會跳出來，🔔 有數字。
6. **晚了**（電腦剛醒、SYNOX 剛開、剛好沒檢查到那一分鐘）：到點判斷是「到點時間 ≤ 現在、這一次還沒處理」，
   所以下一次檢查一定會處理。60 分鐘內照樣叫，並說晚了幾分鐘；60 分鐘～6 小時一則一則送「你錯過了 1 個鬧鐘：今天 06:00 運動」；
   超過 6 小時的這一輪併成一則「有 N 個提醒在 SYNOX 沒開的時候過了」。只算「設好之後才到的那一次」；每天的只看最近那一次
   （更早的不補）。
7. **沒送到不刪**：響了的提醒先留在清單檔裡（`/remind_list` 不列，看起來跟以前「響過就刪」一樣），直到有人按、或 24 小時沒人理
   自動收掉；一次性的處理完、而且沒有管道還在重試，才真的拿掉。送出一律經過送達層（`notify/delivery.py`）。
8. **待辦與試響**：`/remind_todo 繳電話費` 記一個沒有時間的待辦（不會響，`/remind_list` 下半部列出，`/remind_done <n>` 做完）；
   `/remind_test` 一分鐘後響一次，看每個地方有沒有收到。
9. **引擎自己壞了**：提醒與排程這個背景任務失敗後最多 1 分鐘就重試（不像其他任務會拉長到 30 分鐘）；連續 3 次讀不到清單，
   直接通知「⚠️ 提醒引擎停了」，恢復時再說一聲。舊的 `data/schedule.json(.enc)` 讀到時自動轉成新格式，讀不懂的那一筆原樣留著。

選配（只記在這個瀏覽器，都要自己按才打開，不會自己跳出瀏覽器的詢問）：「開啟提示音」（分頁開著時嗶兩聲）、
「開啟桌面通知」（瀏覽器的通知）。

**老實說**：鬧鐘只有在 SYNOX 開著的時候才會響——電腦要開著、沒有睡著。Windows 上可以打開「保持清醒」
（`runtime/keepawake.py`，docs/adr/0006）讓電腦不要自己睡著，但闔上筆電、按睡眠、沒電、Windows Update 重開機都擋不住。
電腦關著或睡著時到的鬧鐘，醒來後 60 分鐘內會補叫，更晚的只會告訴你錯過了。

## 契約：提醒必達（ADR 0028，實作中）

上面是現在的行為。接下來要補「送出去有沒有成功」「SYNOX 沒開也會響」「電腦上的提醒視窗」「待辦」「排程回執」，
**疊在通知中心上**，`Hub.notify` 的用法不變。完整欄位、例子與差距表在 [adr/0028](adr/0028-reminder-delivery-on-notify-hub.md)；
四份契約程式（只有型別與簽名，測試 `tests/test_remind_contract.py`）：

| 檔 | 定什麼 |
|---|---|
| `schedule/reminder.py` | 一筆提醒／待辦：絕對到點時間 `due`、`repeat`（once／daily／none＝待辦）、`status`（七種）、延後、每個管道的送達紀錄；舊資料怎麼轉（`upgrade_item`，舊欄位 `time`／`date` 照寫） |
| `schedule/receipt.py` | 排程回執：排上了才有；何時（`when`、`due`）、從哪些管道送、什麼情況不會送；回覆的字由程式產生 |
| `notify/delivery.py` | 送達介面：`deliver(Message)`、管道回報 `DeliveryResult`、`RetryPolicy`（30 秒起、最多 6 小時）、佇列、`resolve`（一處按了其他處收掉）、`ReminderActions`（按鈕回頭叫提醒引擎） |
| `notify/desk.py` | 電腦提醒視窗與提醒哨兵：`data/remind/` 的檔名、欄位、誰寫誰刪；`engine.lock` 與讓位 |

數字：晚 60 分鐘內照常響（不變）；60 分鐘～6 小時一則一則說錯過；超過 6 小時併成一則；送失敗重試到 6 小時；響了 24 小時沒人按自動收掉。

## 網頁 API（`synox/notify/web_api.py`）

| 方法與路徑 | 做什麼 |
|---|---|
| `GET /api/notifications?since=<rev>` | rev 之後變了的通知、沒讀幾則、下一個鬧鐘（每 10 秒；分頁在背景 30 秒） |
| `POST /api/notifications/read` `{"id"}` | 知道了（沒給 id＝全部已讀） |
| `POST /api/notifications/<id>/snooze` | 5 分鐘後再提醒 |
| `GET/POST /api/notifications/prefs` | 哪一類送到哪裡 |
| `GET /api/alarms` | 接下來的鬧鐘、會在哪裡響、可能漏掉的原因 |
| `POST /api/alarms/<id>/delete`、`POST /api/alarms/test` | 刪掉、試響一下 |

工具完整畫面的「現在關掉」「再給我 30 分鐘」直接用 `/api/apps/<名>/stop`、`/keep`（擁有者、手機驗證規則照舊）。

## 用字

一般人聽得懂的話：不說服務、網址、埠、閒置。例如「記帳的完整畫面 30 分鐘沒人用了。要關掉嗎？不理我的話，再 90 分鐘我會自己關。」

測試：`tests/test_notify.py`（假的 Telegram／Discord，不連網）。畫面：`static/notify.js`、`static/notify.css`（顏色只用 token）。
