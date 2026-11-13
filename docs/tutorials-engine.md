# 新手教學引擎（/tutorial）：怎麼寫一份教學、位置清單

> 狀態：第 1 版（2026-11-13）。程式：`src/synox/tour/`、`src/synox/web/static/tour.js`、`tour.css`。測試：`tests/test_tour.py`；
> 真瀏覽器煙霧測試：`scripts/ui_tour_smoke.py`（要 Playwright＋Chromium，不在 pytest 裡）。
> 計畫：`docs/lab/2026-11-13-onboarding-help-aliases-plan.md` 的 3.3、T1／T2／L2；擁有者 2026-11-13 的決定見下面「為什麼這樣做」。

## 一句話

**引擎在 SYNOX 核心、內容是純資料的步驟檔。** 每一份 SYNOX（ZIP、安裝程式、git、Docker）出廠就有「SYNOX 新手教學」；
使用者打 `/tutorial`，SYNOX 自己在真的畫面上把要按的地方圈起來，旁邊一張小卡說明。走完了、忘了，再打一次就能複習。

## 使用者看到的

| 在哪 | 怎麼開始 | 樣子 |
|---|---|---|
| 網頁（第一次打開） | 右下角「要不要我帶你走一遍？（約 5 分鐘）」→〔開始〕／〔之後再說〕 | 聚光圈＋小卡（〔上一步〕〔幫我填好〕〔帶我去〕〔下一步〕／〔完成〕、〔收起〕〔先離開〕、進度條「教學 3／12」） |
| 網頁的對話 | `/tutorial`、`/tour`、`/start tutorial`，或整句只打「開始教學」「教學」「新手教學」「start tutorial」「tutorial」 | 回一句話＋「▶ 在畫面上帶我走」按鈕；剛送出的那次直接開始 |
| Telegram／Discord | 同上 | 一則步驟卡（原地改）＋〔◀️ 上一步〕〔下一步 ▶️〕〔先離開〕；要在網頁上做的那幾步會說「在網頁打 /tutorial，我會直接在畫面上指給你看」 |
| `/help` | 選單後面多一行「🎓 第一次用？打 /tutorial…」（`/help all`、`/help <分類>` 不加） | |

- `/tutorial` 接著上次；走完過的＝從頭複習。`/tutorial restart` 從頭來（做過的清掉）。`/tutorial list` 列出全部教學（工具也可以附自己的）。`/tutorial <名字>` 走那一份。
- 鍵盤：小卡出現時焦點在小卡標題；Tab 在小卡的按鈕之間移動；**Esc 把小卡收成右下角的小按鈕**（不會結束教學，按小按鈕展開）。
- 系統設了「減少動態效果」：聚光圈不滑動、小卡不淡入、自動前進前多停一下。
- 手機（≤760px）：小卡貼在畫面上方或下方（看要指的東西在哪一半），不蓋住要按的地方；底部分頁列上面留空間。

## 為什麼這樣做（設計選擇）

1. **教學是核心、不是工具。** 擁有者 2026-11-13：「原則上只讓它裝完 tutorial，然後讓它自己去熟練一次這個程式…tutorial 是非常核心的一個 synox 的介紹」。
   所以它推翻計畫第六節決定 7（不預設裝）：出廠就有，但**不是 pack**——不經安裝流程、不在「功能（pack）」清單、不算「裝了幾個工具」
   （`packs/library.installed_tools` 照舊是 0、「還沒裝任何工具」的提示照舊出現），也就**刪不掉**（沒有東西可刪）。「出廠不帶工具」仍然成立。
2. **內建內容放 `src/synox/tour/tours/`，不放 `docs/guide/steps/`**（計畫決定 6 的建議）。理由：Docker 映像檔只裝 `src/` 打成的 wheel
   （`.dockerignore` 是白名單、`docs/` 不在裡面），放 docs 的話 Docker 版就沒有教學。放在套件裡＝ZIP、安裝程式（用 ZIP 的檔案清單）、
   git、Docker 都一定有；`pyproject.toml` 的 package-data 有 `tour/tours/*.json`。之後做線上教學頁（G1）時，產生器直接讀這個資料夾。
