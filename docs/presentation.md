# 呈現層：與通道無關的內容區塊（`synox.present`）

> 給維護者。**預設關閉**：`config.json` 沒寫 `presentation`（或 `"enabled": false`）時，AI 回覆跟以前一模一樣、原樣送出。

```
來源（Markdown、純文字、程式產生的卡片）──來源 adapter──▶ 區塊清單（Document）──輸出 adapter──▶ Telegram／Discord／網頁
```

AI 習慣寫 Markdown：Telegram 會把 `**粗體**`、`| 表格 |` 原樣顯示，超過 4096 字也不會切；Discord 的 2000 字切割會切斷 ``` 圍欄。
呈現層先把 AI 的字解析成區塊，再照每個通道能顯示的樣子畫出來、切成放得下的幾則。

## 怎麼開

```json
"presentation": { "enabled": true }
```

- 放在 `config.json` 最外層（`SynoxConfig.presentation`，`config.parse_presentation` 檢查：`enabled` 只收 `true`／`false`，寫錯＝`ConfigError`）。
- 只接**AI 回覆送出**那一條：`agent/loop.py` 的 `AgentLoop.say`（私訊、網頁）與 `agent/room.py` 的 `RoomAgent.say`（Discord 頻道，
  先遮 secret 再畫）都改成 `present.deliver(app, api, chat_id, text)`。工具輸出、系統訊息、確認卡（`agent/approve.py`）都沒動。
- 關著：`deliver` 就是原本的 `api.send_message(chat_id, text)`，一個位元組都不變（`tests/test_present_wiring.py` 用假通道比對）。
- 開著：照 `api.channel_name` 選輸出 adapter（`telegram`／`discord`／`web`）；其他通道（本機畫面、測試的假通道）照原樣送；
  畫的時候出錯也照原樣送並記一行 `[PRESENT]` log。對話記憶裡記的一律是 AI 原本的字。

## 程式在哪

| 檔案 | 內容 |
|---|---|
| `src/synox/present/__init__.py` | 入口：`document(text, trust=, source=)`、`render(text 或 Document, channel, trust=)` → `list[Chunk]`、`enabled(app)`、`deliver(...)` |
| `src/synox/present/blocks.py` | 區塊與行內的資料型別、信任等級、`safe_url`、`visible`（輸出前的共同整理）、`reply_markup`、`Chunk` |
| `src/synox/present/markdown.py` | Markdown → 區塊（自己寫的小解析器，沒有第三方套件）；純文字 → 段落（`from_plain`） |
| `src/synox/present/telegram.py`、`discord.py`、`web.py` | 三個輸出 adapter |
| `src/synox/present/split.py` | 切訊息（區塊邊界優先、區塊太長才在裡面切、每段補自己的標籤） |
| `src/synox/present/tables.py` | 表格降級的判斷（Telegram、Discord 共用） |
| `src/synox/present/width.py` | 等寬顯示寬度（中日韓全形、emoji 算 2）、UTF-16 長度 |
| `src/synox/web/static/blocks.js` | 網頁把區塊畫成 DOM（createElement＋textContent），塞進 `app.html` 的 `INCLUDE:blocks.js` |

## 區塊模型

| 區塊 | 欄位 | 誰會產生 |
|---|---|---|
| 段落 `paragraph` | spans | Markdown、純文字 |
| 標題 `heading` | level 1–6、spans | Markdown `#`～`######` |
| 清單 `list` | ordered、start、items（每項 spans＋最多一層 children） | Markdown `-`／`*`／`+`／`1.`；第三層以下併到第二層 |
| 表格 `table` | header、rows（每格 spans） | Markdown GFM 表格 |
| 程式碼 `code` | code、lang | ``` 或 ~~~（沒閉合＝到結尾） |
| 引用 `quote` | paragraphs | `>`（巢狀攤平成一層） |
| 狀態標籤 `status` | tone（ok／warn／error／info／pending）、label | 程式碼 |
| 按鈕群 `buttons` | rows（text＋data 或 url） | **只有程式碼** |
| 確認卡 `confirm` | title、lines、ok／cancel | **只有核准流程**（`blocks.confirm_card`）；這一版只負責畫得出來，還沒取代現有的卡 |

- 行內一律攤平成 **Span**（字＋粗體／斜體／等寬／連結），巢狀強調不會變成巢狀資料；輸出時每個 Span 自己開關標籤，所以切在哪裡標籤都成對。
- **信任等級**：整份 `Document.trust` 與每個區塊的 `trust`，實際用兩者中較低的（`system` > `assistant` > `external`）。
  AI 回覆＝`assistant`；工具結果、網頁、檔案、別人的訊息＝`external`；SYNOX 自己產生的＝`system`。

## 安全規則

- **按鈕群與確認卡只有實際信任等級是 `system` 時才會變成真的按鈕**（`Document.interactive_ok`）；信任不夠的只畫成普通文字（按鈕的字放在〔〕裡）。
  Markdown 解析器永遠不產生這兩種區塊：`[✅ 執行](agent_ok:go:1)`、`<button>`、貼上的 `inline_keyboard` JSON 都只是字。
- **連結只收 http／https**（`blocks.safe_url`：有主機、沒有空白／控制字元／引號／`<>`）；`javascript:`、`data:`、`file:`、相對路徑整段原樣當普通字。
  按鈕的 url 也一樣。`external` 的連結字跟網址不同時，字後面直接放網址（`blocks.expose_links`），不能用好看的字遮住真正的網址。
- **輸出時一律跳脫**：Telegram／網頁 HTML 跳脫 `& < >`，屬性值再跳脫 `"`；HTML 實體（`&lt;`）不解碼，原樣當字。
  Discord 對所有字跳脫 Markdown 特殊字元（`\ * _ ~ `` ` `` | < [ ] @`、行首的 `# > - +` 與 `1.`）——區塊已經是解析過的結果，剩下的符號都是字。
