# SDK 快速入門：十分鐘寫出第一個工具

給**第一次用 SDK 的開發者**。只走一條最短的路：寫一個 Python 函式 → 本機試跑 → 打包 → 裝進 SYNOX。
每個指令都照這一頁實際跑過（SDK 0.2.x）。想知道更多？看文末的「文件地圖」。

## 先選路（30 秒）

| 你想做的 | 走這條 | 看哪 |
|---|---|---|
| 一個指令一個函式，讓人在 Telegram／網頁打，AI 也能呼叫 | **這一頁**（`kind: cli`，用 `synox_sdk`） | 往下讀 |
| 要存每個人自己的資料、網頁面板、多個檔的大工具 | `kind: python`（`install(app, pack)`） | [tools.md](tools.md)、[pack-format.md](pack-format.md)、[tool-apps.md](tool-apps.md) |
| 只想把別人架好的 MCP 接進來 | 只寫 `pack.json`，不寫程式 | [pack-format.md](pack-format.md)「`mcp`」 |

不確定就從這一頁開始：同一個函式之後要升級成 `kind: python`，不用重寫。

## 0. 準備

- Python 3.11 以上。
- 一份 SYNOX（clone 或解壓縮都行），在它的資料夾裡建好環境（`Setup.bat`，或見 [development.md](development.md)）。
- 下面把 SYNOX 資料夾寫成 `<SYNOX>`。工具指令在 `<SYNOX>\.venv\Scripts\synox-sdk.exe`（Linux：`<SYNOX>/.venv/bin/synox-sdk`），
  下面簡寫成 `synox-sdk`。
- **不需要**金鑰、帳號、網路。

## 1. 寫函式

新資料夾（放哪都行，**不要放在 `<SYNOX>/packs/` 裡**），裡面一個 `tool.py`：

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

三個規則就夠用：

1. `@tool("READ" | "WRITE" | "DANGER")`：**一定要寫**。只看＝READ、會改東西＝WRITE、刪除或付錢＝DANGER（AI 呼叫時一律先送確認卡給人按）。
2. **型別註記就是欄位**：`str`、`int`、`float`、`bool`、`Path`、`Literal[...]`；有預設值＝選填。SYNOX 在叫你的程式**之前**就照型別檢查。
3. **回傳就是答案**：回字串＝給人看的訊息；出錯就 `raise ToolError("代碼", "給人看的一句話")`。

## 2. 產生 pack.json

在那個資料夾裡：

```
synox-sdk init --from tool.py --name hello --title "👋 打招呼"
```

它會產生 `pack.json`、`SKILL.md`，並把單檔 `synox_sdk.py` 放到旁邊（零相依，標準函式庫而已）。
打開 `pack.json`，只要改這幾處（其他不用動）：

| 欄位 | 改成什麼 |
|---|---|
| `summary` | 一句話說這個工具做什麼 |
| `agent.index` | 「什麼時候該找我」（一行、60 字內，給 AI 看） |
| `publisher` | 你的名字（安裝的人會看到） |
| `capabilities` | 工具要連網、開別的程式、讀寫檔案時才寫（下一步的檢查會告訴你缺什麼）；這個例子保持 `[]` |

`SKILL.md` 是給 AI 的用法說明：把 `description` 改成一兩句「什麼時候用、怎麼用」。

## 3. 本機試跑（不用開 SYNOX）

```
synox-sdk run greet Amy style=formal
```

預期看到：`SYNOX 會回：Amy，您好。`。它照 SYNOX 的參數檢查與代換跑，所以這裡過了，SYNOX 裡一樣過。

## 4. 檢查

```
synox-sdk check .
```

這跑的是 SYNOX **安裝時**的前兩關（宣告檢查＋程式靜態掃描），結尾要是 `✅ 可以裝`（結束碼 0）。
有 ⚠️ 不一定是錯：例如 `synox_sdk.py` 讀環境變數會顯示提醒，那是 SDK 本身，正常。結束碼 2＝裝的時候一定會被擋，照訊息修。

## 5. 打包

```
synox-sdk zip .
```

得到 `dist/hello-0.1.0.synoxpack`。版本號來自 `pack.json` 的 `version`；改了工具就升它（semver）。

## 6. 裝進 SYNOX

任選一種（四種走同一條安全檢查，你按確認才會裝；詳見 [install-packs.md](install-packs.md)）：

- 點兩下 `.synoxpack`（`Setup.bat` 跑過就有）；
- 拖進 SYNOX 網頁；
- 命令列：`<SYNOX>\.venv\Scripts\python.exe -m synox install dist\hello-0.1.0.synoxpack`。

裝好後在 SYNOX 的「功能與安裝」看得到「👋 打招呼」；在聊天打指令，或直接對 AI 說「跟 Amy 打招呼」（指令名怎麼組，看 [pack-format.md](pack-format.md) 的 `group`）。

## 之後常用的

| 需求 | 做法（正本都在 [sdk.md](sdk.md)） |
|---|---|
| 刪除前先問人看過資料 | `raise Confirm("要刪 3 筆")` |
| 存 token、密碼 | 在 `pack.json` 宣告 `auth.fields`，程式裡 `secret("欄位名")` 取值（使用者在工具頁「連接」填；不要印出來） |
| 知道是誰叫的／擋掉 AI 呼叫 | `caller()`、`require_human()` |
| 失敗時告訴 SYNOX 怎麼辦 | `fail("code", "訊息", remedy="needs_config")`，見 [tool-health.md](tool-health.md) |
| 要給別人用、驗證不是被改過 | `synox-sdk keygen`／`sign`／`verify`，見 [sdk.md](sdk.md) 與 [signing.md](signing.md) |
| 同一個檔當 MCP server 給別的 AI 用戶端 | `python tool.py --mcp`，見 [sdk.md](sdk.md)「serve()」 |

完整可跑的範例：[`../examples/hello/`](../examples/hello/)。

## 文件地圖：SDK 的文件在哪

| 想知道 | 看 | 在哪個 repo |
|---|---|---|
| 最短流程（這一頁） | [sdk-quickstart.md](sdk-quickstart.md) | SYNOX |
| `@tool`、型別對照、`Ok`／`fail`／`Confirm`、`serve()`、`synox-sdk` 指令、SDK 版本（`requires.sdk`） | [sdk.md](sdk.md)（**SDK 的正本說明**） | SYNOX |
| 三條接入路怎麼選、權限、secret、安全自檢 | [tools.md](tools.md) | SYNOX |
| `pack.json` 每個欄位 | [pack-format.md](pack-format.md) | SYNOX |
| 工具的網頁畫面 | [tool-apps.md](tool-apps.md) | SYNOX |
| SDK 程式本身 | `src/synox/sdk/author.py`（單檔版 `sdk/synox_sdk.py` 由它產生，不要直接改） | SYNOX |
| 要做**官方工具庫**裡的工具（`kind: python`、多人、公開頁、發佈） | SYNOX_Libs 的 `docs/HANDOFF.md`、`docs/CONTRIBUTING-TOOLS.md` | SYNOX_Libs |
| 開發環境、測試、交 PR | [development.md](development.md) | SYNOX |

文件跟程式對不上時以程式為準。
