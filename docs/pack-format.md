# Pack 格式

一個 pack＝一個資料夾，放在 `packs/`（功能）或 `connectors/`（接外面的服務）。SYNOX 啟動時掃
`packs/*/pack.json` 與 `connectors/*/pack.json`，一個壞掉只跳過那一個（`python -m synox doctor` 會列出原因）。

```
packs/money/
  pack.json     宣告（下面）
  SKILL.md      給 AI 看：什麼時候用哪個指令
  README.md     給人看：有哪些指令、資料存哪
  pack.py       kind=python 時：install(app, pack)
```

## pack.json

```json
{
  "name": "money", "title": "💰 記帳", "summary": "記一筆、看這個月、設預算",
  "version": "0.1.0", "kind": "python",
  "group": "money",
  "category": "生活",
  "access": "owner",
  "surfaces": ["dm"],
  "data": "user",
  "order": 20,
  "python": { "module": "pack" },
  "requires": { "pip": [], "config": [], "env": {} },
  "skill": "SKILL.md",
  "storage": "vault"
}
```

| 欄位 | 必填 | 說明 |
|---|---|---|
| `name` | ✅ | 小寫英數字、`-`、`_`，32 字內。`config.json` 的 `packs.disabled` 用它 |
| `title`、`summary` | ✅ | `/help` 那一頁的標題與說明；也進 AI 的系統提示 |
| `version` | ✅ | `0.1.0` 這種 |
| `kind` | ✅ | `python`｜`cli`｜`connector`（下面） |
| `group` | | 指令群組，小寫英數字 16 字內；沒寫＝`name` 去掉 `-`、`_`。`group: money` → `/money`（主要動作）、`/money_list`… （這是**指令的前綴**，不是網頁工具頁的群組；那個是下一列的 `category`） |
| `category` | | 網頁「工具」頁**建議**把這個 pack 放在哪個群組（給人看的名字，例如 `"生活"`、`"待辦與行程"`；一行、24 字內）。沒寫＝「未分類」。**使用者自己排過的優先**（每個人的排法存在自己的偏好，不寫進 pack 資料夾）；同名的 category 會放進同一個群組。安裝時格式不對＝拒裝；已裝的舊 pack 寫壞了＝當作沒寫。見 [tools.md](tools.md)「網頁工具頁」 |
| `access` | | `owner`（預設：只有安裝時配對的那個人，別人打了跟不存在一樣）｜`member`（伺服器版：成員以上；個人版＝`owner`）｜`everyone`（任何人，伺服器版的訪客也算） |
| `surfaces` | | 在哪裡能用：`["dm"]`（預設：只能私訊，群組／頻道裡打了 SDK 回「請私訊」）｜`["dm", "channel"]`（也能在頻道用）。一定要有 `dm`。見下面「權限宣告」 |
| `data` | | 資料屬於誰：`none`｜`user`（每個人自己一份）｜`shared`（大家共用一份）。沒寫照預設推（下面「權限宣告」）；第 2 關照它檢查程式 |
| `order` | | `/help` 的排序（小的在前，預設 100） |
| `skill` | | SKILL.md 的檔名（要存在） |
| `storage` | | `vault`（`pack.store` 落地是密文 `data/<name>.json.enc`；伺服器版 `pack.store.of(user)` 是 `data/users/<id>/<name>.json.enc`）｜`plain`（`data/<name>.json`，預設） |
| `requires.config` | | `config.json` 要有的欄位；缺了就不載入（doctor 會說缺什麼） |
| `requires.env` | | 要有的環境變數（清單或 `{名字: 說明}`）；缺了就不載入。kind=cli 時**這些名字也是子程序唯一看得到的密鑰**：SYNOX 叫工具時會把像密鑰的變數（`*_TOKEN`、`*_API_KEY`、`*_SECRET`、`*_PASSWORD`…）拿掉，只放行這裡（和 `auth.fields[].env`）列的 |
| `requires.synox` | | SYNOX 最低版本，例如 `">=0.3"`（逗號接好幾個：`">=0.3,<1.0"`；只寫 `"0.3"`＝`>=0.3`）。寫錯＝pack.json 不合；這台的 SYNOX 不合＝**不載入**（狀態「SYNOX 版本不合」），doctor、`packs status`、安裝報告會說要哪一版、這台是哪一版 |
| `requires.pip` | | 要的 Python 套件。`runtime.python` 是 `"auto"`（只給 kind=cli）時，安裝會建 venv 照這份裝，每一項都要是 `名字==版本`（見下面「依賴與環境自動建置」）；沒有 `auto`＝SYNOX 不會幫你裝，只是給人看 |
| `web.panel` | | Web UI 工具頁的面板：pack 資料夾裡的一個 `.html`（不能用 `..`、絕對路徑）。網頁在 `<iframe sandbox="allow-scripts allow-same-origin">` 裡掛 `/packs/<name>/panel`，只給看得到這個 pack 的人 |
| `web.api` | | 面板能打的資料：`["GET /summary"]`（只支援 GET，名字小寫英數字）。pack 在 `install` 裡用 `pack.web_route("summary", fn)` 掛，`fn(user)` 回可以轉 JSON 的東西（**只回這個人自己的**：用 `pack.store.of(user)`）。沒宣告的 route 掛了也打不到 |

面板範例：`packs/money/panel.html`（這個月的總額＋預算條，打 `GET /api/packs/money/summary`）。
面板是 pack 自己的 HTML，跟 `pack.py` 一樣是你決定要不要信任的程式碼：它跟 Web UI 同源，能做你在網頁上能做的事。

`.synoxpack`＝一個 pack 資料夾壓成的 zip（`pack.json` 在最上層，或在唯一的那個資料夾裡）；`synox-sdk zip`／`scripts\pack_zip.py`
會打包並算好 `integrity.sha256`（[sdk.md](sdk.md)）。裝的路有三條，都跑同一條安全管線（[security.md](security.md)「五關」）：
Web UI 設定頁上傳、點兩下 `.synoxpack`（精靈裡勾過的話，`Install-Pack.bat`）、`python -m synox install <檔> [--yes]`。
檢查 zip（沒有絕對路徑、`..`、符號連結；檔名不能是 Windows 保留名（`CON`、`NUL`、`COM1`…，加副檔名也算）、不能有冒號（NTFS 資料流 `x.py::$DATA`）或 `< > " | ? *`、結尾不能是空白或句點；5 MB／解開 20 MB／300 個檔以內）→ 第 1 關宣告 → 第 2 關靜態掃描 → 給人看報告 →
按確認 → 第 3 關寫 `data/packs.lock` → 搬進 `packs/`。移除＝搬到 `packs/_removed/<name>-<版本>-<時間>`（不刪），鎖的那一筆一起拿掉
（旁邊留一份 `<那個資料夾>.lock.json`，`packs rollback` 用）。

### 升級（同名再裝一次）

已經裝了同名的 pack，再裝＝**升級**（`src/synox/packs/upgrade.py`）。一樣先跑第 1、2 關，報告多一段「改了什麼」：

- 新增／移除的 command（cli 的 `commands`、mcp 的 `tools_allow`；python pack 的指令寫在程式裡，比不出來，看檔案差異與掃描報告）
- **紅字（醒目）**：effect 變寬（`READ` → `WRITE` → `DANGER`）、新增 `WRITE`／`DANGER` 的 command、`capabilities` 新增、
  執行方式改了（`kind`、`runtime`、`cli.argv`／`python`／`cwd`／`env`、`python.module`、`mcp.url`）、`auth` 改了、
  多要密鑰環境變數、`access` 變寬、新加網頁面板、`storage` 從 `vault` 改成 `plain`、`surfaces` 多了 `channel`、
  `data` 變寬（`none` → `user` → `shared`）、這次選的 `trust` 跟裝著那一份的鎖不一樣（不管哪個方向；升級沒選＝沿用舊的）
