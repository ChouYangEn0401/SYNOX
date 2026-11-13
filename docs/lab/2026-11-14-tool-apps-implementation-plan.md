# 工具服務（每個工具自己的完整網頁）：實作計畫

- 狀態：**待處理**（提案；[ADR 0023](../adr/0023-tool-apps-services.md) 等擁有者核准。核准前不動 `src/`；核准後照下面的工作包做）
- 寫的時間：2026-11-14 01:54（分支 `feat/tool-apps`，基準 `dev` 的 `b5f48e2`）；**同日第二版**：照擁有者的回覆改了閒置設定（每個工具自己選）、「有在用」的定義、匯出、`kit` 版本欄位（搜尋「第二版」看得到每一處）
- 讀者：實作的代理（每個工作包一個，手上只有這份文件與 repo）。行號都是基準 commit 的。
- 工具那一側（記帳 app）：SYNOX_Libs 的 `docs/adr/0003-tool-apps-and-money-app.md`（工作包 7）。

## 擁有者原話（語音轉文字，一字不改）

> 我會希望未來從 Synox 的主機台，我可以開一個新的服務，然後這個服務就會去開 port 幫我把這個軟體把它架上去。然後呃我們那邊就可以在這個網頁裡面去看它的。結果這樣，然後如果把它關掉了嘛，就回到 Synox 那邊，然後 Synox 這邊就會一直有一個狀態去顯示說你某一個後端有開，那不要用的時候就會建議把它關掉。等於說就是真的是做到我本機的 Telegram 這個感覺，就是 Telegram 會控制某一個服務去幫我做記賬啊，幫我做行事曆的的記錄，可是然後我也有個前端可以看，然後我不用的時候可以關掉，不會有資安的風險。

關於閒置（2026-11-14）：

> 有些東西他可以決定不開有些東西可以決定不關有些東西可以用例如說三十分鐘一百二十分鐘沒有用自己關然後這個東西就在 synox 上面可以讓別人看到它可以自己設定……如果使用者堅持要自己開著那當然也沒有問題。原則上我們的 skills 從我們這邊出發的當然就是儘可能做好不要做出這種意外的漏洞

其餘的回覆（協調者整理，不是原話）：任何裝好的工具都可以附 app（報告明講＋紅字）；app 框架是工具自己選用的，沒選用就沒有這一面；要可以匯出、不擋個人使用者，
多人共用的只給加密的（加密格式還在討論）；AI 能不能開服務還在討論，先維持「不能開」；一般使用者要看得懂什麼是服務、為什麼要關。

## 問題一句話

工具現在只有指令與一小塊唯讀面板；沒有「完整畫面、能改資料、要用才開、不用就關、主機台隨時看得到」的東西。

## 脈絡（動手前要知道的）

- 網頁介面：`src/synox/web/server.py`。所有判斷在 `WebUI.route()`；`_Handler`（`:1735-1759`）只叫 `self.server.ui.handle(method, path, headers, body)`——**任何有 `handle` 的物件都能掛在 `_Server` 上**，這是整個設計的支點。
- 綁定：`HOST`（`:63`）、`bind_host()`（`:187-207`）、`_Server`（`:1721-1732`，Windows 獨佔）。**不准新增別的綁定方式**（AGENT.md invariant 9）。
- 現有的防護：session cookie `synox_session`（HttpOnly、SameSite=Lax）、`_csrf_problem`（`:374-382`：Origin 的 netloc＝Host、`X-SYNOX-CSRF`）、本機自動登入 `_local_owner_navigation`（`:358-364`）。
- 面板：`web.panel`／`web.api`（`manifest.py:362-389`、`loader.py:196-201`、`server.py:504-514`、`:883-891`）。**不要改它**。
- 指令：`kit.command`（`kit.py:172-193`）把 `fields` 掛在葉節點；檢查在 `kit.parse_args`（`:133-169`）。危險程度 `node.effect`（`read`／`write`／`danger`）。權限 `app.registry.authorize(user, node, via, chat_id)`（已經接上 `policy.decide`）。
- 背景工作只能登記成 runtime 任務（AGENT.md invariant 18；範例 `runtime/keepawake.py` 的 `register`／`reschedule`）。
- 測試的假瀏覽器：`tests/test_web.py` 的 `Client`（`:38-80`）。JS 單元測試：`tests/js/*.js` 由 pytest 用 node 跑。
- **瀏覽器的 cookie 不分埠、同一個主機的不同埠算「同一個網站」**（ADR 0023 §3.1）。下面每一條標頭檢查都是為了這件事，不能省。

## 鐵則（每個工作包都要守；違反就不收）

1. **這台電腦不准開任何網路埠、不准動防火牆。** 不啟動 SYNOX、不跑 `synox run`、不起任何伺服器、不寫會 `bind`／`listen` 的測試、不用瀏覽器或無頭瀏覽器。
   驗證只用：`handle()`／`route()` 這種直接呼叫、假時鐘、假的 listener、node 跑純 JS。
2. 跑測試：做的時候只跑自己那幾個檔（`.venv\Scripts\python.exe -m pytest tests\test_app_site.py -q`）；交件前跑一次全部，並且**一定**加
   `--deselect tests/test_web.py::test_port_already_in_use_is_a_bind_failure`（那一個會暫時 listen）。全部約 3～4 分鐘，不要同時跑兩份。不跑 Unity、不裝套件、不連網。
3. 新的測試檔開頭都放這個保險（寫進 `tests/conftest.py` 當 fixture `no_sockets`，新檔用 `pytestmark = pytest.mark.usefixtures("no_sockets")`）：
   把 `socket.socket.bind` 與 `socket.socket.listen` 換成一叫就 `raise AssertionError("測試不准開埠")`。
4. 不執行網路上抓來的東西；不新增任何第三方相依（只用標準函式庫與 repo 已有的）。
5. Git：每個工作包從 `feat/tool-apps` 開自己的分支（`feat/tool-apps-wp<N>-<短名>`），做完**不要合、不要推**，回報分支名。之後由協調者用
   `git merge --no-ff` 合回 `feat/tool-apps`，訊息寫這包做了什麼、為什麼。commit 訊息結尾照你那個 session 的署名規定。
6. `vendor/` 不改。給使用者看的字是白話繁體中文、一個檔一張字串表（JS 檔開頭 `var TEXT = {…}`、Python 模組 `TEXT = {…}`）；主流程的字不出現 port、session、CSRF、origin。
7. repo 裡不寫真名、帳號、本機絕對路徑、Telegram id（invariant 8）。
8. 合約（下一節）是工作包之間的介面：**不要自己改名字或形狀**；覺得合約有問題，停下來回報。

---

## 合約（所有工作包共用）

### C1 設定（`config.json`）

```json
"web": { "enabled": true, "port": 8830, "public_url": "",
         "apps": { "enabled": true, "port_first": 8841, "port_count": 8, "max_running": 3,
                   "idle_suggest_min": 30, "idle_close_min": 120 } }
```

| 欄位 | 規則（不合＝`ConfigError`，一句白話） |
|---|---|
| `enabled` | 布林，預設 true。true 也**不會自己開任何服務**；只是允許擁有者開 |
| `port_first`／`port_count` | 1024–65000／1–20；範圍不能包含 `web.port` |
| `max_running` | 1–`port_count` |
| `idle_suggest_min`／`idle_close_min` | 0–1440；0＝不提醒／不自動關；兩個都不是 0 時 `idle_close_min` 要大於 `idle_suggest_min`。**（第二版）這兩個只是「擁有者還沒替它選過的工具」用的預設；每個工具自己的設定在 `data/apps.json`（C8、C10）** |

功能不可用的情況（`AppManager.available()` 回 `(False, 原因)`，任何「開啟」都拒）：`web.enabled` 是 false、`web.apps.enabled` 是 false、`/web_off` 之後、
`bind_host()` 不是 `127.0.0.1`（＝在容器裡；原因：「容器版還沒開放工具服務」）、`bind_host()` 丟 `BindError`。

### C2 `pack.json` 的 `web.app`

```json
"web": { "app": { "entry": "app/index.html", "root": "app", "title": "記帳本", "kit": 1,
                  "reads": ["month", "entries"], "actions": { "add": "WRITE", "rm": "DANGER" },
                  "exports": ["entries_csv"] } }
```

解析後放在 `Manifest.web["app"]`：沒有宣告＝`None`；有＝
`{"entry": "app/index.html", "root": "app", "title": "記帳本", "kit": 1, "reads": ["month", "entries"], "actions": {"add": "write", "rm": "danger"}, "exports": ["entries_csv"], "files": ["app/app.js", "app/index.html", …]}`
（`files`＝`root` 底下全部檔的相對路徑，正斜線、排序過）。規則見工作包 1。

（第二版）`kit`：必填的整數，這個 app 照哪一版共用元件寫的；現在只收 `1`（常數 `KIT_VERSIONS = (1,)`）。`exports`：選填。
**沒有 `web.app` 的工具沒有任何 app 表面**：不在 `specs()`、不在 `GET /api/apps` 的清單、`start` 回 404、沒有任何埠與路由——工作包 2 有測試鎖住。
工具不能在宣告裡替自己選閒置設定（沒有這種欄位；多寫的鍵在安裝時＝拒）。

### C3 工具端的 Python 介面（SDK 0.2.3 新增，只加不改）

