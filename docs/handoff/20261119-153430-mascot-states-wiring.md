# 交辦單：吉祥物（外觀包的四個狀態）出現在哪裡——先盤點，再接上「AI 實際發生的事」與空狀態／錯誤頁

> 這份是**交辦單**：給一個完全空白的 session（另一台電腦、docker、雲端都可以），沒有對話紀錄、沒有開發機上的檔案，**只讀這份就能開工**。

---

## 1. [狀態]

**待做**（2026-11-19 寫；今天只寫交接，沒有人開工）。

| 項目 | 值 |
|---|---|
| 基底 | `origin/dev`；寫這份時是 `bb465f5` |
| 誰在做 | 還沒有人接 |
| 卡住的地方 | 無。有一題要維護者決定（常駐吉祥物預設開或關，見 §2.5），**不影響這張單**：這張單不做常駐吉祥物 |

接手後把這一段改成「進行中：做到 §3 第幾步；分支 `feat/mascot-states-<YYYYMMDD>`；最新 commit `<hash>`」，卡住就寫「卡住：卡在哪、為什麼」。

## 2. [前情提要]

### 2.1 為什麼要做

- 外觀包（`pack.json` 的 `kind: theme`，規格見 [../themes.md](../themes.md)）可以換掉：四個吉祥物狀態、開場動畫、分頁圖示、字標、對話背景，以及一組顏色 token。
  顏色 token 由 SYNOX 在 `src/synox/theme/contract.py` **單一宣告**，外觀包只覆蓋（[ADR 0042](../adr/0042-theme-tokens-single-source-and-forward-compat.md)）。
- 問題：使用者平常**很少看到吉祥物**。開場播完、點一下進去之後，畫面上幾乎只剩文字；所以換外觀（「衣櫃」）的價值目前主要在顏色，不在吉祥物。
- 想要的是：吉祥物的四個狀態出現在「使用者本來就在看的地方、而且對應到真的發生的事」，讓換外觀換得有感覺。

### 2.2 四個狀態對應的 slot（合約第 1 版，**不改名、不新增**）

| 狀態（白話） | slot 名字 | 合約說明（`contract.SLOTS`） | SYNOX 預設長相（`theme/defaults.py`） |
|---|---|---|---|
| 平常 | `mascot.idle` | 側欄與登入卡左上角的標誌、空白對話的插圖 | 「S」方塊（`app.html` 的 `.mark` 本身） |
| 想事情 | `mascot.think` | 等 AI 回覆時那顆會晃的小方塊 | 藍色小方塊 SVG（`THINK`） |
| 完成 | `mascot.happy` | 裝好、套用成功的時候 | 笑臉的 S 寶寶（`HAPPY`） |
| 要你確認／注意 | `mascot.warn` | 安裝被拒、出問題的時候 | 擔心的 S 寶寶（`WARN`） |

其他 slot：`opening`（開場動畫）、`wordmark`（字標）、`appicon`（分頁圖示，只收 SVG）、`chat.background`（對話背景）。
「要你確認」沿用 `mascot.warn` 這一格（已決定：不新增 slot）；如果要改 `contract.SLOTS` 裡的**說明文字**讓它也涵蓋「要你確認」，可以改說明，**不改名字、不改版號**。

### 2.3 寫這份時讀程式看到的現況（**已查證**＝讀了 `bb465f5` 的程式；盤點時要再確認一次）

| 位置 | 用到的 slot | 在哪 |
|---|---|---|
| 側欄左上角的標誌（也是「再看一次開場」的按鈕） | `mascot.idle`、`wordmark` | `src/synox/web/static/app.html`（`brand-mark`、`.brand .name`） |
| 登入卡左上角 | `mascot.idle` | `app.html`（登入區的 `.mark`） |
| 空白對話（「還沒有訊息」） | `mascot.idle`——**只有外觀包有給時才放**，沒給就只有文字 | `app.html` 的 `emptyNode()` |
| 送出訊息後等 AI 回覆的提示 | `mascot.think` | `app.html` 的 `pendSet()`（收到新回覆就收起來） |
| 安裝報告「不能裝」那一行 | `mascot.warn` | `app.html`（安裝頁，`scan.problems` 不空時） |
| 安裝／升級完成 | `mascot.happy` | `app.html` 的 `showInstalled()` |
| 開場 | `opening`、`wordmark` | `static/splash.js`（每次打開網頁都播，停在最後一格等點；`localStorage` 的 `synox.splash=off` 或 `?splash=0` 不播；系統「減少動態效果」時不播動畫、直接最後一格） |
| 外觀預覽頁 `/theme/preview` | 四個狀態、`opening`、`wordmark` | `src/synox/theme/appearance.py`（預覽用） |
| 伺服器自己產生的小頁（404、登入失敗…） | **沒有**：寫死一個文字「S」 | `src/synox/web/server.py` 的 `_page()`（CSP `default-src 'none'`、只放行 inline style） |
| 工具頁、通知、說明、手機入口等其他前端（`static/*.js`） | **沒有**（只有 `slots.js`、`splash.js` 碰 slot） | `grep -l "SynoxSlots\|slotNode" src/synox/web/static/*` |