- 一般字：移除 command、effect 變窄、不再要某個能力；還有每個檔改了／多了／少了

**版本**：新的 `version` 要是 semver（`1.2.3`、`1.2.3-beta.1`），而且要比裝著的大。一樣或比較小 → 明講並拒絕，
除非明確選「降級／重裝」（網頁勾選框；終端機 `--allow-downgrade`）。新版本不是 semver（例如 `1.2.3.4`）一律不升級。

按「確認升級」（終端機 `python -m synox install <檔> --yes`）：再驗一次 → 舊資料夾搬到 `packs/_removed/<name>-<舊版本>-<時間>`
（旁邊留舊的鎖）→ 新的搬進 `packs/` → `packs.lock` 換成新的一筆 → 重新載入。

**環境**（`runtime.python`／`runtime.node` = `"auto"`）：新版要環境，而且（舊版不用環境、或 `requires.pip`／`package-lock.json`
跟舊版不同、或現在的 `data/envs/<name>/` 沒建好／對不上）→ 升級報告多一段跟安裝報告一樣的「🧱 要建環境／要重建環境」清單；
確認升級之後跟全新安裝一樣建（網頁：背景建，好了／失敗都通知擁有者；終端機 `--yes`：等它建完）。建失敗**不退回升級**：
新版已經裝好，狀態 `missing`、doctor 說原因，修好後 `python -m synox packs env rebuild <name>`。套件清單沒變＝報告寫「沿用」、不重建。

**退回**：`python -m synox packs rollback <name>`：`_removed` 裡這個 pack 最近一份（升級或移除時搬走的）搬回 `packs/<name>`，
`packs.lock` 改回當時核准的那一筆（檔案跟當時的鎖對不上就不鎖，要你 `packs lock --approve`）。現在裝著的那份搬到 `_removed`；
退回時搬走的那份下次退回會跳過，所以連退兩次＝再往前一版。要回到新版就重新裝那個 `.synoxpack`。
舊版要環境、而 `data/envs/<name>/` 跟它對不上（例如升級時已經重建成新版的套件）→ 退回後會提示跑 `packs env rebuild <name>`，**不自動建**。

**資料不在 pack 資料夾裡**（`data/<name>.json.enc`／`data/<name>.json`、伺服器版 `data/users/<id>/`、cli 的 `{user_data_dir}/<name>/`），
升級、退回都不會動到資料。**資料格式（schema）要不要升級是 pack 自己的事**：建議在資料裡存一個 `schema` 版本號，
新版程式讀到舊格式就自己轉換；退回到舊版時舊程式要能看得懂（或至少不弄壞）新版寫的資料——做不到就在 SKILL.md／README 寫清楚「不能退回」。

### 權限宣告：`surfaces`、`data`、安裝時選的 `trust`

舊的 pack 沒寫照舊能用（照下面的預設）；出廠的 notes、money、remind 與 4 個 connector 都寫了 `"surfaces": ["dm"], "data": "user"`。

| | 值 | 沒寫的預設 | 效果 |
|---|---|---|---|
| `surfaces` | `["dm"]`｜`["dm", "channel"]` | `["dm"]` | 沒有 `channel` → loader 定義群組時加 `private_only`（SDK `authorize` 自己擋群組／頻道） |
| `data` | `none`｜`user`｜`shared` | python：有寫 `storage`＝`user`，沒寫＝`none`；cli：樣板（argv、env、cwd、stdin）用了 `{user_data_dir}`＝`user`、只用 `{data_dir}`＝`shared`、都沒有＝`none`；connector／mcp＝`none` | 第 2 關的規則（下面）；`shared` 的 `WRITE`／`DANGER` 指令在**伺服器版**最低角色自動拉到管理員（擁有者不受影響） |

- 第 1 關：`surfaces` 有 `channel` 但 `data` 是 `user` → 拒（每個人的資料不能出現在頻道；不是個人資料就寫 `shared` 或 `none`）。
- 第 2 關（`scan.py`，不合＝拒裝，列 `檔名:行號`）：
  - python、`data: user`：不准裸用 `pack.store`（`pack.store.load`／`save`／`update`…是全部人共用的那一份）——要 `pack.store.of(user)`；
    `pack.secret(name)` 一定要給 user（`pack.secret(name, user)`）；不准用 `pack.path(...)`（全部人共用的資料夾）——要 `pack.path_of(user, ...)`。
  - python、`data: none`：不准用 `pack.store`、`pack.path`、`pack.path_of`（有存資料就宣告 `user` 或 `shared`）。
  - cli、`data: user`：樣板不准 `{data_dir}`（只能 `{user_data_dir}`）；`data: none`：兩個都不准。錯誤列 `pack.json:行號`。
- **`trust` 不在 pack.json**：安裝報告上擁有者選 `core`（跟出廠的一樣信得過）或 `third-party`（預設），寫進 `data/packs.lock`
  （網頁：報告上的下拉選單；終端機：`install <檔> --yes --trust core`；`packs lock --approve <name> [--trust …]` 沒給＝沿用舊鎖的）。
  舊的鎖沒有 `trust`＝當作 `third-party`。
- **伺服器版怎麼用 trust（個人版不受影響）**：
  - kind=python 在 SYNOX 程序裡跑、沒有沙盒，所以 `trust: third-party` 的 python pack **只對擁有者可見**：成員打了跟不存在的指令一樣
    （「未知指令」）、`/help` 與 AI 工具清單都沒有。`core`（擁有者安裝時選的）與出廠的照常。
  - 出廠的＝內建 `packs/`、`connectors/` 裡的 notes、money、remind 與 4 個 connector（不看鎖）。
  - **沒有鎖的**（手動放進 `packs/` 或 `packs.dirs`、沒走安裝流程）＝`third-party`；而且載入前補跑一次第 2 關靜態掃描，
    沒過＝狀態 `rejected`、不載入（理由列 `檔名:行號`）。信得過就 `python -m synox packs lock --approve <name> --trust core`。
  - 為什麼只給擁有者，`doctor` 與 `packs status` 都會寫一行 🔐。kind=cli 的第三方 pack 另外看沙盒（見 `docs/security.md`「運行空間（沙盒）」）。

## pack.json v2（架構 v1 §4）

在上面之上加的欄位；**舊的 pack 照舊能讀**。有任何一個 v2 欄位（`capabilities`、`publisher`、`integrity`、`mcp`、
`commands`、`runtime`、最上層 `env`、物件形式的 `auth`）就當 v2，cli 的每個 command 一定要寫 `effect`。
從網頁或 `synox install` 裝的時候一律用嚴格版（不管 v0 或 v2，cli 的 `effect` 都要寫）。