```python
pack.app_read(name: str, fn)                       # fn(user, params: Dict[str, str]) -> 可轉 JSON 的東西
pack.app_action(name: str, fn, *, describe=None)   # fn(user, values: Dict[str, str]) -> dict
                                                   # describe(user, values) -> str：危險動作確認框的那一句（選填）
kit.check_values(fields, values) -> (clean: Dict[str, str], missing: List[Field], errors: List[str])
kit.AppError(message: str, code: str = "refused", status: int = 409)   # fn 裡丟：照 message 回給畫面
pack.app_export(name: str, fn)                     # （第二版）fn(user, params: Dict[str, str]) -> kit.Download
kit.Download(filename: str, content_type: str, data: bytes)            # （第二版）一個要給使用者存下來的檔
```

- 名字沒寫在 `web.app.reads`／`actions`／`exports` 裡就掛 → `ValueError`（跟 `web_route` 一樣）。存放：`pack.app_reads: Dict[str, Callable]`、`pack.app_actions`、`pack.app_describe`、`pack.app_exports`。
- `kit.check_values`：對**已經照名字放好的** `values` 做 `kit.parse_args` 後半段那些事（`choices`、`check`、補 `default`、找缺的必填）。`parse_args` 改成「切字 → 叫 `check_values`」，行為與訊息一個字都不變（現有測試不改就要過）。
- 工具要相容舊的 SYNOX：`if hasattr(pack, "app_read"): …`（同 money 現在對 `web_route` 的寫法）。

### C4 app 埠上的路由（`AppSite.handle(method, target, headers, body) -> (status, headers, body)`）

每個請求依序：

1. `Host` 不是 `127.0.0.1:<埠>`、`localhost:<埠>` → 403 純文字頁（不洩漏任何東西）。
2. 方法只收 GET、POST；其他 405。**任何回應都不帶 `Access-Control-*`。** `OPTIONS` → 405。
3. 每個回應都帶 `BASE_HEADERS`＋`X-Frame-Options: DENY`＋`Cross-Origin-Opener-Policy: same-origin`＋`Cross-Origin-Resource-Policy: same-origin`＋
   `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'`。

| 路由 | 要登入 | 做什麼 |
|---|---|---|
| `GET /` | 進門規則（下） | 回入口頁（`entry` 的位元組，`text/html; charset=utf-8`） |
| `GET /_synox/kit.js`、`/_synox/kit.css` | 要 | SYNOX 的共用元件（`src/synox/web/static/appkit.js`、`appkit.css`） |
| `GET /<root 底下的相對路徑>` | 要 | 記憶體快照裡的那個檔；`Content-Type` 照副檔名白名單；查不到 404 |
| `GET /api/me` | 要 | 見 C5 |
| `GET /api/read/<name>?k=v` | 要 | `{"ok": true, "data": fn(user, params)}`；`params` 每個鍵取第一個值 |
| `POST /api/do/<name>` | 要＋CSRF | 見 C6 |
| `POST /api/export/<name>` | 要＋CSRF（表單欄位） | （第二版）見 C6.1 |
| `POST /api/alive` | 要＋CSRF | （第二版）「人還在」：見 C11。回 `{"ok": true}`；不記稽核 |
| `POST /api/keep` | 要＋CSRF | 「先留著」：`manager.keep(name)` → `{"ok": true}` |
| `POST /api/leave` | 要＋CSRF | 登出這個 app（刪這個登入、清 cookie） |
| `POST /api/close-service` | 要＋CSRF＋擁有者 | `manager.stop(name, by=user, via="app")`；先回 `{"ok": true}` 再關 |

進門規則（**只有** `GET /`）：

1. 有有效的 app cookie（`synox_app_<name>`）→ 進。
2. 沒有，但有有效的主機台 session（`synox_session`，用 `ui.sessions`）而且 `registry.visible(user, group)` → 新發 app 登入，`Set-Cookie`，回入口頁。
   若請求帶了 `Sec-Fetch-Mode` 而不是 `navigate`，或帶了 `Sec-Fetch-Dest` 而不是 `document` → 不發（當成沒登入）。
3. 沒有，而 `ui._local_owner_navigation(headers)` 的條件成立（把比對的埠換成 app 的埠；實作上抽一個接受埠參數的函式，兩邊共用）→ 以擁有者新發。
4. 都不是 → 401 的白話頁：「請先從 SYNOX 打開這個工具」＋回主機台的連結（`http://127.0.0.1:<web.port>/#tools`）。

API 路由（`/api/…`、`/_synox/…`、靜態檔）**不發登入**，沒登入一律 401 JSON `{"ok": false, "code": "login", "error": …}`。另外：

- 帶了 `Sec-Fetch-Site` 而且不是 `same-origin`（靜態檔與 `/_synox/` 也收 `none`）→ 403 `code: "origin"`。
- 帶了 `Origin`：netloc 要等於 `Host`；`Origin: null` 只有在 `Sec-Fetch-Site: same-origin` 時放行。否則 403 `code: "origin"`。
- POST：`X-SYNOX-CSRF` 要等於這個 app 登入的 csrf（`hmac.compare_digest`），否則 403 `code: "csrf"`；`Content-Type` 要以 `application/json` 開頭、內容是 JSON 物件，否則 400。
- cookie：`synox_app_<name>=<sid>; HttpOnly; SameSite=Strict; Path=/`（不設 Max-Age）。同名 cookie 有好幾個時每個都試，第一個有效的算數。
- 「有在用」的精確規則在 C11（第二版）。被拒絕的請求（origin／csrf／host）寫一行稽核 `denied`（同一個原因每分鐘最多記一行，免得被灌爆）。

錯誤一律 `{"ok": false, "code": "<代碼>", "error": "<白話>"}`。代碼：`login` 401、`origin`／`csrf`／`forbidden` 403、`not_found` 404、`invalid` 400（多一個 `fields: {欄位名: 訊息}`）、
`confirm` 409（多一個 `confirm`）、`refused`（工具丟的 `AppError`，用它的 status）、`too_large` 413、`error` 500（只說「出錯了：<例外類別名>」，細節進 log）。

### C5 `GET /api/me`

```json
{"ok": true,
 "user": {"id": 1, "name": "顯示名稱", "owner": true},
 "csrf": "…",
 "app": {"name": "money", "title": "💰 記帳", "app_title": "記帳本", "version": "0.3.0"},
 "reads": ["month", "entries"],
 "actions": {"rm": {"effect": "danger", "summary": "刪掉某一筆…", "fields": [{"name": "n", "label": "編號", "required": true, "kind": "int", "default": ""}]}},
 "console_url": "http://127.0.0.1:8830/#tools",
 "exports": {"entries_csv": {"available": true, "reason": ""}},
 "policy": {"mode": "auto", "suggest_min": 30, "close_min": 120, "text": "120 分鐘沒用就關，30 分鐘先提醒"},
 "alive_every_s": 60}
```

（第二版）`exports[*].available`：個人版 true；伺服器版 false，`reason` 是 C6.1 那句話（畫面據此把按鈕變灰並說明）。`policy` 見 C10；`alive_every_s` 是 C11 的間隔。

`actions[*].summary`／`fields` 取自那個葉節點（`fields` 用 `toolpage.field_info`，`src/synox/web/toolpage.py:66-77`），所以畫面的表單說明跟 `/help`、工具頁同一份。

### C6 `POST /api/do/<name>`

請求：`{"values": {"欄位名": "字串", …}, "confirm": "<票>"}`（`confirm` 選填）。伺服器依序：

1. `name` 在 `spec.actions` 而且工具掛了函式，否則 404。
2. `node = registry.node(f"{group}.{name}")`；`registry.authorize(user, node, TYPED, user.tg_id)` 不放行 → 403 `forbidden`（訊息用 Decision 的文字，沒有就「你不能做這個動作」）。
3. `values` 要是物件；鍵要是這個節點的欄位名（不認得的拒）、值要是字串、最多 20 個、每個最多 2000 字、不能有 NUL——能重用 `src/synox/agent/validate.py` 的檢查就重用，不要另抄一份。
   再叫 `kit.check_values(node.fields, values)`：有 `errors` 或 `missing` → 400 `invalid`，`fields` 逐欄列出（訊息跟 Telegram 那條同一句）。
4. `node.effect == "danger"`：沒帶 `confirm` → 409：
   `{"ok": false, "code": "confirm", "error": "這個動作要你確認", "confirm": {"token": "…", "expires_in": 60, "text": "<describe(user, values) 或「<節點的 summary>」>"}}`。
   票：隨機、一次性、60 秒、綁（這個 app 登入、動作名、`values` 正規化後的 SHA-256）。帶了但對不上／過期／用過 → 409 再發一張新的。
5. 呼叫 `fn(user, clean)`。回傳值要是 `dict`。`kit.AppError` → 照它的 `status`／`code`／`message`；其他例外 → 500 `error`、`logging.exception`。
6. 稽核一行（成功或失敗都記）。回 `{"ok": true, "data": <fn 的回傳>}`。

### C6.1 `POST /api/export/<name>`（第二版；ADR §2.1）

這一條是**表單送出**（瀏覽器才會把回應當附件存檔），所以跟其他 POST 有兩點不同：`Content-Type` 是 `application/x-www-form-urlencoded`；
CSRF token 放在表單欄位 `csrf`（一樣用 `hmac.compare_digest` 對這個 app 登入的 csrf）。來源檢查照 C4（同源表單在 `no-referrer` 下會送 `Origin: null`，
所以這條特別依賴「`Origin: null` 只在 `Sec-Fetch-Site: same-origin` 時放行」那一條）。其他表單欄位：`confirm`（票，選填）、其餘的都當 `params`（字串）。

