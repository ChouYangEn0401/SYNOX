# SYNOX — AGENT.md

給 AI 與接手的人看的地圖（原始設計規格放在維護者的私有資料夾，不在這個 repo）；
給人看的在 [../README.md](../README.md)。

## Commands

- 安裝（開發）：`py -3.11 -m venv .venv` → `.venv\Scripts\python.exe -m pip install -e .[dev]`；
  用 API 金鑰的 AI 要再裝 ntu_easy_llm（見下面「ntu_easy_llm」）
- 測試：`.venv\Scripts\python.exe -m pytest -q`（2026-11-12 約 1500 個、3～4 分鐘；不連網、不開 Telegram、不叫 `claude`）。
  例外：`tests/test_web.py::test_port_already_in_use_is_a_bind_failure` 會在 127.0.0.1 暫時 listen 一個 port（測獨佔綁定）；
  不想開任何 port 的機器加 `--deselect tests/test_web.py::test_port_already_in_use_is_a_bind_failure`
- 終端機：`.venv\Scripts\python.exe -m synox console`（`--llm fake` 換假 AI；沒有 config.json 用示範設定）
- 健康檢查：`.venv\Scripts\python.exe -m synox doctor --offline`
- 重新 vendor SDK：`.venv\Scripts\python.exe scripts\vendor_sdk.py`（`--sdk` 或 `ISDTELEKIT_SDK`）；打包：`scripts\make_zip.py [--tools <Libs dist>]`
- 文字版設定引導：`.venv\Scripts\python.exe -m synox init`（`--non-interactive`、`--dry-run`）；工具庫：`-m synox tools list｜install <名字>`
- 乾淨安裝的模擬：`.venv\Scripts\python.exe scripts\clean_room_check.py [--tools <Libs dist>｜--libs <SYNOX_Libs>]`（暫存資料夾、
  清掉 SYNOX_*／PATH／使用者資料夾；重用這個直譯器，不建 venv、不 pip、不連網）。發佈（lock、wheelhouse、安裝程式）：[adr/0003](adr/0003-distribution-git-clone-and-installer.md)、
  [handoff/clean-machine-test.md](handoff/clean-machine-test.md) B-1
- 對話助理的離線評測：`.venv\Scripts\python.exe scripts\eval_assistant.py [--split tune|holdout|all] [--replies <資料夾>] [--json <檔>]`
  （照劇本重放在真的 AgentLoop 上、假工具、不叫真的 AI；怎麼新增題目：[../evals/assistant/README.md](../evals/assistant/README.md)）