| 欄位 | 說明 |
|---|---|
| `capabilities` | 宣告要用的能力：`network`、`subprocess`、`filesystem:own`、`filesystem:any`（含 own）、`exec`。第 2 關的掃描看到用了、卻沒宣告 → **拒裝**。沒寫＝什麼都沒宣告（舊 pack 一樣，由掃描結果決定裝不裝得了）。`exec` 也包含：`sys.modules`、dunder 屬性（`x.__class__`、`__dict__`、`__globals__`…，用 `type(x)` 代替 `x.__class__`）、`getattr` 的屬性名不是字面字、`vars()`／`globals()`／`locals()`、呼叫對象看不出是什麼（`handlers[k](…)`、`f()(…)`：先指給一個變數再呼叫）。第 2 關攔的是直呼名與常見的間接取用，**是提醒不是門**；python pack 在 SYNOX 程序裡跑，個人版沒有任何隔離（[security.md](security.md)「五關」） |
| `publisher` | 發行者（給人看；沒寫會在報告裡提醒）。**T2 pack 一定要寫**：安裝者要一字不差地輸入這個值才裝得了（見下面「信任層級」）；升級時換了一律紅字 |
| `integrity.sha256` | `{"檔名": "64 個 16 進位字"}`，打包時算（`synox-sdk zip`）。有寫就每個檔都要對得上、也不能多出沒列的檔（`pack.json` 本身不算） |
| `auth` | v0 的字串（`oauth`／`token`／`caldav`）照舊；v2 寫 `{"type": "none｜token｜oauth｜caldav｜file", "fields": [...]}`。`token`／`file` 的 `fields` 由 SYNOX 收，見下面「pack 的 secret」 |
| `kind: "mcp"`＋`mcp` | 只登記：`{"url": "…", "tools_allow": ["search"], "effects": {"search": "READ"}}`（不連、不能附程式檔）。**真的連**：`"transport": "stdio"`（見下面「`mcp`（stdio）」）或 `"transport": "http"`（遠端 MCP，見「`mcp`（http）」）。兩種都是 `tools_allow` 不能空、每個允許的工具都要有 effect（沒寫＝拒） |
| `commands[].effect` | cli 的每個 command：`READ`／`WRITE`／`DANGER`（大小寫都收）。`commands` 也可以放最上層（等於 `cli.commands`） |
| `commands[].ai`、`commands[].confirm` | cli 的 command：`"ai": false`＝不給 AI 當工具；`"confirm": true`＝AI 呼叫前先送確認卡給人按（effect 照寫的算）。一定要是 true／false。synox_sdk 的 `@tool(ai=…, confirm=…)` 會產生。跟工具執行中回的 `needs_confirm`（下一列）並存 |
| 回 `needs_confirm`（確認來回） | cli 工具最後一行印 `{"ok": true, "needs_confirm": true, "summary": "要刪 3 筆", "confirm_token": "…"}`（結束碼 0）→ SYNOX 出核准卡給下令的人（人打字、AI 呼叫都一樣），按 ✅ 用**同一組參數**重跑，那一次環境變數 `SYNOX_CONFIRMED=1`、`SYNOX_CONFIRM_TOKEN`＝你給的 `confirm_token`（只收英數字與 `. _ : -`、128 字內）；其他每一次都是 `SYNOX_CONFIRMED=0`（`cli.env` 寫了也會被蓋掉）。❌、過期、參數對不上＝不執行。任何語言都能用：自己讀這兩個環境變數。說明見 [sdk.md](sdk.md)「確認來回」 |
| `commands[].summary`、`fields[].ask`、`fields[].help`、`fields[].required`、`fields[].default` | 網頁工具頁的表單與 AI 的工具說明靠這些：`summary`＝這個指令做什麼；`ask`＝欄位的名字（問人的那句話，也是 AI 看到的參數說明）；`help`＝表單上欄位下面的補充說明（例如「只放數字，例如 1200」；**只給人看**，不進 AI 的 schema）；`required`＝必填（`true`／`false`）；`default`＝沒填時用的值（字串、數字或 `true`／`false`，要合 `kind`／`choices`；SYNOX 會自己補上再交給程式；`""`＝沒有預設）。**安裝時（strict）檢查型別**：`summary`／`ask`／`help` 要是 200 字內的一行字、`required` 要是布林（`"false"` 這種字串會被當成必填）、`default` 要合格式——不合＝拒裝；已裝的舊 pack 載入時不擋。沒寫 `summary`／`ask`、或 SKILL.md 沒有 frontmatter 不擋，但安裝報告與 `synox-sdk check` 會提醒（工具頁只看得到英文名字）。synox_sdk 的 `@tool` 會把函式參數的預設值（字串、數字、布林）寫成 `default` |
| `commands[].fields[].kind` | `text`（預設）｜`int`（整數，可有千分位逗號）｜`number`（數字）｜`bool`（是／否：`yes/no`、`true/false`、`1/0`、`是/否`…）｜`path`（值一定要在使用者自己的資料夾裡，第 4 關）｜`choice`（要寫 `choices: ["Red", "Blue"]`，大小寫不拘）。對 AI 的參數 schema 一律是字串；SYNOX 在交給程式**之前**照 kind 檢查（人打字與 AI 呼叫都會），不合回一句人話（例如「次數要是整數（例如 3）」）、不執行。交給程式的值整理過：`bool` → `true`／`false`、`int`／`number` 拿掉逗號、`choice` 換成 `choices` 裡的拼法 |
| `cli.python` | `{python}` 換成什麼：絕對路徑｜`"venv"`（`<pack 資料夾>/../.venv` 的 python）｜沒寫＝看 `runtime`，再沒有＝SYNOX 自己的 Python。**一定要指到 Python 直譯器**（檔名 `python`、`python3`、`python3.12`、`pythonw`、`pypy3`…，可以有 `.exe`）、不能有 `..`；要叫別的程式請直接寫在 `cli.argv` 第一段（算 pack 外的程式、T2）。kind=mcp 寫了也照樣檢查 |
| `runtime.python`、`runtime.python_posix` | 另一種寫法（放在自己 repo 裡、用那個 repo 的 venv 的外部 pack 常用）：相對於 pack 資料夾（或絕對路徑），Windows 用 `python`、其他用 `python_posix`。`cli.python` 有寫就用它。**`"auto"`**＝安裝時自動建 venv（見下面「依賴與環境自動建置」；跟 `cli.python` 不能同時寫）。一樣要是 Python 直譯器的檔名；`..` 只收 `../.venv/Scripts/python.exe`、`../venv/bin/python` 這種「pack 旁邊的 venv」 |
| `runtime.node` | **只給 kind=cli**（kind=mcp 寫了＝pack.json 不合；mcp 的 `{node}` 一律是系統的 node）。`{node}` 換成什麼：相對於 pack 資料夾（或絕對路徑）；**`"auto"`**＝系統的 node＋安裝時照 `package-lock.json` 裝套件；沒寫＝系統的 node。用到 `{node}` 的 pack 是 T2 |
| `env`（最上層）、`cli.env` | 子程序多帶的環境變數；兩個合併，`cli.env` 優先。值可以用下面的代換。名字像密鑰的（`*_TOKEN`…）一樣會被拿掉，除非列在 `requires.env`。名字只能用英數字和 `_`；**不收**會讓直譯器先載入別的程式的名字（`manifest.env_name_problem`，不分大小寫）：`PYTHON*`（只放行 `PYTHONIOENCODING`、`PYTHONUTF8`、`PYTHONUNBUFFERED`；`PYTHONPATH` 只收 `{pack_dir}` 或 `{pack_dir}/子資料夾`）、`NODE_OPTIONS`、`NODE_PATH`（`runtime.node: auto` 由 SYNOX 自己給）、`PATH`、`PATHEXT`、`COMSPEC`、`SYSTEMROOT`、`WINDIR`、`LD_*`、`DYLD_*`、`PIP_*`、`npm_config_*`、`PERL5*`、`RUBYLIB`／`RUBYOPT`、`BASH_ENV`、`JAVA_TOOL_OPTIONS`、`DOTNET_STARTUP_HOOKS`、`COR_*`…；`mcp.env`、`auth.fields[].env` 同一條。SYNOX 開子程序時另外明寫 `PYTHONNOUSERSITE=1`（不讀使用者層的 site-packages） |
| `web.routes` | cli pack 的面板資料：`{"route": "command"}`；沒寫＝同名。對應的 command 要是 `READ`、沒有必填欄位 |

