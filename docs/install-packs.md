# 怎麼裝一個工具（.synoxpack）

`.synoxpack` 是一個工具（pack）壓成的檔。拿到它之後，用下面**任何一種**方法都可以裝；四種走的是**同一條安全檢查**：
SYNOX 先看宣告、掃程式（[security.md](security.md)「五關」），把報告給你看，**你按確認才會裝**。沒按確認，什麼都不會進 `packs/`。

手上不是 `.synoxpack`，而是一個 MCP 網址、要 `npx` 跑的程式、或 Claude 技能資料夾？先看 [install-third-party-tools.md](install-third-party-tools.md)。

| 方法 | 怎麼做 | 什麼時候用 |
|---|---|---|
| 1. 點兩下 | 在檔案總管點兩下 `.synoxpack` | 最簡單；`Setup.bat` 跑過就有 |
| 2. 拖到 `Install-Pack.bat` | 把 `.synoxpack` 拖到 SYNOX 資料夾裡的 `Install-Pack.bat` 上放開 | 點兩下沒反應、或檔案被別的程式接走時 |
| 3. 拖進網頁 | 打開 SYNOX 網頁（`Open-SYNOX.bat`），把 `.synoxpack` 拖進視窗；或「設定 → 功能」選檔按「上傳並檢查」 | SYNOX 已經開著；只有擁有者能裝 |
| 3b. 網頁的官方工具庫 | 「設定 → 🧩 功能與安裝 → 工具庫（官方）」按「載入工具清單」，挑一個按「安裝」 | 要裝官方工具（SYNOX_Libs）時；**只有按按鈕時才連網**，只連 GitHub 上 SYNOX_Libs 的發佈頁（網址寫死在 `src/synox/packs/catalog.py`）。伺服器下載後先對檔案大小與 sha256（跟清單一樣才收），再走同一份報告與確認 |
| 4. 命令列 | `.venv\Scripts\python.exe -m synox install <檔>.synoxpack` | 工程師、沒有網頁時（`--yes` 直接在終端機核准） |

## 1、2：點兩下、拖到 Install-Pack.bat

兩個其實是同一件事：都會跑 `Install-Pack.bat "<檔>"` → `python -m synox install`。

- **SYNOX 開著**：瀏覽器自動打開設定頁，上面是這個工具的安全報告和「確認安裝」按鈕（網頁要先登入：雙擊 `Open-SYNOX.bat`）。
- **SYNOX 沒開**：黑色視窗印出報告，告訴你兩條路：開 SYNOX 之後在網頁裝，或照它印的指令加 `--yes` 在終端機核准。

**檔案圖示與「點兩下」從哪裡來**：`Setup.bat` 在**目前這個 Windows 使用者**底下登記 `.synoxpack` 檔案類型
（`HKCU\Software\Classes\.synoxpack` 與 `HKCU\Software\Classes\SYNOX.Pack`；不用管理員、不影響別的使用者），
畫面上一行一行印出寫了哪些機碼（`+` 寫了、`=` 本來就一樣），重跑不會重複寫。登記之後 `.synoxpack` 會顯示**藍綠色底、白色下載箭頭的圖示**
（`src/synox/assets/synoxpack.ico`），點兩下＝「用 SYNOX 安裝」。

- 看現在登記了什麼：`.venv\Scripts\python.exe -m synox filetype status`；自己重新登記：`… filetype register`。
- 不想要：安裝精靈最後一頁取消勾「讓 .synoxpack 檔案點兩下就安裝」，或 `… filetype unregister`；`Uninstall.bat` 也會拿掉。
- **還是空白圖示／點兩下沒反應？** 檔案總管會快取圖示：按 F5 重新整理，或登出再登入。如果你曾經對 `.synoxpack` 選過
  「開啟檔案 → 一律使用這個應用程式」，Windows 會照你那次的選擇（`UserChoice`），SYNOX 不會蓋掉它：
  在檔案上按右鍵 →「開啟檔案」→「選擇其他應用程式」→ 選「用 SYNOX 安裝」，或直接用方法 2、3。
- 把 SYNOX 資料夾搬到別的地方之後，再跑一次 `Setup.bat`（或 `filetype register`），圖示與點兩下才會指到新位置。

## 3：拖進網頁

SYNOX 網頁的任何一頁都可以把 `.synoxpack` 拖進來：畫面會出現「放開來檢查這個 .synoxpack」，放開之後自動切到設定頁、上傳、
顯示同一份安全報告和確認按鈕（跟按「上傳並檢查」完全一樣）。

- 一次一個檔；只收 `.synoxpack`（或 `.zip`）、最多 5 MB。伺服器還會再驗一次：只有擁有者、檔案要從 zip 檔頭開始
  （前面接了東西的自解壓 exe 一律拒）、大小上限，再跑宣告檢查和靜態掃描。
