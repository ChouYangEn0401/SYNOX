# 別台電腦實測：空白 Windows 上裝 SYNOX（git clone／安裝程式）

- 狀態：**待實測**（2026-11-12 寫；開發機只跑過 `scripts/clean_room_check.py` 的部分模擬）
- 為什麼：QL4——「要完全模擬使用者在空白電腦的狀況，不可以有 hidden dependency 或我這台的路徑架構」。設計在
  [docs/adr/0003](../adr/0003-distribution-git-clone-and-installer.md)。
- 誰做：擁有者（或實驗室的那台）。**這台開發機不打包 exe、不跑空白電腦測試。**

## 0. 準備（一定要「空白」）

選一種（由好到普通）：

- [ ] **Windows 10／11 的 VM**（Hyper-V「快速建立」、VirtualBox、Windows Sandbox 也行——Sandbox 關掉就全沒了，適合跑一次性的）。
- [ ] 或在實驗室的電腦上**新增一個本機 Windows 使用者帳號**（設定 → 帳戶 → 其他使用者 → 新增，選「我沒有這位人員的登入資訊」→
      「新增沒有 Microsoft 帳戶的使用者」）。**用一般使用者，不要給系統管理員**——SYNOX 不需要管理員。

那個帳號裡先確認（照實記下來，回報要用）：

- [ ] Windows 版本：設定 → 系統 → 關於（例如 Windows 11 23H2）。
- [ ] 有沒有 Python：開「命令提示字元」打 `py --version` 和 `python --version`。**最好兩個都沒有**（`python` 打開 Microsoft Store
      的那種也算沒有）。有的話也照樣測，但要記下版本。