### 信任層級：T0／T1／T2

第 2 關只讀得懂 `.py`。SYNOX 照「掃得到多少」把 pack 分三層（`src/synox/packs/tier.py`；說明與限制見 [security.md](security.md)「信任層級」）：

- **T0** 只有宣告：connector、只登記的 mcp。
- **T1** 原始碼：會被執行的只有第 2 關掃過的 `.py`／`.pyw`。`{python}` 要跑的 pack 內檔案**一定要是 `.py`／`.pyw`**
  （或含 `__main__.py` 的資料夾）——`./run.txt`、`./app.pyz`、沒有副檔名的 `./run` 第 2 關一律拒；
  其他檔當資料（沒有副檔名、`ast` 解析得過的也當 `.py` 掃）。T1 不等於安全：掃描是提醒不是門。
- **T2** 二進位或外部相依，只要有一項就是：
  - 資料夾裡有**掃不到內容的檔**：`.exe .dll .com .bat .cmd .ps1 .vbs .sh .so .dylib .pyd .pyc .pyo .jar .class .node .wasm .msi .scr`、
    壓縮檔 `.pyz .pyzw .zip .whl .egg`（Python 可以直接從裡面 import 或執行）、
    別的語言的原始碼（`.js .mjs .cjs .ts .tsx .jsx .rb .pl .php .lua .go .rs .java .kt .cs .psm1 .bash .zsh…`，完整清單是
    `src/synox/packs/scan.py` 的 `SOURCE_EXT`）、`node_modules/`、檔頭是 MZ+PE／ELF／Mach-O 的檔（副檔名寫什麼都一樣）、沒有副檔名但帶執行位元（zip 裡的 unix 權限）或 `#!` 開頭、
    `__pycache__` 裡對不到同一層 `.py` 的編譯檔。→ **`capabilities` 一定要有 `exec`**，不然拒裝。
  - `cli.argv`／`mcp.argv` 指到 **pack 外的程式**：`argv[0]` 不是 `{python}`／`./…`（例如 `{node}`、`npx`、`git`、`C:\…\x.exe`），
    後面一段是直譯器（`node`、`npx`、`deno`、`bun`、`ruby`、`perl`、`php`、`python3`、`cmd`、`bash`…）、看起來是檔案路徑
    （`C:/…`、`/usr/bin/x`、`..`；`/c`、`/k` 這種 Windows 旗標不算）、直譯器要跑的程式在 pack 外（`{data_dir}/x.py`、`C:/x.py`），
    或 `{python} -m 模組` 而模組不在 pack 裡。不擋，報告記解析後的路徑（只查 PATH，不執行）、標「未鎖定執行環境」。
  - `{python}` 解析到 **pack 外的直譯器**：`cli.python` 是絕對路徑或 `"venv"`（`<pack>/../.venv`）、`runtime.python` 指到 pack 外。
    SYNOX 自己的 Python、`runtime.python: "auto"` 建的 venv、pack 資料夾裡的不算。報告與鎖記解析後的路徑。
  - argv 讓直譯器**直接執行一段程式碼**：`{python} -c`／`-i`／`-`／沒指定程式（讀 stdin）、`powershell -Command`／`-EncodedCommand`／
    不是旗標的字、`cmd /c`／`/k`、`node -e`／`-p`／`-r`、`deno eval`、`bash -c`、`ruby -e`、`perl -e`、`php -r`、`osascript -e`，
    或要跑哪支程式由欄位決定（`["{python}", "{script}"]`）。旗標寫在 `commands[].argv` 裡也算。→ **一定要宣告 `exec`**，不然拒裝。
  - `runtime.python`／`runtime.node` = `"auto"`（會裝 `requires.pip`／`package-lock.json` 的套件）。

T2 的安裝報告有紅字一段（會執行什麼、會裝哪些套件、外部程式解析到哪），**`pack.json` 一定要寫 `publisher`**，安裝者要明確輸入它：
網頁勾選「我信任這個發行者」並輸入名字、終端機 `python -m synox install <檔> --yes --trust-publisher "<publisher>"`。
寫進 `packs.lock`：`tier`、`t2`（`opaque`：路徑／大小／sha256／原因、`external`、`packages`、`runs`）、`trusted_publisher`、`trusted_at`。
升級時 publisher 變了、新增 `exec`、可執行的東西變多、或 T1 → T2：紅字、要重新輸入；其他沿用。
伺服器版的 T2 pack 一定要真的沙盒（不管 trust），沒有＝只對擁有者可見。

打包時別把 `__pycache__` 放進 zip（`synox-sdk zip` 本來就不放；放了 SYNOX 也不解出來）。packs.lock 的雜湊涵蓋 pack 資料夾裡的每一個檔。

### pack 的 secret（`auth.fields`）

pack 要使用者的 API key、token、憑證檔時，寫在 `auth.fields`，**SYNOX 收、SYNOX 存**，pack 自己不用寫設定指令：

```json
"auth": {"type": "token",
         "fields": [{"name": "api_key", "label": "Todoist API token", "secret": true, "env": "TODOIST_API_KEY",
                     "help": "Todoist 設定 → 整合 → 開發者"}]}
```

| 欄位 | 說明 |
|---|---|
| `name` | 小寫英數字、`_`。保管箱裡的鍵是 `packs/<pack>/<name>` |
| `label`（或 `ask`）、`help` | 表單上給人看的字 |
| `secret` | `true`＝密碼框、**永遠不回傳值**（網頁只看到「有填」與最後 4 碼），第 4 關會擋 AI 把它當參數送出。`false`（預設）的值會回給表單 |
| `env` | kind=cli：這個值放進子程序的這個環境變數（也自動列進 `keep_env`）。**絕不放進 argv**。沒寫 env 的欄位 cli 拿不到 |
| `kind` | `text`（預設，不能換行）｜`file`（上傳一個文字檔，例如 service account JSON；最多 32000 字）。`auth.type: "file"` 時預設 `file` |
| `required` | 預設 `true`。必填的沒填＝工具頁顯示「要先設定」，cli 指令回「到網頁工具頁按『連接』」、不執行 |

- 只做 `auth.type` 是 `token`／`file`（`oauth` 這一版不做）。
- 怎麼填：Web UI 工具頁那個 pack 的「🔌 連接」（留空＝沿用原值）；或在電腦上 `python -m synox connect <pack>`（同一份）。
  **Telegram 不收**（聊天紀錄留在 Telegram 的伺服器上）。個人版只有擁有者能設；伺服器版每個人設自己的（`vault.for_user`）。
- 怎麼拿：kind=cli 從環境變數讀；kind=python 用 `pack.secret("api_key", user)`（伺服器版一定要給 user）。
- 哪些 pack 算「SYNOX 收」：kind=cli 一律；kind=python 要原始碼有呼叫 `pack.secret(...)`。`"auth": {"managed": "pack"}`＝pack 自己管
  （例如內建 connector 的 `/todoist_token`），`"managed": "synox"`＝一定 SYNOX 收。內建的 notion／todoist／google-calendar／apple-reminders
  都還是自己的指令，不受影響。

