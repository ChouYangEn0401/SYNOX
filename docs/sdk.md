# synox_sdk：寫一個函式，就是一個工具

**十行接一個工具。** 寫 Python 函式、標上型別、加 `@tool`，同一個檔就同時是：

- SYNOX 的 `kind: cli` pack（Telegram 指令＋AI 工具＋網頁工具頁），
- 一個 MCP stdio server（給其他支援 MCP 的 AI 用戶端）。

```python
from typing import Literal
from synox_sdk import tool, serve

@tool("READ")
def greet(name: str, style: Literal["casual", "formal"] = "casual"):
    """跟某人打招呼。"""
    return f"{name}，您好。" if style == "formal" else f"嗨 {name}！"

if __name__ == "__main__":
    serve()
```

```
synox-sdk init --from tool.py --name hello --title "👋 打招呼"   產生 pack.json＋SKILL.md
synox-sdk run greet Amy style=formal                            本機試跑（不用開 SYNOX）
synox-sdk zip .                                                 → dist/hello-0.1.0.synoxpack
```

完整的小範例：[`examples/hello/`](../examples/hello/)（`tool.py`＋產生出來的 `pack.json`、`SKILL.md`）。

## 拿到 SDK

兩種都可以，內容一樣：

- **單檔**：把 [`sdk/synox_sdk.py`](../sdk/synox_sdk.py) 複製到你的工具旁邊，`from synox_sdk import tool, serve`。只用標準函式庫，零相依；
  `synox-sdk init --from` 看到你 import `synox_sdk` 而旁邊沒有這個檔，會自動放一份。
- **裝了 SYNOX**：`from synox.sdk import tool, serve`。

單檔版是從正本 `src/synox/sdk/author.py` 用 `scripts/build_synox_sdk.py` 產生的；改 SDK 改正本，再重產（測試會比對兩份一樣）。

## @tool

```python
@tool(effect, summary="", *, default=False, ai=True, confirm=False)
```

| 參數 | 說明 |
|---|---|
| `effect` | **一定要寫**：`"READ"`（只看）、`"WRITE"`（改東西）、`"DANGER"`（刪除、付錢…，AI 呼叫一律先送確認卡給人按）。沒寫 `init` 拒絕產生 |
| `summary` | 一句話說明；沒寫就用 docstring 第一段 |
| `default` | `True`＝打 `/<群組>` 就是這個指令（最多一個） |
| `ai` | `False`＝不給 AI 當工具（也不在 MCP 列出） |
| `confirm` | `True`＝AI 要呼叫時先送確認卡給人按（effect 照寫的算）；`DANGER` 本來就會 |

**參數就是欄位**，型別註記決定格式（SYNOX 在叫你的程式**之前**就照這個檢查，不合回一句人話、不執行）：

| 型別註記 | 欄位 kind | 你拿到的 |
|---|---|---|
| `str`（或沒寫） | `text` | 字串 |
| `int` | `int`（可以有千分位逗號） | `int` |
| `float` | `number` | `float` |
| `bool` | `bool`（是／否、yes／no、true／false…） | `bool` |
| `Path` | `path`（一定要在使用者自己的資料夾裡） | `Path` |
| `Literal["a", "b"]` | `choice`（大小寫不拘） | 你寫的那個拼法 |

- 有預設值、或 `Optional[...]`＝選填；其他是必填。`*args`、`**kwargs`、`dict`、`list` 不支援。
- 欄位說明（`ask`）：docstring 的 `Args:` 段落（`name: 說明`），或 `Annotated[str, "說明"]`；都沒有就是參數名。
- 參數名用小寫英數字、`_`；`python`、`node`、`pack_dir`、`data_dir`、`user_data_dir`、`tg_id`、`json`、`mcp`、`help` 保留。

**回什麼：**