另外兩件**推測**、要在盤點時確認的：

- 網頁對話裡的**核准卡**（[ADR 0037](../adr/0037-approval-cards-upgrade.md)）送到前端時只是一則帶按鈕的訊息（`src/synox/web/chats.py` 的訊息只有 `text`、`buttons`、`at` 這類欄位），前端**分不出「這是一張核准卡」**。
  要接「要你確認」，可能要在伺服器加一個**可選**欄位（例如訊息上的 `mood: "confirm"`），舊前端忽略即可；用按鈕的 `data` 前綴去猜比較脆弱，不建議。
- 「工具跑完」目前在網頁上有沒有獨立的事件或畫面（還是只是 AI 的下一則回覆），要盤點時找出來；沒有的話 ① 的「完成」就先只接在已有明確結果的地方。

### 2.4 已想過的方向（建議順序）

| 順序 | 方向 | 這張單做不做 |
|---|---|---|
| ① | 把四個狀態接到 AI 實際發生的事上：AI 回答中的輸入指示器＝想事情、工具跑完＝完成、核准卡片＝要你確認 | **做**（§3 第二步） |
| ③ | 空狀態與錯誤頁以吉祥物為主角（空白對話、沒有結果的清單、404 等伺服器小頁） | **做**（§3 第二步） |
| ② | 側欄或標題列的小型常駐吉祥物（可以關） | 不做；預設開或關是維護者的決定（§2.5） |
| ④ | 開場縮短、可略過，只在「久睡後回來／重啟後／第一次換外觀」時才播 | 不做（之後另開單） |
| ⑤ | 長期：讓 AI 依一句話生成一套顏色（資料注入；ADR 0042 的單一宣告就是為這個鋪路） | 不做 |
| ⑥ | 外部頻道（Telegram／Discord）的頭像或貼圖跟著狀態 | 不做 |

（表上順序是建議的做法順序，① ③ 先做；② ④ 之後；⑤ ⑥ 長期。）

### 2.5 要維護者決定的事（開工前看；**都不擋這張單**）

| 題目 | 沒決定時的預設 |
|---|---|
| [常駐的小吉祥物預設開還是關](open-questions/20261119-153432-mascot-always-on-default.md) | 關（而且這張單不做常駐吉祥物） |

### 2.6 相關文件與測試

| 東西 | 在哪 |
|---|---|
| 外觀合約與 slot 規格 | [../themes.md](../themes.md)、`src/synox/theme/contract.py`（`SLOTS`）、[ADR 0042](../adr/0042-theme-tokens-single-source-and-forward-compat.md) |
| slot 的載入 | `src/synox/web/static/slots.js`（`SynoxSlots.has／get／make／fill`；伺服器在 `<head>` 放 `<template data-slot-src>` 與 `<template data-slot-default>`） |
| 外觀包的消毒 | `src/synox/theme/sanitize.py`、`theme/pack.py`（第 2 關：每個 slot 檔都消毒、白名單重建） |
| 動態效果的規則 | [../ui/motion-notes.md](../ui/motion-notes.md) |
| 外觀的真機清單 | [../testing/theme-apply-checklist.md](../testing/theme-apply-checklist.md) |
| 相關自動測試 | `tests/test_theme.py`、`tests/test_theme_compat.py`、`tests/test_wardrobe.py`、`tests/test_motion.py`、`tests/test_tools_page.py`、`tests/test_web.py` |

## 3. [任務]

### 3.1 第一步：盤點（先做完、先 commit，再做第二步）

