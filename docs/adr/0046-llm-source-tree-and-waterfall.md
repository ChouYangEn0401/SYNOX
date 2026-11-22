# ADR 0046：AI 來源改成分步選擇（經 ntu_easy_llm 0.6 的來源目錄）、可選的備援（waterfall）

- 日期：2026-11-23
- 狀態：**已採用**（分支 `feat/llm-source-tree`）。用本機 ntu_easy_llm 主線（0.6.0.dev0，已有 HTTP adapter、`router.Router`、LLOP 與訂閱 adapter）
  測過：測試用的是真的 router，成員是假的來源；真的服務（雲端金鑰、LLOP、訂閱 CLI）還沒實測（`HumanTestList.md`、`VerifyList.json` 有記）。
- 相關：[0007](0007-local-llm-platform.md)（本地模型，**不動**）、[0010](0010-stop-words.md)（停止詞）、[0021](0021-vlm-vision.md)（看圖）、
  [0008](0008-completion-guard.md)／[0014](0014-per-turn-tool-cap.md)（auto 開關看「弱來源」）、[0037](0037-approval-cards-upgrade.md)（核准卡）。
- 程式：`src/synox/llm/sources.py`（目錄、kind=source 的檢查）、`llm/easy_llm.py`（`SourceAdapter`、新路與舊路）、
  `llm/router.py`（`llm.waterfall`、`RouterAdapter`、`AsEasyAdapter`、`FallbackAsk`）、`llm/kinds.py`（錯誤種類 → 中文）、
  `llm/factory.py`、`config.py`（`LLM_KINDS` 多 `source`、`parse_waterfall`）、`agent/fallback_card.py`（「先問我」的卡）、
  `agent/loop.py`（`offer_fallback`）、`agent/auto.py`（`adapter.weak`）、`web/server.py`（目錄、列模型、備援的 API）、
  `wizard/logic.py`（`llm_settings("source", …)`）、`web/static/app.html`（設定頁的分步選擇與備援）。
- 測試：`tests/test_llm_sources.py`、`tests/test_llm_router.py`、`tests/test_settings_catalog.py`。

## 背景

設定頁的「AI 從哪裡來」是一個平的下拉選單（Claude Code、四個金鑰來源、本地、先不用）。ntu_easy_llm（LLM 底層，創始維護者的套件）
0.6 起有一棵**來源分類樹**（本地／遠端 → API 金鑰／訂閱登入 → 服務），每個來源都是同一個 adapter 介面、錯誤都帶**種類**（`.kind`），
還有備援鏈（waterfall）的型別與設定格式。分工的原則是：**SYNOX 是 agent 外殼（agent loop、技能、工具）；中心模型經 ntu_easy_llm 取得；
ntu_easy_llm 是乾淨的底層；SYNOX 只做 UI 與流程整合。** SYNOX 自己的本地 adapter（`llm/local.py`）留在 SYNOX，不搬。
SYNOX 不直接 import LLOP 的套件（LLOP 經 `ntu_easy_llm[llop]`）。

## 決定

1. **設定頁改成分步選擇**：① 來源（本地／遠端服務／先不用 AI）→ ② 認證（遠端才有：API 金鑰／訂閱登入）→ ③ 服務 → ④ 連線欄位 → ⑤ 模型 → ⑥ 細節。
   服務清單來自 ntu_easy_llm 的 `catalog()`；**這台不能用的反灰並寫原因**（例如「LLOP：要先安裝 ntu_easy_llm[llop]」「這個版本還沒有這個來源的 adapter」），
   不藏起來。SYNOX 自己加兩個內建項目：「本地」底下第一個是 **SYNOX 內建的本地模型**（kind=local，ADR 0007 的 context 建議、列出模型、載入／卸載照舊），
   「訂閱登入」底下第一個是 **SYNOX 內建的 Claude Code**（kind=claude_code）。訂閱來源標「只給本人使用」（能不能拿來服務別人還沒定案：**只標、不擋**）。
