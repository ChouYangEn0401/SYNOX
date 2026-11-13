# 小模型 Harness 技術：中國團隊論文與開源框架（不需訓練的部分）— 摘要

- 日期：2026-11-13　完整版：[2026-11-13-cn-harness-techniques.html](2026-11-13-cn-harness-techniques.html)（31 張卡片、前 8 項規格、沒讀到的清單）
- 範圍：推論端／harness 端；排除微調、RL、蒸餾。目標是 SYNOX 接本地 9B（Ollama、CPU）。
- 閱讀方式：網頁與論文由四個研究子代理用 WebFetch 實際讀取並回報引文；主筆讀 SYNOX 原始碼與四份報告。關鍵數字動工前請點出處核對。

## 診斷：「沒叫工具卻說做完了」是三層疊在一起

1. **解析器層**：Qwen3.5 在 Ollama 有已知的工具呼叫格式錯配（issues #14745、#14493；PR #15022／#15224 修了一部分），症狀就是把 `<tool_call>` 印成文字。先看 `/api/chat` 原始回應。
2. **模型層**：文獻叫「執行幻覺」（2509.18970）、「工具繞過」（2601.05214）、「向上欺騙」（2512.04864）、「Halluci-action」（最高 45.9%）。Qwen3-8B 開 thinking 時干擾工具幻覺 36.2%→56.8%（2510.22977）；系統提示禁止只有邊際效果，所以要 harness 閘門。
3. **Context 層**：Ollama 預設 4096；`/v1` 不能設 `num_ctx`（官方文件）；截斷時伺服器只記 WARN、客戶端 HTTP 200（#10368）。要走 `/api/chat` 帶 `options.num_ctx`，用 `prompt_eval_count` 偵測截斷。

## 前 8 項（規格在 HTML）

1. **虛假完成檢測**：`agent/claims.py`（宣稱詞表＋否定／問句排除＋證據帳本）；`loop._turn` 的 `if not calls` 分支；重試 ≤2（`llm.verify_retries`）、中性修正字句、用完就老實回報；`evals/checks.py` 加 `claimed_without_call`；note-01 改 `any_of`。文獻沒有規則式偵測器的誤判率，要自己標定（目標 FP ≤ 2%）。
2. **Ollama 原生 adapter** `llm/ollama.py`：`num_ctx`、`think:false`、`stop`、`options`、`timeout` 300、暖機 runtime 任務、`prompt_eval_count` 截斷偵測、doctor 只讀探測。
3. **文字裡洩漏的工具呼叫救回**：`textproto.strip_think`、`parse_leaked`（`<tool_call>` JSON、Qwen XML `<function=>`、MiniMax `<invoke>`），救回的呼叫照常過 `ai_decision`＋第 4 關。
4. **停止詞、`system__cannot_do` 出口、重複失敗偵測、步數用完總結**：`stop=["〔工具結果〕","⟦SYNOX-TOOL"]`；連續同呼叫失敗 2 次提示、3 次停。
5. **工具說明精簡化（EasyTool）＋每輪工具數上限**：`tools.description()` 去掉「人打的用法」、加 pack.json `commands[].ai.scenario`；`agent/toolpick.py` 2-gram 排序、`llm.max_tools`。
6. **Context 預算** `agent/context.py`：估算、Qwen-Agent 式分級截斷、工具結果 `cap_result`（預設 3000 字）。
7. **系統提示尾端重注入「本輪規則」、時間放最後一行、多步覆誦目標、Qwen3 不思考取樣參數。**
8. **評測擴充**：`claimed_without_call`、`any_of`、`missing_tool`／`missing_param` 題、Reliable Pass Rate、工具觸發 F1、第 4 關通過率；`live.py --repeat N`。

施工順序：2 → 3 → 1 → 4 → 7 → 6 → 5 → 8。

## 技術卡片一覽（出處）

