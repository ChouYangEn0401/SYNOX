# 工具服務的介面合約（給維護者；之後要改先改這份）

決定與理由在 [ADR 0024](adr/0024-tool-apps-services.md)（第三版）；實作計畫的合約 C1–C12 在
[lab/2026-11-14-tool-apps-implementation-plan.md](lab/2026-11-14-tool-apps-implementation-plan.md)。這份是**現在程式實際的樣子**。
給寫工具的人看的是 [tool-apps.md](tool-apps.md)。

## 位址與開關

- 主機台 `http://127.0.0.1:<web.port>`（不變）；工具的畫面 `http://127.0.0.2:<埠>`。`127.0.0.2` 是 `src/synox/web/apps/listen.py` 的常數
  `APP_HOST`，設定檔沒有任何欄位能改；整個工具服務只有 `listen.open_listener` 會開埠。
- `config.json`：`web.apps = {enabled, port_first(8841), port_count(16), max_running(3), idle_suggest_min(30), idle_close_min(120)}`。
  埠範圍不能包含 `web.port`（沒寫 `port_first` 時，預設範圍自動挪到 `web.port` 後面）。
- 開：只有擁有者，只收主機台的按鈕（`via="web"`）與 Telegram 自己打的 `/app_open`（`via="telegram"`）。AI、排程、連動規則、工具畫面都開不了。
  不能用：`web.enabled`／`web.apps.enabled` 是 false、`/web_off` 之後、在容器裡。
- 一個工具配一個埠，配過就永遠是它的（`data/apps.json` 的 `ports`）；被別的程式占住 → 錯誤、不換埠。關是同步的，5 秒關不掉 → 「關不乾淨」，
  那個埠到 SYNOX 重開之前不用。SYNOX 每次重開，所有服務都是關的。

## app 的埠（`AppSite.handle`）

- 不讀、不發任何 cookie。Host 一定是 `127.0.0.2:<埠>`；帶 `Forwarded`、`Via`、`X-Forwarded-*`、`Service-Worker` → 403；只收 GET、POST。
- 每個回應：`nosniff`、`no-referrer`、`no-store`、`X-Frame-Options: DENY`、COOP／CORP `same-origin`、CSP
  `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; worker-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'`；
  沒有 `Access-Control-*`。開服務之後第一個 `GET /` 多 `Clear-Site-Data: "storage"`。

| 路由 | 要登入 | 內容 |
|---|---|---|
| `GET /`、`/_synox/kit.js`、`/_synox/kit.css`、`/<root 裡的檔>` | 不用 | 記憶體快照（有鎖就逐檔對 SHA-256） |
| `POST /api/enter` `{"ticket"}` | 交接票 | `{"ok", "token", "me"}` |
| `GET /api/me` | 要 | 見下 |
| `GET /api/read/<名>?k=v` | 要 | `{"ok", "data"}` |
| `POST /api/do/<名>` `{"values", "confirmed"?}` | 要 | 危險的沒有 `"confirmed": true` → 409 `confirm`（伺服器不存確認狀態） |
| `POST /api/export/<名>`（表單，`t`＝token、`confirmed=1`） | 要 | 個人版：先 409 提醒、再下載；伺服器版 403 `export_encrypted_only` |
| `POST /api/alive`、`/api/keep`、`/api/leave`、`/api/close-service`（擁有者） | 要 | `{"ok": true}` |

- `/api/` 一律：`Sec-Fetch-Site` 有值就要 `same-origin`；`Origin` 的 netloc 要等於 Host（`null` 只在 `same-origin` 時收）；POST（匯出除外）要 JSON 物件。
- 登入：`X-SYNOX-App` 標頭（匯出放表單欄位 `t`）。每個請求都查：token 的雜湊、12 小時內、**上一層還 `alive()`**（本機＝主機台的那個登入還在；
  手機入口＝那一條入口還開著）、這個人現在仍看得到這個工具。每人每個 app 最多 5 個登入。
- 動作：名字要在 `web.app.actions`、有同名指令且危險程度一樣；權限問 `registry.authorize(user, node, TYPED)`；欄位走 `kit.check_values`
  （第一步是門禁核心的基本檢查）；工具丟 `kit.AppError` → 照它的 status／訊息；別的例外 → 500「出錯了：<類別名>」。
- 來源（ADR 0026 對接 e）：讀與動作在 `guard.origin` 底下跑（外面沒設＝web，surface 跟主機台那個登入一樣；外面是 remote 就沿用）。
  來源是 remote：危險動作 403 `remote_no_danger`、匯出 403 `remote_no_export`，工具的函式不會被叫到；`/api/me` 的 `remote` 是 true。
- 錯誤：`{"ok": false, "code", "error"}`；`code`：`login` 401、`origin`／`forbidden`／`remote_no_*`／`export_encrypted_only` 403、`not_found` 404、
  `invalid` 400（多 `fields`）、`confirm` 409（多 `confirm`）、`refused`、`too_large` 413、`error` 500。

`GET /api/me`：`{"ok", "user": {id, name, owner}, "app": {name, title, app_title, version}, "reads", "actions": {名: {effect, summary, fields}},
"exports": {名: {available, reason}}, "console_url", "policy": {mode, suggest_min, close_min, text}, "alive_every_s": 60, "remote"[, "remote_until"]}`。

## 主機台這一側（`web/apps/web_api.py`）

- `GET /api/apps`（登入的人；成員只看得到自己看得到的工具，`can_manage` 只有擁有者 true）；`POST /api/apps/<名>/start|stop|keep|policy`、
  `/api/apps/stop-all`、`GET /api/apps/log?limit=`（擁有者）。清單沒有 app 的網址，`open` 是主機台自己的表單位址。
- `POST /apps/<名>/open`（表單、`csrf` 欄位、來源判斷同登入）：服務要開著（打開不會順便開服務）→ 303 到 `http://127.0.0.2:<埠>/#t=<票>`。
  票 256 位元、30 秒、只能用一次、綁（app、埠、人、主機台的那個登入）；每個 app 最多 20 張，服務一關全部作廢。

## 有在用、閒置

- `touch` 只在帶有效登入的 `/api/` 請求（enter、me、read、do、export、keep）與 `/api/alive`（同一個登入 60 秒最多一次）。靜態檔不算。
- 每個工具的設定（`data/apps.json` 的 `policy`）：`auto`（`close_min` 5–1440；大於 30 時 30 分鐘先提醒）、`suggest`、`keep`（要 `understood: true`）、
  `blocked`（開著的先關）。沒設定＝設定檔的預設（30 提醒、120 關）。「一直開著」不保存「開著」。
- runtime 任務 `system.tool_apps`：只有開著的時候每 60 秒跑一次 `tick()`；spec 不見、變成有問題、被健康檢查隔離 → 關。

## 稽核與 log

- `data/apps_audit.jsonl`：欄位固定（`at event app by via action effect ok code confirmed port bytes reason mode close_min`），每個欄位白名單檢查，
  不在名單的寫成 `other`；沒有參數的值、檔案內容、token、票、cookie、例外的訊息。1 MB 換檔。
- log：`audit.safe_trace(e)`（類別名＋檔名:行號 函式名），不寫例外的訊息。
- `data/apps_state.json`：`{"pid", "at", "running": [{name, port, since}]}`，給 `doctor` 讀；SYNOX 啟動與結束時寫成空的。
