# 🍎 apple-reminders（CalDAV 提醒事項）

**狀態（2026-11-09）**：程式做好了（`kind: python`、`capabilities: ["network"]`，只用 `requests`＋標準函式庫），
測試全部用假的 HTTP 傳輸，**還沒有對真的伺服器跑過**。

## 結論先講：iCloud 的提醒事項，現在大多數人用不了

| 情況 | 能不能用 |
|---|---|
| iCloud 帳號，提醒事項在 iOS 13（2019）之後**升級過**（幾乎所有人；新功能如子任務、標籤、群組都要升級） | ❌ Apple 把升級過的提醒事項搬離 CalDAV，第三方程式讀不到也寫不進去。登入會成功，但找不到任何提醒事項清單（`/applerem_status` 會說明） |
| iCloud 帳號，提醒事項**從沒升級**（極少數、很舊的裝置） | ✅ 可以，但 Apple 隨時可能關掉，不建議依賴 |
| iPhone 的提醒事項 App 接一個**別家的 CalDAV 帳號**（設定 → 提醒事項 → 帳號 → 加入帳號 → 其他 → 加入 CalDAV 帳號） | ✅ **建議的用法**。那個帳號的清單會出現在 iPhone 的提醒事項 App，SYNOX 連同一個伺服器讀寫。iOS 的升級只動「主要 iCloud 帳號」的提醒事項，其他 CalDAV 帳號不受影響 |
| iCloud **行事曆**（VEVENT） | ✅ CalDAV 仍然可用（DAVx⁵ 等 2026 年還在用）；這個 pack 沒做，見下面「替代方案」 |

依據：DAVx⁵ 的 iCloud 相容頁（「Reminders sync has been disabled by Apple and is only available when you use very old iOS
versions」「If you "upgrade" the Reminders with iOS 13, CalDAV functionality is removed by the server」）、
BusyCal 的 FAQ（iOS 13／Catalina 的提醒事項改存 Apple 私有的地方、不再支援 CalDAV）、Thunderbird CalDAV 外掛的使用者回報。
Apple 沒有官方的「提醒事項 API」給 Windows 用；EventKit 只在 Apple 裝置上。
**App 專用密碼**仍然是第三方 CalDAV 程式登入 iCloud 的方式（appleid.apple.com → 登入與安全性 → App 專用密碼），
iCloud 行事曆、聯絡人照樣能用它登入。

## 怎麼接

1. 在**這台電腦**上雙擊 `Connect-Apple.bat`（或 `python -m synox connect apple-reminders`）：
   - 伺服器網址（預設 `https://caldav.icloud.com`；別家就填那家的 CalDAV 網址，一定要 `https://`）
   - 帳號（iCloud 是 Apple ID 的 email）
   - App 專用密碼（打字時不顯示）
   存進保管箱 `data/apple-reminders.auth.json.enc`（密文；伺服器版是 `data/users/<id>/…`，`--user <id>` 指定替誰設）。
   **不提供在聊天裡登入**：Telegram 不是端對端加密、會留紀錄，SDK 的 `[ROUTE]` log 也會印出指令全文。
2. Telegram 打 `/applerem_status`：測試登入、列出找到的清單。

## 指令
| 指令 | 效果 | AI 能用 |
|---|---|---|
| `/applerem [清單]` | 列出還沒完成的（照到期排序，最多 30 項，有編號） | ✅ READ |
| `/applerem_lists` | 有哪些提醒事項清單 | ✅ READ |
| `/applerem_add <內容> [due=明天 15:00] [list=清單]` | 加一個；有時間的會帶一個到時提醒（VALARM） | ✅ WRITE |
| `/applerem_done <編號>` | 打勾（編號是上一次 `/applerem` 列的） | ✅ WRITE |
| `/applerem_status` | 帳號（遮住）＋連線測試 | ❌ |
| `/applerem_logout` | 清掉這台電腦存的帳號 | ❌ |

## 怎麼做的（給接手的人）
- CalDAV 流程：`PROPFIND` 伺服器根 → `current-user-principal` → `PROPFIND` principal → `calendar-home-set` →
  `PROPFIND Depth:1` 找 `supported-calendar-component-set` 有 `VTODO` 的集合 → `REPORT calendar-query`（VTODO）讀、
  `PUT … If-None-Match: *` 加、`GET`＋`PUT … If-Match: <etag>` 打勾。
- iCalendar 自己解析／產生（unfold／fold 75 octet、TEXT 跳脫、DATE／DATE-TIME／TZID／UTC），打勾時只換
  `STATUS`／`COMPLETED`／`PERCENT-COMPLETE`／`DTSTAMP`／`LAST-MODIFIED`，其他欄位（Apple 的 `X-` 欄位、VALARM）原樣留。
- 安全：只連 https；伺服器回的每個網址都要是同一台主機（iCloud 允許 `*.icloud.com`，因為帳號分流到 `pNN-caldav.icloud.com`），
  不跟隨重新導向；回應上限 5 MB；XML 有 `DOCTYPE`／`ENTITY` 拒讀；使用者的字跳脫後才寫進 iCalendar；
  重複（RRULE）的提醒事項不打勾（CalDAV 打勾會結束整串）。
- 網路呼叫在指令裡同步做（逾時 20 秒），這樣 AI 拿得到結果。
- 測試：`tests/test_apple_reminders.py`（假的 session，不連網）。

## 替代方案（iCloud 提醒事項用不了的時候）

| 選項 | 一句話 | 建議 |
|---|---|---|
| A. 接一個別家的 CalDAV 帳號到 iPhone 提醒事項（Fastmail、mailbox.org、自架 Nextcloud／Radicale／Synology Calendar） | 這個 pack 不用改、iPhone 提醒事項 App 看得到；要一個帳號（Fastmail 付費、Nextcloud 要自己架在別台機器） | ✅ 想真的同步 iPhone 就選這個 |
| B. 用 SYNOX 本機待辦（SYNOXPacks 的 `todo`）＋ Telegram 提醒 | 不碰 Apple、什麼帳號都不用；提醒從 Telegram 跳出來，不在 iPhone 提醒事項 App 裡 | ✅ **預設**（大部分人夠用） |
| C. 改寫 iCloud **行事曆**（VEVENT＋VALARM） | iCloud CalDAV 對行事曆仍開放，同一個 App 專用密碼；iPhone 會跳通知，但出現在「行事曆」不是「提醒事項」 | 需要的話另開一張做 |
| D. iPhone「捷徑」App 收 SYNOX 的訊息再建提醒事項 | 要捷徑能連到 SYNOX（SYNOX 只綁 127.0.0.1、這台不開埠），或靠使用者手動分享 | ❌ 不建議 |
