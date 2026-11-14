# 把你的工具接進 SYNOX（給工具作者）

這份是給**寫工具的人**看的總覽：不用讀 SYNOX 的程式碼，照這份就能把一個工具接進來、打包、給別人裝。
細節（每個欄位的完整規則）在 [pack-format.md](pack-format.md)；Python SDK 的用法在 [sdk.md](sdk.md)；
安全模型（裝的人那邊看到什麼、SYNOX 擋什麼、不擋什麼）在 [security.md](security.md)。

**授權**：工具 SDK（`sdk/`、`src/synox/sdk/`）與 `examples/` 是 Apache-2.0。你用 SDK 寫的工具，授權由你自己決定
（閉源、商用都可以），見 [LICENSING.md](../LICENSING.md)。

- [一個工具＝一個 pack](#一個工具一個-pack)
- [三條接入路怎麼選](#三條接入路怎麼選)
- [十行入門](#十行入門)
- [信任層級](#信任層級)
- [權限欄位](#權限欄位)
- [網頁工具頁（群組、分頁、表單）](#網頁工具頁群組分頁表單)
- [secret 與連接表單](#secret-與連接表單)
- [確認來回](#確認來回)
- [環境建置](#環境建置)
- [升級與版本](#升級與版本)
- [測試方法](#測試方法)
- [安全清單（作者自檢表）](#安全清單作者自檢表)
- [範例](#範例)

## 一個工具＝一個 pack

pack 是一個資料夾，壓成 zip 就是 `.synoxpack`：

```
<你的資料夾>/
  pack.json     宣告：叫什麼、怎麼執行、有哪些指令、每個指令危不危險、要什麼權限
  SKILL.md      給 AI 看：什麼時候用哪個指令、參數怎麼填
  README.md     給人看
  tool.py …     你的程式（遠端 MCP 沒有這個）
```

裝進 SYNOX 之後，每個指令同時是：

- 一個 Telegram 指令（`/<群組>_<指令>`，主要的那個就是 `/<群組>`），
- 一個 AI 工具（使用者講人話，AI 替他叫），
- 網頁介面「工具」頁裡的一張指令卡（整個 pack 是一個分頁，見下面「網頁工具頁」）。

使用者裝你的 pack 時，SYNOX 先跑**宣告檢查（第 1 關）**與**靜態掃描（第 2 關）**，把報告給他看，他按確認才裝，
並把每個檔的雜湊鎖起來（之後檔案被改過就不載入）。之後每次 AI 叫你的工具，SYNOX 先驗參數、
危險的先送確認卡給人按。整條管線見 [security.md](security.md)「五關」。

## 三條接入路怎麼選

| | **cli 子程序** | **MCP stdio（長駐）** | **遠端 MCP** |
|---|---|---|---|
| pack.json | `"kind": "cli"` | `"kind": "mcp"`＋`"mcp": {"transport": "stdio"}` | `"kind": "mcp"`＋`"mcp": {"transport": "http"}` |
| 適合 | 大部分的工具；你有一支命令列程式或幾個函式 | 你已經有 MCP 伺服器；或啟動很慢、要保持連線的工具 | 對方服務已經架好 https 的 MCP 伺服器 |
| 程式在哪跑 | 這台；**每次呼叫開一次程序**（簡單、互不影響） | 這台；**每個使用者一個長駐程序**（第一次呼叫才開、閒置 10 分鐘收） | 對方的伺服器；這台不跑任何程式 |
| 要寫程式嗎 | 要（任何語言） | 要（任何語言） | 不用，只寫 pack.json |
| 指令從哪來 | pack.json 的 `cli.commands` | 伺服器的 `tools/list`，只留 `mcp.tools_allow` 列的 | 同左 |
| 參數格式 | `fields[].kind` | 工具的 `inputSchema` | 同左 |
| 危險程度（effect） | 每個 command 的 `effect` | `mcp.effects`（伺服器自述的不算） | 同左 |
| 一定要的 `capabilities` | 看程式做什麼 | `subprocess` | `network`（不能有 `subprocess`、`exec`、`filesystem:any`） |
| 信任層級（通常） | T1（只跑 `.py`）／T2（附執行檔、別的語言的原始碼、叫 `{node}` 這類直譯器） | 同左 | T0（只有宣告） |
| 伺服器版預設誰看得到 | 看 `access` 與 `capabilities` | 管理員以上（因為 `subprocess`） | 成員以上（寫 `"access": "member"`） |
| 第三方套件 | `runtime.python`／`runtime.node` = `"auto"` | 不支援 `runtime`（見下面「環境建置」） | — |
| 本機試跑 | `synox-sdk run` | 手動餵 JSON-RPC（見 [examples/node-mcp-tool](../examples/node-mcp-tool/)） | 沒有本機試跑 |
| 範例 | [hello](../examples/hello/)、[any-language-cli](../examples/any-language-cli/) | [node-mcp-tool](../examples/node-mcp-tool/) | [mcp-remote-todoist](../examples/mcp-remote-todoist/)、[mcp-remote-notion](../examples/mcp-remote-notion/) |

**不知道選哪個就選 cli。** 用 Python 的話，同一個 `tool.py` 用 SDK 的 `serve()` 兩種都能跑（`--mcp`＝MCP stdio），之後要換很容易。

還有第四種 `kind: "python"`：在 SYNOX 程序裡面跑、拿得到整個 app，是 SYNOX 自己內建功能用的。
它沒有沙盒可以包，所以在伺服器版，第三方的 python pack **只有擁有者看得到**；給別人用的工具請寫成上面三種。

## 十行入門

```python
# tool.py
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
synox-sdk init --from tool.py --name hello --title "👋 打招呼"   產生 pack.json＋SKILL.md（旁邊放一份 synox_sdk.py）
synox-sdk run greet Amy style=formal                            本機試跑：跟在 Telegram 打 /hello_greet Amy style=formal 一樣
synox-sdk check .                                               安裝時的第 1、2 關
synox-sdk zip .                                                 → dist/hello-0.1.0.synoxpack
```

- `@tool` 的第一個參數 **effect 一定要寫**（`"READ"`、`"WRITE"`、`"DANGER"`），沒寫 `init` 拒絕產生。
- 型別註記就是欄位格式（`str`、`int`、`float`、`bool`、`Path`、`Literal[...]`），有預設值＝選填。
- 回字串＝給使用者的那句話；回 dict／list＝資料；`raise ToolError("code", "人話")`＝失敗。
- 打開 `pack.json` 補上 `publisher`（你的名字或組織），要連網、開別的程式、讀寫檔案就補 `capabilities`（`synox-sdk check` 會說缺什麼）。

SDK 只用標準函式庫、是單一檔案，也可以不用：SYNOX 跟 cli 工具的接口只是「子指令＋`--json`，最後一行印一個 JSON 物件」。
不用 SDK、任何語言都適用的協定寫在 [examples/any-language-cli/README.md](../examples/any-language-cli/README.md)。
SDK 的完整說明（`@tool` 的參數、型別對照、`serve()`、`secret()`、`context()`）在 [sdk.md](sdk.md)。

## 信任層級

SYNOX 的靜態掃描（第 2 關）**只讀得懂 `.py`**。所以它照「看得到多少」把 pack 分三層：

| 層級 | 是什麼 | 對作者 | 對裝的人 |
|---|---|---|---|
| **T0 只有宣告** | 遠端 MCP、只登記的 connector：沒有程式在這台跑 | 不能附程式檔（附了＝拒）。你只寫 pack.json | 報告逐一列出每個工具與 effect、請求與 token 會送到哪個主機。能信的只有這份宣告，對方伺服器做什麼看不到 |
| **T1 原始碼** | 會被執行的只有第 2 關掃過的 `.py`／`.pyw`：`{python}` 要跑的 pack 內檔案**一定要是 `.py`**（或含 `__main__.py` 的資料夾；`./run.txt`、`./app.pyz`、沒有副檔名的 `./run` 一律拒）；其他檔當資料 | 程式用了什麼（連網、子程序、檔案、動態執行）都會被列出 `檔名:行號`，沒宣告就拒裝 | 看得到程式裡**直接寫出來的**那些動作；掃描是提醒不是門，T1 不等於安全。按一次確認就裝 |
| **T2 二進位或外部相依** | 附了執行檔或編譯檔（`.exe .dll .bat .cmd .ps1 .sh .so .dylib .pyd .pyc .jar .wasm…`、壓縮檔 `.pyz .pyzw .zip .whl .egg`（Python 可以直接從裡面 import）、檔頭是 MZ／ELF／Mach-O 的檔、沒有副檔名但帶執行位元或 `#!` 開頭）、別的語言的原始碼（`.js .mjs .cjs .ts .tsx .jsx .rb .pl .php .lua .go .rs .java .kt .cs .psm1 .bash .zsh…`：SYNOX 讀不懂）、`node_modules/`、`cli.argv`／`mcp.argv` 叫 pack 外的程式（`{node}`、`node`、`npx`、`deno`、`bun`、`ruby`、`perl`、`php` 這類直譯器、`git`、絕對路徑、`{python} -m` 不在 pack 裡的模組）、`{python}` 指到 pack 外的 Python（`cli.python`、`"venv"`、`runtime.python` 指到外面）、argv 讓直譯器直接執行一段程式碼（`{python} -c`、`powershell -Command`、`cmd /c`、`node -e`、`bash -c`…）、或 `runtime` = `"auto"` 會裝套件 | 資料夾裡有掃不到內容的檔、argv 直接執行程式碼，就**一定要宣告 `exec`**；**一定要寫 `publisher`**。升級時換 publisher、新增 `exec`、多附執行檔，裝的人都會看到紅字 | 報告有紅字一段：會執行什麼、會裝哪些套件、外部程式解析到這台的哪裡。要**一字不差地輸入你的 publisher** 才能裝。伺服器版的 T2 pack 沒有真的沙盒（Linux 的 bwrap／systemd）就只有擁有者看得到 |

**T2 不是沙盒保證，只是讓裝的人知道他在信任誰。** `publisher` 現在只是 pack.json 裡的一個字串（還沒有簽章驗證），
它證明不了檔案出自你；「明確輸入」是讓對方停下來想一次、事後在鎖裡查得到當時信了誰。

能用純 `.py` 寫完就別附執行檔。用別的語言寫、又想讓別人放心裝，就把原始碼公開，讓對方自己編。

> 用 Node（或任何 `.py` 以外的語言）寫的工具一律是 T2：照實宣告 `exec`、寫好 `publisher`
> （[examples/node-mcp-tool](../examples/node-mcp-tool/) 就是這樣寫）。`synox-sdk check .` 會印出信任層級、掃不到內容的檔案清單，
> T2 沒寫 `publisher` 會警告並以非 0 結束（安裝時一定會被擋）。

## 權限欄位

pack.json 裡跟「誰能用、能做什麼」有關的欄位。全部都是**宣告**：SYNOX 照它決定誰看得到、要不要確認，
第 2 關再對照你的程式，用了沒宣告的就拒裝。

### `access`：誰看得到這組指令

| 值 | 意思 |
|---|---|
| `owner`（預設） | 只有安裝 SYNOX 的那個人。別人打了跟「沒有這個指令」一樣 |
| `member` | 伺服器版的成員以上（個人版＝只有擁有者） |
| `everyone` | 任何人，含伺服器版的訪客 |

### `capabilities`：你的程式要什麼能力

| 值 | 什麼時候要寫 |
|---|---|
| `network` | 連網（`urllib`、`requests`、`socket`…）；遠端 MCP 一定要 |
| `subprocess` | 開別的程式（`subprocess`、`os.system`…）；MCP stdio 一定要 |
| `filesystem:own` | 讀寫檔案（你自己的資料夾） |
| `filesystem:any` | 讀寫 pack 以外、使用者資料夾以外的檔案（含 own） |
| `exec` | 動態執行程式碼（`exec`、`eval`、`importlib`、`ctypes`、`pickle.loads`…；`sys.modules`、`x.__class__`／`__dict__`／`__globals__` 這類 dunder 屬性、`getattr` 的屬性名不是字面字、`vars()`／`globals()`、`handlers[k]()` 這種看不出呼叫什麼的寫法也算），pack 裡有掃不到內容的檔（T2），或 argv 讓直譯器直接執行程式碼（`-c`、`-e`、`-Command`、`/c`…） |

> 第 2 關攔的是直接寫出來的名字和常見的間接取用，**是提醒、不是門**：Python 太動態，掃描不保證抓得到每一種寫法。
> python pack 在 SYNOX 程序裡跑，**個人版沒有任何隔離**；伺服器版第三方的 python pack 只給擁有者。
> 不想被算成 `exec`：用 `type(x)` 代替 `x.__class__`、`getattr(x, "名字")` 寫字面字、`f = handlers[k]` 先指給變數再呼叫。
> **import 第三方套件要寫進 `requires.pip`**：不在標準函式庫、不在 pack 資料夾裡、`requires.pip` 也沒寫的模組算
> 「來源不明」＝`exec`。pip 名跟 import 名不一樣的（`PyYAML`→`yaml`、`beautifulsoup4`→`bs4`、`Pillow`→`PIL`…）有內建對照；
> 也不要 `from os import *`、`from 某套件 import eval`、改 `sys.path`、把函式名拆成字串再拼回來——這些都算 `exec`。

**宣告也決定誰看得到**：每個角色有能力上限，pack 的 `capabilities` 裝不下，那個角色就看不到整組指令（跟不存在一樣）。
預設上限：訪客 `[]`、成員 `network`＋`filesystem:own`、管理員再加 `subprocess`；**`exec`、`filesystem:any` 只有擁有者**
（設定檔也不能把它們開給任何角色）。所以寫 `access: member` 卻宣告 `subprocess`，成員還是看不到。
宣告要誠實，但能少就少：宣告越少，能用的人越多。

### `surfaces`：在哪裡能用

| 值 | 意思 |
|---|---|
| `["dm"]`（預設） | 只能私訊；在群組／頻道裡打了會回「請私訊」 |
| `["dm", "channel"]` | 也能在群組／頻道用 |

一定要有 `dm`。`channel`＋`data: user` 第 1 關就拒：每個人自己的資料不能出現在頻道裡。

### `data`：資料屬於誰

| 值 | 意思 | 規則（第 2 關） |
|---|---|---|
| `none` | 不存資料 | cli／mcp 的樣板不能用 `{user_data_dir}`、`{data_dir}` |
| `user` | 每個人自己一份（伺服器版每人一個資料夾） | 樣板不能用 `{data_dir}`（只能 `{user_data_dir}`）。檔放 `<user_data_dir>/<pack 名>/` |
| `shared` | 大家共用一份 | 伺服器版裡 `WRITE`／`DANGER` 的指令只有管理員以上能用 |

沒寫會照樣板推（用了 `{user_data_dir}`＝`user`、只用 `{data_dir}`＝`shared`、都沒有＝`none`）。**建議明寫。**

### 每個指令的 `effect`、`ai`、`confirm`

| 欄位 | 值 | 意思 |
|---|---|---|
| `effect` | `READ`｜`WRITE`｜`DANGER`（**一定要寫**） | 只看／會改東西／刪除、付錢這類。**AI 叫 `DANGER` 一律先送確認卡給人按**。MCP 的工具在 `mcp.effects` 寫，沒寫＝第 1 關拒 |
| `ai` | `true`（預設）｜`false` | `false`＝不給 AI 當工具，只有人自己打指令能用（例如放寬安全的開關） |
| `confirm` | `false`（預設）｜`true` | `true`＝AI 要叫之前先送確認卡（effect 照寫的算）。工具執行**中**看了資料才知道要不要問人，用下面的「確認來回」 |

SDK：`@tool("WRITE", ai=False, confirm=True)`；cli 的 pack.json：`{"name": "…", "effect": "WRITE", "ai": false, "confirm": true, …}`。

### 常見組合

| 工具 | 寫法 |
|---|---|
| 純計算（算小費、換單位） | `capabilities: []`、`data: "none"`、`effect: "READ"`。可以 `access: "everyone"`、`surfaces: ["dm", "channel"]` |
| 個人記事（存在自己的資料夾） | `capabilities: ["filesystem:own"]`、`data: "user"`、新增 `WRITE`、全部刪掉 `DANGER` 或用確認來回、`surfaces: ["dm"]`；`access: "member"` 成員就能用 |
| 查外部服務（天氣、待辦） | `capabilities: ["network"]`、`auth.fields` 收 API key、查詢 `READ`、新增 `WRITE`、刪除 `DANGER`；`access: "member"` |
| 團隊共用的清單 | `data: "shared"`、`surfaces: ["dm", "channel"]`（伺服器版寫入自動只給管理員） |
| 包一支現成的程式 | `capabilities: ["subprocess"]`（管理員以上）；附了執行檔再加 `exec`（只有擁有者）＋`publisher`（T2） |
| 接 MCP 伺服器 | stdio：`capabilities: ["subprocess"]`；遠端：`capabilities: ["network"]`＋`access: "member"`。每個 `tools_allow` 都寫 effect |

## 網頁工具頁（群組、分頁、表單）

網頁介面的「工具」頁是你的 pack 給人看的那一面（skill 的視覺化版本）：**左邊是群組**，選一個群組，
群組裡的每個工具（pack）是**一個分頁**；分頁裡有說明、指令清單、每個參數的輸入欄、「執行」。全部從你的宣告讀出來，**不用寫網頁**：

| 畫面上 | 從哪裡來 |
|---|---|
| 放在哪個群組 | pack.json 的 `category`（建議；沒寫＝「未分類」）。使用者按「編輯」自己排過的優先 |
| 分頁標題、說明 | `title`、`summary`；「什麼時候用」＝SKILL.md frontmatter 的 `description` |
| 標題旁的穩定度標籤 | `stage`（沒寫＝🧪 alpha）；滑鼠停在上面看意思 |
| 指令卡 | 每個 command：指令名、`summary`、effect 徽章（唯讀／會寫入／**危險：會先問你**）、`confirm`／`ai: false` 的註記 |
| 參數的輸入欄 | `fields[]`：`ask`＝欄位名稱、`required`＝必填標籤、`kind`＝輸入方式（`bool` 是／否下拉、`choice` 下拉、`int`／`number` 數字鍵盤）、`default`＝預先填好、`help`＝欄位下面的說明 |
| 執行 | 送出 `/<指令> 欄位=值 …`，走跟聊天一樣的路（權限、第 4 關、確認來回都一樣）。`DANGER` 的指令按下去先在畫面上問一次「確定要執行嗎？」 |

- 使用者可以**新增／改名／刪除群組、排序、把工具移到別的群組**。排法存在**每個人自己的**偏好（保管箱密文，
  `data/web_prefs/<id>.json.enc`），擁有者與成員各自一份；**不會寫進你的 pack 資料夾**（packs.lock 的雜湊照樣對得上）。
- `category` 只是建議：同名的放同一個群組（例如兩個 pack 都寫 `"待辦與行程"`）。名字取一般人看得懂的，一行、24 字內。
- 說明寫得好，工具頁才好用：每個 command 寫 `summary`、每個欄位寫 `ask`（不然畫面上只剩英文名字），格式提示寫進 `help`。
  `synox-sdk check` 會列出「📝 說明不齊」。
- SDK 的 `@tool`：函式參數的預設值會變成 `default`、docstring 的 `Args:` 會變成 `ask`；`category` 自己加進 pack.json。

## 工具服務：完整的網頁畫面（`/apps`、`/app_open`、`/app_close`）

工具可以在 `pack.json` 宣告 `web.app`，附一個完整的網頁畫面（寫法見 [tool-apps.md](tool-apps.md)、[pack-format.md](pack-format.md)「完整網頁畫面」）。
擁有者決定什麼時候開：

| 指令 | 誰 | 說明 |
|---|---|---|
| `/apps` | 看得到工具的人（AI 也能叫） | 每個有畫面的工具一行：開著（多久、多久沒用）／關著，後面接它的閒置設定；擁有者另外看到最近三筆紀錄 |
| `/app_open <名字>` | 擁有者、只在私訊 | 開服務（之後到 SYNOX 網頁的工具頁按「打開」）。**AI 與排程都不能開**（`interactive`、只收本人）；`/app_open <名字> remote` 轉到 `/app_remote`（手機入口） |
| `/app_close <名字｜all>` | 擁有者（AI 也能叫） | 關掉；資料都在，Telegram 照樣可以用 |

名字可以打工具名、群組名、標題（不用打 emoji）、畫面的標題，不分大小寫。

**手機入口**：`/app_remote <名字> [分鐘]`（擁有者、只在私訊、AI 與排程都不行）先問一組手機驗證器的數字，對了回一個只能用一次的連結；手機打開再打一組新的數字才進得去。只有宣告了 `web.app.remote` 而且你在工具頁打開「可以從手機用」的工具才行；危險的動作與匯出在手機上不能做。`/app_close <名字>` 一起關掉。回覆裡不會有畫面的網址：打開一律從 SYNOX 網頁的工具頁。
閒置設定（多久沒用就關、只提醒、一直開著、不開放）只能在網頁的工具頁改。

## 指令的白話說明

使用者打 `/help` 看到的是**你寫的字**：每個工具一顆按鈕 → 最常用的幾個指令與例子 → 一個指令的一句白話＋範例。
寫在 pack.json 最上層的 `help` 區塊（格式與檢查：[pack-format.md「指令的白話說明與範例」](pack-format.md#指令的白話說明與範例help-區塊)）。

寫作守則（給不會用電腦的人看）：

1. **一句話、動詞開頭、說「會發生什麼」**：「把一筆花掉的錢記下來」，不是「記一筆支出（類別是收入或轉帳類的，就照那一種記）」。
2. **一句只講一件事**。例外、預設值、進階用法放 `fields[].help` 或 SKILL.md，不放 `plain`。
3. **不用符號當語言**：不寫 `＝`、`<>`、`[]`、`key=value`、`!!`、`#`。要示範語法就寫成**範例**。
4. **不用術語**：API、token、integration、JSON、OAuth、CalDAV、.ics、參數、字串……（安裝時會提醒你）；欄位問句用名詞（「金額」「哪一天」），補充放 `help`。
5. **範例用日常的事**（午餐、看牙醫、買牛奶），第一個範例是最短能成功的那一個；範例只寫參數，指令名 SYNOX 會補。
6. **唸給不會用電腦的家人聽**，聽不懂就重寫。自動檢查只擋明顯的術語，好不好懂要人唸過才知道。
7. 可以附**建議的中文名字**（`alias_suggest`，例如「記帳」）：使用者一鍵就能把 `/money` 叫成「記帳」（[commands.md](commands.md)）。

## secret 與連接表單

要使用者的 API key、token、憑證檔時，**不要做成指令參數、也不要叫使用者在聊天裡打**。在 pack.json 宣告：

```json
"auth": {"type": "token",
         "fields": [{"name": "api_key", "label": "Weather API key", "secret": true, "env": "WEATHER_API_KEY",
                     "help": "到 <服務的網站> → 設定 → API key"}]}
```

- 使用者在網頁介面「工具」頁你那張卡的「🔌 連接」填（或在電腦上 `python -m synox connect <pack 名>`）；**Telegram 不收**（聊天紀錄留在 Telegram 的伺服器上）。
- SYNOX 存進加密的保管箱（伺服器版每人一份）；`secret: true` 的值網頁永遠不回傳（只顯示有填與最後 4 碼）。
- **cli／MCP stdio**：叫你的程式時放進 `env` 指定的環境變數，**絕不放進 argv**。SDK：`secret("api_key")`；其他語言：讀那個環境變數。
  沒寫 `env` 的欄位 cli 拿不到。
- **遠端 MCP**：送成 `Authorization: Bearer <值>`（`mcp.bearer` 指定哪個欄位）；或 `auth.type: "oauth"` 讓使用者貼回登入後的網址。
- `required`（預設 `true`）的沒填：指令回「到網頁工具頁按『連接』」，不執行。
- `kind: "file"`：上傳一個文字檔（例如 service account JSON，最多 32000 字）。
- AI 要是把某個已存的 secret 當成參數送出（被網頁裡的字騙了之類），SYNOX 執行前就擋下（不說是哪一個）。
- 其他名字像密鑰的環境變數（`*_TOKEN`、`*_API_KEY`、`*_SECRET`、`*_PASSWORD`…）SYNOX 叫你的程式時會拿掉；
  你真的要讀機器上的某個變數，寫進 `"requires": {"env": ["名字"]}`。

你的程式拿到 secret 之後做什麼，SYNOX 管不了：**不要印出來、不要放進回覆、不要寫進 log**。

## 確認來回

兩種確認，可以同時用：

| | `confirm: true`（或 `DANGER`） | 工具回 `needs_confirm` |
|---|---|---|
| 什麼時候問 | AI 叫之前，不看資料 | 工具執行**中**看了資料才知道（「要刪 3 筆」） |
| 誰會被問 | AI 呼叫時 | 人自己打指令、AI 呼叫都會 |
| 誰決定 | pack.json | 你的程式 |

工具回 `needs_confirm` 的流程：

1. 第一次叫：你的工具回「要確認」（SDK：`raise Confirm("要刪 3 筆", token=…)`；cli 其他語言：最後一行印
   `{"ok": true, "needs_confirm": true, "summary": "要刪 3 筆", "confirm_token": "…"}`、結束碼 0；
   MCP：`tools/call` 的 result 帶 `structuredContent: {"needs_confirm": true, "summary": "…", "confirm_token": "…"}`、`isError: false`）。
2. SYNOX **不顯示結果**，送確認卡給下指令的那個人（AI 呼叫時這一輪就停在這裡）。
3. 人按 ✅：SYNOX 驗過一次性的憑證（綁這個 pack、這個指令、這組參數、這個人，幾分鐘過期，只能用一次），
   用**同一組參數**再叫你一次：cli 的環境變數 `SYNOX_CONFIRMED=1`、`SYNOX_CONFIRM_TOKEN`＝你給的 token；
   MCP 帶 `params._meta["synox/confirm_token"]`。SDK 的 `confirmed()` 這時回 True。
4. 按 ❌、過期、參數對不上：不會叫你第二次。

- `confirm_token` 只收英數字與 `. _ : -`、128 字內。建議放「你看到的那份資料」的雜湊，重跑時比對，資料變了就不做。
- 「已確認」只來自 SYNOX 驗過憑證之後明寫的值：其他每一次 SYNOX 都明寫 `SYNOX_CONFIRMED=0`（蓋過 pack.json 的 `cli.env`），
  AI 也碰不到 MCP 的 `_meta`。所以**不要**另外做 `--yes` 這種旗標，AI 會去帶它。
- 確認過的重跑又回 `needs_confirm`：SYNOX 不再出卡，回「工具又要求確認」。
- 本機試：`synox-sdk run <指令> …` 印出 SYNOX 會出的卡；加 `--confirmed`＝當作按了 ✅。

## 環境建置

**最好不要有第三方套件**：只用標準函式庫的工具裝起來最快、是 T1、裝的人最放心。真的需要時（只給 kind=cli）：

```json
"runtime": {"python": "auto", "python_posix": "auto"},
"requires": {"pip": ["requests==2.32.3", "idna==3.7", "charset-normalizer==3.3.2", "urllib3==2.2.2", "certifi==2024.7.4"]}
```

- 使用者按確認安裝之後，SYNOX 在它自己的資料夾（不是你的 pack 資料夾）建 venv，跑
  `pip install --no-deps --only-binary=:all:`。
- `requires.pip` **每一項都要是 `名字==版本`**：`>=`、`~=`、萬用字元、extras、網址、`-r`、`--index-url` 第 1 關都拒。
  建議再加雜湊：`"requests==2.32.3 --hash=sha256:…"`（`pip hash <wheel 檔>` 或 PyPI 的檔案頁拿；每一項都要寫）。有寫就
  `--require-hashes`；沒寫的話裝的人會在報告上看到紅字「版本釘選不等於來源可信」。來源一律 PyPI，pack 不能指定 index。
- `--no-deps`：**相依的套件也要自己全部列出來、釘死版本**（上面的例子是示意，版本請自己確認）。
- 只裝現成的 wheel：不在使用者電腦上跑套件的 setup.py。
- Node：`"runtime": {"node": "auto"}`＋pack 裡放 `package.json` 與 `package-lock.json`；SYNOX 跑 `npm ci --ignore-scripts`（套件的安裝腳本一律不跑）。
- `runtime` = `"auto"` 會裝套件＝**T2**：要寫 `publisher`，裝的人要輸入它；報告列出每個套件與版本。
- 建失敗：pack 照樣裝好但不能用，`python -m synox doctor` 說原因；修好後 `python -m synox packs env rebuild <pack 名>`。
- **不支援**：kind=mcp 不能寫 `runtime`（第 1 關拒）；MCP stdio 的 `{node}`／`{python}` 是這台系統的 node／SYNOX 自己的 Python。
- 沒寫 `runtime`：`{python}`＝SYNOX 自己的 Python（只保證標準函式庫）、`{node}`＝系統的 node（這台沒裝就叫不起來）。

## 升級與版本

- 同名的 pack 再裝一次＝**升級**。`version` 要是 semver（`1.2.3`、`1.2.3-beta.1`），而且**要比裝著的大**；
  一樣或比較小會被拒，除非裝的人明確選「降級／重裝」。
- 升級報告會列「改了什麼」，**權限變大的用紅字**：effect 變寬、新增 `WRITE`／`DANGER` 指令、新增 `capabilities`、
  執行方式改了（`kind`、`runtime`、argv、`mcp.url`…）、`auth` 改了、多要密鑰、`access` 變寬、新加網頁面板、
  `surfaces` 多了 `channel`、`data` 變寬、換了 `publisher`。T2 的 pack 換 publisher、新增 `exec`、多了要執行的東西，要重新輸入發行者。
  **想讓使用者順順地升級，就別順手放大權限。**
- 舊版不刪，搬到旁邊；使用者可以 `python -m synox packs rollback <pack 名>` 退回。
- **資料不在 pack 資料夾裡**，升級、退回都不會動到資料。資料格式要不要轉換是你的事：在資料裡存一個 `schema` 版本號，
  新版讀到舊格式自己轉；退回的舊版要看得懂新版寫的資料（做不到就在 README 寫清楚「不能退回」）。
- `requires.synox`（例如 `">=0.2"`）：這台的 SYNOX 版本不合就不裝、不載入，並說要哪一版。
- **`requires.sdk`（一定要寫）**：你照哪一版 SDK 介面寫的，例如 `">=0.2,<0.3"`（0.x 寫到下一個 MINOR）。SDK 的版本是
  `synox_sdk.SDK_VERSION`，跟 SYNOX 本體的版本分開；不合一樣不裝、不載入（[sdk.md](sdk.md)「SDK 版本」）。`synox-sdk init` 會自動寫。
- **`stage`（穩定度，建議寫）**：`test`｜`alpha`｜`beta`｜`stable`，沒寫＝`alpha`。裝的人在 `/help`、網頁工具頁、安裝報告、
  `doctor` 都會看到「🔧 test／🧪 alpha／🚧 beta／⭐ stable」這種標籤；寫錯（例如 `"Beta"`、`"gold"`）安裝時拒裝。
  它跟 `version` 是兩回事：`version` 說「哪一版」，`stage` 說「這一版多可靠」（[pack-format.md](pack-format.md) 的 `stage` 那一列）。

## 放進工具庫（SYNOX_Libs）

SYNOX 出廠不帶工具；官方工具都放在另一個專案 **SYNOX 工具庫（SYNOX_Libs）**：一個工具一個資料夾 `packs/<name>/`，
`scripts/build.py` 打包成 `.synoxpack` 並寫一份目錄 `index.json`（名稱、版本、說明、SDK 範圍、建議組合、雜湊），使用者挑來裝。
打包前會擋：沒寫 `requires.sdk`、範圍不含拿來打包的那份 SYNOX 的 SDK、附的 `synox_sdk.py` 版本不在範圍內，以及安裝時的第 1、2 關。
規則與流程見工具庫的 README 與 `docs/adr/0001-tool-library-and-sdk-dependency.md`。自己用的工具不一定要進工具庫，`.synoxpack` 直接給人也行。

## 測試方法

```
synox-sdk run <指令> [參數…] [--pack 資料夾] [--data 資料夾]   本機試跑一個 cli 指令
synox-sdk check <資料夾>                                       第 1 關（宣告）＋第 2 關（靜態掃描）
synox-sdk zip <資料夾>                                         → dist/<name>-<version>.synoxpack（算好每個檔的雜湊）
synox-sdk init <資料夾> --kind cli --name x                    不用 @tool 的範本
```

還沒有 `synox-sdk` 這個指令時（要 `pip install -e .` 才有），用 `python -m synox.sdk …`，一樣。

- **`run`**（只跑 kind=cli）：照 SYNOX 的路走一次：照位置填／`key=value` → 欄位格式檢查 → 執行前的參數檢查（值以 `-` 開頭、換行、
  像密鑰的檔名、`path` 不在使用者資料夾裡、把 secret 當參數…都擋）→ 代換 → 開子程序（環境變數照 SYNOX 拿掉像密鑰的）→ 印出 SYNOX 會回什麼。
  `--typed`＝當作人自己打字、`--confirmed`＝工具要確認時當作按了 ✅、`--data`＝當作使用者資料夾的地方（預設暫存資料夾）。
  secret 用你在終端機設好的環境變數。結束碼：0＝工具回 ok、1＝工具回失敗、2＝SYNOX 不會讓它執行。
- **`check`**：裝的人那邊會跑的兩關。沒過會列出原因與 `檔名:行號`，結束碼 2。⚠️ 開頭的（例如讀環境變數）只是列給人看、不擋。
- **`zip`**：先跑 `check`，沒過不打包。不打包 `__pycache__`。
- **你自己的邏輯**：用你習慣的測試框架直接測函式。SDK 的 `@tool` 函式就是普通函式，可以直接叫。
- **MCP stdio**：`synox-sdk run` 不跑 MCP。直接執行你的伺服器，一行貼一個 JSON-RPC（`initialize`、`tools/list`、`tools/call`），
  看回應（[examples/node-mcp-tool/README.md](../examples/node-mcp-tool/README.md) 有三行範例）。Python SDK 的 `python tool.py --mcp` 也一樣。
- **遠端 MCP**：只能 `check`；連上一次之後 `python -m synox doctor` 會列出 `tools_allow` 裡伺服器沒有的名字。

## 安全清單（作者自檢表）

送出去之前對一次。左邊是會被**擋下**的寫法（不裝、不載入或不執行），右邊是為什麼。

### 安裝時（打包檔與第 1 關：宣告）

| 會被擋 | 為什麼 |
|---|---|
| cli 的 command 沒寫 `effect`；MCP 的 `tools_allow` 有工具沒寫 effect；`tools_allow` 是空的 | 沒有 effect，SYNOX 不知道 AI 叫它要不要先問人 |
| `capabilities` 寫了 `network`、`subprocess`、`filesystem:own`、`filesystem:any`、`exec` 以外的字 | 宣告不存在的能力沒有意義，多半是寫錯 |
| `surfaces` 有 `channel` 而 `data` 是 `user` | 每個人自己的資料不能出現在頻道 |
| 欄位取名 `python`、`node`、`pack_dir`、`data_dir`、`user_data_dir`、`tg_id` | 這些是 SYNOX 的代換名，會被冒用 |
| `requires.pip` 有沒釘死版本的（`>=`、`~=`、網址…）；`runtime.node: "auto"` 卻沒有 `package-lock.json`；kind=mcp 寫了 `runtime` | 裝的套件要可以重現、可以在報告裡列清楚 |
| `cli.python`／`runtime.python` 的檔名不是 Python 直譯器（`python*`／`pypy*`），或有 `..`（只收 `../.venv/…`） | `{python}` 被當成「SYNOX 的 Python」看待；要叫別的程式就寫在 argv 第一段 |
| `env`／`cli.env`／`mcp.env` 寫了 `PYTHON*`（`PYTHONIOENCODING`、`PYTHONUTF8`、`PYTHONUNBUFFERED` 除外；`PYTHONPATH` 只收 `{pack_dir}` 或 `{pack_dir}/子資料夾`）、`NODE_OPTIONS`、`NODE_PATH`、`PATH`、`PATHEXT`、`COMSPEC`、`SYSTEMROOT`、`LD_*`、`DYLD_*`、`PIP_*`、`npm_config_*`… | 這些會讓 Python／Node／系統在跑你的程式之前，先載入 pack 外、沒鎖、沒掃過的程式 |
| pack.json 任何路徑（`cli.python`、`runtime`、argv、env 的值、`cwd`、`skill`…）用了網路／裝置路徑（`\\主機\分享`、`//主機/…`、`\\?\`、`\\.\`）；`skill` 不在 pack 裡、`python.module` 不是單純的模組名字 | Windows 光是檢查這種路徑就會連到那台主機（在你按確認之前）；pack 外的檔沒鎖也沒掃 |
| MCP stdio 沒宣告 `subprocess` | 長駐子程序就是開別的程式 |
| 遠端 MCP：網址是 `http://`、帶 `帳號:密碼@`、`#`、`{樣板}`；宣告 `subprocess`／`exec`／`filesystem:any`；寫了 `argv`、`env`、`headers` | token 只能走加密連線、只送到宣告的那個主機；這台不跑對方的程式 |
| `requires.synox` 跟這台的版本不合 | 你用到的功能這版沒有 |
| `category` 不是一行字（空的、換行、超過 24 字）；command 的 `summary`、欄位的 `ask`／`help` 有換行或超過 200 字；欄位的 `required` 不是 `true`／`false`；`default` 不合 `kind`／`choices` | 網頁工具頁與 AI 照這些畫表單、送參數；`"required": "false"` 這種字串會被當成必填 |
| `stage` 不是 `test`、`alpha`、`beta`、`stable` 其中一個（大小寫也要對） | 裝的人靠這個標籤判斷多可靠；寫錯就看不出來 |
| `.synoxpack` 超過 5 MB（解開 20 MB、300 個檔），或有絕對路徑、`..`、符號連結 | 防止解壓縮時寫到 pack 資料夾外面 |
| zip 裡的檔名是 Windows 保留名（`CON`、`NUL`、`COM1`、`nul.txt`…）、有冒號（`x.py::$DATA`）、`< > " \| ? *`、結尾是空白或句點 | Windows 解壓縮時會變成裝置、資料流或另一個檔名，看到的跟裝進去的不一樣 |

### 安裝時（第 2 關：靜態掃描）

| 會被擋 | 為什麼 |
|---|---|
| `.py` 用了連網、子程序、檔案、動態執行，`capabilities` 卻沒宣告 | 讓裝的人在裝之前看到你要做什麼（報告列 `檔名:行號`） |
| `.py` 解析不了（語法錯誤） | 掃不了就不能說它安全 |
| pack 裡有執行檔、編譯檔、`node_modules/`，沒宣告 `exec` | 掃不到內容的東西要明說 |
| argv 讓直譯器直接執行程式碼（`-c`、`-e`、`-Command`、`/c`…，寫在 `commands[].argv` 也算），沒宣告 `exec` | 那段程式碼第 2 關掃不到 |
| `{python}` 要跑的 pack 內檔案不是 `.py`／`.pyw`（`./run.txt`、`./app.pyz`、沒有副檔名的 `./run`）；`{python} -m 模組` 而 `cwd` 不在 pack 資料夾（例如 `{user_data_dir}`） | Python 不看副檔名照樣執行、第 2 關卻不會掃；`-m` 會先從 cwd 找模組，使用者資料夾裡同名的檔會先被載入 |
| argv 樣板把旗標和值分兩段（`["--city", "{city}"]`）、用了不認得的 `{…}` | 值一定要綁在同一段，才不會被拼成別的旗標 |
| `data: "user"` 卻用 `{data_dir}`；`data: "none"` 卻用 `{user_data_dir}`／`{data_dir}` | 資料放錯地方會跨戶 |
| 遠端 MCP 或 connector 附了程式檔 | 只能是宣告 |
| 寫了 `integrity` 而檔案對不上、或多了沒列的檔 | 打包之後被改過 |

### 安裝確認時

| 會被擋 | 為什麼 |
|---|---|
| T2 的 pack 沒寫 `publisher`（**`synox-sdk check` 現在不會提醒這一項**，請自己確認） | 裝的人要輸入「信的是誰」，沒有名字就不能裝 |
| 升級時 `version` 沒有比裝著的大 | 避免被換回有漏洞的舊版（裝的人可以明確選降級） |

### 執行時（每次呼叫）

| 會被擋或拿掉 | 為什麼 |
|---|---|
| AI 送的參數：不認得的欄位、超過 2000 字、NUL、（cli）換行、會變成單獨一段 argv 卻以 `-` 開頭 | 不讓 AI（或騙了 AI 的網頁內容）塞旗標或改到別的欄位 |
| `kind: "path"` 的值不在使用者自己的資料夾、像密鑰的檔名（`.env`、`id_rsa`、`*.pem`、`*.key`、`credentials*`…） | 不讓 AI 被騙去讀別的檔 |
| 參數的值等於（或夾著）這個人存的 secret | 防止 secret 被送到別的工具 |
| 名字像密鑰的環境變數（不在 `requires.env`、`auth.fields[].env` 裡的） | 你的程式只拿到你宣告的那幾個 |
| 安裝之後檔案被改過（雜湊對不上） | 不載入，並通知擁有者 |
| MCP 伺服器列了 `tools_allow` 以外的工具 | 不存在、叫不到 |

### 好習慣（不會被擋，但請照做）

- effect 照實寫：會改東西就是 `WRITE`，刪除、付錢、寄信給別人就是 `DANGER`。寫低了，升級時改高會是紅字。
- 不要印 secret、不要把它放進回覆或錯誤訊息；`message` 寫一句人話就好。
- 不要做 `--yes`、`--force` 這種讓 AI 自己跳過確認的旗標，用確認來回。
- 一般指令在 `timeout` 內做完（AI 會等）；很久的工作在 command 上標 `"background": true`。
- 資料只寫在 `<user_data_dir>/<pack 名>/`（`data: "user"`）；資料裡放 `schema` 版本號。
- 用外部程式（`npx`、`git`）時要知道：那支程式不在 SYNOX 的雜湊鎖裡，被換掉 SYNOX 不會發現；`npx` 每次還會去網路抓。
- 第三方的執行檔、npm 套件請在別台機器或隔離環境（雲端、容器、VM）先測過，不要在你平常用的電腦上直接跑別人的東西。
- SKILL.md 寫清楚「什麼時候用、參數怎麼填、什麼時候要先問使用者」：AI 只看得到這份和指令說明。
- 每個 command 寫 `summary`、每個欄位寫 `ask`（格式提示放 `help`），pack 寫 `category`：網頁工具頁照這些分群組、畫表單。

## 範例

| 範例 | 接入路 | 示範什麼 |
|---|---|---|
| [examples/hello](../examples/hello/) | cli（SDK） | `@tool`＋`serve()`、型別即欄位、`init --from` 產生 pack.json |
| [examples/any-language-cli](../examples/any-language-cli/) | cli（不用 SDK） | 純文字協定：任何語言只要印 JSON 信封；`data: user`、確認來回（環境變數） |
| [examples/node-mcp-tool](../examples/node-mcp-tool/) | MCP stdio | Node 標準函式庫手寫 JSON-RPC、`tools_allow`／`effects`、`exec`＋`publisher` |
| [examples/mcp-remote-todoist](../examples/mcp-remote-todoist/) | 遠端 MCP | API token 當 Bearer、`access: member`（網址與工具名是佔位） |
| [examples/mcp-remote-notion](../examples/mcp-remote-notion/) | 遠端 MCP | OAuth 貼回網址（網址、工具名、client_id 是佔位） |

每個範例都會通過 `synox-sdk check`（SYNOX 的測試每次都檢查）。

## 還沒有的

- publisher 的簽章驗證：現在的 publisher 只是一個字串。
- SDK 的 `serve()` 只有 stdio，沒有 HTTP 伺服器。
- MCP：巢狀 `object`／`array` 參數不給、OAuth 只有「貼回網址」（不開本機埠收碼）、沒有動態註冊、不處理伺服器主動推播。
- `synox-sdk run` 只跑 kind=cli。
- 確認卡的憑證放在記憶體：SYNOX 重開之後，舊的卡按不動（要重新下指令）。