### kind=cli 的代換

`cli.argv`、每個 command 的 `argv`、`env`（最上層與 `cli.env`）、`cli.cwd` 裡的這幾個字，**每一次呼叫**照下令的人換掉：

| 寫法 | 換成 |
|---|---|
| `{python}` | 上面 `cli.python`／`runtime` 決定的直譯器（`auto`＝`data/envs/<pack>/venv` 的 python；規則在 `envs.python_target`，第 2 關用同一份判斷它在不在 pack 外） |
| `{node}` | `runtime.node` 決定的 node（`auto` 或沒寫＝系統的 node） |
| `{pack_dir}` | pack 資料夾的絕對路徑 |
| `{data_dir}` | SYNOX 的 `data/` |
| `{user_data_dir}` | 伺服器版 `data/users/<tg_id>`（第一次用時建立）；個人版 `data/` |
| `{tg_id}` | 下令的人的 Telegram id（排程、網頁也是那個人） |

欄位不能取這幾個名字。使用者給的值只換一次（值裡寫 `{data_dir}` 不會被換）。
**`{python} -m 模組` 時 `cli.cwd`（`mcp.cwd`）一定要在 pack 資料夾裡**（`.`、`./子資料夾`、`{pack_dir}…`）：
`python -m` 會先從 cwd 找模組，cwd 是 `{user_data_dir}` 時，使用者資料夾裡同名的 `.py` 會先被載入（沒鎖、沒掃過）。
資料要放使用者資料夾就用環境變數告訴程式（例如 `"env": {"MYTOOL_HOME": "{user_data_dir}/mytool"}`），或改成 `{python} ./tool.py`（腳本模式不受 cwd 影響）。
子程序另外一定拿到這幾個環境變數（[synox_sdk](sdk.md) 的 `context()`／`secret()` 讀它們；蓋過 pack 自己寫的同名變數）：
`SYNOX_USER_DATA_DIR`（＝`{user_data_dir}`）、`SYNOX_TG_ID`、`SYNOX_MODE`（`personal`｜`server`）、`SYNOX_PACK_DIR`、`SYNOX_PACK_NAME`、
`SYNOX_SECRET_ENV`（`auth.fields` 的「欄位名=環境變數名」，逗號分隔；只有名字，值照舊只在那個環境變數裡）。
沒填的選填欄位：`--k={v}` 那一段拿掉；單獨一段的 `{v}` 連同前面緊鄰的字面 `--旗標` 一起拿掉。
樣板規則（第 2 關）：只能是字面字、單獨一段的 `{欄位}`、或 `--k={欄位}`；`["--k", "{v}"]` 這種分兩段的會被拒（要寫成 `--k={v}`）。

### 依賴與環境自動建置（`runtime.python`／`runtime.node` = `"auto"`，只給 kind=cli）

```json
"runtime": {"python": "auto", "python_posix": "auto"},
"requires": {"pip": ["requests==2.32.3", "idna==3.7"]}
```

- **Python**：安裝時在 `data/envs/<pack>/venv` 跑 `python -m venv`，再
  `pip install --no-deps --only-binary=:all: -r requirements.txt`。`requires.pip` 每一項都要是 `名字==版本`
  （`>=`、`~=`、萬用字元、extras、環境標記、網址、`-r`／`--index-url` 之類都算 pack.json 不合）；`--no-deps` 所以相依的套件也要自己列。
  只裝現成的 wheel（不在這台電腦上跑套件的 setup.py）。
  **雜湊（建議）**：每一項後面可以加 pip 的 `--hash=sha256:<64 個 16 進位字>`（一個或幾個，例如每個平台的 wheel 各一個）：
  `"requests==2.32.3 --hash=sha256:…"`。有寫就 `pip install --require-hashes`，下載到的檔對不上就不裝；要嘛每一項都寫、要嘛都不寫
  （混著寫＝pack.json 不合）。沒寫雜湊的，T2 安裝報告會紅字寫「版本釘選不等於來源可信」。
  **來源固定 PyPI**：pip 一律 `--isolated --index-url https://pypi.org/simple`（不讀 pip.conf、`PIP_INDEX_URL`、`PIP_EXTRA_INDEX_URL`），
  pack 不能指定 index；建環境的子程序只拿到乾淨的環境變數（`envs.BUILD_ENV_KEEP`：PATH、TEMP、使用者資料夾、代理設定…，
  `PIP_*`、`npm_config_*`、`PYTHONPATH` 一律不繼承），再加 `PIP_CONFIG_FILE=os.devnull`：pip 連全機（`C:\ProgramData\pip\pip.ini`）
  與 venv 裡的設定檔都不讀（`--isolated` 只跳過使用者的那一份）。
- **Node**：pack 裡要有 `package.json`＋`package-lock.json`；複製到 `data/envs/<pack>/` 後 `npm ci --ignore-scripts`
  （套件的安裝腳本一律不跑），裝進 `data/envs/<pack>/node_modules`；子程序拿到 `NODE_PATH` 指到那裡。系統沒有 node＝doctor 說缺、pack 不載入。
  **只收官方 registry**：`package-lock.json` 每個 `resolved` 都要是 `https://registry.npmjs.org/…`，其他來源（`http://`、`file:`、
  `git+…`、別的 registry）＝拒裝；`npm ci` 固定 `--registry=https://registry.npmjs.org/`。
- pack 資料夾本身不寫任何東西（`packs.lock` 的雜湊才對得上）。
- **安裝流程**：第 2 關之後、按確認之前，報告多一段「🧱 要建環境：Python venv、裝 N 個套件：名稱 版本…」；按確認、pack 裝好之後才建
  （經 JobRunner，整個最多 10 分鐘，log 在 `data/job_logs/`）。建失敗＝pack 照樣裝好，狀態 `missing`、doctor 標「環境沒建好」並說原因
  （沒網路會直接說「連不上網路」）。重建：`python -m synox packs env rebuild <name>`。`requires.pip` 或 `package-lock.json` 改了也要重建（doctor 會說對不上）；
  經「升級」裝進來的新版會自動建／重建（見上面「升級」）。
- 建置的實作在 `src/synox/packs/envs.py`（`Builder.plan(m)`／`build(m, jobs, on_done)`；`set_factory` 可換實作）。

### 容器（`runtime.container`，kind=cli 與 kind=mcp stdio；建議提供）

作者「建議提供」：有了它，擁有者安裝時可以選「用容器跑」，伺服器版的第三方／T2 pack 選了容器、伺服器又有 podman／docker，
就能開給成員（沒提供或選不用容器，照舊只給擁有者）。做法與每個旗標防什麼：`docs/discussions/2026-11-10-isolation-howto.md`。

```json
"runtime": {"container": {
  "image": "ghcr.io/作者/工具@sha256:<64 個 16 進位字>",
  "network": false,
  "resources": {"mem_mb": 512, "cpus": 1, "pids": 64},
  "mounts": {"pack": "/pack", "user_data": "/data/user", "shared_data": "/data/shared"},
  "env_passthrough": ["WEATHER_API_KEY"],
  "user": "nonroot",
  "python": "python3"
}}
```