| 編號 | 技術 | 出處 | 可信度 |
|---|---|---|---|
| A1 | 宣稱↔工具紀錄比對（證據帳本） | [completion_guard](https://gist.github.com/Julientalbot/64ecdb8c545b441ec685ced69cdc5910)、[Halluci-Action](https://neurips.cc/virtual/2026/173318)、[ECT 2608.23623](https://arxiv.org/abs/2608.23623)、[Arize](https://arize.com/blog/harnesses-have-an-expiration-date/)、[AIClaw](https://dev.to/chowyu12/how-aiclaws-harness-runtime-stops-agents-from-pretending-theyre-done-51cm) | 高（實作）／中（學術） |
| A2 | 偽造工具結果／分隔符偵測 | [Relign 2412.04141](https://arxiv.org/html/2412.04141v3)、SYNOX 測試紀錄 | 高 |
| A3 | finish／回報阻礙當工具 | [AgentScope v0](https://raw.githubusercontent.com/agentscope-ai/agentscope/v0/src/agentscope/agents/_react_agent_v2.py)、[v1 _config.py](https://raw.githubusercontent.com/agentscope-ai/agentscope/main/src/agentscope/agent/_config.py)、[OpenManus](https://raw.githubusercontent.com/FoundationAgents/OpenManus/main/app/agent/toolcall.py)、[ToolBeHonest 2406.20015](https://arxiv.org/html/2406.20015v2) | 高 |
| A4 | nudge 字句與次數上限 | [LessWrong（Inspect 字句消融）](https://www.lesswrong.com/posts/bvfobE9GAbt9HvQzc/)、[LangChain #4608](https://forum.langchain.com/t/4608) | 高 |
| A5 | 行動輪關 thinking | [Reasoning Trap 2510.22977](https://arxiv.org/html/2510.22977v1) | 高 |
| A6 | 不逼最終答案格式、給回報失敗的路 | [Upward Deceivers 2512.04864](https://arxiv.org/html/2512.04864v1) | 高 |
| A7 | LLM 裁判（第二道） | [Relign](https://arxiv.org/html/2412.04141v3)、[MIRAGE-Bench 2507.21017](https://arxiv.org/html/2507.21017v1) | 高 |
| B1 | content 後備解析器、不解析 think 內 | [Qwen-Agent nous_fncall_prompt.py](https://raw.githubusercontent.com/QwenLM/Qwen-Agent/main/qwen_agent/llm/fncall_prompts/nous_fncall_prompt.py)、[Qwen 文件](https://qwen.readthedocs.io/en/latest/framework/function_call.html)、Ollama [#14745](https://github.com/ollama/ollama/issues/14745) [#14493](https://github.com/ollama/ollama/issues/14493) | 高 |
| B2 | 寬鬆 JSON 修復 | [MetaGPT repair_llm_raw_output.py](https://raw.githubusercontent.com/FoundationAgents/MetaGPT/main/metagpt/utils/repair_llm_raw_output.py)、[AgentScope 論文](https://arxiv.org/html/2402.14034)、[DeepSeek updates](https://api-docs.deepseek.com/updates)、[json_repair](https://github.com/mangiucugna/json_repair) | 高 |
| B3 | 驗證錯誤當工具結果回饋 | [AgentScope v1 _agent.py](https://raw.githubusercontent.com/agentscope-ai/agentscope/main/src/agentscope/agent/_agent.py)、[Kani 2309.05542](https://arxiv.org/abs/2309.05542) | 高 |
| B4 | 受限解碼：K2 enforcer、DeepSeek strict、Ollama format、llama.cpp required、vLLM、XGrammar | [K2 報告](https://arxiv.org/html/2507.20534)、[K2VV](https://github.com/MoonshotAI/K2-Vendor-Verifier)、[DeepSeek API](https://api-docs.deepseek.com/api/create-chat-completion)、[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)、[llama.cpp PR #9639](https://github.com/ggml-org/llama.cpp/pull/9639)、[vLLM](https://docs.vllm.ai/en/stable/features/tool_calling/)、[XGrammar 2411.15100](https://arxiv.org/abs/2411.15100) | 高／中 |
| B5 | 兩段式「先決定再行動」schema | [Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)、[AgentScope structured output tool](https://raw.githubusercontent.com/agentscope-ai/agentscope/main/src/agentscope/agent/_structured_output_tool.py) | 中 |
| B6 | 停止詞防偽造結果 | [qwen_fncall_prompt.py](https://raw.githubusercontent.com/QwenLM/Qwen-Agent/main/qwen_agent/llm/fncall_prompts/qwen_fncall_prompt.py)、[react_chat.py](https://raw.githubusercontent.com/QwenLM/Qwen-Agent/main/qwen_agent/agents/react_chat.py) | 高 |
| C1 | 重複回覆／失敗呼叫偵測 | [OpenManus base.py](https://raw.githubusercontent.com/FoundationAgents/OpenManus/main/app/agent/base.py)、AgentScope `tool_retries_limit`、[OpenHands stuck.py](https://huggingface.co/spaces/Backup-bdg/OpenHands/resolve/main/openhands/controller/stuck.py)、[AgentTuning](https://arxiv.org/html/2310.12823) | 高 |
| C2 | 步數上限強制總結 | [AgentScope v0 _react_agent.py](https://raw.githubusercontent.com/agentscope-ai/agentscope/v0/src/agentscope/agents/_react_agent.py) | 高 |
| C3 | DFSDT 放棄＋多樣性提示 | [ToolLLM 2307.16789](https://arxiv.org/html/2307.16789v2) | 高（CPU 不划算） |
| D1 | EasyTool 工具說明改寫 | [EasyTool 2401.06201](https://arxiv.org/html/2401.06201) | 高 |
| D2 | 每輪工具子集 | [Less is More 2411.15399](https://arxiv.org/html/2411.15399)、[AnyTool 2402.04253](https://arxiv.org/html/2402.04253)、[ToolRet 2503.01763](https://arxiv.org/abs/2503.01763) | 高 |
| D3 | 工具群組 vs 遮罩不移除 | [AgentScope tool 教學](https://doc.agentscope.io/tutorial/task_tool.html)、[Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) | 高 |
| E1 | Ollama num_ctx／靜默截斷／偵測 | [FAQ](https://docs.ollama.com/faq)、[context-length](https://docs.ollama.com/context-length)、[openai-compatibility](https://docs.ollama.com/api/openai-compatibility)、[#5356](https://github.com/ollama/ollama/issues/5356)、[#10368](https://github.com/ollama/ollama/issues/10368) | 高 |
| E2 | Qwen-Agent 分級截斷 | [Qwen-Agent llm/base.py](https://raw.githubusercontent.com/QwenLM/Qwen-Agent/main/qwen_agent/llm/base.py) | 高 |
| E3 | 工具結果上限＋可還原指標 | ToolLLM、AgentScope `tool_result_limit`、Manus、[Sibyl 2407.10718](https://arxiv.org/html/2407.10718v2) | 高 |
| E4 | 接近上限時固定 schema 摘要 | [ReSum 2509.13313](https://arxiv.org/html/2509.13313)、AgentScope `trigger_ratio` | 高 |
| E5 | Manus 六條（KV cache、append-only、覆誦、留錯誤…） | [Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) | 高 |
| E6 | IterResearch 每輪重建工作區 | [WebResearcher 2509.13309](https://arxiv.org/html/2509.13309v2)、[Tongyi DeepResearch 2510.24701](https://arxiv.org/html/2510.24701) | 高（機制）／低（未訓練遷移） |
| E7 | LLMLingua-2（CPU BERT 壓縮器） | [2403.12968](https://arxiv.org/html/2403.12968)、[LightMem 2510.18866](https://arxiv.org/html/2510.18866v4) | 高 |
| F1 | MemoryOS／A-MEM／LightMem／MemoryBank | [2506.06326](https://arxiv.org/html/2506.06326)、[2502.12110](https://arxiv.org/html/2502.12110)、[2305.10250](https://arxiv.org/html/2305.10250) | 高 |
| G1 | 小模型守不住系統提示→尾端重注入 | [SysBench 2408.10943](https://arxiv.org/html/2408.10943v2)、[IHEval 2502.08745](https://arxiv.org/html/2502.08745v2) | 高 |
| G2 | 取樣參數與思考歷史依模型家族 | [Qwen3-8B 模型卡](https://huggingface.co/Qwen/Qwen3-8B)、[MiniMax-M2](https://github.com/MiniMax-AI/MiniMax-M2)、[DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode) | 高 |
| G3 | Plan-and-Solve | [2305.04091](https://arxiv.org/html/2305.04091) | 高／低（9B） |
| H1 | K2VV 工具觸發 F1＋schema 正確率 | [K2-Vendor-Verifier](https://github.com/MoonshotAI/K2-Vendor-Verifier) | 高 |
| H2 | Reliable Pass Rate、BFCL irrelevance、重播停滯輪 | [Relign](https://arxiv.org/html/2412.04141v3)、[BFCL v3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html)、[MAST 2503.13657](https://arxiv.org/html/2503.13657v3) | 高 |

## 沒讀到或不確定

- Kimi K2 enforcer 程式碼未公開；vLLM `--tool-strict-level` 細節為二手。
- DeepSeek `/guides/function_calling` 頁抓不到（SPA）；DeepSeek Harness 只讀到 quickstart。
- MiniCPM4-MCP `generate_example.py` 404；SGLang 文件 404；AgentScope 文件站多頁 404（改讀 GitHub 原始碼）；vLLM glm4_moe 解析器原檔 404（讀 EasyDeL 移植版）。
- Ollama 截斷切法（runner.go）未讀到原始碼，由日誌欄位推。
- 規則式「宣稱偵測器」的誤判率文獻無數據；要自己標定。
- ntu_easy_llm 是否支援 `stop`／`tool_choice`／content parts 未驗證。
- SYNOX 9b「印出分隔符」是解析器層還是模型層，要回看 `tools/local-llm-live/results/*.json` 原始回應才知道（本次沒重跑模型）。
- LongLLMLingua、ToolRet、MemAgent 只讀摘要。
