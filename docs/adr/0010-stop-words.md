# ADR 0010：停止詞（讓模型寫不出假的工具結果）

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/completion_guard`）
- 依據：研究交接書前 8 項的第 4 項（卡片 B6；Qwen-Agent 把 `✿RESULT✿`、`Observation:` 設成 stop）
- 程式：`src/synox/llm/base.py`（`supports_stop`、`chat(..., *, stop=())`）、`src/synox/llm/local.py`、`src/synox/agent/loop.py`

## 決定

1. `ChatAdapter.chat(messages, tools=(), *, stop=())`，另加類別屬性 `supports_stop`（預設 False）。**迴圈只對 `supports_stop=True` 的 adapter 傳 stop**，
   所以舊的、測試寫的 adapter（`chat(messages, tools)`）不受影響。
2. 送什麼：文字協定 `("〔工具結果〕",)`；原生 `("<tool_response>",)`。`llm.think` 是 true 時不送（Qwen 文件：思考段可能含停止詞）。
3. 誰支援：`LocalAdapter`（ollama＝`options.stop`；vLLM／LM Studio／其他＝`body.stop`，最多 4 個）、`FakeAdapter`（記在 `stops`）。
   **ntu_easy_llm 0.5.0 的 `agent.chat` 沒有 stop 參數**（2026-11-13 看過簽名：只有 `extra_body`，規格說不支援就略過），
   所以 `EasyLLMAdapter.supports_stop=False`；`claude_code` 也沒有。doctor 那一行寫「此來源不支援停止詞（不送）」。

## 跟規格不一樣的地方（照實說）

規格寫的是文字協定 `["〔工具結果〕", "⟦SYNOX-TOOL"]`、原生 `["<tool_response>", "⟦SYNOX-TOOL"]`。**`⟦SYNOX-TOOL` 沒有放**：
真實的 qwen3.5:9b 文字協定回覆（`tools/local-llm-live/results/9b-text.json`）9 則裡有 2 則用分隔符**包住自己的工具呼叫**
（`⟦SYNOX-TOOL-…⟧ {"tool": "mail__read", …}`）——停在 `⟦SYNOX-TOOL` 會把整則截成空白，這兩題本來是過的（解析器找得到裡面的 JSON），
加了就會壞。模型把分隔符印出來時，ADR 0008 的 `forged` 仍然會攔（重試），所以拿掉這個停止詞不會少擋偽造，只是少截一刀。

## 擋不住的

- 停止詞是字面比對：模型寫「[工具結果]」之類的變體不會被截（閘門的 forged 也只認系統真的用的標記）。
- 不支援停止詞的來源（ntu_easy_llm、Claude Code）只能靠閘門。
