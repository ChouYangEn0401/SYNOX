# 分支盤點（2026-11-19）

為了發一版乾淨的 alpha、把 `dev` 與 `main` 合好，盤點一次所有分支、worktree、stash：哪些已經在 `dev`、哪些要搬、哪些可以刪。

背景：2026-11-17 整理過一次歷史（改寫 commit 訊息與檔案內容、拿掉不該公開的內部文件）。改寫**前**留下來的本機分支跟現在的 `dev` **沒有共同祖先**，
所以 `git cherry` 看不出關係；這類分支改用「作者時間＋commit 標題」逐一對照 `dev`，再看改寫拿掉的檔案是不是都已經另外保存。

整理前先做了完整備份（`git bundle --all`，含 stash 與 tag），只留在本機，不推送。

## 分類

| 代號 | 意思 | 怎麼處理 |
|---|---|---|
| A | 已合併，或內容完整存在於 `dev`（含改寫後的版本） | 可刪 |
| B | 被 `-v2` 等後來的版本取代 | 可刪 |
| C | 有 `dev` 沒有、仍有價值的內容 | 搬進 `dev` |
| D | 不確定、要擁有者決定 | 列題目 |
| E | 別的 session 正在用（locked、不是這次開的 worktree、24 小時內有 commit） | 不碰 |

## 本機分支

| 分支 | 跟 `origin/dev` 的關係 | 內容 | 最後 commit | 版本號問題 | 分類 |
|---|---|---|---|---|---|
| `dev` | 等於 `origin/dev` | 主線 | 2026-11-19 | 見下面「版本號」 | — |
| `main` | 改寫前舊歷史，無共同祖先；每個 commit 在 `dev` 都有改寫後的對應 | 舊的 `main`（停在 0.2.1-alpha.1） | 2026-11-16 | 停在 alpha.1，比 `origin/main` 舊 | A（改成指向 `origin/main`） |
| `release/0.2.1` | 舊歷史，無共同祖先；`origin/release/0.2.1` 是它改寫後的版本 | 0.2.1-beta.2 發佈 commit | 2026-11-18 | — | A（改成指向 `origin/release/0.2.1`） |
| `backup/dev-before-rewrite-20261117` | 舊歷史，無共同祖先；每個 commit 在 `dev` 都有改寫後的對應 | 改寫前 `dev` 的備份 | 2026-11-17 | — | A（已在備份 bundle） |
| 本機限定分支 `…/dev-with-docs` | 舊歷史；33 個 commit 是內部規劃／研究文件 | 只在本機的內部文件版 `dev` | 2026-11-12 | — | A（文件已在私有文件庫，程式部分在 `dev`） |
| 本機限定分支 `…/pack-warnings-pre-rewrite` | 舊歷史；6 個 commit 是 pack 警告（ADR 0041）第一版 | pack.json 警告 | 2026-11-18 | — | B（`feat/pack-warnings-v2` 已合進 `dev`）；但 24 小時內有 commit、今天剛改過名，照規則先當 E 不刪，之後再刪 |
| `encrypted/plans-20261113` | 舊歷史；`origin/encrypted/plans-20261113` 是改寫後的版本，密文完全相同 | 加密的計畫封存 | 2026-11-13 | — | A（本機舊版；遠端那條保留） |
| `chore/versioning-rules` | 等於 `origin/dev` | 別的 session 剛開的版本號規則工作 | 2026-11-19 | — | E |
| `worktree-agent-aad04d716dfd1ced7` | 舊歷史 | locked 的 agent worktree | 2026-11-14 | — | E |
| `worktree-agent-aad73c03b5df55f60` | 舊歷史 | locked 的 agent worktree | 2026-11-10 | — | E |

## 遠端分支

