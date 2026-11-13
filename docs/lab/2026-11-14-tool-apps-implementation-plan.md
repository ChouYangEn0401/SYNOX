# 工具服務（每個工具自己的完整網頁）：實作計畫

- 狀態：**待處理**（提案；[ADR 0023](../adr/0023-tool-apps-services.md) 等擁有者核准。核准前不動 `src/`；核准後照下面的工作包做）
- 寫的時間：2026-11-14（分支 `feat/tool-apps`，基準 `dev` 的 `b5f48e2`）。**這是第三版，整份重寫過**；前兩版在 git 歷史裡，不要照舊版做。
- 讀者：實作的代理（每個工作包一個，手上只有這份文件與 repo）。行號都是基準 commit 的。
- 工具那一側（記帳 app）：SYNOX_Libs 的 `docs/adr/0003-tool-apps-and-money-app.md`（工作包 7）。

## 版本紀錄

| 版 | 改了什麼 |
|---|---|
| 一 | 初版 |
| 二 | 擁有者的回覆：閒置設定每個工具自己選（C10）、「有在用」的定義（C11）、匯出（C6.1）、`kit` 版本欄位（C2） |
| **三** | 獨立安全審查九項（ADR「第三版：安全審查的九項」）。**進門方式整個換掉**：app 綁 `127.0.0.2`、不用 cookie、只能用主機台發的一次性交接票進、登入 token 放在分頁裡用標頭帶（C4、C5、C7）；確認不再存票（C6）；`/app_open` 擋排程（C9）；鎖與同步關閉（C12）；稽核沒有自由文字、log 沒有例外訊息（C8）；`kit.csv_bytes`（C3）；安裝檢查只擋 HTML 結構（WP1）；上線前的實測關卡 G1（第 9 節） |

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
- 主機台的綁定：`HOST`（`:63`）、`bind_host()`（`:187-207`）、`_Server`（`:1721-1732`，Windows 獨佔）。**主機台這邊一個字都不改。**
- 主機台現有的防護：session cookie `synox_session`（HttpOnly、SameSite=Lax、`Path=/`：`:371`、`:486`）、`_csrf_problem`（`:374-382`）、表單送出的來源判斷（`login_post`，`:453-463`）。
- 面板：`web.panel`／`web.api`（`manifest.py:362-389`、`loader.py:196-201`、`server.py:504-514`、`:883-891`）。**不要改它**。
- 指令：`kit.command`（`kit.py:172-193`）把 `fields` 掛在葉節點；檢查在 `kit.parse_args`（`:133-169`）。危險程度 `node.effect`（`read`／`write`／`danger`）。權限 `app.registry.authorize(user, node, via, chat_id)`（已經接上 `policy.decide`）。
  `interactive=True` 的節點在排程、例行、AI 三條路都被擋（`vendor/isdtelekit/core/registry.py:444`）。
- 背景工作只能登記成 runtime 任務（AGENT.md invariant 18；範例 `runtime/keepawake.py` 的 `register`／`reschedule`）。
- 測試的假瀏覽器：`tests/test_web.py` 的 `Client`（`:38-80`）。JS 單元測試：`tests/js/*.js` 由 pytest 用 node 跑。
- **三件一定要記得的事**（ADR §3.1）：（1）瀏覽器的 cookie 只看主機、不看埠；（2）本機的埠誰都可以去聽；（3）工具的畫面程式跟共用元件在同一頁，畫面那一側的東西它都能跳過。
  下面的每一條檢查都是為了這三件事，不能省，也不要「順手」把 cookie 加回 app 的埠。

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
6. `vendor/` 不改。給使用者看的字是白話繁體中文、一個檔一張字串表（JS 檔開頭 `var TEXT = {…}`、Python 模組 `TEXT = {…}`）；主流程的字不出現 port、session、token、CSRF、origin。
7. repo 裡不寫真名、帳號、本機絕對路徑、Telegram id（invariant 8）。
8. 合約（下一節）是工作包之間的介面：**不要自己改名字或形狀**；覺得合約有問題，停下來回報。
9. log 與稽核：**不寫參數的值、不寫 token 與票、不寫例外的訊息**（C8）。

---

## 合約（所有工作包共用）

### C1 設定與位址

```json
"web": { "enabled": true, "port": 8830, "public_url": "",
         "apps": { "enabled": true, "port_first": 8841, "port_count": 16, "max_running": 3,
                   "idle_suggest_min": 30, "idle_close_min": 120 } }
```

| 欄位 | 規則（不合＝`ConfigError`，一句白話） |
|---|---|
| `enabled` | 布林，預設 true。true 也**不會自己開任何服務**；只是允許擁有者開 |
| `port_first`／`port_count` | 1024–65000／1–40；範圍不能包含 `web.port` |
| `max_running` | 1–`port_count` |
| `idle_suggest_min`／`idle_close_min` | 0–1440；0＝不提醒／不自動關；兩個都不是 0 時 `idle_close_min` 要大於 `idle_suggest_min`。只是「擁有者還沒替它選過的工具」用的預設（C10） |

**位址**：主機台 `http://127.0.0.1:<web.port>`（不變）；app `http://127.0.0.2:<埠>`。`APP_HOST = "127.0.0.2"` 是 `web/apps/listen.py` 裡的常數：
不從 `config.json` 讀、沒有環境變數可以改、不經 `bind_host()`、永遠不會是 `0.0.0.0`。**設定裡沒有任何欄位能改 app 綁在哪。**

功能不可用（`AppManager.available()` 回 `(False, 原因)`，任何「開啟」都拒）：`web.enabled` 是 false、`web.apps.enabled` 是 false、`/web_off` 之後、
**在容器裡**（環境變數 `SYNOX_IN_CONTAINER` 是 `1`，或 `server.CONTAINER_MARKERS` 任一個存在；`exists` 可以注入給測試——**不要**用 `bind_host()` 的結果判斷）→「容器版還沒開放工具服務」。

### C2 `pack.json` 的 `web.app`

```json
"web": { "app": { "entry": "app/index.html", "root": "app", "title": "記帳本", "kit": 1,
                  "reads": ["month", "entries"], "actions": { "add": "WRITE", "rm": "DANGER" },
                  "exports": ["entries_csv"] } }
```

解析後放在 `Manifest.web["app"]`：沒有宣告＝`None`；有＝
`{"entry": "app/index.html", "root": "app", "title": "記帳本", "kit": 1, "reads": ["month", "entries"], "actions": {"add": "write", "rm": "danger"}, "exports": ["entries_csv"], "files": ["app/app.js", "app/index.html", …]}`
（`files`＝`root` 底下全部檔的相對路徑，正斜線、排序過）。規則見工作包 1。

- `kit`：必填的整數，這個 app 照哪一版共用元件寫的；現在只收 `1`（常數 `KIT_VERSIONS = (1,)`）。`exports`：選填。
- **沒有 `web.app` 的工具沒有任何 app 表面**：不在 `specs()`、不在 `GET /api/apps` 的清單、`start` 回 404、沒有任何埠與路由——工作包 2 有測試鎖住。
- 工具不能在宣告裡替自己選閒置設定（沒有這種欄位；多寫的鍵在安裝時＝拒）。

### C3 工具端的 Python 介面（SDK 0.2.3 新增，只加不改）

```python
pack.app_read(name: str, fn)                       # fn(user, params: Dict[str, str]) -> 可轉 JSON 的東西
pack.app_action(name: str, fn, *, describe=None)   # fn(user, values: Dict[str, str]) -> dict
                                                   # describe(user, values) -> str：危險動作確認框的那一句（選填）
pack.app_export(name: str, fn)                     # fn(user, params: Dict[str, str]) -> kit.Download
kit.check_values(fields, values) -> (clean: Dict[str, str], missing: List[Field], errors: List[str])
kit.AppError(message: str, code: str = "refused", status: int = 409)   # fn 裡丟：照 message 回給畫面
kit.Download(filename: str, content_type: str, data: bytes)            # 一個要給使用者存下來的檔
kit.csv_bytes(header: Sequence[str], rows: Iterable[Sequence]) -> bytes   # （第三版）見下
```

- 名字沒寫在 `web.app.reads`／`actions`／`exports` 裡就掛 → `ValueError`（跟 `web_route` 一樣）。存放：`pack.app_reads: Dict[str, Callable]`、`pack.app_actions`、`pack.app_describe`、`pack.app_exports`。
- `kit.check_values`：對**已經照名字放好的** `values` 做 `kit.parse_args` 後半段那些事（`choices`、`check`、補 `default`、找缺的必填）。`parse_args` 改成「切字 → 叫 `check_values`」，行為與訊息一個字都不變（現有測試不改就要過）。
- `kit.csv_bytes`：UTF-8、開頭 BOM、CRLF、用標準函式庫 `csv` 的引號規則。每個儲存格：`int`／`float` 原樣寫（不加千分位）；`None` 寫空的；字串開頭是 `=`、`+`、`-`、`@`、Tab、CR、LF 的前面加一個 `'`（防試算表公式）。
  **每個工具的 CSV 都用它，不要自己組**（審查發現 8）。
- `kit.AppError` 的 `message` 會原樣顯示給使用者，所以它是工具寫給人看的一句話；**別的例外的訊息永遠不會出現在回應、log、稽核裡**（C8）。
- 工具要相容舊的 SYNOX：`if hasattr(pack, "app_read"): …`（同 money 現在對 `web_route` 的寫法）。

### C4 app 埠上的路由（`AppSite.handle(method, target, headers, body) -> (status, headers, body)`）

**app 的埠不讀任何 cookie、不發任何 `Set-Cookie`。** 登入是一個 token：`POST /api/enter` 用交接票換來，之後每個 `/api/` 請求放在 `X-SYNOX-App` 標頭（匯出那一條放在表單欄位 `t`）。

每個請求依序（任何一條不過就回、不往下）：

1. `Host` 不是 `127.0.0.2:<埠>`（完全相等，不收 `localhost`、不收 `127.0.0.1`）→ 403 純文字（不洩漏任何東西）。
2. 帶了 `Forwarded`、`Via`、或任何 `X-Forwarded-` 開頭的標頭 → 403（有人把它放到代理後面）。帶了 `Service-Worker` 標頭 → 403。
3. 方法只收 GET、POST；其他（含 `OPTIONS`）405。
4. 每個回應都帶 `BASE_HEADERS`＋`X-Frame-Options: DENY`＋`Cross-Origin-Opener-Policy: same-origin`＋`Cross-Origin-Resource-Policy: same-origin`＋
   `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; worker-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'`。
   **任何回應都沒有 `Access-Control-*`、沒有 `Set-Cookie`。**

