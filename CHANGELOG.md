# Changelog

## 未發佈（「遇到問題？」回報面板）

### 新增
- 設定頁多一個「🙋 遇到問題？」分頁（側欄和設定頁標題也有小連結）：三步——沒有 GitHub 帳號先免費註冊、「幫我準備好回報內容」、帶著內容到 GitHub 開問題單（你自己按送出）。
- 回報內容先遮掉金鑰、token、密碼、email、長數字、含使用者名稱的路徑；給你看、你可以改。SYNOX 不連網、不寫檔、不會自己送出。
- GitHub 白話中文的問題單表單（`.github/ISSUE_TEMPLATE/problem.yml`）與 `config.yml`（資安問題請看 SECURITY.md，不要公開回報）。

## 未發佈（版本與發佈規則）

### 新增
- `docs/versioning.md`：版本號、分支、tag、每版要有什麼、「我要怎麼更新？」；`scripts/release.py`（bump／check／notes）；ADR 0023 自己更新與緊急修補（提案）。
- `synox about`、`synox doctor` 多一行：到 GitHub 發佈頁看有沒有新版（不自己連網）。
- `docs/advanced-install.md`：給工程師的進階安裝（原始碼＋venv、Docker、無畫面執行、背景服務），每項標 ✅ 跑過／🧪 未實測／⏳ 未完成。

## 未發佈（設定頁的官方工具庫、預設用 SYNOX 自己的 Python）

### 新增
- **設定 →「功能與安裝」多了「工具庫（官方）」**：按「載入工具清單」才連網（固定只抓 SYNOX_Libs 發佈頁 v0.2.0 的清單），每個工具一張卡（徽章、「安裝」「⬇ 下載」「說明」，已裝的顯示版本／有新版）。
  「安裝」由 SYNOX 自己下載：只走 GitHub 發佈頁與它的下載主機、檔名要對、大小有上限、sha256 要等於清單，之後走跟上傳一樣的檢查報告→按確認（`src/synox/packs/catalog.py`）。
  另有「別人做的技能（OpenClaw、Hermes）」說明卡（⏳ 尚未完成、沒有安裝鈕）與「沙盒模式」預留卡（⏳ 尚未完成、開關關著）。
- **Setup.bat 預設用 SYNOX 自己的 Python**：沒有 `runtime\python` 時，下載釘死版本與 sha256 的 uv，把 CPython 3.12 裝進 `runtime\python-uv`（只用它自己管的 Python，不看系統、Conda、商店版），
  不改 PATH、不寫登錄檔、不用 winget；偵測到 Conda／其他 Python 會先白話說明；`Setup.bat -UseSystemPython` 可改用自己的 Python（進階）。所有啟動用的 .bat 先清掉 PYTHONHOME、PYTHONPATH、CONDA_* 再跑。
  **Windows 上都還沒實測**（步驟見 docs/handoff/clean-machine-test.md 的 A14–A16）。
- **線上頁面一律有本機副本＋頁面版本**：登記表 `docs/artifacts.json`；`scripts/page_stamp.py --check` 檢查頁面版本對不對得上內容；
  `tests/test_artifact_registry.py` 擋「沒有本機副本／頁尾沒有線上網址／改了內容沒重蓋版本」；規則寫在 `docs/AGENT.md`。介紹頁的版本號也改成同一種格式。
- **一步一步教學網頁** `docs/guide/index.html`（線上版 https://claude.ai/artifact/96iWvykYyUfAC5pkYUrC6F ）：26 步＋Discord 選讀，每一步一個畫面、要按的地方會亮；
  步驟資料集中在一個陣列，之後可以給教學工具共用。介紹頁「安裝設定」卡片與「怎麼開始」標題下都有連結。
- **自動打包 Windows 安裝程式**：`.github/workflows/build-installer.yml`（手動觸發或推 `v*` 標籤；附到草稿 release，不會自動發佈），`docs/release-build.md`。**還沒跑過**。
- 規劃：`docs/lab/2026-11-13-onboarding-help-aliases-plan.md`（新 /help、範例、教學引擎與教學工具、自訂指令）。
- 設計稿：`docs/installer/spec.html`（安裝程式規格，線上版 https://claude.ai/artifact/3oCmmu4Epmqf2raNAaoavB ）、
  `docs/lab/design/2026-11-13-brand-explorations.html`（六套品牌提案，線上版 https://claude.ai/artifact/QqdEnR3s25c7tPUW23zfoz ）；`scripts/page_stamp.py` 替這類網頁蓋頁面版本。

### 修正
- 把 .synoxpack 拖進網頁：一定跳到「功能與安裝」分頁（以前跳到上次開的分頁，報告藏在看不到的地方）。

## 未發佈（安裝精靈：一鍵安裝 Claude Code、「下一步」不再被擠掉）

### 新增
- 精靈 AI 頁找不到 Claude Code 時，多一顆「一鍵安裝（PowerShell）」：開一個 PowerShell 視窗跑官方的 `irm https://claude.ai/install.ps1 | iex`
  （裝在使用者自己的資料夾、不用系統管理員），跑完提示「打 claude 登入一次，再回來按『裝好了，重新偵測』」；另有可以複製的那一行指令與「複製指令」。
  12 種語言都有字串。
- `find_claude` 也找 npm 全域安裝的位置（`%APPDATA%\npm\claude.cmd`）：PATH 還是舊的時候不再誤報「找不到」。

### 修正
- 精靈的「下一步」那一列釘在視窗最下面，內容比視窗高時改成可以捲動（擁有者回報 AI 頁的「下一步」有時被藏起來）。

## 未發佈（介紹頁改版）

### 改變
- **介紹頁 `docs/landing/index.html` 改版**（線上版同一個網址 <https://claude.ai/artifact/SNsSkbcVQm7BU22BBZN3gW>）：
  開頭改成標語「聊天就能用，資料不出門。」，下面用圖示列出支援的地方（Telegram、Discord、網頁）、AI（Claude、OpenAI、Gemini、本機模型）與 Windows；
  「它能幫你做什麼」縮成 8 格一句話；「看畫面」改成大圖、可切換 7 個畫面（對話、工具、主控、裝功能、設定、接聊天軟體、手機）和深淺色、點圖放大；
  安全、安裝、開發者、alpha 現況都縮短。修掉「三步裝好」第 2 步的子清單被套成步驟格、文字一字一行的跑版。
- 截圖用目前的網頁介面重拍（`docs/ui/preview.html` 的假資料，電腦版 1360×820 兩倍解析度、手機 390×844），存成 `docs/landing/shots/*.webp`。
- 新增 `scripts/make_landing.py`：`--shoot` 用 Playwright 重拍截圖；不加就只把原稿 `docs/landing/page.html` 和截圖組成單一檔案的 index.html（約 1.3 MB）。
  品牌圖示取自 Simple Icons（CC0），頁尾註明名稱與標誌屬於各自的所有者。
- 介紹頁加上網頁版同一隻 S 寶寶的開場動畫：`make_landing.py` 組頁面時把 `static/splash.js` 整支和 `splash.css` 的開場段落原封不動塞進去
  （網頁版改了，重組就跟著變）；點左上角的 S 重播；系統開了「減少動態效果」就不播。
- 介紹頁照實標出 **⏳ 尚未完成**（一鍵安裝 .exe、GitHub Copilot、哨兵模式、macOS／Linux 安裝器、換電腦匯出、長期記憶）與
  **🧪 寫好了還沒實測**（Discord、外部服務、看照片、全新 Windows 安裝、Linux 沙盒與容器），並列出測試數字（2,349 個自動測試；
  2026-11-13 在 Linux 雲端 2,292 過、14 沒過、43 略過；真機驗證清單 0／32）。拿掉「安裝程式版附好 Python、不用上網」這句（exe 還沒打包）。
- 「功能」每格標「工具庫」或「內建」，加「還想要別的？裝一個就會」；支援列加 GitHub Copilot、個人版／伺服器版、哨兵模式；連結改連 GitHub 與線上教學。
- README 最上面加介紹頁的連結。
- 開場改成「點一下才進場」：網頁在後面載好之後，點 S 寶寶（或按 Enter）→ 隨機說「你好！／歡迎！／很高興認識你！」→ 翻成 S 標誌 → 進頁面；
  右上「直接進入」或 Esc 可略過；同一個分頁只出現一次；減少動態效果時不出現。樣子沿用 `splash.css`，流程在 page.html 自己的 `SynoxGate`（不再嵌 splash.js）。
- 「尚未完成」改用 ⏳（🚧 在 SYNOX 是 beta 的標籤，避免混淆）；「手機」分頁改名「窄螢幕」並寫清楚還沒有手機 App、網頁預設只給這台電腦用。
- 開場改成**每次打開都出現**（原本同一個分頁只出現一次，看起來時有時無）；文件裡的連結統一寫成 `…/SNsSkbcVQm7BU22BBZN3gW#synox`。
- 「怎麼開始」改成「下載、解開、點兩下」三張圖卡：大大的「⬇ 下載 SYNOX」（GitHub 的 main 分支 ZIP）、右鍵「全部解壓縮」、點兩下 `Setup.bat`；
  下面一行「裝好之後」，其他細節（Windows 安全提示、第一次要等、exe 尚未完成、git clone）收進「卡住了？」。
- 「它能幫你做什麼」的工具庫卡片直接接上工具庫：隨手記、記帳、行事曆、待辦各有「⬇ 下載」（GitHub 發佈頁 v0.2.0 的 .synoxpack）與說明頁連結；
  「接你的服務」連到工具庫說明頁；「還想要別的？」改成「⬇ 一次下載全部 9 個」「工具庫：每個工具的說明」「裝 OpenClaw／Hermes 的工具 ⏳ 尚未完成」「看怎麼寫工具」，
  「尚未完成」清單加上 OpenClaw／Hermes 生態的工具。
- 「還想要別的？」加「怎麼裝別人的工具 →」連到工具庫的說明頁；頁尾加很小的「線上版網址＋頁面版本」給開發者比對線上版和本機版。

## 未發佈（網頁設定頁分頁、安裝 pack 的專屬頁）

### 新增
- **設定頁分成分頁**：AI（來源＋用量）／聊天通道／功能與安裝／帳號（伺服器版、有權限才有）／電腦與備份（保持清醒＋備份）。
  分頁在網址上（`#settings:ai`、`#settings:channels`、`#packs`、`#settings:accounts`、`#settings:system`），重新整理、貼連結都留在同一頁；
  換分頁不重抓資料、不清掉正在填的表單。
- **安裝 pack 的專屬頁 `#packs`**（＝`#settings:packs`）：「安裝新功能」在最上面，報告、確認、結果都在同一格，不用往下捲。
  雙擊 .synoxpack／Install-Pack.bat／`synox install <檔>` 開的網址改成 `/?pack=<token>#packs`；不管帶什麼 hash，有 `?pack=` 一律到這頁、
  打開那一份，然後用 `history.replaceState` 把 token 從網址拿掉（留乾淨的 `#packs`）。
- **待核准清單**：還沒按確認的暫存 pack（`data/web_uploads/`）不用 token 也看得到（名字、版本、T2 標記、幾天後清掉），可以「看報告」或「不要裝」。
  新 API（擁有者）：`GET /api/packs/staged`、`POST /api/packs/discard {"token"}`；`admin.list_staged`（順便清掉 7 天沒處理的、
  沒有 staged.json 超過 1 小時的半套暫存；只看像 token 的資料夾、不跟符號連結）、`admin.discard_staged`。
- **安裝步驟**：檢查 → 看報告 → 確認 → 安裝 → 完成，有狀態動畫（遵守 reduced-motion）。每一步丟 `document` 的 `synox:install-step` 事件
  （detail：step、status、token、name），`#install-steps` 上也有 `data-step`／`data-status`：pack／工具作者之後可以掛自己的動畫或狀態。
  給其他程式碼用的入口 `window.SynoxInstall`（`open`、`reviewFile(file)`、`reviewToken(token)`、`onStep(fn)`、`state()`），之後的拖放也走它。

### 改變
- 報告上的「不要裝」現在真的刪掉暫存；多一個「稍後再決定」（收起來，留在待核准清單）。

## 未發佈（.synoxpack 好裝：檔案圖示、拖進網頁、安裝說明）

### 新增
- **.synoxpack 有圖示、點兩下就裝**：`Setup.bat` 替目前的 Windows 使用者登記檔案類型（只寫 HKCU、不用管理員、重跑一樣），
  一行一行印出寫了哪些機碼；多了 `DefaultIcon`（`src/synox/assets/synoxpack.ico`：藍綠底白色下載箭頭，`scripts/make_pack_icon.py`
  只用標準函式庫畫）與 `OpenWithProgids`，檔案總管不再顯示像壞掉的空白圖示。`python -m synox filetype register｜unregister｜status`。
  精靈最後一頁沒勾「點兩下安裝」＝拿掉；`Uninstall.bat` 照舊拿掉並列出刪了哪些機碼。
- **把 .synoxpack 拖進網頁**（任何一頁）：出現「放開來檢查」，放開就切到設定頁、交給原本的「上傳並檢查」，顯示同一份報告與確認按鈕
  （`static/packdrop.js`／`packdrop.css`；不另開 API、不跳過確認）。設定頁上傳框下面多一句「怎麼裝」的提示。
- 文件 [docs/install-packs.md](docs/install-packs.md)：四種裝法（點兩下、拖到 Install-Pack.bat、拖進網頁、`synox install`）與圖示空白／點兩下沒反應的排查；
  README、packs/README.md、docs/README.md 連過去。

### 安全
- 網頁上傳多驗 Content-Type（只收 zip／octet-stream／沒寫，否則 415）與大小（413）；`admin.stage` 要求檔案從 zip 檔頭 `PK\x03\x04` 開始——
  前面接了東西的自解壓 exe／polyglot 以前 zipfile 打得開，現在一律拒（網頁、`synox install`、點兩下都一樣）。

## 未發佈（branch feat/vlm_vision：看圖）

### 新增
- **看圖（VLM）**（`src/synox/llm/vision.py`，[ADR 0021](docs/adr/0021-vlm-vision.md)）：harness 不分叉，只多 provider 能力——
  `ImagePart`、`Message.images`、`ChatAdapter.supports_vision`／`check_vision()`。本地 Ollama 原生 `/api/chat` 送純 base64 的 `images`；
  OpenAI 相容（vLLM／LM Studio／other、openai／gemini／openai_compat）送 data URI 的 content parts（不送網址）；Anthropic 送 base64 image 區塊；
  Claude Code 不支援。不支援卻收到圖＝明講「此來源不支援圖片」，不偷偷丟掉。
- `llm.vision`＝auto（預設：Ollama 唯讀查 `/api/show` 的 capabilities、雲端看內建名單、查不到＝不支援）｜on｜off；
  `llm.vision_model`＝主模型看不到時的兩段式（看圖模型先把圖轉成文字、包進分隔符當資料）；都沒有＝老實說「這個模型看不到圖片」。
  `llm.vision_limits`（每則 3 張、每張 8 MB、長邊 1568 px）；只收 JPEG／PNG／WebP／GIF，去掉 EXIF（GPS）；Pillow 選用（沒裝就不縮圖）。
- **Telegram 私訊的照片**（含副檔名是圖的檔案）會交給 AI 看：getFile 讀進記憶體、不寫檔，抓不到或太大會告訴你，file_id 不再當文字給 AI。
- 圖裡的字是資料不是指令（有圖的那一輪系統提示多一段）；由圖導出的工具呼叫照樣過權限、參數驗證、確認卡、完成宣稱檢查。
- 設定頁與 doctor 多一行「看圖：…」（唯讀、不載入模型）；網頁換 AI 來源時保留 vision 的設定。
- 評測：新類別 `vision` 兩題（讀收據→叫工具、圖裡夾指令→不照做；假圖在 `evals/assistant/images/`），共 38 題。

### 不變
- 沒有圖的對話：提示、請求、連線一個字都不變。對話記憶、常駐助理、心跳、soul 只留文字替身，不存圖。
- Discord 私訊、網頁這一輪不收圖；Telegram 照片的說明文字（caption）SDK 收不到（見 ADR 0021）。

## 未發佈（branch feat/small_model_harness：工具說明精簡化、每輪工具上限、context 預算、本輪規則與覆誦、Qwen3 取樣、評測擴充）

### 新增
- **工具說明精簡化**（[ADR 0013](docs/adr/0013-tool-scenario-descriptions.md)）：pack.json `commands[].ai` 可以寫 `{"scenario": "一句話"}`，
  給 AI 的說明變成「用途。情境：…」，不放人打的用法（第 1 關檢查：120 字內、一行、不准網址或像指令的字）。SDK `@tool(scenario=)`（SDK 0.2.2）。
  **沒寫 scenario 的工具說明一個字都不變。**
- **每輪工具數上限**（`src/synox/agent/toolpick.py`，[ADR 0014](docs/adr/0014-per-turn-tool-cap.md)）：工具太多時用使用者這句話的字元 2-gram
  挑前 N 個；`system__cannot_do`、`skill_read`、系統指令永遠保留；叫了清單外但有權的工具照常執行、下一步給全部。`llm.max_tools`＝auto
  （本地／私網來源 12，其他不限）｜0｜數字。
- **Context 預算**（`src/synox/agent/context.py`，[ADR 0015](docs/adr/0015-context-budget.md)、[0016](docs/adr/0016-tool-result-cap.md)）：
  設了 `llm.context_size` 就在送出前估長度、照 Qwen-Agent 的順序截（舊對話 → 舊的工具結果 → 最後一個工具結果的中間 → soul.md），
  工具結果超過 `llm.tool_result_chars`（auto＝有預算時 3000 字）保頭尾。截了一定寫 log、另送一則提醒。**沒設 context_size＝不截。**
- **本輪規則與時間放最後一行、多步覆誦目標**（[ADR 0017](docs/adr/0017-tail-rules-and-time-last.md)、[0018](docs/adr/0018-goal-recitation.md)）：
  `llm.prompt_tail`＝auto（本地／私網來源開）｜on｜off。開頭整段多輪逐字相同（本地模型的 prefix cache）。