3. **內容可以插拔。** 步驟是資料（JSON），不是程式：改字、加一步、換順序都不用改程式。工具也可以在自己的資料夾放 `tours/*.json`，
   載入了就出現在 `/tutorial list`（小卡上會寫「這份教學是工具「X」附的」）。id 跟內建的撞名＝內建的贏。
4. **畫面由 SYNOX 自己畫。** 步驟檔只給「字」與「位置的名字」；找元素、畫聚光圈、判斷做完沒，都是核心的 `tour.js`。

## 安全（不能放寬）

- 教學**只指、不按**：`tour.js` 不呼叫任何元素的 `click()`、不送出表單、不呼叫會改東西的 API；只打 `GET /api/tour`、
  `POST /api/tour/progress`、`POST /api/tour/offer`（都只碰這個人自己的教學進度）。聚光圈與遮罩是 `pointer-events: none`。
  `tests/test_tour.py::test_tour_js_never_presses_anything` 掃這個檔。
- 「幫我填好」只把字放進輸入框，不送出；「帶我去」只換網址的 `#`（只能去 `chat`／`tools`／`settings` 與設定的分頁）。
- **裝工具的流程一點都沒變**：教學只說「按「安裝」會先給你看報告，你自己按「確認安裝」才會裝」，確認鈕永遠是使用者自己按；
  位置清單裡**沒有**確認、刪除、密鑰欄位這種按鈕（安裝報告是整張卡）。五關檢查照舊。
- 字一律純文字（網頁用 `textContent`）；步驟檔裡出現網址或 HTML 標籤＝整個檔不載入。
- 教學的字**不進 AI 的提示**；`/tutorial` 是 `ai=False`（不給 AI 當工具）、`quota_exempt`、按鈕走 `tour:` 前綴並以按的人的身分過 `authorize`。
- 工具附的教學：檔案的真實路徑必須在那個工具的資料夾裡（捷徑指出去＝不載入）；跟內建的一樣過格式檢查。

## 怎麼寫一份教學

放一個 `.json` 檔：內建的在 `src/synox/tour/tours/`；工具附的在 `<工具資料夾>/tours/`。格式 `synox-steps` 第 1 版：

```json
{
  "schema": 1,
  "id": "basics",
  "title": "SYNOX 新手教學",
  "version": "1.0.0",
  "minutes": 5,
  "summary": "一句話說這份教學在教什麼",
  "steps": [
    {"id": "open-chat", "title": "這裡是「對話」",
     "body": "按「對話」。跟我說話、打指令，都在這一頁。",
     "chat": "Telegram／Discord 看到的字（沒寫就用 body）",
     "where": {"anchor": "nav.chat"},
     "go": {"view": "chat"},
     "try": {"text": "/help"},
     "done_when": {"event": "view", "value": "chat"},
     "audience": "all"}
  ]
}
```