| 路由 | 要登入 | 做什麼 |
|---|---|---|
| `GET /` | 不用 | 入口頁（`entry` 的位元組，`text/html; charset=utf-8`）。查詢字串一律忽略。**每次開啟服務之後的第一個** `GET /` 回應多帶 `Clear-Site-Data: "storage"`（`AppSite` 一個旗標，送過就不再送） |
| `GET /_synox/kit.js`、`/_synox/kit.css` | 不用 | SYNOX 的共用元件（`src/synox/web/static/appkit.js`、`appkit.css`）。`kit.js` 送出前把 `/*{{CONSOLE_URL}}*/` 換成主機台的網址（工作包 3「啟動」第 3 點） |
| `GET /<root 底下的相對路徑>` | 不用 | 記憶體快照裡的那個檔；`Content-Type` 照副檔名白名單；查不到 404 |
| `POST /api/enter` | 交接票 | 見下 |
| `GET /api/me` | 要 | C5 |
| `GET /api/read/<name>?k=v` | 要 | `{"ok": true, "data": fn(user, params)}`；`params` 每個鍵取第一個值 |
| `POST /api/do/<name>` | 要 | C6 |
| `POST /api/export/<name>` | 要（表單欄位 `t`） | C6.1 |
| `POST /api/alive` | 要 | 「人還在」：C11。回 `{"ok": true}`；不記稽核 |
| `POST /api/keep` | 要 | 「先留著」：`manager.keep(name)` → `{"ok": true}` |
| `POST /api/leave` | 要 | 作廢這個登入 → `{"ok": true}` |
| `POST /api/close-service` | 要＋擁有者 | 先回 `{"ok": true}`，再用 `app.tasks.run` 在別的執行緒叫 `manager.stop(name, by=user, via="app")`（請求的執行緒不能自己關自己的伺服器） |

靜態的三種（`GET /`、`/_synox/*`、`root` 的檔）是公開的：它們就是工具附的檔，沒有任何人的資料。**所有 `/api/` 路由**另外要過：

- 帶了 `Sec-Fetch-Site` 而且不是 `same-origin` → 403 `code: "origin"`。
- 帶了 `Origin`：netloc 要等於 `Host`；`Origin: null` 只有在 `Sec-Fetch-Site: same-origin` 時放行。否則 403 `code: "origin"`。
- POST（匯出除外）：`Content-Type` 要以 `application/json` 開頭、內容是 JSON 物件，否則 400。
- 被拒絕的請求（host／代理／origin）寫一行稽核 `denied`（同一個原因碼每分鐘最多一行）。

**`POST /api/enter`**，內容 `{"ticket": "…"}`：`manager.redeem_ticket(name, port, ticket)`（C7、C12：查與用掉在同一把鎖裡）→ 得到 `(tg_id, console_digest)`，否則 401 `code: "login"`。
再查這個人現在看得到這個工具（`registry.visible(user, group)`），否則 401。過了 → 建一個 app 登入、回 `{"ok": true, "token": "<256 bit 隨機>", "me": <C5 的內容>}`、稽核 `enter`。

**要登入的路由怎麼驗**（每個請求都做，不快取）：`X-SYNOX-App` 的雜湊找得到登入；沒過期（建立後 12 小時，常數 `APP_SESSION_TTL`）；
它記的 `console_digest` 還在 `ui.sessions` 裡（主機台登出、過期、`/web_off` 之後就不在了）；`registry.visible(user, group)` 現在仍然成立。
任何一條不成立 → 作廢這個登入、401 `code: "login"`。每人每個 app 最多 5 個登入（`APP_SESSIONS_PER_USER`），新的擠掉最舊的。伺服器只存 token 的 SHA-256。

錯誤一律 `{"ok": false, "code": "<代碼>", "error": "<白話>"}`。代碼：`login` 401、`origin`／`forbidden` 403、`not_found` 404、`invalid` 400（多一個 `fields: {欄位名: 訊息}`）、
`confirm` 409（多一個 `confirm`）、`refused`（工具丟的 `AppError`，用它的 status）、`too_large` 413、`error` 500（只說「出錯了：<例外類別名>」）。

### C5 `GET /api/me`（也是 `/api/enter` 回應裡的 `me`）

```json
{"ok": true,
 "user": {"id": 1, "name": "顯示名稱", "owner": true},
 "app": {"name": "money", "title": "💰 記帳", "app_title": "記帳本", "version": "0.3.0"},
 "reads": ["month", "entries"],
 "actions": {"rm": {"effect": "danger", "summary": "刪掉某一筆…", "fields": [{"name": "n", "label": "編號", "required": true, "kind": "int", "default": ""}]}},
 "exports": {"entries_csv": {"available": true, "reason": ""}},
 "console_url": "http://127.0.0.1:8830/#tools",
 "policy": {"mode": "auto", "suggest_min": 30, "close_min": 120, "text": "120 分鐘沒用就關，30 分鐘先提醒"},
 "alive_every_s": 60}
```

- 沒有 `csrf`（第三版：登入標頭本身就擋偽造）。`/api/me` 不回 token。
- `actions[*].summary`／`fields` 取自那個葉節點（`fields` 用 `toolpage.field_info`，`src/synox/web/toolpage.py:66-77`），所以畫面的表單說明跟 `/help`、工具頁同一份。
- `exports[*].available`：個人版 true；伺服器版 false，`reason` 是 C6.1 那句話。`policy` 見 C10；`alive_every_s` 是 C11 的間隔。

### C6 `POST /api/do/<name>`

請求：`{"values": {"欄位名": "字串", …}, "confirmed": true}`（`confirmed` 選填）。伺服器依序：

1. `name` 在 `spec.actions` 而且工具掛了函式，否則 404。
2. `node = registry.node(f"{group}.{name}")`；`registry.authorize(user, node, TYPED, user.tg_id)` 不放行 → 403 `forbidden`（訊息用 Decision 的文字，沒有就「你不能做這個動作」）。
3. `values` 要是物件；鍵要是這個節點的欄位名（不認得的拒）、值要是字串、最多 20 個、每個最多 2000 字、不能有 NUL——能重用 `src/synox/agent/validate.py` 的檢查就重用，不要另抄一份。
   再叫 `kit.check_values(node.fields, values)`：有 `errors` 或 `missing` → 400 `invalid`，`fields` 逐欄列出（訊息跟 Telegram 那條同一句）。
4. `node.effect == "danger"` 而且 `confirmed` 不是 `true` → 409：
   `{"ok": false, "code": "confirm", "error": "這個動作要你確認", "confirm": {"text": "<describe(user, values) 或「<節點的 summary>」>", "button": "確定"}}`。
   **伺服器不存任何確認的狀態**（第三版）：帶 `"confirmed": true` 再送一次就執行。這擋的是手滑，不是惡意畫面（ADR §3.5）。
5. 呼叫 `fn(user, clean)`。回傳值要是 `dict`。`kit.AppError` → 照它的 `status`／`code`／`message`；其他例外 → 500 `error`，log 照 C8。
6. 稽核一行（成功或失敗都記；`confirmed` 記有沒有帶）。回 `{"ok": true, "data": <fn 的回傳>}`。

### C6.1 `POST /api/export/<name>`

這一條是**表單送出**（瀏覽器才會把回應當附件存檔）：`Content-Type` 是 `application/x-www-form-urlencoded`；登入 token 在表單欄位 `t`（不是標頭）；
`confirmed=1` 表示使用者看過提醒了；其餘欄位都當 `params`（字串）。來源檢查照 C4（同源表單在 `no-referrer` 下會送 `Origin: null`，
所以這條依賴「`Origin: null` 只在 `Sec-Fetch-Site: same-origin` 時放行」）。伺服器依序：

1. 用 `t` 驗登入（同 C4）。`name` 在 `spec.exports` 而且工具掛了函式，否則 404。
2. **伺服器版（`config.mode == "server"`）一律拒**：403 `code: "export_encrypted_only"`，`error`：「這台 SYNOX 是多人共用的，只能匯出加密的檔；這個功能還沒做好。」`fn` 不會被叫到。稽核 `export`、`ok: false`。
   （加密匯出的格式擁有者還沒定。**不要自己挑一種做。**）這一條是伺服器的規則，畫面跳不過。
3. 沒有 `confirmed=1` → 409 JSON：`{"ok": false, "code": "confirm", "confirm": {"text": "匯出的檔案沒有加密，打得開這個檔的人都看得到內容。存在你放心的地方，用完就刪。", "button": "下載"}}`。這段字是 SYNOX 的常數。
4. `result = fn(user, params)`，必須是 `kit.Download`：`filename` 只留英數與 `-_.`（其他換成 `_`，最多 80 字，一定要有副檔名）；
   `content_type` 只收白名單（`EXPORT_TYPES = ("text/csv; charset=utf-8",)`）；`data` 是 `bytes`、最多 20 MB。不合 → 500 `error`。`kit.AppError` 照舊。
5. 回 200：`Content-Type` 照白名單、`Content-Disposition: attachment; filename="<檔名>"`、其餘標頭照 C4 第 4 點。
6. 稽核 `export`：`action`＝名字、`ok`、`bytes`＝大小、`confirmed`。**不記 `params` 的值、不記檔案內容。**

共用元件的流程（工作包 3）：`available` 是 false → 不送任何請求，顯示 `reason`。否則先用 `fetch` 送一次（表單格式、帶 `t`、不帶 `confirmed`）拿到 409 的那段字 → 確認框 → 按「下載」→ 建一個看不見的 `<form method="post">` 帶 `t`、`confirmed=1`、參數送出。

### C7 主機台這一側（8830）

`/api/apps…` 照主機台現有的規矩（要登入、非 GET 要 `X-SYNOX-CSRF`）：

| 路由 | 誰 | 回 |
|---|---|---|
| `GET /api/apps` | 登入的人 | 下面的清單（成員只看得到自己看得到的工具；`can_manage` 只有擁有者是 true） |
| `POST /api/apps/<name>/start` | 擁有者 | `{"ok": true, "app": <一筆>}`；錯：403、404、409（`code`：`max_running`｜`unavailable`｜`blocked`｜`busy`＝正在開或正在關）、503（`code: "port"`） |
| `POST /api/apps/<name>/stop`、`/keep` | 擁有者 | `{"ok": true, "app": <一筆>}` |
| `POST /api/apps/<name>/policy` | 擁有者 | 內容見 C10 → `{"ok": true, "app": <一筆>}`；不合 400 |
| `POST /api/apps/stop-all` | 擁有者 | `{"ok": true, "stopped": ["money"]}` |
| `GET /api/apps/log?limit=50` | 擁有者 | `{"events": [<稽核行>…]}`（新的在前，最多 200） |

**打開（交接）**：`POST /apps/<name>/open`——不在 `/api/` 底下，因為它是一個 `target="_blank"` 的**表單送出**，回應是轉址：

- 在 `WebUI.route()` 裡自己一條（寫法照 `/login` 的 POST）：要有效的主機台 session；表單欄位 `csrf` 要等於 session 的 csrf（`session.csrf_ok`）；
  來源判斷照 `login_post`（`Origin` 的 netloc 等於 `Host`；`Origin: null` 只在 `Sec-Fetch-Site: same-origin` 時放行；`Sec-Fetch-Site` 有值而且不是 `same-origin` → 403）。
- 這個人要看得到這個工具，而且服務開著；否則一頁白話（「這個工具的服務沒有開」＋回工具頁）。**打開不會順便把服務開起來**——開是擁有者的另一個動作。
- 過了 → `ticket = manager.issue_ticket(name, user.tg_id, console_digest)` → `303`，`Location: http://127.0.0.2:<埠>/#t=<ticket>`，加 `Referrer-Policy: no-referrer`、`Cache-Control: no-store`。稽核 `handoff`。
- 票：256 bit 隨機、30 秒（`HANDOFF_TTL`）、只能用一次、綁（app 名、埠、`tg_id`、主機台 session 的雜湊）。記憶體裡只存票的 SHA-256；每個 app 最多 20 張沒用過的（多的丟最舊的）。服務一關全部作廢。