| 分支 | 跟 `origin/dev` 的關係 | 內容 | 最後 commit | 分類 |
|---|---|---|---|---|
| `origin/main` | 是 `origin/dev` 的祖先（`dev` 領先 92 個 commit，`main` 沒有 `dev` 沒有的 commit） | 0.2.1-beta.1 | 2026-11-18 | 保留 |
| `origin/dev` | — | 主線 | 2026-11-19 | 保留 |
| `origin/release/0.2.1` | 領先 1（0.2.1-beta.2 發佈 commit，tag `v0.2.1-beta.2` 在這裡） | 0.2.1 發佈線 | 2026-11-18 | C（這次合進來；合進 `dev` 後變 A） |
| `origin/claude/lm-studio-e2e-encryption-ug09c3` | 已合併 | LM Studio、0.2.1-beta.1 | 2026-11-18 | A |
| `origin/feat/completion_guard` | 已合併 | ADR 0008–0012 等 | 2026-11-13 | A |
| `origin/feat/local_llm_platform` | 已合併 | 本機模型平台 | 2026-11-13 | A |
| `origin/feat/screen_protect_awaker` | 已合併 | 保持喚醒 | 2026-11-13 | A |
| `origin/feat/setup-tutorials-and-landing` | 已合併 | 教學與首頁 | 2026-11-12 | A |
| `origin/feat/small_model_harness` | 已合併 | 小模型 harness | 2026-11-13 | A |
| `origin/feat/ui-redesign` | 已合併 | 介面改版 | 2026-11-12 | A |
| `origin/feat/vlm_vision` | 已合併 | 看圖 | 2026-11-13 | A |
| `origin/encrypted/plans-20261113` | 領先 1（只有加密檔） | 加密的計畫封存 | 2026-11-13 | D（要不要留由擁有者決定） |
| `origin/claude/charming-einstein-41ih1s` | 領先 2，`dev` 都沒有 | 主控台／工作機連線（SYNOX Link，實驗中，含網路傳輸） | 2026-11-12 | D（文件已寫「在另一個分支、還沒合進 dev」） |

## Worktree

| 位置 | 分支 | 狀態 | 分類 |
|---|---|---|---|
| 主 checkout | `dev` | 別的 session 可能在用 | E |
| `.claude/worktrees/agent-aad04d716dfd1ced7` | `worktree-agent-aad04d716dfd1ced7` | locked（agent 程序還在） | E |
| `.claude/worktrees/agent-aad73c03b5df55f60` | `worktree-agent-aad73c03b5df55f60` | locked（agent 程序還在） | E |
| `SYNOX-wt/versioning`、`SYNOX-wt/versioning-base` | `chore/versioning-rules`／detached | 別的 session 今天開的 | E |
| `SYNOX-wt/data-migrations` | `feat/data-migrations` | 別的 session 今天開的（盤點途中出現） | E |
| `SYNOX-wt/consolidate-branches`、`SYNOX-wt/consolidate-base` | 這次整理用 | 驗收後收掉 | — |

## Stash

| stash | 內容 | 跟 `dev` 的關係 | 分類 |
|---|---|---|---|
| `stash@{0}`（2026-11-16） | 誤改在主 checkout 的提醒回覆字樣與 `clock()` | 改寫前的基底；`dev` 已有 `clock()` 與新的回覆字樣（更完整的版本） | A（已在備份 bundle） |

## 改寫前分支「內容都還在」的證明方式

1. **commit**：每個舊分支的 commit，用「作者時間＋標題」在 `dev`（或 `origin/release/0.2.1`）找對應。找不到的只有改寫時改過標題的 8 個，
   用作者時間各自找到改寫後的 commit。
2. **檔案**：舊分支 tip 與對應的改寫後 commit 比較，舊分支多出的檔案（內部規劃頁面、研究、交接、收件單）逐一用 blob hash 在私有文件庫找到，內容相同。
3. **備份**：整理前 `git bundle --all` 已驗證（`git bundle verify` 通過），含全部本機分支、遠端追蹤分支、stash、tag。

## 版本號

- `dev` 現在是 `0.2.2-alpha.1`；CHANGELOG 開頭寫明為什麼不是 `0.2.1-alpha.N`（`0.2.1-beta.*` 發過了，alpha 不能往回排）。順序正確。
- 缺的：`dev` 的 CHANGELOG 沒有 `0.2.1-beta.2` 那一節，tag `v0.2.1-beta.2` 也不在 `dev` 上。這次把 `release/0.2.1` 合進來補上（版本號與安裝檔指紋保留 `dev` 的）。
- 沒改、留給版本號規則那條工作線：`docs/versioning.md`、`docs/release-playbook.md` 還寫「下一版是 `0.2.1-beta.1`」「現在是 `0.2.0`」，已經過時。
