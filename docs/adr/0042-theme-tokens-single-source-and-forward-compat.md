# ADR 0042：外觀的顏色只宣告一次、舊外觀包遇到新 token 不會壞、套用時列逐項檢查

- 日期：2026-11-19
- 狀態：**已採用**（分支 `feat/theme-token-check`；擁有者的需求：SYNOX 在同一個地方宣告所有顏色、衣櫃只覆蓋它們，方便之後做資料注入；
  需求原文不公開）。標 **「實作時決定，待擁有者確認」** 的是這一輪自己定的，擁有者不同意可以改。
- 程式：`src/synox/theme/contract.py`（DEFAULTS、FIXED、REQUIRED_COLORS、root_decls）、`theme/tokens.py`（parse_tokens_full）、
  `theme/pack.py`（不認得的 slot）、`theme/check.py`（套用檢查）、`web/server.py`（render_app 換 `/*{{TOKENS:…}}*/`、PAGE_CSS）、
  `remindwin/style.py`、`theme/appearance.py`（預覽頁、`/api/appearance` 的 `check`）、`packs/admin.py`、`__main__.py`。
- 前提：外觀合約第 1 版（[docs/themes.md](../themes.md)）。這份**不升** `CONTRACT_VERSION`（沒有改名、沒有刪名）。

> **給使用者的一句話**：SYNOX 以後加新的顏色，你裝著的舊外觀包照樣能用——它沒給的顏色先用 SYNOX 自己的，等外觀包更新。
> 套用外觀前可以看一份清單：每個顏色、每個吉祥物位置是「外觀包有給」「沿用 SYNOX 預設」還是「這版不認得、先忽略」。

## 1. 背景

調查時（2026-11-19，dev）SYNOX 的預設顏色寫在好幾個地方，靠測試互相對：

| 在哪 | 是什麼 | 這次怎麼處理 |
|---|---|---|
| `static/app.html` 的 `:root`（淺色、跟隨系統的深色、強制深色三段） | 網頁真正用的值 | **改成產生的**：只留 `/*{{TOKENS:light}}*/`、`/*{{TOKENS:dark}}*/` 記號，`render_app` 從 contract 填 |
| `theme/contract.py` 的 `DEFAULTS` | 只有一部分 token 的副本 | **變成唯一的來源**：每個合約 token 都有淺色值、深色列換掉的；另加 `FIXED`（陰影、圖片白底、暗幕：外觀包換不到的） |
| `remindwin/style.py` 的 `DEFAULTS`、`DERIVED` | 提醒視窗用的副本 | 改成從 contract 取 |
| `web/server.py` 的 `PAGE_CSS` | 登入小頁的副本 | 改成從 contract 組 |
| `theme/appearance.py` 的預覽頁 | 用 DEFAULTS＋DERIVED 「算」原本的樣子（跟真的不一樣） | 先墊 contract 的 `:root`（`root_css`），再蓋外觀包的 |
| `static/appkit.css`（工具服務的 `/_synox/kit.css`）、`static/remote_enter.css`（手機入口） | 靜態檔，不經 `render_app` | **留著副本**，加測試：同名的值要跟 contract 一樣（`tests/test_theme_compat.py`） |
| `appkit.css` 的 `--synox-*` | 工具服務頁首自己的一組（為了對比度故意不同） | 不動（有 `tests/test_appkit.py` 的對比度檢查） |
| `sdk/__init__.py` 的頁面樣式 | SDK 產生的工具頁，跟主控台不同一套 | 不動（不屬於外觀合約） |
| `apps.js`、`security.js` 的 `#fff`／`#000` | 畫 QR code 的 canvas（一定要黑白才掃得到） | 不動 |

## 2. 決定

### 2.1 顏色只宣告一次

- `contract.DEFAULTS`：`light`＝每一個合約 token（`ALL_TOKENS`）都有值；`dark`＝深色時換掉的（沒列＝跟淺色一樣）。
- `contract.FIXED`：SYNOX 自己用、外觀包換不到的顏色（`--img-bg`、`--shadow-*`、`--highlight`、`--tour-scrim`…）。
- 網頁 `app.html` 不寫任何顏色；`render_app` 把記號換成 `root_decls(mode)`。送出去的頁跟以前**一字不差的值**（測試比對三段 `:root`）。
- 加一個 token＝名字進 contract 的表、值進 `DEFAULTS`，網頁自己多一行；不用再改 app.html。

### 2.2 向前相容：舊外觀包、新 SYNOX

