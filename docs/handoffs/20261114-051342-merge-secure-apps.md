# 把「工具網頁服務＋手機驗證器＋手機入口」合進主線

- **狀態**：待處理
- **擁有者原話**：「我會希望未來從 Synox 的主機台，我可以開一個新的服務，然後這個服務就會去開 port 幫我把這個軟體把它架上去……不用的時候可以關掉，不會有資安的風險。」「如果需要的話，你就在 Dev 上面開一個新的分支……到時候我們再 merge 就可以了。」

## 問題一句話
功能做完、測過、審過了，在分支上等你點頭合進 SYNOX 的 `dev` 與 SYNOX_Libs 的 `main`。

## 脈絡
- SYNOX：分支 `feat/secure-apps`（從 `origin/dev` 的 `6b4253c` 開出），15 段開發＋1 輪安全修正，每段都是 `--no-ff` 合進來的。測試 3045 過、16 跳過（開發前是 2545 過）。
- SYNOX_Libs：分支 `feat/tool-apps`，記帳 0.3.1（記帳網頁、`/money_edit`、CSV 匯出、可以在手機上用）。測試 312 過，`build.py --check` 與 `public_check.py` 都乾淨。
- 設計：`docs/adr/0024`（工具網頁）、`0025`（門禁核心＋手機驗證器）、`0026`（手機入口）；計畫與「實作偏差」表在 `docs/lab/2026-11-14-stepup-remote-plan.md`。
- 這台電腦上沒開過任何埠、沒跑過 cloudflared；所有網路行為都只用假的測。
- 本機的 `dev` 落後 `origin/dev` 很多，而且可能有別的 session 在用，所以沒在今晚合。

## 選項
| 選項 | 一句話 | |
|---|---|---|
| A | 先在別台電腦做完「G1／手機入口實測」那一張，過了再合 | **建議** |
| B | 現在就合進 `dev`／`main`，實測之後再修 | |
| C | 先只合 SYNOX_Libs 的記帳（舊版 SYNOX 會被 SDK 範圍擋住，不會壞） | |

## 驗收
- `git merge --no-ff feat/secure-apps` 進 `dev`（訊息寫做了什麼、為什麼），合完全套測試照樣過。
- Libs 的 `feat/tool-apps` 同樣 `--no-ff` 進 `main`。
- 合完把 `C:\…\SYNOX-wt\secure-apps`、`C:\…\SYNOX_Libs-wt\tool-apps` 兩個 worktree 收掉（如果還在）。

## 不要做的事
- 不要 fast-forward；不要 push 前沒跑測試；不要在這台電腦為了「試試看」把服務真的開起來。
