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
  "access": "owner",
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
| `group` | | 指令群組，小寫英數字 16 字內；沒寫＝`name` 去掉 `-`、`_`。`group: money` → `/money`（主要動作）、`/money_list`… |
| `access` | | `owner`（預設：只有安裝時配對的那個人，別人打了跟不存在一樣）｜`member`（伺服器版：成員以上；個人版＝`owner`）｜`everyone`（任何人，伺服器版的訪客也算） |
| `order` | | `/help` 的排序（小的在前，預設 100） |
| `skill` | | SKILL.md 的檔名（要存在） |
| `storage` | | `vault`（`pack.store` 落地是密文 `data/<name>.json.enc`；伺服器版 `pack.store.of(user)` 是 `data/users/<id>/<name>.json.enc`）｜`plain`（`data/<name>.json`，預設） |
| `requires.config` | | `config.json` 要有的欄位；缺了就不載入（doctor 會說缺什麼） |
| `requires.env` | | 要有的環境變數（清單或 `{名字: 說明}`）；缺了就不載入。kind=cli 時**這些名字也是子程序唯一看得到的密鑰**：SYNOX 叫工具時會把像密鑰的變數（`*_TOKEN`、`*_API_KEY`、`*_SECRET`、`*_PASSWORD`…）拿掉，只放行這裡（和 `auth.fields[].env`）列的 |
| `requires.synox` | | SYNOX 最低版本，例如 `">=0.3"`（逗號接好幾個：`">=0.3,<1.0"`；只寫 `"0.3"`＝`>=0.3`）。寫錯＝pack.json 不合；這台的 SYNOX 不合＝**不載入**（狀態「SYNOX 版本不合」），doctor、`packs status`、安裝報告會說要哪一版、這台是哪一版 |
| `requires.pip` | | 給人看的（v0 不會自動 pip install） |
| `web.panel` | | Web UI 工具頁的面板：pack 資料夾裡的一個 `.html`（不能用 `..`、絕對路徑）。網頁在 `<iframe sandbox="allow-scripts allow-same-origin">` 裡掛 `/packs/<name>/panel`，只給看得到這個 pack 的人 |
| `web.api` | | 面板能打的資料：`["GET /summary"]`（只支援 GET，名字小寫英數字）。pack 在 `install` 裡用 `pack.web_route("summary", fn)` 掛，`fn(user)` 回可以轉 JSON 的東西（**只回這個人自己的**：用 `pack.store.of(user)`）。沒宣告的 route 掛了也打不到 |

面板範例：`packs/money/panel.html`（這個月的總額＋預算條，打 `GET /api/packs/money/summary`）。
面板是 pack 自己的 HTML，跟 `pack.py` 一樣是你決定要不要信任的程式碼：它跟 Web UI 同源，能做你在網頁上能做的事。

`.synoxpack`＝一個 pack 資料夾壓成的 zip（`pack.json` 在最上層，或在唯一的那個資料夾裡）；`synox-sdk zip`／`scripts\pack_zip.py`
會打包並算好 `integrity.sha256`（[sdk.md](sdk.md)）。裝的路有三條，都跑同一條安全管線（[security.md](security.md)「五關」）：
Web UI 設定頁上傳、點兩下 `.synoxpack`（精靈裡勾過的話，`Install-Pack.bat`）、`python -m synox install <檔> [--yes]`。
檢查 zip（沒有絕對路徑、`..`、符號連結；5 MB／解開 20 MB／300 個檔以內）→ 第 1 關宣告 → 第 2 關靜態掃描 → 給人看報告 →
按確認 → 第 3 關寫 `data/packs.lock` → 搬進 `packs/`。移除＝搬到 `packs/_removed/<name>-<版本>-<時間>`（不刪），鎖的那一筆一起拿掉
（旁邊留一份 `<那個資料夾>.lock.json`，`packs rollback` 用）。

### 升級（同名再裝一次）

已經裝了同名的 pack，再裝＝**升級**（`src/synox/packs/upgrade.py`）。一樣先跑第 1、2 關，報告多一段「改了什麼」：