`GET /api/apps` 的內容：

```json
{"available": true, "reason": "", "can_manage": true, "running": 1, "max_running": 3,
 "explain": {"what": "…", "why_close": "…", "restart": "…"},
 "apps": [{"name": "money", "title": "💰 記帳", "app_title": "記帳本", "state": "on",
           "open": "/apps/money/open", "port": 8841,
           "since": "2026-11-14T10:00:00", "last_used": "2026-11-14T10:20:00", "idle_min": 12,
           "suggest_close": false, "auto_close_in_min": 108, "error": "",
           "policy": {"mode": "auto", "suggest_min": 30, "close_min": 120, "default": true,
                      "text": "120 分鐘沒用就關，30 分鐘先提醒"},
           "actions": {"write": 9, "danger": 1}, "exports": ["entries_csv"], "problem": ""}]}
```

- **沒有 app 的網址**（第三版）：畫面上不顯示、不讓人複製 `http://127.0.0.2:…`；`open` 是主機台自己的表單位址，只有 `state` 是 `on` 時有值。`port` 只放在「進階」的小字裡。
- `policy` 給每個看得到這個工具的人（成員也看得到，只是不能改）；`auto_close_in_min` 在不會自動關的設定下是 `null`。
- `state`：`off`｜`on`｜`error`。`error`：一個原因碼對應的白話（埠被占用、關不乾淨、檔案跟安裝時不一樣）。`problem`：宣告了 app 但掛不起來的原因；有 `problem` 的不能開。`explain` 的三句照 ADR「給使用者的說法」。

### C8 稽核、log、狀態檔

- `data/apps_audit.jsonl`，一行一個 JSON，**欄位固定、沒有自由文字**（第三版）：
  `{"at": "<ISO 秒>", "event": "start|stop|auto_stop|suggest|keep|policy|handoff|enter|leave|action|export|denied|error", "app": "money", "by": <tg_id 或 0＝系統>, "via": "web|telegram|app|system", "action": "", "effect": "", "ok": true, "code": "", "confirmed": false, "port": 8841, "bytes": 0, "reason": "", "mode": "", "close_min": 0}`
  - `reason` 只能是：`""`、`owner`、`idle`、`shutdown`、`web_off`、`reload`、`blocked`、`tampered`、`stuck`、`host`、`proxy`、`origin`、`ticket`。`code` 只能是 C4 的錯誤代碼。`action` 只能是宣告過的名字。
  - 寫入函式用白名單檢查每個欄位（不在名單的值寫成 `"other"`），所以不可能有人把一段文字帶進來。
  - **永遠不寫**：參數的值、檔案內容、token、票、cookie、例外的訊息。超過 1 MB：改名成 `apps_audit.jsonl.1`（蓋掉舊的）再開新檔。寫檔持自己的鎖。
- **log**：這個功能的每個 `except` 都用同一個小函式 `safe_trace(e) -> str`：例外的類別名＋每一層的「檔名:行號 函式名」（`traceback.extract_tb`），**不含 `str(e)`、不含原始碼那一行、不含區域變數**。
  不准用 `logging.exception`、不准把 `e` 放進 f-string。（例外訊息常常帶著使用者打的字，例如 `ValueError("bad memo: …")`。）
- `data/apps.json`：`{"ports": {"money": 8841}, "explained": true, "policy": {"money": {"mode": "auto", "close_min": 120}}}`。
  `ports`：**一個埠配給一個工具之後永遠是它的**，工具移除了也不還（要回收只能人手動刪這個檔裡的那一筆）。範圍用完 → 開不了、說明把 `web.apps.port_count` 調大。
- `data/apps_state.json`：`{"pid": 1234, "at": "<ISO>", "running": [{"name": "money", "port": 8841, "since": "<ISO>"}]}`。SYNOX 啟動與結束時都寫成空清單；每次開關更新。給 `doctor` 讀。

### C9 Telegram／指令

群組 `apps`（`registry.ensure_group("apps", "🧩 工具服務", "開、關、看每個工具自己的網頁", bare=True, …)`，個人版擁有者、伺服器版成員可看清單）。

| 指令 | 危險程度 | 誰 | AI／排程 | 回什麼 |
|---|---|---|---|---|
| `/apps` | 唯讀 | 看得到工具的人 | 可 | 每個有 app 的工具一行：開著（開多久、多久沒用）／關著，後面接它的閒置設定；最後三筆紀錄；一句「開：/app_open 名字　關：/app_close 名字」 |
| `/app_open <名字>` | 會寫入 | 擁有者、只在私訊 | **都不行**：`ai=False`、`interactive=True`、`owner_only=True`、`private_only=True` | 開（已開就不重開）→「💰 記帳的服務開好了。到 SYNOX 網頁的工具頁按『打開』：http://127.0.0.1:8830/#tools（要在跑 SYNOX 的這台電腦上）。不用的時候 /app_close money。」第一次另附 ADR 的三句說明 |
| `/app_close <名字｜all>` | 會寫入 | 擁有者 | 可 | 「關好了。資料都在，Telegram 照樣可以用。」 |

- **回覆裡不放 app 的網址**（直接開只會看到「請從 SYNOX 打開」），也不放任何票。
- `/app_open` 為什麼要 `interactive=True`（審查發現 2）：`/schedule_add 03:00 /app_open money` 建立時用 `SCHEDULE`、到點用 `ROUTINE` 檢查，這兩條路與 AI 都只擋 `interactive` 的節點。
  第二層：`AppManager.start(name, by, via)` 的 `via` 只收 `"web"` 與 `"telegram"`，其他值（`"system"`、`"app"`、任何內部呼叫）一律 `AppsError("forbidden")`。
- `<名字>` 認：pack 名、群組名、標題（去掉 emoji 與空白）、`app.title`，不分大小寫；對不到 → 列出有哪些。設成「不開放」的工具回「你把<標題>設成不開放了；要開先到 SYNOX 網頁的工具頁改設定。」
- 這一輪沒有改閒置設定的 Telegram 指令。AI 能不能開服務擁有者還在考慮，定案前不要預留 AI 的路。

### C10 每個工具的閒置設定（ADR §4.2）

`POST /api/apps/<name>/policy` 的內容與 `data/apps.json` 存的形狀：

| `mode` | 其他欄位 | 行為（`AppManager.tick()`） | `text`（給人看） |
|---|---|---|---|
| `auto` | `close_min`：5–1440 的整數 | 閒置滿 `close_min` → 自動關＋通知。`close_min > 30` 時，閒置滿 30 分鐘先提醒一次；`≤ 30` 不另外提醒 | 「120 分鐘沒用就關，30 分鐘先提醒」／「30 分鐘沒用就關」／「N 分鐘沒用就關…」 |
| `suggest` | — | 閒置滿 30 分鐘提醒一次（同一段閒置只一次），不關 | 「只提醒，不自動關」 |
| `keep` | 請求要帶 `"understood": true`，否則 400 | 不提醒、不關 | 「一直開著」 |
| `blocked` | — | 不能開；設定當下開著的先關掉（稽核 `stop`，`reason: "blocked"`） | 「不開放這個工具的畫面」 |

- 沒有存過設定的工具：`mode: "auto"`、`suggest`／`close` 用 `web.apps.idle_suggest_min`／`idle_close_min`（預設 30／120），`policy.default` 是 true。
  `config.json` 的 `idle_close_min` 是 0 時預設等同 `suggest`；兩個都是 0 等同 `keep`（擁有者自己改設定檔的選擇，不用再問）。
- 提醒的 30 分鐘是常數 `SUGGEST_MIN = 30`（`auto` 與 `suggest` 共用；預設那一組用設定檔的值）。
- 只有擁有者能改；每次改寫一行稽核 `policy`（`mode`、`close_min`）。改設定算一次「先留著」（重新計時）。
- 「一直開著」**不保存「開著」這件事**：SYNOX 重開之後它一樣是關的。
- 畫面上的選項與警告文字在 ADR §4.2 的表（工作包 4 照抄進 `TEXT`）。

### C11 什麼算「有在用」（ADR §4.1）

`manager.touch(name)`（更新 `last_used`、清掉「這一段閒置已經提醒過」）**只在**這些時候叫：

1. app 埠上**帶著有效登入**的 `/api/` 請求：`/api/enter` 成功、`/api/me`、`/api/read/*`、`/api/do/*`（不管成功失敗）、`/api/export/*`、`/api/keep`。
2. `POST /api/alive`：同一個 app 登入**每 60 秒最多算一次**（比較與更新 `AppSession.last_alive` 在那個登入自己的鎖裡一次做完；太頻繁的照樣回 200 但不 `touch`）。
3. 主機台的「先留著」與改閒置設定。

**不算**：`GET /`、靜態檔、`/_synox/*`（不帶登入，任何網頁都能讓瀏覽器去抓——審查發現 5）；沒登入、被擋的請求；主機台的 `GET /api/apps` 與「打開」；`tick()` 自己。

共用元件什麼時候送 `/api/alive`（工作包 3）：在 `mousemove`、`keydown`、`pointerdown`、`wheel`、`scroll`、`touchstart` 的監聽裡（`passive: true`），
`event.isTrusted` 而且 `document.visibilityState === "visible"` 而且距離上次送出（或上次任何 `read`／`act` 成功）超過 `alive_every_s` 秒 → 送一次。
**沒有 `setInterval`／`setTimeout` 迴圈**：沒有輸入就什麼都不送。失敗不重試、不顯示任何東西。

### C12 同時動手（第三版；審查發現 4）

- `AppManager` 一把 `threading.RLock`（`manager.lock`）。**在鎖裡做的**：`start`、`stop`、`stop_all`、`set_policy`、`tick` 裡「決定要關誰、要提醒誰」與真的關、`issue_ticket`、`redeem_ticket`、讀寫埠的對照表與 `apps.json`。
- **不在鎖裡做的**：`notify_owner`、寫稽核、寫狀態檔以外的任何 I/O——先在鎖裡收集要做的事，放開鎖再做。
- `touch` 與 alive 的節流**不拿這把鎖**（各自的小鎖或單一賦值），請求的執行緒才不會卡在一個正在關的服務上。
- 每個 app 有一個狀態：`off`｜`starting`｜`on`｜`stopping`｜`error`。`starting`／`stopping` 期間再來的 `start`／`stop` → `AppsError("busy", …, 409)`（不排隊、不重入）。
- **關是同步的**：`Listener.close()`＝`shutdown()` → `server_close()` → `join` 聽連線的那條執行緒（最多 5 秒）。`join` 回來了才把狀態設成 `off`、才把埠當成空的。
  超過 5 秒 → 狀態 `error`、`reason: "stuck"`，那個埠到 SYNOX 重開之前不再用。**關的時候不等正在處理請求的執行緒**；那些執行緒之後拿登入去查會發現登入已經作廢。
