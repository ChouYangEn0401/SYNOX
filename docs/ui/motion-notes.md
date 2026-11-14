# 開場動畫與微動畫（2026-11-12，分支 `feat/ui-splash`；2026-11-14 改成「點一下打開 SYNOX」的門）

> **2026-11-14 更新：開場變成一道門**（擁有者：每次打開網頁都要看到開場、停在那裡等人點；左上角的 S 點了再看一次）。
>
> - **每次打開網頁**（含重新整理、登入後回到首頁、還沒登入時的登入畫面）都會出現：S 寶寶照下面的時間表掉下來、眨眼、說「嗨！」、
>   翻成 S、SYNOX 跳出來，約 **1.3 秒播到最後一格就停住**——S 輕輕上下浮、外面一圈光一直往外擴，下面一顆小膠囊寫
>   **「點一下打開 SYNOX」**（有鍵盤的電腦多寫「或按 Enter」）。不會自己消失。
> - **點畫面任何地方、或按 Enter／空白鍵／Esc** → 整片往前放大、淡掉（0.45 秒），後面的側欄和內容同時浮上來。動畫還沒播完就點也可以。
> - **門是真的對話框**：`role="dialog"`、`aria-modal`，中間的 S 寶寶是一顆 `<button aria-label="點一下打開 SYNOX">`；
>   有鍵盤的電腦一打開焦點就在它上面，Tab 不會跑到後面的畫面；門關了焦點還給原本的地方（例如左上角的 S）。觸控螢幕不搶焦點。
> - **減少動態效果**：不播任何動畫，直接是最後一格（S 標誌朝前、SYNOX、提示亮著），**一樣等你點**，點了馬上進去（`.sx-still`）。
> - **左上角（手機是上方列左邊）的 S** 變成按鈕（`#brand-mark`、`data-splash-replay`、提示「再看一次開場」）：點了再開一次同一道門。
>   樣子跟原本一樣（外觀包換了 `mascot.idle` 也照樣是按鈕）；手指按得到的範圍往外多 7px。
> - **外觀**：換了 `opening` → 門的按鈕裡放的就是外觀的開場（尺寸規則照舊，見 [themes.md](../themes.md)）；換了 `wordmark` → SYNOX 那五個字換成字標。
> - **新手教學的邀請**（「要不要我帶你走一遍？」）等門關了才出現（`tour.js` 聽 `document` 上的 `synox:splash-done`）。
> - **登入**：伺服器的「登入確認頁」（按登入連結先到的那一頁）是另一頁，**沒有門**；按「登入」回到網頁介面時會出現一次。
>   還沒登入時打開網頁介面＝門 → 登入說明卡。
> - **自動化與預覽跳過門**：網址 `?splash=0`；或在頁面載入前設 `window.SYNOX_NO_SPLASH = true`（Playwright：
>   `context.add_init_script("window.SYNOX_NO_SPLASH = true;")`，`scripts/ui_tour_smoke.py` 就是這樣）；或 `localStorage` 的
>   `synox.splash` 設成 `off`（使用者自己關）。`?splash=1` 一定出現（蓋過上面兩個）。設計預覽 `docs/ui/preview.html` 預設不出現，
>   預覽列的「重播開場」＝`?splash=1`；手機預覽的「登入」那一格會出現門。
> - 檔案：`static/splash.js`（`decide`／`build`／`open`／`isOpen`，不再有「時間到自己收掉」）、`static/splash.css` 的「網頁介面的門」一段
>   （放在「開場時：」之後，所以 `scripts/make_landing.py` 不會把它帶進介紹頁；介紹頁有自己的 SynoxGate）、`app.html` 的 `#brand-mark`、
>   `tour.js` 的 `offer`。測試：`tests/js/test_splash.js`、`tests/test_motion.py`。
>
> 下面是原本（自動播完就淡出）的說明；時間表 0～1.3 秒那段照舊，1.25 秒之後的「淡出」改成「停住等你點」。

**結論**：SYNOX 網頁打開時，會有一隻「S 寶寶」掉下來、眨眼、說「嗨！」，翻面變成 S 標誌，SYNOX 五個字跳出來，
整段約 **1.7 秒**，點一下或按任何鍵就略過；**同一個分頁只播第一次**（重新整理、登入後都不再播）。
另外加了頁面切換、卡片進場、按鈕、狀態點的小動畫，以及背景很淡的光暈呼吸和慢慢往上飄的小光點。
版面（側欄、對話頁、工具頁、設定頁）一個像素都沒動；系統開了「減少動態效果」時，開場不播、其他動畫全關。

**怎麼看**：雙擊 [preview.html](preview.html)（第一次打開就會播）；右上角預覽列的「重播開場」＝`?splash=1`。
手機寬度：[preview-phone.html](preview-phone.html) 的「登入」那一格每次打開都重播。
關鍵影格的截圖在 [screenshots/](screenshots/)（`splash-*.png`、`motion-background-light.png`）。

擁有者原話（2026-11-12）：「synox 打開可不可以跟 isdpcs 學一下，絢麗的動畫，讓人會喜歡上這個可愛的工具 !!」

