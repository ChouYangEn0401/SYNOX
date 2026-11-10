<!-- SPDX-License-Identifier: Apache-2.0 -->
# ✅ Todoist：遠端 MCP 範例（kind=mcp、transport=http）

> ⚠️ **這是範例，裡面的網址與工具名是佔位，要你對照服務的官方文件確認後才能用。**
> - `mcp.url` 是 `https://todoist-mcp.example.invalid/mcp`（保證連不到）。Todoist 官方遠端 MCP 的正確網址、
>   它收不收 API token 當 Bearer（還是只收 OAuth），請到 Todoist 的官方文件查，**不要照記憶填**。
>   只收 OAuth 的話，照 `examples/mcp-remote-notion` 把 `auth` 改成 `type=oauth`。
> - `tools_allow` 的工具名（find-tasks、add-tasks、complete-tasks、delete-object）也是佔位：
>   連上一次之後用 `python -m synox doctor` 看哪些名字伺服器沒有，照真的 tools/list 改。

現有的 `connectors/todoist`（REST）保留不動；這個範例示範另一條路。

## 示範什麼

- **tools_allow**：只有這 4 個工具會變成指令（/todoistmcp_find_tasks…）；伺服器多列的不存在，AI 也叫不到。
- **effects**：READ／WRITE／DANGER 只看這份 pack.json。`delete-object` 是 DANGER：AI 要用先出核准卡。
- **token 當 Bearer**：`auth.fields` 的 `token`（secret）由網頁介面「連接」表單收進保管箱，
  SYNOX 只把它放在 `Authorization: Bearer` 標頭送到 `mcp.url` 的主機；不寫 log、不給 AI、結果裡出現也會遮掉。
- **access: member**：伺服器版的成員能用（成員的能力上限有 network）；每個人填自己的 token、各自一條連線。訪客看不到。
- 安裝報告逐一列出工具與 effect（T0：只有宣告）。