- **Qwen3 不思考模式取樣參數**（[ADR 0019](docs/adr/0019-qwen3-no-think-sampling.md)）：kind=local 的 Ollama、模型名有 qwen3＝送
  temperature 0.7／top_p 0.8／top_k 20／min_p 0；`llm.sampling`（auto｜qwen3｜off）、`llm.options` 可蓋過。
- **評測**（[ADR 0020](docs/adr/0020-eval-missing-tool-param-and-metrics.md)）：新類別 `missing_tool`、`missing_param` 各 2 題（共 36 題）、
  新檢查 `cannot_do`；報表多 Reliable Pass Rate、工具觸發 F1、第 4 關通過率；`scripts/eval_assistant.py --merge` 合併重跑 N 次的報表。
- doctor 多一行「小模型 harness」（工具上限、context 預算、工具結果上限、本輪規則開不開）。

### 改變
- 「auto」的判斷抽成 `src/synox/agent/auto.py`（完成宣稱檢查、步數總結、上面這些共用）；`claims.weak_source` 等舊名字照舊能用。
- 本地 Ollama 跑 qwen3 系列模型時，請求的 options 多了取樣參數（以前用伺服器／Modelfile 的預設）。
- 網頁設定頁換 AI 來源時也保留 `max_tools`／`tool_result_chars`／`prompt_tail`／`sampling`／`options`。

### 不變
- 雲端來源與 Claude Code 預設：工具清單、系統提示、工具結果一個字都不變（沒設 context_size 就不截）。

## 未發佈（branch feat/completion_guard：本地模型的虛假完成檢測、救回洩漏的工具呼叫、停止詞與「做不到」出口）

### 新增
- **完成宣稱檢查**（`src/synox/agent/claims.py`，[ADR 0008](docs/adr/0008-completion-guard.md)）：AI 說「已記下／已新增／記好了」，
  這一輪卻沒有成功的寫入工具呼叫（或回覆裡自己寫了「工具結果」、分隔符）＝不送出，用中性的修正字句重試（`llm.verify_retries`，預設 2）；
  用完就照實告訴使用者「沒有執行」，並附上 AI 原本的回覆（不吞掉、不假裝成功）。`llm.completion_guard`＝`auto`（預設：只對本地模型、
  指到這台或家裡網路的 openai_compat 開）｜`on`｜`off`。用已存的真實 9b／27b 回覆標定：真實回覆 20 則不該攔的 0 誤判、3 則該攔的全抓到
  （樣本很小，統計意義有限，見 ADR）。doctor 多一行說開了沒。
- **救回文字裡的工具呼叫**（[ADR 0009](docs/adr/0009-leaked-tool-call-recovery.md)）：模型把呼叫印成文字（`<tool_call>` JSON、Qwen 的
  `<function=…>`、MiniMax 的 `<invoke>`）時救回來，**照常過權限判斷、參數驗證、確認卡**；壞掉的 JSON 會寬鬆修復。思考段 `<think>` 一律拿掉、不從裡面找呼叫。
- **停止詞**（[ADR 0010](docs/adr/0010-stop-words.md)）：本地模型在模型開始寫「〔工具結果〕」／`<tool_response>` 時就截斷。
- **「做不到」的出口** `system__cannot_do`（[ADR 0011](docs/adr/0011-cannot-do-exit.md)）：AI 呼叫它＝這一輪結束、回「做不到：原因」。
- **同一個呼叫連續失敗**：第 2 次提醒 AI 換做法、第 3 次停下來；**步數用完的總結**（本地來源預設開，`llm.summarize_on_limit`）
  （[ADR 0012](docs/adr/0012-repeat-failure-and-step-limit-summary.md)）。
- 評測：新檢查 `claimed_without_call`（每一題都跑）、`must_call` 的 `any_of`、新類別 `fake_done` 兩題（共 32 題）。

### 改變
- `note-01` 的檢查改成「`note__add` 或內建 `remind__add`」都算對。
- 系統提示第 2 行：有工具時說明「沒有呼叫工具就什麼都沒做」並指向 `system__cannot_do`。
- `AgentLoop.call_tool` 回三個值（結果、是否出卡、ok）；`ChatAdapter.chat` 多一個關鍵字參數 `stop`（只傳給 `supports_stop=True` 的 adapter）。
- 網頁設定頁換 AI 來源時保留 `completion_guard`／`verify_retries`／`summarize_on_limit`／`think`。

### 不變
- 雲端來源與 Claude Code 預設不開完成宣稱檢查、不做步數總結；正常的對話一個字都不變。
## 未發佈（branch feat/local_llm_platform：本地模型是內建能力、context 建議、無進展逾時；保持清醒加固）

### 新增
- **本地模型**（`llm.kind = "local"`，`src/synox/llm/local.py`，設計 [ADR 0007](docs/adr/0007-local-llm-platform.md)）：SYNOX 內建，
  不需要金鑰、不需要 ntu_easy_llm。`server`：`ollama`（預設，原生 `/api/chat`，`num_ctx`、`think: false`、原生工具）｜
  `vllm`｜`lmstudio`｜`other`（OpenAI 相容 `/v1/chat/completions`）。真的串流（Ollama NDJSON、SSE，工具呼叫的增量會組回來）。
- **逾時改成「無進展」**：`llm.timeout`（預設 **450 秒**＝以前 90 秒的 5 倍）是「多久完全沒有新的字」，模型只要還在回就不砍；
  另有很寬的總上限 `llm.max_total_timeout`（預設 1800 秒）。錯誤訊息會說是哪一種。
- **context-size 設定與建議**：`llm.context_size`（0＝伺服器預設；512～1048576）。建議選項 4096～131072，依這台可用的記憶體、
  模型權重大小與 KV cache 估出「建議／吃緊／可能撐不住」，並標出「會截斷 SYNOX 提示」的選項（`src/synox/llm/local_advice.py`；
  **都是估算**，偏保守）。文字版 `synox init`、視窗精靈、網頁設定頁（「看建議」）、`doctor` 都有。
- **截斷不再靜默**：提示用掉 context 的 97% 以上＝提醒（log、對話裡另一則、設定頁），不再讓 Ollama 悄悄丟掉系統提示。
- **唯讀的「測一下」**：本地模型只讀模型清單與中繼資料（不載入模型、不送對話），說模型在不在、最大 context、設定合不合理；
  模型不在會提示 `ollama pull <名字>`。
- `synox init` 多 `--llm local`、`--server`、`--context-size`；網頁新 API `POST /api/settings/llm/local-advice`（[runtime-api.md](docs/runtime-api.md)）。
- **保持清醒加固**（[ADR 0006 附記](docs/adr/0006-keep-awake-screen-may-sleep.md)）：同時請求 `PowerRequestExecutionRequired`；
  偵測「現代待命」（Modern Standby）機型並說明效果有限；新的排查文件 [keep-awake-troubleshooting.md](docs/keep-awake-troubleshooting.md)
  （`powercfg /requests`、`/sleepstudy`、網路卡省電、DAM）。網頁**設定頁**新增「保持清醒」卡片（開關＋閒置幾分鐘關螢幕）。
  打開它的每個地方都講明：**會覆蓋 Windows 電源選項的「睡眠」設定**；螢幕仍可變暗／關閉；闔蓋、手動睡眠、低電量、Windows Update 重開機擋不住。

### 改變
- `openai_compat` 現在真的會用 `llm.timeout`（以前沒傳下去）；沒寫時網址是這台或家裡網路＝450 秒，其他維持 90 秒。
- `pyproject.toml` 的 `llm` 組改成 ntu_easy_llm 0.5.0 官方 release wheel 的網址；`setup/bootstrap.ps1` 連網安裝那一條改裝 `-e .[llm]`。
- `Reply` 多 `warnings`（給人看的提醒，不是錯誤）。

### 不變
- 保持清醒仍然**預設關**（有測試鎖住）；SYNOX 不修改任何電源設定。雲端 AI 來源的行為不變。

## 未發佈（branch feat/screen_protect_awaker：保持清醒——電腦不睡著、螢幕可以熄）

### 新增
- **保持清醒**（任務 `system.keep_awake`，`src/synox/runtime/keepawake.py`，設計 [ADR 0006](docs/adr/0006-keep-awake-screen-may-sleep.md)）：
  請 Windows「系統需要保持清醒」，電腦不會自己睡著；**不**請求螢幕常亮，所以螢幕照 Windows 電源計畫熄，動滑鼠或鍵盤 Windows 自己點亮——
  不需要另外做「黑螢幕小工具」。每 60 秒確認請求還在；SYNOX 停止時放掉（程式結束 Windows 也會自己放掉）。
- 電源計畫把「關閉螢幕」設成「永不」的人：`screen_off_after_min`（1～240）＝閒置這麼久就請 Windows 關一次螢幕，之後一樣動一下就亮。
- **設定** `runtime.keep_awake`：`{"enabled": false, "screen_off_after_min": 0}`，**預設關**（不替人改電腦的睡眠行為）。
  網頁 `POST /api/runtime/keep-awake`（寫回 config.json）、`GET /api/runtime/status` 多 `keep_awake`、`doctor` 多一行。

### 擋不住的（照實說）
- 闔上筆電蓋、開始選單手動睡眠、電池快沒電、Windows Update 重開機。只有 Windows 有作用，其他系統顯示 idle，不算失敗。
- 沒有新的相依套件（標準函式庫 ctypes）。

## 未發佈（branch feat/soul-memory：soul 帳本——助理筆記的來歷、有疑慮先問、取代不刪除、整理與遺忘）

### 新增
- **soul 帳本**（`src/synox/runtime/ledger.py`，設計 [ADR 0005](docs/adr/0005-soul-ledger-memory-provenance-review.md)）：
  常駐助理記進 soul.md「助理筆記」的每一條現在有**來歷**（誰、什麼時候、上次確認、看不看得出是你自己說的）。
- **有疑慮的先問你**：助理想記的那一行如果像在對 AI 下指令、有網址或電子郵件、要跳過確認、要把資料傳出去、要把某個來源當成可信、
  提到密碼、夾了分隔符，或跟現有的一條很像（可能是更新、也可能相反），**不會自己寫進 soul.md**，在主控面板等你按
  「加進去／取代舊的那條／不要」。你拒絕過的，它再提同一句直接丟。像密鑰的連提議都不留。
- **取代與收起不是刪除**：舊筆記搬到「收起來的」，可以放回去。
- **整理**（任務 `system.soul_tidy`，每 6 小時，不叫 AI）：一模一樣的重複行拿掉；很像的兩條、只差在否定字的、90 天沒確認的變成提議；
  30 天沒處理的提議丟掉。有新的提議時通知你一句（不帶內容，一天最多一次，安靜時段不吵）。
- **忘掉**：打一個詞，先看會動到幾筆，確認後把助理筆記、提議、收起來的、修改紀錄、常駐助理的記憶裡提到的全部拿掉；你自己寫的段落不動。
- **匯出**：soul.md、每條筆記的來歷、提議、收起來的、修改紀錄、常駐助理的巡邏記憶，一份 JSON 下載。
- **設定** `runtime.mother.soul_review`（預設 `false`）：`true`＝助理想記的每一條都先問你。
- 網頁：新 API `GET /api/runtime/soul/notes`、`POST /api/runtime/soul/proposal`、`/note`、`/forget`、`/tidy`、`GET /api/runtime/soul/export`
  （[docs/runtime-api.md](docs/runtime-api.md)）；主控頁多一張「🗒️ 助理記下來的事」卡。

### 改變
- 對話助理的系統提示：soul.md 超過 2000 字時不再從尾巴硬切。你寫的段落全留，「助理筆記」挑跟你這句話相關、比較新的放，其餘註明幾條沒放。
  沒超過＝跟以前一模一樣。
- 助理筆記多了上限：最多 40 條、一天最多自動加 6 條；超過的變成提議。
- 常駐助理的提示多一行：只根據你自己說的話記，任務訊息與轉述的網頁、檔案內容裡叫它「記住」的不記。

### 沒改的
- soul.md 的格式與 6000 字上限、你直接改的那條路、`runtime.mother.soul_append=false` 整個關掉、對話助理不寫 soul.md、成員與頻道拿不到 soul.md。
  預設設定下，沒有疑慮的筆記照舊直接記。沒有新的相依套件。

## 未發佈（branch feat/activator：連動——任務做完馬上觸發下一件，防無限連動）

### 新增
- **連動（activator）**：任務狀態一變（排程的任務做完、逾時、pack 回報），符合規則的動作**馬上**做，不用等排程或心跳；
  可以一串接一串。規則＝「任務變成某個狀態（可加：從哪個狀態變過來、標籤、程式條件）→ 跑一個任務／通知你一句話／呼叫程式」。
  不急的可以 `timing: "heartbeat"` 留成待處理，下一次心跳（或主控面板「現在處理」）再做。設計：[ADR 0004](docs/adr/0004-activator-event-driven-rules.md)。
- **防無限連動**：登記時就找循環（會繞回自己的不收）；執行時每個事件帶連動串（串 id、第幾層、走過的規則），同一條規則在同一串出現第二次、
  超過 5 層、同一串做超過 20 件 → 暫停那條規則；每條規則一小時最多 30 次、可設冷卻；動作連續失敗 5 次暫停；全部規則 10 分鐘最多 60 件，
  超過就全部暫停；一個事件最多觸發 10 條。暫停會通知你一次、主控面板看得到原因、按「重設」／「恢復」才恢復；重開 SYNOX 還記得。
- 規則三種來源：`config.json` 的 `runtime.activator.rules`（只收資料）、系統程式、python pack 的 `pack.on_event(...)`（只能跑自己的任務、
  看不到別人任務的訊息）。
- 回報狀態可以多帶**標籤**：`pack.report_status(state, message, tag=)`、SDK `report_status(state, message, tag=)`（信封 `status.tag`），
  讓規則分得出「哪一件事做完了」。舊工具不帶＝照舊。
- 網頁：`GET /api/runtime/status` 多 `activator`；新 API `activator/rules/<id>/reset`、`activator/resume`、`activator/pending/run`、
  `activator/pending/<id>/dismiss`（[docs/runtime-api.md](docs/runtime-api.md)）。主控頁多一張「🔗 連動」卡。`doctor` 多一行「連動」。
- 例子（測試與示範 pack `tests/fixtures/chain_pack`）：日記圖片做好了 → 馬上問你要不要打卡；問完回報另一個標籤，不會自己觸發自己。

## 未發佈（branch feat/landing-readme：介紹頁、README 對齊現況、工具生態文件）

### 新增
- **介紹頁** `docs/landing/index.html`：單一檔案、雙擊就能看（深淺色跟系統、手機寬度可看）。內容：它是什麼、本機優先（會出門的只有兩條）、
  網頁版畫面（`docs/ui/screenshots/*.png` 轉成 WebP data URI 嵌進去，約 0.5 MB）、三步裝好、安全（確認卡、五關、信任層級、保管箱）、
  工具與 pack、alpha 現況、安裝、接下來（分「做好了等驗證」「還沒有」「提案」）。同一份發佈成 Artifact：
  <https://claude.ai/artifact/SNsSkbcVQm7BU22BBZN3gW>（私人連結）。沒有編任何數字、見證或網址（專案網址照 `synox about` 一樣寫「還沒公開」）。
- **`docs/ecosystem.md`**：使用者怎麼找、裝、更新（同名再裝＝升級、`packs rollback`）、移除工具；作者怎麼做一個工具給人裝、發佈前清單；
  「之後的路」（線上目錄、簽章驗證、檢查更新、評分、一鍵安裝、其他平台安裝器）**全部標為提案**並寫現在為什麼沒有；
  「文件維護清單」：每次發版改了什麼要跟著動哪些文件、教學、介紹頁。

### 文件
- README：對齊目前的狀態（出廠不帶工具、Telegram 擁有者可在網頁配對、bot 步驟可跳過、網頁四頁＋對話封存＋常駐助理入口、
  本機擁有者直接開網頁就登入）；新增「文件與教學」一表，連到介紹頁、`docs/tutorials/telegram/`、`docs/tutorials/discord/`、
  `docs/discord-concepts.md`（教學由另外的分支產生）、`docs/ecosystem.md`。alpha 警告原樣保留。
- `docs/README.md` 索引加介紹頁、教學、ecosystem。

## 未發佈（dev，2026-11-12：合併 debug/setup-python-telegram＋跟進 ClawBot／金流簿）

### Telegram 圖文教學與教學的共用管線（branch `feat/tutorial-telegram`，已合併）
- 新增 [docs/tutorials/telegram/index.html](docs/tutorials/telegram/index.html)：給電腦新手的一步一圖教學——跟 @BotFather 建 bot、拿 token、
  貼進 SYNOX（精靈或網頁設定）、六位數配對、第一則訊息；常見問題（token 格式／401、bot 不回、作廢重發 token、隱私模式、群組、改名與頭像、
  帳號被佔、換電腦）。自足一頁（沒有外部資源、沒有 JavaScript）、亮暗兩色、手機可看；示意圖是手繪的 HTML／CSS 框，都標「示意圖」。
  純文字版 `telegram/README.md`（含「怎麼更新」）；線上版（Artifact）網址與加新教學的規則在 [docs/tutorials/README.md](docs/tutorials/README.md)。
  BotFather 的指令與規則對照 Telegram 官方文件（core.telegram.org/bots/features、/bots/tutorial）。
- 共用管線（Discord 之後只要放 `docs/tutorials/discord/index.html`，不用改程式）：新 `src/synox/tutorials.py`（`path_of`／`names`／`read`／`open_local`）；
  網頁 `GET /tutorials/<名字>/`（公開文件、不用登入、嚴格 CSP：只放行內嵌樣式與 data: 圖）；精靈 token 頁多一顆「看圖文教學」
  （有那個平台的教學才出現，用瀏覽器開本機那份；12 種語言各加一句 `open_tutorial`）；網頁設定「聊天通道」Telegram 那一格多一個連結；
  `synox init` 印本機檔路徑。發佈 zip／安裝程式本來就帶 `docs/`。測試 `tests/test_tutorials.py`。