- **不自動換埠**：工具記在 `apps.json` 的埠被別的程式占住（`OSError`）→ 狀態 `error`、白話說明（「8841 被別的程式用了。關掉那個程式再試；還是不行就重開 SYNOX。」），不跳到下一個。
- `redeem_ticket`：在鎖裡「找到 → 檢查 app、埠、沒過期 → 刪掉」一次做完；兩個請求同時用同一張票，只有一個成功。比對用 `hmac.compare_digest`。

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
**出貨的前提是第 9 節的 G1**（擁有者在別台電腦做）：G1 沒過，WP2 之後的東西都不合進 `dev`。

### WP0 主機台加固（跟功能無關，只有變嚴；可以先單獨合進 `dev`）

**為什麼**：之後這台電腦上會有另一個位址在跑第三方的畫面程式；主機台先把「不是自己的頁面送來的請求」擋掉。

改 `src/synox/web/server.py`：

1. `route()`：`path.startswith("/api/")` 而且請求帶了 `Sec-Fetch-Site`、值是 `same-site` 或 `cross-site` → `_err(403, "來源不對（不是從 SYNOX 自己的頁面送出的）。")`。沒帶這個標頭（curl、舊瀏覽器）照舊。放在登入檢查之前。
2. `_cookie` 旁邊加 `_cookies(headers, name) -> List[str]`（同名的全部）；`session_from` 改成每個都試、回第一個有效的。`_cookie` 留著給其他呼叫端。
3. 所有回應加 `Cross-Origin-Opener-Policy: same-origin`；`_json` 的回應加 `Cross-Origin-Resource-Policy: same-origin`（加在 `BASE_HEADERS`／`_json`，不要一個一個路由補）。
4. `src/synox/web/tokens.py`：`Sessions.has(key_digest: str) -> bool`（這個雜湊的 session 還在而且沒過期；WP2 用它把 app 的登入綁在主機台的登入上）。

文件：`docs/security.md`「沒有做的保護（誠實清單）」加一條**既有問題**（ADR「擋不住的」那一段，白話）：同一台電腦上的另一個帳號或程式去聽 `127.0.0.1` 的任何一個埠、再讓擁有者的瀏覽器連過去一次，
就收得到主機台的登入 cookie（cookie 不分埠）。這一包**不修它**，只寫出來；另外在 `docs/lab/issues-to-open.md` 加一筆。

測試 `tests/test_web_hardening.py`：

- `/api/me` 帶 `Sec-Fetch-Site: same-site`／`cross-site` → 403；`same-origin`、`none`、沒帶 → 照舊 200。POST 同理。
- `/`、`/login`、`/tutorials/x/` 不受影響（帶 `cross-site` 也照舊）。
- Cookie 標頭是 `synox_session=假的; synox_session=<真的>` 與反過來 → 都認得出登入。
- 每種回應（頁面、JSON、錯誤）都有 COOP；JSON 有 CORP。
- `Sessions.has`：剛建立的 → True；`drop` 之後、過期之後、`drop_all` 之後 → False；亂給的字串 → False。

驗收：新測試全過；現有 `tests/test_web*.py`、`test_tools_page.py`、`test_control_panel.py` 不改就過。

### WP1 宣告與檢查（manifest、第 2 關、升級紅字、報告、工具端介面）

| 檔 | 做什麼 |
|---|---|
| `src/synox/packs/manifest.py` | `parse_web` 多解析 `app`（C2）。規則：kind 不是 python → 拒；`root` 是 pack 裡的子資料夾（不能是 `.`、不准 `..`、絕對路徑；沿用 `_inside`）；`entry` 是 `root` 裡的 `.html`、檔案存在；`title` 選填、一行、24 字內；`kit` 必填、整數、要在 `KIT_VERSIONS` 裡（不認得的版本＝拒，訊息說這台 SYNOX 認得哪幾版）；`reads` 清單、名字合 `WEB_ROUTE_RE` 的名字規則、不重複、最多 40；`actions` 物件、名字同規則、值只收 `WRITE`／`DANGER`（不分大小寫，存小寫）、最多 40；`exports` 選填、清單、名字同規則、不重複、最多 10；`reads` 與 `actions` 至少一邊有東西；`web.app` 裡不認得的鍵＝拒（安裝時）；`root` 底下：副檔名只准 `.html .js .css .json .png .jpg .jpeg .webp .svg .ico .woff2`、最多 100 個、單檔 ≤ 512 KB、合計 ≤ 3 MB、不准符號連結。`_unc_strings` 加 `web.app.root`、`web.app.entry`（strict）。常數集中放檔頭（`APP_EXT`、`APP_MAX_FILES`…）。已裝的舊 pack 寫壞了＝當作沒有 app（不要讓整個工具載不起來），安裝時（strict）＝拒 |
| `src/synox/packs/appscan.py`（新） | `scan_app(m) -> List[Finding]`（沿用 `scan.Finding`），只用標準函式庫、不執行。**擋（種類 `app`）——只有解析 HTML（`html.parser`）就能確定的**：有內容的 `<script>`；`on*` 屬性；`<base>`；`<meta http-equiv>`；`<iframe>`／`<object>`／`<embed>`／`<frame>`；`script`／`link`／`img`／`source`／`video`／`audio`／`form` 的 `src`／`href`／`action`／`srcset`／`poster` 是帶協定或 `//` 開頭的網址；`entry` 的**第一個** `<script>` 不是 `src="/_synox/kit.js"`。**提醒（種類 `app_note`，不擋）——字串比對**：JS／CSS／JSON／SVG 文字裡的 `http://`、`https://`（`http://www.w3.org/` 除外）；CSS 的 `@import`、`url(` 指到外面；JS 的 `eval(`、`new Function`、`document.cookie`、`window.open`、`location.href =`／`location =`／`location.assign`／`location.replace`、`sendBeacon`、`WebSocket`、`importScripts`、`serviceWorker`、`fetch(`、`XMLHttpRequest`（最後兩個的字：「畫面程式自己連線，沒經過共用元件」）。每筆有檔名與行號。兩個種類加進 `scan.LABELS`（「網頁畫面不合規則」／「網頁畫面（提醒）」）與 `CAPABILITY_OF`（`""`） |
| `src/synox/packs/scan.py` | `opaque_files`／`opaque_reason`：宣告了 `web.app` 時，`root` 底下副檔名在 `APP_EXT` 的檔**不算**掃不到的檔（要把 manifest 或 app root 傳進來；簽名怎麼改自己定，但 `tier.assess` 兩條路都要一致）。`scan()` 把 `appscan.scan_app(m)` 的結果併進報告 |
| `src/synox/packs/admin.py` | `summary_of` 多 `"app": None 或 {"title", "kit", "files": 個數, "reads": [...], "actions": {...}, "exports": [...]}`；`warnings_for` 多一段（有 app 一定顯示，字照 ADR §5，**第三版的版本**）：「這個工具附了完整的網頁畫面（N 個檔）。它在你的瀏覽器裡跑，可以不經你同意讀、改、匯出這個工具裡的所有資料（僅限下面列的動作）。SYNOX 檢查了格式、不讓它連到外面的網址，但看不懂畫面程式在做什麼——跟 pack.py 一樣，是你決定要不要信任的程式。要看服務開著沒、要關掉，以 SYNOX 自己的畫面為準。」有 `exports` 再多一句「它的畫面可以把資料匯出成檔案：<名字>。」 |
| `src/synox/packs/upgrade.py` | `app`「新加了完整的網頁畫面（工具服務）」紅；`app_action_added`「畫面多了動作 <名>（<危險程度>）」紅；`app_effect`「畫面動作 <名> 的危險程度 a → b」變寬紅、變窄一般；`app_export_added`「畫面多了匯出 <名>」紅；拿掉 app／動作／匯出一般字 |
| `src/synox/packs/loader.py` | `Pack` 加 `app_reads`、`app_actions`、`app_describe`、`app_exports` 四個 dict 與 `app_read()`、`app_action()`、`app_export()`（C3）；重新載入時清空 |
| `src/synox/packs/kit.py` | `check_values`、`AppError`、`Download`（dataclass）、`csv_bytes`；`parse_args` 改用 `check_values` |
| `tests/fixtures/app_pack/` | 測試用的小工具 `counter`：`pack.json`（python、`data: user`、`storage: vault`、`web.app`：`kit: 1`、reads `state`，actions `add: WRITE`、`reset: DANGER`、exports `state_csv`）、`pack.py`（指令 `add <n>`（WRITE，`check=kit.positive_int`）、`reset`（DANGER）＋ `app_read`／`app_action`／`app_export`（用 `kit.csv_bytes`），核心函式共用）、`app/index.html`（第一個 script 是 kit）、`app/app.js`（只用 `SynoxApp.*`）、`app/app.css`、`SKILL.md`。**之後每個工作包的測試都用它** |
| `src/synox/web/static/app.html`（安裝報告那一段） | 報告顯示 `summary.app`：上面那段白話＋動作清單（沿用 `EFFECT` 的字）＋匯出清單。只加顯示，不動流程 |

測試 `tests/test_app_manifest.py`：

- 好的 fixture 過第 1、2 關；信任層級是 T1（`app/app.js` 沒把它推到 T2）；沒宣告 `exec` 也不會被要求；沒有任何提醒。
- 每條第 1 關規則各一個壞例子 → 拒，訊息點名欄位（`..`、絕對路徑、UNC、`root` 是 `.`、`entry` 不在 `root`、副檔名不在白名單（`app/x.py`、`app/x.exe`）、檔太多、檔太大、`actions` 的值是 `READ`、kind=cli、`kit` 沒寫／是 `2`／是字串 `"1"`、多一個不認得的鍵 `idle`、`exports` 不是清單／名字不合／重複）。
- `app/` 外面的 `.js` 照舊算掃不到的檔（T2）；`app/` 裡放 `.py` → 拒。
- appscan **擋**：內嵌 script、`onclick=`、`<base>`、`<iframe>`、`<script src="https://evil.example/x.js">`、`<img src="//evil.example/a.png">`、入口頁沒有 kit、kit 不是第一個 script → 各自被擋、有檔名行號。
- appscan **只提醒、不擋**：`app.js` 的註解裡有 `https://example.com`、字串裡有網址、CSS `@import`、`eval(`、`fetch(`、`navigator.serviceWorker` → 報告各有一筆 `app_note`、安裝**不被拒**。SVG 的 `xmlns="http://www.w3.org/2000/svg"` 連提醒都沒有。
- 升級：舊版沒有 app → 新版有＝紅；多一個動作＝紅；多一個匯出＝紅；`WRITE`→`DANGER`＝紅；`DANGER`→`WRITE`＝一般。
- `pack.app_read`／`app_action`／`app_export`：沒宣告的名字丟 `ValueError`；宣告的掛得上。
- `kit.check_values` 與 `parse_args`：同一組輸入，錯誤訊息一樣；現有 `tests/test_packs.py`、`test_tools.py` 不改就過。
- `kit.csv_bytes`：開頭是 BOM；CRLF；數字原樣；`None` 是空的；`"=1+1"`、`"+x"`、`"-5"`（字串）、`"@a"`、Tab 開頭、換行開頭 → 前面多 `'`；數值 `-5`（int）**不加**；有逗號、引號、換行的儲存格用 `csv` 讀回來一樣。
- 報告的白話裡有「不經你同意」「以 SYNOX 自己的畫面為準」。
- 舊的行為不變：沒有 `web.app` 的 pack，`summary_of`、tier、報告跟以前一模一樣（拿現有 fixture 比）。

