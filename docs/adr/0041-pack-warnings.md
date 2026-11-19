# ADR 0041：pack.json 的標記警告（`warnings`）——作者標的風險，每個看得到工具的地方都顯示

- 日期：2026-11-18
- 狀態：**已採用**（擁有者的需求：沒有官方標章的選配工具要能帶「官方不保證安全」的警告與執行建議；需求原文不公開）。
  2026-11-19 移植到改寫後的 `dev`（分支 `feat/pack-warnings-v2`），補上第 5 節「與 sandbox 的關係」。
  標 **「實作時決定，待擁有者確認」** 的是這一輪自己定的，擁有者不同意可以改。
- 程式：`src/synox/packs/packwarn.py`（欄位的檢查、清理、規則、顯示用的字），掛在 `manifest.py`、`admin.py`、`upgrade.py`、
  `loader.py`、`lock.py`、`agent/index.py`、`agent/skills.py`、`agent/tools.py`、`web/server.py`、`doctor.py`。
- 前提：[ADR 0028](0028-pack-signatures-official-badge.md)（簽章與官方標章、標章只由 SYNOX 畫）、[ADR 0030](0030-tool-registration-index.md)（給 AI 的工具索引）。

> **給使用者的一句話**：有些工具的作者會在工具上標「⚠️ 官方不保證安全——建議在 docker 或 sandbox 執行」這種警告。
> SYNOX 在工具清單、安裝報告、/help、工具頁、設定頁、doctor、給 AI 的清單裡一律照樣顯示；第一次要用時，你要逐條勾「我知道」（終端機 `--accept-warning <代號>`）才會啟用。

## 1. 欄位

```json
"warnings": [{"code": "vendor_no_security_guarantee", "text": "官方不保證安全", "advice": "建議在 docker 或 sandbox 執行"}]
```

| 欄 | 規則 |
|---|---|
| `code` | 小寫英數字與 `_`，字母開頭，48 字內。固定的代號：確認、規則都用它 |
| `text` | 給人看的一句話，**60 字內**；SYNOX 認得的 code 沒寫 text 用內建的字 |
| `advice` | 建議怎麼做（選填），**120 字內** |
| 條數 | 最多 **5** 條；同一個 code 只留第一條；超過時 SYNOX 認得的 code 一定留 |

`text`／`advice` 一律先清理：換行與 tab 換成空白、拿掉控制字元（C0、DEL、C1）、零寬字元（U+200B–U+200F、U+2060–U+2064、BOM、軟連字號）、
雙向文字控制字元（U+202A–U+202E、U+2066–U+2069），連續空白併成一個，太長截斷加「…」。這段字也會給 AI 看，所以像在對 AI 下指令、
要跳過確認、夾分隔符的字（跟 `agent.index` 同一套 `risk_flags`）、或含「✅」（冒充 SYNOX 的標章）→ 換成內建的字並記一句問題。

SYNOX 認得的 code（`packwarn.KNOWN`）：
- `vendor_no_security_guarantee`：官方不保證安全／建議在 docker 或 sandbox 執行
- `malformed_warning`：SYNOX 自己用的（見下一節），作者不用寫

## 2. 壞格式：不掛掉、不靜默（實作時決定，待擁有者確認）

- `warnings` 寫壞（不是清單、`null`、某一條不是物件、code 不合格式）**不讓整個 pack 掛掉**——安裝時、載入時都一樣。
- 但**不丟掉**：看不懂的那一條換成一條 `malformed_warning`（「這個工具的警告寫壞了，SYNOX 看不懂」），照樣顯示、照樣要確認。
  理由：作者想警告卻寫錯，比較安全的那一邊是「照樣當作有警告」。
- 不認得的欄位（例如 `severity`）：那一條照收，記一句問題。
- 每一個問題都是一句白話：載入時寫 log（`[PACKS] … warnings field problems`）、安裝報告列出來、doctor 列出來、設定頁 API 有 `warning_problems`。
- 沒有 `warnings` 欄位的舊 pack：行為完全不變（`Manifest.warnings == []`，鎖不多欄位，/help 標題、AI 清單一個字都不變）。

