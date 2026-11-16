# 找到別人做的工具，怎麼放進 SYNOX（安全版）

給**使用者**：你在網路上、朋友那裡、或別的 AI 助理的生態看到一個好用的東西（工具、MCP 伺服器、Claude 技能…），想放進 SYNOX。
這一頁告訴你：它是哪一種、能不能裝、怎麼裝、安裝報告怎麼看、哪些情況 SYNOX 一定會拒絕。

> 先講結論：SYNOX 只認一種東西——**pack**（一個資料夾，裡面有 `pack.json`，通常壓成 `.synoxpack`）。
> 不管來源是什麼，最後都要變成 pack、走同一條「檢查 → 報告給你看 → 你按確認才裝」的路。
> 沒按確認，什麼都不會裝進去；報告上看不懂或不放心，就不要按。

- [第一步：它是哪一種？](#第一步它是哪一種)
- [安裝報告怎麼看](#安裝報告怎麼看)
- [例子：接一個官方的遠端 MCP](#例子接一個官方的遠端-mcp)
- [本機 MCP（README 叫你 npx、uvx、docker run 的）](#本機-mcpreadme-叫你-npxuvxdocker-run-的)
- [Claude 技能（SKILL.md 資料夾）](#claude-技能skillmd-資料夾)
- [危險信號](#危險信號)
- [SYNOX 一定會拒絕的](#synox-一定會拒絕的)

## 第一步：它是哪一種？

照你手上拿到的東西，對下面這張表：

| 你拿到的是… | 怎麼認 | 能不能裝 | 怎麼做 | 信任層級 |
|---|---|---|---|---|
| **一個 `.synoxpack` 檔** | 副檔名 `.synoxpack`（或裡面有 `pack.json` 的 `.zip`） | ✅ 可以 | 點兩下、拖進網頁、或 `synox install`：[install-packs.md](install-packs.md) | 看報告（T0／T1／T2） |
| **SYNOX 官方工具庫裡的工具** | 網頁「設定 → 🧩 功能與安裝 → 工具庫（官方）」看得到 | ✅ 可以 | 按「載入工具清單」→「安裝」；或 `synox tools install <名字>` | 看報告 |
| **遠端 MCP**（一個 `https://…/mcp` 網址） | 服務說明寫「remote MCP server」「Streamable HTTP」，給你一個網址＋登入方式（API token 或 OAuth） | ✅ 可以，**要自己寫一份 `pack.json`**（只有宣告，不用寫程式） | 見下面[例子](#例子接一個官方的遠端-mcp) | **T0**：這台電腦不跑它的程式 |
| **本機 MCP** | README 寫 `npx …`、`uvx …`、`docker run …`、`node server.js` | ⚠️ 技術上可以，但等於在你電腦上跑別人的程式 | 見下面[本機 MCP](#本機-mcpreadme-叫你-npxuvxdocker-run-的)；能用遠端版就用遠端版 | 通常 **T2** |
| **Claude 技能／Agent 技能**（一個資料夾，裡面有 `SKILL.md`） | 例如 Anthropic 的 `docx`、`xlsx`、`pdf`、`pptx`，或技能市集上的 | ❌ **現在不能直接裝** | 見下面[Claude 技能](#claude-技能skillmd-資料夾) | — |
| **一支 Python 程式或命令列程式**（不是 pack） | 沒有 `pack.json` | ❌ 不能直接裝 | 請作者照 [tools.md](tools.md) 包成 pack（用 SDK 約十行） | 包好之後看報告 |
| **別的 AI 助理的外掛**（plugin、hook、排程） | 是給另一套程式用的 | ❌ 不能 | SYNOX 不跑別家的外掛程式（[ADR 0022](adr/0022-ecosystem-bridge-and-sandbox.md) §1.4，提案） | — |

不確定是哪一種？**不要裝**，先問給你東西的人「這是遠端網址，還是要在我電腦上跑的程式？」

## 安裝報告怎麼看

每一條安裝的路最後都會給你一份報告，**你按確認才會裝**。重點看這幾行：

| 報告上的字 | 意思 | 你要做什麼 |
|---|---|---|
| **信任層級 T0（只有宣告）** | 沒有任何程式會在你電腦上跑（遠端 MCP、外觀包） | 看「連到哪個主機」是不是你認得的服務 |
| **T1（原始碼）** | 會跑 Python 程式，SYNOX 讀過內容、檢查過 | 檢查是**提醒不是保證**；只裝你信得過的人給的 |
| **T2（二進位或外部相依）**，紅字 | 會跑 SYNOX **看不到內容**的東西：執行檔、npm 套件、`npx`、要下載的套件 | 要你**一字不差打出發行者名字**才能裝。不認識這個人就不要打 |
| 🔌 MCP：連到 `xxx`，只允許下面這 N 個工具 | 遠端 MCP 會把你的請求和 token 送到這個主機；只有列出來的工具存在 | 一個一個看：READ（只看）、WRITE（會改東西）、DANGER（刪除、送出…，AI 每次都要你按核准） |
| 要什麼權限：`network`、`subprocess`、`filesystem:any`、`exec` | 連網、開別的程式、讀寫整台電腦的檔案、執行看不到的程式 | 權限越多越要小心；跟工具說的用途對不起來就不要裝 |
| ⚠️ 未鎖定執行環境 | 它叫的程式在工具資料夾**外面**（例如 `npx`），被換掉 SYNOX 不會發現 | 本機 MCP 才會有；見下面 |
| 🧱 要建環境：裝 N 個套件 | 按確認之後會從 PyPI／npm 下載套件 | 套件內容 SYNOX 不看；「沒有雜湊」的紅字代表只釘了版本 |
| 升級時的紅字（權限變大、發行者換了、T1 變 T2） | 新版比舊版要更多 | 想清楚為什麼要更多 |

細節：[security.md](security.md)「五關」「信任層級」。

## 例子：接一個官方的遠端 MCP

假設某個服務公告了官方的遠端 MCP：網址 `https://mcp.example.com/mcp`，用 API token 登入，提供 `search-items`、`get-item`、`add-item`、`delete-item` 四個工具。
（這裡全是假的佔位名字；換成那個服務官方文件寫的。）

### 1. 先確認三件事

1. **網址是 `https://` 開頭**、而且是那個服務自己的網域（不是某個人的個人網站）。
2. **登入方式**：
   - API token（服務的設定頁可以產生一串 token）→ 最簡單，`auth.type` 寫 `token`。
   - OAuth（「用 XX 帳號登入」）→ `auth.type` 寫 `oauth`，**你要先在那個服務登記一個應用程式**拿到 `client_id`，
     而且那個服務要允許回呼網址是 `http://127.0.0.1:<埠>/`（SYNOX 不開埠，登入後要你把瀏覽器網址列貼回來）。
     需要 client secret 的服務現在接不起來（見下面「已知接不起來的」）。
   - 不用登入 → `auth.type` 寫 `none`。
3. **工具的名字**：官方文件會列。只挑你要的，**能只開「看」的就只開「看」的**。

### 2. 建一個資料夾，放兩個檔

資料夾名字隨意，例如 `example-mcp`。

`pack.json`：

```json
{
  "name": "example-mcp",
  "title": "📦 Example（遠端 MCP）",
  "summary": "接 Example 的官方遠端 MCP：查資料、加一筆。",
  "version": "0.1.0",
  "kind": "mcp",
  "group": "example",
  "access": "owner",
  "surfaces": ["dm"],
  "skill": "SKILL.md",
  "publisher": "我自己",
  "capabilities": ["network"],
  "auth": {
    "type": "token",
    "fields": [{"name": "token", "label": "Example API token", "secret": true,
                "help": "Example 設定 → 開發者 → API token"}]
  },
  "mcp": {
    "transport": "http",
    "url": "https://mcp.example.com/mcp",
    "bearer": "token",
    "timeout": 60,
    "tools_allow": ["search-items", "get-item", "add-item"],
    "effects": {"search-items": "READ", "get-item": "READ", "add-item": "WRITE"}
  }
}
```

- `tools_allow`：**只有這裡列的工具存在**，伺服器提供再多也看不到、叫不到。上面故意沒開 `delete-item`。
- `effects`：每個工具都要寫，沒寫就拒裝。**SYNOX 只看你寫的這一份**，不信伺服器自己說「我是唯讀的」。
  拿不準就寫 `DANGER`：AI 每次要用都會先送確認卡給你按。
- `access: owner`＋`surfaces: ["dm"]`：只有你、只在私訊用得到。

`SKILL.md`（告訴 AI 什麼時候用；開頭那段一定要有 `name`、`description`）：

```markdown
---
name: example-mcp
description: 使用者想查 Example 上的資料，或要加一筆到 Example 時使用。
---

# Example（遠端 MCP）
- 「找一下關於 X 的資料」→ `example__search_items`
- 「把這個加到 Example」→ `example__add_item`（會寫入）
```

工具名在 SYNOX 裡會變成 `/<group>_<工具名>`（`search-items` → `/example_search_items`）；給 AI 的名字是 `example__search_items`。

完整欄位規則：[pack-format.md](pack-format.md)「`mcp`（http：遠端 MCP）」；可以照抄的：`examples/mcp-remote-todoist`（token）、`examples/mcp-remote-notion`（OAuth）。

### 3. 打包、上傳、看報告

- 沒裝工具 SDK：把資料夾壓成 zip（檔案總管：右鍵 →「傳送到」→「壓縮的資料夾」），拖進 SYNOX 網頁，或「設定 → 功能」選檔按「上傳並檢查」。
- 有裝工具 SDK（`pip install <SYNOX 資料夾>/sdk`）：`synox-sdk check example-mcp` 先看會不會被擋，再 `synox-sdk zip example-mcp` 打包。
- 報告上應該看到：**信任 T0（只有宣告）**、連到 `mcp.example.com`、三個工具和各自的 READ／WRITE。對得上才按確認。
  上面這個例子的報告（終端機版，節錄）：

```
🔌 MCP：http，連到 mcp.example.com，信任 T0（只有宣告）；只允許下面這 3 個工具（請逐一確認）：
  · search-items：READ（只讀）
  · get-item：READ（只讀）
  · add-item：WRITE（會寫入）
🧭 在哪裡用：只能私訊　資料：不存資料（沒寫，照預設推的）
🧩 信任層級：T0 只有宣告（沒有程式在這台跑）
⚠️ 這是遠端 MCP（T0，只有宣告）：你的請求和 token 會送到 mcp.example.com；那台伺服器做什麼掃描看不到。只會用上面列的工具，effect 照這份宣告（不照伺服器自己說的）。
```

### 4. 登入、試用

- token：網頁「工具」頁那張卡按「🔌 連接」，貼 token（**不要在聊天裡貼**）。或在電腦上 `synox connect example-mcp`。
- OAuth：私訊 bot 打 `/<group>_login` → 打開它給的連結、登入、按允許 → 瀏覽器會顯示「無法連上」（正常，SYNOX 不開埠）→
  把網址列**整串**用 `/<group>_code <貼上>` 傳回去。之後把那則訊息刪掉。登出：`/<group>_logout`。
- 先叫一個 READ 的試試：`/example_search_items 測試`。
- `synox doctor` 會說「`tools_allow` 的某個工具伺服器上沒有」——代表名字打錯了。

### 已知接不起來的

- **Google 官方的遠端 MCP（Gmail、雲端硬碟、試算表…）**：Google 的設定說明要求「網頁應用程式」類型的 OAuth 用戶端＋**client secret**，
  而且要加 `access_type=offline` 才拿得到 refresh token。SYNOX 這一版的 OAuth 只送 `client_id`（沒有放 client secret 的地方）、也不送
  `access_type`，所以**現在不能直接接**（換 token 那一步預期會被拒；沒有實際試過）。另外這批端點是 Google 的
  Developer Preview，要先加入計畫，個人帳號能不能加入沒有查到。要等 SYNOX 補上這兩點才能用。
- 要用「loopback」（SYNOX 暫時開本機埠收登入結果）的服務：這一版不做，會被拒。

## 本機 MCP（README 叫你 npx、uvx、docker run 的）

這種 MCP 伺服器是**一支要在你電腦上跑的程式**。SYNOX 可以接（`kind: mcp`、`"transport": "stdio"`），但你要知道：

- `npx`／`uvx` 每次可能從網路抓**最新版**來跑；SYNOX 的雜湊鎖只鎖工具資料夾裡的檔，**鎖不到它**（報告標「未鎖定執行環境」、T2）。
- **個人版、Windows 上沒有沙盒**：它跟 SYNOX 一樣看得到你整台電腦的檔案（[security.md](security.md)「運行空間」）。
  SYNOX 只把每個程序關在 Windows 的 Job Object 裡（SYNOX 結束時一起結束），**不限制檔案和網路**。
- 真的隔離只有兩種：Linux 伺服器上的 bwrap／systemd（還沒在真機驗證），或作者在 `pack.json` 提供 `runtime.container`
  （映像要釘 `@sha256:`；你自己裝了 Docker／Podman，安裝時選「用容器跑」）。

建議順序：

1. **那個服務有官方遠端版嗎？** 有就用遠端版（上面的例子），這台電腦什麼都不用跑。
2. 沒有：請作者或工具庫維護者包成**帶容器的 pack**，或在別台電腦／雲端跑它的 HTTP 模式，SYNOX 再用遠端 MCP 的方式接那個網址。
3. 還是要在本機跑：只裝你信得過的作者、釘死版本（不要 `@latest`）、`tools_allow` 只開需要的，報告上的發行者想清楚再打。

pack.json 怎麼寫：[pack-format.md](pack-format.md)「`mcp`（stdio）」。

## Claude 技能（SKILL.md 資料夾）

**它是什麼**：一個資料夾，裡面一份 `SKILL.md`（開頭寫名字和「什麼時候用」，後面是給 AI 的操作說明），常常還附 `scripts/`（Python、JavaScript）
和參考檔。Claude 的 App、Claude Code、Claude API 會在需要時讀它，**再用它自己的電腦工具去跑裡面的程式**。
格式是公開的 [Agent Skills](https://agentskills.io) 規格。

**能不能在 SYNOX 用：現在不能直接用。** 原因：

1. SYNOX 沒有「技能」這種安裝種類（`kind=skill` 還是 [ADR 0022](adr/0022-ecosystem-bridge-and-sandbox.md) 的提案，沒做）。
2. 技能的說明是寫給「手上有命令列的 AI」看的（例如「用 pandoc 轉檔」「跑 `scripts/xxx.py`」）。SYNOX 的 AI **不能直接操作電腦**，
   只能叫你裝好的工具；它讀得懂說明，但做不到。
3. 用 Claude Code 當 SYNOX 的 AI 來源也一樣：SYNOX 叫 Claude Code 時把它的工具全部關掉（`--tools ""`、`--setting-sources ""`、
   空的工作資料夾；[claude-code-cli.md](claude-code-cli.md)），它只能回文字，**不會載入、也不會執行技能**。
   這是故意的：技能附的程式如果讓 AI 自己跑，就繞過了 SYNOX 的「報告 → 你按確認 → 核准卡」。

**那想要「做 Word、Excel、PDF」怎麼辦？**

| 做法 | 安全嗎 | 現況 |
|---|---|---|
| 做一個 SYNOX 工具（pack），用 `python-docx`、`openpyxl`、`pypdf` 這類套件處理**你自己資料夾裡**的檔，每個動作標 READ／WRITE | ✅ 走正常的安裝報告；會裝套件所以是 T2 | 還沒有人做；可以提給工具庫 |
| 只借技能的「說明文字」（純文字、沒附程式的技能，例如寫作風格、品牌規範），貼進某個工具的 `SKILL.md` | ✅ 不跑任何程式；但只對已經有的工具有用 | 現在就能做；記得保留原作者與授權（Anthropic 的技能是 Apache-2.0） |
| 直接讓 AI 跑技能附的 `scripts/` | ❌ 等於讓 AI 在你電腦上跑別人的程式 | SYNOX 不做 |
| 在 Claude 自己的 App 或 API 裡用（程式在 Anthropic 的雲端容器跑） | 程式不在你電腦上跑 | 那是 Claude 的功能，不經過 SYNOX |

技能市集上的技能**不要直接執行裡面的安裝步驟**（「先跑這行指令」「Prerequisites」）：這正是假技能最常用的手法。

## 危險信號

看到這些，先停下來：

- 要你**複製一行指令貼到終端機**（`curl … | sh`、`iwr … | iex`、`npx 某某@latest`）才能「裝好」。
- 要你在聊天裡貼密碼、token、API key（SYNOX 的 token 一律在網頁「連接」表單填）。
- 遠端 MCP 的網址是 `http://`（不是 https）、IP 位址、短網址，或不是那個服務自己的網域。
- 報告上的權限比用途大很多：一個「查天氣」的工具要 `filesystem:any`、`exec`。
- T2 的發行者名字你不認識、或跟你以為的作者不一樣。
- 升級時突然多了權限、換了發行者（紅字）。
- 「免費破解版」「不用登入就能用某某付費服務」。

## SYNOX 一定會拒絕的

不用你判斷，SYNOX 會直接擋（[security.md](security.md)「五關」）：

- 遠端 MCP：網址不是 `https://`、網址帶帳密；pack 裡附了程式檔；`tools_allow` 是空的；任何工具沒寫 effect；伺服器想把你轉到別的網址（不跟著轉）。
- OAuth：端點不是 https；回呼網址不是 `http://127.0.0.1:<埠>/`；要 SYNOX 開埠收登入結果（loopback）。
- 壓縮檔：超過 5 MB、檔案超過 300 個、有捷徑（符號連結）、絕對路徑或 `..`、Windows 保留檔名、前面接了東西的自解壓 exe。
- 程式用了沒宣告的能力（連網、開程式、讀 pack 外的檔…）。
- T2 沒寫發行者、或你打的名字對不上。
- Python 套件沒釘版本（`==`）、npm 套件不是從官方 registry 來的、容器映像沒釘 `@sha256:`、容器要特權或主機網路。
- 安裝之後檔案被改過（雜湊對不上）：不載入，並通知你。

## 相關文件

- 裝 `.synoxpack`：[install-packs.md](install-packs.md)
- 找、更新、移除工具：[ecosystem.md](ecosystem.md)
- 安全邊界與沒有做的保護：[security.md](security.md)
- 給作者（把你的程式包成工具）：[tools.md](tools.md)、[pack-format.md](pack-format.md)、[sdk.md](sdk.md)
- 沙盒的現況與徵求協助：[sandbox-roadmap.md](sandbox-roadmap.md)