驗收：上面全過；`python -m synox doctor --offline` 不變；`docs/pack-format.md` 的表格加 `web.app` 一列與一小節（規則、範例）；`docs/security.md` 五關表格的第 1、2 關各補一句。

### WP2 核心執行（管理員、每個 app 的站、交接票、登入、稽核、閒置）

新資料夾 `src/synox/web/apps/`：

| 檔 | 內容 |
|---|---|
| `__init__.py` | `install(app, config, ui) -> AppManager`：建管理員、`app.extras["synox_apps"] = manager`、`ui.apps = manager`；`app.on_start`：清狀態檔、登記 runtime 任務；`app.on_stop`：`stop_all(reason="shutdown")`。由 `web.install` 在建好 `ui` 之後呼叫 |
| `spec.py` | `AppSpec`（name、group、title、app_title、version、entry、root、reads、actions、exports、files、pack）；`specs_of(app) -> (Dict[name, AppSpec], Dict[name, problem])`：從 `app.extras["synox_packs"]` 現算。核對：`reads`／`exports` 每個都掛了函式；`actions` 每個都掛了函式、`registry.node(f"{group}.{name}")` 存在、`node.effect` 等於宣告。任何一條不合 → 這個 app 進 `problems`、不能開 |
| `sessions.py` | `AppSessions`（記憶體）：`create(tg_id, console_digest) -> (token, AppSession)`（每人上限、擠掉最舊的）、`get(token) -> Optional[AppSession]`（只查，不判斷有效與否）、`drop(token)`、`drop_all()`。`AppSession`：`tg_id`、`console_digest`、`created`、`expires`、`last_alive`、自己的小鎖、`alive_ok(now) -> bool`（比較與更新一次做完）。`HandoffTickets`：`issue(...)`／`redeem(...)`（C7、C12；由 manager 在大鎖裡叫）。只存 SHA-256（沿用 `tokens.digest`）。**沒有 `ConfirmTickets`**（第三版拿掉） |
| `audit.py` | `Audit(path, clock)`：`write(event, app, **fields)`（白名單檢查，C8）、`tail(limit)`；`safe_trace(e)` 也放這裡 |
| `site.py` | `AppSite(manager, spec, port, *, clock)`：`handle()` 照 C4–C6.1。建構時 `snapshot = load_snapshot(spec, pack.locked_files)`：讀 `files` 進記憶體、有鎖就逐檔對 SHA-256，不符丟 `AppsError("tampered", …)`（訊息點名那個檔）；沒鎖（`packs.dirs` 開發用）照讀 |
| `listen.py` | `APP_HOST = "127.0.0.2"`。`open_listener(site, port) -> Listener`：`srv = server._Server((APP_HOST, port), server._Handler)`、`srv.daemon_threads = True`、`srv.ui = site`、開 `serve_forever` 的 daemon 執行緒；`Listener.port`、`Listener.close(timeout=5.0) -> bool`（C12：同步，回有沒有關乾淨）。**整個功能唯一會開埠的地方，越短越好；不 import `bind_host`** |
| `manager.py` | `AppManager`（下面） |
| `web_api.py` | `route(ui, user, method, path, data) -> Resp`：C7 的 `/api/apps…`；`open_handoff(ui, session, user, name, headers, body) -> Resp`：C7 的 `POST /apps/<name>/open`。給 WP4 接進 `server.py` |
| `testing.py` | `AppClient(manager, name, *, console=None)`：假瀏覽器（`Host` 自動帶對、不帶任何 cookie）。`open_from_console(tg_id) -> ticket`（走真的 `issue_ticket`）、`enter(ticket) -> me`（存 token）、`get(path)`、`read(name, **params)`、`do(name, values, confirmed=False)`、`do_confirmed(name, values)`（自動走兩步）、`export(name, params, confirmed=False)`、`raw(method, path, headers=, body=)`。`FakeListener`、`fake_listen`（記下被要求開的位址與埠；可設定某個埠丟 `OSError`、可設定 `close()` 回 False）。給 SYNOX 自己與 SYNOX_Libs 的測試用 |

`AppManager`（`__init__(self, app, config, ui, *, listen=open_listener, clock=time.time, exists=os.path.exists, environ=None)`）：

- `available() -> (bool, str)`：C1。
- `specs()`／`problems()`：包 `spec.specs_of`。
- `start(name, by, via) -> dict`：`via` 不是 `"web"`／`"telegram"` → `AppsError("forbidden")`。不可用／不是擁有者／沒有這個 app／有 `problem`／`blocked`／已達 `max_running`／`busy` → `AppsError(code, message, status)`。已經開著 → 直接回現況。
  配埠：`apps.json` 記的那個；沒有就取範圍內**從來沒配給任何工具**的第一個並立刻記下來。`listen` 丟 `OSError` → 狀態 `error`、`AppsError("port", …, 503)`，**不換埠**（C12）。
  成功：更新狀態檔、稽核 `start`、`reschedule` runtime 任務成 60 秒。
- `stop(name, by=0, via="system", reason="owner") -> bool`：C12 的同步關；`site.sessions.drop_all()`、清這個 app 的票、狀態檔、稽核（`stop` 或 `auto_stop`）；都關了就 `reschedule(None)`。
- `stop_all(...)`、`keep(name, by, via)`、`touch(name)`（C11）、`views(user) -> dict`（C7）、`resolve(text) -> Optional[str]`（C9）、`policy_of(name)`、`set_policy(name, data, by)`（C10）、`issue_ticket(name, tg_id, console_digest) -> str`、`redeem_ticket(name, port, ticket) -> Optional[tuple]`（C7、C12）。
- `tick()`（runtime 任務 `system.tool_apps`「工具服務」的 `fn`）：每個開著的 app 照它自己的 `policy_of(name)`：該關的 → `stop(via="system", reason="idle")`＋`notify_owner("🧩 <標題>的服務 <N> 分鐘沒有用，我先關掉了。資料都在；要用再 /app_open <名>。")`；
  該提醒而且這一段閒置還沒提醒過 → 稽核 `suggest`、`notify_owner("🧩 <標題>的服務 <N> 分鐘沒有用了。要關：/app_close <名>。不理我的話再 <M> 分鐘我會自己關。")`（`suggest` 模式後半句換成「它會一直開著，直到你關掉或重開 SYNOX。想改成自動關，到 SYNOX 網頁的工具頁設定。」）；`keep` 什麼都不做。
  通知在鎖外送（C12）。任務的狀態訊息：有開著的 → `running`「開著：記帳（閒置 12 分）」；沒有 → `idle`。
- 該自動關的時機都要接上：`WebUI.turn_off()`（`/web_off`，`reason: "web_off"`）→ `stop_all`；`WebUI._reload()`、`pack_remove`、升級（`_pack_upgrade`）之前 → `stop_all(reason="reload")`；
  `tick()` 每次檢查開著的 app 的 spec 還在不在、有沒有變成 `problem`、所屬工具是不是被健康檢查隔離——任何一個成立就關。

改 `src/synox/web/__init__.py`（呼叫 `apps.install`）、`src/synox/config.py`（C1 的預設與檢查）、`config.example.json`、`src/synox/web/server.py`（`turn_off`／`_reload`／移除／升級的掛鉤，各一兩行）。

測試 `tests/test_app_site.py`（用 `AppClient`、fixture `counter`、`no_sockets`）：

- Host：`127.0.0.1:<埠>`、`localhost:<埠>`、錯的埠、沒有 Host → 403，內容沒有任何 app 的字。只有 `127.0.0.2:<埠>` 過。
- 代理與 worker：帶 `X-Forwarded-For`、`X-Forwarded-Host`、`Forwarded`、`Via`、`Service-Worker: script` 任一個 → 403，連靜態檔也是。
- **沒有 cookie 這回事**：帶著有效的主機台 `synox_session` cookie（而且沒有 token）打 `/api/me`、`/api/read/state`、`/api/do/add` → 401；**所有**回應（入口、靜態、JSON、各種錯誤）都沒有 `Set-Cookie`。
- 進門：`GET /` 不用任何東西就 200，內容是入口頁，沒有任何使用者資料；`/api/enter` 帶真的票 → 200、有 `token` 與 `me`；同一張票再用 → 401；亂給的票 → 401；
  票是替別的 app／別的埠發的 → 401；31 秒後 → 401；發票之後主機台登出 → 進不來；發票之後那個人變成看不到這個工具 → 401。
- 登入每次都重查：有效的 token → 過；12 小時又 1 秒後 → 401 而且登入被刪；主機台 session `drop` 之後 → 401；把那個人的角色降到看不到這個工具 → **下一個請求**就 401；`/api/leave` 之後 → 401。
  同一個人進第 6 次 → 第 1 個 token 失效。
- 來源：`/api/` 路由帶 `Sec-Fetch-Site: same-site`／`cross-site` → 403；`Origin` 是別的埠或 `127.0.0.1` → 403；`Origin: null` 沒有 `same-origin` → 403、有 → 過。POST 的 `Content-Type` 不是 JSON → 400。
- 標頭：每種回應都有 C4 第 4 點全部的標頭（含 `worker-src 'none'`）；**沒有任何 `Access-Control-` 開頭的標頭**；`OPTIONS` → 405。
  `Clear-Site-Data`：開啟後第一個 `GET /` 有、第二個沒有；關掉再開之後的第一個又有。
- 靜態：`/app.js` 的位元組與 `Content-Type` 對；`/../pack.py`、`/%2e%2e/pack.py`、`/app/../../config.json`、`/pack.json` → 404；鎖裡的雜湊跟檔不一樣 → 開不起來、訊息點名那個檔。
- 讀：`/api/read/state` 回這個人的；伺服器版兩個人各自進門、互相看不到（真的保管箱，照 `tests/test_members.py` 的做法）。沒宣告的名字 → 404。
- 動作：`add` 成功後 store 的內容**跟用 `/counter_add 3` 打字的結果一樣**；`values` 有不認得的欄位、不是字串、太長 → 400；`n=abc` → 400 而且訊息等於指令那條的訊息；
  `reset`（危險）沒帶 `confirmed` → 409＋要顯示的字，資料沒動；`confirmed: true` → 成功；`confirmed: "true"`（字串）／`1` → 當成沒帶。
  工具函式丟 `kit.AppError("沒有這筆")` → 409 `refused`＋那句話；丟 `ValueError("秘密字串")` → 500，**回應、log（用 `caplog`）、稽核裡都找不到「秘密字串」**，log 裡有類別名與檔名行號。
- 權限：把節點設成擁有者限定，成員做動作 → 403（`authorize` 真的被叫到）。
- `/api/me`：形狀符合 C5，沒有 `csrf`、沒有 `token`。`/api/close-service`：成員 → 403；擁有者 → 200，之後 manager 說它關著。
- 匯出（C6.1）：個人版沒帶 `confirmed` → 409＋那段固定的字；帶 → 200、`Content-Disposition: attachment`、內容對、標頭齊；`t` 沒有／錯 → 401；`Sec-Fetch-Site: same-site` → 403；`Origin: null`＋`same-origin` → 過。
  **伺服器版 → 403 `export_encrypted_only`，帶不帶 `confirmed` 都一樣，而且工具的函式沒被叫到**（計數器）。工具回的不是 `kit.Download`、`content_type` 不在白名單 → 500；檔名有 `../` 或中文 → 被清乾淨。