- 主控台是 cp950：跑 Python 前 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`

## Map

| Path | Role |
|---|---|
| `vendor/isdtelekit/` | ISDTeleKitSDK 的**原樣**複製（版本與 commit 在 `vendor/VERSION`）。不要改；要不同的行為就在 `src/synox` 寫轉接 |
| `src/synox/__main__.py` | `python -m synox run｜console｜wizard｜init｜tools list｜tools install <名字…>｜doctor｜stop｜open（＝web-login）｜about｜tips [--all]｜install <檔> [--yes] [--trust-publisher <名字>]｜packs status｜packs lock --approve <name> [--trust-publisher <名字>] [--runtime container|host]｜packs runtime <name> container|host｜packs env rebuild <name>`（install 也收 `--runtime`） |
| `src/synox/app.py` | `build(config, home=, adapter=, vault=, config_path=)`：SDK `build_app` → basics/help → `packs.load_all` → `agent.install` → `schedule.install` → `web.install` |
| `src/synox/config.py` | `SynoxConfig`＝SDK `BotConfig`＋`mode`（personal｜server）／`llm`／`vault`／`packs`／`policy`；路徑相對 SYNOX 資料夾（`ROOT`＝`default_root()`：SYNOX_HOME → 原始碼版面 → 目前資料夾，`ROOT_SOURCE` 記哪一種，doctor 會印） |
| `src/synox/policy.py` | `decide`（權限唯一交會點）、`parse_policy`（`policy.roles` 能力上限，第 1 關式檢查）、`group_policy_for`（loader 用）、`ceiling`／`fits`；bot 範圍 `bot_scope`／`using_bot`／`current_bot`／`run_as`；`install`（把 decide 接到 SDK 的 `registry.authorize`） |
| `src/synox/sandbox.py` | 運行空間（PERM-7）：`Sandbox.wrap(argv, env, cwd, grants)`、`Grants`、後端 none／jobobject／bwrap／systemd／container（每個 pack 自己的，S1）／appcontainer（介面）、`set_factory`／`sandbox_for`、`box_for`／`view_for`／`set_engine_which`／`set_container_factory`、`grants_for`、`data_scope`（推斷集中處）、`trust_of`、`restricted_reason`、`doctor_line`；jobobject 的 launcher（`python -I sandbox.py jobobject …`） |
| `src/synox/discord/scope.py` | bot 範圍報告：`/bot_status`（`install`）、`report`／`lines`（doctor 也用）、`REASONS`（不會出現的原因，可擴充）、`channel_line`（頻道型的收訊設定） |
| `src/synox/discord/` 其他 | `bots.py`（BotSpec、設定檢查；頻道型 `guilds`／`role_map`／`trigger`／`rate_per_minute`）、`events.py`（`parse_event` 私訊、`parse_room_event` 頻道）、`rest.py`（`DiscordChannel`）、`gateway.py`（`INTENTS`／`CHANNEL_INTENTS`、`on_ready`）、`__init__.py`（`install`、`DiscordEntry`、`RoomEntry`／`RoomReply`／`RoomThrottle`、`MultiHome`、配對）。見 [discord.md](discord.md) |
| `src/synox/llm/` | `base.py`（`ChatAdapter`、`Message`、`Reply`（含 `warnings`）、`ToolCall`、`ToolSpec`）、`easy_llm.py`（openai／anthropic／gemini／openai_compat，經 `ntu_easy_llm.agent`，lazy import）、`claude_code`、`local.py`（kind=local 本地模型，SYNOX 內建、只用 urllib：`LocalAdapter`（ollama 的 `/api/chat` NDJSON、vllm／lmstudio／other 的 `/v1/chat/completions` SSE、無進展逾時＋總上限、截斷提醒）、`validate`（config 檢查）、`host_kind`／`url_warning`、唯讀的 `inspect`／`probe`、`report_lines`；[adr/0007](adr/0007-local-llm-platform.md)）、`local_advice.py`（context-size 建議：純函式 `advise`、`kv_bytes_per_token`、`system_ram`、`from_report`、`lines`、`option_label`）、`fake`、`textproto`（文字協定；`strip_think`、`parse_leaked`／`LEAK_MARKERS`＝救回文字裡的 `<tool_call>`／Qwen XML／MiniMax 呼叫，[adr/0009](adr/0009-leaked-tool-call-recovery.md)）、`factory.make_adapter`（`opener=` 給測試；`easy_timeout`：`llm.timeout`，openai_compat 指到 loopback／私網預設 450 秒） |
| `src/synox/vault/` | `vault.py`（Fernet＋每檔 scrypt、`*.json.enc`；`for_user(id)`＝伺服器版每人的保管箱，HKDF 衍生）、`keyring.py`（DPAPI 包住主金鑰 `data/.synox.key`） |
| `src/synox/packs/` | `manifest.py`（pack.json v2 檢查＝第 1 關；`surfaces`／`data`（`_check_scope`、`default_data`、`cli_templates`）；`requires.synox`＝`synox_problem`、`requires.env`→`secret_env_names`、`fields[].kind`、`auth.fields`；工具頁用的 `category`、穩定度 `stage`（`STAGES`、`stage_label`／`stage_text`，沒寫＝alpha；/help 標題用 `loader.help_title`）、strict 時的說明欄位型別 `_field_doc_problems`、提醒 `doc_warnings`）、`secrets.py`（pack 的 secret：`PackSecrets`、`managed_fields`）、`scan.py`（ast 靜態掃描＝第 2 關；`_check_data_python`／`_check_data_cli`＝data 宣告的規則；`ImportContext`＝import 的來源、`_fold`＝拼出來的字串，審查 C #C5）、`lock.py`（`data/packs.lock`＝第 3 關；`trust`、`trust_of`）、`loader.py`（掃 `packs/`（＋`packs.dirs`）、`Pack`／`PackStore`／`store.of(user)`、`group_policy`、`surface_policy`（沒有 channel＝private_only）、`shared_write_admin`、cli 代換與 `build_argv`）、`kit.py`（照位置填的指令）、`envs.py`（`runtime.python／node = "auto"`：`Builder.plan`／`build(m, jobs, on_done)` 建 `data/envs/<pack>/`、`python_of`／`node_of`／`node_env` 給 loader 代換、`env_problem` 給 loader／doctor；`set_factory` 換實作） |
| `src/synox/packs/mcp.py` | kind=mcp stdio（P4a）：`Session`（JSON-RPC over stdio、讀執行緒、`request`／`notify`）、`handshake`（initialize／initialized／tools/list）、`spawn`（Windows Job Object）、`McpPool`（每個 key 一個長駐程序、`reap()` 閒置回收、`close_all`；`clock`／`spawner` 可換）、`Scope`／`PerUserScope`／`SharedScope`（介面）、`shape_of`（inputSchema → fields）、`to_arguments`、`needs_confirm_of`、`render_result`、快取 `data/mcp/<pack>.tools.json`、`doctor_notes`、`Backend`／`StdioBackend`（連法）、`redact`、`install`（loader 叫，兩種連法共用） |
| `src/synox/packs/mcp_http.py` | kind=mcp http（P4b）：`HttpSession`（Streamable HTTP：POST JSON-RPC、JSON／單次 SSE 回應、`Mcp-Session-Id`、不跟轉址、DELETE 收尾）、`HttpBackend`（Bearer token 或 OAuth）、`parse_sse`、`new_session`（測試換掉） |
| `src/synox/packs/oauth.py` | 遠端 MCP 的 OAuth（選配）：`Flow`（PKCE＋state、貼回網址、換／更新 token 存 PackSecrets、`/<群組>_login／_code／_logout`）、`Listener`／`PasteListener`／`LoopbackListener`（只有介面，叫了就拒） |
| `src/synox/sdk/` | 給 pack 作者：JSON 信封、`Pack.load`、`init_pack`、`zip_pack`；`synox-sdk init｜check｜zip`（`python -m synox.sdk`）。說明 [sdk.md](sdk.md) |
| `src/synox/agent/` | `tools.py`（葉節點 → ToolSpec；`CANNOT_DO`／`cannot_do_spec`＝「做不到」的偽工具，[adr/0011](adr/0011-cannot-do-exit.md)）、`loop.py`（`ai_decision`、一輪、用量；停止詞、救回洩漏的呼叫、連續失敗、步數用完的總結）、`claims.py`（完成宣稱檢查：`verdict`／`claims`／`forged`／`progress_only`、`Evidence` 證據帳本、修正字句、`guard_on`（auto＝本地／私網來源）；[adr/0008](adr/0008-completion-guard.md)）、`validate.py`（第 4 關呼叫驗證）、`delimit.py`（第 5 關工具結果分隔符）、`budget.py`（伺服器版成員每月額度；`BotPool` 頻道型 bot 一池）、`room.py`（頻道 AI：`RoomAgent`、`redact_reply`）、`capture.py`、`approve.py`（核准卡）、`skills.py` |
| `src/synox/evals/`、`evals/assistant/` | 對話助理的離線評測（量，不改助理）：`cases.py`（題目格式、`DISTRIBUTION`、範例網域檢查）、`fake_tools.py`（假工具掛成指令樹的葉節點）、`replay.py`（`ReplayAdapter` 照劇本回話、`run_case` 用 `app.build` 建暫存的整支 SYNOX 跑真的 `AgentLoop`、不同步＝`replay_mismatch`、`stamp`）、`checks.py`（硬檢查、拒絕／替代標記、簡體字表；`claimed_without_call` 每題都跑、`must_call` 的 `any_of`）、`report.py`（決定性的文字＋JSON）；題目與劇本在 `evals/assistant/`（不進發佈物：`make_zip.ROOT_ONLY_DIRS`）。**沒有真跑的路徑**，要加先看 README 最後一節 |
| `src/synox/runtime/` | 常駐的排程迴圈與常駐助理（[adr/0001](adr/0001-runtime-loop-heartbeat-mother-session.md)，網頁合約 [runtime-api.md](runtime-api.md)）：`loop.py`（`RuntimeLoop`／`Task`：每 5 秒看、每個任務自己的執行緒、逾時、退避、連續 5 次失敗通知一次、`report`、`peer_states`、`data/runtime/state.json`）、`heartbeat.py`（`system.heartbeat`、快照與「沒事別吵」的規則）、`mother.py`（`MotherSession`：沒有工具、自己的記憶在保管箱、`NOTIFY:`／`SOUL+:` 格式）、`soul.py`（`SoulStore`：保管箱、追加規則、稽核、超過上限時挑筆記）、`ledger.py`（`SoulLedger`：助理筆記的來歷、等擁有者確認的提議、收起來的、整理 `system.soul_tidy`、遺忘、匯出；[adr/0005](adr/0005-soul-ledger-memory-provenance-review.md)）、`activator.py`（`Activator`／`Rule`：狀態一變照規則觸發下一件、靜態找循環、連動串的層數與總件數、每條規則的冷卻與每小時上限、全部的總量、斷路器與重設、留給心跳的待處理；[adr/0004](adr/0004-activator-event-driven-rules.md)）、`settings.py`（config `runtime` 的預設與檢查，含 `activator.rules`）、`web_api.py`（`/api/runtime/...`）、`__init__.py`（`install`、`report`／`ingest_envelope`／`peer_env`，`Runtime.use_fakes` 給測試） |
| `src/synox/schedule/` | `store.py`（伺服器版 `store.of(user)` 每人一份、`all_stores()`）、`runner.py`（`tick` 由 runtime 的任務 `system.schedule` 每 30 秒叫；沒有 runtime 才自己開執行緒；via=ROUTINE，以檔案主人的身分跑）、`commands.py`（`install_system_remind`＝系統指令「⏰ 提醒（系統）」`/remind_*`，app.build 在載入 pack 之前掛；`/schedule_*`） |
| `src/synox/web/` | Web UI：`server.py`（`WebUI.route(method, path, headers, body, session)` 做全部判斷；`_Handler` 是薄殼；只綁 127.0.0.1）、`channel.py`（`WebChannel`＝SDK Channel）、`chats.py`（每人的對話紀錄，密文）、`tokens.py`（一次性登入連結、cookie session）、`static/app.html`（一頁、vanilla JS）、`__init__.py`（`install`、`/web`、`/web_off`） |
| `src/synox/schedule/` | `store.py`（伺服器版 `store.of(user)` 每人一份、`all_stores()`）、`runner.py`（30 秒、via=ROUTINE，以檔案主人的身分跑）、`commands.py`（`/remind_*`＝⏰ 提醒（系統）、`/schedule_*`） |
| `src/synox/web/` | Web UI：`server.py`（`WebUI.route(method, path, headers, body, session)` 做全部判斷；`_Handler` 是薄殼；只綁 127.0.0.1）、`channel.py`（`WebChannel`＝SDK Channel）、`chats.py`（每人的對話紀錄，密文）、`tokens.py`（一次性登入連結、cookie session）、`static/app.html`（一頁、vanilla JS）、`__init__.py`（`install`、`/web`、`/web_off`）；工具頁：`toolpage.py`（指令卡與參數表單的資訊 `command_info`、群組排版 `effective`／`parse_layout`、每人的偏好 `UserPrefs`＝`data/web_prefs/<id>.json.enc`）＋`static/tools.js`／`tools.css`（`server.render_app` 換掉 app.html 的 `<!-- include: … -->`，同一個 nonce） |
| `src/synox/present/` | 呈現層（[presentation.md](presentation.md)，`config.json` `presentation.enabled`，**預設關**）：`blocks.py`（區塊、Span、信任等級 system／assistant／external、`safe_url`、`visible`）、`markdown.py`（Markdown／純文字 → 區塊，不用第三方套件、不丟例外）、`telegram.py`／`discord.py`／`web.py`（輸出；切割在 `split.py`、表格降級在 `tables.py`、寬度在 `width.py`）、`__init__.py`（`render`、`deliver`）。只接 AI 回覆（`AgentLoop.say`、`RoomAgent.say`）；按鈕群／確認卡只有 system 才是真的按鈕；網頁送 JSON 區塊給 `static/blocks.js`（textContent） |
| `src/synox/packs/admin.py` | `.synoxpack`：stage（zip 檢查＋第 1、2 關；記 zip 的執行位元、不解出 `__pycache__`）→ install_staged（再驗一次＋T2 要 `trust_publisher`＋第 3 關寫鎖）／移除到 `packs/_removed/`／`reload()`（Web UI、`synox install` 共用）；`format_tier`／`red`＝T2 的紅字段 |
| `src/synox/packs/tier.py` | 信任層級（SDK P7）：`assess`（T0／T1／T2＋掃不到內容的檔、外部程式、runtime auto 套件）、`warning_lines`、`confirm_problem`（publisher 一字不差）、`reconfirm_reasons`（升級）、`lock_fields` |
| `src/synox/packs/upgrade.py` | 同名再裝＝升級：`staged_upgrade`（「改了什麼」、semver 版本檢查，權限變大的標 alert＝紅字）→ `upgrade_staged`（舊的搬到 `_removed/<name>-<版本>-<時間>`＋旁邊留舊鎖、鎖換新）；`rollback`（`python -m synox packs rollback <name>`）。資料不在 pack 資料夾，不動；資料 schema 升級由 pack 自己負責 |
| `Install-Pack.bat`、`scripts/pack_zip.py` | 點兩下 `.synoxpack` 的落點（精靈勾了才在 HKCU 登記）；打包 |
| `src/synox/backup.py` | `export_backup`／`read_backup`：data/ 的 zip 用保管箱主金鑰加密（`Vault.encrypt_bytes`） |
| `src/synox/wizard/` | `pages.py`（tkinter 畫面：這台給誰用 → token → 配對 → AI → 完成）、`logic.py`（寫 config、mode、AI 頁的 helper、金鑰進保管箱；`env:` 照原樣）、`telegram_probe.py`（getMe、配對碼）、`shortcuts.py`；`init_cli.py`（文字版 `synox init`：同一份 config，`Prompter` 可換、`--non-interactive`／`--dry-run`）、`tools.py`（工具庫：位置規則＝`packs.library` → `<SYNOX>/tools`、讀 `index.json`、`file_of` 對檔名與 sha256、`pick` 名字或組合；`packs/library.py` 也用它） |
| `scripts/` 發佈 | `make_zip.py`（`release_files`＝會發出去的檔案，`--tools`／`--wheelhouse`）、`lock_deps.py`（`requirements.lock`，只讀已裝的版本與本機 wheel）、`stage_installer.py`（安裝程式的 stage：只複製）、`clean_room_check.py`（乾淨副本＋清掉這台的環境跑一遍）；`setup/installer/synox.iss`（Inno Setup，每個使用者自己裝） |
| `src/synox/doctor.py` | 健康檢查（不改任何檔、不產生金鑰） |
| `src/synox/health/` | 工具健康（[tool-health.md](tool-health.md)）：`failure.py`（失敗信封 v1、類別碼表、正規化、`ai_line`）、`state.py`（狀態機、指紋）、`store.py`（`data/health/tools.json.enc`，保管箱）、`settings.py`（config `health`）、`__init__.py`（`HealthRegistry`、fail open 的入口 `observe_*`／`hidden`、runtime 任務 `system.health`）。loader（cli）、`packs/mcp.py`、`agent/loop.py` 只經這些入口；權限仍只看 `policy.decide` |
| `src/synox/brand.py` | 終端機門面：歡迎畫面（`show_banner`；`BANNER_COMMANDS`＝沒參數／run／open／wizard／init／doctor／about）、`about_text`、`TIPS`。只在互動終端機印；`--quiet`、`SYNOX_NO_BANNER`、`CI`、管線＝不印（既有輸出一個字都不變），`TERM=dumb`＝一行，`NO_COLOR`＝不上色；Windows 主控台 code page 不是 65001（cp950）或 `SYNOX_ASCII=1`＝ASCII logo。預覽 `docs/ui/cli-welcome.txt`（`scripts/make_cli_welcome.py`） |
| `packs/` | **出廠是空的**（2026-11-12，[../legacy/builtin-packs.md](../legacy/builtin-packs.md)）：使用者裝的工具的落點（`PACK_DIRS` 只有它），只有 `README.md` 進 git。所有工具的正本在 **SYNOX_Libs**（工具庫，另一個 repo；ADR 在它的 `docs/adr/0001`） |
| `connectors/` | **只剩 README**（2026-11-12，[../legacy/connectors.md](../legacy/connectors.md)）：以前的 notion、todoist、google-calendar、apple-reminders 連同測試搬到 SYNOX_Libs；loader 不再掃這裡、`BUNDLED` 是空的 |
| `src/synox/packs/library.py` | 「還沒裝任何工具、去哪裡裝」：`installed_tools`（不算 `BUNDLED`；現在是空的）、`empty_hint`／`start_hint`（/start、/help 只給擁有者）、`install`（包 SDK 的 /help）、`status`（網頁 `/api/tools`、`/api/settings` 的 `library`）、`doctor_lines`；工具庫位置＝`config.json` 的 `packs.library`（`library_location`，不寫死路徑） |
| `sdk/` | 單檔 SDK `synox_sdk.py`（產生的）＋`pyproject.toml`（`pip install <SYNOX>/sdk`＝`synox-sdk` 套件，版本讀 `SDK_VERSION`） |
| `tests/fixtures/packs/` | host 測試用的 money／notes（下架前的凍結複本，不是正本、不加功能）；提醒直接測核心的 `/remind_*` |
| `src/synox/connect.py` | `python -m synox connect <pack>`（`Connect-Apple.bat`；要先從工具庫裝好那個工具）：照 pack.json `auth.fields` 用 getpass 問帳密，存進 `pack_secrets`（`src/synox/packs/secrets.py`，保管箱的鍵 `packs/<pack>/<field>`；跟 Web UI 工具頁「連接」表單是同一份）。帳密不經聊天：Telegram 會留紀錄、`[ROUTE]` log 印指令全文 |
| `Setup.bat`、`setup/bootstrap.ps1` | 一鍵安裝；`Start.bat`／`Stop.bat`／`Console.bat` |
| `tests/` | pytest；`conftest.py` 的 `make_bot` 用測試用的 packs＋真的 Vault＋`FakeAdapter`＋SDK `BotHarness`。測試期間 `loader.PACK_DIRS` 一律換成 `tests/fixtures/packs`（autouse `_test_pack_dirs`；不讀 repo 的 `packs/`），伺服器版的 make_bot 先把三個測試 pack 鎖成 core。空 host 的測試在 `tests/test_empty_host.py`。要讀工具庫的測試（`SYNOX_LIBS=<工具庫>`，沒有就跳過）：`test_empty_host` 的「工具庫每個工具打包→裝進空 host」、`test_smoke_real` 的四個服務、`test_sdk_p2_secret` 的 connector 不被 SYNOX 管 secret。connector 自己的測試在工具庫。穩定度 `stage` 的測試在 `tests/test_stage.py` |

## Invariants

SDK 的 12 條照用（只 vendor 了套件、沒有 vendor 文件；原文在 ISDTeleKitSDK repo 的 AGENT.md：唯一的 `authorize()`、
權限沿樹只收緊、指令名由路徑產生、按鈕綁節點、核心不認識 Telegram、等待都有期限、表單、🔐 fail closed、
jsonstore、外部程式經 JobRunner、回覆走 handler 的 api、角色階梯是參數）。SYNOX 多的（spec §7）：

1. **AI 能不能用一個節點只有一個判斷**：`agent/loop.py` 的 `ai_decision(app, user, node)`＝`policy.decide(via=AI)`。工具清單、每次呼叫、
   排程裡包的指令都問它。`effect=DANGER`（含 `Node.effect_of` 算出來的）、要 /sudo、有驗證碼欄位的 → 一律核准卡。
   驗證碼欄位不出現在工具 schema（`tools.schema` 跳過 `fresh_code`），核准後由人那一端照常問碼。
2. **adapter 只會聊天**：`llm/*` 不 import registry、不拿 Telegram api。換 LLM 只改 `config.json` 的 `llm`。
3. **pack 不互相 import、不自己開檔**：資料經 `pack.store`（vault → 密文）；每個人的檔案經 `pack.path_of(user, …)`
   （`data/users/<id>/<pack>/files/`，擋 `..`）；全部人共用的檔案經 `pack.path()`（伺服器版 `data: user` 的 pack 呼叫丟 `PackPathError`）。
   共用的放 `synox`（例如 `synox.packs.kit`）。
4. **安裝不需要使用者打任何指令**：Setup.bat 之後全部在視窗裡點。
5. **沒有隱藏的背景程式**：Start.bat 開看得到的（最小化）視窗；開機自啟是使用者在精靈裡勾的。
6. **.bat 只用 ASCII＋CRLF；.ps1 UTF-8 有 BOM＋CRLF；requirements.txt 只用 ASCII**。`.gitattributes` 的萬用規則放第一行（後面的規則才蓋得過它）。
7. **測試不綁埠、不連網、不開 Telegram、不開 `claude`**；requests 用假的 session，`claude` 用假的 runner/which；
   Web UI 測 `WebUI.handle()`／`route()`，不開 `ThreadingHTTPServer`。
8. **repo 裡沒有真名、token、Telegram id 或個人資料**；`config.json`、`data/` 在 `.gitignore`。範例一律佔位字。
9. **Web UI 只綁 127.0.0.1**（`web/server.py` 的 `HOST`，不從 config 讀）；對外是營運者的反向代理＋TLS。
   唯一例外只在 `web/server.py` 的 `bind_host`：SYNOX 的容器裡（`SYNOX_IN_CONTAINER=1`＋`CONTAINER_MARKERS`、非 Windows）且
   `SYNOX_WEB_BIND=0.0.0.0` 才綁容器自己的 0.0.0.0（compose 只發佈到宿主 127.0.0.1，[docker.md](docker.md)）；其他值＝`BindError`、網頁不開。
   不要再加別的改綁方式，也不要讓 config.json 決定綁哪裡。每個 API 用 session 的那個人算權限，
   非 GET 要 CSRF header；網頁的字一律 `textContent`，伺服器產生的 HTML 一律 escape；沒有外部資源、沒有 inline 事件（nonce CSP）。
   網頁送出的指令與按鈕一律經 `dispatcher.handle`（同一個 authorize），按鈕的 callback_data 還要真的在那則訊息上。

10. **裝別人的 pack 一律過五關**（docs/security.md「五關」）：宣告（`manifest.validate(strict=True)`）→ 靜態掃描（`scan.py`）→
    `packs.lock`（載入時雜湊不符＝不載）→ 呼叫前驗參數（`agent/validate.py`，AI 的每個工具呼叫）→ `ai_decision`＋核准卡＋分隔符。
    新的安裝路徑一律走 `packs/admin.py` 的 `stage`／`install_staged`，不要自己搬檔進 `packs/`。
    pack 的依賴環境（`runtime.*` = `auto`）一律在**按確認之後**經 `admin.build_env`（JobRunner、最多 10 分鐘）建在 `data/envs/<pack>/`，
    不寫進 pack 資料夾；pip 只裝 `==` 釘死的版本（`--no-deps --only-binary=:all:`）、npm 一律 `ci --ignore-scripts`。
    **測試絕不真的 pip／npm install**：用假的 JobRunner（`tests/test_envs.py` 的 `FakeJobs`）與假的 which。

11. **權限的唯一交會點是 `src/synox/policy.py` 的 `decide(app, user, node, *, via, chat_id, bot=None)`**（PERM-1）：
    SDK `authorize` ∧ pack.capabilities ⊆ 角色上限（`config.json` `policy.roles`；擁有者不受限）。新的權限條件（bot 範圍 PERM-4、
    頻道 surfaces／data PERM-2）一律加在 decide，不要在呼叫端另寫判斷。上限的可見性由 loader 落實（`loader.pack_group_policy` →
    `policy.group_policy_for`：群組門檻拉到裝得下的最低一級，都裝不下＝`owner_only`），所以 SDK 的 authorize／visible 自己就擋；
    decide 再對這個人算一次（縱深）。`exec`、`filesystem:any` 不能寫進任何角色（`policy.parse_policy`，`SynoxConfig.from_dict` 呼叫）。
    **bot 範圍（PERM-4）**：`bot`＝`BotSpec`（packs、max_effect、ai）；沒傳就用 `policy.current_bot()`（`DiscordEntry` 收訊時
    `policy.using_bot(spec)` 設的 contextvar；AI 那一輪在 `app.tasks` 的執行緒，`AgentFallback`／`/ai` 用 `policy.run_as` 帶過去），
    都沒有＝不限制。清單外的 pack＝`bot_pack`、ai 關掉的 bot 上的 agent＝`bot_ai`（當作不存在）；effect 超過上限＝`bot_effect`
    （拒，agent 群組不算）。**接到 SDK 的方式**：`policy.install(app)`（`app.build` 一開始）把 `app.registry.authorize` 換成
    `policy.authorize_for(app)`（先 decide、再原本的 SDK authorize），並包 `dispatcher._hidden_from`（打群組名）；
    `capability`／`bot_pack`／`bot_ai` 對 SDK 一律回 `owner_only`，所以 dispatcher、/help、按鈕都回「未知指令」、不洩漏存在
    （PERM-1 時能力上限造成的隱藏回「沒有權限」，現在也是未知指令）。vendor/ 的 SDK 沒有改；要看 SDK 本身的結果用
    `CommandRegistry.authorize(registry, …)`。`/bot_status`、doctor 的範圍報告在 `src/synox/discord/scope.py`（不會出現的原因是
    `REASONS` 一串檢查；頻道型的 surfaces／data 原因是 `_not_for_channel`，排在 `_over_max_effect` 前面）。
    **頻道（PERM-5）**：bot 是頻道型（`surface=channel`）＝這則來自伺服器頻道。`bot_scope` 加：surfaces 沒 channel 或 data=user 的 pack、
    `CHANNEL_BUILTINS`（help／start／exit）以外的內建指令＝`bot_channel`（當作不存在）；DANGER 一律 `bot_effect`；`channel_write`：
    WRITE 要 data=shared 且有效角色 ≥ 成員。`bot_ai_enabled` 對頻道型一律 False（agent 群組在頻道永遠 `bot_channel`）。role_map 的角色由 `RoomEntry` 用
    `policy.using_role_floor` 帶進來，`effective_user` 回複本（max、封頂成員），**不寫回 users.json、不改 vendor**。
    頻道的 chat_id 是負號（`Identities.resolve_room("discord-channel", …)`，-(10^15+n)），所以 SDK 的 private_only 與
    「群組閒聊不回」自然成立。頻道收訊在 `discord/__init__.py` 的 `RoomEntry`（allowlist、trigger、節流、只有發話者能按按鈕、
    別人的問答不插嘴）與 `RoomReply`（回到那個頻道、引用發話者）；解析在 `events.parse_room_event`（純函式）。
    **頻道 AI（PERM-6）**：`RoomEntry` 收到 dispatcher 的 `Route(IGNORED, reason="group")`（被 @ 但不是指令）時，`policy.channel_ai_enabled`
    （`bots.channel_ai_on`：ai.enabled 且 pool_usd_month > 0；沒 pool＝`bots.channel_ai_problem`，doctor／/bot_status 列 ❌）才交給
    `agent/room.py` 的 `RoomAgent`（AgentLoop 子類別，在 `policy.run_in_room(bot, floor, …)` 裡跑）。它只換 AgentLoop 的幾個點：
    `decision`（`ai_decision(bot=頻道型, chat_id=頻道)`，再拿掉 `room.needs_dm` 的：DANGER／wraps／needs_card／confirm——**工具判斷仍只有
    decide 一個**）、`call_tool`（要卡的回 `DM_ONLY`、`_NoCardApi` 攔住執行中才出的卡）、`system_prompt`（公開頻道版＋persona）、
    `out_of_budget`／`_record`（`budget.BotPool`，整個 bot 一池，不碰個人額度）、`say`（`room.redact_reply`：`mcp.redact`＋`TOKEN_PATTERNS`）。
    記憶 key＝頻道負號 id（`history_turns`＝`ai.history_turns`）。節流：（頻道, 人）、（頻道）`room_rate_per_minute`、AI 的（頻道, 人）
    `ai.rate_per_minute`。`policy.decide` 現在先算 `effective_user` 再做 via=AI 的訪客判斷（role_map 對到成員的人才有工具）。
    私訊的 AgentLoop 行為不變（新加的 `decision`／`tools_for`／`out_of_budget`／`say`／`carded_note` 預設就是原本的做法）。

12. **cli 子程序一律過 `src/synox/sandbox.py`**（PERM-7）：`loader._install_cli` 的 `make_cli` 用 `sandbox.grants_for`（宣告 → 讀／寫／網路／資源）
    算範圍、`sandbox.sandbox_for(config).wrap(argv, env, cwd, grants)` 包 argv；wrap 回的 argv 一定以原 argv 結尾（JsonCli 在後面接子指令）。
    後端 none／jobobject／bwrap／systemd／appcontainer（只有介面）；換實作用 `sandbox.set_factory`（測試一律給假後端，**不真的跑
    bwrap／systemd-run／AppContainer，jobobject 用假 kernel32**）。「資料屬於誰」的推斷只在 `sandbox.data_scope`（PERM-2 的 `data` 欄位優先）。
    伺服器版 `policy.sandbox.required_for` 命中又沒有真隔離（`isolates`；none、jobobject 不算）→ loader 把那個 cli pack 的群組改 `owner_only`
    （`sandbox.restricted_reason`，doctor／packs status 寫原因）。真機驗證要在 Linux 伺服器上做（docs/security.md「運行空間」）。
    **容器（S0–S2）**：pack.json `runtime.container` 的第 1 關、Dockerfile 的第 2 關在 `packs/container.py`；後端 `ContainerSandbox`
    （podman／docker，只組 argv）。每個 pack 用哪個後端一律問 `sandbox.box_for(config, m)`（packs.lock 的 `runtime.mode`＝container、
    `pick_engine` 用 which 找得到引擎 → 容器；否則 `sandbox_for(config)`），代換用 `sandbox.view_for(box, ph)`（容器裡的路徑），
    grants 仍用本機的 ph。測試換引擎偵測用 `sandbox.set_engine_which`、換容器後端用 `sandbox.set_container_factory`——
    **這台開發機絕不執行 podman／docker、不 pull、不 build**；真機清單 `docs/handoff/container-verification.md`。
    安裝時的選擇：`admin.runtime_report`／`check_runtime`、`lock.runtime_record`／`set_runtime`、升級 `upgrade.runtime_choice`。

13. **伺服器版 python pack 看信任**（PERM-8）：`loader.python_trust`——出廠的（`loader.BUNDLED` 且在內建 `PACK_DIRS`；
    2026-11-12 起 `BUNDLED` 是空的、連 connector 都搬走了，**不要再把工具加回出廠**——新工具放 SYNOX_Libs、走安裝流程）＝core、
    有鎖＝`lock.trust_of`、沒鎖＝third-party；third-party 的 kind=python 群組 `owner_only`（`loader.trust_reason`，跟 PERM-7 的
    `restricted_reason` 同一個出口：item.detail、doctor／packs status 的 🔐 行）。伺服器版沒鎖又不是出廠的 pack 載入前補跑第 2 關
    （`loader.unlocked_scan`），沒過＝`rejected`、不載入。測試裡手放的 python pack 要給成員看，
    先用 `conftest.trust_core(data_dir, folder)` 鎖成 core。個人版一律不受影響。

14. **kind=mcp stdio 的程序一律經 `packs/mcp.py` 的 `McpPool`**（P4a）：每個 `Scope.key(pack, user)` 一個長駐子程序（預設
    `PerUserScope`＝(pack, tg_id)；`SharedScope` 只有介面，擁有者還沒決定伺服器版要共用還是一人一個，**不要偷偷改成共用**）。
    第一次呼叫才啟動（載入時不開程序）、`IDLE_SECONDS` 閒置回收、死掉的下次呼叫重開、`app.on_stop` 全收；env 指紋（含 secret）變了換新程序。
    啟動照 kind=cli：`loader.placeholders`／`substitute`／`context_env`、`secrets.env_for`、`clean_env(keep=secret_env_names＋confirm.ENV_NAMES)`、
    `sandbox.grants_for`＋`box.wrap`（`grants.timeout=None`）。`tools_allow` 外的工具不掛節點；**effect 只看 `mcp.effects`**
    （`mcp.effect_name`，沒寫＝DANGER；工具的 annotations 不看）。節點的 fields／summary 在每次新程序讀完 `tools/list` 時更新（`learned`），
    所以 `kit.command` 不能用（它的 closure 會留舊欄位）——leaf 自己 `kit.parse_args(node.fields, …)`。確認來回用 `params._meta["synox/confirm_token"]`
    （`mcp.CONFIRM_META`），環境變數一律 `SYNOX_CONFIRMED=0`。**測試只開本機 Python 子程序（stdio 管線），不開埠、不連網**；
    假伺服器寫在 `tests/test_mcp_stdio.py`，真伺服器用 synox_sdk 的 `serve()` `--mcp`；閒置回收用 `pool.clock` 換假時鐘＋`pool.reap()`。

15. **kind=mcp 的連法是 `mcp.Backend`**（P4b）：`install()` 是共用部分（工具→節點、fields、effect、policy、第 4 關、核准卡、
    needs_confirm、`mcp.redact` 遮 secret、404 過期重試一次），連法只實作 `plan(user)→(ctx, 指紋)`、`open(user, ctx)→未 initialize 的 session`、
    `not_connected`、`commands`。stdio＝`mcp.StdioBackend`；http＝`packs/mcp_http.py` 的 `HttpBackend`／`HttpSession`（跟 `Session` 同介面）。
    **新增連法不要複製 install()**，加一個 Backend。http 的規則：只 POST 到 pack.json 的 `mcp.url`、`allow_redirects=False`、3xx 一律拒；
    token 只進 `Authorization` 標頭（不 log 標頭、錯誤只寫例外型別名、`HttpSession.__repr__` 不印 token）。
    OAuth 在 `packs/oauth.py`（`Flow`：PKCE、state 只在記憶體、token 存 PackSecrets 的 `oauth.FIELDS`；`LoopbackListener` 只有介面、叫了就拒——
    **這台電腦不開埠，不要實作監聽**）。**測試用假傳輸**：`monkeypatch.setattr(mcp_http, "new_session", fake)`（oauth 換 token 也走它），
    假伺服器在 `tests/test_mcp_http.py`；不連網、不開埠。
16. **信任層級 T0／T1／T2 只在 `src/synox/packs/tier.py` 判斷**（SDK P7）：`tier.assess(m, report)`＝`scan.opaque_files`（掃不到內容的檔：
    副檔名、MZ+PE／ELF／Mach-O 檔頭、無副檔名＋執行位元／`#!`、`node_modules/` 一筆、對不到原始碼的 `__pycache__`）＋`scan.externals`
    （argv 指到 pack 外的程式，解析路徑只用 `shutil.which`／`PathFinder.find_spec`，**不執行**；`{python}` 解析到 pack 外＝
    `scan.python_external`，規則只在 `envs.python_target`，`loader.cli_python` 也用它；argv 直譯器直接執行程式碼＝`scan.inline_code`，
    一筆 `inline: True` 的 external＋一個 `exec` finding）＋`envs.all_pins`。資料夾裡掃不到內容的檔
    要宣告 `exec`（第 2 關 `binary` finding）。argv 的分析在 `scan._argv_hits`（cli 是 cli.argv＋每個 command 的 argv 整條看；
    直譯器家族 `scan.family_of`：python／powershell／cmd／node／deno／shell／ruby／perl／php／lua／osascript／mshta／wsh）。
    `cli.python`／`runtime.python` 的檔名、`..` 在第 1 關（`manifest.python_path_problems`）。
    python 原始碼的繞法（審查 B #B）在 `scan._Visitor`：`DUNDER_ATTRS`、`DYNAMIC_NAMES`、`DYNAMIC_CALLS`、`DYNAMIC_ATTRS`、
    `_dynamic_call`、`visit_Assign`（`x = os` 別名）；文件語氣一律是「提醒不是門」（docs/security.md「五關」）。
    **放進 pack 的 `synox_sdk.py`（`src/synox/sdk/author.py`）不能用 `__dict__`／`vars()`／`handlers[k](…)`**（`test_single_file_matches_source`
    要它不用宣告任何能力）；@tool 的宣告掛在 `fn.synox_tool_spec`，舊版的 `__dict__["__synox_tool__"]` 由 `synox.sdk._legacy_spec` 搬。
    pip 的來源（審查 B #C）：`requires.pip` 的 `--hash=sha256:` 用 `envs.PIP_LINE_RE`／`pin_hashes`（`pins` 照舊回 (名字, 版本)）；
    `VenvBuilder.plan` 的 pip 一律 `--isolated --index-url https://pypi.org/simple`，有雜湊加 `--require-hashes`；
    `build` 給 `jobs.start(env=envs.build_env())`（白名單 `BUILD_ENV_KEEP`）。`tier.hash_lines` 給安裝報告。
    載入後再對鎖（審查 B #D）：`load_all` 對有鎖的 pack 掛 `pack.live = lock.live_check(record, folder)`；`Pack.tampered_since_load()`
    在 cli 的 `submit`／面板 route（`changed_files`）與 `mcp.StdioBackend.open` 前面問，對不上＝`loader.tampered_text`＋`_tamper_notice`、不執行。T2 安裝一律要 `trust_publisher`＝pack.json `publisher`（`tier.confirm_problem`；
    `admin.install_staged`／`approve_installed`、`upgrade.upgrade_staged` 都過這裡；升級要不要重新確認看 `tier.reconfirm_reasons`）。
    鎖的欄位用 `tier.lock_fields` → `lock.approve(tier_fields=)`。執行期：`sandbox.required` 對 T2 一律 True、`sandbox.restricted_reason`
    對 T2 python pack 一律 owner_only（伺服器版）；個人版 `sandbox.t2_personal_note` 給 doctor。
    **packs.lock 雜湊每一個檔**（`lock.hash_files` 預設含 `__pycache__`，`"hash_scope": "all"`；舊鎖用 `lock.hashes_for` 照舊算法對）。
    上傳的 zip 不解出 `__pycache__`、`synox-sdk zip` 不打包它、`check_integrity` 不比它；SYNOX 的子程序一律 `PYTHONDONTWRITEBYTECODE=1`
    （`loader.context_env`）。**測試的 T2 pack 一律用位元組造假檔頭（`tests/test_t2_trust.py` 的 `FAKE_EXE`），絕不執行任何執行檔**；
    開發機不跑第三方 exe／npm 套件是擁有者的政策（docs/security.md「信任層級」）。
    **審查 C（feat/fix-round2、fix-round3）的不變量**——改這些地方之前先看 `tests/test_review_c.py`、`tests/test_review_c2.py`：
    - **#C1 `{python}` 只准跑 pack 裡的 `.py`／`.pyw`／含 `__main__.py` 的資料夾**（`scan.script_target_problem`、`scan.argv_blocked`；
      載入時 `loader.refuse_blocked_argv` 再查）。`ARCHIVE_EXT`（.pyz .pyzw .zip .whl .egg）是 opaque；`guessed_python` 把沒有副檔名、
      ast 解析得過的檔當原始碼掃。不要放寬成「pack 裡的檔都行」。
    - **#C2 子程序環境變數名的黑名單只在 `manifest.env_name_problem`**（第 1 關；`loader.cli_env`／mcp env 用同一張表再濾一次）；
      子程序一律 `PYTHONNOUSERSITE=1`。**不要在 `{python}` 加 `-I`**（SDK pack 旁邊的 `synox_sdk.py` 會 import 不到）。
    - **#C3 `{python} -m` 的 cwd 一定在 pack 裡**（`scan.cwd_inside_pack`，純字串判斷）。
    - **#C4 UNC／裝置路徑（`//`、`\\`、`\\?\`、`\\.\`、`\??\`）在任何 realpath／exists／isfile 之前拒**：第 1 關 `manifest.unc_problems`
      在 `validate()` 最前面；`agent/validate.inside`、`envs._network_path`、`scan.resolve_program` 都先看 `unc_like`。
      新增「會碰檔案系統的檢查」時，順序一定在 `unc_problems` 之後。
    - **#C5 掃描器的名單都是 `scan.py` 頂端的常數**（`NETWORK_MODULES`／`SUBPROCESS_MODULES`／`EXEC_MODULES`／`STAR_RISKY`／`NETWORK_CALLS`／
      `NETWORK_PREFIXES`／`NETWORK_ATTRS`／`DYNAMIC_ATTRS`／`SYS_PATH_HOOKS`／`CONSTRUCTED_NAMES`）；來源不明的 import 用
      `scan.ImportContext`（pack 資料夾＋`scan.pip_names(m)`；pip 名≠import 名的對照在 `PIP_IMPORT_NAMES`，SYNOX 自己的在 `SYNOX_MODULES`）；
      拼字串用 `scan._fold`（只在 ast 上算字面字，**絕不 eval**）。`scan_source(rel, text)` 沒給 context＝只認標準函式庫與 SYNOX 自己的。
      文件語氣永遠是「提醒不是門」。
    - **#C6 zip 檔名**：`admin._safe_parts` 拒雙向文字控制與零寬字元、`MAX_PART`／`MAX_REL_PATH`；`stage` 的解壓縮與 `install_staged`
      的搬移把 OSError 包成 `PackAdminError`（網頁不能出 500）。
    - **#C7 建環境的子程序一律 `PIP_CONFIG_FILE=os.devnull`**（`envs.build_env`；pip 看到 devnull 就不讀任何設定檔）。不要換成空檔。
    - **#C8 npm 只收 `envs.NPM_REGISTRY`**（`envs.npm_bad_sources`／`npm_source_problems`：`admin.run_gates` 拒裝、`VenvBuilder.plan` 拒建、
      `tier.assess` 的 `npm_bad_sources` 給紅字）；`npm ci` 帶 `--registry=`。
17. **巢狀參數的 schema 模式只給 MCP 工具、只給 AI**（Q6 方案 B）：pack.json `mcp.schema_tools` 列的工具，`mcp.shape_of(..., schema_mode=True)`
    用 `packs/mcp_schema.normalize` 正規化 inputSchema（白名單子集；`$ref`／`oneOf`／開放的 additionalProperties／路徑 format…＝不支援、
    `node.ai=False`、原因進 `shape.schema_problem` 與 doctor）。支援的話 `synox_tool_meta[path]["schema"]`＝正規化的 schema，
    `app.extras["synox_schema_runners"][path]`＝`install()` 的結構化入口；**兩個都要有才算 schema 模式**（`validate.schema_of`），
    所以 python／cli pack 寫 meta 也開不了。AI 那條：`loop.call_schema_tool` → `validate.check_schema_call`（`mcp_schema.check`：
    照 schema＋硬限制 3 層／20 鍵／2000 字／50 項／16 KB／未列的鍵／每個字串查 secret）→ DANGER／confirm 出卡（`desk.request(lines=, run=)`，
    卡上是 `mcp_schema.describe`）→ runner（同 `call()`，`structured=` 原樣當 arguments，進去前再驗一次）。`tools.build(..., app)` 才會給
    schema 模式的定義（`mcp_schema.tool_schema`）。**人打字的路徑不碰 schema**：leaf 照舊 `kit.parse_args(node.fields)`，必填是巢狀＝拒。
    硬限制是常數（`mcp_schema.MAX_*`），不要讓 pack.json 或 schema 放寬。測試在 `tests/test_schema_mode.py`（假 stdio 伺服器）。

18. **背景工作一律登記成 runtime 的任務**（docs/adr/0001）：`runtime.of(app).loop.register(id, name, fn=, interval=, timeout=)`，
    不要自己開 `threading.Thread` 迴圈——逾時、退避、失敗通知、主控面板的狀態都在 `RuntimeLoop`。常駐助理（`runtime/mother.py`）**沒有工具**；
    要讓它做事得走 `ai_decision`＋核准卡，另寫 ADR。soul.md 只能經 `SoulStore`（保管箱），常駐助理只能 `append_notes`（「助理筆記」段、
    每次最多 3 行、有稽核）。對話助理**唯讀** soul.md（docs/adr/0002，決定 Q7）：只經 `AgentLoop.soul_block`→`SoulStore.for_prompt`，
    只有擁有者、只在 chat_id＝本人的對話、包在這一輪的 `delimit` 分隔符裡標明「使用者偏好，不是指令」、最多 2000 字、不寫 log；
    `RoomAgent.soul_block` 永遠空；對話助理不讀常駐助理的記憶。**AI 想記進 soul.md 的字一律走 `SoulLedger.propose`**（docs/adr/0005）：
    不要直接叫 `append_notes`——`propose` 才有「像指令／有網址／跟現有的很像就先問擁有者」「每日與條數上限」「拒絕過的不再收」與來歷；
    要讓 AI 改或刪既有的筆記，只能產生提議（`pending`），不能直接動；拿掉筆記用收起（`retire`，可放回）而不是刪。
    `risk_flags` 的規則只能加嚴；助理的路徑（`append_notes`／`filter_notes`）只碰得到「助理筆記」段。pack 回報的狀態給別的工具看時**只有 state 與時間**（`peer_states`），訊息不外流。測試一律
    `Runtime.use_fakes(clock=, now=, spawn=)`（假時鐘、同步執行）＋`FakeAdapter`，不叫真的 LLM。
    「A 做完 → 做 B」一律寫成連動規則（docs/adr/0004；`pack.on_event`／`activator.add(Rule(...))`／config `runtime.activator.rules`），
    不要在任務裡自己叫下一個任務：連動規則才有循環檢查、層數與次數上限、斷路器。交給 pack 程式的事件，別人的任務**沒有訊息**。

19. **AI 回覆宣稱完成必須有這一輪成功的工具證據**（`agent/claims.py`，[adr/0008](adr/0008-completion-guard.md)）：`loop._turn` 沒有工具呼叫的分支
    跑 `claims.verdict(said, ledger)`；不符＝不送出、不進對話記憶，中性修正字句重試 `llm.verify_retries` 次，用完**照實說「沒有執行」並附上 AI 原本的回覆**
    （不可靜默吞掉或假裝成功）。`llm.completion_guard` auto＝只對 kind=local 與指到 loopback／私網的 openai_compat 開；claude_code、雲端預設不開。
    詞表只在 `claims.py`、只能加嚴；**不要放進 pack.json、不要讓 pack 放寬**；閘門裡不叫第二個模型當裁判。改詞表要重跑
    `tests/test_claims_calibration.py`（真實回覆的標定），並更新 ADR 0008 的數字。`call_tool` 回 `(結果, 出卡, ok)` 三個值（`RoomAgent` 也是）。
20. **救回來的工具呼叫不走捷徑**（[adr/0009](adr/0009-leaked-tool-call-recovery.md)）：`textproto.parse_leaked` 只把文字變成 `ToolCall`，
    跟原生呼叫走同一個 `call_tool`（`ai_decision`、第 4 關、確認卡）。思考段（`<think>`）裡的呼叫一律不解。
    停止詞只對 `supports_stop=True` 的 adapter 傳（[adr/0010](adr/0010-stop-words.md)）；`system__cannot_do` 不是節點、不經 `ai_decision`、
    什麼都不做（[adr/0011](adr/0011-cannot-do-exit.md)）；同一個呼叫連續失敗 3 次結束這一輪、步數用完的總結（[adr/0012](adr/0012-repeat-failure-and-step-limit-summary.md)）。

另外：
- **本地模型（kind=local，[adr/0007](adr/0007-local-llm-platform.md)）**：`llm.timeout` 是**無進展**逾時（每次 socket 讀取；
  0＝450 秒），`llm.max_total_timeout` 是很寬的總上限（1800）——不要改回「總時限」，CPU 上的模型一直在吐字時不能砍。
  `inspect`／`probe`／建議**只能唯讀**（`/api/tags`、`/api/show`、`/api/ps`、`/v1/models`），絕不送 chat／generate（不載入模型）。
  截斷一律大聲說（`Reply.warnings` → AgentLoop 另送一則提醒、不進對話記憶；`adapter.last_warning` → 設定頁）。
  訊息轉換只在 `local.ollama_message`／`openai_message`（VLM 之後加圖片的地方）。**測試一律用假 opener**（`tests/test_local_llm.py`）：
  不 listen、不連網、不開 Ollama。
- **保持清醒（`runtime/keepawake.py`，[adr/0006](adr/0006-keep-awake-screen-may-sleep.md)）預設關**；打開它的每個地方都要顯示
  `keepawake.NOTICE`（會覆蓋 Windows 的「睡眠」設定）。測試一律假電源（`FakePower`／假 kernel32），不碰真的電源請求；
  SYNOX 不修改任何電源設定（排查步驟 [keep-awake-troubleshooting.md](keep-awake-troubleshooting.md) 只叫人自己看）。
- **⏰ 提醒（系統）＝系統指令，不是 pack**（擁有者 2026-11-12，QuestionToUser QL5）：`/remind_add`／`/remind_list`／`/remind_rm` 由
  `schedule.install_system_remind` 在 `loader.load_all` **之前**掛，群組名 `remind` 登記在 `app.extras[loader.SYSTEM_GROUPS_KEY]`；
  pack 宣告 `group: remind`（例如工具庫的舊 remind 工具）＝`loader.system_group_problem` → 狀態 `incompatible`＋一句「不需要了、去移除」，不載入。
  權限照以前的 remind pack（`group_policy(member)`＋`private_only`）；它是系統指令，所以跟 `/schedule_*` 一樣**不看 Discord bot 的 `packs` 清單**
  （頻道型 bot 照樣看不到：不在 `CHANNEL_BUILTINS`）。資料就是 `data/schedule.json.enc`（伺服器版每人一份），跟以前同一份。
  名字刻意寫「（系統）」：工具、文件不要再用 remind／reminder 指別的東西；Apple 提醒事項是 connector `apple-reminders`，另一回事。
  網頁工具頁把 SYNOX 自己的指令都歸在「系統」群組（`toolpage.BUILTIN`）。
- **沒有 hidden dependency**（[adr/0003](adr/0003-distribution-git-clone-and-installer.md) D）：路徑一律相對 `config.ROOT` 或可設定（config、環境變數、參數）；
  不寫任何一台電腦的路徑或使用者名稱。「找 SYNOX 旁邊的兄弟資料夾」只能當有文件的後備，那一行標 `clean-room: sibling-fallback`；
  `tests/test_clean_room_check.py` 擋所有 git 追蹤的檔案裡沒標記的猜測與 `C:\Users\<名字>` 這類路徑。相依要能照 `requirements.lock` 離線裝。
- pack 的群組由 loader 依 pack.json 定義（`loader.group_policy`）：`access: owner`（預設）＝整組 `owner_only`；`member`＝伺服器版 `role=MEMBER`、
  個人版 `owner_only`；`everyone`＝最低一級；再套角色能力上限（只會更嚴，見 invariant 11）。agent 群組也用同一個規則（`member`）：個人版只有擁有者，伺服器版成員以上；
  `AgentFallback.accepts` 問的是 `authorize(user, agent.ai)`，不另寫判斷。訪客（最低一級）在 `ai_decision` 一律沒有工具。
- 權限宣告（PERM-2）：`surfaces` 沒有 `channel`（預設）→ `loader.surface_policy` 給群組 `private_only`；`data: shared` 的 WRITE／DANGER 葉節點
  在伺服器版由 `loader.shared_write_admin` 拉到角色階梯最高那一級（install 之後跑；個人版不動）。第 2 關照 `data` 檢查（`data: user` 不准裸 `pack.store`、
  `pack.secret(name)` 不給 user、`pack.path(` 要改 `pack.path_of(user, …)`（PERM-8）、cli 不准 `{data_dir}`）。`trust`（core｜third-party）不在 pack.json：安裝報告上選、`lock.approve(trust=)` 寫進鎖，
  舊鎖沒有＝third-party；升級沒給＝沿用舊鎖的。工具庫的 pack 與 connector 都宣告 `surfaces: ["dm"]`、`data: user`，新寫的 pack 也要寫。
- **SDK 版本（`requires.sdk`，SYNOX_Libs ADR-0001）**：`SDK_VERSION` 只寫在 `src/synox/sdk/author.py`（SYNOX 給工具的介面合約：pack.json 格式、
  子程序的環境變數與 JSON 信封、kind=python 的 `install(app, pack)`／`Pack` 方法／`synox.packs.kit`）。改了不相容的地方就升 MINOR（0.x）並重產
  `sdk/synox_sdk.py`（`scripts/build_synox_sdk.py`）。檢查只在 `manifest.synox_problem`（先 `requires.synox` 再 `sdk_problem`）：安裝的
  `admin.run_gates`、`loader.load_all`（incompatible）、doctor、`/bot_status` 都經它，不要另寫一份。
  可見性的總判斷（`policy.decide`）是 PERM-1，不在這裡。
- **每個人自己的資料一律 `pack.store.of(user)`**（notes、money）。伺服器版 → `data/users/<id>/`，vault 金鑰 HKDF(主金鑰, `user:<id>`)；
  個人版 → 共用的那一份。營運者仍讀得到（docs/security.md）；「營運者也看不到」的 SYNOX Node 是另一份規格，不在這裡做。
- 伺服器版才裝 SDK 的 `accounts`、`limits` pack（`app.install_server_packs`）；陌生人＝GUEST（SDK `UserManager`）。
- 保管箱解不開時**丟 VaultError，絕不當成空的再蓋過去**；金鑰檔不見而 `data/` 已有 `*.json.enc` 時不產生新金鑰。
- kind=cli（`loader._install_cli`）：經 AI 呼叫（`api.via_ai is True`，agent 的 `CaptureApi`）的一般指令**同步**跑、回覆被攔下來交回 AI
  （loop 包 nonce）；人打字的照舊丟 `app.tasks`。子程序環境照 SDK `clean_env` 拿掉像密鑰的變數，`keep_env` 只放 `manifest.secret_env_names(m)`
  （`requires.env`＋`auth.fields[].env`）——不要整包放行。`fields[].kind` 的格式檢查在 `validate.typed_check`（掛在 `Field.check`，經
  `kit.parse_args`，人打字與 AI 兩條路都跑），交給程式前 `validate.normalize`；AI 的 schema 一律字串。
- 工具的確認來回（SDK P3，`packs/confirm.py`）：cli 工具回 `needs_confirm` → `submit` 的 `finish` 不顯示結果，`ConfirmGrants.issue`
  發一次性憑證（綁 pack／指令／`args_hash`／tg_id、`timing.confirm_ttl` 過期）→ `ApprovalDesk.request(..., grant=, rerun=)` 出卡
  （`app.extras["synox_approval_desk"]`）→ ✅：desk 先 BUTTON authorize，再 `rerun` ＝ `submit(..., _grant=)`（同一組原始參數，
  不重新解析 argv）→ `redeem` 對得上才 `make_cli(confirmed=token)`。**`SYNOX_CONFIRMED`／`SYNOX_CONFIRM_TOKEN` 每次都明寫**
  （`env_for`，蓋過 `cli.env`），名字加進 `keep_env`（`_TOKEN` 結尾會被 `clean_env` 拿掉）。`_grant` 只有 desk 的 rerun 給，
  kit.command／Forms／AI 都只傳四個參數。經 AI：`CaptureApi.mark_carded()` → `call_tool` 回 carded、這一輪結束。
  確認過的重跑又回 needs_confirm → `AGAIN`，不再出卡。`commands[].confirm`（AI 呼叫前的卡）不受影響，兩張卡可以先後出現。
- pack 的 secret（`packs/secrets.py`）：`auth.type` token／file 的 `auth.fields` 由 SYNOX 收（`managed()`：kind=cli、或 python 原始碼有
  `.secret(`；`auth.managed` 可以強制），存保管箱 `pack_secrets`、鍵 `packs/<pack>/<field>`、伺服器版 `vault.for_user`。只有 Web UI
  `/api/pack-secrets/<name>`（CSRF＋Origin；個人版擁有者、伺服器版本人）與 `python -m synox connect` 能寫；**不加 Telegram 指令**。
  值永遠不回網頁（`status()` 只給 set／last4）。cli：`env_for()` 進 `env_extra`，**絕不進 argv**；python：`Pack.secret(name, user)`。
  第 4 關 `check_call` 拒「值＝已存 secret（或夾著 8 字以上的）」。工具庫的 4 個 connector（以前內建）沒呼叫 pack.secret，不受影響——別讓它們變 managed，
  除非一起改成讀 `pack.secret`（遷移時加 `"managed": "synox"`）。
- `requires.synox` 不合 → `PackStatus.status = "incompatible"`（不載入、不算 `LoadReport.ok` 的失敗）；doctor、`packs status`、安裝的第 1、2 關都用
  `manifest.synox_problem` 那句人話。

## 跟 SDK 的差異／轉接（vendor 沒有改過）

| 什麼 | 為什麼 |
|---|---|
| `synox.packs.kit.command`（照位置填）而不是 SDK `Forms.leaf` | SDK 的 `parse_fields` 把第一個 `key=` 之前的字全給第一個欄位：`/money 120 午餐` 會變成 amount="120 午餐"。kit 照位置分配，最後一個欄位吃剩下的；仍設 `node.fields` 給 AI schema。缺必填回用法、不開問答；不收 `fresh_code` 欄位（要碼的指令用 SDK Forms） |
| `llm/claude_code.py` 直接 `subprocess.run`，不經 `JobRunner`（SDK invariant 10） | adapter 不拿 app（invariant 2）。有 argv 陣列、`CREATE_NO_WINDOW`、逾時；沒有 Job Object 收程序樹 |
| 核准卡的節點叫 `agent.ai_approve`（`/ai_approve`），不是 `agent.approve` | 群組 `agent` 是 bare（葉節點直接用自己的名字：`/ai`、`/ai_usage`），`approve` 會變成 `/approve`，跟 AI 無關的名字容易撞名 |
| 排程（`synox/schedule`） | SDK D6 沒有排程。照前身專案的排程器做法，只做每天 HH:MM 與某一天一次；跑在 runtime 的任務 `system.schedule` 裡（逾時、退避、連續失敗通知；不自動暫停，見 adr/0001） |

## 模式（`config.json` 的 `mode`）

| | personal（預設） | server |
|---|---|---|
| 誰用得到 | 擁有者 | 擁有者＋被升級的人；陌生人是 GUEST，只看得到 `access: everyone` |
| 帳號管理 | 沒有 | SDK `accounts`（`/me`、`/me_upgrade`、`/user_list`、`/user_role`）＋`limits`（`/limit_*`） |
| pack 資料 | `data/<pack>.json.enc` 一份 | `data/users/<id>/<pack>.json.enc` 每人一份 |
| 提醒、排程 | 擁有者；`data/schedule.json.enc` | 成員以上；每人 `data/users/<id>/schedule.json.enc`，提醒送給建立的人，排程以他的身分跑（建立時 via=SCHEDULE 檢查裡面的指令） |
| AI | 擁有者 | 成員以上；工具只有 `ai_decision` 對他放行的；每月額度 `ai_member_monthly_usd`（預設 2.0，`/ai_budget` 調），用量 `data/users/<id>/llm_usage.json` |
| 網頁介面 | `/web`：擁有者 | `/web`：每個人（訪客也可以，看到的只有自己能用的）；帳號頁給擁有者／管理員。網頁只聽 127.0.0.1：沒設 `web.public_url` 時連結只在伺服器那台電腦打得開，設了就人人能從外面登入（白話表：security.md「誰進得了網頁」；要不要收緊：QuestionToUser QS1） |
| 舊資料 | — | 個人版的共用檔不會自動搬到 `data/users/<擁有者>/`（留著不動；改回個人版又會用它們） |

工程師模式：不跑精靈，照 `config.example.json` 寫 `config.json`（含 `mode`），`python -m synox run`。

## ntu_easy_llm（創始維護者的套件，LLM 那一層）

- 用 API 金鑰的四種 kind（`openai`、`anthropic`、`gemini`、`openai_compat`）都經 `ntu_easy_llm.agent.chat`（0.5.0 起才有；舊的 `ask*` 沒有工具呼叫）。
  `claude_code`、`fake`、`none` 不需要它。`easy_llm.py` 用到時才 import；沒裝 → `LLMError("還沒安裝 ntu_easy_llm：…")`。
- **已發佈 0.5.0 GitHub release**（2026-11-13）：`pyproject.toml` 的選用組是官方 release wheel 的直接網址

  ```
  llm = ["ntu_easy_llm @ https://github.com/ChouYangEn0401/ntu_easy_llm/releases/download/ntu_easy_llm-0.5.0/ntu_easy_llm-0.5.0-py3-none-any.whl"]
  ```

  開發機：`.venv\Scripts\python.exe -m pip install -e .[llm]`（它會一起裝 openai、anthropic、google-genai 三個 SDK——
  那是舊 API 要的；SYNOX 用的 `agent` 只用標準函式庫打 HTTP）。
  `setup/bootstrap.ps1` **連網、照 pyproject 範圍裝**的那一條已改成 `pip install -e "$Root[llm]"`；wheelhouse 離線與
  `requirements.lock` 那兩條沒動（鎖與 wheelhouse 不含 llm 組，`scripts/lock_deps.py` 的 `top_level` 只看 dependencies）。
  `requirements.txt` **刻意沒加**：Dockerfile（`pip wheel -r requirements.txt`）與 devcontainer 也讀它，加了會把三個 SDK
  帶進每個映像檔，而且這台不 build 容器、驗不了；要加請在能 build 的機器上一起改（同一行網址，本身是 ASCII）。
  **不要**寫成只有名字的 `ntu_easy_llm>=…` 給一般使用者裝：它不在 PyPI 上，萬一有人在 PyPI 註冊了同名套件，pip 會去裝那個。
- **本地模型（kind=local）不經 ntu_easy_llm**：SYNOX 內建（`llm/local.py`，標準函式庫 urllib），沒有登入要包，所以不像
  claude_login／openai_login 另做套件（[adr/0007](adr/0007-local-llm-platform.md)）。

## Known limitations / next steps

- AI 對話紀錄只在記憶體（每個聊天最近 6 輪），重開就忘。
- 經 AI 呼叫的 kind=cli 一般指令已改成同步（`api.via_ai`），結果交回 AI。仍然例外：`background: true` 的 cli 指令（AI 只拿到「開始了」，
  結果之後直接送給使用者），以及 python pack 自己丟背景執行緒回覆的指令（同樣的問題，要 pack 自己看 `api.via_ai` 改成同步）。
- 核准卡按下執行的結果直接給使用者，只在 AI 的紀錄留一句「已執行」，不會自動再開一輪讓 AI 接著做。
- `Setup.bat` 的完整安裝路徑（winget、embeddable zip、wheelhouse 離線、文字版 init 退路）與安裝程式（`setup/installer/synox.iss`）
  都沒有在任何一台陌生電腦上跑過（清單：[handoff/clean-machine-test.md](handoff/clean-machine-test.md)）；精靈的畫面沒有自動化測試（只測了 logic／probe／shortcuts）。
  `requirements.lock` 還沒產生（開發機的 .venv 少 websocket-client，要在發佈機的乾淨 venv 產生）。
- connector 全部接上了，但都只對假傳輸測過。網頁工具頁對 kind=python 一律顯示「已連接」，沒設憑證時要打各自的 `_status`；
- 工具庫的 connector（notion、todoist、google-calendar、apple-reminders）全部接上了，但都只對假傳輸測過（標 🧪 alpha）。網頁工具頁對 kind=python 一律顯示「已連接」，沒設憑證時要打各自的 `_status`；
  Notion 指令參數照空白切（換行變空白）；Todoist 呼叫是同步的、逾時 15 秒；Apple 的帳號只能在電腦上用 `Connect-Apple.bat` 設。
- `[ROUTE]` log 會印指令全文（SDK dispatcher），所以任何密碼都不能設計成「在聊天裡打」的指令（Notion／Todoist 的 token 指令靠 `redact_in_logs` 遮罩）。
- Google 日曆：連接只有指令（`/gcal_setup`、貼網址列回來），網頁沒有「連接」按鈕；只用主要日曆；`/gcal_rm` 的編號是最近一次列表；沒有改行程。
- 文字協定一次只解析一個工具呼叫。
- kind=mcp：stdio（P4a）與遠端 http（P4b，token／OAuth 貼回網址）；OAuth loopback、動態註冊、GET 長連線串流沒做；巢狀 object／array 參數只有列進 `mcp.schema_tools` 的工具給 AI（schema 模式，
  `$ref`／`oneOf` 之類不支援、人打字打不出巢狀），其他的不給（doctor 列出）；還沒啟動過的 MCP 工具第一次只有 `args`
  一個參數（讀完 tools/list 才換成真的欄位，同一輪 AI 的 schema 是舊的、但第 4 關已經用新欄位）；`SharedScope` 沒做；
  沙盒後端包長駐程序（bwrap／systemd-run `--pipe`）沒在 Linux 真機驗過。
- 伺服器版：個人版的舊資料不會自動搬到擁有者的 `data/users/<id>/`；精靈的伺服器版沒有多問「誰是管理員」（擁有者之後用 `/user_role <id> admin`
  或網頁帳號頁）。成員的 AI 額度用 token × 單價估（`llm.price_in`／`price_out`，預設 3／15 美元每百萬 token），不是供應者的帳單。
- Web UI：主動通知（提醒、排程的結果、申請通知）仍然只走 Telegram（`app.home`），網頁對話頁只看得到在網頁上講的；圖片、檔案在網頁只顯示一行說明；
  網頁與 Telegram 的私訊共用同一份 AI 對話記憶（chat_id 都是那個人的 id）；pack reload 拿不掉 pack 自己綁的按鈕前綴；
  Telegram 指令選單在 reload 之後不會自動重設（重開 bot 才會）；設定頁改 AI 來源**立刻生效**（`agent.set_adapter`：對話助理與常駐助理一起換；只有「啟動時沒有 AI 才沒建的 Discord 頻道 AI」要重開才出現）。
- `/backup` 的 Telegram 指令與還原按鈕沒做（只有網頁下載＋`synox.backup.restore_cli`）；備份綁 DPAPI，換電腦解不開。

## 公開前檢查清單（repo 改成 public 或發佈 zip 之前）

1. 跑 `.venv\Scripts\python.exe scripts\prepublish_check.py`（只用標準函式庫、不連網）。它看**目前的檔案**（git 追蹤的＋沒被忽略的新檔）
   與 **git 歷史**（所有分支、每個不同版本的檔案讀一次、每個 commit 的作者信箱），找：疑似密鑰（Telegram、OpenAI／Anthropic `sk-`、
   Google `AIza`／`GOCSPX-`、Slack `xox`、GitHub `ghp_`、AWS `AKIA`、私鑰檔頭、Notion、Discord）、`C:\Users\<名字>`／`/Users/<名字>`
   這類本機路徑、個人信箱、不該提交的檔名（`.env`、`config.json`、`*.enc`、`packs.lock`…；`config.example.json` 可以）。
   報告只列「檔名:行號＋種類」，不印內容；有發現時退出碼是 1。`--worktree-only` 只看目前的檔案（PR 前自檢用）。
2. 「目前的檔案」那一段必須是零。確定是範例或測試假值的行，在同一行加 `prepublish-check: allow`（並在 PR 說明為什麼）。
3. 「git 歷史」那一段：舊版本裡的本機路徑不一定要改寫歷史，由維護者決定；**真的密鑰**一律先到服務端撤銷、換新，再考慮改寫歷史。
4. commit 作者信箱若是個人信箱：要不要改寫成 GitHub 的 noreply 信箱，由維護者決定。
5. 文件：README 頂端的 alpha 說明仍然屬實；`<待補：…>` 佔位（SECURITY.md、LICENSING.md、CONTRIBUTING.md、MAINTAINERS.md）都填好了。
6. 測試全過：`.venv\Scripts\python.exe -m pytest -q`。