| 欄位 | 規則（第 1 關，`packs/container.py`；不合＝拒裝） |
|---|---|
| `image` | `image`／`dockerfile` 至少一個。**一定要帶 `@sha256:` digest**（只寫 `:latest`、`:1.0` 的不收：tag 會被換成別的內容）；registry 主機一定要寫、要在白名單（`docker.io`、`ghcr.io`、`quay.io`）；不收網址、`localhost`、IP、指定埠 |
| `dockerfile`＋`base` | pack 資料夾裡的相對路徑（檔名 `Dockerfile`／`Containerfile`／`x.Dockerfile`，不能有 `..`）；`base` 是 Dockerfile 的 `FROM`，一樣要帶 digest。Dockerfile 本身在 packs.lock 的雜湊裡。**第 2 關**掃 Dockerfile：一定剛好一個 `FROM`、跟 `base` 一字不差；`ADD <網址>`、`ADD --from`、`RUN --network`／`--security`、`COPY --from=<沒有 digest 的映像>`、`ONBUILD` 拒裝；`RUN` 裡的 `curl`／`wget`／`pip install`… 列進報告（提醒不是門）。**SYNOX 這一版不會替你 build**（S3）：營運者自己 build 成 `localhost/synox-<pack>:<Dockerfile sha256 前 12 字>` |
| `entry` | 只有 `stdio`（容器的 stdin／stdout 就是 cli／MCP 的管線；SYNOX 不開埠） |
| `network` | `true`／`false`，沒寫＝`false`（`--network none`）。**要跟 `capabilities` 的 `network` 一致**（一邊有一邊沒有＝拒）；`"host"` 這類字一律拒 |
| `resources` | `mem_mb`（16–65536）、`cpus`（0.1–64）、`pids`（1–4096）；執行時跟 `policy.sandbox` 取**小的**（pack 只能把上限調低） |
| `mounts` | 只能改 **容器裡** 的路徑（`pack`、`user_data`、`shared_data` 三個鍵）。不能指定本機路徑、不能 `..`、不能 `/`、不能在 `/proc`、`/sys`、`/dev`、`/etc`、`/usr`、`/run`、`/tmp`… 底下、不能碰 `*.sock`、彼此不能重疊。本機要掛什麼由 SYNOX 照 `data` 宣告算：pack 資料夾（唯讀）＋那個人的 `<user_data_dir>/<pack>`（或共用的 `data/packs/<pack>`）可寫，其他什麼都不掛 |
| `env_passthrough` | 選填：只放行這幾個密鑰名進容器（一定要是 `requires.env`／`auth.fields[].env` 列過的）；沒寫＝那些都放行。值不進命令列（`--env 名字`，值由 podman／docker 從 SYNOX 的環境拿） |
| `user` | `nonroot`（預設：podman `--userns=keep-id`＝SYNOX 帳號的 uid；docker `--user <SYNOX 的 uid:gid>`，Windows 上 `65534:65534`）或 `"uid:gid"`（都不能是 0）。`root` 一律拒 |
| `python`、`node` | `{python}`／`{node}` 在容器裡換成什麼（預設 `python3`／`node`；指令名或 `/` 開頭的路徑） |
| 其他欄位 | **一律拒**：`privileged`、`cap_add`、`devices`、`volumes`、`security_opt`、`network_mode`、`pid`、`ipc`、`args`、`ports`… 這些都是把牆打掉的開關 |

**在容器裡跑時的代換**：`{pack_dir}`→`/pack`、`{user_data_dir}`→`/data/user`、`{data_dir}`→`/data/shared`、`{python}`→`python3`
（照 `mounts`／`python` 改），`./tool.py`→`/pack/tool.py`；`SYNOX_USER_DATA_DIR`、`SYNOX_PACK_DIR` 也是容器裡的路徑。所以 argv 不用寫兩份。
可寫的只有 `{user_data_dir}/<pack 名字>/`（data=user）或 `{data_dir}/packs/<pack 名字>/`（data=shared），`/tmp` 是關門就清空的暫存。
容器裡的根檔案系統唯讀、沒有 Linux 特權、不能提權、程序數與記憶體有上限；`HOME=/tmp`。
**信任層級不變**（容器講的是「在哪跑」，層級講的是「掃得到多少」）；映像的內容 SYNOX 不看（跟 pip／npm 套件一樣）。
建議 SDK 產生的 pack 附一份 Dockerfile（`FROM docker.io/library/python@sha256:…`、`COPY . /pack`、非 root 使用者）。

經 AI 呼叫的一般 command 會**同步**跑完，印出來的結果（攤平成文字）交回 AI 當工具結果（包在每輪的分隔符裡），由 AI 轉述給人；
人自己打的指令照舊在背景跑、結果直接回給人。`background: true` 的 command 兩條路都一樣：先回「開始了」，做完直接通知人（AI 只知道「開始了」）。

## 三種 kind

### `python`

`pack.py` 有 `install(app, pack)`。群組已經由 loader 照 pack.json 定義好，你只掛葉節點：

```python
from isdtelekit.core.registry import DANGER, WRITE, Field
from synox.packs import kit

def install(app, pack):
    def add(api, chat_id, user, values):
        n = pack.store.update(lambda d: (d.setdefault("items", []).append(values["text"]), len(d["items"]))[1],
                              {"items": []})
        api.send_message(chat_id, f"記下了（第 {n} 筆）")

    kit.command(pack.group, "add", add, "記一筆", default=True, effect=WRITE,
                fields=[Field("text", "要記的內容", required=True)])
```

- `pack.group`：SDK 的 `Group`，`.leaf(...)` 或 `kit.command(...)` 都可以；要問答／驗證碼的用 `app.forms.leaf`（SDK Forms）。
- `pack.store`：`load(default)`、`save(data)`、`update(fn, default)`（讀改寫整段持鎖）；`key=` 可以分好幾份。
- **每個人自己的資料用 `pack.store.of(user)`**（同樣的 `load`／`save`／`update`）：個人版回共用的那一份；伺服器版（`mode: server`）回這個人自己的
  `data/users/<id>/` 那一份（vault 的金鑰由主金鑰＋id 用 HKDF 衍生）。直接用 `pack.store` 是整個 pack 共用的資料（例如設定）。
- **每個人自己的檔案用 `pack.path_of(user, "x.txt")`**：伺服器版 `data/users/<id>/<name>/files/x.txt`；個人版 `data/<name>/files/x.txt`。
  資料夾會先建好；不准絕對路徑、不准用 `..` 跑出那個資料夾（丟 `PackPathError`）；伺服器版一定要給 user。
- `pack.path("x.txt")`：`data/packs/<name>/x.txt`，**全部人共用**的檔案（`data: shared`／設定）。伺服器版 `data: user` 的 pack 呼叫會丟
  `PackPathError`（會跨戶），要改用 `path_of`；個人版照舊可以用（相容）。同樣擋 `..` 逃逸。
- `effect`：`READ`（預設）／`WRITE`／`DANGER`。**DANGER 的指令 AI 一律要送確認卡**；`/help` 標 ⚠️。
- `ai=False`：不給 AI 當工具（例如放寬安全的開關）。
- 不要 import 別的 pack；共用的東西放 `synox`。

`kit.command` 照位置填：`/money 120 午餐 跟同事` → amount、category、memo（最後一個欄位吃剩下的字）；
也收 `key=value`（AI 走這條）。`positional=2` 表示只有前兩個欄位能照位置填，其餘要寫 `key=`。

### `cli`

包一支「會印 JSON 的命令列程式」，不用寫 Python：