- [ ] 有沒有 git：`git --version`（沒有也沒關係，A 路線可以用 Download ZIP）。
- [ ] 不要把開發機的任何資料夾、`.venv`、`config.json`、`data\` 複製過去。

要準備的帳號：一個**測試用**的 Telegram bot（跟 @BotFather 拿新的，不要用正式那支）、你的 Telegram 帳號。AI 先選「先不用 AI」或
「Claude Code」（那台有登入的話）；用金鑰的 AI 見最後「已知會缺的東西」。

---

## A. git clone（或 Download ZIP）路線

| # | 做什麼 | 預期 | 結果 |
|---|---|---|---|
| A1 | 有 git：`git clone <SYNOX repo 網址> C:\Users\<測試帳號>\Desktop\SYNOX 測試`（路徑**故意**有空白和中文）；沒 git：GitHub「Code → Download ZIP」解到同一個地方 | 資料夾裡有 `Setup.bat`、`src\`、`vendor\`，**沒有** `.venv`、`config.json`、`data\` | [ ] |
| A2 | （有拿到 tools 的話）把發佈的 `tools` 資料夾放進 `SYNOX 測試\tools\`（裡面要有 `index.json`） | — | [ ] |
| A3 | 雙擊 `Setup.bat` | 先問語言；然後「準備 Python 和套件」。沒 Python 時：winget 裝 Python 3.12（可能跳 UAC 或要同意條款）或下載可攜版；**整個過程不用打指令** | [ ] |
| A4 | 等它跑完 | 開出安裝精靈視窗（四頁）。**如果**出現「這個 Python 沒有視窗元件：改用文字版設定」→ 在同一個黑色視窗照問題回答（這也算通過，記下來） | [ ] |
| A5 | 精靈：選「只有我」→ 貼 bot token → 配對 → AI 選「先不用 AI」→ 完成並開始 | 手機收到「👋 我在了」 | [ ] |
| A6 | 手機打 `/help` | 有基本指令；**還沒裝任何工具**的提示，並且寫出工具庫位置（有 A2 的話是 `…\SYNOX 測試\tools`） | [ ] |
| A7 | 在 SYNOX 資料夾開命令提示字元：`.venv\Scripts\python.exe -m synox tools list` | 列出工具、建議組合；沒 A2 的話說「不知道工具庫在哪裡」 | [ ] |
| A8 | `.venv\Scripts\python.exe -m synox tools install notes` | 印出安全檢查報告、說「還沒裝」（沒加 `--yes`）。再加 `--yes` 跑一次 → 「✅ 裝好了：notes」 | [ ] |
| A9 | 雙擊 `Stop.bat`、再雙擊 `Start.bat`；手機打 `/note 買牛奶`、`/note_list` | 記下來、列得出來 | [ ] |
| A10 | `.venv\Scripts\python.exe -m synox doctor --offline` | 「資料夾：」是 A1 的資料夾、**沒有任何開發機的路徑**；工具「裝了 1 個（notes）」 | [ ] |
| A11 | 文字版也試一次：`.venv\Scripts\python.exe -m synox init` | 依序問：這台給誰用、Telegram（Enter 沿用）、AI、工具庫（Enter＝tools）、要裝哪些（打 `money`）→ 報告 → 問「裝 money？」→ 裝好 | [ ] |
| A12 | 把整個 SYNOX 資料夾**搬到**另一個位置（例如 `D:\SYNOX2` 或桌面另一個資料夾），在新位置跑 `.venv\Scripts\python.exe -m synox doctor --offline` | 預期：**`.venv` 會壞**（venv 記著舊路徑，這是 Python 的限制）→ 刪掉 `.venv` 重跑 `Setup.bat` 就好；config 裡的工具庫位置是相對的，不用改 | [ ] |
| A13 | 網頁：雙擊 `Open-SYNOX.bat` | 瀏覽器打開 127.0.0.1:8830 並登入 | [ ] |

## B. 安裝程式路線

### B-1 在發佈機上做出安裝程式（不是測試的那個空白帳號）

需要：一台可以上網的 Windows（實驗室那台即可）、Inno Setup 6（https://jrsoftware.org/isinfo.php ）、
官方 Python 3.12.x「Windows embeddable package (64-bit)」zip **和**同一版的完整安裝版（要 tkinter 才需要）。

- [ ] 1. `git clone` SYNOX 與 SYNOX_Libs（兩個放哪都可以）。
- [ ] 2. 用**同一版** Python 3.12 建乾淨 venv：`py -3.12 -m venv C:\build\venv` → `C:\build\venv\Scripts\python.exe -m pip install -e <SYNOX>`
- [ ] 3. `C:\build\venv\Scripts\python.exe <SYNOX>\scripts\lock_deps.py` → 產生 `<SYNOX>\requirements.lock`
- [ ] 4. `C:\build\venv\Scripts\python.exe -m pip download -r <SYNOX>\requirements.lock -d C:\build\wheelhouse --only-binary=:all:`
      再 `... -m pip download pip virtualenv "setuptools>=64" -d C:\build\wheelhouse`
- [ ] 5. `C:\build\venv\Scripts\python.exe <SYNOX>\scripts\lock_deps.py --wheelhouse C:\build\wheelhouse`（鎖檔多了 sha256）→ 把
      `requirements.lock` commit 進 SYNOX（只有這個檔）。
- [ ] 6. SYNOX_Libs：`set SYNOX_HOME=<SYNOX>` → `C:\build\venv\Scripts\python.exe <Libs>\scripts\build.py --out C:\build\tools`
- [ ] 7. 解開 embeddable zip 到 `C:\build\python-embed`；（要視窗精靈的話）裝好同版本的完整 Python（勾 tcl/tk）。
- [ ] 8. `C:\build\venv\Scripts\python.exe <SYNOX>\scripts\stage_installer.py --python-embed C:\build\python-embed --wheelhouse C:\build\wheelhouse --tools C:\build\tools [--tk-from "C:\Program Files\Python312"]`
      → 最後一行印出 ISCC 指令。
- [ ] 9. 跑那行 `ISCC.exe ...` → `<SYNOX>\dist\SYNOX-Setup-<版本>.exe`
- [ ] 10.（選做）簽章：見 QuestionToUser.md QD1。
- [ ] 11. 第三方授權清單：把 wheelhouse 每個套件的授權（`pip-licenses` 之類，或手抄）與 CPython 的 LICENSE 放進 stage（之後補進腳本）。

### B-2 在空白帳號上安裝

| # | 做什麼 | 預期 | 結果 |
|---|---|---|---|
| B1 | 把 `SYNOX-Setup-<版本>.exe` 複製到空白帳號，雙擊 | 沒簽章的話 SmartScreen 擋：「其他資訊 → 仍要執行」（記下有沒有被擋、防毒有沒有叫）。**不要求管理員**（沒有 UAC 盾牌） | [ ] |
| B2 | 照畫面裝（預設位置 `%LOCALAPPDATA%\Programs\SYNOX`） | 最後一頁勾著「Set up SYNOX now」 | [ ] |
| B3 | 按完成 | 跑出 Setup 的黑色視窗：「從附的 wheelhouse 離線安裝」。**把網路拔掉也要成功**（建議這一步先斷網） | [ ] |
| B4 | 等它跑完 | 視窗精靈（stage 時有 `--tk-from`）或文字版 init（沒有的話）。照 A5 填 | [ ] |
| B5 | 重做 A6～A11（指令路徑換成 `%LOCALAPPDATA%\Programs\SYNOX\.venv\Scripts\python.exe`） | 同 A；`tools list` **不用設定**就找到 `tools\`，而且列出全部工具 | [ ] |
| B6 | 控制台 →「應用程式」→ 解除安裝 SYNOX | 捷徑、開機啟動、`.synoxpack` 關聯消失；**`config.json`、`data\`、`packs\` 還在**（資料夾沒有整個被刪） | [ ] |
| B7 | 再裝一次 | 沿用舊的 `config.json` 與資料，不用重新設定（精靈裡是舊的值） | [ ] |

---

## 失敗時回報什麼（貼給 Claude 的格式）

```
步驟：A4（或 B3…）
那台：Windows 11 23H2；原本有沒有 Python：沒有；git：沒有；VM／新帳號：新帳號
看到的：（黑色視窗最後 20 行，或截圖）
doctor：.venv\Scripts\python.exe -m synox doctor --offline 的完整輸出（它不會印 token 和金鑰）
```

- 黑色視窗一閃就關：在 SYNOX 資料夾開命令提示字元，手動跑 `Setup.bat`，視窗就不會關。
- **不要**貼 `config.json`、`data\` 裡的任何東西、bot token、金鑰。
- 有「找不到某個檔」「C:\Users\<別的名字>\…」這種路徑的錯誤，一定要貼完整的那一行——那就是要抓的 hidden dependency。

## 已知會缺的東西（不算失敗，但請記下發生了沒）

- 用 API 金鑰的 AI（OpenAI、Anthropic、Gemini、相容端點）需要 `ntu_easy_llm`，它還不在 PyPI：init／doctor 會說「還沒安裝 ntu_easy_llm」（QD2）。
- 可攜版 Python 的 tkinter（B4）：沒驗證過，開不了就是文字版。
- 文字版 init 只有中文。
- 搬資料夾後 `.venv` 會壞（A12），要重跑 `Setup.bat`。