## 3. 規則

1. **官方＋「官方不保證安全」不能同時成立**：帶 `vendor_no_security_guarantee` 的 pack，簽章驗出來是「✅ 官方」→
   安裝時拒（第 1、2 關之後當作沒過，沒有確認鈕）、載入時拒（`rejected`）。其他 code 的警告可以是官方的。
   顯示上再加一層：工具頁、設定頁的標章遇到這個 code 一律不畫成官方（`web/server.py _signature`）。
2. **第一次啟用要明確確認**：pack 有警告，安裝（`install_staged`）、核准（`approve_installed`）、升級（`upgrade_staged`）都要擁有者
   確認每一個 code——終端機 `--accept-warning <code>`（可以重複）、網頁在報告上逐條勾「我知道」、`synox init` 逐條問（預設「不要」）。
   少一個就不裝，訊息寫是哪條警告、怎麼確認。確認過的 code 寫進 `packs.lock` 的 `accepted_warnings`。
   - 升級：舊鎖確認過、新版還有的沿用；新版多的 code 要再確認（升級報告紅字列出）；拿掉的不再記。
   - 載入：pack 有警告、鎖裡沒全部確認（例如舊版 SYNOX 裝的、鎖是別的路寫的）→ 狀態 `unaccepted`，不載入，detail 說怎麼確認。
     `unaccepted` 不算錯誤（`LoadReport.ok` 不變）。
3. **簽章涵蓋**：ADR 0028 的 `pack.sig.json` 本來就列出 `pack.json` 的 sha256，所以拿掉、清空、改掉 `warnings` ＝ 簽章驗不過（⛔ 被改過，拒裝）；
   裝好之後在 `packs/` 裡改 = `packs.lock` 的逐檔雜湊對不上（`tampered`，不載入）。**沒有另外的簽章欄位**，不改簽章格式。

## 4. 顯示（每個看得到工具的地方）

| 哪裡 | 怎麼顯示 |
|---|---|
| 安裝報告（終端機 `format_summary`） | 標章那一行的正下方、工具自己的字之前：紅字「⚠️ 這個工具的作者標了 N 個警告」＋每條一行＋怎麼確認 |
| 安裝報告（網頁） | 同一個位置；每條一個勾選框，全部勾了「確認安裝／升級」才按得下去 |
| 安裝報告 JSON | `pack_warnings: {items, lines, codes, problems, needs_accept}`（`warnings` 這個鍵本來就是 SYNOX 自己的提醒字串，所以另取名） |
| 升級報告 | `pack_warnings: {accepted, needs_accept, items, problems}`；新的 code 是紅字的「改了什麼」 |
| /help | 群組標題「🔎 搜尋（🧪 alpha｜⚠️ 官方不保證安全）」；/help 卡片的標籤也帶 |
| 網頁工具頁 | 標題旁紅色標記＋「⚠️ 作者標的警告」一段（每條一行）；`/api/tools` 每列有 `warnings`、`warning_badge` |
| 網頁設定頁 | 每列紅色標記＋建議；`/api/settings` 每列有 `warnings`、`warning_problems`；狀態「有警告還沒確認，先不開」 |
| doctor、`packs status` | 每條一行；沒確認＝⛔ 不會載入＋怎麼確認 |
| 工具庫清單（網頁卡片、`synox tools list`） | 清單（index.json）有 `warnings` 就照同一套檢查顯示（紅色標記排第一）。清單上的只是預告，真正擋人的是安裝報告那一份 |
| 給 AI：能力清單（agent/index.py） | 標題後面「〔⚠️警告 code：text；advice〕」，縮短時只剩 code 與 text，**永遠不縮掉**；清單太長要併成「…另有 N 項」時，有警告的最後才併；有警告時多一行守則（`packwarn.AGENT_RULE`） |
| 給 AI：技能索引、`skill_read` | 名字後面同一個標記；`skill_read` 回的正文最前面先附警告與守則 |
| 給 AI：工具說明（tool spec） | 這個工具的每個指令，說明最前面「〔⚠️警告 code：text〕」 |
| 給 AI：Discord 頻道的功能清單 | 同一個標記＋守則 |
| `data/agent_index.json` | 每一項有 `warnings`（結構化的 `[{code, text, advice}]`） |

