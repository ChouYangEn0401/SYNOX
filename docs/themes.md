# 外觀（換裝）

SYNOX 預設是原本的樣子（S 寶寶、藍綠色）。**外觀包**（`.synoxpack`，`"kind": "theme"`）可以把整個網頁換一套衣服：
顏色、字型、吉祥物、開場動畫、字標、分頁圖示。品牌頁的每一個系列都可以做成一個外觀包給大家下載。

架構一句話：**SYNOX 定「大方針」，外觀只注入替換。**

- 大方針＝一小組 **token**（CSS 自訂屬性：顏色、圓角、字型）＋一小組 **slot**（可以整個換掉的位置：吉祥物、開場…）。
  網頁的每一個顏色都只從 token 來（`tests/test_theme.py` 會檢查），所以換 token＝整個對話畫面一起換色。
- 外觀包與「自己貼」**只能**蓋 token、換 slot 的內容，加不了程式、碰不到別的地方。
- 只影響網頁。Telegram、Discord 是純文字，不受影響。

程式：`src/synox/theme/`（`contract.py` 名字、`sanitize.py` 消毒、`tokens.py`、`pack.py` 外觀包、`appearance.py` 設定與存檔），
網頁：`static/slots.js`（把 slot 內容放到畫面上）、`static/app.html` 最上面的 token、設定頁「🎨 外觀」。

## token（合約第 1 版）

外觀包的 `theme.tokens.light` 與 `theme.tokens.dark` **都要給齊核心 12 色**；其他選填。名字可以寫 `bg` 或 `--bg`。

| token | 用在哪 | 原本（淺色／深色） |
|---|---|---|
| `bg` | 頁面底色 | `#f3f5f8`／`#0b0f14` |
| `surface` | 卡片、側欄、輸入框 | `#ffffff`／`#121924` |
| `text` | 文字 | `#131b26`／`#dbe4ef` |
| `muted` | 次要文字 | `#6a7687`／`#7f90a7` |
| `line` | 框線、分隔線 | `#e2e7ee`／`#1f2b3b` |
| `accent` | 主色（主要按鈕、連結、選到的東西） | `#0a7c70`／`#35e0c4` |
| `accent-ink` | 主色上面的字 | `#ffffff`／`#04221d` |
| `accent2` | 副色（漸層、光點） | `#2f7fd6`／`#4aa8ff` |
| `soft` | 主色的淡底（選到的對話、我的泡泡、標籤） | `#e0f2ef`／`rgba(53, 224, 196, .12)` |
| `ok`、`warn`、`bad` | 狀態色（能用、注意、壞了／危險） | 見 app.html |
| `radius` | 基本圓角（其他圓角照比例算） | `10px` |
| `font-ui` | 介面字型 | Segoe UI／微軟正黑體… |
| `font-brand` | 字標、標誌字 | 同 `font-ui` |
| `m1`、`m2`、`mi`、`mb` | 吉祥物配色：主體、第二色、眼睛／線條、腮紅 | 等回覆的方塊：`#4f8df5`、`#2f66d0`、`#ffffff` |

進階 token（選填；沒寫就從上面算，公式在 `contract.DERIVED`）：
`bg-glow surface-2 sunken line-strong text-2 accent-hover accent-line ok-soft warn-soft bad-soft me me-ink m-hi scrim shadow-up`。

值只能是一個顏色／長度／字型名單：可以用 `#hex`、`rgb()`、`hsl()`、`oklch()`、`color-mix()`、`var(--別的 token)`；
不能有 `url()`、分號、大括號、反斜線。字型名單不能有括號。

舊名字 `--accent-2`、`--accent-soft`、`--r`、`--font` 還在（是上面那些的別名），新的 CSS 請用合約上的名字。

## slot（合約第 1 版）

網頁上 `data-slot="<名字>"`（也有 class `theme-slot-<名字，點換成 ->`）的元素。名字只加不改（規則同教學的位置清單）。

| slot | 在哪裡 | 原本的 | 收 |
|---|---|---|---|
| `mascot.idle` | 側欄、登入卡左上角的標誌；空白對話的插圖 | 「S」方塊 | SVG／HTML |
| `mascot.think` | 等 AI 回覆時那顆會晃的小東西 | 藍色方塊 | SVG／HTML |
| `mascot.happy` | 裝好、套用成功 | 笑臉 S 寶寶 | SVG／HTML |
| `mascot.warn` | 安裝被拒、出問題 | 擔心的 S 寶寶 | SVG／HTML |
| `opening` | 打開網頁的開場（約 1.7 秒，時間 SYNOX 管） | S 寶寶掉下來、翻成 S | SVG／HTML＋CSS 動畫 |
| `wordmark` | 側欄的「SYNOX」、開場的字 | 文字 SYNOX | SVG／HTML |
| `appicon` | 分頁圖示（favicon） | 瀏覽器預設 | 只收 SVG |

