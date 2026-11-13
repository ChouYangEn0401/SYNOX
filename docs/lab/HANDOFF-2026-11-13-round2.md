# 交接：2026-11-13 第二輪（接在 HANDOFF-2026-11-13.md 之後）

## 這一輪做完並合進 SYNOX `dev`（已 push，HEAD `04a6f47`，完整 pytest 2305 過）
| 合併 | 內容 | ADR |
|---|---|---|
| `d48e216` feat/local_llm_platform | `llm.kind="local"`（Ollama／vLLM／LM Studio）；context_size 設定＋建議（依剩餘 RAM、模型大小、SYNOX 提示大小估算）；逾時＝450 秒「無進展」＋1800 秒總上限；97% 截斷警告；keep-awake 對現代待命加固、預設關、開啟處都提醒「會覆蓋 Windows 睡眠設定」、設定頁開關；`ntu_easy_llm` 改官方 release wheel | 0007、0006 附記 |
| `08b80a4` feat/completion_guard | 虛假完成檢測（`agent/claims.py`，預設只對本地）、洩漏工具呼叫救回、停止詞、`system__cannot_do`、重複失敗停止、步數用完總結 | 0008–0012 |
| `9f02773` feat/small_model_harness | 工具說明精簡（pack.json `scenario`）、每輪工具上限、context 預算、本輪規則重注入、qwen3 不思考取樣、評測擴充 | 0013–0020 |
| `04a6f47` feat/vlm_vision | `ImagePart`／`Message.images`／`llm.vision`（auto／on／off、`vision_model` 兩段式）、Telegram 私訊照片、限制與去 EXIF、記憶只留文字替身 | 0021 |

研究依據：`research/2026-11-13-cn-harness-techniques.html`（＋.md），commit `1a7fe5f`。

## 這台機器已做的本機設定（不在 git）
- `<HOME>\SYNOX\config.json`（被 git 忽略）：新增 `runtime.keep_awake = {enabled:true, screen_off_after_min:0}`。要重啟 SYNOX 才生效。

## 沒驗證／已知問題（重要）
1. **沒有任何真實模型驗證**：本輪所有開發都用假 adapter／假 opener／已存回覆；9B 在新 harness 下是變好還是變差，要實測（`--repeat N` 重跑＋人工複核每次閘門觸發）。
2. 虛假完成閘門的誤判率標定：0/97，統計上證明不了 ≤2%（95% 上界約 3%）；詞表缺「我再」，「…我再幫你加進行事曆」會被誤讀為完成宣稱（ADR 0020）。
3. 停止詞沒放 `⟦SYNOX-TOOL`（9B 真實回覆有 2/9 用它包工具呼叫，ADR 0010）。
4. `ntu_easy_llm` 0.5.0 沒有圖片 API；VLM 靠它「原封不動傳遞 content」的現有行為（ADR 0021），改版前要重跑測試，建議請套件正式支援 images。
5. 兩份 token 估算不一致（context.py 與 local.py），英文為主的提示可能在刪減後仍出截斷警告。
6. Telegram 照片的 caption 收不到（vendor SDK 丟掉，規定不改 vendor）。Discord、網頁不收圖。
7. 12 種語言：只有繁中是正式文字、簡中是 agent 自寫，其餘 10 種是英文。
8. keep-awake：現代待命下，插電時可擋閒置睡眠；用電池時請求在睡眠逾時後 5 分鐘被取消；闔蓋／電源鍵／手動睡眠一律取消；進入待命後 Windows 凍結所有桌面程式（含 Google Drive）。螢幕關閉計時器與真實進入待命**未在實機驗證**。排查：`docs/keep-awake-troubleshooting.md`（以系統管理員跑 `powercfg /requests`、`/sleepstudy`，檢查網卡「允許電腦關閉這個裝置以節省電源」）。
9. `requirements.txt` 刻意沒加 `ntu_easy_llm`（Dockerfile 也讀它，會讓每個映像多裝三個大 SDK）；`bootstrap.ps1` 只改了線上安裝路徑。
10. vLLM、LM Studio、Ollama 的圖片格式只對假伺服器測過；Pillow 路徑（縮圖）沒裝沒測。
11. 此台 `ntu_easy_llm` 已裝（0.5.0，SYNOX 的 .venv）。

## 如何用本地模型測 better harness
`config.json` 的 `llm` 改成 `{"kind":"local","server":"ollama","base_url":"http://127.0.0.1:11434","model":"qwen3.5:9b","context_size":8192}`，重啟，`python -m synox console`；`python -m synox doctor --offline` 看閘門／工具上限／預算／看圖狀態。先用 9B，27B 在 CPU 上慢且吃記憶體；一次只載入一個模型。

## 仍要擁有者決定（承接上一份）
- `openai_login`、`copilot_login`：要不要接進 SYNOX、真實 binary 實測、自己讀 OpenAI 條款；Kimi 灰色未做。
- 閘門詞表重新標定、是否把閘門預設 auto 擴到其他來源。
- 三個新專案（`SYNOX_Plans`、`openai_login`、`copilot_login`）需自行 `git remote add origin`；`SYNOX_Plans` 含本檔與研究 HTML，**尚未 push**。