- 有在用（C11）：`GET /`、`/app.js`、`/_synox/kit.js` 打一百次 → `last_used` **不變**；`/api/read/state` → 變。`/api/alive` 第一次 → 變；30 秒後再一次 → 200 但不變；61 秒後 → 變；
  沒 token 的 alive → 401、不變；被擋的請求不變。`/api/alive` 不寫稽核。
- 稽核：`handoff`、`enter`、動作（含失敗）、`export`、被拒各有一行；每一行的鍵都在 C8 的名單裡；整個檔案裡**找不到**動作的參數值、token、票；硬塞一個不在名單的 `reason` → 寫成 `other`。

測試 `tests/test_app_manager.py`（假 listener、假時鐘）：

- `web.apps.enabled=false`、`web.enabled=false`、`/web_off` 之後 → 不可用。容器：`environ={"SYNOX_IN_CONTAINER": "1"}` → 不可用；`exists` 對 `/.dockerenv` 回 True → 不可用；
  **兩個都沒有、但 `SYNOX_WEB_BIND` 之類的變數亂設 → 仍然可用**（證明沒有在看綁定位址）。
- 位址：假 listener 收到的永遠是 `("127.0.0.2", 埠)`；把 `config.web` 加上任何像 `host`／`bind` 的鍵、設任何環境變數，都不會變。`open_listener`：把 `server._Server` 換成假的類別，確認位址、`ui` 是 site、`daemon_threads` 是 True（**不真的綁**）。
- `start` 的 `via`：`"web"`、`"telegram"` → 可以；`"system"`、`"app"`、`"ai"`、`""` → `forbidden`，假 listener 沒被叫到。
- 不是擁有者 → 拒；沒宣告 app 的工具 → 404；宣告的危險程度跟指令不一樣的 fixture → `problems` 有它、開不了。
- 埠：`start` 兩次只開一次；埠寫進 `apps.json`、關掉再開是同一個；**假 listener 說那個埠被占用 → `error`／503、`apps.json` 的埠沒變、沒有去試別的埠**；
  工具 A 配過 8841、把 A 從清單拿掉之後開工具 B → B 拿到 8842，不是 8841；範圍用完 → 白話錯誤。
- `max_running=1` 開第二個 → 409，訊息列出開著的那個。
- 同時動手（C12，真的用執行緒）：兩條執行緒同時 `start` 同一個 → 假 listener 只被叫一次；`start` 進行到一半（假 listener 裡卡住）時另一條 `start`／`stop` → `busy`；
  兩條執行緒同時 `redeem` 同一張票 → 恰好一個成功；`stop` 進行中（假 `close()` 卡住）時 `touch` 不會卡住；假 `close()` 回 False → 狀態 `error`、`reason` 是 `stuck`、之後 `start` 不會再用那個埠。
  `stop` 回來之前，狀態不是 `off`。
- `stop`：登入與票全部失效（關之前拿到的 token 與票再用 → 401）、狀態檔清掉、稽核有 `stop`。
- 閒置（預設）：29 分 → 沒事；30 分 → `notify_owner` 一次、稽核 `suggest`；再 tick → 不重複；中間有帶登入的請求 → 重新計時；`keep` 同理；120 分 → 關、稽核 `auto_stop`（`reason: "idle"`）、通知一次。
- 每個工具自己的設定（C10）：`auto` 30 → 30 分直接關、沒有先提醒；`auto` 45 → 30 分提醒、45 分關；`suggest` → 提醒一次、之後不關；`keep` 沒帶 `understood` → 400，帶了 → 永不提醒不關；
  `blocked` → 開著的被關、`start` 回 409 `blocked`；`close_min` 是 4、1441、小數、字串 → 400。兩個工具不同設定同時開著，各走各的。成員改 → 403。
  改設定寫稽核 `policy`（有 `mode`、`close_min`，沒有任何文字）、存進 `apps.json`、新的 `AppManager` 讀得回來；`keep` 的工具在新的 `AppManager` 裡**不是開著的**。
- **沒宣告 `web.app` 的工具沒有表面**：拿 repo 裡現成沒有 app 的 fixture pack：不在 `specs()`／`problems()`、不在 `views()`、`start` → 404、`set_policy` → 404、`issue_ticket` → 拒、假 listener 沒被叫過。
- 一個都沒開時 runtime 任務沒有排程（`task.next_due is None`）；開一個之後有；全關之後又沒有。
- `turn_off()`、重新載入、移除工具 → 全部服務關掉；`tick()` 發現 spec 不見了 → 關。啟動時狀態檔被寫成空的；`on_stop` 全關。
- `views()` 的每一筆都沒有 `url`，字串化之後找不到 `127.0.0.2`。

驗收：上面全過；整個 repo 搜尋 `ThreadingHTTPServer(`、`_Server(`、`.bind(`、`.listen(`，**新增的只有 `listen.py` 裡那一個 `_Server(`**；`src/synox/web/apps/` 裡搜尋 `Set-Cookie`、`cookie`（不分大小寫）、`logging.exception`——都沒有（測試檔與註解除外）；
`docs/AGENT.md`：invariant 9 改寫成兩條（主機台照舊；「工具服務只綁 `web/apps/listen.py` 的 `APP_HOST`、只由那個檔開埠、不用 cookie、只能用交接票進」），加 invariant 23（「app 的每個請求照 C4 檢查；動作一定對到同名指令的葉節點；開服務只收網頁與打字兩種來路」）與 Map 的一列。

### WP3 共用元件（`appkit.js`、`appkit.css`；不依賴其他工作包，照合約寫）

檔案：`src/synox/web/static/appkit.js`、`src/synox/web/static/appkit.css`、`tests/js/test_appkit.js`、`tests/test_appkit.py`（照 `tests/test_control_panel.py` 怎麼用 node 跑 `tests/js/test_control.js` 的方式；沒有 node 就 skip）。

`appkit.js`（IIFE、`"use strict"`、不用 `innerHTML`、不用 `eval`、**不做任何定時的網路請求**、不碰 `document.cookie`、不註冊 service worker；檔頭一張 `TEXT`）。

**啟動（腳本一載入就做，在工具的程式之前）**：

1. `location.hash` 裡有 `t=<票>` → 先 `history.replaceState` 把網址改成乾淨的 `/`（票不留在網址列與歷史），再 `POST /api/enter {"ticket"}`。成功 → `sessionStorage.setItem("synox.app.token", token)`、記下 `me`。
2. 沒有票 → 讀 `sessionStorage` 的 token → `GET /api/me`。
3. 兩個都沒有，或回 401 → 清掉 `sessionStorage` 的 token、蓋一層遮罩：「請從 SYNOX 打開這個工具。」＋回主機台的連結。
   這時候還沒有 `me`，所以主機台的網址不能從 `/api/me` 來：`AppSite` 送出 `/_synox/kit.js` 時，把檔裡**唯一的**標記 `/*{{CONSOLE_URL}}*/` 換成 `json.dumps("http://127.0.0.1:<web.port>/#tools")`
   （埠是設定檔裡檢查過的整數；跟 `server.py` 的 `INLINE_RE` 同一種做法）。不要從入口頁讀——入口頁是工具的檔。

對外只有 `window.SynoxApp`：

| 函式 | 行為 |
|---|---|
| `ready(fn)` | 啟動完成而且有 `me` → 畫頁首列 → `fn(ctx)`；`ctx = {me, app, actions, reads, exports}`。沒登入就不叫 `fn` |
| `read(name, params)` | GET `/api/read/<name>`＋查詢參數 → resolve `data`；失敗 reject `{code, error}` 並 `toast(error)` |
| `act(name, values, opts)` | 值全部轉成字串（`null`／`undefined`／空字串的欄位不送）→ POST `/api/do/<name>`。收到 `confirm` → `confirmBox(confirm.text, confirm.button)`，按確定帶 `confirmed: true` 重送一次；按取消 reject `{code: "cancelled"}`（不 toast）。`invalid` → reject，`fields` 給呼叫端標在表單上。`opts.quiet` 不 toast |
| `form(actionName, opts)` | 照 `actions[name].fields` 產生表單（label 用 `label`、`required`、`kind` 決定 input 型別、`choices` 變下拉）；送出＝`act`；欄位錯誤顯示在欄位下面。`opts.values` 預填、`opts.submitText`、`opts.onDone(data)` |
| `download(name, params)` | 匯出，流程照 C6.1 |
| `toast(text, tone)`、`confirmBox(text, button) -> Promise<boolean>`、`el(tag, cls, text)`、`clear(node)`、`fmt.number(n)`、`fmt.date(iso)` | 小工具 |
| `keep()` | POST `/api/keep` |

- 每個 `/api/` 請求帶 `X-SYNOX-App: <token>`；`credentials: "omit"`（app 的埠沒有 cookie，也不要把任何 cookie 帶過去）；POST 帶 `Content-Type: application/json`。
- 「人還在」的訊號（C11）：kit 自己掛那六種事件的監聽；工具不用叫、也沒有對外的函式可以叫。`read`／`act` 成功時順便把「上次送出時間」設成現在。
- 頁首列（插在 `<body>` 最前面）：`app.title`、登入的人、連結「回 SYNOX」（`console_url`，`rel="noopener noreferrer"`）、「離開」（`/api/leave` 之後清 `sessionStorage`）、擁有者才有的「關閉服務」（`confirmBox` 之後 `/api/close-service`）、
  小字「這是 SYNOX 在這台電腦上開的工具畫面，不用的時候可以關掉。」（這條列是方便，不是保證——ADR §3.5；不要在文件裡把它寫成可信的狀態。）
- 網路失敗（連不上）或 401：蓋一層遮罩。連不上：「這個服務已經關了。回 SYNOX 再開一次就好，資料都在。」；401：「請從 SYNOX 再打開一次。」各附回主機台的連結。**表單裡打到一半的字不清掉。**
- `appkit.css`：`:root` 的顏色 token 抄主機台 `app.html` 的那一組（`--bg --surface --line --text --muted --accent --ok --warn --bad` 與深色版；`prefers-color-scheme`）；基本元件 `.bar`、`.card`、`.btn`（`.primary`、`.danger`、`.ghost`）、`.field`、`.badge`（`.read .write .danger`）、`.table`、`.toast`、`.modal`、`.mask`、`.tabs`、`.meter`；手機寬度不橫向捲；只用系統字型；沒有 `url()`、沒有 `@import`。

`tests/js/test_appkit.js`（照現有四個測試的做法自備最小的假 DOM、假 `fetch`、假 `sessionStorage`、假 `history`）：

- 啟動：網址有 `#t=abc` → `replaceState` **先於** `fetch` 被叫、之後網址沒有 `abc`；`/api/enter` 的內容是那張票；成功後 `sessionStorage` 有 token、`ready` 的函式被叫。
  沒有票、有存的 token → 打 `/api/me` 而且帶 `X-SYNOX-App`。兩個都沒有 → 一個請求都沒有、出現「請從 SYNOX 打開」的遮罩、`ready` 的函式**沒**被叫。`/api/me` 回 401 → token 被清掉、遮罩。