伺服器依序：

1. `name` 在 `spec.exports` 而且工具掛了函式，否則 404。這個人要看得到這個工具（`registry.visible`），否則 403。
2. **伺服器版（`config.mode == "server"`）一律拒**：403 `code: "export_encrypted_only"`，`error`：「這台 SYNOX 是多人共用的，只能匯出加密的檔；這個功能還沒做好。」`fn` 不會被叫到。稽核 `export`、`ok: false`。
   （加密匯出的格式擁有者還沒定——ADR「還沒定的」第 2 題。**不要自己挑一種做。**）
3. 沒帶 `confirm` → 409 JSON：`{"ok": false, "code": "confirm", "confirm": {"token", "expires_in": 60, "text": "匯出的檔案沒有加密，打得開這個檔的人都看得到內容。存在你放心的地方，用完就刪。", "button": "下載"}}`。
   票跟危險動作同一個 `ConfirmTickets`（綁登入、`export:<name>`、`params` 的雜湊）。這段字是 SYNOX 的常數，工具改不了。
4. 帶了有效的票 → `result = fn(user, params)`，必須是 `kit.Download`：`filename` 只留英數與 `-_.`（其他換成 `_`，最多 80 字，一定要有副檔名）；
   `content_type` 只收白名單（`EXPORT_TYPES = ("text/csv; charset=utf-8",)`）；`data` 是 `bytes`、最多 20 MB。不合 → 500 `error`（工具寫錯了，進 log）。`kit.AppError` 照舊。
5. 回 200：`Content-Type` 照白名單、`Content-Disposition: attachment; filename="<檔名>"`、其餘標頭照 C4 第 3 點。
6. 稽核 `export`：`action`＝名字、`ok`、`bytes`＝大小。**不記 `params` 的值、不記檔案內容。**

共用元件的流程（工作包 3）：先用 `fetch` 送一次（不帶票，`Content-Type` 一樣是表單格式、`csrf` 在內容裡）拿到 409 的那段字 → 畫確認框 → 按「下載」→ 建一個看不見的 `<form method="post">` 帶 `csrf`、`confirm`、參數送出。
`available` 是 false 時不送任何請求，直接顯示 `reason`。

### C7 主機台的 API（8830；照現有規矩：要登入、非 GET 要 CSRF）

| 路由 | 誰 | 回 |
|---|---|---|
| `GET /api/apps` | 登入的人 | 下面的清單（成員只看得到自己看得到的工具；`can_manage` 只有擁有者是 true） |
| `POST /api/apps/<name>/start` | 擁有者 | `{"ok": true, "app": <一筆>}`；錯：403、404、409（`code: "max_running"`，訊息列出開著的）、409（`code: "unavailable"`）、409（`code: "blocked"`，第二版：這個工具被設成不開放）、503（`code: "port"`） |
| `POST /api/apps/<name>/stop`、`/keep` | 擁有者 | `{"ok": true, "app": <一筆>}` |
| `POST /api/apps/<name>/policy` | 擁有者 | （第二版）內容見 C10 → `{"ok": true, "app": <一筆>}`；不合 400 |
| `POST /api/apps/stop-all` | 擁有者 | `{"ok": true, "stopped": ["money"]}` |
| `GET /api/apps/log?limit=50` | 擁有者 | `{"events": [<稽核行>…]}`（新的在前，最多 200） |

```json
{"available": true, "reason": "", "can_manage": true, "running": 1, "max_running": 3,
 "explain": {"what": "…", "why_close": "…", "restart": "…"},
 "apps": [{"name": "money", "title": "💰 記帳", "app_title": "記帳本", "state": "on",
           "url": "http://127.0.0.1:8841/", "port": 8841,
           "since": "2026-11-14T10:00:00", "last_used": "2026-11-14T10:20:00", "idle_min": 12,
           "suggest_close": false, "auto_close_in_min": 108, "error": "",
           "policy": {"mode": "auto", "suggest_min": 30, "close_min": 120, "default": true,
                      "text": "120 分鐘沒用就關，30 分鐘先提醒"},
           "actions": {"write": 9, "danger": 1}, "exports": ["entries_csv"], "problem": ""}]}
```

（第二版）`policy` 給**每個看得到這個工具的人**（成員也看得到，只是不能改）；`auto_close_in_min` 在不會自動關的設定下是 `null`。

`state`：`off`｜`on`｜`error`。`problem`：宣告了 app 但掛不起來的原因（例如「動作 rm 宣告是 WRITE，指令是 DANGER」）；有 `problem` 的不能開。`explain` 的三句照 ADR 0023「給使用者的說法」。

### C8 稽核與狀態檔

- `data/apps_audit.jsonl`，一行一個 JSON：`{"at": "<ISO 秒>", "event": "start|stop|auto_stop|suggest|keep|enter|leave|action|export|policy|denied|error", "app": "money", "by": <tg_id 或 0＝系統>, "via": "web|telegram|app|system", "action": "", "effect": "", "ok": true, "code": "", "port": 8841, "bytes": 0, "note": ""}`
  （第二版：`export`、`policy` 兩種事件與 `bytes`；`policy` 的 `note` 寫新設定的 `text`）。
  **不寫參數的值、不寫 cookie／token。** 超過 1 MB：改名成 `apps_audit.jsonl.1`（蓋掉舊的）再開新檔。寫檔持鎖。
- `data/apps.json`：`{"ports": {"money": 8841}, "explained": true, "policy": {"money": {"mode": "auto", "close_min": 120}}}`（配過的埠；擁有者看過第一次說明了沒；（第二版）每個工具的閒置設定，沒有那一筆＝用預設）。
- `data/apps_state.json`：`{"pid": 1234, "at": "<ISO>", "running": [{"name": "money", "port": 8841, "since": "<ISO>"}]}`。SYNOX 啟動與結束時都寫成空清單；每次開關更新。給 `doctor` 讀（doctor 是另一支程序）。

### C9 Telegram／指令

群組 `apps`（`registry.ensure_group("apps", "🧩 工具服務", "開、關、看每個工具自己的網頁", bare=True, …)`，個人版擁有者、伺服器版成員可看清單）。

| 指令 | 危險程度 | 誰 | AI | 回什麼 |
|---|---|---|---|---|
| `/apps` | 唯讀 | 看得到工具的人 | 可 | 每個有 app 的工具一行：開著（網址、開多久、多久沒用）／關著；最後三筆紀錄；一句「開：/app_open 名字　關：/app_close 名字」 |
| `/app_open <名字>` | 會寫入 | 擁有者、只在私訊 | **否**（`ai=False`） | 開（已開就不重開）→「💰 記帳的畫面開好了：http://127.0.0.1:8841/（只有跑 SYNOX 的這台電腦打得開）。不用的時候 /app_close money。」第一次另附 ADR 的三句說明 |
| `/app_close <名字｜all>` | 會寫入 | 擁有者 | 可 | 「關好了。資料都在，Telegram 照樣可以用。」 |

`<名字>` 認：pack 名、群組名、標題（去掉 emoji 與空白）、`app.title`，不分大小寫；對不到 → 列出有哪些。

（第二版）`/apps` 每一行後面加這個工具的閒置設定（`policy.text`）；設成「不開放」的工具 `/app_open` 回「你把<標題>設成不開放了；要開先到 SYNOX 網頁的工具頁改設定。」
這一輪**沒有**改閒置設定的 Telegram 指令。AI 能不能開服務擁有者還在考慮，定案前 `/app_open` 維持 `ai=False`，不要預留 AI 的路。

### C10 每個工具的閒置設定（第二版；ADR §4.2）

`POST /api/apps/<name>/policy` 的內容與 `data/apps.json` 存的形狀：

| `mode` | 其他欄位 | 行為（`AppManager.tick()`） | `text`（給人看） |
|---|---|---|---|
| `auto` | `close_min`：5–1440 的整數 | 閒置滿 `close_min` → 自動關＋通知。`close_min > 30` 時，閒置滿 30 分鐘先提醒一次；`≤ 30` 不另外提醒 | 「120 分鐘沒用就關，30 分鐘先提醒」／「30 分鐘沒用就關」／「N 分鐘沒用就關…」 |
| `suggest` | — | 閒置滿 30 分鐘提醒一次（同一段閒置只一次），不關 | 「只提醒，不自動關」 |
| `keep` | 請求要帶 `"understood": true`，否則 400 | 不提醒、不關 | 「一直開著」 |
| `blocked` | — | 不能開；設定當下開著的先關掉（稽核 `stop`，`note`「設成不開放」） | 「不開放這個工具的畫面」 |

- 沒有存過設定的工具：`mode: "auto"`、`suggest`／`close` 用 `web.apps.idle_suggest_min`／`idle_close_min`（預設 30／120），`policy.default` 是 true。
  `config.json` 的 `idle_close_min` 是 0 時預設等同 `suggest`；兩個都是 0 等同 `keep`（這是擁有者自己改設定檔的選擇，不用再問）。
- 提醒的 30 分鐘是常數 `SUGGEST_MIN = 30`（`auto` 與 `suggest` 共用；預設那一組用設定檔的值）。
- 只有擁有者能改；每次改寫一行稽核 `policy`。改設定算一次「先留著」（重新計時）。
- 「一直開著」**不保存「開著」這件事**：SYNOX 重開之後它一樣是關的，只是下次開了之後不會被閒置關掉。
- 畫面上的選項與警告文字在 ADR §4.2 的表（工作包 4 照抄進 `TEXT`）。

