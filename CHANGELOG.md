# Changelog

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