| 欄位 | 必填 | 規則 |
|---|---|---|
| `schema` | ✔ | 現在只有 `1` |
| `id` | ✔ | 小寫英數與 `-`，≤40 字；`/tutorial <id>` 用它 |
| `title` | ✔ | ≤30 字 |
| `version` | ✔ | `1.0.0` 這種。**第一個數字變了＝大家的進度從頭來**；後兩個變了，做過的步驟照樣算做過、新的補上 |
| `minutes` | | 1～60（邀請卡寫「約 N 分鐘」） |
| `summary` | | ≤200 字 |
| `lang` | | 語言代號（同安裝精靈：`zh-TW`、`en`、`ja`…），沒寫＝`zh-TW`。同一個 id 可以一種語言一個檔（`basics.json`、`basics.en.json`）：引擎照 SYNOX 資料夾的 `lang.txt` 挑，沒有那個語言先退回 `en`、再退回 `zh-TW`（跟精靈的字串一樣） |
| `steps` | ✔ | 1～40 步；步驟 `id` 不能重複。**進度記的是步驟 id**，改字不影響進度，改 id＝那一步算新的 |
| `steps[].title`／`body` | ✔ | 純文字；≤30／≤200 字 |
| `steps[].chat` | | 聊天通道版本的字（≤300 字）。沒寫、而且這步有指位置＝聊天通道會多一句「在網頁打 /tutorial，我會直接指給你看」 |
| `steps[].where.anchor` | | 一個位置名，或最多 3 個的清單（第一個看得到的；例如報告還沒出現時先指工具庫）。**只能用下面的位置清單** |
| `steps[].go` | | 〔帶我去〕：`{"view": "chat"｜"tools"｜"settings", "tab": "ai"｜"channels"｜"packs"｜"accounts"｜"system"}`。位置看不到、或最後一步才會出現這顆 |
| `steps[].try` | | 〔幫我填好〕：`{"text": "/help"}`，只填進輸入框（≤200 字） |
| `steps[].done_when` | | 做完了就打勾、自動到下一步（見事件清單）。沒寫＝按〔下一步〕。一開始就已經做到的（例如本來就在那一頁）只打勾、不自動跳 |
| `steps[].audience` | | `all`（預設）、`owner`（只給擁有者，例如裝工具）、`member`（不是擁有者的人） |
| `steps[].stage` | | 現在只收 `in-app`（之後線上教學頁會多 `before-install`／`wizard`） |

不認得的欄位、不認得的位置或事件、太長、有網址或 HTML＝**整個檔不載入**（log 一行 `[TOUR] … (not loaded)`）。

### 事件清單（`done_when.event`）

| 事件 | value | 怎麼知道的 |
|---|---|---|
| `view` | `chat`｜`tools`｜`settings` | 網頁現在在哪一頁 |
| `tab` | `ai`｜`channels`｜`packs`｜`accounts`｜`system` | 設定頁現在在哪個分頁 |
| `message_sent` | — | 在對話頁送出一則訊息（不看內容） |
| `command` | 指令名（不含 `/`），例如 `help` | 在對話頁送出那個指令 |
| `catalog_loaded` | — | 官方工具清單載入好了 |
| `pack_report` | — | 出現安裝前的檢查報告 |
| `pack_installed` | — | 裝好一個工具（使用者自己按了確認） |
| `pack_removed` | — | 移除了一個工具（使用者自己按了移除） |

自動判斷只在網頁；聊天通道一律按〔下一步〕。

## 位置清單（第 1 版；`src/synox/tour/anchors.py`）

網頁元素上寫 `data-tour="<名字>"`。`tests/test_tour.py` 比對 `app.html` 與這張表：**多一個少一個都會失敗**。

| 名字 | 是什麼 | 加入 |
|---|---|---|
| `nav.chat` | 左側（手機在下方）的「對話」 | 0.2 |
| `nav.tools` | 「工具」 | 0.2 |
| `nav.settings` | 「設定」 | 0.2 |
| `chat.list` | 對話頁：對話紀錄清單 | 0.2 |
| `chat.new` | 對話頁：「＋ 新對話」 | 0.2 |
| `chat.input` | 對話頁：打字的地方（輸入框＋送出鈕） | 0.2 |
| `chat.send` | 對話頁：「送出」 | 0.2 |
| `tools.page` | 工具頁：工具清單 | 0.2 |
| `settings.tabs` | 設定頁：分頁列 | 0.2 |
| `settings.tab.ai` | 「🤖 AI」分頁 | 0.2 |
| `settings.tab.channels` | 「💬 聊天通道」分頁 | 0.2 |
| `settings.tab.packs` | 「🧩 功能與安裝」分頁 | 0.2 |
| `settings.tab.accounts` | 「👥 帳號」分頁（伺服器版） | 0.2 |
| `settings.tab.system` | 「💻 電腦與備份」分頁 | 0.2 |
| `settings.tab.help` | 「🙋 遇到問題？」分頁 | 0.2 |
| `settings.ai.source` | 「AI 從哪裡來」那張卡 | 0.2 |
| `settings.channels` | 聊天通道（Telegram／Discord）那張卡 | 0.2 |
| `settings.packs.catalog` | 官方工具庫那張卡 | 0.2 |
| `settings.packs.catalog.load` | 「載入工具清單」按鈕（只讀清單，不會裝任何東西） | 0.2 |
| `settings.packs.upload` | 上傳 .synoxpack 那張卡 | 0.2 |
| `settings.packs.review` | 安裝前的檢查報告（整張卡；不是確認鈕） | 0.2 |
| `settings.packs.installed` | 已安裝的工具清單 | 0.2 |
| `settings.backup` | 備份那張卡 | 0.2 |