- 每個 `/api/` 請求都有 `X-SYNOX-App`、`credentials` 是 `omit`；整個檔沒有 `document.cookie`。
- `act`：值變字串、空欄位不送；409 confirm → 叫確認框 → 確定後帶 `confirmed: true` 重送、取消後 reject `cancelled` 而且沒有第二個請求；`invalid` 把 `fields` 交回。
- `read`：參數正確編碼（中文、`&`）。連不上 → 遮罩、文字對；401 → 另一種文字。`form`：必填、`choices`、欄位錯誤顯示在對的欄位。
- 人還在：`isTrusted: true` 的 `mousemove`、`visible`、離上次 61 秒 → 送一次 `POST /api/alive`；馬上再發十個事件 → 沒有第二個；`hidden` → 不送；`isTrusted: false` → 不送；
  完全沒有事件、時鐘推一小時 → **一個請求都沒有**；剛 `read` 成功 30 秒內的事件 → 不送；alive 失敗 → 沒有遮罩、沒有 toast、不重試。
- `download`：`available: false` → 沒有請求、顯示 `reason`；可用 → 第一個請求是表單格式、有 `t`、沒有 `confirmed`；確認框顯示伺服器給的字；按下載後建立的表單有 `t`、`confirmed=1` 與參數、`method` 是 post；按取消 → 沒有表單。
- 檔案裡沒有 `setInterval`、`innerHTML`、`eval`、`serviceWorker`、`cookie`、`http://`、`https://`（`tests/test_appkit.py` 直接讀檔檢查；CSS 沒有 `url(`、`@import`）；`/*{{CONSOLE_URL}}*/` 恰好出現一次。

驗收：測試過；`appkit.js` ≤ 650 行、`appkit.css` ≤ 400 行（提案值；超過先回報再說）。

### WP4 主機台畫面與 API（等 WP2）

檔案：`src/synox/web/server.py`（`api()` 開頭把 `/api/apps` 前綴轉給 `apps.web_api.route`，寫法照 `/api/runtime/` 那三行：`:529-532`；`route()` 加 `POST /apps/<name>/open` → `apps.web_api.open_handoff`，放在 `/login` 那幾條旁邊）、
`src/synox/web/static/apps.js`＋`apps.css`（新；用 `INCLUDES`／`<!-- include: … -->` 的機制放進 `app.html`，`server.py:148-173`）、`src/synox/web/static/app.html`（側欄一個標記的掛點、工具頁卡片的掛點；主機台的 CSP 是 `form-action 'self'`，交接的表單送往自己，不用改）、
`src/synox/web/static/tools.js`（`renderTool` 裡在面板旁邊叫 `SynoxApps.card(panel, tool)`；`server.py` 的 `tools()` 每個工具多回 `"app": true/false`）、`tests/js/test_apps.js`、`tests/test_app_console.py`、新 `docs/apps-api.md`（C4–C12 的合約，之後要改先改文件）。

畫面：

1. **側欄常駐標記**（`#side-foot` 上方）：`running > 0` 才顯示「● N 個工具服務開著」（有 `suggest_close` 的時候用提醒色、字變成「● 記帳的服務很久沒用了」；有「一直開著」的工具時一直是提醒色）。點了開一個小清單：每個開著的一列（標題、開多久、多久沒用、「打開」「關掉」）、底下「全部關掉」「這是什麼？」。
2. **工具頁的卡片**（有 app 的工具才有，放在說明與指令之間）：標題「完整畫面」。關著：一句 `explain.what`＋按鈕「開啟」；開著：狀態徽章「開著 · 12 分鐘沒用」＋「打開」「關掉」「先留著」（只有 `suggest_close` 時）；`error`／`problem`：原因＋下一步。
   底下可展開「這是什麼？為什麼要關？」（三句說明＋「什麼叫有在用」那句）與「最近紀錄」（`/api/apps/log` 前 5 筆，用事件與代碼對到 `TEXT` 裡的白話：「10:20 你開了記帳的服務」）。不是擁有者：只有「打開」（開著時）與一句「服務由擁有者開關」。
3. **「打開」是一個表單**：`<form method="post" action="/apps/<name>/open" target="_blank" rel="noopener noreferrer">`＋隱藏欄位 `csrf`。不用 `window.open`、不用 `fetch`（真的導覽才不會被擋彈出視窗，也不必把票交給主機台的 JS）。
   「開啟」之後卡片上出現「打開」，使用者再按一次才開新分頁（**開服務與打開畫面是兩個動作**，第三版）。
4. **卡片上的閒置設定**（C10；ADR §4.2 的表與字）：一行現況「沒在用的時候：<policy.text>」，每個看得到的人都看得到；擁有者旁邊有「改」→ 六個選項的單選
   （120 分鐘〔建議〕／30 分鐘／自己填 N／只提醒／一直開著／不開放），「自己填」有一個數字欄（5–1440）。選「一直開著」先跳警告、按「我知道，一直開著」才送（帶 `understood: true`）；
   之後卡片與側欄清單上那個工具一直帶一個提醒色的「一直開著」標籤。選「不開放」而它正開著 → 先問「會先把它關掉，確定？」。
5. **第一次開**：`explained` 是 false 時先出一個對話框（三句說明）＋「知道了，開啟」／「先不要」；按了才送 `start`（請求帶 `{"explained": true}`，伺服器記進 `apps.json`）。
6. 畫面上**不顯示 app 的網址**、沒有「複製連結」、不提書籤。埠號只在「進階」的小字。
7. 更新：進到工具頁、按任何按鈕之後、以及頁面看得到時每 30 秒抓一次 `GET /api/apps`（`document.hidden` 時不抓）。主控頁不用另外做，`system.tool_apps` 會自己出現在任務清單。

測試 `tests/test_app_console.py`（用 `tests/test_web.py` 的 `Client`＋假 listener）：

- C7 每條 `/api/apps…` 路由的權限（成員 `start`／`stop`／`policy`／`log` → 403；成員的清單沒有 `can_manage`、有 `policy`、看不到自己看不到的工具）、CSRF、`start` 的每種錯誤碼、`explained` 只記一次、`/api/tools` 的 `app` 欄位、清單形狀符合 C7、`log` 的上限、`/policy` 的每種 `mode`。
- 交接 `POST /apps/counter/open`：沒登入 → 401 頁；`csrf` 欄位沒有／錯 → 403；`Origin` 是別的來源 → 403；`Sec-Fetch-Site: cross-site`／`same-site` → 403；`Origin: null`＋`same-origin` → 過；
  服務關著 → 白話頁、**沒有發票**、服務沒有被開起來；看不到這個工具的成員 → 白話頁；過了 → 303、`Location` 以 `http://127.0.0.2:<埠>/#t=` 開頭、有 `no-referrer` 與 `no-store`；
  那張票真的能在 `AppClient.enter` 用、而且只能用一次；連按 21 次 → 最舊的那張失效；稽核有 `handoff`、裡面沒有票。`GET /apps/counter/open` → 404／405。
- 現有 `/api/…` 的 `Sec-Fetch-Site` 檢查（WP0）不影響這一條（它不在 `/api/` 底下，有自己的檢查）。

`tests/js/test_apps.js`：三種狀態的卡片、不是擁有者的樣子、第一次的對話框、「打開」是 `method=post`、`target=_blank`、`rel` 有 `noopener` 的表單而且有 `csrf` 欄位、整個檔沒有 `window.open`、沒有 `127.0.0.2`；
六個閒置選項、「一直開著」的警告流程（沒按確認不送請求）、「不開放」時沒有開啟的按鈕、成員只看得到現況那一行；`document.hidden` 不輪詢；字串都在 `TEXT`。

驗收：測試過；`render_app()` 產生的頁面仍只有 nonce 的 script／style（現有 `test_web.py` 的 CSP 測試不改就過）；主流程的字裡沒有 port、session、token、CSRF（寫一個讀 `apps.js` `TEXT` 的測試）。

### WP5 Telegram 指令、提醒、doctor（等 WP2）

檔案：`src/synox/web/apps/commands.py`（新，由 `apps.install` 呼叫）、`src/synox/doctor.py`、`tests/test_app_commands.py`、`docs/tools.md`（指令一覽加一段）。

- 指令照 C9。`/apps`（READ）、`/app_close`（WRITE）給 AI；`/app_open`：`ai=False`、`interactive=True`、`owner_only=True`、`private_only=True`，處理函式叫 `manager.start(name, by=user, via="telegram")`。
- 回覆的字照 C9 與 ADR「給使用者的說法」；功能不可用時說原因。
- 閒置提醒的兩則訊息在 WP2 的 `tick()`（純文字附指令）。加碼（不在驗收內）：SDK 的按鈕好接的話，在提醒下面加「關掉」「先留著」兩顆；接不乾淨就不做。
- `doctor`：在「網頁介面」那行下面多一行 `工具服務：開放（本機位址 127.0.0.2，埠 8841–8856，最多同時 3 個；預設 30 分鐘沒用提醒、120 分鐘自動關，各工具可以自己設）`／`關（web.apps.enabled=false）`／`容器版還沒開放`；
  再讀 `data/apps_state.json`：`running` 不是空的 →「上次紀錄：記帳開在 8841（由程序 1234 寫的；SYNOX 沒在跑的話這些都已經關了）」。**doctor 不連任何埠。**
  有 app 宣告掛不起來的（`problems`）、有工具設成「一直開著」的，各列一行 ⚠️。

測試：

- 三個指令在個人版／伺服器版成員／擁有者的結果；群組裡打 `/app_open` 被擋；名字比對（`money`、`記帳`、`💰 記帳`、`記帳本`、大小寫）；`all`；不存在的名字列出有哪些；`blocked` 的回覆。
- `/app_open` 的回覆裡**沒有** `127.0.0.2`、沒有任何票，有主機台的網址。
- **排程這條路（審查發現 2）**：`/schedule_add 03:00 /app_open counter` → 被拒（回覆說不能排）、沒有存進排程；直接往排程的 store 塞一筆 `/app_open counter` 再讓 runner 觸發（照 `tests/test_schedule.py` 的做法）→ 沒有開、擁有者收到「沒有跑成」；
  AI 的工具清單裡有 `apps`、`app_close`、沒有 `app_open`（照 `tests/test_agent.py`）；AI 叫 `schedule_add` 帶 `/app_open …` → 一樣被拒。`/schedule_add 03:00 /app_close all` → 可以（關是安全的）。
- 連動規則裡直接叫 `manager.start(name, by=owner, via="system")` → `forbidden`。
- doctor 的四種輸出（用假的狀態檔與假的容器證據）。

驗收：測試過；`/help` 多一頁「🧩 工具服務」而且三個指令的說明是白話。

### WP6 SDK 與文件（等 WP1、WP3）