## 檔案

| 檔案 | 做什麼 |
|---|---|
| `src/synox/web/static/splash.js` | 開場：判斷要不要播、用 `createElement`＋`textContent` 畫出來、計時收掉。不讀資料、不打 API（可拆卸零件） |
| `src/synox/web/static/splash.css` | 開場的樣子與時間表，加上全站的微動畫與背景 |
| `src/synox/web/static/app.html` | 只多兩行：`<head>` 最後的 `/*{{INCLUDE:splash.css}}*/`、`<body>` 一開始的 `/*{{INCLUDE:splash.js}}*/` |
| `tests/test_motion.py`、`tests/js/test_splash.js` | 靜態檢查（同一個 nonce、沒有外部資源、只用 token 顏色、有 reduced-motion）＋播放規則與「一定收得掉」 |

伺服器送出頁面時照舊用 `server.render_app` 把兩個檔原地塞進 `<style>`／`<script>`（同一個 nonce），**CSP 沒有放寬、server.py 沒有改**。

## 開場時間表（毫秒）

| 時間 | 畫面 | 手法 |
|---|---|---|
| 0 | 整片背景＋中間一圈主色光暈出現 | `sx-halo`：scale .25→1 |
| 0–600 | S 寶寶（圓角方塊、有眼睛、腮紅、笑臉）從上面掉下來，落地壓扁、彈起、站好 | `sx-drop`：squash & stretch（1.12×0.86 → 0.95×1.06 → 1） |
| 120–1100 | 身邊噴出 6 顆小圓點＋2 顆 ✦（主色、副色、綠、琥珀、粉） | `sx-fly`：每顆自己的方向 `--dx`／`--dy`、錯開 `--d` |
| 200–700 | 眨一次眼、臉紅 | `sx-blink`：scaleY 1→.12→1 |
| 380–1280 | 右上冒出「嗨！」對話框，彈一下後淡掉 | `sx-hi`：從左下角長出來、轉一點點 |
| 620–1320 | SYNOX 五個字母一個一個跳上來（每個差 50 毫秒） | `sx-letter`：overshoot 曲線 |
| 720–1220 | 卡片翻面，背面是 S 標誌（跟側欄的 `.mark` 同一個漸層） | `sx-flip`：rotateY 0→180°，曲線會多轉一點再回來 |
| 850– | 下面三個小點輪流跳（像「準備中」） | `sx-hop` |
| 1020–1720 | S 標誌上掃過一道光 | `sx-shine` |
| 1250–1670 | 整片淡出、S 往上縮；**同時**側欄從左滑進、內容往上浮 | `sx-out`（最後 `visibility: hidden`）＋拿掉 `html.sx-hold` |
| 1700 | 拿掉開場的元素 | `splash.js` 的計時器 |
| 2600 | 保險：不管發生什麼都收掉 | `SAFETY` |

開場期間，後面的頁面照常載入（不會因為動畫晚 1.7 秒才能用）；只是側欄和內容的進場動畫先停在第 0 格（`html.sx-hold`），
淡出那一刻才一起播，看起來是「開場 → 進到 SYNOX」一口氣接起來。

**什麼時候播**（`splash.js` 的 `decide`，有測試）：

1. 系統開了「減少動態效果」→ 永遠不播。
2. 網址 `?splash=1` → 重播；`?splash=0` → 不播。
3. 瀏覽器的 `localStorage` 裡 `synox.splash` 是 `off` → 不播（目前只能在主控台打 `localStorage.setItem("synox.splash", "off")`；
   要不要在設定頁放開關見 [QuestionToUser.md](../QuestionToUser.md) QM1）。
4. 其他：這個分頁第一次打開才播（`sessionStorage` 的 `synox.splash.seen`）。登入前看到開場 → 按登入連結回來不會再播；
   直接用登入連結打開 → 登入完回到首頁時播一次。私密視窗、`file://` 讀不到儲存空間時照播，不會出錯。

## 其他微動畫

| 哪裡 | 做什麼 | 時間 |
|---|---|---|
| 頁面切換（對話／工具／主控／設定／登入） | 新的那頁往上浮 10px 淡入。區塊從隱藏變顯示時 CSS 自己重播，不用改 JS | .34s |
| 設定頁、主控頁的卡片、登入卡 | 一張一張浮上來（每張差 50 毫秒，最多 .25s） | .44s |
| 登入卡的 S | 每 3.2 秒輕輕浮一下、歪一下頭（像在等你） | 無限 |
| 按鈕 | 滑過浮起 1px（主要按鈕多一圈主色的影子）；按下壓扁一點（.96） | .2s／.06s |
| 側欄分頁 | 滑過圖示歪一下；切到的那頁圖示「啵」一下 | .25s／.45s |
| 側欄的 S | 滑過搖一下 | .5s |
| 對話泡泡 | 從說話的那一邊「啵」出來（自己的從右下、SYNOX 的從左下） | .3s |
| 提示條（toast） | 彈上來 | .32s |
| 對話標題旁的綠點 | 每 2.6 秒往外擴一圈淡掉（「在線上」的感覺） | 無限 |
| 背景 | 左下主色、右上副色兩團很淡的光慢慢飄、呼吸（24 秒來回）；小光點每 90 秒往上飄一格、亮暗 7 秒 | 無限 |

