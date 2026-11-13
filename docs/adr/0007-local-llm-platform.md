# ADR 0007：本地模型是 SYNOX 內建的 platform ability（llm.kind = "local"）

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/local_llm_platform`）
- 依據：維護者私有資料夾的「本地模型（Ollama）測試紀錄」與「VLM 設計」（2026-11-13）
- 網頁 API：[../runtime-api.md](../runtime-api.md) 的 `POST /api/settings/llm/local-advice`

## 擁有者的要求（精神）

1. 只要選「本地模型／Ollama server」，所有設定介面都要有 **context-size**，並給**建議選項**（不確定電腦撐不撐得住）。
2. 本地推論本來就慢：逾時預設改成 90 秒的 **5 倍（450 秒）**，而且**只要模型還在回應就不要砍**。
3. 本地模型屬於 SYNOX 內建的 platform ability（不像 claude_login／openai_login 另做套件，因為沒有登入要包）。
4. VLM 這一輪不做，但 adapter 不能擋住它。

## 決定

1. **新的 `llm.kind = "local"`**，adapter 在 `src/synox/llm/local.py`（`LocalAdapter`），只用標準函式庫 urllib、不走系統 proxy。
   欄位：`server`（`ollama` 預設｜`vllm`｜`lmstudio`｜`other`）、`base_url`（預設依 server，例如 `http://127.0.0.1:11434`；
   結尾的 `/v1` 會被拿掉）、`model`、`context_size`（0＝伺服器預設；合法 512～1048576）、`timeout`（無進展，0＝450）、
   `max_total_timeout`（1800）、`tools`、`max_tokens`。檢查在 `local.validate`，`config.py` 載入時就跑（寫錯＝ConfigError）。
2. **協定**：ollama 走原生 `POST /api/chat`（`stream: true`、`options.num_ctx`＝context_size、`think: false` 關掉推理輸出、
   `tools` 原生工具；伺服器不認得 think 就拿掉再試一次）；其他三種走 OpenAI 相容 `POST /v1/chat/completions`
   （SSE、`stream_options.include_usage`，tool_calls 的增量依 index 組回來）。其他三種的 context **客戶端設不了**：忽略，
   probe 說明要在伺服器那邊設（vLLM `--max-model-len`、LM Studio 載入時設）。
3. **逾時是「無進展」，不是總時限**：urllib 的 timeout 就是每次 socket 讀取的上限，所以只要模型還在吐字（每一行都是進展）就不會砍；
   第一個字出來之前也算（CPU 上長提示的 prefill 要很久，這就是 450 秒的理由）。另設很寬的總上限 `max_total_timeout`，
   在兩次讀取之間檢查（所以最多再多等一個無進展逾時）。錯誤訊息講清楚是「無進展」還是「總上限」。
4. **截斷不靜默**：Ollama 超過 num_ctx 會靜默丟掉最前面（系統提示先沒）。回報的 prompt token ≥ context 的 97%＝「很可能被截斷」；
   沒設 context_size 時讀 `/api/ps` 看實際的 context（剛 chat 完模型已載入；唯讀），讀不到就假設 4096 並寫明是假設。
   另外送出前用字元數 ÷ 2.5 估一次（回報的數字可能沒算快取的部分）。提醒進 `logging.warning`、`Reply.warnings`
   （AgentLoop 另送一則「⚠️ AI 來源的提醒」，不進對話記憶）、`adapter.last_warning`（網頁設定頁顯示）。
5. **probe／inspect 唯讀**：ollama 只打 `GET /api/tags`、`POST /api/show`（API 本身是 POST，但只讀模型中繼資料、不載入模型），
   其他打 `GET /v1/models`（LM Studio 另試 `/api/v0/models`）。**絕不送 chat／generate**。回報模型在不在、最大 context、
   設定合不合理（context 比模型上限大、沒設 context、`tools=true` 但模型沒有 tools 能力）。doctor、精靈與網頁的「測一下」都用它。
   代價：「測一下」通過不代表模型真的跑得動（記憶體不夠要等第一次對話才知道）——這台機器經不起每次測試都載入模型，這是刻意的。
6. **context-size 建議**（`src/synox/llm/local_advice.py`，純函式）：選項 4096／8192／16384／32768／65536／131072（不超過模型上限）。
   需要的記憶體 ≈ 權重（`/api/tags` 的 size）＋ KV cache（每 token：有注意力的各層 kv_heads 加總 ×（key_length＋value_length）× 2 bytes，
   取自 `/api/show` 的 model_info；缺資料用偏大的估計或靜態假設）＋ 執行時額外（0.6 GB＋權重 10%），對照 `GlobalMemoryStatusEx`
   的可用 RAM：≤ 60%＝建議、≤ 85%＝吃緊、其他＝可能撐不住。SYNOX 實際的提示（系統提示＋全部工具規格＋soul.md 上限，
   `AgentLoop.prompt_chars`）÷ 2.5 估 token，小於「提示＋回覆上限」的選項標「會截斷」。**推薦值是夠放提示＋對話紀錄＋回覆的最小那個**
   （CPU only、資源脆弱，偏保守）。全部明講「這是估算」。沒連上 Ollama 時退回靜態表（常見 7–9B Q4 的假設）並說明。
   介面：文字版 `synox init`（印表、預設填推薦值）、視窗精靈（「看建議」）、網頁設定頁（「看建議」，`POST /api/settings/llm/local-advice`，
   用 POST 是因為它會讓 SYNOX 去連使用者填的網址）、doctor（一行摘要）。
7. **openai_compat 也補上逾時**：factory 以前沒把 `llm.timeout` 傳給 `EasyLLMAdapter`。現在傳；沒寫時 `base_url` 指到 loopback／私網＝450，
   其他＝90（雲端行為不變）。
8. **網址**：loopback、私網（RFC 1918、link-local、沒有點的主機名、`.local`／`.lan`…）不提醒；公網位址或看不出來的主機名提醒一次
   （不擋，不查 DNS）。
9. **不擋 VLM**：訊息轉換集中在 `local.ollama_message`／`openai_message`；`Message` 之後加一個有預設值的圖片欄位，
   在這兩個函式各加幾行（Ollama 的 `images`、OpenAI 的 content parts）就好，不需要第二套流程。

## 為什麼不是另一個套件

claude_login／openai_login 包的是「別人的登入」（訂閱、token 檔），要隔離、要另外授權；本地模型沒有登入、沒有金鑰，
就是對這台或家裡網路的一個 HTTP 伺服器說話，屬於 SYNOX 自己的平台能力。只用標準函式庫，也不需要 ntu_easy_llm。

## 擋不住的、沒做的

- Ollama 回報的 `prompt_eval_count` 可能不含快取命中的部分：截斷判斷會漏報（所以多了送出前的估算），不會誤報成「沒事」以外的東西。
- 記憶體估算不含其他程式之後再吃掉的記憶體；模型已載入時可用 RAM 會少算（偏保守）。混合架構（線性注意力層）的狀態大小沒算，量級小。
- vLLM／LM Studio／其他伺服器沒有在真機測過（只有假 opener）；Ollama 只做了一次最小的冒煙測試。
- VLM、「宣稱完成但沒有對應工具呼叫」的檢查（測試紀錄建議 1）這一輪不做。
- 文字協定（`tools=false`）照舊一次只解析一個工具呼叫。
