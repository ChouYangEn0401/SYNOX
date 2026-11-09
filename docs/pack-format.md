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
| `requires.env` | | 要有的環境變數 |
| `requires.pip` | | 給人看的（v0 不會自動 pip install） |
| `web.panel` | | Web UI 工具頁的面板：pack 資料夾裡的一個 `.html`（不能用 `..`、絕對路徑）。網頁在 `<iframe sandbox="allow-scripts allow-same-origin">` 裡掛 `/packs/<name>/panel`，只給看得到這個 pack 的人 |
| `web.api` | | 面板能打的資料：`["GET /summary"]`（只支援 GET，名字小寫英數字）。pack 在 `install` 裡用 `pack.web_route("summary", fn)` 掛，`fn(user)` 回可以轉 JSON 的東西（**只回這個人自己的**：用 `pack.store.of(user)`）。沒宣告的 route 掛了也打不到 |

面板範例：`packs/money/panel.html`（這個月的總額＋預算條，打 `GET /api/packs/money/summary`）。
面板是 pack 自己的 HTML，跟 `pack.py` 一樣是你決定要不要信任的程式碼：它跟 Web UI 同源，能做你在網頁上能做的事。

`.synoxpack`＝一個 pack 資料夾壓成的 zip（`pack.json` 在最上層，或在唯一的那個資料夾裡）；`synox-sdk zip`／`scripts\pack_zip.py`
會打包並算好 `integrity.sha256`（[sdk.md](sdk.md)）。裝的路有三條，都跑同一條安全管線（[security.md](security.md)「五關」）：
Web UI 設定頁上傳、點兩下 `.synoxpack`（精靈裡勾過的話，`Install-Pack.bat`）、`python -m synox install <檔> [--yes]`。
檢查 zip（沒有絕對路徑、`..`、符號連結；5 MB／解開 20 MB／300 個檔以內）→ 第 1 關宣告 → 第 2 關靜態掃描 → 給人看報告 →
按確認 → 第 3 關寫 `data/packs.lock` → 搬進 `packs/`。移除＝搬到 `packs/_removed/<name>-<時間>`（不刪），鎖的那一筆一起拿掉。

## pack.json v2（架構 v1 §4）

在上面之上加的欄位；**舊的 pack 照舊能讀**。有任何一個 v2 欄位（`capabilities`、`publisher`、`integrity`、`mcp`、
`commands`、`runtime`、最上層 `env`、物件形式的 `auth`）就當 v2，cli 的每個 command 一定要寫 `effect`。
從網頁或 `synox install` 裝的時候一律用嚴格版（不管 v0 或 v2，cli 的 `effect` 都要寫）。

| 欄位 | 說明 |
|---|---|
| `capabilities` | 宣告要用的能力：`network`、`subprocess`、`filesystem:own`、`filesystem:any`（含 own）、`exec`。第 2 關的掃描看到用了、卻沒宣告 → **拒裝**。沒寫＝什麼都沒宣告（舊 pack 一樣，由掃描結果決定裝不裝得了） |
| `publisher` | 發行者（給人看；沒寫會在報告裡提醒） |
| `integrity.sha256` | `{"檔名": "64 個 16 進位字"}`，打包時算（`synox-sdk zip`）。有寫就每個檔都要對得上、也不能多出沒列的檔（`pack.json` 本身不算） |
| `auth` | v0 的字串（`oauth`／`token`／`caldav`）照舊；v2 寫 `{"type": "none｜token｜oauth｜caldav｜file", "fields": [...]}` |
| `kind: "mcp"`＋`mcp` | `{"url": "…", "tools_allow": ["search"], "effects": {"search": "READ"}}`。`tools_allow` 不能空，每個允許的工具都要有 effect（沒寫＝拒）。這一版只登記、不連；不能附程式檔 |
| `commands[].effect` | cli 的每個 command：`READ`／`WRITE`／`DANGER`（大小寫都收）。`commands` 也可以放最上層（等於 `cli.commands`） |
| `commands[].fields[].kind` | `text`（預設）｜`path`：值一定要在使用者自己的資料夾裡（第 4 關） |
| `cli.python` | `{python}` 換成什麼：絕對路徑｜`"venv"`（`<pack 資料夾>/../.venv` 的 python）｜沒寫＝看 `runtime`，再沒有＝SYNOX 自己的 Python |
| `runtime.python`、`runtime.python_posix` | 另一種寫法（金流簿用的）：相對於 pack 資料夾（或絕對路徑），Windows 用 `python`、其他用 `python_posix`。`cli.python` 有寫就用它 |
| `env`（最上層）、`cli.env` | 子程序多帶的環境變數；兩個合併，`cli.env` 優先。值可以用下面的代換 |
| `web.routes` | cli pack 的面板資料：`{"route": "command"}`；沒寫＝同名。對應的 command 要是 `READ`、沒有必填欄位 |

### kind=cli 的代換

`cli.argv`、每個 command 的 `argv`、`env`（最上層與 `cli.env`）、`cli.cwd` 裡的這幾個字，**每一次呼叫**照下令的人換掉：

| 寫法 | 換成 |
|---|---|
| `{python}` | 上面 `cli.python`／`runtime` 決定的直譯器 |
| `{pack_dir}` | pack 資料夾的絕對路徑 |
| `{data_dir}` | SYNOX 的 `data/` |
| `{user_data_dir}` | 伺服器版 `data/users/<tg_id>`（第一次用時建立）；個人版 `data/` |
| `{tg_id}` | 下令的人的 Telegram id（排程、網頁也是那個人） |

欄位不能取這幾個名字。使用者給的值只換一次（值裡寫 `{data_dir}` 不會被換）。
沒填的選填欄位：`--k={v}` 那一段拿掉；單獨一段的 `{v}` 連同前面緊鄰的字面 `--旗標` 一起拿掉。
樣板規則（第 2 關）：只能是字面字、單獨一段的 `{欄位}`、或 `--k={欄位}`；`["--k", "{v}"]` 這種分兩段的會被拒（要寫成 `--k={v}`）。

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
- 每個 command 是一個 SDK Forms 表單指令（行為照 SDK `service.install`：背景執行、值以 `-` 開頭一律拒絕）；
  loader 自己組 argv，因為開頭、env、cwd 要照「這一次是誰」代換。
- 程式要做的事：子指令＋`--json`，最後一行印一個 JSON 物件，結束碼 0＝成功；`{"message": "…"}` 會直接回給使用者。

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
