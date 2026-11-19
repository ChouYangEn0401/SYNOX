# 通知與鬧鐘（synox/notify）

SYNOX 要「告訴你一件事」的時候（鬧鐘到了、工具的完整畫面太久沒人用、有新版、常駐助理的消息、工具裝好了、安全警告），
同一則會送到你用的**每一個地方**：

| 地方 | 什麼時候會送 | 長什麼樣子 |
|---|---|---|
| 網頁 | 網頁介面有開（`web.enabled`） | 左上角 🔔 的數字＋跳出來的小卡；清單留最近 100 則 |
| Telegram | 有 Telegram bot，而且你接得到：你本來就是用 Telegram 編號，或在網頁「設定 → 聊天通道」配對過 | 一則訊息，鬧鐘帶「知道了」「完成」「5 分鐘後再提醒」按鈕 |
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
4. **時間到**：每個接上的地方都送「⏰ 提醒：吃藥」＋「知道了」「完成」「5 分鐘後再提醒」。網頁的小卡**一直留著**直到你按；
   「5 分鐘後再提醒」交給提醒引擎把**同一個提醒**延後（`/remind_list` 寫「（延後到 08:05）」），不另加一筆；
   同一則按第二次會說「已經處理過了」。
5. **網頁沒開**：通知留在清單裡，下次打開時還沒看的鬧鐘會跳出來，🔔 有數字。
6. **晚了**（電腦剛醒、SYNOX 剛開、剛好沒檢查到那一分鐘）：到點判斷是「到點時間 ≤ 現在、這一次還沒處理」，
   所以下一次檢查一定會處理。60 分鐘內照樣叫，並說晚了幾分鐘；60 分鐘～6 小時一則一則送「你錯過了 1 個鬧鐘：今天 06:00 運動」；
   超過 6 小時的這一輪併成一則「有 N 個提醒在 SYNOX 沒開的時候過了」。只算「設好之後才到的那一次」；每天的只看最近那一次
   （更早的不補）。
7. **沒送到不刪**：響了的提醒先留在清單檔裡（`/remind_list` 不列，看起來跟以前「響過就刪」一樣），直到有人按、或 24 小時沒人理
   自動收掉；一次性的處理完、而且沒有管道還在重試，才真的拿掉。送出一律經過送達層（`notify/delivery.py`）。
8. **待辦與試響**：`/remind_todo 繳電話費` 記一個沒有時間的待辦（不會響，`/remind_list` 下半部列出，`/remind_done <n>` 做完）；
   待辦一有變動（新增、做完、刪掉）就整份交給電腦提醒視窗的下半部，在視窗上按 ✓ 也會從清單拿掉。
   `/remind_test` 一分鐘後響一次，看每個地方有沒有收到。刪掉一個正在響的提醒，各處的按鈕跟視窗那張也一起收掉。
9. **引擎自己壞了**：提醒與排程這個背景任務失敗後最多 1 分鐘就重試（不像其他任務會拉長到 30 分鐘）；連續 3 次讀不到清單，
   直接通知「⚠️ 提醒引擎停了」，恢復時再說一聲。舊的 `data/schedule.json(.enc)` 讀到時自動轉成新格式，讀不懂的那一筆原樣留著。

選配（只記在這個瀏覽器，都要自己按才打開，不會自己跳出瀏覽器的詢問）：「開啟提示音」（分頁開著時嗶兩聲）、
「開啟桌面通知」（瀏覽器的通知）。

**老實說**：鬧鐘只有在 SYNOX 開著的時候才會響——電腦要開著、沒有睡著。Windows 上可以打開「保持清醒」
（`runtime/keepawake.py`，docs/adr/0006）讓電腦不要自己睡著，但闔上筆電、按睡眠、沒電、Windows Update 重開機都擋不住。
電腦關著或睡著時到的鬧鐘，醒來後 60 分鐘內會補叫，更晚的只會告訴你錯過了。

## 契約：提醒必達（ADR 0029）

「送出去有沒有成功」「SYNOX 沒開也會響」「電腦上的提醒視窗」「待辦」「排程回執」都**疊在通知中心上**，`Hub.notify` 的用法不變。完整欄位、例子與差距表在 [adr/0029](adr/0029-reminder-delivery-on-notify-hub.md)；
四份契約程式（只有型別與簽名，測試 `tests/test_remind_contract.py`）：

