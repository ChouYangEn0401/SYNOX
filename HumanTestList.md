# HumanTestList（要人親手測的）

給維護者看的待測清單：做了、但自動測試碰不到的東西（真的 GitHub 設定、真的瀏覽器、別台電腦、雲端 session、要維護者決定的驗收）。
電腦能自己跑的檢查在 [VerifyList.json](VerifyList.json)。這兩份只在 git clone 裡，不進發佈 ZIP／安裝程式。

格式：一行一件 `- [ ] 日期 · 什麼 · 怎麼測（步驟）· 看到什麼算過`。測過了打 `[x]`、寫日期與結果，搬到「測過了」。

## 待測

- [ ] 2026-11-19 · GitHub 的 Actions「prepublish check」讀得到私人詞清單 · 到 GitHub repo 的 Settings → Secrets and variables → Actions，新增 repository secret `SYNOX_PRIVATE_TERMS_TEXT`，內容貼維護者本機的私人詞清單（一行一個；不要貼進任何檔案或 issue）；之後推一次 commit，打開那次的 Actions → prepublish check 的紀錄 · 紀錄最後寫「私人詞清單：…（N 筆）」而不是「沒有私人詞清單」的警告，且結果沒有發現（綠勾）
- [ ] 2026-11-19 · v0.2.1 的 GitHub Release 附件要重建或刪掉 · 歷史在 2026-11-18 改寫過，v0.2.1 的 zip 與 Setup.exe 是用改寫前的原始碼建的；維護者決定：(A，建議) 從改寫後的 `dev` 打新 tag（例如 v0.2.2 或 v0.2.1-r1）照 docs/release-playbook.md 重建、上傳，舊附件刪掉；(B) 只刪舊附件、先不發新版 · 選定的做法做完後，Releases 頁上看不到改寫前建的附件；有新版的話下載 zip 解開，裡面沒有開發用文件（AGENTS.md、CLAUDE.md、HumanTestList.md、VerifyList.json）
- [ ] 2026-11-19 · Linux 從零走一遍交接文件，記 Linux 基準 · 開一個乾淨的 Linux 雲端 session，只照 docs/HANDOFF.md 與 docs/development.md：clone、建 venv、`pip install -e .`、跑全套 `python -m pytest -q`；把略過與失敗的測試清單記下來 · 每一步照文件都做得到（做不到或跟文件不同的地方逐條回報、修文件）；得到一份 Linux 基準（通過／略過／失敗數與失敗清單），寫回 docs/development.md 第 3 節
- [ ] 2026-11-19 · 假 AI 的網頁開發設定能開網頁、能對話 · 在 SYNOX 資料夾照 docs/development.md「開網頁介面（只用網頁、假 AI）」那列寫 `config.json`（`{"owner_id": 1, "llm": {"kind": "fake"}, "vault": {"mode": "file"}}`）；`python -m synox run --no-browser`；另一個終端機 `python -m synox open` 拿一次性登入連結，用瀏覽器打開，送一句話；測完 Ctrl+C 或 `python -m synox stop`，刪掉這份 config.json · 網頁在 `http://127.0.0.1:8830/` 打得開、送出的話有假 AI 的回覆；伺服器只綁 127.0.0.1；關掉後埠已放掉（再開一次不會說埠被佔用）
- [ ] 2026-11-19 · 網頁裡裝一個有面板的工具，面板讀得到資料 · 在新版 SYNOX 網頁裝一個有面板的工具（例如記帳 money），隨便記一筆，再從工具列表打開它的面板 · 面板顯示剛記的那筆；沒有 401、「讀不到」或空白
- [ ] 2026-11-19 · 改寫歷史後沒有人把舊歷史推回來 · 確認每個舊 clone（雲端 session、別台電腦、舊 worktree）都已刪掉重新 clone；`git ls-remote origin` 列出遠端所有分支與 tag，跟維護者私下保管的改寫前後 commit 對照表比對 · 遠端沒有任何分支或 tag 指向改寫前的 commit；之後幾天的推送也沒有舊 commit 回來
- [ ] 2026-11-23 · 設定頁的 AI 來源分步選擇（ADR 0046）· 裝 ntu_easy_llm 0.6 後開網頁「設定 → AI」：依序換「① 來源 → ② 認證 → ③ 服務」，各選一次本地內建、Claude Code、OpenAI（填假金鑰也行）、一個反灰的來源；本地內建按「列出模型」「看建議」；選 ntu_easy_llm 的本地來源（例如 Ollama）按「列出模型」；換回原本的來源按「存起來」 · 反灰的來源點不到、下面寫得出原因；本地內建的面板跟以前一樣；存起來之後對話照常；原本的 config.json 除了改的那一塊沒有被動到
- [ ] 2026-11-23 · 真的雲端金鑰來源走 ntu_easy_llm 0.6 的新 adapter · 用自己的 OpenAI／Anthropic／Gemini 金鑰（設定頁填）各聊一句、叫一個工具、故意填錯金鑰 · 回覆與工具照常；錯的金鑰顯示「金鑰不對或已失效」一句中文
- [ ] 2026-11-23 · LLOP 來源 · 在這台裝 `ntu_easy_llm[llop]`，照服務提供者給的指令在終端機註冊（SYNOX 裡不註冊），回設定頁按「重新整理」→ 選設定檔 →「列出模型」→「測一下」→ 聊一句 · LLOP 從反灰變成可用、看得到註冊好的設定檔、聊得通；服務提供者換連結時顯示「API 連結已更換」那句
- [ ] 2026-11-23 · 訂閱登入來源（Claude／GitHub Copilot／ChatGPT）· 裝好對應的登入套件、在終端機登入過，設定頁選它，聊一句並請 AI 用一個工具 · 標「只給本人使用」；回得出文字；要用工具時走文字協定（不會報「不支援工具呼叫」）
- [ ] 2026-11-23 · 備援真的換來源 · 設定頁「備援」加一個能用的來源，模式「自動換」；讓主要來源額度用完（或填一把會回 429 額度用完的假閘道）再聊一句；再改成「先問我」重做 · 自動換：回覆後另一則「⚠️ AI 來源的提醒：已改用 …（原因：額度用完）」；先問我：出「改用 X 重送」按鈕，按了那句用 X 重送；關掉備援之後恢復只用主要來源
- [ ] 2026-11-23 · 網頁一鍵更新（ADR 0047）· Windows、用 ZIP 裝的 SYNOX（不要用開發用的 git clone）：先照 docs/release-playbook.md「先測更新」用 `scripts/make_update_testkit.py` 做一組有簽章的測試包、設好 `SYNOX_UPDATE_API` 與 `SYNOX_UPDATE_TEST_PUBKEY` 再開 SYNOX；網頁「設定 → 💻 電腦與備份 → SYNOX 更新」按「檢查更新」→「更新到 X」→「開始更新」；測完把兩個環境變數刪掉 · 卡片先出現下載、簽章驗過的字；接著電腦上跳出「SYNOX Update」視窗、SYNOX 關掉又開回來（沒有多開一個瀏覽器分頁）、網頁自己重新整理並停在「電腦與備份」，卡片寫「✅ 上次更新：舊版 → X」；`config.json`、`data`、`packs` 沒被動；`_previous` 多一份舊版
- [ ] 2026-11-23 · 網頁「回到上一版」· 接著上一項，卡片按「回到上一版（…）」→ 確認 · 視窗跳出、SYNOX 關掉換回舊版再開、網頁自己重新整理；卡片寫「↩️ 上次退回到 …」；`synox about` 印的是舊版本
- [ ] 2026-11-23 · 沒有簽章的版本網頁不換 · 用沒有簽章的測試包（make_update_testkit 不給私鑰，或刪掉 release.json.sig）重做第一項 · 卡片沒有「更新到 X」，只有「打開更新視窗…」並寫「這一版沒有簽章」；什麼都沒有被換
- [ ] 2026-11-23 · 換版本後啟動時套件自動補齊 · 在 ZIP 裝的 SYNOX 的 `.venv` 裡先裝舊的 ntu_easy_llm（例如 0.5），確定設定頁說「這個來源要 ntu_easy_llm 0.6 以上」；關掉 SYNOX，點 Start.bat · 啟動視窗印「🔧 這版 SYNOX 要的套件跟裝著的不一樣，補裝：ntu_easy_llm 0.5.0 → 0.6.0a2…」再印「✅ 套件補好了」；設定頁那句提示不見；`data/deps.json` 記著 `llm`（裝過 `[llop]` 的也記著 `llop`）
- [ ] 2026-11-23 · 沒網路時套件補不成也照常啟動 · 跟上一項一樣先放舊版，拔掉網路再點 Start.bat；之後接回網路，到網頁卡片按「再試一次（補裝套件）」 · 沒網路時 SYNOX 照常開起來，視窗與卡片寫「ntu_easy_llm 沒有更新到 0.6.0a2（現在是 0.5.0）：連不到網路」與怎麼補；接回網路按「再試一次」後寫「✅ 套件補好了」並出現「重新啟動 SYNOX」，按了之後設定頁那句提示不見

## 測過了

（還沒有）
