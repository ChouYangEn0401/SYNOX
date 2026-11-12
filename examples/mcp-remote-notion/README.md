<!-- SPDX-License-Identifier: Apache-2.0 -->
# 🗂 Notion：遠端 MCP 範例（kind=mcp、transport=http）

> ⚠️ **這是範例，裡面的網址與工具名是佔位，要你對照服務的官方文件確認後才能用。**
> - `mcp.url`、`auth.oauth.authorize_url`／`token_url` 都是 `*.example.invalid`（保證連不到）。
>   Notion 官方遠端 MCP 的正確網址、授權端點，請到 Notion 的官方文件查，**不要照記憶填**。
> - `tools_allow` 的工具名（search、fetch、create-pages、update-page）也是佔位：
>   填好網址、登入一次之後，用 `python -m synox doctor` 看「伺服器上次的 tools/list 沒有這個工具」的提示，
>   照伺服器真的列出來的名字改。
> - `client_id` 要事先在服務那邊登記（SYNOX 這一版不做動態註冊）；登記的 redirect URI 要是
>   `http://127.0.0.1:47232/`（SYNOX 不在那裡聽，見下面）。

SYNOX 工具庫（SYNOX_Libs）的 `notion` 工具（REST、integration token；以前是 SYNOX 的 `connectors/notion`）保留不動；這個範例是另一條路：讓 Notion 自己的 MCP 伺服器提供工具。

## 示範什麼

- **tools_allow**：只有列出來的 4 個工具會變成 SYNOX 的指令（/notionmcp_search…）；伺服器多列的工具不存在。
- **effects**：每個工具的 READ／WRITE／DANGER 由這份 pack.json 決定，伺服器自己說的（annotations）不算。
  `update-page` 寫成 DANGER：AI 要用一定先出核准卡。
- **OAuth 貼回網址**（`auth.type=oauth`、`receiver=paste`）：
  1. 私訊打 `/notionmcp_login`，SYNOX 給一個登入連結（PKCE＋一次性 state，15 分鐘內有效）。
  2. 登入、按允許後，瀏覽器會轉到 `http://127.0.0.1:47232/?code=…`，顯示「無法連上」——正常，SYNOX 沒開埠。
  3. 把網址列整串用 `/notionmcp_code <貼上>` 傳回來。token 存進保管箱。
- 安裝報告會逐一列出 4 個工具與 effect，請安裝的人確認；這種 pack 是 T0（只有宣告，這台不跑它的程式）。

## 安裝

改好網址、client_id、工具名之後，壓成 zip（`python scripts/pack_zip.py examples/mcp-remote-notion`）再用網頁或
`python -m synox install` 裝；報告上確認工具清單。
