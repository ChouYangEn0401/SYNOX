# 交辦單：讓 SYNOX 接上外部的本地 LLM 閘道（H-S1～H-S3）

## [狀態]

待做。這張只是記錄，還沒有人開工。

## [前情提要]

- 有一個獨立的開源專案 **LocalLLMOutsiderProvider（`llmop`）v0.2.0**（GitHub `ChouYangEn0401/LocalLLMOutsiderProvider`，`dev` 分支）：
  把本地 LLM（Ollama／LM Studio 等）包成 OpenAI 相容 API，前面加帳號、API key（`sk-llop-…`）、用量與排隊，可選端對端加密。
- 它的 README「讓 SYNOX 使用」一節列了三種接法，SYNOX 端需要配合三件事（llmop 的 `docs/plan/MERGE_PLAN.md` 9.6）。
- llmop 本身還沒在真機上驗證過；這張單不急，等 llmop 實測通過再做比較好。

## [任務]

1. **H-S1**：SYNOX 的 local 後端可選擇帶 API key 標頭（`Authorization: Bearer <key>`），不設就跟現在一樣。
2. **H-S2**：確認 SYNOX 的 OpenAI 相容後端實際送出的標頭與是否串流，寫進文件（llmop 公開 `/v1` 預設不串流，非串流超過約 100 秒會被 Cloudflare 回 524）。
3. **H-S3（可選）**：把 llmop 的用戶端 SDK 做成 SYNOX 的 adapter，省掉另外跑本機代理（`127.0.0.1:8788`）。

不要做：
- 不改 `vendor/isdtelekit/`，也不把 llmop 的程式碼複製進 SYNOX 本體。
- key 不寫進設定範例的真實值，也不進 git。
- 改 AI 行為規則或對外合約前，先照 AGENTS.md 寫 ADR。

## [安裝流程與環境確認]

照 [../development.md](../development.md) 建環境，開工前先在沒改過的 `dev` 跑一次測試，記下基準。
測試一律用假後端，不連網、不開埠、不需要真的 llmop。

## [驗證清單集]

- [ ] H-S1：沒設 key 時，送出的請求跟改之前完全一樣；有設 key 時，標頭正確（用假傳輸的測試檢查）。
- [ ] H-S2：文件寫清楚標頭與串流行為，內容跟程式一致。
- [ ] `python -m pytest -q -p no:cacheprovider` 沒有比基準多壞。
- [ ] `python scripts/prepublish_check.py --worktree-only` 通過；沒有 key、本機路徑、私人資訊。
- [ ] 沒有留下 TODO 或半成品。

## [交回]

回報分支、commit、測試結果（含基準數字）、驗證清單逐項結果。使用者看得到的改變寫進 `CHANGELOG.md` 的「未發佈」。