```json
{
  "name": "diary", "title": "📔 日記", "summary": "寫一篇、看今天", "version": "0.1.0", "kind": "cli",
  "cli": {
    "argv": ["{python}", "./diary_cli.py"],
    "cwd": ".",
    "json_flag": "--json",
    "timeout": 60,
    "commands": [
      {"name": "today", "argv": ["today"], "summary": "看今天", "default": true},
      {"name": "add", "argv": ["add", "{text}"], "summary": "寫一篇", "effect": "write",
       "fields": [{"name": "text", "ask": "寫什麼", "required": true}]}
    ]
  },
  "skill": "SKILL.md"
}
```

- `{python}` 等代換見上面「kind=cli 的代換」；`./` 開頭的換成 pack 資料夾裡的路徑。
- 每個 command 的填法跟內建的 python pack 一樣：**照位置填、`key=value` 補、選填的不追問**。
  例如記帳 pack 的 `/mybook 120 午餐` 直接存。`commands[].positional`＝前幾個欄位能照位置填（沒寫＝必填的個數；最後一個位置欄位吃掉剩下的字）；
  有驗證碼欄位（`fresh_code`）的 command 才走 SDK Forms（碼永遠最後問）。值以 `-` 開頭一律拒絕；loader 自己組 argv，
  因為開頭、env、cwd 要照「這一次是誰」代換。
- `commands[].stdin`：`"{answers}"` 這種樣板——那個欄位的內容走 **stdin** 給程式、不進 argv（長文字、日記正文；不會出現在
  程序清單與 log 的 argv 那一行）。程式那端從 stdin 讀。
- 程式要做的事：子指令＋`--json`，最後一行印一個 JSON 物件，結束碼 0＝成功。**回 `{"message": "…"}` 或 `{"text": "…"}` 最好**，
  會原樣給使用者；其他結構由 SYNOX 攤平（`synox/packs/render.py`：dict 一行一個 key、list 一行一項、最多 25 行）。

### `mcp`（stdio）

接一個 **MCP 伺服器**（任何語言寫的，包括 [synox_sdk](sdk.md) 的 `serve()` 的 `--mcp`）。SYNOX 開子程序、用 stdin／stdout 講
JSON-RPC 2.0（一行一個訊息），不開網路埠：

```json
{
  "name": "notes-mcp", "title": "📝 筆記（MCP）", "summary": "…", "version": "0.1.0", "kind": "mcp",
  "capabilities": ["subprocess"], "data": "user", "skill": "SKILL.md",
  "mcp": {"transport": "stdio", "argv": ["{python}", "./server.py", "--mcp"],
          "env": {"NOTES_DIR": "{user_data_dir}/notes-mcp"}, "cwd": ".", "timeout": 60, "start_timeout": 20,
          "tools_allow": ["search", "add_note", "delete_note"],
          "effects": {"search": "READ", "add_note": "WRITE", "delete_note": "DANGER"}}
}
```

- `argv`、`env`、`cwd` 的代換跟 kind=cli 一樣（`{python}`、`{node}`、`{pack_dir}`、`{data_dir}`、`{user_data_dir}`、`{tg_id}`；
  `./` 開頭＝pack 資料夾裡），SYNOX_* 環境變數、`auth.fields` 的 secret（只走環境變數）、像密鑰的環境變數拿掉（`requires.env`／
  `auth.fields[].env` 例外）也都一樣。`capabilities` **一定要有 `subprocess`**（沒有＝pack.json 不合）——所以預設的角色上限下，
  伺服器版只有管理員以上看得到（成員、訪客跟不存在一樣），要開給成員得在 `policy.roles` 給 member `subprocess`。
- `timeout`：每次 `tools/call` 等幾秒（預設 60）；`start_timeout`：啟動＋`initialize`＋`tools/list` 等幾秒（預設 20）。
- **只有 `tools_allow` 列的工具存在**：每個變成一個指令（`/<群組>_<工具名轉成小寫英數字與 _>`，例如 `getWeather` → `get_weather`），
  伺服器列了別的也看不到、叫不到。**effect 只看 `effects`**：伺服器的 `annotations`（readOnlyHint 之類）一律不算；沒寫 effect 的當 `DANGER`。
- 參數：第一次啟動時讀 `tools/list` 的 `inputSchema`（存在 `data/mcp/<pack>.tools.json`，之後載入先用存的）：`string`→`text`、
  `integer`→`int`、`number`→`number`、`boolean`→`bool`、`enum`→`choice`；屬性名轉成小寫英數字與 `_`（`maxResults` → `max_results`），
  送出時換回原名、轉成 JSON 型別。**巢狀 `object`／`array` 平面模式不給**（`doctor` 列出來）；是必填的話整個工具不給 AI、人打也不能跑
  ——要給 AI 就把工具列進 `schema_tools`（下面「schema 模式」）。
  說明（`description` 第一段，截到 200 字）進 `/help` 與 AI 的工具說明。還沒啟動過時，指令只有一個 `args` 參數，第一次呼叫後換成真的欄位。
  打字的填法跟 cli 一樣：必填的照位置填、其他 `key=value`。
- **schema 模式**（巢狀參數，stdio 與 http 都可以）：`"schema_tools": ["add-tasks", "create-pages"]`（一定要是 `tools_allow` 裡的工具）。
  這些工具的 `inputSchema` 先在本地正規化，支援的話 **AI** 拿到保留型別的工具定義（整數、布林、陣列、物件），呼叫參數照 schema 驗過，
  原樣（原型別、原屬性名）當 `tools/call` 的 `arguments`。**只給 AI**：人在聊天裡打不出巢狀，打字照舊只有平面欄位
  （必填的是巢狀＝人打字不能用，會說「只能經 AI 呼叫」）。
  - 支援的子集：`type`（單一型別，或 `["integer", "null"]` 這種加 null）、`properties`、`required`、`items`（單一 schema）、`enum`、
    `minimum`／`maximum`／`exclusiveMinimum`／`exclusiveMaximum`、`minLength`／`maxLength`、`minItems`／`maxItems`、`pattern`，
    以及只是說明的 `description`、`title`、`default`、`examples`、`format`、`$schema`、`$comment`…。
  - **不支援＝這個工具不給 AI**（`doctor` 寫原因）：`$ref`／`$defs`、`oneOf`／`anyOf`／`allOf`／`not`、`if`／`then`、`patternProperties`、
    `additionalProperties` 不是 `false`、沒寫 `type`、tuple 型的 `items`、`format` 看起來是路徑（path、file、dir、folder）、
    屬性名不是 `[A-Za-z0-9_.-]{1,64}`、schema 比 3 層深、一個物件超過 20 個屬性、太長或有巢狀量詞的 `pattern`。
    沒寫 `additionalProperties` 的物件 SYNOX 一律當成 `false`（schema 沒列的鍵不收）。
  - 硬限制（schema 寫得再寬也一樣）：巢狀 ≤3 層（最外層的參數物件算 1，`{"tasks": [{"title": …}]}` 剛好 3）、每個物件 ≤20 鍵、
    字串 ≤2000 字、陣列 ≤50 項、整包 JSON ≤16 KB、每個字串都不能等於或夾帶已存的 secret。
  - effect、核准卡照舊：`DANGER` 的卡把參數一行一個列出來（`pages[1].title = 「第一頁」`，長字串截短並標原長度，超過 30 行才省略並說省了幾行）。
  - 升級時 `schema_tools` 多了工具＝紅字。
- **程序**：每個（pack, 使用者）一個長駐子程序，第一次呼叫才啟動、閒置 10 分鐘收掉、崩潰了下次呼叫重啟、SYNOX 關閉時全部收掉；
  `auth.fields` 的值改了，下一次呼叫換新程序。逾時、印了非 JSON 的東西、中途結束 → 回一句人話（「超過 60 秒沒有回應，已經停掉」），
  這個程序收掉，下次重啟；不會卡住 bot。伺服器的 stderr 寫進 `<user_data_dir>/logs/mcp-<pack>.log`（不給聊天）。
