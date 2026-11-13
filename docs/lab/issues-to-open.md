# 待開的 issue（貼上即可）

這幾項都是「寫完了、測試過，但沒有在真實環境驗證」。歡迎有環境的人幫忙測。

---

## 1. ChatGPTLogin — 需要在真的 `codex` 上驗證
倉庫：https://github.com/ChouYangEn0401/ChatGPTLogin
標題：`Needs verification against a real codex CLI (never run on one)`

內容：
目前 8 個測試全部用假的 runner，**從未在真的 `codex` 上跑過**。需要有 ChatGPT 訂閱並已安裝、登入 `codex` 的人驗證：
- [ ] `ask("請只回一個字：好")` 能回文字
- [ ] `codex exec --json --sandbox read-only --skip-git-repo-check --ephemeral --ignore-rules -` 由 stdin 讀 prompt 是否可行；`-m <model>` 是否被接受
- [ ] JSONL 事件格式（`item.completed`／`agent_message`、`turn.completed.usage`、`turn.failed`、`error`）是否與 `parse_events` 假設一致
- [ ] 未登入、額度用完、逾時時的錯誤訊息
- [ ] Windows（`codex.cmd`）與 macOS／Linux 的找法
- [ ] codex 沒有「完全不給工具」旗標：確認 `--sandbox read-only` 下不會執行指令或改檔
另外：OpenAI 的使用條款作者沒能讀到全文（政策頁 403），發佈前請自行確認可以這樣用。

---

## 2. GithubCopilotLogin — 需要在真的 `copilot` 上驗證
倉庫：https://github.com/ChouYangEn0401/GithubCopilotLogin
標題：`Needs verification against a real GitHub Copilot CLI (never run on one)`

內容：
5 個測試全用假 runner，**從未在真的 `copilot` 上跑過**。需要有 GitHub Copilot 訂閱並已安裝、登入 CLI 的人驗證：
- [ ] `copilot -p "<prompt>" -s --no-ask-user` 在無人值守下能回乾淨文字
- [ ] 不給任何 `--allow-*` 時，需要權限的動作是否真的被拒絕（目前只是照文件推論）
- [ ] `--model` 可用的名稱
- [ ] 沒有 JSON／用量輸出，`Reply.usage` 永遠為空，是否有新版本提供
- [ ] prompt 上限（目前保守設 30000 字，因為 `-p` 走命令列）
- [ ] 未登入／額度用完的錯誤訊息
- [ ] Windows `copilot.cmd` 的找法

---

## 3. SYNOX — 本地模型新 harness 需要真實模型驗證
倉庫：https://github.com/ChouYangEn0401/SYNOX
標題：`Local-model harness (completion guard, tool cap, context budget, vision) is tested only with fakes`

內容：
以下功能的 2305 個測試全部使用假 adapter／假 opener／已存回覆，**沒有用真實模型驗證品質是否變好**（ADR 0007–0021）：
- [ ] 虛假完成閘門（`llm.completion_guard`）：誤判率標定只有 0/97 的樣本，無法證明 ≤2%；詞表已知漏洞（「我再幫你…」會被誤判，見 ADR 0020）。需要帶著閘門重跑 `--repeat N` 並人工複核每次觸發
- [ ] 每輪工具上限（`llm.max_tools`）、context 預算（`llm.context_size`）、本輪規則重注入（`llm.prompt_tail`）是否讓小模型變好
- [ ] `llm.kind="local"` 對 vLLM／LM Studio（只對假伺服器測過）
- [ ] VLM（`llm.vision`，ADR 0021）：Ollama 原生 `images`、OpenAI 相容 data URI、Anthropic、Gemini 格式都沒在真的 VLM 上測過；Pillow 縮圖路徑沒測
- [ ] 依賴 `ntu_easy_llm` 0.5.0「原封不動傳遞 content」的行為來送圖，套件改版可能壞

---

## 4. SYNOX — keep-awake 在實機的行為需要驗證
倉庫：https://github.com/ChouYangEn0401/SYNOX
標題：`keep-awake: idle screen-off timer and Modern Standby behaviour not verified on real hardware`

內容：
`runtime.keep_awake`（ADR 0006）：
- [ ] 「閒置 N 分鐘後主動關螢幕」沒在真螢幕上實測
- [ ] 現代待命（S0）機型：插電時請求可擋閒置睡眠、用電池時 5 分鐘後被取消，是依 Microsoft 文件推論，沒有實機驗證
- [ ] 排查步驟見 `docs/keep-awake-troubleshooting.md`（`powercfg /requests`、`/sleepstudy`）

---

## 5. SYNOX — 主機台的登入只靠 cookie：同一台電腦上別的程式聽任何一個本機埠就收得到
倉庫：https://github.com/ChouYangEn0401/SYNOX
標題：`web: console login cookie is sent to any 127.0.0.1 port (cookies ignore ports)`

內容：
瀏覽器的 cookie 只看主機、不看埠。同一台電腦上的另一個 Windows 帳號或程式去聽 `127.0.0.1` 的任何一個埠，再讓擁有者的瀏覽器連過去一次
（一個連結就夠），就收得到主機台的 `synox_session` cookie。這是主機台原本就有的問題，不是工具服務帶來的（ADR 0023 第三版「擋不住的」第 2 點）；
工具服務第三版的做法是 app 改綁 `127.0.0.2`、app 的埠完全不用 cookie，不讓 app 的網址變成誘餌。
- [ ] 想一個不只靠 cookie 的登入（例如每個請求另外帶分頁裡的 token）
- [ ] 在那之前，共用電腦的人要知道這件事（docs/security.md「沒有做的保護」已寫）