| 檔 | 定什麼 |
|---|---|
| `schedule/reminder.py` | 一筆提醒／待辦：絕對到點時間 `due`、`repeat`（once／daily／none＝待辦）、`status`（八種：知道了＝dismissed、完成＝done 分開記）、延後、每個管道的送達紀錄；舊資料怎麼轉（`upgrade_item`，舊欄位 `time`／`date` 照寫） |
| `schedule/receipt.py` | 排程回執：排上了才有；何時（`when`、`due`）、從哪些管道送、什麼情況不會送；回覆的字由程式產生 |
| `notify/delivery.py` | 送達介面：`deliver(Message)`、管道回報 `DeliveryResult`、`RetryPolicy`（30 秒起、最多 6 小時）、佇列、`resolve`（一處按了其他處收掉）、`ReminderActions`（按鈕回頭叫提醒引擎） |
| `notify/desk.py` | 電腦提醒視窗與提醒哨兵：`data/remind/` 的檔名、欄位、誰寫誰刪；`engine.lock` 與讓位 |

數字：晚 60 分鐘內照常響（不變）；60 分鐘～6 小時一則一則說錯過；超過 6 小時併成一則；送失敗重試到 6 小時；響了 24 小時沒人按自動收掉。

### 送達確認與重試（`notify/outbox.py`、`notify/channels.py`、`notify/deskapp.py`）

提醒到點時，提醒引擎呼叫 `delivery.deliver(app, Message)`（不是 `hub.notify`）。`Hub.notify` 的用法與行為不變，
其他種類的通知照舊一次送完、不重試。

- **管道回報成功才算送到**：網頁（通知清單存好了）、Telegram／Discord（回 `ok`）、電腦視窗（視窗回「卡片出現了」）。
  任一條成功＝「有通知到」，其他條繼續試。
- **失敗就留在佇列重試**：30 秒、1 分、2 分、5 分、10 分，之後每 15 分；第一次試之後滿 6 小時放棄。
  Telegram 說「太快了，N 秒後再來」就照它的；**對方封鎖了 bot、token 壞了不重試**（之後健康檢查會說哪一條壞了）；
  Telegram 把一模一樣的字當重複擋掉時，重試的字尾加「（第 N 次）」。
- **佇列存檔**：`data/notifications/outbox/<id>.json`，保管箱開著時是 `.json.enc`（跟通知清單同一把金鑰）；
  SYNOX 重開照樣重試。runtime 任務「📮 通知重送」（`system.notify.outbox`）每 15 秒看一次。
- **同一則不重送**：同一個提醒的同一次（`delivery.message_key`）只會進佇列一次；通知中心 12 小時的去重也認得這個 key。
- **按鈕的意思（每個地方都一樣）**：「知道了」＝這一次不響了，記成 dismissed（不算做完）；「完成」＝記成 done；
  「延後」＝同一次晚一點再響（卡片寫「延後第 N 次」）；「改到別天」（電腦視窗，只有一次性的提醒有）＝整個提醒改時間，
  到時候當新的一次響。每天的提醒改到下一次之後會被拒絕（下一次本來就會響），下一次之前＝延後這一次。
- **一處按了、其他處收掉**：在 Telegram、Discord、網頁或電腦視窗按「完成／知道了／延後／改到別天」→ 交給提醒引擎
  （`app.extras["synox_reminder_actions"]` 的 `act`）→ 其他地方的按鈕拿掉、訊息改成「✅ 在…做完了」、電腦視窗那張關掉。
  舊的「5 分鐘後再提醒＝另加一筆只響一次的提醒」已經拿掉：沒有提醒引擎時按了只收掉按鈕。
  「你錯過了」那一則按「知道了」也會讓其他地方收掉（電腦視窗上那張寫「（錯過了）…」，只有「我知道了」一顆鍵）。
- **誰在跑提醒引擎**：主程式每一輪到點檢查前先看 `delivery.is_engine(app)`；提醒哨兵還拿著 `engine.lock`（還沒讓位）時，
  主程式這一輪不檢查（哨兵在送，不會重複），`/schedule_*` 的指令照跑（哨兵不跑指令）。
- **健康檢查**（`python -m synox doctor`）多一行「提醒引擎」：上一次檢查是幾秒前、是主程式還是提醒哨兵檢查的
  （`data/remind/engine.json`，沒有個人資料）、現在誰拿著 `engine.lock`、送達佇列裡幾件還沒送到、最近失敗的是哪條管道（只有種類）。

### 電腦提醒視窗與提醒哨兵（`synox/remindwin/`）

Windows 個人版**預設開**。提醒時間到，這台電腦右下角跳出一張提醒卡：

- 永遠在最上層、好幾張會往上疊、跳出來時響一聲；**不按不會自己關**；不會搶走你正在打字的視窗的焦點
  （點一下卡片之後可以用 Tab／Enter／空白鍵操作）。
- 外觀跟著網頁主控面板（設定 → 外觀）：外觀包的顏色、淺色／深色／跟著系統（Windows 的應用程式模式）；
  主程式把顏色寫在 `data/remind/desk/style.json`（只有顏色、字型名、圓角）。