- 新增／移除的 command（cli 的 `commands`、mcp 的 `tools_allow`；python pack 的指令寫在程式裡，比不出來，看檔案差異與掃描報告）
- **紅字（醒目）**：effect 變寬（`READ` → `WRITE` → `DANGER`）、新增 `WRITE`／`DANGER` 的 command、`capabilities` 新增、
  執行方式改了（`kind`、`runtime`、`cli.argv`／`python`／`cwd`／`env`、`python.module`、`mcp.url`）、`auth` 改了、
  多要密鑰環境變數、`access` 變寬、新加網頁面板、`storage` 從 `vault` 改成 `plain`
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

## pack.json v2（架構 v1 §4）

在上面之上加的欄位；**舊的 pack 照舊能讀**。有任何一個 v2 欄位（`capabilities`、`publisher`、`integrity`、`mcp`、
`commands`、`runtime`、最上層 `env`、物件形式的 `auth`）就當 v2，cli 的每個 command 一定要寫 `effect`。
從網頁或 `synox install` 裝的時候一律用嚴格版（不管 v0 或 v2，cli 的 `effect` 都要寫）。

| 欄位 | 說明 |
|---|---|
| `capabilities` | 宣告要用的能力：`network`、`subprocess`、`filesystem:own`、`filesystem:any`（含 own）、`exec`。第 2 關的掃描看到用了、卻沒宣告 → **拒裝**。沒寫＝什麼都沒宣告（舊 pack 一樣，由掃描結果決定裝不裝得了） |
| `publisher` | 發行者（給人看；沒寫會在報告裡提醒） |
| `integrity.sha256` | `{"檔名": "64 個 16 進位字"}`，打包時算（`synox-sdk zip`）。有寫就每個檔都要對得上、也不能多出沒列的檔（`pack.json` 本身不算） |
| `auth` | v0 的字串（`oauth`／`token`／`caldav`）照舊；v2 寫 `{"type": "none｜token｜oauth｜caldav｜file", "fields": [...]}`。`token`／`file` 的 `fields` 由 SYNOX 收，見下面「pack 的 secret」 |
| `kind: "mcp"`＋`mcp` | `{"url": "…", "tools_allow": ["search"], "effects": {"search": "READ"}}`。`tools_allow` 不能空，每個允許的工具都要有 effect（沒寫＝拒）。這一版只登記、不連；不能附程式檔 |
| `commands[].effect` | cli 的每個 command：`READ`／`WRITE`／`DANGER`（大小寫都收）。`commands` 也可以放最上層（等於 `cli.commands`） |
| `commands[].fields[].kind` | `text`（預設）｜`int`（整數，可有千分位逗號）｜`number`（數字）｜`bool`（是／否：`yes/no`、`true/false`、`1/0`、`是/否`…）｜`path`（值一定要在使用者自己的資料夾裡，第 4 關）｜`choice`（要寫 `choices: ["Red", "Blue"]`，大小寫不拘）。對 AI 的參數 schema 一律是字串；SYNOX 在交給程式**之前**照 kind 檢查（人打字與 AI 呼叫都會），不合回一句人話（例如「次數要是整數（例如 3）」）、不執行。交給程式的值整理過：`bool` → `true`／`false`、`int`／`number` 拿掉逗號、`choice` 換成 `choices` 裡的拼法 |
| `cli.python` | `{python}` 換成什麼：絕對路徑｜`"venv"`（`<pack 資料夾>/../.venv` 的 python）｜沒寫＝看 `runtime`，再沒有＝SYNOX 自己的 Python |
| `runtime.python`、`runtime.python_posix` | 另一種寫法（金流簿用的）：相對於 pack 資料夾（或絕對路徑），Windows 用 `python`、其他用 `python_posix`。`cli.python` 有寫就用它。**`"auto"`**＝安裝時自動建 venv（見下面「依賴與環境自動建置」；跟 `cli.python` 不能同時寫） |
| `runtime.node` | `{node}` 換成什麼：相對於 pack 資料夾（或絕對路徑）；**`"auto"`**＝系統的 node＋安裝時照 `package-lock.json` 裝套件；沒寫＝系統的 node |
| `env`（最上層）、`cli.env` | 子程序多帶的環境變數；兩個合併，`cli.env` 優先。值可以用下面的代換。名字像密鑰的（`*_TOKEN`…）一樣會被拿掉，除非列在 `requires.env` |
| `web.routes` | cli pack 的面板資料：`{"route": "command"}`；沒寫＝同名。對應的 command 要是 `READ`、沒有必填欄位 |

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
| `{python}` | 上面 `cli.python`／`runtime` 決定的直譯器（`auto`＝`data/envs/<pack>/venv` 的 python） |
| `{node}` | `runtime.node` 決定的 node（`auto` 或沒寫＝系統的 node） |
| `{pack_dir}` | pack 資料夾的絕對路徑 |
| `{data_dir}` | SYNOX 的 `data/` |
| `{user_data_dir}` | 伺服器版 `data/users/<tg_id>`（第一次用時建立）；個人版 `data/` |
| `{tg_id}` | 下令的人的 Telegram id（排程、網頁也是那個人） |