- **一定要給的只有合約第 1 版的核心 12 色**（`REQUIRED_COLORS`，凍結）。以後加的 token 一律選填。
- 外觀包沒給的 token：在 `DERIVED` 裡的用外觀包自己的核心色算；不在的**沿用 SYNOX 的預設**（網頁的 `:root` 本來就有）。
  外觀包的 CSS 只蓋它給的 token（同樣三段選擇器，晚載入），所以不會出現沒定義的變數。
- 預覽頁（`/theme/preview`）一樣先墊 SYNOX 的值。電腦提醒視窗本來就是「看不懂的那一個用原本的」。

### 2.3 向前相容：外觀包比 SYNOX 新（實作時決定，待擁有者確認）

以前不認得的 token、slot 一律拒裝。改成：

| 情況 | 以前 | 現在 |
|---|---|---|
| token 名字不認得（像個名字：小寫英數與 `-`） | 拒裝 | **忽略那一個**、記提示（`unknown-token`） |
| 值裡用到不認得的 `var(--x)`（`--th-` 開頭的本來就收） | 拒裝 | **那一個 token 沿用 SYNOX 的**、記提示（`unknown-ref`）；核心 12 色也算「有給」，不會因此拒裝 |
| slot 名字不認得（像個名字） | 拒裝 | **忽略那一個**、記提示（`unknown-slot`）；那個檔照樣在第 2 關消毒 |
| 名字根本不像名字（空白、大寫、符號） | 拒裝 | 照舊拒裝 |
| 值本身不合（網址、程式、`!important`…） | 拒裝 | 照舊拒裝（安全規則不放寬） |
| `theme.contract` 比 SYNOX 新 | 拒裝「請先更新 SYNOX」 | 照舊（合約版號只在改名、刪名時升，那時舊 SYNOX 真的看不懂） |
| `theme` 底下不認得的欄位 | 拒裝 | 照舊（**待擁有者決定**要不要也改成忽略） |

代價：作者把名字打錯（`acent`）不會再被擋，只會在報告上變成一條「要注意」。工具庫那邊做外觀包時有自己的檢查（`build_costumes.py check`）會擋。

### 2.4 套用時的逐項清單（提示，不擋）

`theme/check.py` 的 `coverage(theme)`：

- 每個 token、淺色深色分開：`provided`（外觀包有給；深色沒給圓角、字型時用淺色的，`from: light`）／`derived`（用外觀包自己的色算）／
  `default`（沿用 SYNOX 預設）／`ignored`（這版不認得）。每個 slot：`provided`／`default`／`ignored`。
- **要注意**（`issue`）：`ignored` 的；以及顏色 token 是 `default`（可能跟這套外觀不搭）——暗幕、陰影（`NEUTRAL_TOKENS`）除外。
- `blocking` 永遠是 `false`：清單只是提示，套用照常。
- 出現在：安裝報告（終端機 `format_theme`、網頁報告）、設定 → 外觀每一張外觀卡（`/api/appearance` 的 `themes[].check`）、
  `synox packs theme-check <名字或資料夾> [--details] [--json]`、`synox install <檔> --details`。
- 預設只顯示摘要與要注意的；網頁「展開看每一項」、終端機 `--details` 看全部。給 AI 的是 `--json`／API 裡的結構（欄位見 `check.py` 開頭）。
- `theme-check` 的結束碼：0＝沒有要注意的、10＝有（還是可以套用）、2＝不是外觀包或 pack.json 不合。

## 3. 為什麼不選別的

- **反過來，以 app.html 為準、Python 去讀它**：提醒視窗、登入頁、預覽頁都要去解析一個 3700 行的 HTML；資料注入（之後要做的）也比較難接。
- **把 appkit.css、remote_enter.css 也改成產生的**：它們是直接送出的靜態檔（工具服務的頁、手機入口），改成產生要多一條路由或快取，
  這次只加「值要對得上」的測試，之後要做再說。
- **新 token 也要求外觀包給齊**：舊外觀包會在 SYNOX 升級後突然裝不上、整個外觀消失，這正是要避免的。

## 4. 測試怎麼守

- `tests/test_theme.py`：送出去的 `:root` 三段＝contract；app.html 的 token 區一個顏色都沒有、沒有留下記號。
- `tests/test_theme_compat.py`：每個合約 token 都有淺色預設；提醒視窗、登入小頁、兩個靜態副本對得上；網頁用到的 `var(--x)` 都有定義；
  預設的字對比度 ≥ 4.5；只有核心 12 色的舊包照裝、每個 token 有值；假裝 SYNOX 多一個 token：舊包照裝、真的網頁（淺色、深色）與預覽頁都有值、
  清單標「要注意」；比 SYNOX 新的包照裝、不認得的忽略並出現在報告；值不合照樣拒；CLI 的摘要、`--details`、`--json`。
- 真機：[docs/testing/theme-apply-checklist.md](../testing/theme-apply-checklist.md)。