| 函式做的事 | 印出來的信封 | 結束碼 |
|---|---|---|
| `return "記了 120 元"` | `{"ok": true, "message": "記了 120 元"}` | 0 |
| `return {"count": 3}`（dict、list、數字） | `{"ok": true, "data": {"count": 3}}` | 0 |
| `return Ok("共 3 筆", {"count": 3})` | `{"ok": true, "message": "共 3 筆", "data": {...}}` | 0 |
| `raise ToolError("not_found", "找不到這筆")` | `{"ok": false, "error": "找不到這筆", "code": "not_found"}` | 1 |
| `raise Confirm("要刪 3 筆")`（或 return） | `{"ok": true, "needs_confirm": true, "summary": "要刪 3 筆", "confirm_token": "…"}` | 0 |
| 其他例外 | `{"ok": false, "code": "internal", "error": "RuntimeError: …"}`（traceback 印到 stderr） | 1 |

SYNOX 把 `message` 直接回給使用者；沒有就把 `data` 攤平成幾行。`print()` 的 log 沒關係：SYNOX 只看**最後一行**。

## 確認來回：看了資料才知道危險

有些事要先看資料才知道要不要問人（「要刪 3 筆」）。寫法：

```python
from synox_sdk import Confirm, confirmed, tool

@tool("WRITE")
def purge(days: int):
    """刪掉 days 天前的紀錄。"""
    rows = old_rows(days)
    key = digest(rows)                       # 選用：把「看到的那份資料」綁進確認
    if not confirmed(key):
        raise Confirm(f"要刪 {len(rows)} 筆", token=key)
    delete(rows)
    return f"刪了 {len(rows)} 筆"
```

1. 第一次呼叫：工具回 needs_confirm → SYNOX **不顯示結果**，送核准卡給下令的那個人（`⚠️ 要你確認才會做：/demo_purge days=7`，下面是你的 `summary`，[✅ 執行] [❌ 取消]）。
   人自己打的指令、AI 呼叫的都一樣；AI 呼叫時這一輪就停在這裡（卡直接給人，不經 AI）。
2. 按 ✅：SYNOX 驗過一次性的確認憑證（綁 pack／指令／參數雜湊／使用者、跟卡片同樣幾分鐘過期、用一次就沒了），
   用**同一組參數、同一個 argv** 重跑一次，這一次子程序的環境有 `SYNOX_CONFIRMED=1`、`SYNOX_CONFIRM_TOKEN=<你給的 token>`，
   `confirmed()` 回 True、`context().confirmed`／`context().confirm_token` 也看得到。
3. 按 ❌、過期、參數對不上：不執行，回一句話。確認過的重跑又回 needs_confirm：SYNOX 不再出卡，回「工具又要求確認」。

**為什麼不能偽造：** 「已確認」只來自 SYNOX 驗過憑證之後明寫的環境變數；其他每一次 SYNOX 都明寫 `SYNOX_CONFIRMED=0`，
蓋過 pack.json 的 `cli.env` 和 SYNOX 自己的環境。重跑的 argv 跟第一次一樣，沒有 AI 能塞的 `--yes`。
`token` 只收英數字與 `. _ : -`（128 字內），其他的當作沒給；沒給＝隨機一個（那就用 `confirmed()` 不帶參數）。

**跟 `confirm=True` 的差別：** `@tool(confirm=True)`（pack.json `commands[].confirm`）是 AI 呼叫**之前**先送卡、不看資料；
`Confirm` 是工具執行**中**看了資料才問，人打字也會問。兩個可以同時用：AI 呼叫會先出「AI 想執行」的卡，按了之後工具再出自己的卡。

本機試：`synox-sdk run purge 7` 印出 SYNOX 會出的卡；`synox-sdk run purge 7 --confirmed` 當作按了 ✅（同一組參數帶 `SYNOX_CONFIRMED=1` 再跑）。

## serve()：同一組函式，兩種殼

```
python tool.py greet --name=Amy --style=formal --json    → {"ok": true, "message": "Amy，您好。"}
python tool.py greet Amy                                 → Amy，您好。（沒有 --json：給人看的字）
python tool.py --help                                    → 列出每個指令與參數
python tool.py --mcp                                     → MCP stdio server
```

- **命令列（SYNOX 用這條）**：`<指令> --欄位=值 … --json`，也收 `--欄位 值`、bool 的 `--旗標`、照順序的位置參數。
  `init --from` 產生的 argv 樣板一律是 `["指令", "--欄位={欄位}", …]`：沒填的選填欄位整段拿掉，函式就用自己的預設值。
