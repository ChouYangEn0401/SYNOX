<!-- SPDX-License-Identifier: Apache-2.0 -->
# 🎲 Node MCP 範例（kind=mcp、transport=stdio）

一支用 **Node 標準函式庫**手寫的 MCP 伺服器（`server.js`，約 120 行）：自己讀 stdin 的 JSON-RPC、自己印回應，
不用 MCP SDK、不用任何 npm 套件，所以資料夾裡**沒有 `node_modules`、沒有 `package.json`**。

| 檔案 | 做什麼 |
|---|---|
| `server.js` | MCP stdio 伺服器：`initialize`、`ping`、`tools/list`、`tools/call`（`notifications/initialized` 不回） |
| `pack.json` | 告訴 SYNOX 怎麼開它、允許哪些工具、每個工具的 effect |
| `SKILL.md` | 給 AI 看：什麼時候用哪個工具 |

## 示範什麼

- **`kind: "mcp"`＋`mcp.transport: "stdio"`**：SYNOX 開子程序 `{node} ./server.js`，用 stdin／stdout 講 JSON-RPC（一行一個訊息），
  不開網路埠。每個使用者一個長駐程序：第一次呼叫才開、閒置 10 分鐘收。
- **`{node}`**：沒寫 `runtime` 時換成這台系統的 `node`。這台沒有 Node＝SYNOX 叫不起來，回一句人話。
- **`tools_allow`**：只有 `count_words`、`roll_dice` 會變成指令（`/nodemcp_count_words`、`/nodemcp_roll_dice`）。
  `server.js` 多列了一個 `internal_stats`，SYNOX 看不到也叫不到。
- **`effects`**：危險程度**只看 pack.json**；伺服器自己說的 annotations 一律不算，沒寫 effect＝第 1 關就拒。
- **`capabilities: ["subprocess", "exec"]`**：kind=mcp stdio 一定要 `subprocess`。`exec` 是作者**自己誠實宣告**：
  `server.js` 是 SYNOX 第 2 關讀不懂的程式（第 2 關只讀 `.py`），等於「我會執行 SYNOX 看不到內容的程式碼」。
  宣告了 `exec` 的 pack 只有擁有者看得到（角色能力上限，見 [docs/tools.md](../../docs/tools.md)「權限欄位」）。
- **`publisher`**：給安裝的人看「信的是誰」。T2 的 pack 一定要寫，安裝時要一字不差地輸入它。

> **注意（現在的 SYNOX 怎麼算這個範例）**：`synox-sdk check` 會過；信任層級目前算 **T1**——`.js` 不在「掃不到內容的檔」清單裡，
> `{node}` 也不算 pack 外的程式。所以安裝時**不會**要你輸入 publisher。這跟「第 2 關讀不懂 .js」不一致，已回報給維護者決定
> （見 [docs/tools.md](../../docs/tools.md)「信任層級」）。作者這邊照實宣告 `exec`、寫好 `publisher`，規則收緊時不用改。
>
> `runtime.node` 目前只給 kind=cli 用（kind=mcp 寫了第 1 關會拒），所以這個範例沒有寫 `runtime`。

## 試試看

```
synox-sdk check examples/node-mcp-tool        第 1 關（宣告）＋第 2 關（靜態掃描）
synox-sdk zip examples/node-mcp-tool          → dist/node-mcp-tool-0.1.0.synoxpack
```

`synox-sdk run` 只跑 kind=cli，不能試跑 MCP。要在自己的電腦上手動試這支伺服器（**要先裝 Node**）：

```
node server.js
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"roll_dice","arguments":{"times":2}}}
```

每貼一行按 Enter，就會印出一行回應；Ctrl+C 結束。

## 改成你的工具

1. 在 `TOOLS` 加一個工具（`name`、`description`、`inputSchema`）；`callTool` 加處理。
   參數型別用 `string`、`integer`、`number`、`boolean`、`enum`；巢狀的 `object`／`array` SYNOX 這一版不給。
2. `pack.json` 的 `tools_allow` 加名字、`effects` 寫 `READ`／`WRITE`／`DANGER`。
3. 要使用者的 API key：`auth.fields` 宣告（見 [docs/tools.md](../../docs/tools.md)「secret 與連接表單」），
   伺服器從環境變數讀；**不要**從參數收。
4. 要確認才做的事：`tools/call` 回 `structuredContent: {"needs_confirm": true, "summary": "…", "confirm_token": "…"}`，
   SYNOX 讓人按 ✅ 之後用同一組 `arguments`、帶 `params._meta["synox/confirm_token"]` 再叫一次。
5. 要 npm 套件：那就會有 `node_modules`（T2，一定要宣告 `exec`）；能不用就不用。
