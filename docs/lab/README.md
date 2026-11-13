# SYNOX 實驗室紀錄（docs/lab）

本地模型、VLM、訂閱登入的調查、測試紀錄與設計（2026-11-13 起）。先讀 HANDOFF-2026-11-13-round2.md。這些是實驗紀錄，不是產品文件；全部使用假資料。

| 文件 | 內容 |
|---|---|
| [docs/HANDOFF-2026-11-13.md](HANDOFF-2026-11-13.md) | **先讀這份**：這一輪做了什麼、在哪、還沒做什麼、要你決定什麼 |
| [docs/HANDOFF-2026-11-13-round2.md](HANDOFF-2026-11-13-round2.md) | **第二輪（先讀這份）**：local 平台、虛假完成閘門、小模型 harness、VLM 都已合進 dev；沒驗證的事與測試方法 |
| [docs/research/](research/) | 中國團隊小模型 harness 技術研究（HTML 交接書＋摘要） |
| [docs/2026-11-13-local-llm-ollama-test-record.md](2026-11-13-local-llm-ollama-test-record.md) | 本地模型（Ollama）接 SYNOX harness 的測試紀錄 |
| [docs/2026-11-13-vlm-vision-design.md](2026-11-13-vlm-vision-design.md) | VLM（看圖）接進 harness 的設計（含本地實測） |
| [docs/2026-11-13-subscription-login-research.md](2026-11-13-subscription-login-research.md) | 各家訂閱登入調查、`ntu_easy_llm` 結構確認 |
| [tools/local-llm-live/](tools/local-llm-live/) | 對真的 Ollama 跑 SYNOX AgentLoop 的測試腳本與原始結果 |
| [docs/2026-11-14-tool-apps-implementation-plan.md](2026-11-14-tool-apps-implementation-plan.md) | 工具服務（每個工具自己的完整網頁）的實作計畫：合約、八個工作包、只有擁有者能做的真機驗收；設計在 [adr/0023](../adr/0023-tool-apps-services.md)（提案） |

> 這些檔案原本在本機專案 SYNOX_Plans，2026-11-13 併入 SYNOX 的 docs/lab（路徑已改成 <HOME> 佔位）。文中提到「SYNOX_Plans」「尚未 push」的地方是搬進來之前的狀態。

> **改名（2026-11-13）**：文中的 `openai_login` 已改名為 [ChatGPTLogin](https://github.com/ChouYangEn0401/ChatGPTLogin)（套件 `chatgpt_login`），`copilot_login` 已改名為 [GithubCopilotLogin](https://github.com/ChouYangEn0401/GithubCopilotLogin)（套件 `github_copilot_login`），兩個都已推上 GitHub；文中「本機 git、無 origin」是改名前的狀態。

- 待開的 issue 內容（尚未驗證的項目）：[issues-to-open.md](issues-to-open.md)