slot 元素本身的位置被網頁用 `!important` 釘死（不能移動、不能蓋到別的畫面上、裡面畫出界就裁掉）；
動畫請動 slot **裡面**的東西。SVG 的大小照 slot（`width/height: 100%`，請給 `viewBox`）。

## 外觀包的格式

```
costume-b-lantern/
  pack.json
  theme.css          選填
  slots/idle.svg …   選填
  fonts/x.woff2      選填
  README.md          選填（.md、.txt、LICENSE 都可以）
```

```json
{
  "name": "costume-b-lantern", "kind": "theme", "version": "1.0.0",
  "title": "提燈", "summary": "幫你顧家的一盞小燈", "publisher": "SYNOX",
  "theme": {
    "contract": 1,
    "tokens": {"light": {"bg": "#f5f3ef", "surface": "#fffdf9", "…": "…"},
               "dark":  {"bg": "#121126", "…": "…"}},
    "slots": {"mascot.idle": "slots/idle.svg", "opening": "slots/opening.svg", "appicon": "slots/icon.svg"},
    "css": "theme.css",
    "fonts": ["fonts/Fraunces.woff2", {"family": "Noto Serif TC", "file": "fonts/serif.woff2", "weight": "700"}]
  }
}
```

- 外觀包**沒有程式**：不能寫 `python`、`cli`、`commands`、`mcp`、`runtime`、`env`、`capabilities`、`web`、`auth`、`health`…（第 1 關就拒）；
  `requires` 只能寫 `synox`。不用 SKILL.md。
- 資料夾裡只能有 `pack.json`、`.svg`、`.html`、`.css`（只有 `theme.css` 指到的那一份）、`.woff2`（只有 `theme.fonts` 列的）與說明文字。最多 40 個檔。
- 大小：一個 slot 檔 64 KB、`theme.css` 64 KB、字型一個 400 KB、最多 4 個、加起來 1 MB。
- 字型**一定附在包裡**（woff2）。網頁不會連到 Google Fonts 之類的地方（隱私）；`@import`、外部網址一律拒。
  沒附字型就寫系統字型（例如 `"Noto Sans TC", "Microsoft JhengHei UI", system-ui, sans-serif`）。
  `fonts` 寫字串時，字型名字＝檔名（不含副檔名）；寫物件可以指定 `family`、`weight`（`400`、`700`、`"100 900"`）、`style`。
- `theme.contract`：照第幾版的合約做的（現在 1）；比這台 SYNOX 新＝不裝，請先更新 SYNOX。

範例：`tests/fixtures/theme_pack/`（提燈，換了全部 7 個 slot）。打包：`python scripts/pack_zip.py <資料夾>`。

## 消毒規則（安裝時第 2 關、每次送網頁都再跑一次）

原則是**白名單重建**：把 SVG／HTML／CSS 解析之後，只用白名單裡的東西**重新組一份**送進網頁，不是把原文刪刪改改。

**整份拒絕**（安裝報告會列出哪個檔、為什麼）：

- `<script>`、`<foreignObject>`、`<iframe>`、`<object>`、`<embed>`、`<img>`、`<image>`、`<feImage>`、`<video>`、`<audio>`、
  `<a>`、`<set>`、`<animateMotion>`、`<link>`、`<meta>`、`<base>`、表單元素、`<math>`、`<template>`…
- 任何 `on…` 事件屬性（`onload`、`onclick`…）
- `javascript:`、`vbscript:`（拆開寫、用 `&#x09;` 藏也一樣抓）
- 外部網址：`href`／`xlink:href` 只能是同一份裡的 `#id`；`url(…)` 只能是 `url(#id)`（`http(s):`、`data:`、相對路徑都拒）
- `<animate attributeName>` 只能動形狀、顏色、位置這類屬性（不能動 `href`）
- CSS：`@import`、`@font-face`（字型寫在 pack.json）、`@namespace`、`@charset`、`expression()`、`-moz-binding`、`behavior`、
  `image-set()`、`cross-fade()`、`element()`、反斜線跳脫、`<`、`!important`、沒關的註解或大括號

**丟掉、在報告上提一下**（無害的雜訊）：註解、`<?xml?>`、`<!DOCTYPE>`、`<metadata>`、`inkscape:*`／`sodipodi:*` 這類編輯器屬性、
不認得的元素與屬性、`data-*` 屬性。`style="…"` 屬性：SVG 的顏色、線條這類會轉成同名屬性，其他丟掉（網頁的 CSP 不收 inline style）。

**改寫**：`id="x"` → `id="ts-<slot>-x"`，`#x`、`url(#x)` 一起改（不會撞到網頁自己的元素）。
SVG 裡的 `<style>` 拿出來，每個選擇器自動套上 `[data-slot="<slot>"]`，`@keyframes` 自動改名成 `th-<slot>-…`。