欄位不能取這幾個名字。使用者給的值只換一次（值裡寫 `{data_dir}` 不會被換）。
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
- **Node**：pack 裡要有 `package.json`＋`package-lock.json`；複製到 `data/envs/<pack>/` 後 `npm ci --ignore-scripts`
  （套件的安裝腳本一律不跑），裝進 `data/envs/<pack>/node_modules`；子程序拿到 `NODE_PATH` 指到那裡。系統沒有 node＝doctor 說缺、pack 不載入。
- pack 資料夾本身不寫任何東西（`packs.lock` 的雜湊才對得上）。
- **安裝流程**：第 2 關之後、按確認之前，報告多一段「🧱 要建環境：Python venv、裝 N 個套件：名稱 版本…」；按確認、pack 裝好之後才建
  （經 JobRunner，整個最多 10 分鐘，log 在 `data/job_logs/`）。建失敗＝pack 照樣裝好，狀態 `missing`、doctor 標「環境沒建好」並說原因
  （沒網路會直接說「連不上網路」）。重建：`python -m synox packs env rebuild <name>`。`requires.pip` 或 `package-lock.json` 改了也要重建（doctor 會說對不上）；
  經「升級」裝進來的新版會自動建／重建（見上面「升級」）。
- 建置的實作在 `src/synox/packs/envs.py`（`Builder.plan(m)`／`build(m, jobs, on_done)`；`set_factory` 可換實作）。

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
- `pack.path("x.txt")`：`data/packs/<name>/x.txt`，pack 自己的檔案放這裡。
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
- 每個 command 的填法跟內建的 python pack 一樣（2026-11-10 起）：**照位置填、`key=value` 補、選填的不追問**。
  `/moneybook 120 午餐` 直接存。`commands[].positional`＝前幾個欄位能照位置填（沒寫＝必填的個數；最後一個位置欄位吃掉剩下的字）；
  有驗證碼欄位（`fresh_code`）的 command 才走 SDK Forms（碼永遠最後問）。值以 `-` 開頭一律拒絕；loader 自己組 argv，
  因為開頭、env、cwd 要照「這一次是誰」代換。
- `commands[].stdin`：`"{answers}"` 這種樣板——那個欄位的內容走 **stdin** 給程式、不進 argv（長文字、日記正文；不會出現在
  程序清單與 log 的 argv 那一行）。程式那端從 stdin 讀。
- 程式要做的事：子指令＋`--json`，最後一行印一個 JSON 物件，結束碼 0＝成功。**回 `{"message": "…"}` 或 `{"text": "…"}` 最好**，
  會原樣給使用者；其他結構由 SYNOX 攤平（`synox/packs/render.py`：dict 一行一個 key、list 一行一項、最多 25 行）。

### `connector`

接外面的服務（Google 日曆、Notion…）。v0 **只登記**：一個群組、一個葉節點說「還沒接上」，不給 AI。
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
- 工具名＝節點路徑把 `.` 換成 `__`：`money.add` → `money__add`。參數名就是 Field 的 name。
- 正文寫「什麼時候用哪個工具、參數怎麼填、要注意什麼」，用繁體中文。