- **MCP（`--mcp`）**：JSON-RPC 2.0、一行一個訊息（stdin 進、stdout 出）。只做 `initialize`、`ping`、`tools/list`、`tools/call`。
  `inputSchema` 由型別註記產生（`integer`／`number`／`boolean`／`string`／`enum`，必填列在 `required`）。
  工具裡 `print()` 的字會改送到 stderr，不會弄壞 JSON-RPC。`ai=False` 的工具不列出、叫不到。
  **effect 不由工具自述**：MCP 的回應裡沒有「這個工具安不安全」的標記；要在 SYNOX 裡用 MCP 工具，危險程度由裝的那一方在
  pack.json 的 `mcp.effects` 宣告（見 [pack-format.md](pack-format.md)）。
  **Confirm 在 MCP**：`tools/call` 的 result 是 `isError: false`、`content` 一句「還沒做：要使用者確認才會做：…」，
  另附 `structuredContent: {"needs_confirm": true, "summary": "…", "confirm_token": "…"}`。用戶端讓**人**確認之後，
  用同一組 `arguments` 再叫一次，並帶 `params._meta["synox/confirm_token"]`＝那個 token，這一次 `confirmed()` 才是 True。
  MCP 模式**不看** `SYNOX_CONFIRMED` 環境變數（server 長駐，環境變數不是「這一次」）。AI 只決定 `arguments`、碰不到 `_meta`；
  一般的 MCP 用戶端不會帶 `_meta`，所以 Confirm 的工具在那裡只會停在「還沒做」（安全的預設）。
- **在 SYNOX 裡用 `--mcp`（P4a）**：pack.json 寫 `"kind": "mcp"`、`"capabilities": ["subprocess"]`、
  `"mcp": {"transport": "stdio", "argv": ["{python}", "./tool.py", "--mcp"], "tools_allow": [...], "effects": {...}}`
  （把 `synox_sdk.py` 放在 tool.py 旁邊）。SYNOX 每個使用者開一個長駐的 server（第一次呼叫才開、閒置 10 分鐘收），
  所以 `context()` 的 `tg_id`／`user_data_dir`、`secret()` 在 MCP 模式一樣是那個人的（程序啟動時的環境變數）。
  `Confirm` 的確認來回 SYNOX 會帶 `_meta` 完成。細節見 [pack-format.md](pack-format.md)「`mcp`（stdio）」。
  跟 kind=cli 比：cli 每次呼叫開一次程序（簡單、互不影響）；mcp 長駐（啟動慢的工具、要保持連線的工具比較快），但你的程式要能連續處理很多次呼叫。

## secret() 與 context()

```python
from synox_sdk import secret, context

key = secret("api_key")          # 使用者在 SYNOX 工具頁「🔌 連接」填的；沒填回 None。不要印出來、不要放進回覆
ctx = context()                  # 這一次是誰
ctx.user_data_dir                # 這個人的資料夾（伺服器版每人一個）；你的檔放 <user_data_dir>/<pack_name>/
ctx.tg_id, ctx.mode              # 下令的人的 Telegram id（字串）、personal｜server
ctx.pack_dir, ctx.pack_name      # pack 資料夾、pack 名
ctx.confirmed, ctx.confirm_token # 是不是人按過 ✅ 的重跑、當時 Confirm 給的 token（見「確認來回」）
```

`secret` 要在 pack.json 宣告（使用者填、SYNOX 存進保管箱、叫你的工具時放進那個環境變數，**不會放進 argv**）：

```json
"auth": {"type": "token", "fields": [{"name": "api_key", "label": "Weather API key", "secret": true, "env": "WEATHER_API_KEY"}]}
```

`secret("api_key")` 和 `secret("WEATHER_API_KEY")` 都可以。SYNOX 叫工具時放這幾個環境變數：
`SYNOX_USER_DATA_DIR`、`SYNOX_TG_ID`、`SYNOX_MODE`、`SYNOX_PACK_DIR`、`SYNOX_PACK_NAME`、`SYNOX_SECRET_ENV`（「欄位名=環境變數名」，只有名字）、
`SYNOX_CONFIRMED`（`1`＝按過 ✅ 的重跑，其他一律 `0`）、`SYNOX_CONFIRM_TOKEN`。
不是從 SYNOX 叫的（自己在終端機跑）就都是空的——用 `synox-sdk run` 試跑會模擬。

