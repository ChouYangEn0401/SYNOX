# 網頁最常被打的地方，SYNOX 各自怎麼擋

- 這是一份**會一直更新**的清單：每做完一包、每發現一個洞，就回來改這裡的「狀態」。下一個接手安全的 session 先讀這份。
- 最後更新：2026-11-14（分支 `feat/secure-apps`，S1–S15 之後＋獨立安全審查第 1 輪的 9 項修正，`fix/security-review-1`）。每一列「已做」都點名至少一個測試；`tests/test_attack_matrix.py` 檢查這裡寫的測試都真的存在。
  實作計畫：[../lab/2026-11-14-stepup-remote-plan.md](../lab/2026-11-14-stepup-remote-plan.md)。
- 相關：[ADR 0025](../adr/0025-guard-core-and-stepup.md)（門禁核心、手機驗證器）、[ADR 0026](../adr/0026-remote-tool-apps.md)（手機入口）、[ADR 0024](../adr/0024-tool-apps-services.md)（工具服務）、[../security.md](../security.md)（給使用者看的整體說明）。
- 狀態：**已做**＝有程式、有測試｜**計畫**＝設計好了、排進哪一包｜**缺口**＝知道、還沒有對策｜**不適用**＝SYNOX 沒有那種東西。
- 怎麼更新：做完一包，把那一列改成「已做」並在「在哪」補上測試的位置（`tests/檔名::測試名`）。S15 會加一個測試，檢查這份文件裡寫的測試都真的存在。

## 三個面，風險不一樣

| 面 | 誰連得到 | 今天有沒有 |
|---|---|---|
| 主機台（`127.0.0.1:8830`） | 只有這台電腦 | 有 |
| 工具服務（`127.0.0.2:<埠>`） | 只有這台電腦 | 有（[ADR 0024](../adr/0024-tool-apps-services.md)） |
| 手機入口（臨時的公開網址 → 遠端閘門） | **網際網路上的任何人都敲得到門**，開著的那幾十分鐘 | 有（ADR 0026；預設關，真的通道要在別台電腦實測） |

## 清單