- **白名單標籤**：Telegram 只有 `b i code pre a blockquote`（`code` 只在 `pre` 裡帶 `class="language-…"`）；網頁另外有
  `p h3 h4 h5 ul ol li table thead tbody tr th td span`，屬性只有 `a` 的 `href`／`rel`、`span` 的 `class`、`ol` 的 `start`。沒有 `style`、`on*`、`<script>`、外部資源。
- 解析器不丟例外（出錯就整份退成純文字段落）；強調的配對是單一堆疊、連結的括號一次查表，大量巢狀不會變慢或爆遞迴。

## 各通道的降級規則

| 內容 | Telegram（HTML，4096） | Discord（Markdown 子集，2000） | 網頁 |
|---|---|---|---|
| 粗體／斜體／程式碼／連結 | `<b>` `<i>` `<code>` `<a href>` | `**` `*` `` ` `` `[字](網址)`（字＝網址只放網址） | `<b>` `<i>` `<code>` `<a>` |
| 標題 | `<b>` 一行 | `##`（1–2 級）、`###`（3 級以下） | `h3`～`h5` |
| 清單 | 「• 」「1. 」開頭的行；第二層縮排、「◦ 」 | 「- 」「1. 」；第二層縮兩格 | `ul`／`ol`／`li` |
| 引用 | `<blockquote>` | 每行「> 」 | `<blockquote>` |
| 程式碼 | `<pre>`（有語言標記＝`<pre><code class="language-…">`） | ``` 圍欄＋語言標記；字裡的 ``` 插零寬空白拆開 | `<pre><code>` |
| 表格：2 欄 | 一列一行「**第一欄**：第二欄」 | 同左 | 真的 `<table>` |
| 表格：窄表（每行顯示寬度 ≤ 36） | `<pre>` 等寬對齊（中文算 2 格） | 程式碼區塊對齊 | 真的 `<table>` |
| 表格：寬表 | 一列一小段（第一欄粗體當小標題，其餘「欄名：值」） | 同左 | 真的 `<table>` |
| 表格：超過 30 列 | 只放前 20 列＋「表格太長…完整內容請在網頁看」 | 同左 | 全部 |
| 狀態標籤 | `✅ <b>完成</b>` | `✅ **完成**` | `<span class="status status-ok">` |
| 按鈕（只有 system） | 最後一則的 reply_markup | 最後一則的按鈕元件 | 訊息的 buttons（照舊） |
| 切割 | 區塊邊界；單一區塊太長才在裡面切，每段補上自己的標籤 | 同左；切在圍欄裡＝這則結尾補 ```、下一則重開 | 不切 |

- 長度一律用 UTF-16 單位、連標籤一起算（保守，Telegram 的上限其實只算看得到的字）。切點優先找換行，其次空白，都沒有（一行沒有空白的超長字串）才硬切。
- 網頁：伺服器端可以產生已跳脫的 HTML（`web.to_html`，黃金檔比的是它），但**實際接線送的是 JSON 區塊**（`web.wire` → 訊息的 `blocks` 欄位，
  `text` 仍是原本的字）：AGENT.md invariant 9 規定網頁的字一律 `textContent`、`app.html` 從來不用 `innerHTML`，所以由 `static/blocks.js`
  用 `createElement`／`textContent` 畫，伺服器產生的 HTML 不必塞進頁面。改字或刪掉訊息時 `blocks` 一起拿掉。

## 測試與黃金檔案

- `tests/test_present_golden.py`：`tests/fixtures/present/<案例>/` 每個資料夾一份 `source.md`（`meta.json` 可以指定 `trust`），
  比對 `blocks.json`、`telegram.json`（切好的每一則）、`discord.json`、`web.html`；每個案例也對三種信任等級各跑一次不變量。
- 不變量（`tests/present_checks.py`）：Telegram 每則 ≤ 4096、Discord 每則 ≤ 2000、標籤成對且正確巢狀、只出現白名單標籤與屬性、
  `href` 只有 http／https、沒有未跳脫的 `<`／`>`／`&`、Discord 每則的圍欄成對、非 `system` 產生不出按鈕。
- `tests/test_present_markdown.py`（解析器、壞掉的輸入、速度）、`tests/test_present_blocks.py`（信任、按鈕、連結、表格、切割）、
  `tests/test_present_wiring.py`（開關、三個通道的接線、頻道 AI）、`tests/js/test_blocks.js`（網頁的 DOM，用 node＋假 document；沒有 node 就跳過）。
- 全部離線：純函式＋假通道／假 HTTP／假 AI，不開埠、不連網、不叫真的 AI。

**重新產生黃金檔**（輸出改了、而且確定新的是對的）：

```powershell
$env:SYNOX_UPDATE_GOLDEN = "1"; .venv\Scripts\python.exe -m pytest -q tests\test_present_golden.py; Remove-Item Env:SYNOX_UPDATE_GOLDEN
git diff tests/fixtures/present      # 一定要看過差異再 commit
```

新增案例：在 `tests/fixtures/present/` 開一個資料夾放 `source.md`（範例一律用佔位資料），再用上面的指令產生其他四個檔。

## 這次沒做的

- Telegram 的 Rich Message（Bot API 新格式）與串流草稿；對話狀態機、進度卡、「在等你的」總表。
- 確認卡區塊還沒取代 `agent/approve.py` 的卡；工具輸出、系統訊息還沒經過呈現層。
- 沒有在真的 Telegram／Discord 上看過畫出來的樣子（只有假通道與黃金檔）。