### Discord 觀念篇與步驟教學（branch `feat/tutorial-discord`，已合併）
- 新增 [docs/discord-concepts.md](docs/discord-concepts.md)：給覺得 Discord 難懂的人——名詞對照（Application／bot user／token／intent／guild／頻道／私訊／身分組／ID）、
  一支 bot 的三種用法（私訊、伺服器、同伺服器不同頻道）、對照到 SYNOX 今天做得到／做不到的表、四種情境的決定表（只有我／私人伺服器／公開頻道／每頻道不同）、
  公開頻道的風險表、**每頻道設定的提案**（`guilds.<g>.channels` 的每一項可寫成物件、收訊時算派生 BotSpec 丟給現有的 `policy.using_bot`；還沒做）、
  查證紀錄（2026-11-12 讀的 docs.discord.com 官方文件，含哪些是官方、哪些是社群共識）。
- 新增 [docs/tutorials/discord/](docs/tutorials/discord/README.md)：`index.html` 單一檔案的逐步教學（建 Application → token → Message Content intent →
  URL Generator → 邀進伺服器／私訊 → 開發者模式與複製 ID → 貼進 SYNOX 的三條路 → 配對的三條路 → 測試 → 頻道與每頻道不同 → 安全 → 疑難排解
  （bot 離線、4014、4004、50001、50013、50007、沒回、429、token 外洩 → Reset Token）→ 還沒驗證的事）；步驟圖是 HTML／CSS 畫的**示意圖**（不是截圖），
  深淺色、手機可看；`README.md` 是同一份的純文字版＋更新方式。同一個檔案也發佈成 Artifact（網址在 README 頂端）。
- `docs/discord.md` 頂端加一節「先看這些」連到上面兩份。
- 查證時發現兩件要注意的：官方說 **User Install 的 app 只能用 slash 指令**（SYNOX 沒有 slash 指令，所以 `docs/discord.md` 第 1 節把 User Install 列為
  讓 bot 收私訊的選項之一，**未驗證**；教學一律走「邀進伺服器」）；特權 intent 的審核門檻官方現在是「1 萬個不重複使用者」（不是舊的 100 個伺服器）。

### 心跳：失敗狀態沒變就不再叫 AI（branch `feat/cb1-heartbeat`，還沒合併）
- 有任務一直壞著時，心跳不再每次都叫 AI（以前一天最多多叫 30 幾次）：失敗只看「哪個任務＋去掉數字的原因」，沒變就記一句「失敗狀態沒有變化」；
  同一批失敗只通知一次（新的壞了、原因變了、恢復了才再來）；安靜時段擋下的，時段過了再問一次；指紋存在 `state.json`（只有雜湊），重開後接著用。
  每日上限、安靜時段、手動一定叫 AI 都照舊，設定沒有新欄位。說明：[ADR 0001 §3「2026-11 修訂」](docs/adr/0001-runtime-loop-heartbeat-mother-session.md)。

### 對話助理評測集與離線重放（branch `feat/cb2-eval`，還沒合併）
- 新增 30 題日常助理任務（記事、改寫與摘要、查資料、行程、該追問／不該追問、拒絕、提示注入、多回合記憶、工具鏈；
  tune 20 題、holdout 10 題），每題有自動判定的硬檢查，品質項目只留給人看的欄位。題目全部是虛構情境與範例網域。
- 「某個模型對每一題的回覆」錄成檔案就能**離線重放**：照劇本回話的假 AI 接在**真的**對話迴圈上（工具清單、參數驗證、
  確認卡、步數上限、對話記憶都是真的），工具一律是假的；劇本跟題目對不上時標 `replay_mismatch`，不硬算。
- 報表：每題 pass／fail 與沒過的檢查、每一類通過率、tune／holdout 分開的總分、簡體字統計（只統計）；文字＋JSON、每次一字不差。
- 指令：`scripts/eval_assistant.py`；怎麼新增題目：[evals/assistant/README.md](evals/assistant/README.md)。
  不呼叫任何真的 AI、沒有「真跑」模式（要先決定花費上限，見 README 最後一節）；對話助理本身沒有改。
- `evals/` 是開發用的，`scripts/make_zip.py` 不打包它。

### 用 Docker 開發與執行（branch `feat/docker-support`，還沒合併）
- 新增開發容器 `.devcontainer/devcontainer.json`（Python 3.11、裝相依、pytest；網頁埠只轉到本機 localhost）與執行用映像檔：
  `Dockerfile`（兩段式、非 root、`HEALTHCHECK` 不經對外的埠）、`.dockerignore`（白名單）、`docker-compose.yml`（具名 volume、
  埠只發佈到宿主 127.0.0.1、唯讀根目錄、tmpfs、cap_drop ALL、資源上限）、`.env.example`、`docker/healthcheck.py`。說明：[docs/docker.md](docs/docker.md)。
- 網頁介面：只有在 SYNOX 的容器裡（`SYNOX_IN_CONTAINER=1`＋容器證據）且 `SYNOX_WEB_BIND=0.0.0.0` 才綁容器自己的 0.0.0.0；
  預設行為不變（127.0.0.1），其他值一律拒、網頁不開（`web/server.py` 的 `bind_host`，`tests/test_web_bind.py`）。
- 映像檔**還沒實際建置、容器還沒實際跑過**：驗證清單在 docs/docker.md「驗證」。

### 呈現層：與通道無關的內容區塊（branch `feat/cb3-blocks`，還沒合併）
- 新增 `synox.present`（[docs/presentation.md](docs/presentation.md)）：AI 回覆的 Markdown → 區塊 → Telegram HTML（4096 切割）／Discord（2000 切割、圍欄不斷）／網頁區塊，表格依寬度降級；設定 `"presentation": {"enabled": false}` **預設關**，關著時送出的東西跟以前完全一樣。

### 工具健康：失敗信封 v1 與隔離清單（branch `feat/cb4-health`，還沒合併）
- 工具失敗時有固定格式（類別碼、能不能重試、補救建議；截長、遮密鑰），AI 收到一行 `FAIL …`；同一個根因連續失敗的工具暫時不給 AI、冷卻後用 pack.json 的
  `health.check` 重新檢查（不叫 AI），`doctor` 與網頁工具頁看得到狀態，擁有者可以重新檢查、解除隔離。SDK 0.2.1 加 `fail()`／`ToolFailure`
  （舊的 `ToolError` 照舊；沒處理的例外改叫 `unclassified`）。不做自動修復。說明：[docs/tool-health.md](docs/tool-health.md)。

### 網頁的開場動畫與微動畫（branch `feat/ui-splash`，還沒合併）
- 打開網頁時「S 寶寶」掉下來、眨眼、說嗨、翻面變成 S 標誌、SYNOX 字樣跳出來（約 1.7 秒；點一下或按任何鍵略過；同一個分頁只播一次）；
  頁面切換、卡片進場、按鈕、對話泡泡、狀態點、背景淡光與小光點的微動畫。版面沒動；系統開了「減少動態效果」→ 開場不播、動畫全關。
  新檔 `static/splash.js`／`splash.css`（`app.html` 只多兩行 include；CSP、server.py 沒改）。手法取自 ISDPCS，說明與時間表：
  [docs/ui/motion-notes.md](docs/ui/motion-notes.md)。預覽多了「重播開場」（`?splash=1`）。要你決定的：[QuestionToUser.md](QuestionToUser.md) QM1～QM3。
### 終端機的 SYNOX 門面：歡迎畫面、`synox open`（branch `feat/cli-brand`，還沒合併）
- 新增 `synox open`：在這台電腦上打開網頁介面（好記的名字；行為跟 `web-login` 一樣，`web-login`、`Open-SYNOX.bat` 照舊）。
- 新增歡迎畫面（`src/synox/brand.py`）：`synox`（沒參數）、`run`、`open`、`wizard`、`doctor`、`about` 開頭印貓頭鷹＋SYNOX logo、
  「Welcome to SYNOX」、版本、照時段的問候（照 ISDPCS 歡迎頁）、下一步提示。只在互動終端機印；管線／重導向／`CI`／`--quiet`／
  `SYNOX_NO_BANNER=1` 不印（既有指令被程式讀時輸出不變），`TERM=dumb` 一行純文字，`NO_COLOR` 不上色，Windows 舊主控台（cp950）
  與 `SYNOX_ASCII=1` 用純 ASCII logo。預覽：[docs/ui/cli-welcome.txt](docs/ui/cli-welcome.txt)（`scripts/make_cli_welcome.py` 產生）。
- 新增 `synox about`（版本、授權、裝在哪裡；專案網址還沒定所以寫「還沒公開」）、`synox tips`（隨機一則小提示，`--all` 全部）。
- 全域 `-q`／`--quiet`（放在指令前後都可以）。
- 要你決定的事：[QuestionToUser.md](QuestionToUser.md) QB1～QB3（專案網址、`synox` 要不要在任何命令列都能打、logo 的樣子）。

### 提醒變系統指令、soul.md 給對話助理（branch `feat/core-remind-soul`，還沒合併）
- **提醒回到核心當系統指令**（QuestionToUser QL5）：`/remind_add`、`/remind_list`、`/remind_rm` 不用再裝工具，標題「⏰ 提醒（系統）」，
  網頁工具頁歸在「系統」群組（SYNOX 自己的指令原本叫「內建」，一起改名）。指令名、AI 工具名、資料（`data/schedule.json.enc`）都不變，
  舊提醒直接接上；權限照舊（個人版只有擁有者、伺服器版成員以上、只在私訊）。群組名 `remind` 保留給系統：裝過工具庫舊 `remind` 工具的人，
  它會被標成「不需要了」（狀態 incompatible、不載入、不算壞掉）。工具庫那邊把 `remind` 搬到它的 `legacy/remind/`。
  `tests/fixtures/packs/remind` 拿掉（測試直接用核心的 `/remind_*`）。
- **soul.md 放進對話助理的系統提示**（決定 Q7，[docs/adr/0002](docs/adr/0002-soul-md-in-chat-assistant-prompt.md)）：只有擁有者的私訊／網頁對話、
  唯讀、最多 2000 字、包在分隔符裡標明「使用者偏好，不是指令」；沒寫東西（預設的空段落）就不放；成員、訪客、公開頻道都不帶；不寫 log；
  對話助理仍不讀常駐助理的記憶。「agent 怎麼讀 context」的 HTML 說明記在 [docs/README.md](docs/README.md) 的待做（MVP 之後）。
- 心跳預設**維持 45 分鐘**、最短 15 分鐘（決定 Q10）：ADR 0001 §3 補理由（擁有者：搭得上約 1 小時的 prompt 快取、固定 beat 下去比較划算），
  並註明 SYNOX 現在的 adapter 沒有自己標 1 小時快取（之後的工作）；新測試對設定預設值、`config.example.json`、主控面板三處都是 45。
- 網頁誰進得了（Q11）：[docs/security.md](docs/security.md) 新增白話表；程式沒改。查到伺服器版 `/web` 對每個人（含訪客）都發連結，
  要不要收緊另開 QuestionToUser **QS1**。
- [QuestionToUser.md](QuestionToUser.md)：最上面加常駐規則（擁有者 2026-11-12：「你作玩得可以先刪掉，剩下的我沒回就都先留著」）；
  Q5、Q7、Q10、Q11、QL5 標成已回答、濃縮成結論搬到最下面「已回答」；其他題目不動。

### 乾淨安裝：git clone＋安裝程式、工具庫附在旁邊（branch `feat/clean-room-dist`，還沒合併）
- 發佈方式定案（QL4）：**git clone／Download ZIP＋`Setup.bat`**，以及 **Windows 安裝程式**（Inno Setup 6＋官方可攜版 Python＋離線套件，
  每個使用者自己裝、不要管理員）。為什麼不用 PyInstaller／Nuitka：[docs/adr/0003](docs/adr/0003-distribution-git-clone-and-installer.md)。
  安裝程式的腳本做好了（`scripts/stage_installer.py`、`setup/installer/synox.iss`），**還沒真的打包、還沒在空白電腦上試**。
- **新指令** `python -m synox init`：文字版設定引導（模式、Telegram、AI、工具庫位置、挑工具），`--non-interactive`、`--dry-run`；
  `python -m synox tools list｜install <名字或組合>`：從工具庫挑來裝（先對 sha256，再走原本的五關；不自動全裝）。
- **工具庫預設位置**：`config.json` 沒寫 `packs.library` 時，SYNOX 找自己資料夾裡的 `tools\`（相對位置）；`make_zip.py --tools` 會把它放進 zip。
- **Setup.bat**：有 `wheelhouse\` 就完全離線裝、有 `requirements.lock` 就照鎖定版本裝（`scripts/lock_deps.py` 產生）；SYNOX 資料夾自己帶的
  `runtime\python` 優先；開不了視窗（沒有 tkinter）就在同一個視窗跑文字版 init。setup 訊息 12 種語言各多兩句。
- **乾淨安裝審計**：SYNOX 資料夾的判斷不再假設原始碼版面（`SYNOX_HOME` → 原始碼 → 目前資料夾，doctor 會說）；交接單裡這台電腦的路徑拿掉；
  `vendor_sdk.py` 可以用 `--sdk`／`ISDTELEKIT_SDK`；精靈存設定時 `env:名字` 不再被當成金鑰；doctor 不再把 `max_tokens` 當密鑰遮掉。
  新的 `scripts/clean_room_check.py`：在暫存資料夾、清掉這台的環境變數／PATH／使用者資料夾後跑 doctor、init、tools、pytest 子集。
- SYNOX_Libs（另一個 repo）：`scripts/_synox.py` 找 SYNOX 改成 `SYNOX_HOME` → 跑腳本的 Python 裝的那份 → 後備 `../SYNOX`；README 寫清楚安裝流程。
- 給擁有者：空白電腦實測清單 [docs/handoff/clean-machine-test.md](docs/handoff/clean-machine-test.md)；要你決定的事 [QuestionToUser.md](QuestionToUser.md) QD1～QD4。

### 常駐助理、心跳、runtime loop（branch `feat/runtime-heartbeat`，還沒合併）
- 新增 `src/synox/runtime/`：常駐的排程迴圈（每個任務自己的執行緒、逾時、失敗退避、連續 5 次失敗通知一次）、
  心跳（預設每 45 分鐘、下限 15 分鐘、沒有新狀況不叫 AI、安靜時段、每天通知／叫 AI 的上限）、常駐助理（母 session：沒有工具、
  自己的記憶存保管箱、可清空）、soul.md（保管箱、你可改可重設、助理只能照規則追加、有稽核）。原本的提醒排程改成 runtime 的一個任務。
  設計：[docs/adr/0001](docs/adr/0001-runtime-loop-heartbeat-mother-session.md)。
- 網頁 API `/api/runtime/...`（只給擁有者；合約 [docs/runtime-api.md](docs/runtime-api.md)）；`PUT /api/runtime/soul` 是第一個收 PUT 的 API。
- 工具回報狀態：SDK `report_status()`／`peer_status()`（信封多一個選填的 `status`、環境變數 `SYNOX_PEER_STATUS` 只有狀態與時間）；
  python pack `pack.report_status()`／`pack.peer_status()`。舊工具不受影響。
- `config.json` 多 `runtime` 一塊（預設值與檢查在 `runtime/settings.py`；精靈寫新設定時帶上）；`doctor` 列出心跳開關、間隔、上一次。
- 等擁有者決定：[QuestionToUser.md](QuestionToUser.md) Q6（助理自動記 soul.md）、Q7（soul.md 給對話助理）、Q8（助理讀最近對話）。
### 工具搬到 SYNOX_Libs、主程式出廠是空的（branch `feat/libs-extraction`）
- **移除（BREAKING）**：出廠的 `money`、`notes`、`remind` 下架，正本搬到新專案 **SYNOX_Libs（工具庫）**；`packs/` 只剩說明（安裝的落點，
  內容不進 git）。從舊版更新的人：`/help` 裡這三個會不見，**資料沒動**，從工具庫裝回同名工具就接著用。說明與怎麼救回：
  [legacy/builtin-packs.md](legacy/builtin-packs.md)。`loader.BUNDLED` 只剩 4 個 connector（connector 要不要也搬：[QuestionToUser.md](QuestionToUser.md) QL1；後來也搬了，見下一段）。
- **新增 `requires.sdk`**：工具在 pack.json 宣告照哪一版 SDK 寫（例如 `">=0.2,<0.3"`）；安裝、載入、doctor 都檢查，不合＝不裝、不載入、說原因。
  `SDK_VERSION` 0.1.0 → **0.2.0**；`synox-sdk init` 自動寫；examples 都補上。`sdk/` 可以 `pip install <SYNOX>/sdk`（`synox-sdk` 套件）。
- **新增「還沒裝任何工具」提示**（`src/synox/packs/library.py`）：`/start`、`/help`（只給擁有者）、`doctor`（「• 工具：…」一行）、精靈完成頁、
  網頁 `/api/tools`／`/api/settings` 的 `library` 欄位（工具頁、設定頁要不要顯示由前端決定，這次沒改 `static/`）。
  工具庫的位置寫在 `config.json` 的 `packs.library`（資料夾或網址；不寫死路徑），`doctor` 會檢查資料夾在不在。
- 測試：`tests/fixtures/packs/` 是三個工具下架前的凍結複本（host 測試用）；conftest 測試期間把 `loader.PACK_DIRS` 換成它＋`connectors/`。
  新的 `tests/test_empty_host.py`（空 host、只有 connector、什麼都沒有、從 `.synoxpack` 裝進空 host；設 `SYNOX_LIBS` 會多跑「工具庫每個工具都裝得進來」）、
  `tests/test_sdk_requires.py`。記帳、筆記本身的測試搬到 SYNOX_Libs。
- 要你決定的事：[QuestionToUser.md](QuestionToUser.md) QL1～QL5（connector 要不要也搬、舊使用者怎麼接回、SYNOXPacks 怎麼處理、工具壓縮檔怎麼發、提醒要不要獨立）。

### connector 也搬到 SYNOX_Libs、工具的穩定度標示（branch `feat/connectors-to-libs`）
- **移除（BREAKING）**：`connectors/` 的 4 個（notion、todoist、google-calendar、apple-reminders）連同測試搬到 SYNOX_Libs（QL1 擁有者回「當然要」）；
  `connectors/` 只剩 README、loader 只掃 `packs/`、`loader.BUNDLED` 清空——**主程式出廠真的一個工具都沒有**。pack 名字沒變，
  從舊版更新的人裝回同名工具，保管箱裡的 token／帳號照用。說明與怎麼救回：[legacy/connectors.md](legacy/connectors.md)。
- **新增 pack.json `stage`（穩定度）**：`test`｜`alpha`｜`beta`｜`stable`，沒寫＝`alpha`；安裝時寫錯＝拒裝。顯示「符號＋字」
  （🔧 test、🧪 alpha、🚧 beta、⭐ stable）：`/help` 那一頁的標題、網頁 `/api/tools`（`stage`／`stage_label`／`stage_text`，工具頁標題旁一個小徽章）、
  安裝報告（「穩定度」一行；不是 stable 的在提醒清單多一句意思）、`doctor` 每個 pack 那一行。工具庫的工具目前全部標 alpha。
- `scripts/smoke_real.py`：先找這台裝好的工具，沒裝就讀工具庫的原始碼（`SYNOX_LIBS`）；`connect` 找不到工具時提示先從工具庫裝。
- 測試：要讀工具庫的（smoke_real 的四個服務、connector 不被 SYNOX 管 secret、工具庫每個工具裝進空 host）設 `SYNOX_LIBS`，找不到就跳過；
  新的 `tests/test_stage.py`。

### 合併進來的（安裝流程的真機除錯）
- 從 `origin/debug/setup-python-telegram` 合併（`--no-ff`，沒有衝突）：安裝程式先問語言（12 種）、`Uninstall.bat`、bot 步驟可以跳過
  （只開網頁版）、Discord 當第二個通道、本機擁有者在瀏覽器打 `http://127.0.0.1:<port>/` 就登入、`web-login`／`Open-SYNOX.bat`、
  Windows 上網頁獨佔綁定 port、開機自動啟動不跳瀏覽器、網頁設定頁的「聊天通道」卡。每一條的細節與還沒拍板的事都在
  [docs/debug-notes.md](docs/debug-notes.md)（這裡不重抄）。

