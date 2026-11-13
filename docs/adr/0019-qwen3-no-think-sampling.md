# ADR 0019：Qwen3 不思考模式的取樣參數（只有 kind=local 的 Ollama）

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/small_model_harness`）
- 依據：研究交接書前 8 項的第 7 項（卡片 G2、A5）
- 程式：`src/synox/llm/local.py`（`QWEN3_NO_THINK`、`sampling_options`、`parse_sampling`、`parse_options`）、`src/synox/llm/factory.py`

## 決定

1. `llm.sampling`＝`auto`（預設：模型名有 `qwen3` 才送）｜`qwen3`｜`off`。送的是 Qwen3 模型卡的不思考模式建議值
   `temperature 0.7、top_p 0.8、top_k 20、min_p 0`（不要 greedy，會無限重複）。
2. `llm.options`：自己蓋過的 Ollama options（數字、布林、短字串，最多 20 個）；`num_ctx`／`num_predict`／`stop` 不收
   （由 context_size、max_tokens、停止詞管）。
3. **只有 server=ollama 的 `/api/chat` 會送**；vLLM／LM Studio／其他（OpenAI 相容）照舊不加任何取樣參數。雲端來源、
   claude_code 不受影響。`think: false` 與舊版 Ollama 的退回（ADR 0007）不變。
4. 網頁設定頁換來源時保留 sampling／options（`KEEP_LLM_KEYS`）。

## 擋不住的

- MiniMax／DeepSeek 家族要保留思考段，目前不支援；用 Ollama 只保證 Qwen 系列測過。