2. **設定的寫法**：
   - 舊的單一 `llm.kind`（none、fake、local、openai、anthropic、gemini、openai_compat、claude_code）**完全照舊能讀**；
     在新畫面選 OpenAI／Anthropic／Gemini／OpenAI 相容時**照舊存成舊的 kind**（舊版 SYNOX 也讀得懂）。
   - 其他來源（LLOP、訂閱、ntu_easy_llm 的本地 adapter…）存成新的 `kind: "source"`：
     `{"kind": "source", "source": "<分類樹路徑>", "model": "…", "base_url": "…", "api_key": "vault:…", "source_options": {…}}`。
     `source_options` 只收那個來源在目錄上宣告的欄位（例如 `llop_profile`、`transport`、`max_tokens`、`temperature`、`timeout`、`tools`、`effort`），
     照型別轉好；名字像金鑰、值像金鑰的一律擋。不用 `options` 這個名字：kind=local 已經有 `options`（Ollama 的參數，ADR 0019），換來源時會互相帶到。
   - 金鑰跟以前一樣：網頁收到明文就放進保管箱，config 只寫 `vault:…`；交給 ntu_easy_llm 的 Profile 裡只有引用（`synox:llm_api_key`），
     真的金鑰由 SYNOX 在 adapter 要用時給（`resolve_secret`）。
   - **不升 config.json 的 schema_version**：每一份 v1 的檔照舊有效、沒有任何欄位要改寫，所以不需要遷移步驟（ADR 0044 的「改格式」指的是舊檔要轉換）。
     代價：寫了 `kind: "source"` 的 config 給舊版 SYNOX 讀，會在啟動時清楚地說「llm.kind 只能是…」（不服務降級，符合 0044）。
3. **easy_llm.py 改用 0.6 的 `get_adapter`**：`SourceAdapter` 把任何 ntu_easy_llm adapter 包成 SYNOX 的 ChatAdapter。
   - `supports_stop`＝`capabilities().stop`（ADR 0010；不再寫死 False）；`supports_tools`：設定有寫就照它，沒寫＝不是 False 就算支援；
     `supports_vision`：True／False 照 capabilities，`None`（不知道）照 `llm.vision`（on 才算）。圖片改用 ntu_easy_llm 正式的 `types.ImagePart`。
   - 錯誤照 `.kind` 翻成中文（`llm/kinds.py`：額度用完、金鑰失效、太頻繁、連不到、API 連結已更換、加密或金鑰核對失敗…）；
     沒有 kind（0.5）才照狀態碼（`base.http_error`）。SYNOX 的 `LLMError` 多一個 `kind` 屬性（預設 ""，舊的程式不受影響）；
     `llm/local.py` 的「連不到」「無進展逾時」「HTTP 錯誤」也標上種類（訊息不變），備援才判斷得了。
   - 舊的四種 kind：這台的 ntu_easy_llm 有那個來源的新 adapter 就走新路，沒有（0.5，或 0.6 預發布版還沒有 HTTP adapter）照舊走 `agent.chat`（舊路）。
     使用者看不出差別。舊路在 0.6 底下回覆被 max_tokens 切掉時也會帶 `finish`，agent 照 ADR 0012 的規則自動接續（以前雲端來源不會）。
   - `kind=source` 的本地來源（`local/…`）與「鏈裡有本地成員」的備援算**弱來源**（`adapter.weak`），auto 開關（完成宣稱檢查、每輪工具上限…）照本地的規則開。
4. **可選的備援** `llm.waterfall`：
   - **沒寫或 `mode: "off"`＝照舊只用主要來源**（不建 router、不 import 任何新東西）。有寫才用 ntu_easy_llm 的 router。
   - 寫法：`{"mode": "auto|ask|off", "backups": [<跟 llm 同一種寫法>…], "triggers": […], "retry_429", "max_retry_wait_s", "cooldown_s", "ask_ttl_s"}`；
     最多 4 個備援、備援裡不能再有 waterfall、`trust` 永遠不能當觸發條件。**順序就是使用者寫的順序；SYNOX 與 ntu_easy_llm 都不預設任何來源的先後。**
   - **換不換、換誰、重試、冷卻全在 ntu_easy_llm 的 router**；SYNOX 只把自己的 adapter 包成它的成員（`AsEasyAdapter`，成員 id `primary`、`backup1`…）、
     把結果翻回來（換了來源＝回覆後面另一則「⚠️ AI 來源的提醒：已改用 X（原因：額度用完）」，名字用 SYNOX 的）。
   - 成員的能力取**交集**：每個成員都支援原生工具才用原生工具呼叫，否則整條鏈走文字協定（換來源時格式不會對不上）；看圖、停止詞同理。
   - ntu_easy_llm 沒有 router（沒裝、0.5、0.6 預發布版）：只用主要來源，設定頁與 doctor 寫「備援沒有啟動：…」。
