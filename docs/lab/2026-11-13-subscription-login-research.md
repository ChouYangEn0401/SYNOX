# 用「訂閱登入」取代 API 金鑰：各家調查與 `ntu_easy_llm` 結構確認

- 日期：2026-11-13
- 來源：兩個研究子代理（只讀網頁）；我自己重新抓了 OpenAI 的 `codex exec` 文件確認旗標。**子代理的結論是它們的說法，不是我逐條驗證過的**；標 [記憶] 的是它沒讀到頁面、憑記憶寫的。
- 擁有者的前提：Claude 那個套件（驅動官方 `claude -p`）是因為 Anthropic 官方文件允許才做。同樣標準套到別家：**只做「官方文件允許」的路，不抽 token。**

## 一、結論

| 廠商 | 官方訂閱登入 CLI | 無人值守模式 | 條款判斷 | 建議 |
|---|---|---|---|---|
| **OpenAI**（ChatGPT 方案） | `codex`（Sign in with ChatGPT） | `codex exec --json`、SDK、app-server | **允許**（官方文件把 `codex exec`、SDK 列為可用方案額度的方式）；抽 `auth.json` token 自己打後端＝**未明文、風險高** | **已做：`openai_login`**（驅動官方 binary，不讀 auth.json） |
| **GitHub Copilot** | `copilot`、官方 SDK | `copilot -p`、SDK（2026-06 GA [2nd]） | **允許**（唯一明講可嵌進自己 app）；一般 AUP 禁「過量自動化」 | 值得做 `copilot_login`（下一個） |
| **Kimi** | `kimi login`（device code） | `kimi -p`、`stream-json` | **灰色**：編碼場景可用、不得改 User-Agent；「自己的產品」請用 Open Platform | 可做，預設關＋警語；或走 `openai_compat` |
| **xAI Grok** | `grok login`（SuperGrok／X Premium+） | `grok -p`、json | **未知**（條款頁 403）；有 403 擋名單的回報 [2nd] | 先 `openai_compat`（`api.x.ai/v1`），不做 wrapper |
| **Gemini CLI** | 有 | 有 | **明文禁止**第三方軟體用其 OAuth | 不做；用 AI Studio／Vertex API key |
| **Qwen Code** | 免費 OAuth 已於 2026-04-15 停 | — | — | `openai_compat` + API key |
| **DeepSeek** | 沒有訂閱制、沒有官方 CLI | — | — | `openai_compat`（`api.deepseek.com`，支援 tool calls） |

優先序（大架構優先）：OpenAI（做完）→ Copilot → Kimi（可選）。其他一律 `openai_compat`，SYNOX 現成的 `llm.kind` 就夠，不用新套件。

## 二、OpenAI 重點（官方 learn.chatgpt.com/docs，原 developers.openai.com/codex 轉址）

- Auth 頁：兩種登入——Sign in with ChatGPT（訂閱）、API key（用量計費）。「API keys are still the recommended default for automation」。憑證在 `~/.codex/auth.json`，文件說「Treat it like a password」。
- Pricing 頁：「Codex SDK, `codex exec`, and scriptable workflows」可用方案額度。
- CI/CD 頁：自動化「the right way」是 API key；ChatGPT 帳號做自動化是「advanced workflow for … trusted private automation」，不要多個工作共用同一份 auth 檔。
- 額度：Plus 約每 5 小時 15–160 則（依模型），有週上限；Pro 無 5 小時上限（子代理轉述，我沒獨立核對數字）。
- 官方嵌入路：**Sign in with ChatGPT** 為開源／本機 app 登記自己的 client 取得方案額度（preview，`stream` 必須 true、`store` 必須 false）；**Codex app-server**（stdio JSON）。
- 我確認的 `codex exec`：`--json`（JSONL：`thread.started`、`item.completed`＋`agent_message`、`turn.completed.usage`、`turn.failed`、`error`）、`--sandbox read-only`（預設）、`--skip-git-repo-check`、`--ephemeral`、`--ignore-rules`、`--ignore-user-config`、`-` 從 stdin 讀 prompt。**`-m` 與離開碼那頁沒寫**。
- 條款全文（openai.com/policies）子代理 403，是憑記憶：禁止「自動／程式化擷取資料」、「規避速率限制或保護措施」、逆向、分享帳號憑證。**要在發佈前請擁有者自己讀一次。**
- 執法：沒找到 OpenAI 因此停帳號的回報（搜尋結果裡的封號報導是 Anthropic 的）。這是缺少證據，不是保證。

### `openai_login`（`<HOME>\openai_login`，本機 git，無 origin）
- 驅動 `codex exec --json … -`（prompt 走 stdin）、唯讀沙盒、空的暫存工作資料夾、`--ephemeral`；解析 JSONL；不碰 auth.json。8 個測試過（假 runner）。
- **沒在真的 codex 上跑過**（這台沒裝）。第一次用前要實測一次。
- 跟 Claude 套件的差異要誠實：`claude --tools ""` 能保證「只回文字」；**codex 沒有等價旗標**，只能降低風險。接進 SYNOX 前，擁有者要決定能不能接受（SYNOX invariant 2「adapter 只會聊天」會變弱）。

## 三、「ntu_easy_llm 結構受不受得了這種強度」——能確認與不能確認的

**不能確認**：這台沒有 `ntu_easy_llm`（`Downloads` 只有 `ntu_easy_llm-0.1.3.rar`，檔名有 `withKey`，**我沒有打開**，避免碰到金鑰；版本也低於 SYNOX 要求的 0.5.0），所以套件內部（重試、連線池、串流、`arguments` 不是字串時的處理）我看不到。

**能確認的（從 SYNOX 這端與實測）**：
1. 介面夠窄：`agent.chat(provider, model, neutral_messages, tools, api_key, base_url, max_tokens, timeout, session)` → `reply(text, tool_calls, usage)` + 三種例外。SYNOX 只靠這個，換掉套件只要重寫 `llm/easy_llm.py` 一個檔（約 120 行）。你說的「規定好 input／output 就沒問題」在 SYNOX 這邊成立。
2. 這個強度對 SYNOX 的呼叫量並不高：對話一輪最多 `max_steps=6` 次呼叫；心跳每 45 分鐘、一天最多 40 次。實測一題 2～3 次呼叫。**瓶頸不在套件結構，在逾時**：`EasyLLMAdapter.timeout=90` 寫死；本地 CPU 上 27B 有 3/8 次單次呼叫超過 90 秒（見本地模型測試紀錄）。
3. 套件沒有對「模型偽造工具分隔符／工具結果」做任何事（這是 SYNOX loop 的責任）。
4. `session` 參數可注入，所以測試能不連網；可以拿來寫一支對真 Ollama 的整合測試，不用動套件。

**建議**：(a) `llm.timeout` 做成設定；(b) 擁有者在有套件的機器上跑一次 `ChatAdapter.probe`（對 Ollama、對雲端各一次）；(c) 若要讓 `ntu_easy_llm` 收圖片（VLM 設計），先確認它的 neutral message 能不能帶 content parts。

## 四、沒做／沒驗證
- 沒寫 `copilot_login`、`kimi_login`（優先序在上表；等擁有者拍板）。
- 沒把 `openai_login` 接進 SYNOX（沒新增 `llm.kind`）；SYNOX 沒有改動。
- 沒實測任何訂閱登入（這台沒有 codex／copilot／kimi／grok）。
- Kimi 的「automated／derivative products」條款原文沒讀到；xAI 條款頁 403；OpenAI 政策頁 403。
