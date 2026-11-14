# ISDTeleKitSDK：把 ClawBot 11-11 的「收訊不互等、429 等一下重送」搬進 SDK

- 狀態：**待處理**（由擁有者轉交給 ISDTeleKitSDK repo 的 session；SYNOX 的 `vendor/` 不改，修好後重新 vendor）
- 寫的時間：2026-11-12
- 對象：ISDTeleKitSDK `isdtelekit/telegram/poller.py`、`isdtelekit/telegram/bot_api.py`

## 擁有者原話

「目前 synox 最後一次更新完以後，telegram bot 有大更新……我感覺這邊的核心也會需要更新一下。」

（ClawBot 那邊的原話，工作單 agent-busy-blocking：「你AI對話是AI對話，你的指令是指令為什麼會卡住？」）

## 問題一句話

SYNOX 用的 SDK 0.2.1（`vendor/VERSION`：commit c884443）收訊是一則做完才收下一則、Telegram 回 429 就整則丟掉；
ClawBot 11-11 在自己的 Telegram 通道修掉了這兩件（commit 9ab81de），SDK 和 SYNOX 都還沒有。

## 脈絡

- **收訊**：SDK `Poller.poll_once` 對每個 update 同步呼叫 `entry.dispatch`。SYNOX 的 AI 一輪與 cli pack 指令已經丟到 `app.tasks`，
  不會卡收訊；但 **python pack 的指令在收訊執行緒上直接跑**——內建 connector 的 Todoist、Notion、Google 日曆、Apple 提醒事項都是同步 HTTP（逾時 15～20 秒），
  它在等網路時，同一台 bot 所有人的打字和按鈕都排在後面（按鈕超過約 15 秒 Telegram 就不認了）。
- **429**：SDK `BotAPI._parse` 把 `retry_after` 放進回傳值，但沒有人看，訊息就沒送出去。SYNOX 的 Discord 通道（`src/synox/discord/rest.py`）
  已經是「等 retry_after（最多 5 秒）再送一次」，Telegram 這邊不一致。
- ClawBot 的做法（`MyFirstTelegramClawBot` 9ab81de，`src/clawbot/channels/telegram/poller.py`、`bot_api.py`、`tests/test_agent_busy.py`）：
  - 收訊執行緒不等任何一則：打字「一個聊天一條線」照順序、按鈕「一則訊息一條線」（同一張卡連按照順序），不同線互不等；多記 `[WAIT]` 一行。
  - `post` 撞到 429 且 `retry_after ≤ 5` 秒 → 等完重送一次（429＝Telegram 沒做，重送不會變兩則）；更久的照舊交回呼叫的一方。
- 另一張還開著的 SDK 工作單：`_inbox/20261110-134500-service-build-argv-drops-filled-flag.md`（`build_argv` 丟掉前一個已填旗標）。
  可以一起出 0.2.2。

## 選項

| 選項 | 一句話 | |
|---|---|---|
| A. 兩件都搬（收訊分線＋429 短等重送），連同 build_argv 那張一起出 0.2.2 | SDK 跟 ClawBot 一致，SYNOX 重新 vendor 就有 | **建議（預設）** |
| B. 只搬 429 短等重送 | 改動小（`bot_api.post` 一處），但慢的 python pack 仍會卡住別人的按鈕 | |
| C. 不改 SDK，SYNOX 自己在 `src/synox` 包一層 | 不用等 SDK，但 SYNOX 的 AGENT.md 說 vendor 原樣、要不同行為才轉接；收訊分線包在外面很彆扭 | |

## 驗收

- SDK：假的慢 handler（睡 3 秒）在跑時，另一個聊天的文字與按鈕照常立刻被處理；同一個聊天的兩則照順序；
  假 session 回 429 `retry_after=1` → 只多送一次、回 ok；`retry_after=30` → 不等、回 `retry_after`；`pytest` 全過；版本 0.2.2。
- SYNOX：`.venv\Scripts\python.exe scripts\vendor_sdk.py` 重新 vendor，`vendor/VERSION` 換成新 commit，全套測試過
  （`tests/conftest.py` 用 `isdtelekit.testing` 的 `BotHarness`，它不經 Poller，應不受影響）。

## 不要做的事

- 不要改 `BotHarness`／`FakeChannel` 的介面（SYNOX 一千多個測試靠它）。
- 不要為了重送拿掉「一定沒送到才重送」的原則：除了 429 與連線沒建立，其他錯誤不重送（會變兩則）。
- 不要在 SYNOX 的 `vendor/` 直接改。
