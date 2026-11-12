<!-- SPDX-License-Identifier: Apache-2.0 -->
# 👋 hello：synox_sdk 的最小範例（kind=cli）

兩個 Python 函式加上 `@tool`，就是兩個 SYNOX 指令（`/hello` 算小費、`/hello_greet` 打招呼），也是兩個 AI 工具。

| 檔案 | 做什麼 |
|---|---|
| `tool.py` | 你寫的：`@tool("READ")` 的函式＋`serve()` |
| `synox_sdk.py` | SDK 單檔版（只用標準函式庫）；`synox-sdk init --from` 看到你 import 它就自動放一份。**不要改**這個檔 |
| `pack.json`、`SKILL.md` | `synox-sdk init --from tool.py --name hello --title "👋 範例"` 產生的；`publisher` 是之後手動填的 |

## 試試看

```
cd examples/hello
synox-sdk run tip 1000 percent=15      → 含 15% 小費共 1150 元
synox-sdk run greet Amy style=formal   → Amy，您好。
synox-sdk check .                      第 1 關（宣告）＋第 2 關（靜態掃描）
synox-sdk zip .                        → dist/hello-0.1.0.synoxpack
python tool.py --help                  列出指令與參數
```

（還沒有 `synox-sdk` 指令時用 `python -m synox.sdk …`。）

## 示範什麼

- 型別註記就是欄位格式：`float` → `number`、`int` → `int`、`bool` → `bool`、`Literal[...]` → `choice`；
  SYNOX 在叫你的程式**之前**就照這個檢查。
- 有預設值＝選填；docstring 的 `Args:` 段落＝欄位說明。
- `raise ToolError("bad_amount", "金額要大於 0")` → 失敗的信封；`return Ok("…", {...})` → 成功的信封。
- 只有 `.py`＝**T1**（第 2 關掃得到全部），`capabilities` 空著（沒有連網、沒有開別的程式、沒有讀寫檔案）。

改函式之後重跑 `synox-sdk init --from tool.py --name hello`：只會重產 `pack.json` 的 `cli.commands`，其他欄位不動。
完整說明：[docs/tools.md](../../docs/tools.md)、[docs/sdk.md](../../docs/sdk.md)。