### C11 什麼算「有在用」（第二版；ADR §4.1）

`manager.touch(name)`（更新 `last_used`、清掉「這一段閒置已經提醒過」）**只在**這些時候叫：

1. app 埠上任何**已登入而且通過 C4 檢查**的請求：`GET /`（進門成功）、靜態檔、`/_synox/*`、`/api/me`、`/api/read/*`、`/api/do/*`（不管成功失敗）、`/api/export/*`、`/api/keep`。
2. `POST /api/alive`：同一個 app 登入**每 60 秒最多算一次**（`AppSession.last_alive`；太頻繁的照樣回 200 但不 `touch`）。
3. 主機台的「先留著」與改閒置設定。

不叫的：沒登入、被擋的請求；主機台的 `GET /api/apps`（看狀態不算用）；`tick()` 自己。

共用元件什麼時候送 `/api/alive`（工作包 3）：在 `mousemove`、`keydown`、`pointerdown`、`wheel`、`scroll`、`touchstart` 的監聽裡（`passive: true`），
`event.isTrusted` 而且 `document.visibilityState === "visible"` 而且距離上次送出（或上次任何 `read`／`act` 成功）超過 `alive_every_s` 秒 → 送一次。
**沒有 `setInterval`／`setTimeout` 迴圈**：沒有輸入就什麼都不送。失敗不重試、不顯示任何東西（連不上時由下一次真的操作去顯示遮罩）。

---

## 工作包

相依與順序：

```
WP0 主機台加固 ─┐
WP1 宣告與檢查 ─┼─→ WP2 核心執行 ─┬─→ WP4 主機台畫面 ─┐
WP3 共用元件  ──┘                 ├─→ WP5 Telegram＋doctor ─┼─→ WP7 記帳 app（SYNOX_Libs）
                                  └─→ WP6 SDK 與文件 ───────┘
```

WP0、WP1、WP3 可以同時做（檔案不重疊）；WP2 等 WP1 合進來；WP4、WP5、WP6 等 WP2，可同時做；WP7 最後。同一時間最多五個代理。
合回 `feat/tool-apps` 的順序：0 → 1 → 3 → 2 → 4 → 5 → 6（`server.py` 的衝突最少）。

### WP0 主機台加固（跟功能無關，只有變嚴；可以先單獨合進 `dev`）

**為什麼**：之後同一個主機上會有別的埠在跑第三方的畫面程式；主機台要先不怕「同站不同埠」的請求。

改 `src/synox/web/server.py`：

1. `route()`：`path.startswith("/api/")` 而且請求帶了 `Sec-Fetch-Site`、值是 `same-site` 或 `cross-site` → `_err(403, "來源不對（不是從 SYNOX 自己的頁面送出的）。")`。沒帶這個標頭（curl、舊瀏覽器）照舊。放在登入檢查之前。
2. `_cookie` 旁邊加 `_cookies(headers, name) -> List[str]`（同名的全部）；`session_from` 改成每個都試、回第一個有效的。`_cookie` 留著給其他呼叫端。
3. 所有回應加 `Cross-Origin-Opener-Policy: same-origin`；`_json` 的回應加 `Cross-Origin-Resource-Policy: same-origin`（加在 `BASE_HEADERS`／`_json`，不要一個一個路由補）。
4. 把 `_local_owner_navigation` 裡的判斷抽成模組層函式 `owner_navigation(headers, port) -> bool`（方法留著、改成呼叫它）；WP2 要用。

測試 `tests/test_web_hardening.py`：

- `/api/me` 帶 `Sec-Fetch-Site: same-site`／`cross-site` → 403；`same-origin`、`none`、沒帶 → 照舊 200。POST 同理。
- `/`、`/login`、`/tutorials/x/` 不受影響（帶 `cross-site` 也照舊）。
- Cookie 標頭是 `synox_session=假的; synox_session=<真的>` 與反過來 → 都認得出登入。
- 每種回應（頁面、JSON、錯誤）都有 COOP；JSON 有 CORP。
- `owner_navigation`：對的埠＋三個 `Sec-Fetch-*` → True；埠不對、帶 `Origin`、`same-site` → False。

驗收：新測試全過；現有 `tests/test_web*.py`、`test_tools_page.py`、`test_control_panel.py` 不改就過；`docs/security.md`「網頁介面」補一行說明這三項。

### WP1 宣告與檢查（manifest、第 2 關、升級紅字、報告、工具端介面）

檔案：

| 檔 | 做什麼 |
|---|---|
| `src/synox/packs/manifest.py` | `parse_web` 多解析 `app`（C2）。規則：kind 不是 python → 拒；`root` 是 pack 裡的子資料夾（不能是 `.`、不准 `..`、絕對路徑；沿用 `_inside`）；`entry` 是 `root` 裡的 `.html`、檔案存在；`title` 選填、一行、24 字內；`reads` 清單、名字合 `WEB_ROUTE_RE` 的名字規則、不重複、最多 40；`actions` 物件、名字同規則、值只收 `WRITE`／`DANGER`（不分大小寫，存小寫）、最多 40；（第二版）`kit` 必填、整數、要在 `KIT_VERSIONS` 裡（不認得的版本＝拒，訊息說這台 SYNOX 認得哪幾版）；`exports` 選填、清單、名字同規則、不重複、最多 10；`web.app` 裡不認得的鍵＝拒（安裝時）；`reads` 與 `actions` 至少一邊有東西；`root` 底下：副檔名只准 `.html .js .css .json .png .jpg .jpeg .webp .svg .ico .woff2`、最多 100 個、單檔 ≤ 512 KB、合計 ≤ 3 MB、不准符號連結。`_unc_strings` 加 `web.app.root`、`web.app.entry`（strict）。常數集中放檔頭（`APP_EXT`、`APP_MAX_FILES`…）。已裝的舊 pack 寫壞了＝當作沒有 app（不要讓整個工具載不起來），安裝時（strict）＝拒 |
| `src/synox/packs/appscan.py`（新） | `scan_app(m) -> List[Finding]`（沿用 `scan.Finding`）。HTML 用 `html.parser`：有內容的 `<script>`、`on*` 屬性、`<base>`、`<meta http-equiv>`、`<iframe>`／`<object>`／`<embed>`／`<frame>` → 擋；`entry` 沒有 `<script src="/_synox/kit.js">` → 擋。所有文字檔（html／js／css／json／svg）：出現 `http://`、`https://`、或引號後面接 `//主機` → 擋，`http://www.w3.org/` 開頭的除外；CSS 的 `@import` → 擋。JS 的提醒（不擋）：`eval(`、`new Function`、`document.cookie`、`window.open`、`location.href =`／`location =`／`location.assign`／`location.replace`、`sendBeacon`、`WebSocket`、`importScripts`、（第二版）`fetch(`／`XMLHttpRequest`（「畫面程式自己連線，沒經過共用元件」）。每筆有檔名與行號。新的 finding 種類 `app`（擋）與 `app_note`（提醒），加進 `scan.LABELS`（「網頁畫面不合規則」／「網頁畫面（提醒）」）與 `CAPABILITY_OF`（`""`） |
| `src/synox/packs/scan.py` | `opaque_files`／`opaque_reason`：宣告了 `web.app` 時，`root` 底下副檔名在 `APP_EXT` 的檔**不算**掃不到的檔（要把 manifest 或 app root 傳進來；簽名怎麼改自己定，但 `tier.assess` 兩條路都要一致）。`scan()` 把 `appscan.scan_app(m)` 的結果併進報告 |
| `src/synox/packs/admin.py` | `summary_of` 多 `"app": None 或 {"title", "kit", "files": 個數, "reads": [...], "actions": {...}, "exports": [...]}`；`warnings_for` 多 ADR §5 那一段白話（有 app 一定顯示）；（第二版）有 `exports` 再多一句「它的畫面可以把資料匯出成檔案：<名字>。」 |
| `src/synox/packs/upgrade.py` | 三條：`app`「新加了完整的網頁畫面（工具服務）」紅；`app_action_added`「畫面多了動作 <名>（<危險程度>）」紅；`app_effect`「畫面動作 <名> 的危險程度 a → b」變寬紅、變窄一般；拿掉 app／動作一般字；（第二版）`app_export_added`「畫面多了匯出 <名>」紅 |
| `src/synox/packs/loader.py` | `Pack` 加 `app_reads`、`app_actions`、`app_describe`、`app_exports` 四個 dict 與 `app_read()`、`app_action()`、`app_export()`（C3）；重新載入時清空 |
| `src/synox/packs/kit.py` | `check_values`、`AppError`、（第二版）`Download`（dataclass）；`parse_args` 改用 `check_values` |
| `tests/fixtures/app_pack/` | 測試用的小工具 `counter`：`pack.json`（python、`data: user`、`storage: vault`、`web.app`：`kit: 1`、reads `state`，actions `add: WRITE`、`reset: DANGER`、exports `state_csv`）、`pack.py`（指令 `add <n>`（WRITE，`check=kit.positive_int`）、`reset`（DANGER）＋ `app_read`／`app_action`／`app_export`，核心函式共用）、`app/index.html`、`app/app.js`（只用 `SynoxApp.*`，沒有 `fetch`）、`app/app.css`、`SKILL.md`。**之後每個工作包的測試都用它** |
| `src/synox/web/static/app.html`（安裝報告那一段） | 報告顯示 `summary.app`：一段白話＋動作清單（沿用 `EFFECT` 的字）。只加顯示，不動流程 |