- 這一步只是「上傳並檢查」；**裝要你在報告下面按確認**。T2 工具（有掃不到內容的執行檔）還要勾選並輸入發行者名字。

## 4：命令列

```
.venv\Scripts\python.exe -m synox install notes-1.0.0.synoxpack            # 印報告；SYNOX 開著就打開網頁給你按確認
.venv\Scripts\python.exe -m synox install notes-1.0.0.synoxpack --yes      # 看完報告直接在終端機核准
.venv\Scripts\python.exe -m synox tools install notes money                 # 從工具庫（tools\）挑、對雜湊，再走同一條路
```

同名已經裝了＝升級：會先列「改了什麼」；退回用 `python -m synox packs rollback <名字>`。更多（找工具、更新、移除）：[ecosystem.md](ecosystem.md)。

## 工具標了「⚠️ 警告」時

有些工具的作者會在工具上標警告（pack.json 的 `warnings`，[ADR 0041](adr/0041-pack-warnings.md)），例如
「⚠️ 官方不保證安全——建議在 docker 或 sandbox 執行」。這種工具：

- 報告最上面（SYNOX 的標章正下方）用紅字列出每一條警告；工具頁、設定頁、/help、doctor、給 AI 的工具清單也一直都會顯示。
- **第一次要用時要你逐條確認**，沒確認就不裝、不啟用：
  - 網頁：在報告上每一條警告前面勾「我知道」，「確認安裝」才按得下去。
  - 終端機：照報告印的指令加 `--accept-warning <代號>`（每條一個），例如
    `python -m synox install search.synoxpack --yes --accept-warning vendor_no_security_guarantee`。
  - 升級：之前確認過的沿用；新版多了的警告要再確認一次（升級報告會紅字列出）。
- 已經裝了、但還沒確認的（例如舊版 SYNOX 裝的）：設定頁寫「有警告還沒確認，先不開」。重新從安裝頁裝一次並勾選，或在電腦上跑
  `python -m synox packs lock --approve <名字> --accept-warning <代號>`。
- 標了「官方不保證安全」的工具不可能同時是「✅ 官方」：真的遇到兩個都有的，SYNOX 會拒裝（那份檔不對，向給你的人問清楚）。
- 確認只是「我知道了」，不會讓工具變安全：照建議，把這類工具放在 docker 或 sandbox 裡跑（安裝報告的「🧱 執行環境」能選容器的就選容器）。
  **SYNOX 不會因為有這個警告就自動把工具隔開**：Windows 個人版目前 SYNOX 自己還沒有沙盒（設定頁「沙盒模式」寫「⏳ 尚未完成」），
  能用的只有「工具有提供容器、這台裝了 docker 或 podman、安裝時選用容器」這一條。細節：[ADR 0041](adr/0041-pack-warnings.md) 第 5 節。

## 我自己把資料夾放進 packs/ 可以嗎？

**不行，SYNOX 不會載入它。** 只有經過上面四種方法、看過報告、你按過確認的工具才會跑（ADR 0028 §4）。
直接複製進 `packs\` 的資料夾（或是瀏覽器、同步軟體、別的程式偷偷放進來的）沒有經過檢查，SYNOX 一律當作「沒有經過安裝頁」：

- **你會看到**：SYNOX 啟動時通知你一次「⚠️ 有一個工具不是從安裝頁裝的，SYNOX 沒有載入它」；設定頁的工具清單那一列寫
  「⛔ 沒有經過安裝頁，沒有載入」；`python -m synox doctor`、`python -m synox packs status` 也會列出來。它的指令打了跟不存在一樣。
- **要用它**：到網頁「設定 → 功能與安裝」，在那一列按「**送去安裝頁檢查**」。SYNOX 把那個資料夾原地打包、跑跟上傳一模一樣的檢查，
  給你同一份報告和確認按鈕；按確認之後，原本的資料夾搬到 `packs\_removed\`（不刪），裝進去的是檢查過的那一份。
  工具的資料在 `data\`，不會被動到。
- **不是你放的**：不要按確認，把 `packs\` 裡那個資料夾刪掉就好。
- **以前版本手放的工具**：升級 SYNOX 之後會變成「沒有經過安裝頁」，不會被刪、資料也還在；照上面按一次「送去安裝頁檢查」就好。
- **工程師（config.json 的 `packs.dirs`）**：`packs.dirs` 指過去的資料夾（例如別的 repo 裡的 pack）一樣不載入，而且不能「送去安裝頁」
  （那個資料夾不歸 SYNOX 管、搬不了）。在電腦上跑 `.venv\Scripts\python.exe -m synox packs lock --approve <名字>`：
  它會跑同樣的檢查、印報告，過了才鎖起來；之後重新載入（或重開 SYNOX）就會載入。改了檔案要再跑一次。