### 網頁介面重新設計（branch `feat/ui-redesign`，還沒合併）
- `src/synox/web/static/app.html` 重畫：左側欄＋對話紀錄（手機改成底部分頁）、一套 CSS token（淺色取記帳專案、深色取 ISDPCS）、
  深淺色跟隨系統、狀態徽章（顏色＋文字＋形狀）、手機 44px 按鈕與 16px 輸入。登入確認頁、錯誤頁（`server.py` 的 `PAGE_CSS`）同一套顏色。
  API、CSRF、登入、CSP 都沒動。說明與前後對照：[docs/ui/redesign-notes.md](docs/ui/redesign-notes.md)。
- 新增 `scripts/make_ui_preview.py`：產生 `docs/ui/preview*.html`（真的 app.html＋假資料，雙擊就能看）；`tests/test_ui_preview.py` 檢查預覽有沒有同步。
- 主色與深淺色切換鈕、安裝精靈要不要跟著換：[QuestionToUser.md](QuestionToUser.md) Q4、Q5。

### 網頁「主控」頁（branch `feat/control-panel-ui`，還沒合併）
- 側欄多一個「主控」（只有擁有者看得到；成員打 `#control` 會回到對話頁）：常駐助理（母 session）的狀態、heartbeat 開關與間隔（預設 45 分鐘）、
  「現在執行一次」、排定任務的狀態與日誌、偏好檔 soul.md 的編輯、清空記憶（二次確認，寫清楚會清掉／不會動什麼）。
  前端在 `src/synox/web/static/control.js`／`control.css`，`server.app_html` 把它們塞進 app.html（仍是一頁、同一個 CSP nonce）。
  呼叫的是 `/api/runtime/*`（後端另一個分支做，這裡沒有實作）。測試：`tests/test_control_panel.py`＋`tests/js/test_control.js`（node、假 fetch）。
  說明見 [docs/ui/redesign-notes.md](docs/ui/redesign-notes.md)「主控」；要你決定的在 [QuestionToUser.md](QuestionToUser.md) Q6、Q7。
### 網頁「工具」頁：群組＋分頁＋表單（branch `feat/tools-page-groups`，還沒合併）
- 工具頁重做：頁內左邊是群組，群組裡的工具用分頁隔開；每個工具有說明、指令卡（effect 徽章）、照宣告產生的參數表單
  （必填、下拉、預設值、說明）、「會送出：…」預覽、執行（危險的先在畫面上問一次；仍經同一個 dispatcher）。
  使用者可以新增／改名／刪除群組、排序、把工具移到別的群組，存在每個人自己的偏好（`data/web_prefs/<id>.json.enc`，
  擁有者與成員各自一份，不寫進 pack 資料夾）。新 API：`POST /api/tools/layout`；`GET /api/tools` 多了 `layout` 與每個欄位的表單資訊。
  程式在 `src/synox/web/toolpage.py`、`static/tools.js`、`static/tools.css`。
- pack.json 新欄位 `category`（網頁工具頁建議的群組，沒寫＝「未分類」；使用者排的優先）、`fields[].help`（表單上的說明）。
  安裝時多檢查說明欄位的型別（`summary`／`ask`／`help` 一行字、`required` 布林、`default` 合 kind）；SKILL.md 沒有 frontmatter、
  指令沒 summary、欄位沒 ask 只提醒不擋（安裝報告、`synox-sdk check`）。`@tool` 參數的預設值會寫成 `default`。
  說明：[docs/tools.md](docs/tools.md)「網頁工具頁」、[docs/pack-format.md](docs/pack-format.md)。

### AI 用量與花費小儀表板、新對話不再記得前面、Discord 網頁配對
- **用量與花費**（設定頁新的一張卡，`GET /api/usage?period=hour|day|week|month`，只給擁有者）：選「每小時／每天／每週／每月」，看這段期間的花費、呼叫次數、token，
  長條圖（可切成表格）。花費：Claude Code 回報的 `total_cost_usd`（訂閱制下是照 API 價換算的約數）優先，沒有就照 `llm.price_in／price_out` 算；
  **個人版以前不記花費（一律 0）**，現在也記；舊紀錄沒花費的用 token 估、標「約」。`llm_usage.json` 多了 `hours`（只留最近 14 天，`days` 永遠留）。
  程式：`agent/usage_report.py`。常駐助理巡的花費也記進同一本帳。
- **修正：網頁開「新對話」AI 還記得前面**。原因：每一段網頁對話送給 AI 的 chat_id 都是你自己的 id，記憶的鍵是 chat_id，所以整個人共用一份。
  現在記憶多一個「對話串」（`WebChannel.thread`＝網頁的 chat id）：每段對話各自一份、`/ai_reset` 只清這一段、確認卡的結果記進按卡的那一段；
  Telegram／Discord 私訊照舊（整個人一份）。常駐助理巡的時候看「最近有動靜的那一段」（`AgentLoop.latest_history`）。重開 SYNOX 仍會清空（記憶在記憶體）。
- **Discord 擁有者配對搬到網頁**（設定 → 聊天通道 → Discord →「配對我的 Discord 帳號」）：產生六位數字，私訊 bot 傳它，**正在跑的 SYNOX 直接接上**
  （不用開終端機、不用先關 SYNOX）；或直接貼 Discord 使用者 ID，馬上配好。碼 15 分鐘有效、用掉就作廢、猜錯 10 次作廢（`discord/pairing.py`）。
  bot 對還沒配對的人回的那句也改成指到網頁。三種配對（指令、網頁碼、貼 ID）共用 `discord.bind_owner`。
- 聊天通道卡片標明「目前只能一對一私訊」：加進 Telegram 群組、Discord 頻道／社群沒有用（指令與 AI 在群組、頻道都被擋）；邀請連結的說法改成「為了能私訊它」。
- Telegram 擁有者配對在網頁怎麼做（會換擁有者 id、牽涉資料搬遷）：[QuestionToUser.md](QuestionToUser.md) Q14。

### 對話可以封存、再到另一頁徹底刪除
- 側欄每段對話多一顆「封存」（滑鼠移上去才出現；手機一直顯示）：封存的對話從側欄消失，但**不會被自動清掉**（不算在 30 段上限裡），也不能再傳訊息。
  側欄下面「🗄 已封存的對話」（`#archive`）可以**還原**，或**徹底刪除**（要按兩次；只有封存過的才能刪，刪了就沒了，AI 對那段的記憶也一起忘掉）。
  固定的兩段（工具頁、常駐助理）不能封存。API：`POST /api/chat/<id>/archive|restore|delete`、`GET /api/chats/archived`。程式：`web/chats.py`。

### Telegram 擁有者也能在網頁配對（跟 Discord 一樣）
- 原因：只用網頁／Discord 安裝的人，擁有者的內部 id 是保留的 10^15，Telegram 傳訊息進來是他真正的 Telegram 編號，被當成陌生人（guest）；
  陌生人傳自由文字只會一直收到「我只看得懂指令，打 /help」——看起來像鬼打牆。
- 做法（`telegram_link.py`，**不改 SDK、不換擁有者 id、不搬資料**）：`identities.json` 記「telegram:<編號> ＝ 擁有者」；進來的訊息對得上就換成擁有者的內部 id，
  回覆時 BotAPI 物件裡「送給某個 chat_id」的方法把擁有者的內部 id 翻回 Telegram 編號。設定 → 聊天通道 → Telegram →「配對我的 Telegram 帳號」：
  網頁顯示六位數字，在 Telegram 私訊 bot 傳它（15 分鐘、用掉即作廢、猜錯 10 次作廢），或直接貼 Telegram 編號。要先存好 token 並重開一次。
- 還沒配對時，這種安裝的 Telegram 一律不收訊息（回一句「還沒配對」，每人一次），不登記陌生人。**擁有者本來就是 Telegram 帳號的安裝完全不經過這一層。**
- 網頁的配對區改成 Discord、Telegram 共用同一段程式（`makePairing`）。這等於照 Q14 的建議 B 做了（用 SYNOX 這邊包一層，沒動 vendor），請確認。

### 常駐助理的獨立聊天入口
- 側欄固定多一個「🫀 常駐助理」（只給擁有者；主控頁的常駐助理那格也有「跟它聊天」連結）：直接跟常駐助理（母 session）聊天，沒有工具、純文字。
  這個聊天的紀錄**只在記憶體**（最多 12 輪，重開 SYNOX 就清空），跟巡邏用的保管箱記憶（主控頁清）分開，只讀最近 5 筆巡邏摘要當背景。
  程式：`MotherSession.chat()`／`chat_reset()`、`web/chats.py` 的 `MOTHER_CHAT`。

### 設定頁選好 AI 來源就立刻能用
- 設定頁選 Claude Code 時可以挑模型（預設／Sonnet／Opus／Haiku）；「存起來」之後對話助理與常駐助理**馬上換上、不用重開**
  （`agent.set_adapter`）。接不上時設定仍會存，並說原因。「測一下」遇到沒登入會說怎麼登入。
- 主控頁：還沒設定 AI 來源時，常駐助理那格說「到設定選好並存起來，這裡馬上就會開始跑」；`/api/runtime/status` 的 `mother` 多 `ai` 欄位。
- 已知限制：啟動時沒有 AI，Discord 頻道 AI 要重開才會出現。

### 聊天通道改了要重開：說得更明顯
- 設定頁的「聊天通道」卡：只要 Telegram／Discord 有改過、還沒重開，頂端出現黃色提示「要重新啟動 SYNOX 才會生效（Stop.bat → 桌面捷徑），在那之前 bot 不會上線」；
  存 Discord token 的訊息也在最前面先講一次（原本埋在第 ③ 步）。

### 對話頁桌面版改滿版
- 寬度超過 760px 時，對話區佔滿側欄以外的整個區域（原本是置中、最寬 980px 的浮動卡片，螢幕一大就飄在中間）。手機版沒動。
  `docs/ui/screenshots/desktop-chat-*.png` 還是舊的卡片版，沒有重拍。

### 找不到 Claude Code 時給安裝點
- 網頁設定頁「測一下」回「找不到 claude」時，顯示 Windows／Linux／macOS 的安裝指令（可複製，不代跑）與官方說明連結；
  安裝精靈與網頁共用的 `CLAUDE_DOWNLOAD_URL` 改成官方安裝說明頁（原本的行銷頁會讓人裝成 Claude Desktop）。
- `find_claude()` 除了 PATH，也找 `~/.local/bin/claude(.exe)`（原生安裝程式的位置，不一定在 PATH 上）。
  背景與「VS Code 能用不代表 SYNOX 找得到」：[docs/claude-code-cli.md](docs/claude-code-cli.md)。

### 修正
- 兩個無效的跳脫字元（`src/synox/wizard/shortcuts.py` 的說明、`tests/test_wizard.py` 的位元組字串）改成 raw 字串，內容不變；
  Python 3.12 起會是 SyntaxWarning。

### 測試
- `tests/fixtures/moneybook_pack/` 對齊金流簿 synox-pack 0.17.0（補 `commands[].positional`）；新測試 `/moneybook 120 便當` 照位置填 amount、desc。

### 跟進外部專案（只讀、沒改對方）
- ClawBot（MyFirstTelegramClawBot）11-10～11-12 的更新查過：通用的兩件（收訊不互等、429 短等重送）在 SDK 那一層，寫成
  [docs/handoffs/2026-11-12-isdtelekit-poller-lanes-and-429.md](docs/handoffs/2026-11-12-isdtelekit-poller-lanes-and-429.md)；
  「AI 寫行事曆先確認」「確認卡編號」會改產品行為，寫進 [QuestionToUser.md](QuestionToUser.md)。
  ClawBot 的「工具呼叫前寫的答案沒送出」不影響 SYNOX（`claude -p` 不給工具，一輪只有一段文字）。
- 金流簿（記帳專案）0.18.x：SYNOX 的安裝檢查唯讀跑過對方現在的 pack，沒有問題；新指令要對方的 synox-pack 跟上，寫成
  [docs/handoffs/2026-11-12-moneybook-synox-pack-0.18.md](docs/handoffs/2026-11-12-moneybook-synox-pack-0.18.md)。

## 0.2.0

版本從 0.1.0 升到 0.2.0：pack 格式多了 surfaces／data／auth.fields／mcp／runtime auto／schema_tools 等欄位，SDK 產生的 pack 寫 `requires.synox: ">=0.2"`，舊版 SYNOX 會明說要先更新、不會載入。

## 未發佈（branch feat/isolation：容器隔離 S0–S2，只組指令、還沒真機驗證）

擁有者 2026-11-10 的決定：作者「建議提供」容器（不強制）；伺服器版第三方／T2 pack 選了容器才開給成員；Linux 優先 rootless podman、
也支援 Docker；這台開發機不跑任何容器／VM（全部用假後端），真機驗證寫成 `docs/handoff/container-verification.md`。
調查與做法：`docs/discussions/2026-11-10-isolation-howto.md`。

### 新增
- **pack.json `runtime.container`**（kind=cli、mcp stdio；`packs/container.py`）：`image` 一定帶 `@sha256:` digest（白名單 registry、
  不收 localhost／IP／網址）或 pack 裡的 `dockerfile`＋帶 digest 的 `base`；`network` 要跟 capabilities 一致；`resources` 只能調低；
  `mounts` 只能改容器裡的路徑；`user` 不能是 root；`privileged`、`cap_add`、`devices`、`volumes`、`network_mode`、`args`… 一律拒（第 1 關）。
  第 2 關掃 Dockerfile（單一 FROM＝base、ADD 網址、RUN --network、COPY --from 沒 digest、ONBUILD 拒；RUN 下載東西列出來）。
- **容器後端 `ContainerSandbox`**（podman／docker；`src/synox/sandbox.py`）：只組 `run --rm -i --pull=never --network none --read-only
  --tmpfs /tmp:noexec --cap-drop ALL --security-opt no-new-privileges --pids-limit --memory --memory-swap`、podman `--userns=keep-id`／
  docker `--user`、只掛 pack（唯讀）與那一格資料夾、`--env 名字`（值不進 argv）。`policy.sandbox.engine`：`auto`（podman → docker）｜
  `podman`｜`docker`，只用 which 偵測。容器裡的路徑：`{pack_dir}`→`/pack`、`{user_data_dir}`→`/data/user`、`{python}`→`python3`。
  kind=cli 與 mcp stdio 都走同一條（`sandbox.box_for`）。
- **安裝報告「🧱 執行環境」**（終端機、網頁）：這台的引擎、pack 提供的容器、選「用容器／不用」；`install --runtime container|host`、
  `packs lock --runtime`、`packs runtime <name> container|host`；記進 packs.lock 的 `runtime`（跟 trust 並列）。
  升級：容器 → 不用、network false → true、映像換了＝紅字。
- **伺服器版**：第三方／T2 的 cli、mcp stdio pack 選了容器、引擎找得到 → 算真隔離、給成員；找不到引擎 → 照舊只給擁有者，原因寫在
  doctor／packs status。doctor 多一行「容器引擎」（只看 PATH，不執行）。

### 還沒做
- SYNOX 自己拉映像／build（S3）、MCP 長駐容器的收尾（S4）、installer 偵測（S6）、VM 後端（S7）。容器後端沒在真機跑過。

## 未發佈（branch feat/fix-connect：真機測試前的兩個小修）

### 修正
- **Notion：`python -m synox connect notion` 設的 token `/notion` 讀不到**。connect 存在保管箱的 `notion.auth`，
  `/notion` 只讀 `/notion_token` 存的 `notion`。現在兩份都認：connect 存的優先，沒有再讀 `/notion_token` 存的（舊使用者不受影響）；
  `/notion_token` 存新的時清掉 connect 那份（最後設的算數）；`/notion_logout` 兩份都清；`/notion_status` 說用的是哪一份（只給結尾 4 碼）。
  `scripts/smoke_real.py` 改用同一套讀法，不再把 connect 存的當成錯誤。
  其他內建 connector 查過：Apple 提醒事項本來就讀 `auth`（一致）；Todoist、Google 日曆的 `auth.fields` 是純字串，
  connect 不收（會說「沒有 auth.fields」），只能用 `/todoist_token`、`/gcal_setup`，沒有兩份不一致的問題。