測試 `tests/test_app_manifest.py`：

- 好的 fixture 過第 1、2 關；信任層級是 T1（`app/app.js` 沒把它推到 T2）；沒宣告 `exec` 也不會被要求。
- 每條第 1 關規則各一個壞例子 → 拒，訊息點名欄位（`..`、絕對路徑、UNC、`root` 是 `.`、`entry` 不在 `root`、副檔名不在白名單（`app/x.py`、`app/x.exe`）、檔太多、檔太大、`actions` 的值是 `READ`、kind=cli）。
- `app/` 外面的 `.js` 照舊算掃不到的檔（T2）；`app/` 裡放 `.py` → 拒。
- appscan：內嵌 script、`onclick=`、`<base>`、`<iframe>`、`https://evil.example/x.js`、CSS `@import`、入口頁沒有 kit → 各自被擋、有檔名行號；SVG 的 `xmlns="http://www.w3.org/2000/svg"` 不擋；`eval(` 只是提醒。
- 升級：舊版沒有 app → 新版有 ＝紅；多一個動作＝紅；`WRITE`→`DANGER`＝紅；`DANGER`→`WRITE`＝一般。
- `pack.app_read`／`app_action`／`app_export`：沒宣告的名字丟 `ValueError`；宣告的掛得上。
- （第二版）`kit`：沒寫、寫 `2`、寫 `"1"`（字串）→ 拒，訊息點名；`web.app` 多一個 `idle` 之類不認得的鍵 → 拒。`exports` 的壞例子（不是清單、名字不合、重複）。
  JS 裡直接 `fetch(` → 報告有一筆提醒、**不擋**；fixture 的 `app.js` 沒有這筆提醒。升級多一個匯出＝紅。
- `kit.check_values` 與 `parse_args`：同一組輸入，錯誤訊息一樣；現有 `tests/test_packs.py`、`test_tools.py` 不改就過。
- 舊的 SYNOX 行為不變：沒有 `web.app` 的 pack，`summary_of`、tier、報告跟以前一模一樣（拿現有 fixture 比）。

驗收：上面全過；`python -m synox doctor --offline` 不變；`docs/pack-format.md` 的表格加 `web.app` 一列與一小節（規則、範例）；`docs/security.md` 五關表格的第 1、2 關各補一句。

### WP2 核心執行（管理員、每個 app 的站、登入、稽核、閒置）

新資料夾 `src/synox/web/apps/`：

| 檔 | 內容 |
|---|---|
| `__init__.py` | `install(app, config, ui) -> AppManager`：建管理員、`app.extras["synox_apps"] = manager`、`ui.apps = manager`；`app.on_start`：清狀態檔、登記 runtime 任務；`app.on_stop`：`stop_all(reason="SYNOX 結束")`。由 `web.install` 在建好 `ui` 之後呼叫 |
| `spec.py` | `AppSpec`（name、group、title、app_title、version、entry、root、reads、actions、files、pack）；`specs_of(app) -> (Dict[name, AppSpec], Dict[name, problem])`：從 `app.extras["synox_packs"]` 現算。核對：`reads` 每個都掛了函式；`actions` 每個都掛了函式、`registry.node(f"{group}.{name}")` 存在、`node.effect` 等於宣告；（第二版）`exports` 每個都掛了函式。任何一條不合 → 這個 app 進 `problems`、不能開 |
| `sessions.py` | `AppSessions`（記憶體：`create(tg_id) -> (sid, AppSession)`、`get(sid)`、`drop(sid)`、`drop_all()`；`AppSession` 有 `tg_id`、`csrf`、`created`；只存 sid 的 SHA-256，沿用 `tokens.digest`）；`ConfirmTickets`（`issue(session, action, values) -> token`、`redeem(session, action, values, token) -> bool`；一次性、60 秒、上限 200 張） |
| `audit.py` | `Audit(path, clock)`：`write(event, app, by=0, via="system", **kw)`、`tail(limit)`；格式與換檔照 C8 |
| `site.py` | `AppSite(manager, spec, port, *, clock)`：`handle()` 照 C4–C6。建構時 `snapshot = load_snapshot(spec, pack.locked_files)`：讀 `files` 進記憶體、有鎖就逐檔對 SHA-256，不符丟 `AppsError("檔案跟安裝時不一樣：<檔>")`；沒鎖（`packs.dirs` 開發用）照讀 |
| `listen.py` | `open_listener(site, port, *, bind_host=server.bind_host) -> Listener`：`srv = server._Server((bind_host(), port), server._Handler)`、`srv.daemon_threads = True`、`srv.ui = site`、開 `serve_forever` 的 daemon 執行緒；`Listener.port`、`Listener.close()`（照 `WebUI.stop` 的寫法在另一條執行緒 `shutdown()`＋`server_close()`）。**整個功能唯一會開埠的地方，越短越好** |
| `manager.py` | `AppManager`（下面） |
| `web_api.py` | `route(ui, user, method, path, data) -> Resp`：C7。給 WP4 接進 `server.py` |
| `testing.py` | `AppClient(manager, name)`：假瀏覽器（記 cookie、帶 CSRF、`Host` 自動帶對）。`enter(console_cookie=None, owner_nav=False)`、`get(path)`、`read(name, **params)`、`do(name, values, confirm=None)`、`do_confirmed(name, values)`（自動走兩步）、`raw(method, path, headers=, body=)`。`FakeListener`、`fake_listen`（記下被要求開的埠；可設定某個埠「被占用」丟 `OSError`）。給 SYNOX 自己與 SYNOX_Libs 的測試用 |

`AppManager`（`__init__(self, app, config, ui, *, listen=open_listener, clock=time.time)`）：

- `available() -> (bool, str)`：C1。
- `specs()`／`problems()`：包 `spec.specs_of`。
- `start(name, by, via) -> dict`：不可用／不是擁有者／沒有這個 app／有 `problem`／已達 `max_running` → `AppsError(code, message, status)`。已經開著 → 直接回現況。
  配埠：`data/apps.json` 記的那個；沒有就取範圍內還沒配給別人的第一個。`listen` 丟 `OSError` → 換範圍內下一個沒人用的再試，全部失敗 → `AppsError("port", …, 503)`，訊息說範圍與怎麼改設定。
  成功：存 `apps.json`、更新狀態檔、稽核 `start`、`reschedule` runtime 任務成 60 秒。
- `stop(name, by=0, via="system", reason="") -> bool`：關 listener、`site.sessions.drop_all()`、清確認票、狀態檔、稽核（`stop` 或 `auto_stop`）；都關了就 `reschedule(None)`。
- `stop_all(...)`、`keep(name, by, via)`（把 `last_used` 設成現在、清掉「已提醒」）、`touch(name)`（什麼時候叫：C11）、`views(user) -> dict`（C7）、`resolve(text) -> Optional[str]`（C9 的名字比對）。
- （第二版）`policy_of(name) -> dict`（C10：存過的，或預設）、`set_policy(name, data, by) -> dict`（檢查、存 `apps.json`、稽核 `policy`、`keep`；`blocked` 時先 `stop`）。`start` 遇到 `blocked` → `AppsError("blocked", …, 409)`。
- `tick()`（runtime 任務 `system.tool_apps`「工具服務」的 `fn`）：每個開著的 app 照**它自己的** `policy_of(name)`（C10 的表）：該關的 → `stop(via="system", reason="太久沒用")`＋`app.notify_owner("🧩 <標題>的服務 <N> 分鐘沒有用，我先關掉了。資料都在；要用再 /app_open <名>。")`；
  該提醒而且這一段閒置還沒提醒過 → 稽核 `suggest`、`notify_owner("🧩 <標題>的服務 <N> 分鐘沒有用了。要關：/app_close <名>。不理我的話再 <M> 分鐘我會自己關。")`（`suggest` 模式後半句換成「它會一直開著，直到你關掉或重開 SYNOX。想改成自動關，到 SYNOX 網頁的工具頁設定。」）；`keep` 什麼都不做。
  任務的狀態訊息：有開著的 → `running`「開著：記帳（8841，閒置 12 分）」；沒有 → `idle`。
- 該自動關的時機都要接上：`WebUI.turn_off()`（`/web_off`）→ `stop_all`；`WebUI._reload()`、`pack_remove`、升級（`_pack_upgrade`）之前 → 關那個工具（或全部，簡單為主）；健康檢查把某個工具隔離時 → 關它（看 `src/synox/health/` 的事件點；接不乾淨就在 `tick()` 裡檢查 spec 還在不在、不在就關）。

改 `src/synox/web/__init__.py`（呼叫 `apps.install`）、`src/synox/config.py`（C1 的預設與檢查）、`config.example.json`、`src/synox/web/server.py`（`turn_off`／`_reload`／移除／升級的掛鉤，各一兩行）。

測試 `tests/test_app_site.py`（用 `AppClient`、fixture `counter`、`no_sockets`）：