## synox-sdk 指令

```
synox-sdk init --from tool.py --name x --title "…" [資料夾]   從 @tool 函式產生 pack.json＋SKILL.md（資料夾預設＝tool.py 旁邊）
synox-sdk run <指令> [參數…] [--pack 資料夾] [--data 資料夾]   本機試跑：跟在 Telegram 打的一樣（照位置填、key=value）
synox-sdk check <資料夾>                                       SYNOX 安裝時的宣告檢查（第 1 關）＋靜態掃描（第 2 關）
synox-sdk zip <資料夾>                                         → dist/<name>-<version>.synoxpack（算好 integrity.sha256）
synox-sdk init <資料夾> --kind cli|python --name x             不用 @tool 的範本（任何語言的命令列工具、python pack）
```

（還沒有 `synox-sdk` 指令時：`python -m synox.sdk …`。）

**init --from** 會：

- import 你的 tool.py（不跑 `if __name__ == "__main__"` 那段），找出每個 `@tool` 函式；有任何一個不合（沒寫 effect、不支援的型別…）就全部列出、**什麼都不寫**。
- 寫 `pack.json`：`kind: cli`、`cli.argv: ["{python}", "./tool.py"]`、`cli.commands`（effect、summary、argv、fields）、
  `requires.synox`。`capabilities` 先空著——掃描看到你用了網路、子程序、讀寫檔案時會提示你補上（沒補會拒裝）。`publisher` 也記得填。
- 寫 `SKILL.md` 骨架（給 AI 看：什麼時候用哪個指令）；已經有就不蓋。
- 已經有 pack.json：**只重產 `cli.commands`**，其他欄位照舊；你在指令上手動加的 `stdin`、`background`、`positional`、`timeout` 會留著。

**run** 照 SYNOX 的路走一次：欄位格式檢查 → 第 4 關（值以 `-` 開頭、換行、像密鑰的檔名、`path` 不在使用者資料夾裡、把 secret 當參數，都擋）
→ `{python}`／`{pack_dir}`／`{user_data_dir}`… 代換 → 子程序（環境變數照 SYNOX 拿掉像密鑰的、只留宣告的）→ 印出 SYNOX 會回什麼。
secret 用你在終端機設好的環境變數（例如 `set WEATHER_API_KEY=…`）。`--typed`＝當作人自己打字（不跑第 4 關）。
`--confirmed`＝工具回 needs_confirm 時當作按了 ✅（同一組參數帶 `SYNOX_CONFIRMED=1` 再跑一次）。
結束碼：0＝工具回 ok、1＝工具回失敗、2＝SYNOX 不會讓它執行。

## 不用 Python 也可以

SDK 只是幫你產生 pack.json、印信封。SYNOX 跟工具的接口只有 CLI：工具可以是 exe、Node、Go……
只要「子指令＋`--json`，最後一行印一個 JSON 物件，結束碼 0＝成功」。自己寫 pack.json：

```json
{
  "name": "weather", "title": "🌤 天氣", "summary": "看今天的天氣", "version": "0.1.0", "kind": "cli",
  "skill": "SKILL.md", "capabilities": [], "publisher": "你的名字",
  "cli": {"argv": ["{pack_dir}/weather.exe"], "json_flag": "--json", "timeout": 30,
          "commands": [{"name": "today", "effect": "READ", "default": true, "summary": "今天天氣",
                        "argv": ["today", "--city={city}"],
                        "fields": [{"name": "city", "ask": "哪個城市", "default": "台北"}]}]}
}
```

規則（安裝時第 2 關會檢查；細節見 [pack-format.md](pack-format.md)）：