| # | 攻擊 | 白話：他怎麼做 | SYNOX 怎麼擋 | 在哪 | 狀態 |
|---|---|---|---|---|---|
| 1 | 注入（SQL、指令、範本） | 在輸入裡夾程式碼，讓伺服器把它當指令執行 | 沒有 SQL；不把輸入接進 shell（子程序一律用參數清單）；工具的值以 `-` 開頭的拒絕；所有欄位值先過一份基本檢查（人打字、AI、工具畫面、手機入口同一份） | `guard/inputs.py`、`packs/kit.py` 的 `check_values`；`tests/test_guard_inputs.py::test_money_add_with_nul_is_refused_with_the_fixed_sentence`、`tests/test_app_site.py::test_action_bad_values` | 已做 |
| 2 | 路徑穿越 | 用 `../`、編碼過的斜線，讀到不該讀的檔 | 工具的畫面檔只從記憶體的快照回應，請求碰不到硬碟；路徑先正規化、白名單 | `guard/inputs.rel_path`、`web/apps/site.py`、`guard/http.py`；`tests/test_guard_inputs.py::test_rel_path_rejects`、`tests/test_app_site.py::test_static_paths` | 已做 |
| 3 | 偽造請求（CSRF） | 讓你的瀏覽器在你不知道的時候替他送請求 | 主機台：每個登入一個防偽造 token＋來源要跟自己一樣＋別的網頁送來的 `/api/` 一律拒；工具服務：不用 cookie、每個請求帶標頭 token；遠端：Strict cookie＋對來源＋標頭 token | `web/server.py`、`web/apps/site.py`、`web/remote/gate.py`；`tests/test_web.py::test_api_needs_session_and_csrf`、`tests/test_web_hardening.py::test_api_from_other_sites_is_refused`、`tests/test_app_site.py::test_origin_rules` | 已做 |
| 4 | 跨站腳本（XSS） | 把腳本塞進頁面，在你的瀏覽器裡用你的身分做事 | 一頁、沒有外部資源、每次回應一個 nonce 的內容安全政策、畫面上的字一律 `textContent`；工具畫面：沒有內嵌腳本、不能連外（安裝時檢查＋CSP） | `web/server.py`（`render_app`）、`packs/appscan.py`、`web/apps/site.py`；`tests/test_web.py::test_app_page_has_nonce_csp_and_no_inline_handlers`、`tests/test_app_manifest.py::test_appscan_blocks` | 已做 |
| 5 | 繞過登入 | 找到一條忘了檢查登入的路 | 主機台：`/api/*` 在一個地方統一檢查；權限只有一個交會點 `policy.decide`；工具服務每個請求重查登入；遠端：路由白名單，其他一律 404 | `web/server.py`、`policy.py`、`web/apps/site.py`、`web/remote/gate.py`；`tests/test_app_site.py::test_login_is_checked_every_time`、`tests/test_remote_gate.py::test_after_entering` | 已做 |
| 6 | 偷登入（session hijack） | 拿到你的 cookie 或連結，冒充你 | cookie 是 HttpOnly、只存雜湊；登入連結一次性、要按確認；**敏感動作另外要手機驗證器，而且解鎖綁那一個登入** | `web/tokens.py`；`guard/stepup.py`；`tests/test_stepup_core.py::test_unlock_is_bound_to_the_entry`、`tests/test_stepup_web.py::test_sensitive_routes`；主機台的敏感動作預設就擋（`tests/test_security_review_1.py::test_sensitive_routes_are_deny_by_default`）；金鑰與備用碼只給真的從這台電腦連進來的請求（`tests/test_security_review_1.py::test_is_local_needs_loopback_peer_and_no_public_url`）；驗證器資料讀不出來＝擋住，不是當作沒設定（`tests/test_security_review_1.py::test_unreadable_store_fails_closed`） | 已做 |
| 6b | 本機別的程式收走主機台的 cookie | 同一台電腦的別的帳號或程式去聽 `127.0.0.1` 的某個埠，再讓你的瀏覽器連過去 | 工具服務改用另一個本機位址、不用 cookie（不再提供誘餌）；主機台本身還沒解（同名的假 cookie 擋不住真的那個） | `docs/lab/issues-to-open.md` 第 5 筆；`tests/test_web_hardening.py::test_duplicate_session_cookies` | **缺口**（手機驗證器讓「拿到 cookie」不等於「什麼都能做」，是減輕不是解決） |
| 7 | 暴力猜（密碼、驗證碼、連結） | 一直試 | 連結 256 位元；驗證碼錯 5 次鎖 15 分鐘並通知本人；遠端錯 5 次整條入口收掉；每分鐘請求數有上限 | `guard/limits.py`、`guard/stepup.py`、`web/remote/manager.py`；`tests/test_stepup_core.py::test_five_bad_lock_notify_once_then_unlock_after_15_min`、`tests/test_remote_gate.py::test_five_bad_codes_close_and_notify_once`、`tests/test_remote_gate.py::test_rate_limits`。驗證碼只收 ASCII 數字（怪數字也是有計次的同一個失敗，`tests/test_security_review_1.py::test_nonascii_digits_are_a_counted_fixed_failure`）；擁有者進門之後，外人亂敲不會把入口收掉（`tests/test_security_review_1.py::test_outsider_cannot_close_an_entered_session`） | 已做 |
| 8 | 重放 | 把攔到的驗證碼或連結再送一次 | 一組碼只過一次（重開也記得）；連結的鑰匙只能換一次登入；交接票只能用一次 | `guard/stepup.py`、`web/remote/gate.py`、`web/apps/sessions.py`；`tests/test_stepup_core.py::test_replay_survives_restart_and_old_counter_is_bad`、`tests/test_remote_gate.py::test_key_once_expired_and_identical_failures`、`tests/test_app_site.py::test_entry_and_ticket_rules` | 已做 |
| 9 | 請求走私 | 用兩種互相矛盾的長度標頭，讓前後兩台伺服器看到不同的請求 | 遠端閘門：有 `Transfer-Encoding` 一律拒、`Content-Length` 重複或不合一律拒 | `guard/http.py`（`GuardedHandler`）；`tests/test_guard_http.py::test_handler_refusals` | 已做（主機台只在本機，沒有前面那一台，風險低） |
| 10 | 塞爆（超大的內容、慢慢送、開一堆連線） | 讓程式忙不過來或記憶體用光 | 主機台：內容上限 256 KB；遠端：標頭 16 KB、內容 64 KB（先對大小才讀）、15 秒逾時、同時 16 條、被拒太多次就收掉 | `web/server.py`（`MAX_BODY`）；`guard/http.py`；`tests/test_guard_http.py::test_rejects`、`tests/test_remote_gate.py::test_too_many_rejects_close`、`tests/test_security_review_1.py::test_too_many_connections_gets_a_real_429`、`tests/test_security_review_1.py::test_second_open_during_slow_start_is_busy_and_nothing_leaks` | 已做 |
| 11 | DNS rebinding | 讓一個外面的網域名稱指到你的本機位址，騙瀏覽器把它當同一個站 | 檢查 `Host`：本機自動登入只認 `127.0.0.1`／`localhost`；工具服務與閘門每個請求都對 `Host` | `web/server.py`（`_local_owner_navigation`）、`web/apps/site.py`、`guard/http.py`；`tests/test_app_site.py::test_host_must_be_exact`、`tests/test_remote_gate.py::test_cookie_and_host_and_origin_checks` | 已做（**主機台的一般 API 沒有對 `Host`**，靠 cookie、token 與來源檢查擋：小缺口） |
| 12 | 伺服器被騙去連別的地方（SSRF） | 給一個網址，讓伺服器替他去連內部的東西 | 連網只在使用者按按鈕時、目的地寫死；遠端 MCP 只連宣告的 https；通道程式的目的地是 SYNOX 自己寫死的本機閘門位址 | `packs/catalog.py`、`packs/mcp_http.py`、`web/remote/tunnel.py`；`tests/test_remote_tunnel.py::test_argv_env_and_url` | 已做。宣告了連網的工具自己要連哪裡沒有白名單：**缺口，不在這一輪** |
| 13 | 開放轉址 | 用你的網址當跳板把人導去壞網站 | 登入之後只轉到固定的 `/#chat`；交接只轉到 `127.0.0.2:<埠>/`；遠端進門之後只轉到固定的 `/` | `web/server.py`（`login_post`）、`web/apps/web_api.py`、`web/remote/gate.py`；`tests/test_app_console.py::test_handoff`、`tests/test_remote_gate.py::test_enter_success_cookie_flags_and_ticket` | 已做 |
| 14 | 點擊劫持 | 把你的頁面藏在他的頁面底下，騙你點 | `X-Frame-Options: DENY`、`frame-ancestors 'none'`、COOP | `web/server.py`、`web/apps/site.py`、`web/remote/gate.py`；`tests/test_web_hardening.py::test_coop_everywhere_corp_on_json`、`tests/test_app_site.py::test_no_cookie_at_all` | 已做 |
| 15 | 不安全的還原（deserialization） | 送一包特製的資料，讓程式在讀它的時候執行東西 | 只讀 JSON；沒有 pickle、沒有 YAML 載入；外面送來的 JSON 另外限深度、不准重複鍵 | `guard/inputs.json_object`；`tests/test_guard_inputs.py::test_json_object_rejects` | 已做 |
| 16 | 檔案上傳 | 上傳一個會被執行的檔 | 上傳只有 `.synoxpack`：大小上限、解開上限、五關、擁有者按確認才裝；遠端沒有任何上傳 | `packs/admin.py`、`docs/security.md`「五關」；`tests/test_packs.py::test_manifest_errors` | 已做 |
| 17 | 供應鏈 | 你裝的工具或它用的套件本身是壞的 | 五關、信任層級、檔案鎖、升級紅字；通道程式要擁有者核准雜湊、每次啟動前再對 | `packs/scan.py`、`tier.py`、`lock.py`、`web/remote/binary.py`；`tests/test_upgrade.py::test_diff_marks_widening_red`、`tests/test_remote_tunnel.py::test_manager_checks_binary_before_running` | 已做。套件內容不檢查、沒有簽章：**缺口，不在這一輪** |
| 18 | 騙 AI（提示注入） | 在訊息、附件、工具回的字裡寫指令，讓 AI 替他做事 | 危險的事 AI 一定先送確認卡；**AI 沒有任何工具收驗證碼、不能開服務或手機入口**；收緊的指令不在 AI 的工具清單 | `agent/approve.py`、`guard/scope.py`、`policy.py`；`tests/test_agent.py::test_danger_needs_card_then_executes`、`tests/test_stepup_policy.py::test_ai_has_no_unlock_tool_and_unlock_cannot_be_scheduled`、`tests/test_scope.py::test_human_only_command`；`stepup` 列的指令 AI 叫也一定走確認卡、按的人要解鎖（`tests/test_security_review_1.py::test_ai_call_of_stepup_command_needs_card_and_unlock`） | 已做。工具的名稱與簡介直接進系統提示：**缺口，不在這一輪** |
| 19 | AI 或排程冒充人 | 讓程式自己去做「只有人該做」的事（例如把危險指令排進半夜） | `interactive` 的不能排、不給 AI；**每個動作帶來源，收緊的指令只收人**；開服務只收網頁與打字 | `guard/origin.py`、`guard/scope.py`、`web/apps/manager.py`；`tests/test_guard_origin.py::test_ai_tool_call_is_ai_on_behalf_of_telegram`、`tests/test_app_commands.py::test_schedule_and_ai_cannot_open` | 已做 |
| 20 | 帳號被盜（Telegram、瀏覽器登入） | 拿到你的帳號，他就是你 | 手機驗證器：危險的動作與敏感的設定要多一組不經過 Telegram 的碼（設定了才有） | `guard/stepup.py`；`tests/test_stepup_policy.py::test_typed_danger_blocked_then_unlock_then_continue` | 已做（沒設定驗證器的人：跟以前一樣沒有擋） |
| 21 | 通道把東西暴露出去 | 臨時網址被猜到、被轉貼、忘了關、通到不該通的地方 | 通道只接閘門、閘門只認一個工具；一次性連結＋進門再一組碼；時間到、閒置、沒人進門都關；主機台永遠不經過通道 | `web/remote/`；`tests/test_remote_manager.py::test_idle_no_entry_and_tunnel_down`、`tests/test_remote_gate.py::test_same_code_as_open_does_not_enter` | 已做（實際的通道要在別台電腦實測） |
| 22 | 中間的人看得到內容 | 通道業者看得到經過的明文 | 擋不了。對策是範圍：遠端不能匯出、不能做危險動作、時間短；說明裡明講 | ADR 0026 §1、「擋不住的」；`tests/test_app_site.py::test_remote_origin` | **接受的風險** |
| 23 | 錯誤訊息洩漏 | 從錯誤頁看出版本、路徑、程式結構 | 主機台的 500 只說例外的類別名；工具服務 log 不寫例外的訊息；遠端一律固定的幾句 | `web/server.py`、`web/apps/audit.safe_trace`、`guard/http.reply`；`tests/test_app_site.py::test_tool_errors`、`tests/test_guard_http.py::test_reply_is_fixed` | 已做 |
| 24 | 紀錄檔被塞假資料 | 在路徑或參數裡夾換行，偽造紀錄行 | 稽核沒有自由文字：只有固定代碼、白名單的名字、數字 | `guard/audit.py`、`web/apps/audit.py`；`tests/test_guard_audit.py::test_only_numbers_and_identifiers`、`tests/test_app_site.py::test_audit_lines` | 已做 |
| 25 | 試算表公式注入 | 匯出的檔裡某一格以 `=` 開頭，別人用試算表打開時被當成公式 | 匯出一律用 SYNOX 給的 `kit.csv_bytes` | `packs/kit.py`；`tests/test_app_manifest.py::test_csv_bytes`；數字欄位不收 nan／inf（`tests/test_security_review_1.py::test_kit_number_rejects_nonfinite_and_nonascii`） | 已做 |
| 26 | 同一台電腦的別人 | 另一個 Windows 帳號直接開 `http://127.0.0.1:8830/` | 個人版的本機自動登入會讓他進來（`web.local_auto_login`）；手機驗證器讓他進來之後做不了敏感的事 | `docs/debug-notes.md`；`guard/stepup.py`；`tests/test_stepup_web.py::test_sensitive_action_does_not_happen` | **缺口**（共用電腦的人請關掉自動登入）；驗證器是減輕 |
| 27 | 惡意的工具程式 | 你裝的 Python 工具本身就是壞的，在 SYNOX 的程序裡跑 | 裝之前的報告與信任層級；伺服器版第三方 Python 工具只給擁有者 | `docs/security.md`「五關」「沒有做的保護」 | **缺口**（沒有程序內的隔離；門禁核心擋不了它） |

## 這一輪之後還開著的（照嚴重程度）

1. **6b／26**：主機台的登入只靠 cookie，本機的其他帳號與程式有辦法拿到。手機驗證器把後果從「什麼都能做」縮到「看得到、做不了敏感的事」，但看得到本身就是問題。要另開一張問題單。
2. **27、17**：程序內的 Python 工具沒有隔離；套件與工具沒有簽章。
3. **22**：通道業者看得到明文。
4. **18**：第三方寫的名稱與簡介進系統提示。
5. **11**：主機台的一般 API 沒有對 `Host`。