1. 讀 `src/synox/web/static/app.html`、`static/*.js`、`static/slots.js`、`static/splash.js`、`src/synox/web/server.py`、`src/synox/web/chats.py`、`src/synox/theme/appearance.py`，
   以及任何會產生 HTML 的地方（`grep -rn "<html\|_page(" src/synox`）。
2. 回答兩個問題，寫成盤點表 **`docs/design/mascot-inventory.md`**（`docs/design/` 寫這份時還不存在，自己建）：
   - 四個狀態（`mascot.idle／think／happy／warn`）與 `opening`、`wordmark`、`appicon`**現在各被用在哪些畫面**（畫面名、檔案與函式、觸發條件、沒有外觀包時長怎樣）；
   - **哪些畫面完全沒用到**吉祥物（列出每一個使用者看得到的畫面與狀態：空清單、錯誤、載入中、核准卡、工具結果、設定各頁、工具頁、404／登入失敗等伺服器小頁、手機入口）。
3. 表後面加一節「機會」：每個沒用到的畫面一行，標「對應哪個狀態」「屬於 ① 還是 ③」「這張單做不做（不做的寫原因）」。
4. 盤點表只寫技術事實，不寫任何人的原話、不放截圖裡的私人資料（截圖不必要；要放就用假資料的畫面）。

### 3.2 第二步：照盤點做 ① 與 ③ 的接線

5. **①**：把狀態接到真的發生的事（以盤點的結果為準；至少這三個）：
   - 想事情：AI 正在回答的輸入指示器（現在 `pendSet()` 已用 `mascot.think`，確認所有「等 AI」的地方都一樣用它，沒有的補上）；
   - 完成：工具跑完、有明確結果的時候（盤點找出位置；只在有結果的那一刻出現一次，不常駐）；
   - 要你確認：核准卡（ADR 0037 的卡）上用 `mascot.warn`。前端分不出核准卡時，伺服器加**可選**欄位，舊前端與 Telegram／Discord 不受影響。
6. **③**：空狀態與錯誤頁以吉祥物為主角：
   - 空白對話：沒有外觀包時也顯示 SYNOX 預設的吉祥物（現在沒外觀包就只有文字）；
   - 其他盤點出來的空清單；
   - 伺服器小頁（`_page()` 的 404、登入失敗…）：用已消毒的 slot 內容或 SYNOX 預設的 SVG，**不加外部資源、不放寬 CSP**（只能是 inline 的 SVG 標記）。
7. **沒有外觀包、或外觀包沒提供那一格時，一律沿用 SYNOX 預設**，不能出現空框、破圖、`alt` 文字或 404 的圖。
8. 每一處都要有：
   - **深淺色**：只用 token 上色（`.cb-*`、`.sb-*` 這類 class，或 `var(--…)`），不寫死顏色；淺色、跟隨系統的深色、強制深色三種都看得清楚；
   - **減少動態效果**：`prefers-reduced-motion: reduce` 時不晃、不動（CSS 動畫停、SVG 的 `<animate>` 用 `pauseAnimations()`，照 `slots.js` 的 `settle()` 的做法），只留靜止圖；
   - **無障礙**：吉祥物是裝飾（`aria-hidden="true"`），意思由旁邊的文字說；不要讓報讀器多念一次；
   - **自動測試**（見 §5 V8～V12；放在既有的 `tests/test_theme*.py`、`tests/test_web.py`、`tests/test_motion.py`，或新增 `tests/test_mascot_states.py`）。
9. 文件：更新 [../themes.md](../themes.md)（每個 slot 會出現在哪些畫面）、`contract.SLOTS` 的說明文字（同樣只改說明）、`CHANGELOG.md` 的「未發佈」。
   如果在網頁 API 的訊息加了欄位（例如 `mood`），那是對外合約：照 [../adr/README.md](../adr/README.md) 先寫 ADR（用當時下一個空號；寫這份時下一號是 0043，另一張交辦單也可能用到，撞號照 README 的規則處理），並更新 [../runtime-api.md](../runtime-api.md) 或對應的 API 文件。

### 3.3 範圍邊界與不要做的事