### 新增
- **`python -m synox discord token --clear [--bot 名字]`**：從保管箱刪掉那個 bot 的 token（以前存了就刪不掉）。
  只刪這台電腦存的那份，會提醒到 Developer Portal 按 Reset Token 才能真正作廢舊 token；config.json 還指著它時也會說。
  本來就沒有＝說一聲、不動檔案。保管箱多一個 `Vault.delete_secret`。docs/discord.md、交接文件跟著改。

## 未發佈（branch feat/fix-round3：獨立安全驗證審查 C 的後半段，C5～C8）

### 變更（安全）
- **#C5 第 2 關掃描補強（改善項；仍是提醒不是門）**：審查 C 找到 24 個一行就零 finding 的寫法，現在：
  - 名單補上底線私有模組與平台別名：`nt`、`posix`、`_winapi`、`_posixsubprocess`、`webbrowser`、`ProcessPoolExecutor`（subprocess）；
    `_socket`、`_ssl`、`pip._vendor.requests`／`urllib3`（network）；`_ctypes`、`_pickle`、`pickle`、`shelve`、`_imp`、`pkgutil`、
    `logging.config`、`runpy`、`zipimport`、`code`、`codeop`、`marshal`、`ctypes`、`pip`（exec）。
  - `from os／sys／builtins／shutil… import *`（和上面任何一個模組）→ exec。
  - 連網也看呼叫：`asyncio.open_connection`／`start_server`、`loop.create_connection(…)`、`socket.socket(…)`、`urllib.request.urlopen(…)`…
  - 看不出對象的 `.eval／.exec／.compile／.loads／.LoadLibrary／.CreateProcess／.fork_exec／.subprocess_exec／.run_path／.resolve_name(…)` → exec；
    `from 某套件 import eval`（不是標準函式庫）在 import 那一行和呼叫那一行都記（`from re import compile` 不算）。
  - import 一個不在標準函式庫、不在 pack 裡、`requires.pip` 也沒宣告的模組 → exec（「來源不明的模組」；常見的 pip 名≠import 名
    例如 PyYAML→yaml 有對照表）；改 `sys.path`／`sys.meta_path` → exec。
  - 只用字面字拆開再組回來的名字（`"sys"+"tem"`、`"".join(…)`、`"%s" %`、`format`、`[::-1]`、`chr()`）是開程式／dunder 名，
    或 `format` 的樣板是組出來的又取屬性 → exec。
- **#C6 zip 路徑**：太深的路徑以前在 Windows 丟原生 `FileNotFoundError`、網頁變成 500；現在一段最多 100 字、整條最多 160 字、
  解壓縮的任何 OSError 都變成一句人話。檔名有雙向文字控制字元（U+202A–U+202E、U+2066–U+2069）或零寬字元（U+200B–U+200D、U+FEFF）＝拒
  （`‮yp.a` 在報告上會顯示成 `a.py`）。
- **#C7 pip 設定檔**：`--isolated` 只跳過使用者的 pip 設定檔，全機與 venv 裡的 `pip.ini` 照讀；建環境的子程序加
  `PIP_CONFIG_FILE=os.devnull`（pip 自己定義的「一個設定檔都不讀」）。不用 SYNOX 建的空檔：空檔只換掉環境變數那一層。
- **#C8 npm 來源**：`package-lock.json` 的 `resolved` 只收 `https://registry.npmjs.org/`；`http://`、`file:`、`git+…`、別的 registry、
  相對路徑＝安裝報告紅字、拒裝（已經裝好的舊 pack 重建環境時也擋，npm 不會被叫）；`npm ci` 固定 `--registry=https://registry.npmjs.org/`。

### 文件
- `docs/security.md` 新增「這套系統現在能保證什麼、不能保證什麼」（個人版自己用／伺服器版給朋友成員用／開放給不信任的第三方作者三種情境）；
  掃描、pip、npm 那幾段照實更新。`docs/AGENT.md` 補 C1～C8 的不變量與地圖；`docs/pack-format.md` 補 pip／npm 的來源規則。

### 測試
- `tests/test_review_c2.py`（新）：每條新規則一個 ast 樣本字串、假 zip、假 JobRunner、假 lock 檔；不執行任何樣本、不跑 pip／npm。

## 未發佈（branch feat/fix-round2：獨立安全驗證審查 C 的前半段，C1～C4）

### 變更（安全）
- **#C1（高）`{python}` 只准跑 pack 裡的 `.py`**：以前 `["{python}", "./run.txt"]`（或 `.pyw`、`.pyz`、`.zip`、沒有副檔名的檔）第 2 關零 finding、
  整包 T1、不用 publisher，Python 卻照跑。現在 `{python}` 要跑的 pack 內檔案一定要是 `.py`／`.pyw` 或含 `__main__.py` 的資料夾，
  其他＝拒（載入時也再查）；要跑哪支由欄位決定（`./{欄位}.py`）＝直接執行程式碼（exec、T2）。`.pyw` 當原始碼掃；
  `.pyz`／`.pyzw`／`.zip`／`.whl`／`.egg` 算掃不到內容（exec、T2）；沒有副檔名、ast 解析得過的檔也當 `.py` 掃。
- **#C2（中高）環境變數黑名單＋`PYTHONNOUSERSITE=1`**：以前 pack 能寫 `"env": {"PYTHONPATH": "C:/Users/Public/x"}`，讓合法的 Python
  在 pack 開始前先跑那裡的 `sitecustomize.py`。現在 `cli.env`／`env`／`mcp.env`／`auth.fields[].env` 不收 `PYTHON*`
  （`PYTHONIOENCODING`／`PYTHONUTF8`／`PYTHONUNBUFFERED` 除外，`PYTHONPATH` 只收 `{pack_dir}…`）、`NODE_OPTIONS`、`NODE_PATH`、`PATH`、
  `PATHEXT`、`COMSPEC`、`SYSTEMROOT`、`LD_*`、`DYLD_*`、`PIP_*`、`npm_config_*`、`PERL5*`、`BASH_ENV`…（不分大小寫，載入時再濾一次）；
  子程序一律 `PYTHONNOUSERSITE=1`。沒有加 `-I`（會讓 SDK pack 旁邊的 `synox_sdk.py` import 不到、`PYTHONIOENCODING` 失效）。
- **#C3（中）`{python} -m` 的 cwd 一定在 pack 裡**：`-m` 先從 cwd 找模組，cwd 是 `{user_data_dir}` 時那裡同名的 `.py` 會先被載入。
  現在 cwd 不是 `.`／`./子資料夾`／`{pack_dir}…` 就拒（載入時也拒）。
- **#C4（中，Windows）UNC／裝置路徑在碰檔案系統前就拒**：以前 pack.json 寫 `\\主機\分享\python.exe`，第 2 關在你按確認**之前**就對它
  `realpath`／`exists`，等於用你的帳號對那台主機連 SMB。現在第 1 關（`manifest.unc_problems`，在任何檔案檢查之前）拒
  `\\…`、`//…`、`\\?\`、`\\.\`、`\??\`；`kind: path` 的值在 `realpath` 之前也拒。順手：`python.module` 只能是模組名字、`skill` 只能是 pack 裡的相對路徑。

### 測試
- `tests/test_review_c.py`（新，161 個）：只做 manifest／scan／loader 的判斷；UNC 測試把 realpath／exists 換成碰到就失敗的假貨。

## 未發佈（branch feat/fix-identity：獨立安全審查 A＋審查 B 的一項）

### 修正（安全）
- **只用 Discord、還沒配對時，第一個陌生人會變成擁有者（高）**：擁有者 id 預設 10^15，身分檔也從 10^15 開始發號。
  10^15 現在保留給擁有者，陌生人從 10^15+1 起；擁有者還沒接上 Discord 帳號時，私訊型 bot **誰的私訊都不收**（不發號碼，回一句「還沒配對」），
  `doctor`／`/bot_status`／啟動 log 警告。舊的 `identities.json` 裡對到 10^15 的帳號標「待確認」，重新 `discord pair`（或 config 的
  `owner_user_id` 對得上）才解除；`owner_user_id` 指別人時把那個陌生人移開並提醒。
- **`identities.json` 壞掉不再靜默重新發號**：Discord 不開、`discord pair` 拒絕、`doctor` 說原因，原檔不動。
- **Telegram 群組 `/ai` 繞過 private_only**：agent 群組加 private_only；AI 判斷工具帶真正的 chat_id；AI 記憶以（聊天, 人）為鍵；
  核准卡一律送私訊（群組只留「卡已私訊給你」）。Discord 頻道 AI 的頻道共用記憶不變。
- **人打字的 `kind: path` 沒檢查資料夾**：cli pack 的 submit 照下令的人跑 `inside()`（`synox-sdk run` 同步）。
- **別人按你的核准卡會讓卡作廢**：先 take，不是本人只回「這不是你的按鈕」，不拿掉按鈕。
- **pack 取名跟出廠的一樣就被當 core**：有 packs.lock 時一律照鎖的 trust；出廠名單只在沒有鎖時算數。出廠 pack 第一次鎖預設 core。
- **網頁登入連結 login CSRF**：GET 只顯示「你將以 <名字> 登入」，按鈕 POST（一次性表單 token＋綁瀏覽器的 cookie＋同源）才登入；
  網頁上方明顯顯示目前登入身分。`public_url` 是 https 時 cookie 加 `Secure`。
- **log 洩漏**：AI 工具呼叫只在過了第 4 關後印「欄位名(長度)」，不印值；`[ROUTE]`／`[AGENT]` 行的 token 樣式一律 `***`（跟頻道 AI 遮罩同一份樣式）。
- 保管箱衍生金鑰快取改成 LRU（最多 256 把），不再永遠變大。
- （審查 B）短 secret（< 8 字）：存的時候網頁「連接」與 `connect` 警告太短；第 4 關對它自己那個 pack 的呼叫值也做子字串比對（4 字以上）。

### 說明（架構限制，先不改）
- 確認卡綁在 agent 群組：`ai: false` 的 bot、頻道型 bot、訪客按不了，`/bot_status`、`doctor` 寫出來。

### 文件
- `docs/discord.md`、`docs/security.md`：更正「只有 discord pair／owner_user_id 能接到擁有者」「使用者之間互相看不到」
  「surfaces 沒有 channel 群組裡 SDK 自己擋」「人打字的 path」「cli 沒鎖仍算 core」等跟程式不符的說法。

### 測試
- `tests/test_review_a.py`（新）與 `test_discord.py`、`test_web.py`、`test_perm8.py`、`test_bot_scope.py`、`test_sdk_p2_secret.py` 增補；
  每一項都有修之前會失敗的測試。全部 910 passed（dev 是 885）。

## 未發佈（branch feat/fix-exec：獨立安全審查 B，pack 供應鏈／工具執行）

### 變更（安全）
- **#A `{python}` 不再一律當成「SYNOX 的 Python」**：之前 `cli.python` 只要絕對路徑、`runtime.python` 只要非空字串，第 2 關對
  `argv[0] == {python}` 一律跳過——`cli.python` 指到 powershell.exe、argv `-Command echo …` 的 pack 會被判 T1、不用 publisher。現在：
  - 第 1 關：`cli.python`／`runtime.python`／`python_posix` 的檔名一定是 Python 直譯器（`python*`／`pypy*`）、不准 `..`
    （`runtime.python` 只收 `../.venv/…` 這種 pack 旁邊的 venv）；`cli.python` 不管 kind 都檢查（mcp stdio 也讀它）。
  - `{python}` 解析到 SYNOX 自己的、`runtime.python: auto` 建的、pack 資料夾裡的以外（`cli.python` 絕對路徑、`"venv"`、
    指到外面的 `runtime.python`）→ 記一筆 external（解析後的路徑、`interpreter: python`、未鎖定執行環境）＝T2、要 publisher、進鎖的 `t2.external`。
    規則只在 `envs.python_target`（`loader.cli_python` 也用它）。
  - argv 讓直譯器**直接執行一段程式碼**（`{python} -c`／`-i`／沒指定程式、`powershell -Command`／`-EncodedCommand`／不是旗標的字、
    `cmd /c`、`node -e`、`deno eval`、`bash -c`、`ruby -e`、`perl -e`、`php -r`、`osascript -e`、要跑哪支由欄位決定…；
    cli.argv＋每個 command 的 argv 整條看）→ 一定要宣告 `exec`、T2（`scan.inline_code`）。
  - 直譯器要跑的程式在 pack 外（`{python} {data_dir}/x.py`、`C:/x.py`）算 pack 外的程式。
  - 修誤判：argv 後面的 `/c`、`/k` 這種 Windows 旗標不再被當成絕對路徑（`scan._looks_like_path`）。
  - 取捨：pack 外的 python 與 `{python} -m 外部模組` 算 T2＋publisher，但**不**要求 `exec`（跟 git、npx 一致；金流簿的 `../.venv` 照舊能裝）。
- **#B 第 2 關的單行繞法**：`dotted()` 遇到非名字開頭的屬性鏈回空字串、什麼都不記，所以 `sys.modules['os'].system(…)`、
  `().__class__.__bases__[0].__subclasses__()`、`f.__globals__['os']` 零 finding。現在都算 `exec`：`sys.modules`（含 `from sys import modules`）、
  dunder／frame 屬性（`scan.DUNDER_ATTRS`，字串裡出現也算：`"{0.__globals__}".format`）、`getattr`／`vars`／`globals`／`locals`／`eval`／
  `exec`／`compile`／`__import__` 當值取用、`getattr` 的屬性名不是純字面字（含 `*args`、f-string 拼的）、呼叫對象看不出是什麼
  （`handlers[k](…)`、`f()(…)`、`(lambda: …)()`、`[os][0].system(…)`、沒匯入的 `obj.popen(…)`）、`inspect.currentframe`／`gc.get_objects`／
  `operator.attrgetter` 這類入口。`x = os` 之後的 `x.system(…)`、`run = os.system` 也照追。
  - 文件語氣改成「攔直呼名與常見的間接取用，是提醒不是門；個人版 python pack 在 SYNOX 程序內無任何隔離，伺服器版靠 PERM-8 只給擁有者」；
    python pack 的安裝報告多一行同樣的提醒（`admin.PYTHON_SCAN_NOTE`，個人版也看得到）。
  - SDK 單檔版（`author.py`）不再用 `fn.__dict__`／`vars()`／`spec["fn"](…)`：@tool 的宣告改掛 `fn.synox_tool_spec`；
    `synox-sdk init --from` 認得舊版的 `__synox_tool__`（`synox.sdk._legacy_spec`）。`sdk/synox_sdk.py`、`examples/hello/synox_sdk.py` 重新產生。
- **#C pip 自動安裝的來源**：之前只釘 `==版本`，沒有雜湊、沒有固定 index，子程序繼承 `PIP_INDEX_URL` 等環境變數。現在：
  - `requires.pip` 可以寫 `"名字==版本 --hash=sha256:…"`（一個或幾個；要嘛每項都有、要嘛都沒有），有寫就 `--require-hashes`。
  - pip 一律 `--isolated --index-url https://pypi.org/simple`；建環境的子程序（venv、pip、npm ci）用乾淨的環境變數
    （`envs.build_env`：只留 PATH、TEMP、使用者資料夾、代理設定…；`PIP_*`、`npm_config_*`、`PYTHONPATH` 不繼承）；pack 不能指定 index。
  - T2 安裝報告逐一標 pip 套件「有雜湊／沒有雜湊」，有沒寫的加紅字「版本釘選不等於來源可信」（`tier.hash_lines`）；
    `synox-sdk check` 同樣標。沒寫雜湊的 pack 環境指紋不變（不會害已建好的環境要重建）。
- **#D 載入後檔案被換**：之前 cli pack 的完整性只在 `load_all` 驗一次，載入後到下次 reload 前 pack 裡的 `./script.py` 被換掉不會發現。
  現在有鎖的 cli pack 每次叫子程序前（指令、AI、核准卡重跑、網頁面板）、mcp stdio 每次開子程序前再對一次鎖（`lock.LiveCheck`：
  先比修改時間＋大小，不一樣才算 sha256；每 10 分鐘全部重算一次；多出來的檔也算）。對不上＝不執行、回一句人話、通知擁有者一次。
- **#E zip 檔名（防禦深度）**：`admin._safe_parts` 另外拒收 Windows 保留裝置名（`CON`、`PRN`、`AUX`、`NUL`、`COM0-9`、`LPT0-9`、
  `COM¹`…，加副檔名也算）、含冒號的檔名（NTFS 資料流 `foo.py::$DATA`）、`< > " | ? *` 與控制字元、結尾是空白或句點的檔名。

### 測試
- `tests/test_review_b_exec.py`（#A）、`tests/test_review_b_scan.py`（#B）、`tests/test_review_b_supply.py`（#C／#D／#E）：
  全部不連網、不開埠、不執行任何樣本（直譯器旗標只組判斷；ast 樣本只解析；pip／npm 用假的 JobRunner；cli 子程序被換成會丟錯的假貨）。
  `tests/test_envs.py` 的 pip argv 斷言跟著 #C 更新。

## 未發佈（branch feat/t2-source）

### 變更（安全）
- **別的語言的原始碼一律算「掃不到內容的檔」（P7 補，擁有者 2026-11-09 決定）**：第 2 關只讀得懂 `.py`，
  `.js .mjs .cjs .ts .tsx .jsx .rb .pl .php .lua .go .rs .java .kt .cs .psm1 .bash .zsh…`（`scan.SOURCE_EXT`，可擴充）
  → 一定要宣告 `exec`、算 T2、安裝要一字不差輸入 publisher。之前 `examples/node-mcp-tool`（server.js）被判成 T1、不用輸入 publisher。
  已裝的這類 pack 升級／重新核准時會因「舊的那一份沒有確認過發行者」要求輸入一次。
