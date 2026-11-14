# 給工具附一個完整的網頁畫面（工具服務）

你的工具平常只在 SYNOX 裡聽指令。宣告 `web.app` 之後，擁有者可以在 SYNOX 開一個**只有這台電腦打得開**的網頁，看你的工具的完整畫面；
不用的時候關掉。決定與理由在 [ADR 0024](adr/0024-tool-apps-services.md)；伺服器那一側的合約在 [apps-api.md](apps-api.md)。

**框架是宣告來選用的**：沒寫 `web.app` 的工具沒有這一面，沒有任何埠、沒有任何路由。登入、來源檢查、閒置、稽核、匯出規則全部在 SYNOX，
不在你的工具裡——所以每個工具的畫面都是同一套保護，你也不用寫任何安全程式。

## 三分鐘範例

```bash
synox-sdk init my-notes --kind python --name my-notes --title "我的筆記" --app
synox-sdk check my-notes
```

產生的東西：`pack.json` 多一段 `web.app`、`app/index.html`（第一個 `<script>` 是 SYNOX 的共用元件）、`app/app.js`、`app/app.css`，
`pack.py` 多一組「核心函式＋指令＋`app_read`／`app_action`」。不加 `--app` 產生的東西跟以前一模一樣。

```python
def install(app, pack):
    def add_core(user, text): ...                                  # 核心函式：指令與畫面都叫它
    kit.command(pack.group, "add", add, "記一筆", effect=WRITE, fields=[Field("text", "要記的內容", required=True)])
    if hasattr(pack, "app_read"):                                  # 舊版 SYNOX 沒有：照樣能用指令
        pack.app_read("items", lambda user, params: {"items": items(user)})
        pack.app_action("add", lambda user, values: {"count": add_core(user, values["text"])})
```

```js
SynoxApp.ready(function () {
  SynoxApp.read("items").then(function (d) { /* 畫表 */ });
  document.getElementById("app").appendChild(SynoxApp.form("add", { onDone: reload }));
});
```

## `web.app` 的欄位

| 欄位 | 說明 |
|---|---|
| `root` | pack 裡的一個子資料夾，畫面的檔都放這裡（`.html .js .css .json .png .jpg .jpeg .webp .svg .ico .woff2`；最多 100 個、單檔 512 KB、合計 3 MB） |
| `entry` | `root` 裡的入口頁；**第一個 `<script>` 一定是 `<script src="/_synox/kit.js"></script>`** |
| `title` | 選填，畫面的標題（一行、24 字內） |
| `kit` | 必填，照哪一版共用元件寫的（現在是 `1`） |
| `reads` | 讀資料的名字（每個都要 `pack.app_read` 掛函式） |
| `actions` | `{"名字": "WRITE"|"DANGER"}`：**每個動作都要有同名的指令、同樣的危險程度**。權限、欄位檢查、稽核都照那個指令 |
| `exports` | 選填，匯出的名字（`pack.app_export` 掛函式） |
| `remote` | 選填，`true`＝這個畫面可以從手機用（擁有者另外打開手機入口，ADR 0026）；危險動作與匯出在手機上一律不行 |

工具**不能**替自己選閒置設定（多久沒用就關由擁有者在 SYNOX 選）；多寫的鍵安裝時會被拒。

## 工具端（python）

| 介面 | 說明 |
|---|---|
| `pack.app_read(name, fn)` | `fn(user, params: Dict[str, str])` → 可以轉 JSON 的東西 |
| `pack.app_action(name, fn, *, describe=None)` | `fn(user, values: Dict[str, str])` → `dict`；`describe(user, values)` → 危險動作確認框的那一句 |
| `pack.app_export(name, fn)` | `fn(user, params)` → `kit.Download(filename, "text/csv; charset=utf-8", data)` |
| `kit.AppError(message, code="refused", status=409)` | 在函式裡丟：`message` 原樣顯示給使用者。別的例外的訊息**永遠不會**出現在回應、log、稽核 |
| `kit.check_values(fields, values)` | 已經照名字放好的值 → `(clean, 缺的必填, 錯誤)`；第一步是 SYNOX 的基本檢查（長度、怪字元），訊息跟 Telegram 那條同一句 |
| `kit.csv_bytes(header, rows)` | CSV（BOM、CRLF、防試算表公式）。**每個工具的 CSV 都用它，不要自己組** |
| `kit.caller()`、`kit.require_human()` | 這一次是誰叫的（`web`、`remote`、`ai`…）；自己再檢查一次用 |