- **不改顏色契約**：不動 `contract.py` 的 token 名單、`DEFAULTS`、`REQUIRED_COLORS`、`CONTRACT_VERSION`。
- **不新增必填 slot**，也不新增 slot 名字；舊外觀包照裝、照套用。
- **不動 pack 簽章**（`docs/signing.md`、`pack.sig.json`）與**警告機制**（ADR 0041）。
- **不在無外觀包時顯示壞圖**；任何外觀包給的內容都要經過既有的消毒（不繞過 `sanitize.py`、不用 `innerHTML` 放未消毒的東西）。
- 不做 ②（常駐吉祥物）、④（開場改版）、⑤（AI 生成顏色）、⑥（外部頻道）。
- 不改 Telegram／Discord 的行為。
- 不從網路抓任何圖或字型；不加外部 CDN。
- 不改 CSP 讓它變寬。
- 不合併、不推送。

## 4. [安裝流程與環境確認]

### 4.1 自己偵測環境（寫進回報；不寫電腦名稱、帳號名、路徑）

```sh
# 作業系統
uname -srm 2>/dev/null || ver          # Windows 的 cmd 用 ver；PowerShell 用 [System.Environment]::OSVersion.VersionString
python --version || python3 --version  # 要 3.11 以上（pyproject.toml 的 requires-python）
git --version
```

這張單**不需要** docker／podman、不需要 GPU、不需要任何雲端模型，也**不需要任何祕密**（測試全部用假的 LLM 與假外觀包）。

### 4.2 取得程式

```sh
git clone <SYNOX 的 repo 網址（見 docs/handoff/README.md 的「最短路徑」）> synox-mascot
cd synox-mascot
git fetch origin
git switch -c feat/mascot-states-<YYYYMMDD> origin/dev     # 你的工作分支；只在這裡 commit。同名已存在就換名字
git log --oneline -1                                       # 記下基底 commit
python -m venv .venv
# Windows： .venv\Scripts\python -m pip install -e ".[dev]"
# Linux／macOS： .venv/bin/python -m pip install -e ".[dev]"
python -c "import synox; print(synox.__file__)"            # 要在這個資料夾的 src/synox/ 底下
```

之後指令裡的 `python` 都是這個 `.venv` 的 python。

### 4.3 開工前先跑測試記基準（**還沒改任何東西時**）

```sh
python -m pytest -q -p no:cacheprovider tests/test_theme.py tests/test_theme_compat.py tests/test_wardrobe.py tests/test_motion.py tests/test_tools_page.py
python -m pytest -q -p no:cacheprovider tests/test_web.py
```

**參考基準**（來源：2026-11-19 在 `origin/dev`＝`bb465f5` 的暫時 worktree 實際跑出來；Windows、Python 3.11.9、pytest 9.2.0；`PYTHONPATH` 指向那個 worktree 的 `src`）：

| 測試檔 | 結果 |
|---|---|
| `test_theme.py`＋`test_theme_compat.py`＋`test_wardrobe.py`＋`test_motion.py`＋`test_tools_page.py` | **157 passed**（0 failed） |
| `test_web.py` | **58 passed**（0 failed） |

- 你那台的數字**以你自己跑出來的為準**，寫進回報；跟上表不同就寫差在哪（平台不同時可能有測試被略過）。
- 有 failed：先記下來是「本來就壞的」，不要修它（不在範圍），回報裡列出。
- 全部測試（`python -m pytest -q -p no:cacheprovider`）比較重，交回前跑一次就好。

### 4.4 看畫面（選做，但建議）

- 照 README 的進階安裝開 SYNOX；網頁**只綁 `127.0.0.1`**（SYNOX 預設，不要改）。開之前記下自己開的程序 pid 與埠號，**看完一定關掉**並確認埠已放掉
  （Windows：`Get-NetTCPConnection -LocalPort <埠>` 沒有東西；Linux／macOS：`ss -ltnp | grep <埠>` 或 `lsof -i :<埠>` 沒有東西）。
- 不碰那台電腦上別人開的服務；分不清是不是自己開的就當成別人的。
- 測外觀包用自己做的**假外觀包**（只放 `pack.json` 與幾個自己畫的簡單 SVG，格式見 [../themes.md](../themes.md)），不要裝網路上抓的外觀包。
- 不改防火牆、不開對外的埠。

### 4.5 開工前確認（全部是「是」才開始）

- [ ] 分支是從最新的 `origin/dev` 開的，基底 commit 記下來了。
- [ ] `synox.__file__` 在自己的資料夾底下。
- [ ] §4.3 的基準跑過，數字記下來了。
- [ ] 讀過 §3.3（不要做的事）。