- 版面：「⏰ 提醒」、大字的提醒內容、下面一行時間；晚了／延後第幾次用小標籤。
- 按鈕：**我知道了**、**我完成了**；稍後再叫我：5 分鐘、15 分鐘、1 小時、自選（打幾分鐘，或「15:30」「+2h」「明天 9 點」）；
  安排到別天（只有一次性的提醒）：明天同一時間、挑日期時間（明天起 7 天＋幾點）。
- 卡片下半部列沒有時間的待辦，每筆一個 ✓。
- 視窗跟 SYNOX 之間只有 `data/remind/desk/` 裡的小檔案（不開任何網路埠、不靠網頁；網頁關著也能用）。
  SYNOX 每 5 秒內讀到你按了什麼。卡片上的提醒文字以明文放在這個資料夾，處理掉就刪。
- 寫了卡片 60 秒都沒跳出來（視窗程式沒開成）＝這一次算沒送到，照上面的重試再開一次。

**提醒哨兵**：登入 Windows 時自動啟動的小程式（`python -m synox sentinel`，用 pythonw 跑、沒有黑色視窗；
只登記在你這個帳號的「啟動」資料夾，檔名 `SYNOX-remind-sentinel.cmd`，不用管理員、不動系統排程）。
SYNOX 沒開的時候，它照同一份提醒資料到點就跳視窗、送 Telegram；SYNOX 一開，它把提醒交回來（`data/remind/engine.lock`
決定現在誰在跑，同一時間只有一個）。電腦關機或睡著時誰都叫不了，開機後補送。

**怎麼關**：

| 要關的 | 怎麼做 |
|---|---|
| 電腦提醒視窗 | 設定 → 💻 電腦與備份 →「🔔 通知要送到哪裡」下面的「🖥️ 電腦提醒視窗」取消第一格；或在 `config.json` 加 `"notify": {"desktop": false}`（一律關，設定頁就改不回來） |
| 提醒哨兵（登入時啟動） | 同一塊取消「登入 Windows 時啟動提醒哨兵」再按「存起來」（馬上把啟動檔拿掉；已經在跑的哨兵下次登入就不會再開）；或直接刪掉「啟動」資料夾裡的 `SYNOX-remind-sentinel.cmd` |

設定存在 `data/remind/settings.json`。伺服器版、不是 Windows 的電腦沒有電腦視窗、也不跑哨兵（只有聊天與網頁）。
試看看視窗長什麼樣子：`python -m synox remind-window --demo`（放一張試跳的卡，不碰 SYNOX 的資料）。

## 網頁 API（`synox/notify/web_api.py`）

| 方法與路徑 | 做什麼 |
|---|---|
| `GET /api/notifications?since=<rev>` | rev 之後變了的通知、沒讀幾則、下一個鬧鐘（每 10 秒；分頁在背景 30 秒） |
| `POST /api/notifications/read` `{"id"}` | 知道了（沒給 id＝全部已讀） |
| `POST /api/notifications/<id>/snooze` | 5 分鐘後再提醒（同一個提醒延後；已經處理過回 404） |
| `POST /api/notifications/<id>/done` | 完成（交給提醒引擎；沒有引擎＝知道了） |
| `GET/POST /api/notifications/prefs` | 哪一類送到哪裡（Windows 個人版的擁有者多一塊 `desk`：電腦視窗、哨兵） |
| `POST /api/notifications/desk` `{"window", "sentinel"}` | 電腦提醒視窗開／關、登入時啟動提醒哨兵（擁有者、Windows 個人版） |
| `GET /api/alarms` | 接下來的鬧鐘、會在哪裡響、可能漏掉的原因 |
| `POST /api/alarms/<id>/delete`、`POST /api/alarms/test` | 刪掉、試響一下 |

工具完整畫面的「現在關掉」「再給我 30 分鐘」直接用 `/api/apps/<名>/stop`、`/keep`（擁有者、手機驗證規則照舊）。

## 用字

一般人聽得懂的話：不說服務、網址、埠、閒置。例如「記帳的完整畫面 30 分鐘沒人用了。要關掉嗎？不理我的話，再 90 分鐘我會自己關。」

測試：`tests/test_notify.py`（假的 Telegram／Discord，不連網）、`tests/test_notify_outbox.py`（佇列、重試、按鈕回頭叫提醒引擎）、
`tests/test_remindwin_spool.py`（視窗的檔案往返、鎖、哨兵、啟動檔；不開視窗、不碰真的啟動資料夾）。畫面：`static/notify.js`、`static/notify.css`（顏色只用 token）。