- Host：錯的主機名、錯的埠、沒有 Host → 403，內容沒有任何 app 的字。
- 進門：沒 cookie → 401 頁、有回主機台的連結；帶主機台的 session cookie → 200＋`Set-Cookie synox_app_counter`（HttpOnly、SameSite=Strict、沒有 Max-Age）；同一個請求帶 `Sec-Fetch-Mode: cors` → 不發；個人版本機導覽（三個 `Sec-Fetch-*`）→ 發擁有者的；`web.local_auto_login=false` → 不發；伺服器版看不到這個工具的成員帶自己的主機台 cookie → 401。
- API 不發登入：沒 app cookie、只有主機台 cookie 打 `/api/me`、`/api/read/state`、`/app.js` → 401。
- 來源：`Sec-Fetch-Site: same-site`／`cross-site` → 403；`Origin` 是別的埠 → 403；`Origin: null` 沒有 `same-origin` → 403、有 → 過。
- CSRF：POST 沒帶／帶錯／帶主機台的 csrf → 403；`Content-Type` 不是 JSON → 400。
- 標頭：每種回應（入口、靜態、JSON、401、403、404）都有 C4 第 3 點全部的標頭；**沒有任何 `Access-Control-` 開頭的標頭**；`OPTIONS` → 405。
- 靜態：`/app.js` 的位元組與 `Content-Type` 對；`/../pack.py`、`/%2e%2e/pack.py`、`/app/../../config.json`、`/pack.json` → 404；鎖裡的雜湊跟檔不一樣 → 開不起來、訊息點名那個檔。
- 讀：`/api/read/state` 回這個人的；伺服器版兩個人各自進門、互相看不到（真的保管箱，照 `tests/test_members.py` 的做法）。沒宣告的名字 → 404。
- 動作：`add` 成功後 store 的內容**跟用 `/counter_add 3` 打字的結果一樣**；`values` 有不認得的欄位、不是字串、太長 → 400；`n=abc` → 400 而且訊息等於指令那條的訊息；
  `reset`（危險）第一次 → 409＋票；帶票 → 成功；同一張票再用 → 409；票配別的參數／別的動作／別的登入 → 409；61 秒後 → 409。
  工具函式丟 `kit.AppError("沒有這筆")` → 409 `refused`＋那句話；丟別的例外 → 500、回應裡沒有例外訊息的細節。
- 權限：把節點設成擁有者限定，成員做動作 → 403（`authorize` 真的被叫到）。
- `/api/me`：形狀符合 C5；`csrf` 不等於主機台 session 的 csrf。
- `/api/leave`：之後同一個 cookie → 401。`/api/close-service`：成員 → 403；擁有者 → 200，之後 manager 說它關著。
- 稽核：進門、動作（含失敗）、被拒各有一行；整個檔案裡**找不到**動作的參數值（例如測試用的特殊字串）。
- （第二版）匯出（C6.1）：個人版沒帶票 → 409＋那段固定的字；帶票 → 200、`Content-Disposition: attachment`、內容對、標頭齊；票再用一次 → 409；
  `csrf` 欄位沒有／錯 → 403；`Sec-Fetch-Site: same-site` → 403；`Origin: null`＋`same-origin` → 過。**伺服器版 → 403 `export_encrypted_only`，而且工具的函式沒被叫到**（用計數器證明）。
  工具回的不是 `kit.Download`、`content_type` 不在白名單、檔名有 `../` 或中文 → 前兩個 500、檔名被清乾淨。稽核有 `export` 與 `bytes`，沒有內容與參數值。
- （第二版）有在用（C11）：`/api/alive` 第一次 → `last_used` 更新；30 秒後再一次 → 200 但**不更新**；61 秒後 → 更新。沒登入／沒 CSRF 的 alive → 401／403、不更新。
  被擋的請求（origin 錯）不更新。`/api/alive` 不寫稽核。`/api/me` 的 `exports`／`policy`／`alive_every_s` 形狀符合 C5。

測試 `tests/test_app_manager.py`（假 listener、假時鐘）：

- `web.apps.enabled=false`、`web.enabled=false`、`/web_off` 之後、假的容器環境（`bind_host` 回 `0.0.0.0`）→ `available()` False、`start` 拒、原因是白話。
- 不是擁有者 → 拒；沒宣告 app 的工具 → 404；宣告的危險程度跟指令不一樣的 fixture → `problems` 有它、開不了。
- `start` 兩次只開一次；埠寫進 `apps.json`、下次同一個；假 listener 說那個埠被占用 → 換下一個、`apps.json` 更新；全部被占用 → `AppsError("port")`。
- `max_running=1` 開第二個 → 409，訊息列出開著的那個。
- `open_listener`：把 `server._Server` 換成假的類別，確認拿到的位址是 `(bind_host(), port)`、`ui` 是 site、`daemon_threads` 是 True（**不真的綁**）。
- `stop`：site 的登入全部失效（關之前拿到的 cookie 再打 → 找不到 site／401）、狀態檔清掉、稽核有 `stop`。
- 閒置：假時鐘推 29 分 → 沒事；30 分 → `notify_owner` 被叫一次、稽核 `suggest`；再 tick → 不重複提醒；中間有請求（`touch`）→ 重新計時、之後會再提醒；`keep` 同理；120 分 → 關、稽核 `auto_stop`、通知一次。`idle_close_min=0` → 永不關；`idle_suggest_min=0` → 不提醒。
- （第二版）每個工具自己的設定（C10）：`auto` 30 → 29 分沒事、30 分直接關、**沒有先提醒**；`auto` 45 → 30 分提醒、45 分關；`suggest` → 30 分提醒一次、之後怎麼推都不關；
  `keep` 沒帶 `understood` → 400，帶了 → 永不提醒不關；`blocked` → 開著的被關、`start` 回 409 `blocked`；`close_min` 是 4、1441、小數、字串 → 400。
  兩個工具不同設定同時開著，各走各的。成員改設定 → 403。改設定寫稽核 `policy`、存進 `apps.json`、重開（新的 `AppManager`）讀得回來。
  `keep` 的工具在新的 `AppManager` 裡**不是開著的**。沒存過設定的工具 `policy.default` 是 true、數字來自設定檔。
- （第二版）**沒宣告 `web.app` 的工具沒有表面**：拿 repo 裡現成沒有 app 的 fixture pack：不在 `specs()`／`problems()`、不在 `views()`、`start` → 404、`set_policy` → 404、假 listener 沒被叫過。
- 一個都沒開時 runtime 任務沒有排程（`task.next_due is None`）；開一個之後有；全關之後又沒有。
- `turn_off()`、重新載入、移除工具 → 那個（或全部）服務關掉。
- 啟動時狀態檔被寫成空的；`on_stop` 全關。

驗收：上面全過；整個 repo 搜尋 `ThreadingHTTPServer(`、`_Server(`、`.bind(`、`.listen(`，**新增的只有 `listen.py` 裡那一個 `_Server(`**；`docs/AGENT.md` 加 invariant 23（「工具服務的埠只能由 `web/apps/listen.py` 開、只綁 `bind_host()`；app 的每個請求照 C4 檢查；動作一定對到同名指令的葉節點」）與 Map 的一列。

### WP3 共用元件（`appkit.js`、`appkit.css`；不依賴其他工作包，照合約寫）

檔案：`src/synox/web/static/appkit.js`、`src/synox/web/static/appkit.css`、`tests/js/test_appkit.js`、`tests/test_appkit.py`（照 `tests/test_control_panel.py` 怎麼用 node 跑 `tests/js/test_control.js` 的方式；沒有 node 就 skip）。

`appkit.js`（IIFE、`"use strict"`、不用 `innerHTML`、不用 `eval`、**不做任何定時的網路請求**；檔頭一張 `TEXT`）對外只有 `window.SynoxApp`：

| 函式 | 行為 |
|---|---|
| `ready(fn)` | 抓 `/api/me` → 存起來 → 畫頁首列 → `fn(ctx)`；`ctx = {me, app, actions, reads}` |
| `read(name, params)` | GET `/api/read/<name>`＋查詢參數 → resolve `data`；失敗 reject `{code, error}` 並 `toast(error)` |
| `act(name, values, opts)` | 值全部轉成字串（`null`／`undefined`／空字串的欄位不送）→ POST `/api/do/<name>`。收到 `confirm` → `confirmBox(confirm.text)`，按確定帶票重送一次；按取消 reject `{code: "cancelled"}`（不 toast）。`invalid` → reject，`fields` 給呼叫端標在表單上。`opts.quiet` 不 toast |
| `form(actionName, opts)` | 照 `actions[name].fields` 產生表單（label 用 `label`、`required`、`kind` 決定 input 型別、`choices` 變下拉）；送出＝`act`；欄位錯誤顯示在欄位下面。`opts.values` 預填、`opts.submitText`、`opts.onDone(data)` |
| `toast(text, tone)`、`confirmBox(text) -> Promise<boolean>`、`el(tag, cls, text)`、`clear(node)`、`fmt.number(n)`、`fmt.date(iso)` | 小工具 |
| `keep()` | POST `/api/keep` |
| `download(name, params)`（第二版） | 匯出，流程照 C6.1：`me.exports[name].available` 是 false → 只顯示 `reason`、不送請求；否則先拿確認的字 → `confirmBox`（按鈕字用回應的 `button`）→ 用看不見的表單送出。resolve 在表單送出之後（瀏覽器接手存檔，這裡不知道存好了沒） |

（第二版）**「人還在」的訊號**（C11）：kit 載入後自己掛那六種事件的監聽，條件與節流照 C11；工具不用叫、也沒有對外的函式可以叫。
`read`／`act` 成功時順便把「上次送出時間」設成現在（已經有真的請求了，不用再送 alive）。

