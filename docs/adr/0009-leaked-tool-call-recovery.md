# ADR 0009：救回文字裡洩漏的工具呼叫、剝除思考段

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/completion_guard`）
- 依據：研究交接書前 8 項的第 3 項（卡片 B1、B2）；Ollama issues #14745、#14493（Qwen3.5 的 XML 呼叫格式對不上 Hermes 解析器，
  呼叫被當成文字印出）
- 程式：`src/synox/llm/textproto.py`（`strip_think`、`parse_leaked`、`LEAK_MARKERS`）、`src/synox/agent/loop.py`

## 決定

1. **`textproto.strip_think(text) -> (clean, thought)`**：去掉 `<think>…</think>`；只有結尾 `</think>`（模板把 `<think>` 放在提示裡）＝前面整段是思考；
   只有開頭沒有結尾（思考到一半被切掉）＝後面整段是思考。**所有解析只在 clean 上做**（Qwen-Agent：不解析思考段裡的 tool_call）。
   `LocalAdapter`、`EasyLLMAdapter` 回的 `Reply.text` 先過它；迴圈對每個 adapter 再過一次（思考段不給人看、不進對話）。
2. **`textproto.parse_leaked(text) -> (calls, rest)`** 依序認：(a) `<tool_call>…</tool_call>` 裡的 JSON（標準解析 → 寬鬆修復：去尾逗號、
   單引號換雙引號、補 `}` → 字串搜尋 `"name"`／`"arguments"`；未閉合也試；裡面是 Qwen XML 也收）；(b) Qwen3-Coder／Qwen3.5 的
   `<function=名><parameter=k>v</parameter></function>`；(c) MiniMax 的 `<invoke name="…"><parameter name="k">v</parameter></invoke>`
   （可包在 `<minimax:tool_call>` 裡）；(d) 都沒有才用既有的 `parse()`（裸 JSON）。一次最多 3 個，第 4 個起丟掉；id 是 `leak-{i}`。
   XML 的值一律字串（看起來是 JSON 物件／陣列才解開，給 schema 模式的工具）。
3. **迴圈**：這一步沒有原生的 `tool_calls`、文字裡有 `LEAK_MARKERS` 任一 → `parse_leaked`，log `[AGENT] recovered N tool call(s) from text`。
   救回的呼叫照原生路徑寫進對話（assistant 的 `tool_calls`＋`role=tool` 的結果），**照常過 `ai_decision`、第 4 關、確認卡**——
   它們就是一般的 `ToolCall`，走同一個 `call_tool`，沒有任何捷徑。有標記但一個都解不出來 → 交給 ADR 0008 的 `forged` 重試。
4. **文字協定也用**（規格只寫原生）：`parse()` 找不到 JSON、文字裡又有標記時也救，但只取第一個（文字協定一次一個呼叫）。
   這只會讓更多正確的呼叫被執行，而且一樣過每一關。

## 不變式

**adapter 只回文字、決策在 harness**（AGENT.md invariant 2）：`textproto` 只把文字變成 `ToolCall`，不碰 registry；
能不能執行一律由迴圈的 `ai_decision`＋第 4 關＋確認卡決定。測試 `tests/test_agent_leak.py` 驗：ai=False 的節點被擋、
參數不對被第 4 關擋、危險工具仍出確認卡。

## 擋不住的

- 模型把呼叫寫成這四種以外的格式（例如自創的 `<tool>`）：不救，交給閘門當偽造或一般文字。
- 寬鬆修復可能把錯的參數交給第 4 關；第 4 關會擋，結果是「參數不對」回饋，不是誤執行。