**CSS 的範圍**（`theme.css`）：

- `:root`（以及 `:root[data-theme="light|dark"]`、`:root:not([data-theme="light"])`）裡**只能設 token**（合約上的名字，或 `--th-` 開頭的自己用的變數）。
- 其他每一條規則都要套在 `[data-slot]`、`[data-slot="<名字>"]` 或 `.theme-slot-<名字>` 裡面（前面可以加 `:root[data-theme="dark"] `）。
- 不能用兄弟組合子（`+`、`~`）和 `:has()`（會選到 slot 外面）。
- `@keyframes` 名字要 `th-` 開頭；可以用 `@media`、`@supports`。
- 注意：slot 裡的 id 被加了前綴，`theme.css` 請用 class 對（或寫完整的 `#ts-mascot-idle-x`）。

另外兩層：網頁的 CSP 只放行有 nonce 的 `<script>`／`<style>`（就算消毒漏了，貼進去的程式也不會跑）；
預覽頁（`/theme/preview`）完全沒有 script，用 `<iframe sandbox>` 掛。

## 安裝與套用

1. 擁有者在「設定 → 功能與安裝」上傳 `.synoxpack`（或雙擊、`synox install`），跟其他 pack 走同一條路：
   第 1 關（宣告）→ 第 2 關（消毒）→ **報告給你看、你按確認才裝** → 第 3 關（`packs.lock`，檔案被改過就不能用）。
2. 報告上有淺色／深色的色票，和兩格預覽（假的對話畫面＋全部吉祥物＋開場）。信任層級固定 **T0（只有宣告）**，但一樣要按確認。
3. 裝好**不會自己套用**：到「設定 → 🎨 外觀」挑它、看預覽、按「套用」。隨時可以按「換回原本的 SYNOX」。
4. 同時只會套一個外觀包。

## 自己貼（進階）

「設定 → 🎨 外觀 → 自己貼」：選一個 slot，貼 SVG（或一小段 HTML＋`<style>`），按「預覽」看消毒後的樣子與拿掉了什麼，
再按「套用到這個位置」。跟外觀包同一套消毒；自己貼的蓋過外觀包的那一格。一格最多 32 KB。
存的是原文，每次送網頁都重新消毒（消毒規則更新了照新的；過不了的那一格就當作沒貼）。

## 存在哪裡、誰的算數

存在每個人的網頁偏好 `data/web_prefs/<tg_id>.json(.enc)`（有保管箱就是密文）的 `appearance`：
`{"theme": "<外觀包>"｜"", "mode": "auto"｜"light"｜"dark", "custom": {"<slot>": "<貼的原文>"}}`。

- **個人版**：擁有者的那一份就是這台的外觀（跟著這次安裝，重開還在）。
- **伺服器版**：每個人自己選、自己貼，只影響自己的畫面；**自己沒選過的欄位（外觀、淺色／深色、自己貼）跟擁有者的一樣**——
  擁有者的那一份＝這台的預設。還沒登入的畫面（登入卡）用擁有者的。外觀包只有擁有者能裝。

## 從品牌頁做一個外觀包

品牌頁（`docs/lab/design/2026-11-13-brand-explorations.html`）每個系列的資料已經是 token：

| 品牌頁 | 外觀包 token |
|---|---|
| `L`／`D` 的 `bg surf text muted line` | `bg surface text muted line` |
| `ac acink ac2 soft` | `accent accent-ink accent2 soft` |
| `ok warn bad` | `ok warn bad` |
| `m1 m2 mi mb` | `m1 m2 mi mb` |
| `rad` | `radius`（品牌頁的是卡片圓角；按鈕用的基本圓角大約取它的一半到六成） |
| `uif`、`wm.font` | `font-ui`、`font-brand`（字型要附 woff2，或改寫成系統字型） |

1. 把那個系列的 `L`、`D` 照上表寫進 `theme.tokens.light`、`dark`。
2. 吉祥物畫成 SVG（四個表情＋開場），顏色用 class，在 `theme.css` 裡寫 `[data-slot] .body { fill: var(--m1) }` 這種（換深淺色會跟著換）。
3. 字標畫成 SVG（文字或路徑都可以），分頁圖示另外一張（favicon 看不到 theme.css，顏色直接寫在屬性上）。
4. `python scripts/pack_zip.py <資料夾>` → `dist/<name>-<version>.synoxpack`（打包前會先跑第 1、2 關）。
5. 放到品牌頁給大家下載。下載的人照上面「安裝與套用」裝。

## 改合約

加 token 或 slot：改 `src/synox/theme/contract.py`（slot 也要在 `static/slots.js` 的 `NAMES` 與網頁上放 `data-slot`），
`tests/test_theme.py` 會比對兩邊。改名、刪名照 `contract.py` 開頭的相容規則（舊名字留至少一個 MINOR、`RENAMED_*`）。
