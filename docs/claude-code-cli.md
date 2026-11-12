# Claude Code 命令列版（`claude`）：SYNOX 怎麼找它、為什麼「VS Code 能用」不算數

給維護者與技術交接人員。使用者看到的只有設定頁／安裝精靈上的一句話和一行安裝指令，不用讀這份。

## 一句話

SYNOX 的「預設 AI 來源」（`kind: claude_code`）是**叫一個叫 `claude` 的執行檔**（`claude -p --output-format json`，
見 `src/synox/llm/claude_code.py`）。它必須是 **Claude Code 命令列版**。下面這些都**不是**，也都**不能**讓 SYNOX 的測試過：

| 看起來像，但不是 | 為什麼 |
|---|---|
| Claude Desktop（Windows 的 Store/MSIX 版、Mac 的 .app） | 圖形介面的聊天 App，不提供 `claude` 指令。 |
| VS Code 的 Claude Code 擴充功能 | 擴充功能自帶一份 `claude.exe`（`%USERPROFILE%\.vscode\extensions\anthropic.claude-code-<版本>-<平台>\resources\native-binary\`），**只給擴充功能自己用**，不在 PATH 上、路徑還帶版本號。 |
| `~/.claude/.credentials.json` 存在 | 那只表示「登入過」。登入資料是各種 Claude Code 共用的，裝好命令列版之後不用再登入；但單有登入檔不會多出 `claude` 指令。 |

所以「我在 VS Code 裡能用 Claude，SYNOX 卻說找不到 claude」是正常的、不是 bug：兩個是不同的程式，只是共用登入。
（2026-11-12 真機遇到的就是這個，加上下一節的 PATH 問題。）

## 找的順序（`find_claude()`）

1. `shutil.which("claude")`（PATH）。
2. 官方原生安裝程式的固定位置：`~/.local/bin/claude.exe`、`~/.local/bin/claude`。

第 2 步是 2026-11-12 加的。原因：原生安裝程式把檔案放在 `~/.local/bin`，但**不保證替使用者加進 PATH**
（真機：裝完 `claude --version` 仍是「無法辨識」，使用者 PATH 裡沒有 `~\.local\bin`）；而且程式是在安裝**前**啟動的話，
它看到的 PATH 也是舊的（Windows 的 PATH 只有新開的程序才更新）。只看 PATH 會誤報「找不到」。

**刻意不做的**：不去撿 VS Code 擴充功能那份 `claude.exe`。路徑隨擴充功能版本變、使用者升級或移除擴充功能就壞，
而且那份的用途與更新節奏不歸我們管。要用就請使用者裝命令列版。

## 沒找到時，使用者看到什麼

- **安裝精靈**（`wizard/pages.py`）：狀態一行＋「打開下載網頁」＋「重新偵測」。網址是 `wizard/logic.py` 的 `CLAUDE_DOWNLOAD_URL`。
- **網頁設定頁**（`web/static/app.html`、`web/server.py` 的 `test_llm`）：「測一下」若回「找不到 claude」，
  伺服器多回 `download_url`，頁面顯示一塊安裝說明：Windows（PowerShell）與 Linux／macOS 各一行、各一顆「複製」，加官方說明連結。
  只有**這個來源＋這句「找不到」**才會帶 `download_url`；其他錯誤（沒登入、逾時）不會。

指令（寫死在 `app.html`，不是從伺服器來的）：

```
Windows（PowerShell）：  irm https://claude.ai/install.ps1 | iex
Linux／macOS：           curl -fsSL https://claude.ai/install.sh | bash
```

### 為什麼只給「複製」、不做「一鍵幫你裝」

「一鍵」＝ SYNOX 的伺服器替使用者執行一段從網路抓來的腳本。那會讓網頁設定頁（擁有者登入後的 session）
變成「能在這台電腦上執行遠端程式碼」的入口，跟 `docs/security.md` 的方向相反；使用者自己貼到終端機執行，他看得到、也決定得了。
如果之後真要做，至少要：只限本機擁有者、每次都要使用者明確按確認、顯示完整指令、不接受任何參數，並寫進 `docs/security.md`。

### 為什麼連結不是 `claude.com/product/claude-code`

那是行銷頁，會把人帶去下載 Claude Desktop。`CLAUDE_DOWNLOAD_URL` 現在是官方安裝說明頁
`https://code.claude.com/docs/en/setup`（上面兩行指令的出處）。改它時要確認它講的是 `claude` 命令列版，不是桌面版。

## 驗證

- 單元測試：`tests/test_llm.py::test_find_claude_falls_back_to_native_install_dir`（PATH 沒有、`~/.local/bin` 有）、
  `tests/test_web.py::test_llm_test_gives_download_url_when_claude_missing`、`tests/test_wizard.py::test_claude_download_url_is_https`。
- 真機：`where claude`（Windows）／`which claude`；沒有的話看 `%USERPROFILE%\.local\bin\claude.exe` 在不在。
  `claude --version` 要印出版本；`claude` 能進去對話才表示登入好了。
- 預覽（`docs/ui/preview*.html`）改了 `app.html` 要重跑 `scripts/make_ui_preview.py`，`tests/test_ui_preview.py` 會檢查有沒有同步。

## 還沒弄清楚的

- 這個 venv 裡有 `claude-subscription 0.1.0`；repo 的程式碼裡沒有用到它，也搜不到 `claude-code-login` 這個名字。
  使用者以為「有這個套件就夠了」——**沒有任何一個 Python 套件會讓 SYNOX 的 `claude_code` 來源生效**，來源只認 `claude` 執行檔。
  這個套件從哪來、做什麼，沒人查過；要不要留，等擁有者決定。
- 全部測試跑起來有 5 個 `tests/test_llm.py` 失敗，原因是這個 venv 沒有 `ntu_easy_llm` 模組（`src/synox/llm/easy_llm.py:41`），
  跟 `claude` 偵測無關、在這次改動之前就是這樣。