- `src/synox/sdk/author.py`：`SDK_VERSION = "0.2.3"`；重產單檔版（`scripts/build_synox_sdk.py`，測試會比對兩份）。`docs/sdk.md`「SDK 版本」補一句 0.2.3 加了什麼。
- `src/synox/sdk/__init__.py`：`synox-sdk init <資料夾> --kind python --app`：多產生 `app/index.html`（第一個 script 是 kit、一個 `<main id="app">`）、`app/app.js`（`SynoxApp.ready` 之後讀一次、畫一張表、一個 `SynoxApp.form`）、`app/app.css`（空殼）、`pack.json` 的 `web.app`（帶 `"kit": 1`、不帶 `exports`），`pack.py` 範本多一組「核心函式＋指令＋`app_read`／`app_action`」。**不加 `--app` 時產生的東西跟現在一模一樣。**
- `synox-sdk check`：自然會跑到 WP1 的規則；確認錯誤訊息從這條路出得來。
- 文件：新 `docs/tool-apps.md`（給寫工具的人）：三分鐘範例；`web.app` 每個欄位；「框架是宣告來選用的，沒宣告就沒有 app 這一面；框架在 SYNOX 不在工具裡，為什麼」；`app_read`／`app_action`／`app_export`／`AppError`／`check_values`／`Download`／`csv_bytes`；kit 的每個函式；
  怎麼用 `AppClient` 寫測試；能做與不能做的事（不能連外、不能內嵌程式、不能輪詢、不要自己送 alive、不要自己 `fetch`、不要碰 cookie 與 service worker）；匯出的規則；「有在用」的定義；
  **「哪些是伺服器保證的、哪些只是畫面會照做」那張表（ADR §3.5）——不要寫「工具改不了」這種話**；畫面上的字怎麼寫。
  `docs/pack-format.md`（連過去）；`docs/security.md`「網頁介面」加一節「工具服務」（ADR §3 的決定表、對策表、§3.5、「擋不住的」，白話）；`README.md` 功能清單一行；`CHANGELOG.md`；`docs/AGENT.md` Map。
- **不做**：`synox-sdk` 的本機預覽伺服器（會開埠）。

測試 `tests/test_sdk_app.py`：`init --app` 產生的資料夾過第 1、2 關、沒有任何提醒、`specs_of` 沒有 problem、用 `AppClient` 能拿票進門、讀、做一個動作；不加 `--app` 的輸出跟基準逐檔相同；單檔版與正本一致。
`docs/tool-apps.md`、`docs/security.md` 新增的段落裡沒有「改不了」「繞不過」「無法繞過」（一個讀檔的測試）。

驗收：測試過；文件裡的範例程式就是測試裡跑的那一份（照 `tests/test_pack_docs.py` 的做法，若它有檢查文件範例的機制就接上）。

### WP7 記帳 app（SYNOX_Libs；等 WP1–3、6 合進 SYNOX 的 `feat/tool-apps`）

照 SYNOX_Libs 分支 `feat/tool-apps` 的 `docs/adr/0003-tool-apps-and-money-app.md`。測試時 `SYNOX_HOME` 指到 SYNOX 的這個工作樹（`scripts/_synox.py` 的規則），只 import、不改它。

---

## 9. 只有擁有者能做的驗收（別台電腦、真的瀏覽器；開發機不做）

### G1 出貨前的關卡（第三版；先做這個，沒過就停）

整個第三版的進門方式建立在幾個**沒有在任何瀏覽器上看過**的假設上。WP2 合好之後、WP4 開工之前，擁有者（或那台電腦上的 session）在別台 Windows 電腦做：

| # | 做什麼 | 要看到 | 沒看到代表 |
|---|---|---|---|
| G1-1 | 開一個服務 | 開得起來；**Windows 沒有跳防火牆的詢問**；`netstat -ano` 看到的是 `127.0.0.2:8841`，不是 `0.0.0.0` | `127.0.0.2` 這條路不能用 → 回報，改用 ADR §3.1 的備案 |
| G1-2 | 從主機台按「打開」 | 新分頁是記帳畫面；網址列是 `http://127.0.0.2:8841/`，**後面沒有 `#t=…`** | 票沒有經過轉址帶到，或共用元件沒把它拿掉 |
| G1-3 | 在那個分頁按 F12 → Network → 點任何一個送往 `127.0.0.2` 的請求 → Request Headers | **沒有 `Cookie`**（特別是沒有 `synox_session`）；`/api/` 的請求有 `X-SYNOX-App`、有 `Sec-Fetch-Site: same-origin` | 主機不同卻還帶 cookie → 整個設計的前提不成立，停 |
| G1-4 | 同一個分頁按重新整理 | 還在裡面、不用重新打開 | `sessionStorage` 沒留住 → 回報（可用但每次重新整理都要重來） |
| G1-5 | 另開一個分頁，直接在網址列打 `http://127.0.0.2:8841/` | 只看到「請從 SYNOX 打開這個工具」 | 有別的進門的路 |
| G1-6 | F12 → Application → Service Workers | 這個來源底下沒有任何 worker | `worker-src 'none'` 沒生效 |
| G1-7 | Edge 與 Chrome 各做一次 G1-2、G1-3、G1-5 | 一樣 | 記下哪個瀏覽器、哪一步不同 |
| G1-8（選做） | 另一台電腦／手機連 `http://<這台的區網 IP>:8841/` | 連不上 | 綁到不該綁的位址，立刻停 |

### 功能驗收（G1 過了之後）

| # | 做什麼 | 預期 |
|---|---|---|
| R1 | 主機台工具頁按「開啟」，再按「打開」 | 第一次先看到三句說明；新分頁是記帳畫面，頁首有工具名與「關閉服務」 |
| R2 | 在 app 分頁按 F12，主控台執行 `fetch("http://127.0.0.1:8830/api/me", {credentials: "include"}).then(r => r.status)` | 被瀏覽器擋（CORS 錯誤），或 401／403；**拿不到內容** |
| R3 | 同上 `fetch("http://127.0.0.1:8830/api/packs/reload", {method: "POST", credentials: "include"})` | 被擋或 401／403；主機台沒有重新載入 |
| R4 | 開兩個 app，在 A 的主控台 `fetch("http://127.0.0.2:<B 的埠>/api/me")` | 被擋或 401 |
| R5 | 記一筆、改一筆、刪一筆（刪要按確認） | Telegram `/money_list` 看得到同樣的結果；反過來在 Telegram 記的，畫面重新整理看得到 |
| R6 | 按「關閉服務」，再重新整理 app 分頁 | 連不上；主機台標記消失；`netstat -ano` 找不到 8841 |
| R7 | 關掉之後馬上再開、再打開 | 同一個埠、正常進得去（沒有「埠被占用」） |
| R8 | 在主機台按登出，回到還開著的 app 分頁做任何事 | 「請從 SYNOX 再打開一次」 |
| R9 | 重開 SYNOX | 所有服務都是關的 |
| R10 | 把記帳設成「自己填 5 分鐘」。開著 app 分頁、切到別的分頁放 6 分鐘 | 服務被關（背景的分頁不算在用） |
| R11 | 同樣設定，app 分頁留在眼前，每分鐘動一下滑鼠，共 8 分鐘 | 服務沒被關；主機台的「多久沒用」一直很小 |
| R12 | 同樣設定，app 分頁留在眼前但完全不碰滑鼠鍵盤 6 分鐘 | 服務被關 |
| R13 | 設成「一直開著」 | 先看到警告；之後卡片一直有「一直開著」的標籤；重開 SYNOX 後它是關的 |
| R14 | 個人版在記帳的帳目頁按「匯出」 | 先看到「沒有加密」那段字；按下載後瀏覽器存了一個 `.csv`，頁面沒有跳走；Excel 打開中文沒有亂碼；備註是 `=1+1` 的那一筆在 Excel 裡是文字 |
| R15 | 另開一份伺服器版的設定做同一件事 | 按鈕是灰的、有一句說明；沒有檔案被下載 |
| R16 | Telegram 打 `/app_open money` | 回覆裡是主機台的網址；照著去工具頁按「打開」進得去 |
| R17 | Telegram 打 `/schedule_add 03:00 /app_open money`；再跟 AI 說「幫我明天早上自動把記帳的畫面開起來」 | 兩個都被拒；`/schedule_list` 裡沒有它 |

## 選項表（實作中遇到要選的；預設照建議，不用回頭問）

| 題目 | 選項 | 建議（預設做這個） |
|---|---|---|
| 重新載入工具時 | 只關那一個／全部關 | **全部關**（簡單、安全） |
| 提醒用按鈕還是文字 | 兩顆按鈕／純文字附指令 | **純文字**；按鈕是加碼 |
| 稽核紀錄要不要進保管箱 | 明文 JSONL、只有固定欄位／加密 | **明文、只有固定欄位**（要能在 SYNOX 沒開時用記事本看） |
| 埠被別的程式占住 | 回報、不換／自動換下一個 | **回報、不換**（C12） |
| 開第二個分頁 | 再按一次「打開」／分頁之間共用登入 | **再按一次**（登入只放在那個分頁） |

擁有者已經回答的在 ADR 0023「擁有者已經決定的」；**還沒定的兩題**（AI 能不能開服務、伺服器版加密匯出的格式）照 ADR「現在先這樣」做：`/app_open` 不給 AI 也不給排程；伺服器版的匯出一律擋。這兩題不要自己往前做。

## 驗收（整體）

- 八個工作包（WP0–WP7）各自的驗收都過；全部測試（加上面那個 `--deselect`）過；新增的測試沒有任何一個真的開埠。
- `git grep -n "_Server(" src/` 只有 `server.py` 原本那一處與 `web/apps/listen.py`；`src/synox/web/apps/` 沒有 `Set-Cookie`、沒有讀 cookie、沒有 `logging.exception`。
- 沒有宣告 `web.app` 的工具：安裝報告、信任層級、工具頁、`/help` 跟合併前一模一樣。
- 給使用者看的每一句新字都在某個 `TEXT` 表裡，主流程沒有 port、session、token、CSRF、origin；新增的文件沒有「工具改不了／繞不過」這類話。
- **G1 過了**（第 9 節），結果寫回 ADR 0023「這份 ADR 沒有驗證的事」。
- ADR 0023 的狀態改成「已採用」並補上實際的分支與 commit；這份計畫的狀態改成「已修」＋ merge commit。

## 不要做的事

- 不要在這台電腦開埠、跑伺服器、開瀏覽器、動防火牆；不要為了「驗一下」而破例。
- 不要改 `vendor/`、不要改 `web.panel`／`web.api` 的行為、不要改三份教學頁、不要改主機台的綁定與登入。
- **不要在 app 的埠上用 cookie**（不讀、不發）；不要加「帶著主機台的 cookie 就進」或「本機直接開網址就進」；不要在任何畫面、回覆、文件裡給 app 的網址或建議書籤。
- 不要加 CORS、不要加 `'unsafe-inline'`、不要讓 `config.json` 或環境變數決定 app 綁哪個位址、不要讓工具自己開伺服器。
- 不要把參數的值、token、票、例外的訊息寫進稽核或 log。
- 不要做容器版、每個 app 一個主機名、WebSocket、kind=cli 的 app、開機自動開服務、在 Telegram 改閒置設定、自動換埠——都在 ADR 的「不做」。
- 不要做伺服器版的加密匯出（格式還沒定）、不要讓 AI 或排程開服務（還沒定）、不要做任何「人不在電腦前也連得到」的東西（通道、雲端轉送；那是另一份 ADR）。
- 不要讓工具在 `pack.json` 裡替自己選閒置設定；不要在共用元件裡放計時器去送請求。
- 不要合併、不要推；不要改這份計畫的合約而不回報。