- **直譯器算 pack 外的程式**：`cli.argv`／`mcp.argv` 的 `{node}`（不再當系統代換略過）、以及任何一段是 `node`、`npx`、`deno`、`bun`、
  `ruby`、`perl`、`php`…（`scan.INTERPRETERS`）→ external 記解析路徑（`{node}` 照 loader 的規則找；只查 PATH，不執行）、
  多一個 `interpreter` 欄位、標「未鎖定執行環境」。
- 遠端 MCP（`transport: http`）的信任層級改成 **T0**（之前誤算成 T1；文件與安裝報告本來就寫 T0）。
- 第 2 關讀 SYNOX 自己注入的協定變數（`SYNOX_USER_DATA_DIR`、`SYNOX_TG_ID`、`SYNOX_MODE`、`SYNOX_PACK_DIR`、`SYNOX_PACK_NAME`、
  `SYNOX_CONFIRMED`，名字是字面字）不再標⚠️「可能是密鑰」；`SYNOX_CONFIRM_TOKEN`、`SYNOX_SECRET_ENV` 照列。

### 新增
- `synox-sdk check` 多印一段：信任層級 T0／T1／T2、掃不到內容的檔案清單、pack 外的程式／直譯器與解析路徑、publisher
  （T2 沒寫＝⚠️ 安裝時一定會被擋）、MCP 工具與 effect、`requires.pip` 有沒有釘死。有「安裝一定會被擋」的問題（第 1、2 關拒裝、
  T2 沒寫 publisher）結束碼 2。`PackCheck.tier`／`blockers`／`pip_status()`。
- 測試 `tests/test_t2_source.py`（61 個）；`tests/test_examples.py` 改成斷言 node-mcp-tool 是 T2。

### 文件
- `docs/pack-format.md`：`requires.pip` 那列改成跟「依賴與環境自動建置」一致；`runtime.node` 註明只給 kind=cli；
  拿掉 command 填法那段的日期；信任層級補別的語言原始碼與直譯器。`docs/tools.md`：T1＝「第 2 關掃得到的 .py 與純資料檔」，
  T2 補原始碼與直譯器，拿掉「.js 目前算 T1」的說明。`docs/AGENT.md`：connect.py 存進 pack_secrets（跟「連接」表單同一份）。
  `docs/security.md`、`docs/sdk.md`、`examples/node-mcp-tool/README.md` 同步。

## 未發佈（branch feat/perm6）

### 新增
- **PERM-6：Discord 頻道 AI**。頻道型 bot 設 `ai: {"enabled": true, "pool_usd_month": 5, "persona": "…"}` 時，被 @（或 trigger 命中）
  但不是指令的訊息交給 AI（新檔 `src/synox/agent/room.py` 的 `RoomAgent`，AgentLoop 的子類別）。
  - 工具清單沿用 `policy.decide(via=AI, bot=頻道型)`：只有頻道看得到、data ≠ user、effect ≤ max_effect（永遠 < DANGER）的工具；
    要核准卡的工具一律不給，叫到了回「🔒 這個動作要到私訊做」，不送卡到頻道（執行中才要確認的也攔下）。
  - 記憶 key＝頻道負號 id，同頻道所有人共用最近 `ai.history_turns` 輪（預設 6）；公開頻道版系統提示＋persona；
    訊息包在 `⟦SYNOX-MSG-<nonce>⟧` 裡，@提及、附件檔名、連結當資料，顯示名稱只當標籤。
  - 費用：`agent/budget.py` 新增 `BotPool`（`data/bot_pools/<名字>/llm_usage.json`），整個 bot 一池、不算個人額度；用完回一句話、
    整個 bot 的頻道 AI 停到下個月。`/bot_status` 列這個月用量。
  - 節流：新增 `room_rate_per_minute`（頻道整體，預設 20）與 `ai.rate_per_minute`（AI 每人每分鐘，預設 2）。
  - 回覆送出前遮罩已存 secret 與 token 樣式（`room.redact_reply`）。
  - `RoomEvent` 多了 `display_name`、`attachments`（檔名）。
- 測試 `tests/test_discord_room_ai.py`（29 個；假 Gateway、假 HTTP、假 AI，不連網、不開埠）。

### 變更
- 頻道型 bot 沒寫 `ai`＝關；`ai.enabled: true` 但沒有 `pool_usd_month`（或是 0）＝設定錯誤，頻道 AI 不開，doctor 與 `/bot_status` 用 ❌ 說明（doctor 算一個問題）。
- `ai` 裡不認得的欄位改成設定錯誤。
- `policy.decide`：via=AI 的訪客判斷改用有效角色（role_map 對到成員的人，在頻道裡才有 AI 工具）；agent 群組在頻道型 bot 上改回 `bot_channel`（一樣當作不存在）。
- `AgentLoop` 抽出 `decision`／`tools_for`／`out_of_budget`／`say`／`carded_note` 幾個可換的點（私訊行為不變）。

## 未發佈（branch feat/sdk-p8）

### 新增
- **SDK P8：文件與範例**。新文件 `docs/tools.md`（給工具作者的總覽，不用讀程式碼）：三條接入路（cli 子程序、MCP stdio、遠端 MCP）
  的決策表、信任層級 T0／T1／T2 對作者與裝的人各代表什麼、十行入門、權限欄位（access、capabilities、surfaces、data、effect、ai、confirm）
  與常見組合、secret 與「連接」表單、確認來回、環境建置（runtime auto、requires.pip 釘死版本）、升級與版本、測試方法、作者自檢表（會被擋的寫法與原因）。
- `docs/README.md`：文件索引，每份一行說明，標出給使用者／作者／維護者。
- 範例 `examples/node-mcp-tool`：Node 標準函式庫手寫的 MCP stdio 伺服器（initialize／ping／tools/list／tools/call，沒有 npm 套件、
  沒有 node_modules）；pack.json 示範 `transport: stdio`、`{node}`、`tools_allow`（伺服器多列的 `internal_stats` 不放行）、`effects`、
  `capabilities: ["subprocess", "exec"]`＋`publisher`。測試只驗宣告與報告，不執行 Node。
- 範例 `examples/any-language-cli`：只用 Python 標準函式庫、不 import SDK 的 cli 工具（備忘清單：list／add／clear），
  README 寫完整的純文字協定（argv 樣板、SYNOX_* 環境變數、JSON 信封、確認來回），說明任何語言都能照寫。
- `examples/hello/README.md`；範例的 README 與程式檔加 `SPDX-License-Identifier: Apache-2.0` 檔頭（含兩個 mcp-remote 範例的 README）。
- 測試 `tests/test_examples.py`：`examples/*/pack.json` 每個都通過 `sdk.Pack.load`（第 1、2 關）、有 README／SKILL.md／publisher、
  程式檔有 SPDX 檔頭；node-mcp-tool 的宣告與安裝報告（工具與 effect）；any-language-cli 不用 SDK、用 `run_command` 跑完確認來回；
  給作者的文件沒有本機路徑或信箱、相對連結都存在。

### 變更
- README「想加功能」一節改指向 `docs/tools.md` 與 `docs/README.md`；`packs.dirs` 的例子改成 `<你的資料夾>` 佔位。

## 未發佈（branch feat/schema-mode）

### 新增
- **巢狀參數的 schema 模式（工具 SDK Q6 方案 B）**。pack.json `mcp.schema_tools`（一定要在 `tools_allow` 裡）列的 MCP 工具，
  inputSchema 的整數、布林、陣列、物件照型別給 **AI**，原樣送進 `tools/call` 的 `arguments`；人打字照舊只有平面欄位。
  - 新檔 `src/synox/packs/mcp_schema.py`：`normalize`（白名單子集；`$ref`／`oneOf`／`anyOf`／`allOf`／開放的 additionalProperties／
    路徑型 format／太深／超過 20 個屬性／危險的 pattern＝不支援，工具不給 AI，doctor 寫原因）、`check`（照 schema＋硬限制 3 層、
    20 鍵、2000 字、50 項、16 KB、未列的鍵、每個字串查 secret）、`tool_schema`（給 LLM 的定義）、`describe`（核准卡的參數行）。
  - 第 4 關：`validate.check_schema_call`／`schema_of`；`agent/loop.py` 的 `call_schema_tool`；`tools.build(..., app)` 給保留型別的定義；
    文字協定的系統提示附上非字串參數的 JSON 型別。
  - 核准卡（`ApprovalDesk.request(lines=, run=)`）：DANGER 與 needs_confirm 都把結構化參數一行一個列出來，按 ✅ 用同一組參數、執行前再驗一次。
  - 升級報告：`schema_tools` 多了工具＝紅字。
- 測試 `tests/test_schema_mode.py`（43 個，假 stdio 伺服器，不連網、不開埠）。

### 變更
- 平面模式不支援的巢狀欄位，doctor 的說明改成「要在 pack.json 的 mcp.schema_tools 列這個工具」。

## 未發佈（branch feat/sdk-p7）

### 新增
- **SDK P7：T2 信任（二進位與外部相依）**。新檔 `src/synox/packs/tier.py`：T0 只有宣告（connector、只登記的 mcp）、T1 原始碼、
  T2 二進位或外部相依（第 2 關掃不到）。**T2 不是沙盒保證，只是讓你知道你在信任誰**（docs/security.md「信任層級」）。
  - 第 2 關（`scan.opaque_files`）：pack 資料夾裡的 `.exe .dll .bat .cmd .ps1 .sh .so .dylib .pyd .pyc .node .wasm…`、檔頭是 MZ+PE／ELF／
    Mach-O 的檔（不管副檔名）、沒有副檔名但帶執行位元（zip 的 unix 權限）或 `#!`、`node_modules/`（一筆）、對不到原始碼的 `__pycache__`
    → 一定要宣告 `exec`，否則拒裝；python、cli、mcp stdio 都看（以前只看 python pack 的副檔名）。報告多「掃不到內容的檔案」：路徑、大小、sha256。
  - `cli.argv` 指到 pack 外的程式（`npx`、`git`、絕對路徑、`{python} -m 外部模組`）也列 external「未鎖定執行環境」＋解析後的路徑
    （只查 PATH／sys.path，不執行），跟 mcp stdio 一樣；不進雜湊。
  - 安裝報告（終端機、網頁、`admin.summary_of` 的 `tier`）：T2 紅字「這個 pack 會執行：…（掃不到內容）」「會安裝 N 個套件（來自 runtime auto）：名稱 版本」；
    安裝者要明確輸入 pack.json 的 `publisher`：網頁勾選＋輸入（一字不差才能按）、終端機 `install --yes --trust-publisher "<名字>"`、
    `packs lock --approve <name> --trust-publisher "<名字>"`。沒寫 publisher 的 T2 pack 不能裝。packs.lock 記 `tier`、`t2`、`trusted_publisher`、`trusted_at`。
  - 升級：publisher 變了（任何 pack 都紅字）、T2 新增 exec、可執行的東西變多、T1 → T2 → 紅字、要重新輸入發行者；沒變就沿用上次的確認。
  - 執行期：伺服器版的 T2 pack 一定要真隔離（`sandbox.required` 對 T2 一律命中，不管 trust、required_for），沒有＝只對擁有者可見；
    T2 python pack 沙盒包不到，伺服器版一律只給擁有者。個人版照用，doctor 每個 T2 pack 提醒一行（`sandbox.t2_personal_note`）。
  - `envs.node_pins`／`envs.all_pins`：package-lock.json 與 requires.pip 的套件清單（只讀 JSON）。
- 測試 `tests/test_t2_trust.py`（37 個）：假執行檔一律是位元組造的檔頭，絕不執行。

### 變更
- **packs.lock 雜湊涵蓋每一個檔**（含 `__pycache__`、`node_modules`、執行檔），新鎖寫 `"hash_scope": "all"`；舊鎖（沒有 hash_scope）
  照當時的算法對檔（`lock.hashes_for`），升級 SYNOX 不會讓已裝的 pack 變成被改過。
- 上傳的 `.synoxpack` 裡的 `__pycache__` 不解出來；`synox-sdk zip` 不打包 `__pycache__`；`integrity` 不跟 `__pycache__` 比。
- SYNOX 開的 cli／mcp 子程序一律 `PYTHONDONTWRITEBYTECODE=1`（`loader.context_env`），不會自己在 pack 資料夾裡產生 `.pyc`。
- `tests/test_envs.py`、`tests/test_upgrade_env.py`：runtime auto 的 pack 是 T2，測試補 `publisher` 與 `trust_publisher`。

## 未發佈（branch feat/perm5）

### 新增
- **PERM-5 Discord 頻道收訊**：`surface: "channel"` 的 bot 真的連線了。只收 `guilds[<伺服器>].channels` 列出的頻道；
  `trigger: "mention"`（被 @ 才回，@ 那段字去掉；預設）或 `"/"`（以 / 開頭才回）；其他頻道、沒觸發的、其他 bot／自己／webhook、
  只有附件、編輯過的訊息一律略過。私訊型 bot 照舊只收私訊。頻道型 bot 的 Gateway 要 `GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT`。
- 頻道的內部 id：`data/identities.json` 新通道名 `discord-channel`，發負號 id（-(10^15+n)，只增不減），跟 Telegram 群組一樣是負的，
  只能私訊的指令（private_only）在頻道自然不能用。
- **頻道裡的權限（保守預設）**：只有 pack.json `surfaces` 含 `channel` 且 `data` 不是 `user` 的 pack 存在，其他（記帳、記事、提醒…）
  是「未知指令」；內建指令只留 /help、/start、/exit。`max_effect` 預設 `read`；`write` 只限 `data=shared` 且發話者至少成員；
  DANGER 在頻道永遠不行（設定拒、decide 也拒），回「這個動作要到私訊做」。頻道型 bot 一律當作 AI 關（頻道 AI 是 PERM-6）。
- `role_map`：Discord 身分組 → `guest`／`member`；這次請求的有效角色＝max(SYNOX 角色, 對應角色)，最高到成員，**不寫回 users.json**；
  寫 `admin` 會被設定檢查拒（管理員只能用 /user_role 給）。
- 回覆用收到訊息的那個 bot 送回那個頻道，引用並提及發話者（其他 @ 不解析）；按鈕只有發話者能按；頻道裡別人的問答不會被插嘴。
- 頻道節流：（頻道, 人）每分鐘 `rate_per_minute` 則（預設 5），超過靜默略過、log 一行；每個 bot 照舊可 `enabled: false`。
- `/bot_status`、doctor：頻道型 bot 多一行「幾個伺服器／頻道、觸發方式、role_map 幾筆、節流」，pack 不會出現的原因多了
  「surfaces 沒有 channel」「data=user 不進頻道」「頻道裡只有 data=shared 能寫」；不印 token。
- 測試 `tests/test_discord_channel.py`（41 個，全部假 Gateway／假 HTTP）。

### 怎麼在 Discord 開頻道 bot（給一般使用者，詳見 docs/discord.md「3c」）
1. Developer Portal 另建一個 Application → Bot 頁 Reset Token 複製；Privileged Gateway Intents 打開 **Message Content Intent**（其他不用開）。
2. OAuth2 → URL Generator 勾 `bot`，權限勾 View Channels、Send Messages、Read Message History → 開網址把 bot 邀進你的伺服器。
3. Discord 使用者設定 → 進階 → 打開**開發者模式**；右鍵伺服器圖示「複製伺服器 ID」、右鍵頻道「複製頻道 ID」、
   伺服器設定 → 身分組 → 右鍵「複製身分組 ID」（要用 role_map 才需要）。
4. `python -m synox discord token --bot <名字>` 存 token；config.json 的 `channels.discord.bots` 加一個 `"surface": "channel"`、
   `"guilds": {"<伺服器 id>": {"channels": ["<頻道 id>"]}}` 的 bot；重開後 `/bot_status` 看「收訊中」，在頻道打 `@bot /help`。

### 變更
- `surface: "channel"` 但沒列任何頻道的 bot：不連線，原因「沒有列任何伺服器／頻道（guilds）」（以前一律說 PERM-5 還沒做）。
- `guilds` 的格式現在會檢查（id 要是數字、`channels` 不能空、只能有 `channels`／`role_map`）；`trigger`、`rate_per_minute`
  只有頻道型能寫。`Gateway` 多 `on_ready`；`DiscordChannel.send_message` 多 `reply_to`。

## 未發佈（dev）

### 變更
- 沒有鎖的 kind=cli pack（手動放進 packs/ 或 packs.dirs）在伺服器版改算 third-party，跟 kind=python 同一條規則（PERM-8 之後統一）：只有出廠的算 core。要給成員用，擁有者核准時選 `--trust core`。

## 未發佈（branch feat/sdk-p4b）

### 新增
- **SDK P4b：遠端 MCP（kind=mcp、`mcp.transport: "http"`）**。新檔 `src/synox/packs/mcp_http.py`：Streamable HTTP——每個 JSON-RPC
  訊息 POST 到 `mcp.url`，回應收 `application/json` 或 `text/event-stream`（只讀這次的串流、找到自己那個 id 就停；通知、伺服器反問不處理）；
  `Mcp-Session-Id`、`MCP-Protocol-Version` 標頭；session 過期（404）自動重新 initialize 再試一次；閒置回收／關閉時 DELETE。
  只往宣告的主機連：`allow_redirects=False`、3xx 一律拒。HTTP 用 requests，測試換 `mcp_http.new_session`。
- 認證：`auth.type=token` 的 secret 欄位（`mcp.bearer`，沒寫＝第一個）以 `Authorization: Bearer` 送出（網頁「連接」表單、保管箱、
  伺服器版每人一份）；token 不 log、沒有 argv、結果與錯誤訊息裡出現會遮成 `***`（stdio 也套用）。
- **OAuth 授權碼流程（選配、預設關）**：新檔 `src/synox/packs/oauth.py`。`auth.type=oauth`＋`auth.oauth`（authorize_url、token_url、
  client_id、scope、redirect_uri、receiver）→ `/<群組>_login`／`_code`／`_logout`（私訊、不給 AI）：PKCE S256＋一次性 state、
  貼回瀏覽器網址列（SYNOX 不開埠）、帶 `resource`、refresh token 自動換新。`receiver: "loopback"`（暫時開 127.0.0.1 埠）只有
  `LoopbackListener` 介面，叫了就拒。