- argv 樣板只能有字面字、**單獨一段**的 `{欄位}`、或 `--旗標={欄位}`（一段）。`["--city", "{city}"]` 會被拒。
- 每個 command 一定要寫 `effect`。可選：`"ai": false`（不給 AI）、`"confirm": true`（AI 呼叫前先送確認卡）。
- 欄位 `"kind"`：`int`、`number`、`bool`、`choice`（配 `"choices"`）、`path`、`text`（預設）。`bool` 一律傳 `true`／`false`。
- 系統代換：`{python}`、`{node}`、`{pack_dir}`、`{data_dir}`、`{user_data_dir}`、`{tg_id}`。
- 機器本身的環境變數寫進 `"requires": {"env": [...]}`：SYNOX 叫工具時拿掉所有像密鑰的環境變數，只放行 `requires.env` 與 `auth.fields[].env`。
- 要第三方套件：`"runtime": {"python": "auto"}`＋`"requires": {"pip": ["名字==版本", …]}`（安裝時自動建 venv）。
- 很久的工作標 `"background": true`；一般指令要在 `timeout` 內做完（AI 會等結果）。
- 有網頁面板：`"web": {"panel": "panel.html", "api": ["GET /summary"]}`，`GET /summary` 由同名、`READ`、沒有必填欄位的 command 回答。

## kind=python 的 pack：每個人的檔案

`init --kind python` 的範本在 SYNOX 程序裡跑，拿到 `pack`。每個人自己的資料：

- JSON 資料：`pack.store.of(user)`（伺服器版每人一份）。
- 檔案：`pack.path_of(user, "x.txt")` → 伺服器版 `data/users/<id>/<pack>/files/x.txt`、個人版 `data/<pack>/files/x.txt`
  （資料夾先建好；絕對路徑、`..` 跑出去丟 `PackPathError`）。
- `pack.path("x.txt")`（`data/packs/<pack>/`）是**全部人共用**的：`"data": "user"` 的 pack 用它，`synox-sdk check`（第 2 關）會拒、
  伺服器版呼叫也會丟錯——改用 `path_of`。

## 給別人裝

把 `.synoxpack` 給對方。對方在 SYNOX 的網頁設定頁上傳，或點兩下檔案：SYNOX 跑宣告檢查與靜態掃描、把報告給他看，
他按「確認安裝」才裝，並把每個檔的雜湊寫進 `data/packs.lock`；之後檔案被改過就不會載入。細節：[security.md](security.md) 的「五關」。
安裝報告上對方選信任：伺服器版選 `third-party`（預設）的 kind=python pack 只有擁有者看得到（沒有沙盒，PERM-8）；
要給成員用，對方得選 `core`，或者把 pack 寫成 kind=cli（之後有沙盒可以包）。

**附了執行檔或外部相依＝T2**（[pack-format.md](pack-format.md)「信任層級」）：pack 裡有 `.exe`／`.dll`／`.bat`／`.sh`／`.so`／`.pyc`、
`node_modules/`、檔頭是執行檔的檔，或 `cli.argv` 叫 `npx`／`git` 這類 pack 外的程式，或 `runtime` 寫 `auto` 會裝套件。
這種 pack：`capabilities` 要宣告 `exec`（資料夾裡有掃不到內容的檔時）、`pack.json` **一定要寫 `publisher`**，
對方安裝時要一字不差地輸入你的 publisher（`--trust-publisher "<publisher>"` 或網頁勾選＋輸入）。之後換 publisher、
新增 exec、多附執行檔，對方升級時都會看到紅字、要重新輸入。伺服器版的 T2 pack 沒有真沙盒＝只有擁有者看得到。
能用純 `.py` 寫完就別附執行檔：T1 的 pack 對方看得到你做什麼，T2 只能「信你」。`synox-sdk check` 會照樣列出掃不到內容的檔。

## 還沒做的

- publisher 的簽章驗證（ed25519）：現在的 publisher 只是 pack.json 裡的一個字串，對方「明確輸入」它，但證明不了檔案出自你。

- SYNOX 端連 MCP server：P4a 做了 stdio；HTTP（遠端 MCP、OAuth）、巢狀物件／陣列參數（schema 模式）、
  全部人共用一個 server 程序（`SharedScope`，只有介面）還沒做。
- 確認憑證放在記憶體：SYNOX 重開之後舊的卡按不動（要重新下指令）。
- `synox-sdk` 這個指令要 `pip install -e .` 才會出現；`python -m synox.sdk` 一樣能用。