工具頁的卡片、主控頁的任務列不加進場動畫：它們會被程式重畫，每次重畫都跳一下會很吵。

## 取自 ISDPCS 的手法（`web/style.css`、`web/fireworks.js`，只讀）

| ISDPCS | 用在 SYNOX 哪裡 | 改了什麼 |
|---|---|---|
| 開機歡迎卡 `wc-rise`（往上 26px＋scale .98、`cubic-bezier(.2,.8,.2,1)`） | 卡片進場、頁面切換、側欄滑進（`--sx-rise`） | 距離縮小到 10～18px（SYNOX 一天開很多次） |
| 歡迎卡的 emoji `wc-pop`（scale .4＋轉 -14°、彈性曲線 `cubic-bezier(.2,1.5,.4,1)`） | 字母跳上來、分頁圖示「啵」、泡泡、toast（`--sx-pop`） | — |
| 歡迎卡的掃光 `wc-shine` | S 標誌翻面後掃過一道光 | 深淺色都看得到（`mix-blend-mode: screen`＋兩道 token 色） |
| 收工小煙火 `fireworks.js`（`--dx`／`--dy`／`--d`、`fw-fly` 900ms、可拆卸、尊重 reduced-motion） | 開場的 8 顆小光點；整個開場也照「可拆卸零件」寫 | 方向寫死在 CSS（不用 JS 改樣式，CSP 更乾淨），顏色用 token |
| 番茄鐘的 `breathe`（scale 1.06、opacity 4.5s） | 開場光暈、背景兩團光 | 背景放慢到 24 秒、只到 10% 透明度 |
| 狀態點 `tb-pulse`（box-shadow 一圈往外擴） | 對話標題旁的綠點 | 改成 `::after` 的 transform＋opacity（不重畫陰影，比較省） |
| `--bg-glow` 頂部光暈、`cubic-bezier(.2,.9,.3,1)` | SYNOX 本來就有（`--ease`），開場的背景也用它 | — |
| `@media (prefers-reduced-motion)` 全關 | 同樣全關，開場直接不產生 | — |

沒取的：霓虹發光、通知鈴的搖晃、鬧鐘的閃爍（SYNOX 要穩重一點，會一直閃的東西會干擾看字）；歡迎卡的音樂（網頁不自己出聲）。

## 怎麼關

- **使用者**：Windows「設定 → 協助工具 → 視覺效果 → 動畫效果」關掉（或手機的「減少動態效果」）→ 全部動畫停；開場的門照樣出現（不動的最後一格），點一下進去。
  連門都不要：瀏覽器主控台 `localStorage.setItem("synox.splash", "off")`。
- **開發者**：拿掉整個開場＝刪 `app.html` 那兩行 include（`splash.css` 裡的微動畫也會一起拿掉）；只拿掉開場＝只刪 `splash.js` 那一行
  （`.sx-*` 的樣式沒有元素就不會作用）。其他程式沒有一行依賴它。

## 效能

- 只動 `transform` 與 `opacity`（瀏覽器可以交給 GPU 合成，不重新排版）；唯一的例外是開場的眼睛、腮紅這些很小的元素。
- 沒有 `filter: blur`、沒有圖片、沒有字型檔、沒有 canvas、沒有 `requestAnimationFrame` 迴圈；背景是兩個 `body::before／::after`
  的漸層，用 `transform` 慢慢移（90 秒一格），不吃滑鼠（`pointer-events: none`）。
- 一直跑的動畫只有：背景兩層、對話頁的綠點、登入卡的 S、開場的三個小點（開場結束就拿掉）。都是很小的合成層。
- 開場的 JS 不到 150 行，只在載入時跑一次；開場期間頁面的資料照常載入。

## 驗證到哪裡（誠實版）

- **看過的**：用 headless Chrome（沙箱照開、暫存 profile、只開自己產生的 `file://` 預覽、不開除錯埠）把動畫停在指定毫秒拍下來：
  深色 200／520／860／1180／1450 毫秒、淺色 520／1180 毫秒、手機寬（390px，淺色）1180 毫秒、淺色登入頁的背景、深色設定頁。
  停格的方法：預覽檔的 `?splashat=毫秒`（`document.getAnimations()` 全部暫停在那一格，只有預覽檔有，伺服器送的頁面沒有）。
- **沒看過的**：**動畫順不順、節奏對不對，靜態截圖看不出來**——要在真的瀏覽器雙擊 `preview.html` 看；沒有在真的手機、Safari、
  Firefox 上看過；沒有量過低階電腦的幀率；「減少動態效果」只用靜態測試確認規則存在，沒有實際切系統設定看。
- 測試：`tests/test_motion.py`（靜態檢查＋用 node 跑 `tests/js/test_splash.js`）。不開瀏覽器、不開埠、不連網。