- 頁首列（kit 自己畫，插在 `<body>` 最前面）：`app.title`、登入的人、連結「回 SYNOX」（`console_url`，`rel="noopener noreferrer"`）、「離開」（`/api/leave`）、擁有者才有的「關閉服務」（`confirmBox` 之後 `/api/close-service`）、小字「這是 SYNOX 在這台電腦上開的工具畫面，不用的時候可以關掉。」
- 請求一律 `credentials: "same-origin"`、POST 帶 `X-SYNOX-CSRF` 與 `Content-Type: application/json`。
- 網路失敗（連不上）或 401：蓋一層遮罩。連不上：「這個服務已經關了。回 SYNOX 再開一次就好，資料都在。」；401：「要重新進來一次。」各附回主機台的連結。**表單裡打到一半的字不清掉。**
- `appkit.css`：`:root` 的顏色 token 抄主機台 `app.html` 的那一組（`--bg --surface --line --text --muted --accent --ok --warn --bad` 與深色版；`prefers-color-scheme`）；基本元件 `.bar`（頁首列）、`.card`、`.btn`（`.primary`、`.danger`、`.ghost`）、`.field`、`.badge`（`.read .write .danger`）、`.table`、`.toast`、`.modal`、`.mask`、`.tabs`、`.meter`（比例條）；手機寬度不橫向捲；只用系統字型；沒有 `url()`、沒有 `@import`。

`tests/js/test_appkit.js`（照現有四個測試的做法自備最小的假 DOM 與假 `fetch`）：

- `act`：值變字串、空欄位不送、帶 CSRF 標頭；409 confirm → 叫確認框 → 確定後帶票重送、取消後 reject `cancelled` 而且沒有第二個請求；`invalid` 把 `fields` 交回。
- `read`：參數正確編碼（中文、`&`）。
- 連不上 → 出現遮罩、文字對；401 → 另一種文字。
- `form`：必填、`choices`、欄位錯誤顯示在對的欄位。
- （第二版）人還在：假 DOM 發一個 `isTrusted: true` 的 `mousemove`、`visibilityState` 是 `visible`、假時鐘離上次 61 秒 → 送一次 `POST /api/alive`（帶 CSRF）；
  馬上再發十個事件 → 沒有第二個請求；`visibilityState` 是 `hidden` → 不送；`isTrusted: false` → 不送；完全沒有事件、時鐘推一小時 → **一個請求都沒有**；
  剛 `read` 成功過 30 秒內的事件 → 不送；alive 失敗 → 沒有遮罩、沒有 toast、不重試。
- （第二版）`download`：`available: false` → 沒有任何請求、顯示 `reason`；可用 → 第一個請求是表單格式且沒有票，確認框顯示伺服器給的字，按下載後建立的表單有 `csrf`、`confirm` 與參數、`method` 是 post；按取消 → 沒有表單。
- 檔案裡沒有 `setInterval`、`innerHTML`、`eval`、`http://`、`https://`（`tests/test_appkit.py` 直接讀檔檢查；CSS 沒有 `url(`、`@import`）。
- 兩個檔都過 WP1 的 `appscan` 文字規則（對外網址那幾條）。

驗收：測試過；`appkit.js` ≤ 600 行、`appkit.css` ≤ 400 行（提案值；超過先回報再說）。

### WP4 主機台畫面與 API（等 WP2）

檔案：`src/synox/web/server.py`（`api()` 開頭把 `/api/apps` 前綴轉給 `apps.web_api.route`，寫法照 `/api/runtime/` 那三行：`:529-532`）、
`src/synox/web/static/apps.js`＋`apps.css`（新；用 `INCLUDES`／`<!-- include: … -->` 的機制放進 `app.html`，`server.py:148-173`）、`src/synox/web/static/app.html`（側欄一個標記的掛點、工具頁卡片的掛點）、
`src/synox/web/static/tools.js`（`renderTool` 裡在面板旁邊叫 `SynoxApps.card(panel, tool)`；`server.py` 的 `tools()` 每個工具多回 `"app": true/false`）、`tests/js/test_apps.js`、`tests/test_app_console.py`、`docs/runtime-api.md`（或新 `docs/apps-api.md`：C4–C8 的合約，之後要改先改文件）。

畫面：

1. **側欄常駐標記**（`#side-foot` 上方）：`running > 0` 才顯示「● N 個工具服務開著」（有 `suggest_close` 的時候用提醒色、字變成「● 記帳的服務很久沒用了」）。點了開一個小清單：每個開著的一列（標題、開多久、多久沒用、「打開」「關掉」）、底下「全部關掉」「這是什麼？」。
2. **工具頁的卡片**（有 app 的工具才有，放在說明與指令之間）：標題「完整畫面」。關著：一句 `explain.what`＋按鈕「開啟並打開」；開著：狀態徽章「開著 · 12 分鐘沒用」＋「打開」「關掉」「先留著」（只有 `suggest_close` 時）；`error`／`problem`：原因＋下一步。底下可展開「這是什麼？為什麼要關？」（三句說明）與「最近紀錄」（`/api/apps/log` 前 5 筆，白話：「10:20 你開了記帳的服務」）。不是擁有者：只有「打開」（開著時）與一句「服務由擁有者開關」。
2a. （第二版）**卡片上的閒置設定**（C10；ADR §4.2 的表與字）：一行現況「沒在用的時候：<policy.text>」，每個看得到的人都看得到；擁有者旁邊有「改」→ 六個選項的單選
   （120 分鐘〔建議〕／30 分鐘／自己填 N／只提醒／一直開著／不開放），「自己填」有一個數字欄（5–1440）。選「一直開著」先跳警告、按「我知道，一直開著」才送（帶 `understood: true`）；
   之後卡片與側欄清單上那個工具一直帶一個提醒色的「一直開著」標籤。選「不開放」而它正開著 → 先問「會先把它關掉，確定？」。
   「什麼叫有在用」的那句白話（ADR「給使用者的說法」）放在設定旁邊的說明裡。
3. **第一次開**：`explained` 是 false 時先出一個對話框（三句說明）＋「知道了，開啟」／「先不要」；按了才送 `start`（請求帶 `{"explained": true}`，伺服器記進 `apps.json`）。
4. 「打開」一律 `window.open(url, "_blank", "noopener,noreferrer")`。
5. 更新：進到工具頁、按任何按鈕之後、以及頁面看得到時每 30 秒抓一次 `GET /api/apps`（`document.hidden` 時不抓）。
6. 主控頁：不用另外做，`system.tool_apps` 會自己出現在任務清單。

測試 `tests/test_app_console.py`（用 `tests/test_web.py` 的 `Client`＋假 listener）：C7 每條路由的權限（成員 `start`／`stop`／`log` → 403；成員的清單沒有 `can_manage`、看不到自己看不到的工具）、CSRF、`start` 的四種錯誤碼、`explained` 只記一次、`/api/tools` 的 `app` 欄位、清單形狀符合 C7、`log` 的上限。
`tests/js/test_apps.js`：三種狀態的卡片、不是擁有者的樣子、第一次的對話框、`window.open` 帶 `noopener`、`document.hidden` 不輪詢、字串都在 `TEXT`。
（第二版）`test_app_console.py` 加：`/policy` 的權限與每種 `mode`（含 `keep` 沒帶 `understood`）、成員的清單裡有 `policy` 但改不了、`blocked` 之後 `start` 的錯誤碼。
`test_apps.js` 加：六個選項、「一直開著」的警告流程（沒按確認不送請求）、「不開放」時沒有開啟的按鈕、成員只看得到現況那一行、`blocked` 的工具卡片的樣子。

驗收：測試過；`render_app()` 產生的頁面仍只有 nonce 的 script／style（現有 `test_web.py` 的 CSP 測試不改就過）；主流程的字裡沒有 port、session、CSRF（寫一個讀 `apps.js` `TEXT` 的測試）。

### WP5 Telegram 指令、提醒、doctor（等 WP2）

檔案：`src/synox/web/apps/commands.py`（新，由 `apps.install` 呼叫）、`src/synox/doctor.py`、`tests/test_app_commands.py`、`docs/tools.md`（指令一覽加一段）。

- 指令照 C9。`/apps`、`/app_close` 給 AI（`effect` 分別 READ／WRITE）；`/app_open` `ai=False`、`owner_only=True`、`private_only=True`。
- 回覆的字照 ADR「給使用者的說法」；功能不可用時說原因；`/app_open` 成功的訊息一定有「只有跑 SYNOX 的這台電腦打得開」與怎麼關。
- 閒置提醒的兩則訊息在 WP2 的 `tick()`（純文字附指令）。這包可以加碼：若 SDK 的按鈕好接（看 `vendor/isdtelekit` 的 callback 用法與 `server.py:740-760` 的 `press`），在提醒下面加「關掉」「先留著」兩顆；接不乾淨就不做，驗收以純文字為準。
- `doctor`：在「網頁介面」那行下面多一行 `工具服務：開放（埠 8841–8848，最多同時 3 個；30 分鐘沒用提醒、120 分鐘自動關）`／`關（web.apps.enabled=false）`；再讀 `data/apps_state.json`：
  `running` 不是空的 →「上次紀錄：記帳開在 8841（由程序 1234 寫的；SYNOX 沒在跑的話這些都已經關了）」。**doctor 不連任何埠。** 有 app 宣告掛不起來的（`problems`）列成 ⚠️。

（第二版）`/apps` 每行帶閒置設定；`blocked` 的工具 `/app_open` 回 C9 那句；doctor 那一行的閒置數字改寫成「預設：30 分鐘沒用提醒、120 分鐘自動關；各工具可以自己設」，
有工具設成「一直開著」時多一行 ⚠️ 列出是哪幾個。