- 呼叫走的路跟 cli 一樣：policy.decide（角色能力上限、surfaces、bot 範圍）→ 第 4 關驗參數 → `DANGER` 先出核准卡 → 結果包分隔符交回 AI。
- **確認來回**：工具回 `structuredContent: {"needs_confirm": true, "summary": "…", "confirm_token": "…"}`（`isError: false`）→
  SYNOX 出核准卡；按 ✅ 用同一組 `arguments`、`params._meta["synox/confirm_token"]`＝那個 token 再叫一次（一次性憑證、過期、
  參數對不上＝不執行；AI 碰不到 `_meta`）。synox_sdk 的 `raise Confirm(…)` 就是這樣回。
- 第 2 關：pack 裡的 `.py` 照一般規則掃；`argv` 指到 pack 外面的程式（`npx`、`node`、`uvx`、絕對路徑…）不擋，但報告與 `doctor`
  標「⚠️ 未鎖定執行環境」：`packs.lock` 只鎖 pack 資料夾裡的檔，外面那支被換掉不會發現。`data` 的規則同 cli（看 `argv`／`env`／`cwd` 樣板）。
- 沙盒同 cli：`box.wrap(argv, env, cwd, grants)`；`grants.timeout` 是空的（程序壽命由 SYNOX 管）；`required_for` 命中又沒真隔離
  ＝伺服器版只給擁有者。

### `mcp`（http：遠端 MCP）

接一個**別人架在網路上的 MCP 伺服器**（Streamable HTTP）。這台不跑它的程式，pack 只有宣告（不能附程式檔）：

```json
{
  "name": "todoist-mcp", "title": "✅ Todoist（MCP）", "summary": "…", "version": "0.1.0", "kind": "mcp",
  "capabilities": ["network"], "access": "member", "skill": "SKILL.md",
  "auth": {"type": "token", "fields": [{"name": "token", "label": "API token", "secret": true}]},
  "mcp": {"transport": "http", "url": "https://mcp.example.com/mcp", "bearer": "token", "timeout": 60,
          "tools_allow": ["find-tasks", "add-tasks", "delete-object"],
          "effects": {"find-tasks": "READ", "add-tasks": "WRITE", "delete-object": "DANGER"}}
}
```

範例（網址與工具名是佔位，要確認）：`examples/mcp-remote-notion`（OAuth）、`examples/mcp-remote-todoist`（token）。

- **第 1 關**：`url` 一定 `https://`（`http://` 拒）、有主機、不能有 `user:pass@`、`#`、`{樣板}`；`capabilities` 一定有 `network`，
  不能有 `subprocess`／`exec`／`filesystem:any`；不能寫 `argv`／`env`／`cwd`／`start_timeout`／`headers`。
  `tools_allow` 不能空、**每個工具都要寫 effect（沒寫＝拒）**。
- **第 2 關**：只能是宣告（附 `.py` 或執行檔＝拒）。信任等級 **T0（只有宣告）**：安裝報告逐一列出 `tools_allow` 的每個工具與 effect，
  請安裝的人確認；也寫明「請求與 token 會送到哪個主機」。
- **只往宣告的主機連**：每個 JSON-RPC 訊息 POST 到 `url`（`Accept: application/json, text/event-stream`）；**不跟著轉址**
  （伺服器回 3xx 一律拒，訊息會說它想轉到哪）。
- **回應**：`application/json`（一個物件）或 `text/event-stream`（只讀這一次 POST 的串流、找到自己那個 id 的回應就停；
  夾在裡面的通知、伺服器反問不處理；不開 GET 長連線、不續傳）。`initialize` 回了 `Mcp-Session-Id` 就之後每個請求都帶，
  也帶 `MCP-Protocol-Version`。帶了 session id 卻回 404＝伺服器那邊過期 → 自動重新 initialize、再試一次。閒置 10 分鐘或 SYNOX 關閉時
  送 `DELETE` 結束 session。
- **token**：`auth.type=token` → `auth.fields` 的 secret 欄位（`mcp.bearer` 指定，沒寫＝第一個 secret 欄位），網頁「連接」表單填、
  存保管箱（伺服器版每人一份）；送出時只放 `Authorization: Bearer …`。不寫 log、沒有 argv、結果與錯誤訊息裡出現會遮成 `***`。
  `auth.type=none`＝不帶 token。換了 token，下一次呼叫換一條新連線。
- **OAuth（選配，預設關）**：`auth.type=oauth`＋`auth.oauth`：
  `{"authorize_url": "https://…", "token_url": "https://…", "client_id": "…", "scope": "…", "redirect_uri": "http://127.0.0.1:47232/", "receiver": "paste"}`。
  會多三個指令（只收私訊、不給 AI）：`/<群組>_login` 給登入連結（PKCE S256＋一次性 state，15 分鐘）→ 瀏覽器最後轉到
  `redirect_uri` 顯示「無法連上」（**SYNOX 不開埠**）→ 使用者把網址列整串用 `/<群組>_code <貼上>` 傳回 → 換 token 存保管箱
  （快過期自動用 refresh token 換）；`/<群組>_logout` 拿掉。授權與換 token 都帶 `resource`＝`mcp.url`。`client_id` 要事先登記
  （這一版不做動態註冊與 metadata 探索）。`receiver: "loopback"`（SYNOX 暫時開 127.0.0.1 隨機埠收一次、最久 5 分鐘）**只有介面**：
  這一版叫它一律拒（`packs/oauth.py` 的 `LoopbackListener`）。
- 工具→指令、參數（inputSchema → fields、快取）、effect 只看 pack.json、policy／第 4 關／DANGER 核准卡／分隔符、`needs_confirm`
  確認來回（`_meta["synox/confirm_token"]`），全部跟 stdio 一樣。每個（pack, 使用者）一條連線，第一次呼叫才連。
- 角色：`capabilities` 只有 `network`，預設上限下成員看得到（`access` 要寫 `member`）、訪客看不到。

### `connector`

接外面的服務（Google 日曆、Notion…）。v0 **只登記**：一個群組、一個葉節點說「還沒接上」，不給 AI。
只寫 `mcp.url`（沒有 `transport`）的 kind=mcp 也一樣只登記。
`auth` 必填：`oauth`｜`token`｜`caldav`。設計寫在那個資料夾的 README。

## SKILL.md

照 [agentskills.io](https://agentskills.io) 的格式：開頭 frontmatter，`name`、`description` 必填（`when` 可選），後面是正文。

```markdown
---
name: money
description: 使用者提到花了多少錢、想記帳、問這個月花多少、或要設定每月預算時使用。
---

# 記帳
## 什麼時候用
- 「午餐 120」→ `money__add`：amount 只放數字…
```

- **AI 的系統提示只放 frontmatter**（每個約 100 token）；正文由 `skill_read` 工具在需要時才讀。
- `description` 也是網頁工具頁那個工具「說明」裡的「什麼時候用」。沒有 frontmatter（或少了 `name`／`description`）：
  AI 不會知道這個 pack，安裝報告與 `synox-sdk check` 會提醒（不擋）。
- 工具名＝節點路徑把 `.` 換成 `__`：`money.add` → `money__add`。參數名就是 Field 的 name。
- 正文寫「什麼時候用哪個工具、參數怎麼填、要注意什麼」，用繁體中文。