守則（`AGENT_RULE`）：標〔⚠️警告 …〕的工具，用之前先把警告原文告訴使用者，不要省略、不要說它是官方或安全的。

## 5. 與 sandbox 的關係（2026-11-19 移植到新 `dev` 時補；只有分析與建議，**這一版沒有改任何 sandbox 行為**）

`vendor_no_security_guarantee` 的建議字是「建議在 docker 或 sandbox 執行」。這一節對照 SYNOX 現在真的有的隔離，回答兩題：
這類 pack 現在能不能被 SYNOX 關起來跑？建議的字跟現有機制一不一致？

### 5.1 SYNOX 裡有兩種「sandbox」，只有一種跟這個警告有關

| 名字 | 管什麼 | 在哪 | 跟這個警告的關係 |
|---|---|---|---|
| **執行期沙盒**（PERM-7） | `kind=cli` 的子程序、`kind=mcp` stdio 的長駐子程序：能讀寫哪些資料夾、能不能連網、記憶體與程序數 | `src/synox/sandbox.py`（`resolve`、`box_for`、`grants_for`、`required`、`restricted_reason`） | **就是建議字說的那個** |
| 面板隔離（ADR 0028 §5） | 工具的網頁面板：`<iframe sandbox="allow-scripts">`＋CSP `sandbox`＋每個 session 的票 | `src/synox/web/paneltickets.py`、`web/server.py` | 只隔開畫面（碰不到主機台的登入與 API），**不隔離 pack 的程式**。不能拿來回答「有沒有關在 sandbox 裡」 |

ADR 0022 的「Gate 1」是擁有者對決定 1–35 的答覆（第 11 節），不是程式裡的一道關；Windows 的探測（`docs/lab/2026-11-16-windows-sandbox-probe-results.md`）
是實測紀錄，**還沒有變成後端程式**。

### 5.2 現在這類 pack 會怎麼跑（讀 `dev` 的程式確認）

| 情況 | 實際用的後端 | 算不算隔離 | 依據 |
|---|---|---|---|
| Windows 個人版（預設 `backend=auto`） | `none` | **不算**：工具用使用者的 Windows 帳號權限跑，讀得到檔案、連得到網路 | `sandbox.resolve`：個人版或不是 Linux 一律 `NoneSandbox()` |
| Windows 設 `backend=jobobject` | Job Object | 不算（只限記憶體與程序數，`isolates=False`） | `JobObjectSandbox` |
| Windows 設 `backend=appcontainer` | 退回 `none` | 不算（只有介面，`APPCONTAINER_TODO`） | `resolve` |
| Windows 11 的 MXC | —— | 還沒有後端（只有探測結果） | ADR 0022 §6.3、探測紀錄 |
| Linux 伺服器版 | `bwrap`，沒有就 `systemd-run` | 算（argv 層面；真機驗證見 `docs/security.md`） | `resolve` |
| pack.json 有 `runtime.container`、擁有者在安裝報告「🧱 執行環境」選了容器、這台 PATH 上有 podman／docker | `container`（任何平台，含 Windows 的 Docker Desktop） | **算**：`--read-only`、`--cap-drop ALL`、`no-new-privileges`、只掛 pack 與它的資料夾；沒宣告 `network` 才 `--network none` | `box_for`、`ContainerSandbox.wrap` |
| `kind=python` | 在 SYNOX 自己的程序裡跑 | **任何後端都包不到** | `sandbox.required` 的說明、ADR 0022 §6.6 |

另外：`required()`／`restricted_reason()`（伺服器版沒有真隔離時「只給擁有者」）只看 trust 與 T2，**不看 `warnings`**；個人版完全不受這條影響。

### 5.3 結論