測試：三個指令在個人版／伺服器版成員／擁有者的結果；群組裡打 `/app_open` 被擋；AI 的工具清單裡有 `apps`、`app_close`、沒有 `app_open`（照 `tests/test_agent.py` 怎麼看工具清單）；名字比對（`money`、`記帳`、`💰 記帳`、`記帳本`、大小寫）；`all`；不存在的名字列出有哪些；doctor 的三種輸出（用假的狀態檔）。

驗收：測試過；`/help` 多一頁「🧩 工具服務」而且三個指令的說明是白話。

### WP6 SDK 與文件（等 WP1、WP3）

- `src/synox/sdk/author.py`：`SDK_VERSION = "0.2.3"`；重產單檔版（`scripts/build_synox_sdk.py`，測試會比對兩份）。`docs/sdk.md`「SDK 版本」補一句 0.2.3 加了什麼。
- `src/synox/sdk/__init__.py`：`synox-sdk init <資料夾> --kind python --app`：多產生 `app/index.html`（載入 kit、一個 `<main id="app">`）、`app/app.js`（`SynoxApp.ready` 之後讀一次、畫一張表、一個 `SynoxApp.form`）、`app/app.css`（空殼）、`pack.json` 的 `web.app`，`pack.py` 範本多一組「核心函式＋指令＋`app_read`／`app_action`」。**不加 `--app` 時產生的東西跟現在一模一樣。**（0022 決定 23 說範本不再預設產生面板，那是另一件事，這包不動它。）
- `synox-sdk check`：自然會跑到 WP1 的規則；確認錯誤訊息從這條路出得來。
- 文件：新 `docs/tool-apps.md`（給寫工具的人：三分鐘範例、`web.app` 每個欄位、`app_read`／`app_action`／`AppError`／`check_values`、kit 的每個函式、怎麼用 `AppClient` 寫測試、能做與不能做的事（不能連外、不能內嵌程式、不能輪詢）、畫面上的字怎麼寫）；
  `docs/pack-format.md`（連過去）；`docs/security.md`「網頁介面」加一節「工具服務」（ADR §3 的對策表與「擋不住的」，白話）＋「沒有做的保護」加兩條；`README.md` 功能清單一行；`CHANGELOG.md`；`docs/AGENT.md` Map。
- （第二版）`docs/tool-apps.md` 另外要有：`kit` 欄位與「框架是宣告來選用的，沒宣告就沒有 app 這一面；框架在 SYNOX 不在工具裡，為什麼」（ADR §5）；`app_export`／`kit.Download` 與匯出的規則（個人版先講清楚、多人版不給沒加密的、工具不要自己做下載）；
  「有在用」的定義與「不要自己送 alive、不要自己用 `fetch`」；範本（`init --app`）產生的 `pack.json` 帶 `"kit": 1`、不帶 `exports`。
- **不做**：`synox-sdk` 的本機預覽伺服器（會開埠）。

測試 `tests/test_sdk_app.py`：`init --app` 產生的資料夾過第 1、2 關、`specs_of` 沒有 problem、用 `AppClient` 能進門、讀、做一個動作；不加 `--app` 的輸出跟基準的雜湊一樣（或逐檔比對）；單檔版與正本一致。

驗收：測試過；文件裡的範例程式就是測試裡跑的那一份（照 `tests/test_pack_docs.py` 的做法，若它有檢查文件範例的機制就接上）。

### WP7 記帳 app（SYNOX_Libs；等 WP1–3、6 合進 SYNOX 的 `feat/tool-apps`）

照 SYNOX_Libs 分支 `feat/tool-apps` 的 `docs/adr/0003-tool-apps-and-money-app.md`。測試時 `SYNOX_HOME` 指到 SYNOX 的這個工作樹（`scripts/_synox.py` 的規則），只 import、不改它。

---

## 9. 只有擁有者能做的驗收（別台電腦、真的瀏覽器；開發機不做）

每項：做什麼 → 預期。失敗就把畫面與 `data/apps_audit.jsonl` 最後幾行帶回來。

| # | 做什麼 | 預期 |
|---|---|---|
| R1 | 主機台工具頁按「開啟並打開」 | 先看到三句說明；按了之後新分頁是記帳畫面，頁首有工具名與「關閉服務」 |
| R2 | 另一台電腦／手機連 `http://<這台的區網 IP>:8841/` | 連不上 |
| R3 | 在 app 分頁按 F12，主控台執行 `fetch("http://127.0.0.1:8830/api/me", {credentials: "include"}).then(r => r.status)` | 被瀏覽器擋（CORS 錯誤），或 403；**拿不到內容** |
| R4 | 同上 `fetch("http://127.0.0.1:8830/api/packs/reload", {method: "POST", credentials: "include"})` | 403 或被擋；主機台沒有重新載入 |
| R5 | 開兩個 app，在 A 的主控台打 B 的 `/api/read/…` | 403 或被擋 |
| R6 | 記一筆、改一筆、刪一筆（刪要按確認） | Telegram `/money_list` 看得到同樣的結果；反過來在 Telegram 記的，畫面重新整理看得到 |
| R7 | 按「關閉服務」，再重新整理 app 分頁 | 連不上；主機台標記消失；用 `netstat -ano` 找 8841，沒有東西在聽 |
| R8 | 開著不動 30 分鐘（或把設定改成 1 分鐘與 3 分鐘） | 收到一則提醒；再過去自動關、收到一則通知 |
| R9 | 重開 SYNOX | 所有服務都是關的 |
| R10 | 把記帳的網址加書籤，服務開著時從書籤進 | 直接進（個人版）；服務關著時瀏覽器說連不上 |
| R11（選做） | 瀏覽器開 `http://money.localhost:8841/` | 記下「打得開／打不開」與瀏覽器名稱版本（ADR 要擁有者決定的第 4 題要用） |
| R12 | 用 Edge 與 Chrome 各做一次 R1、R3、R6 | 一樣 |
| R13（第二版） | 把記帳設成「自己填 3 分鐘」。開著 app 分頁、切到別的分頁放 4 分鐘 | 服務被關（背景的分頁不算在用） |
| R14（第二版） | 同樣設定，app 分頁留在眼前，每分鐘動一下滑鼠，共 5 分鐘 | 服務沒被關；主機台的「多久沒用」一直很小 |
| R15（第二版） | 同樣設定，app 分頁留在眼前但完全不碰滑鼠鍵盤 4 分鐘 | 服務被關 |
| R16（第二版） | 設成「一直開著」 | 先看到警告；之後卡片一直有「一直開著」的標籤；重開 SYNOX 後它是關的 |
| R17（第二版） | 個人版在記帳的帳目頁按「匯出」 | 先看到「沒有加密」那段字；按下載後瀏覽器存了一個 `.csv`，頁面沒有跳走；Excel 打開中文沒有亂碼 |
| R18（第二版） | 另開一份伺服器版的設定做同一件事 | 按鈕是灰的、有一句說明；沒有檔案被下載 |

## 選項表（實作中遇到要選的；預設照建議，不用回頭問）

| 題目 | 選項 | 建議（預設做這個） |
|---|---|---|
| 重新載入工具時 | 只關那一個／全部關 | **全部關**（簡單、安全；訊息說明原因） |
| 提醒用按鈕還是文字 | 兩顆按鈕／純文字附指令 | **純文字**；按鈕是加碼 |
| 稽核紀錄要不要進保管箱 | 明文 JSONL、不記內容／加密 | **明文、不記內容**（要能在 SYNOX 沒開時用記事本看） |
| app 的靜態檔要不要登入 | 要／不要 | **要**（沒登入什麼都拿不到） |

（第二版）擁有者已經回答的在 ADR 0023「擁有者已經決定的」；**還沒定的兩題**（AI 能不能開服務、伺服器版加密匯出的格式）照 ADR「現在先這樣」那一欄做：
`/app_open` 不給 AI；伺服器版的匯出一律擋。這兩題不要自己往前做。

## 驗收（整體）

- 八個工作包（WP0–WP7）各自的驗收都過；全部測試（加上面那個 `--deselect`）過；新增的測試沒有任何一個真的開埠。
- `git grep -n "_Server(" src/` 只有 `server.py` 原本那一處與 `web/apps/listen.py`。
- 沒有宣告 `web.app` 的工具：安裝報告、信任層級、工具頁、`/help` 跟合併前一模一樣。
- 給使用者看的每一句新字都在某個 `TEXT` 表裡，主流程沒有 port、session、CSRF、origin。
- ADR 0023 的狀態改成「已採用」並補上實際的分支與 commit；這份計畫的狀態改成「已修」＋ merge commit。

## 不要做的事

- 不要在這台電腦開埠、跑伺服器、開瀏覽器、動防火牆；不要為了「驗一下」而破例。
- 不要改 `vendor/`、不要改 `web.panel`／`web.api` 的行為、不要改三份教學頁。
- 不要加 CORS、不要加 `'unsafe-inline'`、不要讓 `config.json` 決定綁哪個位址、不要讓工具自己開伺服器。
- 不要把動作的參數值寫進稽核或 log。
- 不要做容器版、`*.localhost`、WebSocket、kind=cli 的 app、開機自動開服務、在 Telegram 改閒置設定——都在 ADR 的「不做」。
- 不要做伺服器版的加密匯出（格式還沒定）、不要讓 AI 開服務（還沒定）、不要做任何「人不在電腦前也連得到」的東西（通道、雲端轉送；那是另一份 ADR）。
- 不要讓工具在 `pack.json` 裡替自己選閒置設定；不要在共用元件裡放計時器去送請求。
- 不要合併、不要推；不要改這份計畫的合約而不回報。
