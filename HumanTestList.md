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

## 測過了

（還沒有）