- 第 1 關：http 的 `url` 一定 https、不帶帳密／#／樣板；`capabilities` 一定有 `network`、不能有 subprocess／exec／filesystem:any；
  不能寫 argv／env／cwd／headers；OAuth 端點一定 https、redirect_uri 只能 127.0.0.1。第 2 關：http 型只能是宣告。
- 安裝報告（終端機與網頁）：kind=mcp 逐一列出 `tools_allow` 與每個工具的 effect、要連的主機、信任 T0（只有宣告），請安裝者確認。
- 範例 `examples/mcp-remote-notion`（OAuth）、`examples/mcp-remote-todoist`（token）：網址與工具名是佔位（`*.example.invalid`），README 標明要擁有者確認。
  `connectors/notion`、`connectors/todoist` 的 REST 實作不動。
- 測試 `tests/test_mcp_http.py`（16 個）：假 HTTP 傳輸跑 initialize→list→call（JSON、SSE 兩種）、轉址被拒、session 過期重連、
  token 不外洩（log／結果／AI／錯誤）、http:// 被第 1 關拒、tools_allow 外被擋、DANGER 卡、needs_confirm 的 `_meta`、
  成員能用／訪客看不到、每人自己的 token 與連線、OAuth 貼回網址（state 不符、只能用一次）、loopback 拒、範例 pack 過關。

### 變更
- `packs/mcp.py` 的 `install()` 拆成共用部分＋連法（`Backend`：`StdioBackend`、`HttpBackend`），不重複兩份。
- `Manifest.mcp_http`／`mcp_connected`；`registered_only` 只剩 connector 與沒有 transport 的 mcp。doctor 對 http 型也列 MCP 的提示。
- `secrets.managed()`：真的會連的 kind=mcp（stdio、http）的 `auth.fields` 也由 SYNOX 收（工具頁有「連接」）。

## 未發佈（branch feat/sdk-p4a）

### 新增
- **SDK P4a：kind=mcp 真的連（stdio）**。pack.json `"mcp": {"transport": "stdio", "argv": [...], "env", "cwd", "timeout",
  "start_timeout", "tools_allow", "effects"}`；代換、SYNOX_* 環境、secret 注入、clean_env 同 kind=cli。新檔 `src/synox/packs/mcp.py`：
  - 協定子集（標準函式庫）：initialize → notifications/initialized → tools/list（分頁）→ tools/call；ping 兩邊都回，伺服器問別的回 -32601。
  - 每個（pack, 使用者）一個長駐子程序（`McpPool`＋`PerUserScope`；`SharedScope` 只有介面），第一次呼叫才啟動、閒置 10 分鐘回收、
    崩潰下次重啟、bot 關閉全收；Windows 上每個子程序放進 KILL_ON_JOB_CLOSE 的 Job Object；啟動前過 `sandbox.wrap(grants)`。
  - 逾時、非 JSON 輸出、中途結束、啟動失敗都回一句人話並收掉那個程序（不卡住 bot）。
  - `tools_allow` 的工具＝葉節點（名稱轉成合法指令）；說明與欄位來自 tools/list（快取 `data/mcp/<pack>.tools.json`）：
    string／integer／number／boolean／enum → text／int／number／bool／choice；巢狀 object／array 不給（doctor 列出、必填的話整個工具不能用）。
  - effect 只看 pack.json（工具的 annotations 不算，沒寫＝DANGER）；照舊走 policy.decide、第 4 關、DANGER 核准卡、nonce 分隔符。
  - 確認來回：`structuredContent.needs_confirm` → 核准卡（P3 的一次性憑證）→ ✅ 以 `params._meta["synox/confirm_token"]` 重叫。
- 第 1 關：stdio 要 `mcp.argv`、`capabilities` 要有 `subprocess`、不能同時寫 `url`；`data` 沒寫照 mcp 樣板推（同 cli）。
- 第 2 關：mcp stdio 掃 pack 裡的 `.py`（同 cli）、`argv`／`env` 只能系統代換、data 規則同 cli；argv 指到 pack 外的程式 → 新的
  非擋關 finding `external`「未鎖定執行環境」（報告與 doctor 都列）。
- doctor：mcp stdio pack 列未鎖定執行環境、不支援的欄位、伺服器沒列的 allowed 工具、還沒連過。
- 測試 `tests/test_mcp_stdio.py`（18 個）：假伺服器（崩潰、卡住、非 JSON）、SDK `serve --mcp` 真伺服器、閒置回收（假時鐘）、
  崩潰重啟、逾時、tools_allow、effect、DANGER 卡、needs_confirm 來回（打字與 AI）、成員／訪客看不到、每人一個程序、沙盒 grants、關閉收程序。

### 變更
- `Manifest.mcp_stdio`／`registered_only`：只登記的（connector、只有 url 的 mcp）才是 status `connector`；mcp stdio 是 `loaded`，
  SKILL 進 AI 的系統提示、網頁工具頁不標「要先設定」。
- `sandbox.required()`（required_for）也看 mcp stdio（`runs_subprocess`）；`data_scope`／`grants_for` 認得 mcp 的樣板，mcp 的 `grants.timeout` 是 None。
- 升級的「執行方式改了」多比 `mcp.transport`／`argv`／`cwd`／`env`。

## 未發佈（branch feat/perm8）

### 新增
- **PERM-8 伺服器版 python pack 信任**：`trust: third-party` 的 kind=python pack 在伺服器版整組只對擁有者可見（成員打了＝「未知指令」、
  `/help`、AI 工具清單都沒有）；出廠的（`loader.BUNDLED`，在內建 `packs/`／`connectors/`）與擁有者安裝時選 `core` 的照常。
  沒有鎖的（手動放進 `packs/` 或 `packs.dirs`）＝third-party。原因寫在 pack 清單的 detail、`doctor` 與 `packs status` 的 🔐 行。個人版不受影響。
- 伺服器版沒鎖、不是出廠的 pack 載入前補跑一次第 2 關掃描：沒過＝新狀態 `rejected`、不載入（網頁顯示「掃描沒過，沒有載入」）；
  `PackStatus.scan`＝passed｜failed。`doctor`、`packs status` 也列出來。
- **`pack.path_of(user, …)`**：伺服器版 `data/users/<id>/<pack>/files/`、個人版 `data/<pack>/files/`；資料夾先建好；絕對路徑、`..`、
  跑出資料夾一律丟 `PackPathError`；伺服器版一定要給 user。
- 第 2 關：`data: user` 的 python pack 用 `pack.path(` ＝拒（提示改用 `path_of`）；`data: none` 用 `pack.path_of` 也拒。
- 測試 `tests/test_perm8.py`（16 個）。

### 變更
- 伺服器版 `data: user` 的 pack 呼叫 `pack.path()`（全部人共用的 `data/packs/<name>/`）丟 `PackPathError`、說改用 `path_of`；個人版照舊。
  `pack.path()` 也擋 `..` 逃逸。出廠 pack 與 4 個 connector 都沒有用 `pack.path`，不用改。
- `python -m synox packs status`／`lock`／`env` 找 pack 時也看 config.json 的 `packs.dirs`。
- 既有測試裡手放、要給成員看的 python pack 先用 `conftest.trust_core` 鎖成 core（test_policy、test_modes、test_perm2）。

## 未發佈（branch feat/sdk-p3）

### 新增
- **SDK P3 確認來回**：cli 工具執行中回 `needs_confirm`（`raise Confirm(summary, token=…)`）→ SYNOX 出核准卡給下令的人（why＝summary；
  人打字與 AI 呼叫都走這條，AI 那一輪在卡送出時結束）→ 按 ✅ 用同一組參數重跑，子程序這一次才有 `SYNOX_CONFIRMED=1`、
  `SYNOX_CONFIRM_TOKEN`＝工具給的 token。新檔 `src/synox/packs/confirm.py`：一次性憑證綁 pack／指令／參數雜湊／使用者、
  跟卡片同樣的 `confirm_ttl` 過期、用一次（對不上也作廢）；❌ 作廢。其他每次都明寫 `SYNOX_CONFIRMED=0`（蓋過 `cli.env` 與 SYNOX 自己的環境）。
  確認過的重跑又要確認 → 回一句話、不再出卡。`commands[].confirm`（AI 呼叫前的卡）照舊，兩者並存。
- SDK：`confirmed(token="")`、`Context.confirmed`／`Context.confirm_token`；`--mcp` 的 Confirm 回 `isError: false`＋
  `structuredContent.needs_confirm`，用戶端確認後帶 `params._meta["synox/confirm_token"]` 重叫才算確認（MCP 模式不看環境變數）。
- `synox-sdk run … --confirmed`：本機模擬按 ✅。
- 測試 `tests/test_sdk_p3_confirm.py`（13 個）。

### 變更
- `ApprovalDesk.request` 多 `grant`／`rerun`／`header`；`CaptureApi.mark_carded()`；`app.extras["synox_approval_desk"]`。
- `tests/test_sdk_author.py` 的子程序一律 `-X utf8`＋`PYTHONIOENCODING=utf-8`＋`errors="replace"`（cp950 解碼警告）。

## 未發佈（branch feat/perm7）

### 新增
- **PERM-7 沙盒介面**：新檔 `src/synox/sandbox.py`。`Sandbox.wrap(argv, env, cwd, grants) -> (argv', env')`，`set_factory` 換實作（仿 `packs/envs.py`）。
  後端：`none`（原樣，個人版預設）、`jobobject`（Windows 只限資源：Job Object 記憶體上限／程序數，經 `python -I sandbox.py jobobject` launcher，設不起來就不跑）、
  `bwrap`（Linux，只組 argv：系統唯讀、grants.read 唯讀、grants.write 可寫、`--unshare-pid`、沒 network 就 `--unshare-net`、前面接 prlimit）、
  `systemd`（只組 `systemd-run --pipe --wait` 的 --property；環境變數只給名字）、`appcontainer`（只有介面，NotImplementedError）。
- loader 的 `make_cli` 每次都過沙盒：grants 從宣告算（data=user → `<user_data_dir>/<pack>/` 可寫；pack 資料夾、`data/envs/<pack>/` 唯讀；
  沒有 network capability → 斷網）。pack.json 的 `data` 欄位（PERM-2）還沒合進來，推斷集中在 `sandbox.data_scope`。
- config.json `policy.sandbox`：`backend`（auto｜none｜jobobject｜bwrap｜systemd｜appcontainer）、`required_for`（third-party｜all｜none）、
  `mem_mb`（1024）、`max_procs`（64）、`systemd_scope`（system｜user）；寫錯讀設定時就拒。`auto`＝個人版、Windows 是 none，Linux 伺服器版 bwrap→systemd→none。
- 伺服器版 `required_for` 命中的 cli pack 沒有真隔離後端（none、jobobject 不算）→ 只對擁有者可見；third-party＝packs.lock 的 `trust`，
  還沒寫的看鎖的 via（web／console＝從檔案裝的）。doctor 多一行「沙盒：後端…；真隔離：是／否」，被限制的 pack 寫原因。
- `docs/security.md`「運行空間」一節（含伺服器上要驗的清單）。**沙盒後端只驗證了組出來的 argv，真機驗證要在 Linux 伺服器上做。**
- 測試 `tests/test_sandbox.py`（16 個，全用假後端／假 kernel32）。

## 未發佈（branch feat/perm4）

### 新增
- **PERM-4 bot 範圍**：Discord 每個 bot 的 `packs`、`max_effect`、`ai` 真的生效。`policy.decide` 的 `bot` 參數改成照 bot 設定判斷
  （原本給了就一律拒）：pack 不在清單＝對這個 bot 不存在、effect 超過 `max_effect`＝拒（會說上限）、`ai: false`＝沒有 AI。
- 每個 bot 的收訊在 `policy.using_bot(spec)` 裡進 dispatcher（`DiscordEntry`），AI 那一輪的執行緒也帶著（`policy.run_as`），
  所以打字、/help、群組選單、按鈕、核准卡、AI 工具清單與系統提示都照收訊的 bot 過濾。Telegram／網頁／終端機不受影響。
- **`/bot_status`**（伺服器版管理員以上；個人版擁有者；有設定 Discord 才有）：每個 bot 會出現的 pack、「設定了但不會出現」的 pack 與原因
  （沒載入、connector 沒指令、指令全部超過上限；原因清單 `discord/scope.py` 的 `REASONS` 可擴充，PERM-2 加 surfaces）、沒開給它的 pack。
- `python -m synox doctor` 每個 bot 底下列同樣的範圍資訊（只讀 pack.json）。

### 變更
- `policy.install(app)`：`app.registry.authorize` 改走 `decide`（SDK 本身沒改）。**能力上限造成的隱藏改回「未知指令」**
  （PERM-1 時成員打 subprocess pack 的指令回「沒有權限」），跟 owner_only、bot 範圍外一致，不洩漏存在。
- 測試：新增 `tests/test_bot_scope.py`（9 個）；`tests/test_policy.py` 兩個改成新行為（未知指令、bot 範圍生效）。

## 未發佈（branch feat/sdk-p1-author）

### 新增
- **SDK P1 作者端：寫函式就是工具**（`src/synox/sdk/author.py`；單檔版 `sdk/synox_sdk.py` 由 `scripts/build_synox_sdk.py` 產生、零相依）。
  `@tool(effect, summary, default, ai, confirm)`：型別註記→fields（int／float／bool／str／Path／Literal／Optional）、docstring→summary 與欄位說明。
  `serve()`：子指令＋`--json` 印信封；`--mcp` 是 MCP stdio server（initialize／ping／tools/list／tools/call，inputSchema 由型別註記產生）。
  `secret()`、`context()`、`ToolError`、`Ok`、`Confirm`（needs_confirm 信封；按鈕來回之後做）。
- `synox-sdk init --from tool.py`（產生 pack.json＋SKILL.md、沒寫 effect 拒產、重跑只重產 cli.commands）、`synox-sdk run <指令>`（本機照 loader 代換＋第 4 關試跑）。
- loader 給 cli 子程序 `SYNOX_USER_DATA_DIR`／`SYNOX_TG_ID`／`SYNOX_MODE`／`SYNOX_PACK_DIR`／`SYNOX_PACK_NAME`／`SYNOX_SECRET_ENV`。
- pack.json cli 的 `commands[].ai`（false＝不給 AI）、`commands[].confirm`（true＝AI 呼叫前先送確認卡）。
- `docs/sdk.md` 改寫成「十行」教學；範例 `examples/hello/`。測試 `tests/test_sdk_author.py`。

## 未發佈（branch feat/perm1）

### 新增
- **PERM-1 policy 層**：新檔 `src/synox/policy.py`，權限的唯一交會點 `decide(app, user, node, *, via, chat_id, bot=None)`
  ＝SDK `authorize` ∧ pack.capabilities ⊆ 這個人角色的能力上限（擁有者不受限）。`agent/loop.py` 的 `ai_decision` 改成呼叫
  `decide(via=AI)`（AI 能不能用一個節點仍只有一個判斷；原本的群組／interactive／ai=False／agent、sudo／訪客規則搬進 decide）。
  `ai_decision` 第一個參數改收 app（仍收裸的 `CommandRegistry`，當作沒有 pack、預設上限）。
- **config.json `policy.roles`**（沒寫＝預設）：guest `[]`、member `["network","filesystem:own"]`、admin 再加 `"subprocess"`。
  `exec`、`filesystem:any` 寫進任何角色＝讀設定時就拒（ConfigError）；不認得的角色／能力、寫 `owner`、上限不是一級比一級寬也拒。
  `policy.sandbox` 只保留預設值（PERM-7 才用）。
- **loader 依上限決定可見性**（`loader.pack_group_policy` → `policy.group_policy_for`）：pack 的 capabilities 裝不下某一級的上限，
  群組門檻拉到裝得下的那一級；哪一級都裝不下（exec、filesystem:any）＝`owner_only`。所以 /help、選單、網頁、人打字、AI 工具清單同一條擋。
  個人版也套（陌生人看不到要 network 的 `access: everyone` pack）。`decide` 對這個人再算一次（縱深）。
- `bot` 參數先留介面：None＝不限制；給了別的（PERM-4 之前）一律拒（fail closed）。
- 測試 `tests/test_policy.py`（26 個）。`tests/test_sdk_p2_secret.py` 的三個測試用 subprocess 回音 pack 給成員／訪客用，改成在設定裡把
  subprocess 開給每一級（測的是 secret，不是上限）。

## 未發佈（branch feat/perm2）

### 新增
- **pack.json 權限宣告**（PERM-2）：`surfaces`（`["dm"]`／`["dm", "channel"]`，預設 `["dm"]`）與 `data`（`none`／`user`／`shared`；沒寫照預設推：
  python 有寫 storage＝user、cli 看樣板用 `{user_data_dir}` 還是 `{data_dir}`）。第 1 關檢查格式，`channel`＋`data: user` 拒。舊 pack 照舊能用。
- 第 2 關新規則（列檔名:行號）：`data: user` 的 python pack 不准裸用 `pack.store`（`load`／`save`／`update`，要 `pack.store.of(user)`）、
  `pack.secret(name)` 一定要給 user；cli 樣板不准 `{data_dir}`（只能 `{user_data_dir}`）；`data: none` 不准用 `pack.store`／`pack.path`／資料夾代換。
- loader：`surfaces` 沒有 `channel` 的 pack 整組 `private_only`（群組裡打了 SDK 回「請私訊」）；`data: shared` 的 WRITE／DANGER 指令在伺服器版只有管理員。
- 安裝報告多「在哪裡用、資料屬於誰」與 **trust** 選項（`core`／`third-party`，預設 third-party）：網頁下拉選單、終端機 `--trust`，寫進 `packs.lock`
  （也記當時的 surfaces／data）；舊的鎖沒有 trust＝third-party。`packs lock --approve` 沒給 `--trust`＝沿用舊鎖的。
- 升級比對：`surfaces` 多了 channel、`data` 變寬（none → user → shared）、trust 跟舊鎖不同 → 紅字；升級沒選 trust＝沿用。
- 出廠 notes、money、remind 與 4 個 connector、`tests/fixtures` 的範例都標上 `surfaces: ["dm"]`、`data`；全部過新掃描（零違規）。`synox-sdk init` 產生的 pack.json 也寫好（python＝user、cli＝none）。