## 5. [驗證清單集]

給高水準模型（驗收者）在 merge 前逐項確認。`<base>`＝`git merge-base origin/dev <branch>`，`<branch>`＝接手者的分支。
**每一項都要實際跑或實際看；有任何一項不通過就不 merge。**

| # | 檢查什麼 | 指令／怎麼看 | 預期 |
|---|---|---|---|
| V1 | 分支與基底 | `git log --oneline -1 <base>`；`git branch -r --contains <base>` | 分支叫 `feat/mascot-states-<YYYYMMDD>`（或回報裡說明的名字）；基底在 `origin/dev` 上 |
| V2 | 任務逐條都做了 | 對照 §3 第 1～9 條與回報的逐條結果 | 每一條都有「做了什麼＋在哪個 commit」；沒做的有理由且是 §3.3 允許的 |
| V3 | 盤點表存在且完整 | 讀 `docs/design/mascot-inventory.md` | 四個狀態＋`opening`、`wordmark`、`appicon` 各有「用在哪」；有「完全沒用到的畫面」清單與「機會」一節；每一列有檔案與函式名 |
| V4 | 盤點表跟程式對得上 | `grep -rn "slotNode\|SynoxSlots\|data-slot=" src/synox/web` 對照表 | 每一個用到 slot 的地方都在表上，表上的都找得到 |
| V5 | 顏色契約沒動 | `git diff <base> <branch> -- src/synox/theme/contract.py` | 只可能改 `SLOTS` 的**說明文字**；`DEFAULTS`、`FIXED`、`REQUIRED_COLORS`、token 名單、`CONTRACT_VERSION`、slot 名字都沒變 |
| V6 | 沒新增 slot | `git diff <base> <branch> -- src/synox/theme/ src/synox/web/static/slots.js` | `SLOTS` 的鍵與 `slots.js` 的 `NAMES` 跟 `<base>` 一樣 |
| V7 | 簽章與警告沒動 | `git diff --stat <base> <branch> -- src/synox/packs/ docs/signing.md docs/adr/0041-pack-warnings.md` | 簽章、警告相關的檔沒有改（如果 `packs/` 有改，回報要說明為什麼、而且跟簽章警告無關） |
| V8 | 沒外觀包時不壞 | 新測試：沒裝外觀包時，每個接上的位置都放了 SYNOX 預設的內容（不是空的） | 測試存在且通過 |
| V9 | 外觀包只給一部分時不壞 | 新測試：假外觀包只給 `mascot.idle`，其他格用預設 | 測試存在且通過 |
| V10 | 深淺色 | 新測試或檢查：接上的元素只用 class／`var(--…)` 上色；`git diff <base> <branch> -- src/synox/web/static/` 搜 `#[0-9a-fA-F]{3,6}` | 新增的行沒有寫死的顏色（QR code 那類原本就有的除外） |
| V11 | 減少動態效果 | 新測試（可以參考 `tests/test_motion.py` 的做法）：每個新加的動畫都在 `prefers-reduced-motion: reduce` 底下停掉 | 測試存在且通過 |
| V12 | 伺服器小頁 | 打一個不存在的網址（或測試裡呼叫 `_page`）：回應裡有吉祥物、CSP 標頭跟 `<base>` 一樣嚴 | 有吉祥物；`Content-Security-Policy` 沒變寬；沒有外部網址 |
| V13 | 核准卡 | 測試：核准卡那則訊息在網頁上帶 `mascot.warn`；Telegram／Discord 的輸出跟 `<base>` 一樣 | 通過；如果加了 API 欄位，舊前端（沒這個欄位時）照常 |
| V14 | 相關測試全過、沒比基準多壞 | `python -m pytest -q -p no:cacheprovider tests/test_theme.py tests/test_theme_compat.py tests/test_wardrobe.py tests/test_motion.py tests/test_tools_page.py tests/test_web.py`＋新測試檔 | 0 failed；passed ≥ 157＋58＋新增的數（平台不同時以驗收者在 `<base>` 上先跑一次的數字為準） |
| V15 | 全部測試沒比基準多壞 | 在 `<base>` 與 `<branch>` 各跑 `python -m pytest -q -p no:cacheprovider` | `<branch>` 的 failed 不多於 `<base>`，而且多出來的 passed 對得上新測試 |
| V16 | ADR 與文件已更新 | `git diff --name-only <base> <branch>` | 有 `docs/themes.md`、`CHANGELOG.md`；加了 API 欄位的話有新 ADR（號碼不撞）與 `docs/adr/README.md` 索引、API 文件 |
| V17 | 沒有 TODO／半成品 | 指令 C | 沒有輸出 |
| V18 | 整棵樹與所有 commit 訊息沒有私人資訊 | 指令 A（整棵樹）與 A2（commit 訊息） | 沒有輸出 |
| V19 | 沒有密鑰 | 指令 B | 沒有輸出 |
| V20 | 公開前檢查腳本 | `python scripts/prepublish_check.py --worktree-only`（沒有私人詞清單時加 `--allow-no-terms`，並在回報寫明） | 跟在 `<base>` 上跑的結果相比沒有新的問題 |
| V21 | 沒有外部資源 | `git diff <base> <branch> \| grep -nE '^\+.*https?://'` | 沒有新增指向外部的圖、字型、腳本（文件裡的連結除外，要逐個看） |
| V22 | commit 訊息 | `git log <base>..<branch>` | 每個 commit 寫做了什麼、為什麼；agent 做的結尾有共同作者行 |
| V23 | 收尾 | 看回報的「收拾」一段 | 自己開的 SYNOX 已關、埠已放掉（附確認指令的輸出）；假外觀包不在 repo 裡 |