**相容規則（0.x）**：這張表是對外的承諾（工具附的教學靠它）。名字只加不改；真的要改名，新名字進表、舊名字放進 `anchors.RENAMED`
（舊 → 新）**至少留一個 MINOR 版本**，舊教學照樣找得到；要拿掉一個位置，也要先在說明寫「下一版拿掉」、留一個 MINOR。
找不到位置（這個人看不到、這一版沒有、畫面還沒出現）的那一步，自動退成畫面中央的文字卡，照樣能走完。
`anchors.VERSION` 在改名或刪名過了相容期時才升；`GET /api/tour` 會回 `anchors_version`。

## 進度（每人一份）

`data/tour/<tg_id>.json`（有保管箱就是 `.json.enc`，那個人的金鑰；備份「下載備份」會帶到）：

```json
{"tours": {"basics": {"version": "1.0.0", "step": "catalog", "done": ["welcome", "open-chat"],
                      "state": "paused", "updated": 1763000000, "finished": 1}},
 "offer": "later"}
```

- `state`：`active`（走到一半、正開著）、`paused`（按了先離開）、`finished`（走完）。`finished` 是走完過幾次（複習不會歸零）。
- `offer`：第一次打開網頁的邀請，按過「之後再說」或開始過就不再問（`/tutorial` 隨時能開）。
- 網頁、Telegram、Discord 共用同一份：在 Telegram 走到一半，到網頁打 `/tutorial` 會接著走。

## 網頁 API

| | |
|---|---|
| `GET /api/tour` | `{"tours": [{id, title, minutes, source, version, steps: [{id, title, body, anchors, go?, try?, done_when?}]}], "progress": {...}, "offer": bool, "default": "basics", "anchors_version": 1}`（步驟已依這個人是不是擁有者篩好） |
| `POST /api/tour/progress` | `{"tour", "step", "state", "done": [步驟 id]}`；要 CSRF |
| `POST /api/tour/offer` | `{"answer": "later"｜"start"}`；要 CSRF |

## 安裝程式（給做安裝程式的人）

不用做任何事，只要**不要排除** `src/synox/tour/`（含 `tours/*.json`）與 `src/synox/web/static/tour.js`、`tour.css`。
它們是 SYNOX 本體的一部分，不是工具，不放進 `packs/`、也不會出現在工具庫。

## 還沒做的

- 線上一步一步教學頁（計畫 G1）還沒有讀這個資料夾；`docs/guide/index.html` 目前是自己的一份步驟資料。
- 聊天通道沒有自動前進（例如等他打一次 `/help`）；只有按〔下一步〕。
- 畫面上有確認框時，小卡不會自己收起來（計畫安全限制 4 的後半）：小卡會避開要指的東西、手機上貼在上或下，蓋到時可以按〔收起〕或 Esc。
- 內建的教學只有繁體中文（網頁與 bot 的字現在也只有繁中，教學裡寫的按鈕名字要跟畫面一樣）。