1. **現在 SYNOX 不會因為這個警告就把 pack 關進 sandbox。** 警告做的事是「每個地方都顯示＋第一次要人確認」（第 3、4 節）；執行時用哪個後端，跟沒有警告的 pack 一樣。
2. **在 Windows 個人版（目前主要的使用者），SYNOX 本身沒有任何一條路能照「在 sandbox 執行」做到**：設定頁「沙盒模式」那張卡也照實寫「⏳ 尚未完成」、doctor 寫「真隔離：否」。
3. **「docker」那半句跟現有機制一致，但有前提**：pack 要自己在 pack.json 宣告 `runtime.container`，擁有者安裝時選「用容器」，這台要有 podman／docker。沒有 `runtime.container` 的 pack，SYNOX 沒辦法替它開容器。
4. 拿 DesktopAgent 的 `web-ddgs`（`kind=cli`、`capabilities` 有 `network`、**沒有** `runtime.container`）對照：SYNOX 跑的是 pack 自己的 `ddgs_cli.py`，用這台的後端（Windows 個人版＝`none`）；
   第三方套件 `ddgs` 本身由這個 pack 交給它自己設定的隔離 worker（`worker_command`，它的文件建議用 docker）。那層隔離在 SYNOX 外面，SYNOX 看不到、也驗證不了。
   所以建議的字**跟這個 pack 自己的設計一致**，但**不是 SYNOX 保證的**。
5. 所以建議字本身沒有錯（它是作者的字，第 3 節的確認也只代表「我知道了」），風險在使用者可能以為「SYNOX 已經幫我放進 sandbox」。
   `docs/install-packs.md` 這一節已經寫「確認不會讓工具變安全」「安裝報告的『🧱 執行環境』能選容器的就選容器」，跟現況一致。

### 5.4 建議（都還沒做；要擁有者決定）

| # | 建議 | 改的是什麼 | 建議／預設 |
|---|---|---|---|
| S1 | 安裝報告與設定頁在警告下面多一行 **SYNOX 自己畫的實況**：「這台目前沒有沙盒，這個工具會用你的帳號權限跑」／「這個工具有提供容器，可以在『🧱 執行環境』選用容器」／「這個工具在 SYNOX 裡面跑，任何沙盒都包不到」（`sandbox.box_for`＋`container_spec`＋`kind` 算） | 只有顯示文字 | **建議做**（另開分支；字照 ADR 0022 R6、R7：白話，術語放小括號） |
| S2 | 帶 `vendor_no_security_guarantee` 的 pack 也算 `sandbox.required()` 命中（跟 T2 一樣）：伺服器版沒有真隔離就只給擁有者 | 執行行為（伺服器版） | 建議做；個人版不受影響 |
| S3 | 隔離做好之後（ADR 0022 決定 17：沒有隔離的電腦上第三方 T2 預設不執行），把這個 code 一起算進去：保護等級「沒有」的電腦上預設不執行，擁有者可以逐個放行 | 執行行為 | 建議，等 MXC／AppContainer 後端做好再做 |
| S4 | `kind=python`＋`vendor_no_security_guarantee`：暫存時拒，或至少紅字寫「任何沙盒都包不到」 | 安裝行為 | 建議「紅字」（拒裝跟修正 O1「一律可以安裝」衝突） |
| S5 | 請 pack 作者（例如 `web-ddgs`）在 pack.json 宣告 `runtime.container`，讓 SYNOX 自己的容器路徑能用，而不是只靠 pack 自己的 worker 設定 | 工具庫與作者端 | 建議；SYNOX 這邊不用改 |

## 6. 沒做的（留給之後）

- 工具庫的 `index.json` 要不要也帶 `warnings`：SYNOX 這邊已經會讀、會顯示；要 SYNOX_Libs 的打包腳本把 pack.json 的 `warnings` 抄過去才有。
- 網頁上「已裝、還沒確認」的工具沒有單獨的「確認」按鈕：要嘛重新從安裝頁裝一次（會勾選），要嘛在電腦上跑
  `python -m synox packs lock --approve <name> --accept-warning <code>`。（實作時決定，待擁有者確認：要不要在設定頁加一顆按鈕）
- 擁有者事後想「取消確認」：目前沒有指令；移除再裝就會重新問。
- 真機上的人工驗證：清單在 [docs/testing/pack-warnings-checklist.md](../testing/pack-warnings-checklist.md)（全部勾完才算過關）。