指令（bash；Windows 用 Git Bash）：

```sh
# A：整棵樹的私人資訊（本機路徑、家目錄、信箱、常見的電腦名稱開頭）
git grep -nEi 'C:\\Users\\|/home/[a-z]|/Users/[a-z]|[a-z0-9._-]+@[a-z0-9-]+\.(com|net|org|tw|io)|DESKTOP-|LAPTOP-' <branch> -- . ':!*.lock'
#   → 只看這次新增或改到的檔案的結果；<base> 上本來就有的（例如 noreply 信箱、文件裡的範例）不算，但要在回報裡說明
# A2：commit 訊息
git log <base>..<branch> --format=%B | grep -nEi 'C:\\Users\\|/home/[a-z]|/Users/[a-z]|@[a-z0-9-]+\.(com|net|org|tw|io)|DESKTOP-|LAPTOP-' | grep -v 'noreply@'
# B：密鑰
git diff <base> <branch> | grep -nEi 'token\s*[:=]|api[_-]?key\s*[:=]|ghp_|sk-[A-Za-z0-9]{10}|BEGIN [A-Z ]*PRIVATE KEY|AGE-SECRET-KEY'
# C：TODO／半成品
git diff <base> <branch> | grep -nE '^\+.*(TODO|FIXME|XXX|待補|未完成)'
```

（私人詞清單由維護者另外保管，`prepublish_check.py` 會讀；驗收者那邊有清單就一定要跑 V20。）

驗收者回報格式：「V1～V23 逐項：通過／不通過（原因）」＋「留下的問題」。全部通過才由驗收者在 `dev` 上 `git merge --no-ff <branch>`，
merge commit 訊息寫這個分支做了什麼、為什麼（不要只留預設的 "Merge branch …"），再把這份交辦單的 [狀態] 改成「已完成：merge commit `<hash>`」。

## 6. [交回]

1. 結論一句話（全部做完／做到第幾條、卡在哪）。
2. 分支名、最新 commit（`git log --oneline -1`）、基底 commit。
3. 環境：作業系統與版本、Python、pytest（不寫電腦名稱、帳號名、路徑）。
4. 測試：§4.3 的基準數字、交回前同樣指令的數字、全部測試的 passed／failed（和基底比）。
5. §3 第 1～9 條逐條：做了什麼、在哪個 commit。
6. §5 驗證清單集裡自己能先檢查的（V1～V13、V16～V23）逐項自查結果。
7. 「收拾」：關了哪些自己開的程序（pid、埠）、確認埠已放掉的輸出。
8. 不確定的地方、想請維護者決定的事：照 `docs/handoff/open-questions/` 的格式另寫題目檔（問題一句話、脈絡、選項表標建議、驗收、不要做的事），**不要自己改已決定的事**。

**只 commit 在自己的功能分支；不合併、不推送。** 合併由驗收者照 §5 確認後用 `git merge --no-ff` 做。
維護者另外要你推到遠端讓驗收者拿時，才推那一條分支，推之前自己跑一次 V18～V20。