### 改變
- 出廠 pack 現在只能私訊用（以前 Telegram 群組裡也能打 `/note`）。測試 `tests/test_perm2.py`（45 個，439 → 484 passed）。

## 未發佈（branch feat/sdk-upgrade-env-glue）

### 修正
- **升級之後照樣建環境**（P5 × P6 接縫）：以前升級 pack 不會建 `runtime.python`／`runtime.node` = `"auto"` 的環境，新版改了
  `requires.pip`／`package-lock.json` 或剛改成 auto，升級完只剩 doctor 說對不上、要手動 `packs env rebuild`。現在升級報告
  （終端機與網頁）多一段跟安裝報告一樣的「🧱 要建環境／要重建環境」清單（新版要環境，且舊版沒有、套件清單跟舊版不同、或現在的環境沒建好）；
  套件清單沒變就寫「沿用」。確認升級後跟全新安裝一樣建：網頁在背景建、好了／失敗通知擁有者；`install --yes` 等它建完。
  建失敗不退回升級（pack 已升級、doctor 說環境沒建好）。升級時終端機不再重複印安裝摘要的那段「要建環境」。
- `packs rollback`：退回的舊版要環境、而 `data/envs/<name>/` 跟它對不上 → 提示重建（不自動建）。
- 清掉 `packs/admin.py` 沒用到的 `import time`。測試 `tests/test_upgrade_env.py`（12 個；假的 JobRunner，不真的 pip／npm、不連網）。

## 未發佈（branch feat/sdk-p6-upgrade）

### 新增
- **pack 升級**：同名的 pack 再裝＝升級（以前是拒裝、要先移除）。安裝報告多一段「改了什麼」：新增／移除的 command；
  effect 變寬、新增 WRITE／DANGER command、capabilities 新增、執行方式（runtime、cli.argv…）或 auth 改動、多要密鑰、access 變寬、
  新加面板一律紅字。版本要是 semver 且比裝著的新；一樣或比較舊會明講並拒絕，除非明確選降級（網頁勾選框、`--allow-downgrade`）。
  確認後舊資料夾搬到 `packs/_removed/<name>-<版本>-<時間>`（旁邊留舊的鎖）、`packs.lock` 換新、重新載入。Web UI 設定頁按「確認升級」；
  `python -m synox install <檔> --yes` 自動走升級。資料不在 pack 資料夾，不受影響；資料 schema 升級由 pack 自己負責（pack-format.md「升級」）。
- `python -m synox packs rollback <name>`：`_removed` 裡最近一份舊版搬回、鎖改回當時的（檔案對不上就不鎖）；現在那份搬到 `_removed`。
- 移除的資料夾名多了版本（`<name>-<版本>-<時間>`），旁邊留 `.lock.json`，移除之後也能 rollback。測試 `tests/test_upgrade.py`（22 個）。

## 未發佈（branch feat/sdk-p5-envs）

### 新增
- **依賴與環境自動建置**（SDK P5，`src/synox/packs/envs.py`）：kind=cli 的 `runtime.python` 可以寫 `"auto"`——安裝時在
  `data/envs/<pack>/venv` 建 venv，`pip install --no-deps --only-binary=:all:` 裝 `requires.pip`（只收 `名字==版本`，其他寫法 pack.json 不合）；
  新的 `runtime.node`（路徑或 `"auto"`）與代換 `{node}`：`auto`＝`npm ci --ignore-scripts` 照 pack 的 `package-lock.json` 裝進
  `data/envs/<pack>/node_modules`（子程序拿到 `NODE_PATH`）。pack 資料夾不寫任何東西。
- 安裝報告（終端機與網頁）在第 2 關之後多一段「🧱 要建環境：Python venv、裝 N 個套件：名稱 版本」；按確認、裝好之後才建
  （JobRunner，整個最多 10 分鐘，log 進 `data/job_logs/`）。失敗不卡安裝：pack 已裝、狀態 `missing`，doctor 標「環境沒建好」並說原因；
  沒網路說「連不上網路」、找不到版本說是哪個套件。網頁裝完會在背景建，好了／失敗都通知擁有者。
- `python -m synox packs env rebuild <name>`：重建。`requires.pip`／`package-lock.json` 改了，doctor 會說環境對不上、要重建。
  系統沒有 node（而 pack 用 `{node}`／`runtime.node`）＝doctor 說缺、不載入。
- `Builder` 是可替換的介面（`envs.set_factory`；預設 `VenvBuilder`）。`node` 成為保留的代換名（欄位不能叫 node）。
  備份略過 `data/envs/`（可以重建）。測試 `tests/test_envs.py`（36 個；假的 JobRunner 與 which，不真的 pip／npm、不連網）。

## 未發佈（branch feat/sdk-p2-secret）

### 新增
- **pack 的 secret**（pack.json `auth.fields[]`，`auth.type` 是 `token`／`file`；oauth 這一版不做）：
  `{"name", "label", "secret": true, "env": "TODOIST_API_KEY", "kind": "text|file", "required"}`。
  - 存保管箱 `pack_secrets`（鍵 `packs/<pack>/<field>`）；伺服器版每人一份（`vault.for_user`）。
  - Web UI 工具頁每個 pack 的「🔌 連接」：secret 用密碼框、**永遠不回傳值**（只回「有填」與最後 4 碼）、留空沿用原值、`kind: file` 可上傳；
    `GET/POST /api/pack-secrets/<name>` 走既有的 CSRF 與 Origin 檢查；個人版只有擁有者、伺服器版每人設自己的。Telegram 不收。
  - `python -m synox connect <pack>` 對這類 pack 寫同一份（secret 用 getpass、file 問路徑）。
  - kind=cli：只有寫了 `env` 的欄位放進子程序環境（同時列進 `keep_env`），**絕不進 argv**；必填的沒填＝回「到網頁工具頁按『連接』」、不執行。
  - kind=python：`pack.secret(name, user=None)`（伺服器版一定要給 user；沒宣告的名字丟 KeyError）。掃描器把 `pack.secret` 列成「讀使用者填的 secret」，不算 capability。
  - 第 4 關：AI 帶的欄位值等於（或夾著 8 字以上的）這個人已存的 secret ＝拒，不執行。
  - 工具頁狀態照這個人存了沒：「要先設定」→「已連接」；doctor 列出還缺哪些（伺服器版看擁有者那一份）。
  - pack.json 第 1 關檢查 `auth.fields`（名字、env、kind、secret／required 是布林）與 `auth.managed`（`synox`｜`pack`）。
- 內建 connector（notion／todoist／google-calendar／apple-reminders）沒呼叫 `pack.secret`，不算 SYNOX 收：照舊用自己的 token 指令，行為不變。
- 測試 `tests/test_sdk_p2_secret.py`（21 個；假的本機命令列程式，不連網、不開埠）。

## 未發佈（branch feat/sdk-p0-fixes）

### 修正
- **AI 呼叫 cli pack 的指令拿到空結果**（G3）：經 AI 呼叫時改成同步跑完，結果（包每輪的 nonce 分隔符）交回 AI 轉述；
  人自己打的指令照舊在背景跑、直接回覆。`background: true` 的指令不變（AI 只知道「開始了」）。
- **cli pack 拿不到任何密鑰**（G1）：SDK 的 `clean_env` 會拿掉 `*_TOKEN`、`*_API_KEY`… 的環境變數，loader 沒傳 `keep_env`。
  現在把 `requires.env`（之後 `auth.fields[].env` 也算）列的名字傳成 `keep_env`，只放行這些；其他像密鑰的照樣拿掉。vendor 沒改。

### 新增
- `pack.json` 的 `requires.synox`（例如 `">=0.3"`、`">=0.3,<1.0"`）：寫錯＝pack.json 不合；版本不合＝不載入（狀態 `incompatible`，
  網頁「SYNOX 版本不合」），doctor、`python -m synox packs status`、安裝報告說要哪一版、這台是哪一版、該怎麼做。
- `fields[].kind` 多了 `int`、`number`、`bool`、`choice`（配 `choices`）：AI 看到的 schema 仍是字串；交給程式前照 kind 檢查
  （不合回人話、不執行），並整理成固定寫法（bool → true/false、去千分位、choice 換成宣告的拼法）。`choices` 比對改成不分大小寫。
- `requires.env` 的名字要是合法的環境變數名（清單或物件都收）。測試 `tests/test_sdk_p0.py`（31 個；假的本機命令列程式，不連網、不開埠）。

## 未發佈（branch feat/connector-notion）

### 新增
- **Notion connector 接上了**（`connectors/notion`，`kind: python`、`capabilities: ["network"]`）：`/notion` 搜尋、`/notion_read`、
  `/notion_dbs`、`/notion_rows`、`/notion_row`（資料庫加一列，`props=欄位:值; …`）、`/notion_new`、`/notion_append`、
  `/notion_set`（DANGER：AI 要做先出核准卡）；`/notion_token`（私訊、不給 AI；token 進保管箱 `data/notion.json.enc`）、
  `/notion_status`、`/notion_logout`。Notion REST `2025-09-03`，只用 requests；log 裡長得像 Notion token 的字遮成 `ntn_***`。
  測試 `tests/test_notion.py` 用假的 HTTP 傳輸，五關各走一次。
## 未發佈（branch feat/connector-todoist）

### 新增
- **Todoist connector 接上了**（`connectors/todoist`，從設計稿變成 `kind: python`＋`capabilities: ["network"]`）：Todoist API v1、個人 API token；
  `/todoist`（加）、`_list`（today｜overdue｜#專案｜@標籤）、`_done`、`_due`（改期）、`_rm`（DANGER）、`_projects`、`_labels`、
  `_token`／`_logout`（ai=False）。寫法與欄位跟 SYNOXPacks 的 `todo` pack 一樣。token 在保管箱（伺服器版每人一份）。
- `synox.packs.kit.redact_in_logs("/指令")`：那個指令後面的字在 log（SDK 的 `[ROUTE]` 行）換成 `***`。

## 未發佈（branch feat/connector-apple）

### 新增
- `connectors/apple-reminders-caldav` 從設計稿變成真的 pack（`kind: python`、`capabilities: ["network"]`，只用 requests＋標準函式庫）：
  `/applerem`、`/applerem_lists`、`/applerem_add`、`/applerem_done`、`/applerem_status`、`/applerem_logout`；自己解析／產生最小的 VTODO。
  研究結論：iCloud 升級過（iOS 13 起）的提醒事項 Apple 不經 CalDAV 提供；建議 iPhone 接別家 CalDAV 帳號（見該資料夾 README）。
- `python -m synox connect <pack> [--user ID] [--clear]`＋`Connect-Apple.bat`：照 pack.json 的 `auth.fields` 把帳號存進保管箱
  （密碼用 getpass，不經聊天、不進 log）。

## 未發佈（branch feat/connector-gcal）

### 新增
- **Google 日曆 connector**（`connectors/google-calendar`，kind=python、`capabilities: ["network"]`）：REST 直連 Calendar API v3，只用 requests。
  `/gcal`、`/gcal_today`、`/gcal_week`、`/gcal_list`、`/gcal_rm`（DANGER）跟 SYNOXPacks 本機 `calendar` pack 同名同欄位；
  連接 `/gcal_setup`、`/gcal_code`、`/gcal_token`、`/gcal_logout`、`/gcal_status`（前四個 ai=False）。
  OAuth：電腦版用戶端＋PKCE＋state，loopback 轉址但**不開 listener**（使用者貼網址列回來）；憑證全在保管箱。測試 `tests/test_gcal.py`（假 HTTP）。

## 未發佈（branch feat/pack-security）

### 新增
- **裝 pack 的五關**（docs/security.md）：pack.json v2 宣告檢查、ast 靜態掃描（沒宣告的能力拒裝、列檔名:行號）、
  `data/packs.lock`（載入時雜湊不符＝不載、通知擁有者一次）、AI 每次工具呼叫前驗參數（`agent/validate.py`）、
  工具結果包在每輪隨機的 `⟦SYNOX-TOOL-<nonce>⟧` 裡。
- `python -m synox install <檔.synoxpack> [--yes]`、`python -m synox packs status｜lock --approve <name>`；`Install-Pack.bat`；
  精靈完成頁可以勾「.synoxpack 點兩下就安裝」（HKCU，不要管理員）。
- `synox.sdk`：JSON 信封、`Pack.load`、`init_pack`、`zip_pack`；`synox-sdk init｜check｜zip`；`scripts/pack_zip.py`；docs/sdk.md。
- kind=cli：`{python}`、`{pack_dir}`、`{data_dir}`、`{user_data_dir}`、`{tg_id}` 代換（argv、env、cwd，每次呼叫照下令的人）；
  `cli.python`（絕對路徑｜venv）與 `runtime.python`／`python_posix`（相對 pack 資料夾）；最上層 `env`；cli pack 的面板（`web.api` → READ command）。
- `kind: mcp`（只登記）。

### 修正
- cli 的選填旗標：SDK `service.build_argv` 在後面的 `--k={v}` 沒填時會把前面已經填好的 `--a=1` 一起拿掉；loader 改用自己的 `build_argv`。

## branch feat/web-ui（已合併）

### 新增
- **Web UI**（`src/synox/web/`，標準函式庫、只綁 127.0.0.1、預設埠 8830）：`/web` 一次性登入連結（7 天、只能用一次）→ cookie session；
  對話頁（每人的對話紀錄、密文、每段 50 則；按鈕可以按、核准卡可以用）、工具頁（看得到的功能、每個指令一個執行框、pack 面板）、
  設定頁（AI 來源、`.synoxpack` 上傳／移除／重新載入、伺服器版帳號表、加密備份下載）。`/web_off` 關掉。埠開不起來 bot 照常跑。
- pack.json 的 `web.panel`／`web.api`、`pack.web_route()`；記帳的面板範例。
- 備份：`synox/backup.py`（data/ 的 zip，用保管箱主金鑰加密）。
- **伺服器版的成員**：AI（工具只有他能用的、每月額度 `ai_member_monthly_usd`、`/ai_budget`）、每人自己的提醒與排程。
  提醒 pack 的 access 改成 `member`（個人版不變）。

## branch feat/llm-and-modes（已合併）

### 新增
- **個人版／伺服器版**：`config.json` 的 `"mode": "personal" | "server"`（沒寫＝personal，行為跟以前一樣）。
  伺服器版：陌生人是訪客（GUEST），只看得到 `access: everyone` 的 pack；裝 SDK 的 `accounts`（`/me`、`/me_upgrade`、`/user_list`、`/user_role`）
  與 `limits`（`/limit_*`）；新的 `access: member`（筆記、記帳改用它）；`pack.store.of(user)` 每人一份 `data/users/<id>/<pack>.json.enc`，
  金鑰 HKDF(主金鑰, `user:<id>`)。營運者仍看得到（docs/security.md）。
- **精靈**：第一頁「這台給誰用？」＋「工程師？直接改 config.json」；AI 頁改成「預設：Claude（這台電腦登入的 Claude Code）」在上、
  「其他金鑰來源」（OpenAI／Anthropic API／Gemini／相容端點）在下、「先不用 AI」。
- **AI 來源經 ntu_easy_llm**（擁有者的套件，0.5.0 的 `ntu_easy_llm.agent`）：新 kind `openai`、`gemini`；`anthropic`、`openai_compat` 也改走它。
  選用相依（`pip install -e .[llm]`），沒裝時用 API 金鑰的來源會說怎麼裝，其他照常。
- `doctor` 印模式、也檢查每個人的加密檔。

### 拿掉
- `src/synox/llm/openai_compat.py`、`anthropic_api.py`（換成 `easy_llm.py`）。


## 0.1.0 — 2026-11-09

第一版，照設計規格 v0（`2026-11-09-synox-design.md`）。

### 有
- **底層**：ISDTeleKitSDK 0.2.1（vendor 在 `vendor/isdtelekit`，`scripts/vendor_sdk.py` 複製、`vendor/VERSION` 記版本與 commit）。
- **AI adapter**：`openai_compat`（OpenAI、Gemini 相容端點、公司閘道、Ollama）、`anthropic`、`claude_code`（本機 `claude -p`，走文字協定）、`fake`（劇本／示範）、`none`。
  不支援 tool-calling 的端點走 JSON-in-text 協定（容錯解析）。用量記在 `data/llm_usage.json`（`/ai_usage`）。
- **AI 助理**（只給擁有者）：指令樹 → 工具；`ai_decision` 唯一判斷；危險的動作送核准卡（✅／❌、10 分鐘、一次性、按下時再 authorize）；
  SKILL.md frontmatter 進系統提示、`skill_read` 讀全文；`/ai`、`/ai_usage`、`/ai_reset`；私訊直接打字＝`/ai`。
- **保管箱**：Fernet＋每檔 scrypt、`*.json.enc`；主金鑰用 Windows DPAPI 保護；壞檔／錯金鑰報錯不清空。
- **pack 載入器**：`packs/*`、`connectors/*` 的 pack.json；kind `python`／`cli`／`connector`；`pack.store`、`pack.path()`。
- **出廠 pack**：notes（`/note`…）、money（`/money`…，超過預算提醒）、remind（`/remind_*`）。connector 設計稿：Google 日曆、Notion、Todoist、Apple 提醒事項。
- **排程**：每 30 秒；提醒與 `/schedule_add`（`Node.wraps`，建立時 via=SCHEDULE、觸發時 via=ROUTINE）；一次性 `date=`。
- **安裝**：`Setup.bat` → `setup/bootstrap.ps1`（py → winget → embeddable zip）→ tkinter 精靈（token、配對碼、AI 來源＋測一下、捷徑、開機自啟）。
  `Start.bat`（看得到的最小化視窗）、`Stop.bat`、`Console.bat`。
- **doctor**：`python -m synox doctor [--offline]`。**打包**：`scripts/make_zip.py`。
- 測試：pytest，不連網、不開埠、不開 Telegram。

### 還沒有
見 README「還沒有」。重點：`/backup`、connector 實作、AI 長期記憶、非 Windows 安裝器、exe。