5. **ask（先問我）用按鈕卡**（`agent/fallback_card.py`，跟核准卡同一套：按鈕綁 `agent.ai_approve`、Pending 有主人有期限、別人按＝不是你的、卡送下令者的私訊）。
   - 卡上每個候選一顆「改用 X 重送」＋「❌ 不用」。按了「改用 X 重送」＝在 `RouterAdapter.pinned(X)` 裡把剛剛那句重跑一次：
     那一輪每一次呼叫都直接用 X（只在那條執行緒，別的聊天不受影響）。之後的輪照 router 的規則（失敗的那個在冷卻）。
   - **只有這一輪還沒做任何事時才給重送**（第一步就失敗、沒有附件或圖、不是叫醒的那一輪）；做到一半的只說明、不出按鈕，免得重複執行已經做過的工具。
   - SYNOX **不呼叫 router 的 `resume`**：一輪中斷後 SYNOX 重跑整輪（系統提示的時間等等會更新），不接回 router 存的半輪；
     重跑的那一輪工具呼叫可能有好幾次，全部固定用選的那一個比較一致。router 的 `resume(pending, use=, messages=)` 留給之後要「接回半輪」時用。
   - router 的 ask 規則：主要來源還在冷卻時，下一句它會**再問一次**（不默默換）；這是 router 的行為，SYNOX 照出卡。
   - 頻道 AI（負號 chat id）不出卡，照舊只說沒有回應。
6. **網頁 API**（只給擁有者；非 GET 要 CSRF，照既有規矩）：
   - `GET /api/settings/llm/catalog`：目錄（`sources.tree()`）＋現在的選擇＋備援狀態。不連網。
   - `POST /api/settings/llm/models`：列某個來源的模型（ntu_easy_llm 的 `list_models`，唯讀、不載入模型）。會連使用者填的網址，所以是 POST（跟 local-advice 同一個理由）。
   - `POST /api/settings/llm`、`/test`：多收 `choice: "source"`（`source`、`model`、`base_url`、`api_key`、`options`）；舊的 choice 照舊。
   - `POST /api/settings/llm/waterfall`：`{"mode", "keep": [保留的備援序號，照新順序], "add": <跟「存起來」同一種內容>}`；新備援的金鑰放保管箱 `llm_api_key_backup_<n>`。
   - 換主要來源（「存起來」）**不洗掉備援**（`waterfall` 加進沿用的欄位）。
7. **不做**：把 `local.py` 搬進 ntu_easy_llm；改 `vendor/`；在 Telegram／Discord 收金鑰；在 SYNOX 裡註冊 LLOP 帳號（帳號由服務提供者在伺服器那台的終端機做；
   SYNOX 只列這台已註冊的 LLOP 設定檔，旁邊寫「在終端機註冊好再按重新整理」）；視窗精靈（tkinter）與文字版 `synox init` 這一版維持原本的平選單。

## 後果

- 好處：使用者看得到所有來源與「為什麼不能用」；裝了新版 ntu_easy_llm 就自動多出來源，SYNOX 不用改；錯誤講人話而且講得出種類；
  額度用完可以自動或問過再換來源。舊設定一個字都不用改。
- 代價：kind=source 的設定舊版讀不懂（會清楚報錯）；ask 模式重送整句（不接半輪）；備援成員能力取交集，鏈裡有一個不支援原生工具就整條走文字協定。
- 待實測（真機、真帳號）：雲端金鑰來源走新路的回覆與錯誤字句；LLOP（裝 `ntu_easy_llm[llop]`、在終端機註冊後）在目錄上變成可用、列模型、測一下、
  連結更換的錯誤；訂閱來源（裝了登入套件、登入過）只回文字、帶工具時整條走文字協定；備援的自動換與先問我在真的額度用完時的樣子。
