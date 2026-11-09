# SYNOX — AGENT.md

給 AI 與接手的人看的地圖。設計規格（合約）在擁有者的 ClawBot repo：`docs/plans/2026-11-09-synox-design.md`；
給人看的在 [../README.md](../README.md)。

## Commands

- 安裝（開發）：`py -3.11 -m venv .venv` → `.venv\Scripts\python.exe -m pip install -e .[dev]`；
  用 API 金鑰的 AI 要再裝 ntu_easy_llm（見下面「ntu_easy_llm」）
- 測試：`.venv\Scripts\python.exe -m pytest -q`（約 10 秒；不連網、不開埠、不開 Telegram、不叫 `claude`）
- 終端機：`.venv\Scripts\python.exe -m synox console`（`--llm fake` 換假 AI；沒有 config.json 用示範設定）
- 健康檢查：`.venv\Scripts\python.exe -m synox doctor --offline`
- 重新 vendor SDK：`.venv\Scripts\python.exe scripts\vendor_sdk.py`；打包：`scripts\make_zip.py`
- 主控台是 cp950：跑 Python 前 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`

## Map

| Path | Role |
|---|---|
| `vendor/isdtelekit/` | ISDTeleKitSDK 的**原樣**複製（版本與 commit 在 `vendor/VERSION`）。不要改；要不同的行為就在 `src/synox` 寫轉接 |
| `src/synox/__main__.py` | `python -m synox run｜console｜wizard｜doctor｜stop｜install <檔> [--yes] [--trust-publisher <名字>]｜packs status｜packs lock --approve <name> [--trust-publisher <名字>]｜packs env rebuild <name>` |
| `src/synox/app.py` | `build(config, home=, adapter=, vault=, config_path=)`：SDK `build_app` → basics/help → `packs.load_all` → `agent.install` → `schedule.install` → `web.install` |
| `src/synox/config.py` | `SynoxConfig`＝SDK `BotConfig`＋`mode`（personal｜server）／`llm`／`vault`／`packs`／`policy`；路徑相對 SYNOX 資料夾（`ROOT`） |
| `src/synox/policy.py` | `decide`（權限唯一交會點）、`parse_policy`（`policy.roles` 能力上限，第 1 關式檢查）、`group_policy_for`（loader 用）、`ceiling`／`fits`；bot 範圍 `bot_scope`／`using_bot`／`current_bot`／`run_as`；`install`（把 decide 接到 SDK 的 `registry.authorize`） |
| `src/synox/sandbox.py` | 運行空間（PERM-7）：`Sandbox.wrap(argv, env, cwd, grants)`、`Grants`、後端 none／jobobject／bwrap／systemd／appcontainer（介面）、`set_factory`／`sandbox_for`、`grants_for`、`data_scope`（推斷集中處）、`trust_of`、`restricted_reason`、`doctor_line`；jobobject 的 launcher（`python -I sandbox.py jobobject …`） |
| `src/synox/discord/scope.py` | bot 範圍報告：`/bot_status`（`install`）、`report`／`lines`（doctor 也用）、`REASONS`（不會出現的原因，可擴充）、`channel_line`（頻道型的收訊設定） |
| `src/synox/discord/` 其他 | `bots.py`（BotSpec、設定檢查；頻道型 `guilds`／`role_map`／`trigger`／`rate_per_minute`）、`events.py`（`parse_event` 私訊、`parse_room_event` 頻道）、`rest.py`（`DiscordChannel`）、`gateway.py`（`INTENTS`／`CHANNEL_INTENTS`、`on_ready`）、`__init__.py`（`install`、`DiscordEntry`、`RoomEntry`／`RoomReply`／`RoomThrottle`、`MultiHome`、配對）。見 [discord.md](discord.md) |
| `src/synox/llm/` | `base.py`（`ChatAdapter`、`Message`、`Reply`、`ToolCall`、`ToolSpec`）、`easy_llm.py`（openai／anthropic／gemini／openai_compat，經 `ntu_easy_llm.agent`，lazy import）、`claude_code`、`fake`、`textproto`、`factory.make_adapter` |
| `src/synox/vault/` | `vault.py`（Fernet＋每檔 scrypt、`*.json.enc`；`for_user(id)`＝伺服器版每人的保管箱，HKDF 衍生）、`keyring.py`（DPAPI 包住主金鑰 `data/.synox.key`） |
| `src/synox/packs/` | `manifest.py`（pack.json v2 檢查＝第 1 關；`surfaces`／`data`（`_check_scope`、`default_data`、`cli_templates`）；`requires.synox`＝`synox_problem`、`requires.env`→`secret_env_names`、`fields[].kind`、`auth.fields`）、`secrets.py`（pack 的 secret：`PackSecrets`、`managed_fields`）、`scan.py`（ast 靜態掃描＝第 2 關；`_check_data_python`／`_check_data_cli`＝data 宣告的規則）、`lock.py`（`data/packs.lock`＝第 3 關；`trust`、`trust_of`）、`loader.py`（掃 `packs/`＋`connectors/`、`Pack`／`PackStore`／`store.of(user)`、`group_policy`、`surface_policy`（沒有 channel＝private_only）、`shared_write_admin`、cli 代換與 `build_argv`）、`kit.py`（照位置填的指令）、`envs.py`（`runtime.python／node = "auto"`：`Builder.plan`／`build(m, jobs, on_done)` 建 `data/envs/<pack>/`、`python_of`／`node_of`／`node_env` 給 loader 代換、`env_problem` 給 loader／doctor；`set_factory` 換實作） |
| `src/synox/packs/mcp.py` | kind=mcp stdio（P4a）：`Session`（JSON-RPC over stdio、讀執行緒、`request`／`notify`）、`handshake`（initialize／initialized／tools/list）、`spawn`（Windows Job Object）、`McpPool`（每個 key 一個長駐程序、`reap()` 閒置回收、`close_all`；`clock`／`spawner` 可換）、`Scope`／`PerUserScope`／`SharedScope`（介面）、`shape_of`（inputSchema → fields）、`to_arguments`、`needs_confirm_of`、`render_result`、快取 `data/mcp/<pack>.tools.json`、`doctor_notes`、`Backend`／`StdioBackend`（連法）、`redact`、`install`（loader 叫，兩種連法共用） |
| `src/synox/packs/mcp_http.py` | kind=mcp http（P4b）：`HttpSession`（Streamable HTTP：POST JSON-RPC、JSON／單次 SSE 回應、`Mcp-Session-Id`、不跟轉址、DELETE 收尾）、`HttpBackend`（Bearer token 或 OAuth）、`parse_sse`、`new_session`（測試換掉） |
| `src/synox/packs/oauth.py` | 遠端 MCP 的 OAuth（選配）：`Flow`（PKCE＋state、貼回網址、換／更新 token 存 PackSecrets、`/<群組>_login／_code／_logout`）、`Listener`／`PasteListener`／`LoopbackListener`（只有介面，叫了就拒） |
| `src/synox/sdk/` | 給 pack 作者：JSON 信封、`Pack.load`、`init_pack`、`zip_pack`；`synox-sdk init｜check｜zip`（`python -m synox.sdk`）。說明 [sdk.md](sdk.md) |
| `src/synox/agent/` | `tools.py`（葉節點 → ToolSpec）、`loop.py`（`ai_decision`、一輪、用量）、`validate.py`（第 4 關呼叫驗證）、`delimit.py`（第 5 關工具結果分隔符）、`budget.py`（伺服器版成員每月額度；`BotPool` 頻道型 bot 一池）、`room.py`（頻道 AI：`RoomAgent`、`redact_reply`）、`capture.py`、`approve.py`（核准卡）、`skills.py` |
| `src/synox/schedule/` | `store.py`（伺服器版 `store.of(user)` 每人一份、`all_stores()`）、`runner.py`（30 秒、via=ROUTINE，以檔案主人的身分跑）、`commands.py`（`/remind_*`、`/schedule_*`） |
| `src/synox/web/` | Web UI：`server.py`（`WebUI.route(method, path, headers, body, session)` 做全部判斷；`_Handler` 是薄殼；只綁 127.0.0.1）、`channel.py`（`WebChannel`＝SDK Channel）、`chats.py`（每人的對話紀錄，密文）、`tokens.py`（一次性登入連結、cookie session）、`static/app.html`（一頁、vanilla JS）、`__init__.py`（`install`、`/web`、`/web_off`） |
| `src/synox/packs/admin.py` | `.synoxpack`：stage（zip 檢查＋第 1、2 關；記 zip 的執行位元、不解出 `__pycache__`）→ install_staged（再驗一次＋T2 要 `trust_publisher`＋第 3 關寫鎖）／移除到 `packs/_removed/`／`reload()`（Web UI、`synox install` 共用）；`format_tier`／`red`＝T2 的紅字段 |
| `src/synox/packs/tier.py` | 信任層級（SDK P7）：`assess`（T0／T1／T2＋掃不到內容的檔、外部程式、runtime auto 套件）、`warning_lines`、`confirm_problem`（publisher 一字不差）、`reconfirm_reasons`（升級）、`lock_fields` |
| `src/synox/packs/upgrade.py` | 同名再裝＝升級：`staged_upgrade`（「改了什麼」、semver 版本檢查，權限變大的標 alert＝紅字）→ `upgrade_staged`（舊的搬到 `_removed/<name>-<版本>-<時間>`＋旁邊留舊鎖、鎖換新）；`rollback`（`python -m synox packs rollback <name>`）。資料不在 pack 資料夾，不動；資料 schema 升級由 pack 自己負責 |
| `Install-Pack.bat`、`scripts/pack_zip.py` | 點兩下 `.synoxpack` 的落點（精靈勾了才在 HKCU 登記）；打包 |
| `src/synox/backup.py` | `export_backup`／`read_backup`：data/ 的 zip 用保管箱主金鑰加密（`Vault.encrypt_bytes`） |
| `src/synox/wizard/` | `pages.py`（tkinter 畫面：這台給誰用 → token → 配對 → AI → 完成）、`logic.py`（寫 config、mode、AI 頁的 helper、金鑰進保管箱）、`telegram_probe.py`（getMe、配對碼）、`shortcuts.py` |
| `src/synox/doctor.py` | 健康檢查（不改任何檔、不產生金鑰） |
| `packs/notes`、`packs/money`、`packs/remind` | 出廠 pack；remind 的程式在 `synox/schedule` |
| `connectors/notion`、`todoist`、`google-calendar`、`apple-reminders-caldav` | **已接上**：`kind: python`＋`capabilities: ["network"]`，只用 requests＋標準函式庫；憑證存 `pack.store.of(user)`（vault）。Notion REST `2025-09-03`（`tests/test_notion.py`）；Todoist API v1（`pack.py` 的 `Client`，`tests/test_todoist.py`）；Google 日曆走 OAuth（PKCE，不開埠）；Apple 是通用 CalDAV VTODO 用戶端（README 有可行性結論）。測試都換成假的 HTTP |
| `src/synox/connect.py` | `python -m synox connect <pack>`（`Connect-Apple.bat`）：照 pack.json `auth.fields` 用 getpass 問帳密，存進 `pack_secrets`（`src/synox/packs/secrets.py`，保管箱的鍵 `packs/<pack>/<field>`；跟 Web UI 工具頁「連接」表單是同一份）。帳密不經聊天：Telegram 會留紀錄、`[ROUTE]` log 印指令全文 |
| `Setup.bat`、`setup/bootstrap.ps1` | 一鍵安裝；`Start.bat`／`Stop.bat`／`Console.bat` |
| `tests/` | pytest；`conftest.py` 的 `make_bot` 用真的 packs＋真的 Vault＋`FakeAdapter`＋SDK `BotHarness` |

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
9. **Web UI 只綁 127.0.0.1**（`web/server.py` 的 `HOST`，不從 config 讀）；對外是營運者的反向代理＋TLS。每個 API 用 session 的那個人算權限，
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

13. **伺服器版 python pack 看信任**（PERM-8）：`loader.python_trust`——出廠的（`loader.BUNDLED` 且在內建 `packs/`／`connectors/`）＝core、
    有鎖＝`lock.trust_of`、沒鎖＝third-party；third-party 的 kind=python 群組 `owner_only`（`loader.trust_reason`，跟 PERM-7 的
    `restricted_reason` 同一個出口：item.detail、doctor／packs status 的 🔐 行）。伺服器版沒鎖又不是出廠的 pack 載入前補跑第 2 關
    （`loader.unlocked_scan`），沒過＝`rejected`、不載入。新加出廠 pack 要同時加進 `BUNDLED`。測試裡手放的 python pack 要給成員看，
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
    `cli.python`／`runtime.python` 的檔名、`..` 在第 1 關（`manifest.python_path_problems`）。T2 安裝一律要 `trust_publisher`＝pack.json `publisher`（`tier.confirm_problem`；
    `admin.install_staged`／`approve_installed`、`upgrade.upgrade_staged` 都過這裡；升級要不要重新確認看 `tier.reconfirm_reasons`）。
    鎖的欄位用 `tier.lock_fields` → `lock.approve(tier_fields=)`。執行期：`sandbox.required` 對 T2 一律 True、`sandbox.restricted_reason`
    對 T2 python pack 一律 owner_only（伺服器版）；個人版 `sandbox.t2_personal_note` 給 doctor。
    **packs.lock 雜湊每一個檔**（`lock.hash_files` 預設含 `__pycache__`，`"hash_scope": "all"`；舊鎖用 `lock.hashes_for` 照舊算法對）。
    上傳的 zip 不解出 `__pycache__`、`synox-sdk zip` 不打包它、`check_integrity` 不比它；SYNOX 的子程序一律 `PYTHONDONTWRITEBYTECODE=1`
    （`loader.context_env`）。**測試的 T2 pack 一律用位元組造假檔頭（`tests/test_t2_trust.py` 的 `FAKE_EXE`），絕不執行任何執行檔**；
    開發機不跑第三方 exe／npm 套件是擁有者的政策（docs/security.md「信任層級」）。
17. **巢狀參數的 schema 模式只給 MCP 工具、只給 AI**（Q6 方案 B）：pack.json `mcp.schema_tools` 列的工具，`mcp.shape_of(..., schema_mode=True)`
    用 `packs/mcp_schema.normalize` 正規化 inputSchema（白名單子集；`$ref`／`oneOf`／開放的 additionalProperties／路徑 format…＝不支援、
    `node.ai=False`、原因進 `shape.schema_problem` 與 doctor）。支援的話 `synox_tool_meta[path]["schema"]`＝正規化的 schema，
    `app.extras["synox_schema_runners"][path]`＝`install()` 的結構化入口；**兩個都要有才算 schema 模式**（`validate.schema_of`），
    所以 python／cli pack 寫 meta 也開不了。AI 那條：`loop.call_schema_tool` → `validate.check_schema_call`（`mcp_schema.check`：
    照 schema＋硬限制 3 層／20 鍵／2000 字／50 項／16 KB／未列的鍵／每個字串查 secret）→ DANGER／confirm 出卡（`desk.request(lines=, run=)`，
    卡上是 `mcp_schema.describe`）→ runner（同 `call()`，`structured=` 原樣當 arguments，進去前再驗一次）。`tools.build(..., app)` 才會給
    schema 模式的定義（`mcp_schema.tool_schema`）。**人打字的路徑不碰 schema**：leaf 照舊 `kit.parse_args(node.fields)`，必填是巢狀＝拒。
    硬限制是常數（`mcp_schema.MAX_*`），不要讓 pack.json 或 schema 放寬。測試在 `tests/test_schema_mode.py`（假 stdio 伺服器）。

另外：
- pack 的群組由 loader 依 pack.json 定義（`loader.group_policy`）：`access: owner`（預設）＝整組 `owner_only`；`member`＝伺服器版 `role=MEMBER`、
  個人版 `owner_only`；`everyone`＝最低一級；再套角色能力上限（只會更嚴，見 invariant 11）。agent 群組也用同一個規則（`member`）：個人版只有擁有者，伺服器版成員以上；
  `AgentFallback.accepts` 問的是 `authorize(user, agent.ai)`，不另寫判斷。訪客（最低一級）在 `ai_decision` 一律沒有工具。
- 權限宣告（PERM-2）：`surfaces` 沒有 `channel`（預設）→ `loader.surface_policy` 給群組 `private_only`；`data: shared` 的 WRITE／DANGER 葉節點
  在伺服器版由 `loader.shared_write_admin` 拉到角色階梯最高那一級（install 之後跑；個人版不動）。第 2 關照 `data` 檢查（`data: user` 不准裸 `pack.store`、
  `pack.secret(name)` 不給 user、`pack.path(` 要改 `pack.path_of(user, …)`（PERM-8）、cli 不准 `{data_dir}`）。`trust`（core｜third-party）不在 pack.json：安裝報告上選、`lock.approve(trust=)` 寫進鎖，
  舊鎖沒有＝third-party；升級沒給＝沿用舊鎖的。出廠 pack 與 connector 都宣告 `surfaces: ["dm"]`、`data: user`，新寫的 pack 也要寫。
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
  第 4 關 `check_call` 拒「值＝已存 secret（或夾著 8 字以上的）」。內建 connector 沒呼叫 pack.secret，不受影響——別讓它們變 managed，
  除非一起改成讀 `pack.secret`（遷移時加 `"managed": "synox"`）。
- `requires.synox` 不合 → `PackStatus.status = "incompatible"`（不載入、不算 `LoadReport.ok` 的失敗）；doctor、`packs status`、安裝的第 1、2 關都用
  `manifest.synox_problem` 那句人話。

## 跟 SDK 的差異／轉接（vendor 沒有改過）

| 什麼 | 為什麼 |
|---|---|
| `synox.packs.kit.command`（照位置填）而不是 SDK `Forms.leaf` | SDK 的 `parse_fields` 把第一個 `key=` 之前的字全給第一個欄位：`/money 120 午餐` 會變成 amount="120 午餐"。kit 照位置分配，最後一個欄位吃剩下的；仍設 `node.fields` 給 AI schema。缺必填回用法、不開問答；不收 `fresh_code` 欄位（要碼的指令用 SDK Forms） |
| `llm/claude_code.py` 直接 `subprocess.run`，不經 `JobRunner`（SDK invariant 10） | adapter 不拿 app（invariant 2）。有 argv 陣列、`CREATE_NO_WINDOW`、逾時；沒有 Job Object 收程序樹 |
| 核准卡的節點叫 `agent.ai_approve`（`/ai_approve`），不是 `agent.approve` | 群組 `agent` 是 bare（葉節點直接用自己的名字：`/ai`、`/ai_usage`），`approve` 會變成 `/approve`，跟 AI 無關的名字容易撞名 |
| 排程（`synox/schedule`） | SDK D6 沒有排程。照 ClawBot `routines/runner.py`，只做每天 HH:MM 與某一天一次；沒有「連續失敗自動暫停」 |

## 模式（`config.json` 的 `mode`）

| | personal（預設） | server |
|---|---|---|
| 誰用得到 | 擁有者 | 擁有者＋被升級的人；陌生人是 GUEST，只看得到 `access: everyone` |
| 帳號管理 | 沒有 | SDK `accounts`（`/me`、`/me_upgrade`、`/user_list`、`/user_role`）＋`limits`（`/limit_*`） |
| pack 資料 | `data/<pack>.json.enc` 一份 | `data/users/<id>/<pack>.json.enc` 每人一份 |
| 提醒、排程 | 擁有者；`data/schedule.json.enc` | 成員以上；每人 `data/users/<id>/schedule.json.enc`，提醒送給建立的人，排程以他的身分跑（建立時 via=SCHEDULE 檢查裡面的指令） |
| AI | 擁有者 | 成員以上；工具只有 `ai_decision` 對他放行的；每月額度 `ai_member_monthly_usd`（預設 2.0，`/ai_budget` 調），用量 `data/users/<id>/llm_usage.json` |
| 網頁介面 | `/web`：擁有者 | `/web`：每個人（訪客也可以，看到的只有自己能用的）；帳號頁給擁有者／管理員 |
| 舊資料 | — | 個人版的共用檔不會自動搬到 `data/users/<擁有者>/`（留著不動；改回個人版又會用它們） |

工程師模式：不跑精靈，照 `config.example.json` 寫 `config.json`（含 `mode`），`python -m synox run`。

## ntu_easy_llm（擁有者的套件，LLM 那一層）

- 用 API 金鑰的四種 kind（`openai`、`anthropic`、`gemini`、`openai_compat`）都經 `ntu_easy_llm.agent.chat`（0.5.0 起才有；舊的 `ask*` 沒有工具呼叫）。
  `claude_code`、`fake`、`none` 不需要它。`easy_llm.py` 用到時才 import；沒裝 → `LLMError("還沒安裝 ntu_easy_llm：…")`。
- **現在（還沒發佈）**：`pyproject.toml` 的選用組 `llm = ["ntu_easy_llm>=0.5.0"]`；開發機手動裝本機的 wheel：
  `.venv\Scripts\python.exe -m pip install C:\Users\user\Documents\ntu_easy_llm\dist\ntu_easy_llm-0.5.0-py3-none-any.whl`
  （它會一起裝 openai、anthropic、google-genai 三個 SDK——那是舊 API 要的；SYNOX 用的 `agent` 只用標準函式庫打 HTTP）。
- **擁有者發佈 GitHub release 之後**：把 `pyproject.toml` 那一行換成（跟 ClawBot `requirements.txt` 同一種寫法）

  ```
  llm = ["ntu_easy_llm @ https://github.com/ChouYangEn0401/ntu_easy_llm/releases/download/ntu_easy_llm-0.5.0/ntu_easy_llm-0.5.0-py3-none-any.whl"]
  ```

  並把 `setup/bootstrap.ps1` 的 `pip install -e $Root` 改成 `pip install -e "$Root[llm]"`，一般使用者裝完就有。
  **不要**寫成只有名字的 `ntu_easy_llm>=…` 給一般使用者裝：它不在 PyPI 上，萬一有人在 PyPI 註冊了同名套件，pip 會去裝那個。
  `requirements.txt` 只用 ASCII（要加的話就是同一行網址，本身是 ASCII）。

## Known limitations / next steps

- AI 對話紀錄只在記憶體（每個聊天最近 6 輪），重開就忘。
- 經 AI 呼叫的 kind=cli 一般指令已改成同步（`api.via_ai`），結果交回 AI。仍然例外：`background: true` 的 cli 指令（AI 只拿到「開始了」，
  結果之後直接送給使用者），以及 python pack 自己丟背景執行緒回覆的指令（同樣的問題，要 pack 自己看 `api.via_ai` 改成同步）。
- 核准卡按下執行的結果直接給使用者，只在 AI 的紀錄留一句「已執行」，不會自動再開一輪讓 AI 接著做。
- `Setup.bat` 的完整安裝路徑（winget、embeddable zip）沒有在任何一台陌生電腦上跑過；精靈的畫面沒有自動化測試（只測了 logic／probe／shortcuts）。
- connector 全部接上了，但都只對假傳輸測過。網頁工具頁對 kind=python 一律顯示「已連接」，沒設憑證時要打各自的 `_status`；
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
  Telegram 指令選單在 reload 之後不會自動重設（重開 bot 才會）；設定頁改 AI 來源要重開 bot 才生效。
- `/backup` 的 Telegram 指令與還原按鈕沒做（只有網頁下載＋`synox.backup.restore_cli`）；備份綁 DPAPI，換電腦解不開。