名字沒寫在 `web.app` 裡就掛 → `ValueError`。

## 共用元件（`window.SynoxApp`）

| 函式 | 說明 |
|---|---|
| `ready(fn)` | 進門完成之後叫 `fn(ctx)`；`ctx = {me, app, actions, reads, exports}`。沒進門（不是從 SYNOX 打開的）就不叫 |
| `read(name, params)` | 讀；失敗會自己顯示 |
| `act(name, values, opts)` | 做一個動作；危險的會先跳確認框；欄位錯誤回 `{fields}`；`opts.quiet` 不顯示 |
| `form(actionName, opts)` | 照那個指令的欄位產生表單（必填、下拉、欄位下面的錯誤）；`opts.onDone(data)` |
| `download(name, params)` | 匯出（先提醒「沒有加密」，按下載才存檔）；手機上與伺服器版不能匯出 |
| `toast`、`confirmBox`、`el`、`clear`、`fmt.number`、`fmt.date`、`keep` | 小工具 |

樣式：`/_synox/kit.css` 的 `.card .btn .primary .danger .ghost .field .badge .table .tabs .meter .toast`，深色模式自動跟著系統。

## 能做與不能做

- **不能**連到外面的網址（CSP 擋；安裝時的檢查也會拒或提醒）、**不能**內嵌程式（`<script>…</script>`、`onclick=`）、不能用 `<iframe>`、`<base>`。
- 不要自己 `fetch`、不要輪詢、不要自己送「人還在」、不要碰瀏覽器存的登入資料、不要註冊背景程式（service worker）。全部經 `SynoxApp`。
- 「有在用」只算真的有人在畫面上做事（讀、按、存），或分頁在眼前而且有動滑鼠、打字、捲動、點、滑；分頁開著但切走了不算。
- 匯出：個人版下載沒加密的檔（先講清楚）；伺服器版一律拒（加密匯出還沒做）；從手機不能匯出。

## 哪些是伺服器保證的、哪些只是畫面會照做

你的畫面程式跟共用元件在同一頁、同一個執行環境。所以要講清楚：

| | 內容 | 惡意的畫面程式能不能跳過 |
|---|---|---|
| 伺服器那一側的規則 | 誰能進、每個動作的欄位檢查與權限、危險程度、伺服器版不給沒加密的匯出、稽核、閒置設定、來源檢查 | 不能 |
| 畫面那一側的東西 | 危險動作的確認框、匯出前的提醒、頁首那一列與「關閉服務」、「人還在」只在有輸入時送 | **能**：它可以不問就做、不提醒就匯出、畫一條假的頁首列、假裝人還在 |

所以安裝報告會照實寫：裝了附畫面的工具，它的畫面可以不經使用者同意讀、改、匯出這個工具裡的所有資料（僅限宣告過的動作）。
官方工具一律經共用元件、不自己連線（工具庫的測試會擋），確認框與提醒才是可靠的。可信的狀態與開關在 SYNOX 的主機台。

## 收緊範圍：`callers`、`stepup`

`pack.json` 可以寫 `"callers": {"指令名": ["human"]}`（這個指令只收你本人；AI、排程、手機入口都不行）與 `"stepup": ["指令名"]`
（一定要先用手機驗證器解鎖）。畫面上的動作對到同名的指令，所以收緊也套在畫面上（手機入口的來源是 `remote`）。
程式裡可以用 `kit.caller()` 看這一次是誰叫的、`kit.require_human()` 自己再檢查一次（多一層，不是邊界）。詳見 [pack-format.md](pack-format.md)「範圍」。

## 測試

用 `synox.web.apps.testing`（不開埠）：

```python
from synox.web.apps.testing import AppClient, FakeListen

manager = apps.of(bot.app)
manager.listen = FakeListen()
manager.start("my-notes", by=owner, via="web")
client = AppClient(manager, "my-notes")
client.enter(client.open_from_console(owner))
assert client.read("items")[0] == 200
assert client.do("add", {"text": "買牛奶"})[0] == 200
```

## 畫面上的字

白話繁體中文；不要出現 port、session、token、CSRF、origin 這類詞。動作的三種標示沿用 SYNOX 工具頁的字：唯讀／會寫入／危險：會先問你。
