# ADR 0039：本機專案直接接——`link`、「synox-agent 結構」、五道關卡怎麼套

- 日期：2026-11-17
- 狀態：**提案（契約定稿，還沒有程式）**。實作分支 `feat/local-link`。
- 基準：分支 `dev`，commit `86a930d`。
- 來源：合一規劃（維護者的私有文件庫，2026-11-17）第 5 節、第 12 節。
- 相關：[0028](0028-pack-signatures-official-badge.md) §4（沒經過安裝頁的工具不載入——不變）、[0022](0022-ecosystem-bridge-and-sandbox.md)（生態相容）、
  [security.md](../security.md)「五關」、[pack-format.md](../pack-format.md)、[install-packs.md](../install-packs.md)。
- 程式：`src/synox/packs/link.py`（新）、`packs/lock.py`（`linked`、狀態 `changed`）、`packs/loader.py`（`changed` 的處理）、`packs/admin.py`（共用報告）、
  `__main__.py`（`link`／`unlink`／`links`）、`web/server.py`＋`static/app.html`（設定頁那一塊）。
- 測試：`tests/test_pack_link.py`、`tests/test_pack_link_web.py`。
- 標籤：**已查證**／**推測**／**待實測**／**待查證**。

## 背景

自己的專案想讓 SYNOX 的 AI 用，現在其實做得到（**已查證**）：`config.json` 的 `packs.dirs` 指到那個資料夾，再在電腦上跑
`python -m synox packs lock --approve <名字>`（跑第 1、2 關、印報告、寫鎖）。不用壓成 `.synoxpack`。缺的是好用：

| 缺的 | 現在 |
|---|---|
| 沒有按鈕 | 要手改設定檔、開終端機 |
| 改一個字就不載入 | 資料夾裡任何檔一變就當成「被改過」（`tampered`），要回終端機再核准，而且說不出「改了什麼」 |
| 資料夾的樣子沒有定 | 每個專案放的位置都不一樣 |
| 專案的程式在工具資料夾外面 | `{python} -m` 的工作目錄一定要在工具資料夾裡（第 2 關的規則），而專案是從自己的根目錄跑的 |

## 決定

| # | 題目 | 決定 |
|---|---|---|
| 1 | 怎麼接 | 新指令 `python -m synox link <資料夾>`，網頁「設定 → 功能與安裝 → 接本機專案」。兩條路走同一個函式、同一份報告 |
| 2 | 接了什麼 | **不複製、不搬**。只做三件事：把那個工具資料夾寫進 `config.json` 的 `packs.dirs`、寫鎖（多 `linked: true`）、存一份核准當時的 pack.json |
| 3 | 改過之後 | 狀態 `changed`（不是 `tampered`）：不載入、通知一次、設定頁列「改了哪些檔」「權限變大了嗎」＋「重新核准」。**沒有自動核准** |
| 4 | 資料夾長什麼樣 | 「synox-agent 結構」：一個標準的 Agent Skill 資料夾（`SKILL.md`）裡多一個 `pack.json` |
| 5 | 五道關卡 | 第 1、4、5 關完整；第 2、3 關只管那個小資料夾。專案本體是「使用者自己信任的程式」，報告上照實寫「未鎖定執行環境」 |
| 6 | 誰能接 | 只有擁有者、只有這台電腦的請求（跟綁驗證器同一個判斷）。開著「危險的動作要先解鎖」時要先解鎖 |
| 7 | 不做 | 監看檔案自動重載；把專案本體放進鎖；自動放行「只改了說明」 |

## 1. 「synox-agent 結構」

```
<你的專案>/
  skills/
    <名字>/                ← 一個 Agent Skill 資料夾；也是 SYNOX 的工具資料夾
      SKILL.md             ← 給 AI：什麼時候用、怎麼用（開頭的 name、description）
      references/*.md      ← 細節分章（用到才讀）
      pack.json            ← 只有 SYNOX 看：有哪些指令、每個多危險、參數、怎麼叫你的程式
      run.py               ← （選）一支很短的啟動檔
```

- **`SKILL.md` 與 `pack.json` 的分工**：`SKILL.md` 是說明書——AI 讀了知道怎麼用，但它只是文字，擋不了任何事。`pack.json` 是合約——
  SYNOX 照它決定 AI 拿得到哪些工具、哪些要先開卡、參數合不合格。只有 `SKILL.md`、沒有 `pack.json` 的資料夾，這一版不能接（沒有工具可以叫）。
- **名字**：資料夾名＝`SKILL.md` 的 `name`＝`pack.json` 的 `name`。三個不一樣＝安裝報告提醒（這一版不拒）。
  想讓別的 agent 也讀得懂就只用小寫英數字與 `-`（**待查證**：Agent Skills 規格對 `name` 的現行規則，技能格式對齊那個 PR 開工前對一次）。
- **`references/`**：這一版照舊要在 `pack.json` 的 `agent.skill.topics` 宣告每一個主題檔；`references/*.md` 自動當主題是技能格式對齊那個 PR 的事。
- **`scripts/`**（Agent Skill 可以附腳本）：SYNOX **不執行**它們；有的話安裝報告寫一行。它們照樣在鎖裡（改了要重新核准）。
- **`pack.json` 怎麼叫專案的程式**（kind=cli）有兩種寫法，二選一：

  | 寫法 | pack.json | 第 2 關會說什麼 | 什麼時候用 |
  |---|---|---|---|
  | **A 模組** | `"argv": ["{python}", "-m", "<專案的模組>"]`、`"cwd": "."`、`runtime.python` 指到專案自己的環境；專案要先裝進那個環境（開發模式安裝） | 外部程式（模組在工具資料夾外）＋外部直譯器：T2「未鎖定執行環境」 | 建議。工具資料夾裡沒有任何程式 |
  | **B 啟動檔** | `"argv": ["{python}", "./run.py"]`；`run.py` 把專案根目錄放進模組搜尋路徑、切過去、呼叫專案的入口 | 啟動檔改了模組搜尋路徑、匯入了工具資料夾外的模組：要宣告 `exec` 能力；同樣是 T2 | 專案沒辦法裝進環境時 |

  **待實測**：兩種寫法過第 2 關的實際輸出（同時進行的行事曆專案分支會用 `synox-sdk check` 跑一次並回報）。
  寫法 A 的 `runtime.python` 現在只認「工具資料夾旁邊一層的環境」（`manifest.SIBLING_VENV_RE`，**已查證**）；`skills/<名字>/` 到專案根目錄是兩層。
  實測確定之後，`feat/local-link` 把這條規則放寬到「往上最多兩層」，照樣記成外部直譯器、照樣 T2——不是放行，只是認得這個版面。
- 接的時候可以選專案的根目錄：SYNOX 自己找 `pack.json`（下面第 2 節的順序）。

## 2. `link`

```
python -m synox link <資料夾> [--yes] [--trust core|third-party] [--trust-publisher <名字>]
python -m synox unlink <名字>
python -m synox links
```

`packs/link.py`：

```python
def find_packs(folder) -> list[str]                    # 找到的工具資料夾（絕對路徑）
def path_problem(folder, *, synox_root, data_dir) -> str    # ""＝可以；否則一句原因
def stage_link(folder, data_dir) -> dict               # 跑第 1、2 關，回報告（不寫任何東西）
def confirm_link(token, data_dir, config_path, *, approved_by, via, trust=None, trust_publisher=None) -> dict
def changed_report(name, data_dir) -> dict             # 狀態 changed：改了什麼
def reapprove(name, data_dir, *, approved_by, via, trust_publisher=None) -> dict
def unlink(name, data_dir, config_path) -> dict
def links(data_dir) -> list[dict]
```

### 找 `pack.json` 的順序（`find_packs`）

1. `<資料夾>/pack.json`（給的就是工具資料夾）；
2. `<資料夾>/skills/*/pack.json`（每個都算，可以一次找到好幾個）；
3. `<資料夾>/synox-agent/pack.json`；
4. `<資料夾>/synox-pack/pack.json`（舊版面，相容用）。

前面的找到了就不看後面的。一個都沒有＝「這個資料夾裡沒有 pack.json」。找到好幾個＝每一個各出一份報告、各自確認。不往更深的地方找。

### 路徑的規則（`path_problem`；任何一條不過＝拒，訊息說是哪一條）

- 要存在、是資料夾、是這台電腦上的本機路徑。
- 拒：UNC 與裝置路徑（`\\伺服器\…`、`//…`、`\\?\…`）；網路磁碟機；路徑上任何一段是符號連結或連接點（解析後的路徑要等於原本的）；
  工具資料夾**裡面**有任何符號連結或連接點。
- 拒：SYNOX 自己的資料夾、它的 `data/`、`packs/`（那是安裝的落點，用安裝頁）。
- 拒：名字或指令群組跟已經載入的工具相同。
- 字串本身：1,024 字內、沒有控制字元與空位元組（網頁那條路先過門禁核心的輸入檢查）。

### 接的時候做什麼

1. `stage_link`：第 1 關（`manifest.validate(strict=True)`）→ 第 2 關（`scan`）→ 信任層級（`tier.assess`）→ 報告。
   報告跟安裝 `.synoxpack` 的是**同一份**（同一個格式化函式），最上面多一塊：

   ```
   🔗 接本機專案（不複製檔案）
      工具資料夾：<路徑>
      SYNOX 只鎖這個資料夾裡的 4 個檔。你的專案本體不在鎖裡：它被改了，SYNOX 不會發現。
   ```

2. 確認（終端機 `--yes` 或互動式問一次；網頁按「確認」）。T2 照舊要一字不差地輸入 `pack.json` 的 `publisher`。
3. `confirm_link`（順序固定；任何一步失敗就把前面的還原）：
   - 寫鎖：`lock.approve(…)`，多兩個欄位 `"linked": true`、`"link": {"source": "<工具資料夾>", "root": "<當初給的資料夾>", "linked_at", "linked_by", "via"}`；
   - 存 `data/links/<名字>/pack.json`：核准當時的 pack.json 原文（之後比「權限變大了嗎」用）；
   - 把**工具資料夾本身**（不是專案根目錄）加進 `config.json` 的 `packs.dirs`（已經在就不重複；其他欄位一個字不動、原子寫入）。
4. SYNOX 開著＝`admin.reload()`；沒開＝下次啟動載入。

`unlink`：從 `packs.dirs` 拿掉、刪鎖的那一筆、刪 `data/links/<名字>/`、重新載入。**不碰專案的任何檔**；工具存在 SYNOX 這邊的資料（`data/<名字>.json` 等）留著，跟移除工具一樣。

`links`：每一個接著的——名字、工具資料夾、狀態（`loaded`／`changed`／`missing`（資料夾不見了）／`invalid`）、什麼時候接的。

## 3. 改過之後：`changed`

- `lock.verify()` 對 `linked` 的鎖：雜湊對不上＝回 `changed`（新狀態；沒有 `linked` 的照舊是 `tampered`）。
- loader：`changed`＝**不載入**、不定義群組；通知擁有者一次（同樣的改動只通知一次，沿用 `first_notice`），類別 `tools`：
  「🔗「{title}」接的本機專案改過了，先不載入。到網頁『設定 → 功能與安裝』看改了什麼、按『重新核准』。」
- 已經載入之後才改（每次叫子程序前的檢查，`LiveCheck`）：那一次**不執行**、同樣的通知、狀態變 `changed`。
- `changed_report(name)`：

  | 欄位 | 內容 | 怎麼算 |
  |---|---|---|
  | `files` | 改了／多了／少了哪些檔（只有檔名） | 鎖裡的雜湊 vs 現在的（`lock.diff`） |
  | `only_docs` | 是不是只有 `.md` 變了 | 同上 |
  | `manifest` | pack.json 改了什麼 | `upgrade.diff_manifests(舊, 新)`、`agent_changes`、`scope_changes`、`caller_changes`：舊的是 `data/links/<名字>/pack.json` |
  | `alert` | 有沒有「權限變大」 | `upgrade` 現成的紅字規則：effect 變寬、多了 WRITE／DANGER 的指令、能力變多、`access` 變寬、`cli.argv`／`runtime`／`cwd` 變了（跑的程式換了）、`agent.always`、`callers`／`stepup` 放寬、`agent.work` 變鬆 |
  | `scan` | 現在這一份過不過第 1、2 關 | 重跑 |

- `reapprove`：第 1、2 關都過才寫新鎖、換掉存的 pack.json。`tier.reconfirm_reasons` 說要重新確認（外部程式變多了、發行者換了）＝要再輸入一次 `publisher`。
- **只改了 `SKILL.md` 也要按**：說明書決定 AI 怎麼用這個工具，改了就該讓人看一眼。畫面上會寫「只有說明改了」，按一下就好。
- 專案本體（工具資料夾外面）怎麼改都**不會**變成 `changed`：它不在鎖裡。

## 4. 五道關卡怎麼套

| 關 | 接本機專案 | 說明 |
|---|---|---|
| 1 宣告檢查 | ✅ 完整 | 接的時候、每次重新核准、每次載入 |
| 2 靜態掃描 | ⚠ 只掃工具資料夾 | 專案本體不掃。報告明寫「外部程式、沒有鎖定」，信任層級 T2（要輸入發行者的名字） |
| 3 鎖定 | ⚠ 只鎖工具資料夾 | `pack.json`、`SKILL.md`、`references/`、啟動檔一改就要重新核准；專案本體怎麼改都不用 |
| 4 呼叫前驗參數 | ✅ 完整 | AI 的每一次呼叫 |
| 5 AI 能不能用＋核准卡＋分隔符 | ✅ 完整 | 跟裝進來的工具一模一樣 |

一句話：**AI 能做什麼、要不要先問你**，本機專案跟打包的工具一樣嚴；**程式本身有沒有被改**，本機專案靠的是「那是你自己的 repo」。
沙盒、能力上限、`callers`／`stepup`、工具健康、`policy.decide` 全部照舊適用（接進來的就是一個 kind=cli 的工具）。

信任預設 `third-party`；要 `agent.always`／`load: always` 才需要選 `core`（規則不變）。接本機的工具**沒有**簽章（狀態 `none`），不會有「官方」標章。

## 5. 網頁

設定 → 功能與安裝，「安裝工具」那一塊下面多一塊「🔗 接本機專案」：

- 一個文字欄位（貼路徑；瀏覽器拿不到絕對路徑，所以不是檔案選擇器）＋「檢查」。
- 檢查的結果用安裝頁現成的報告與確認元件（同一個 `window.SynoxInstall` 流程、同一組步驟事件）。
- 下面一張表：每個接著的工具、狀態；`changed` 的那一列展開是「改了哪些檔」「pack.json 改了什麼（紅字在最上面）」＋「重新核准」；每一列有「取消連接」。

API（都要擁有者、CSRF；多一個條件：`guard.web_api.is_local()`——這台電腦的請求，跟綁驗證器同一個判斷；手機入口一律拒）：

| 方法與路徑 | body | 做什麼 |
|---|---|---|
| `POST /api/packs/link/stage` | `{"path"}` | `find_packs`＋每個 `stage_link`；回 `{"found": [{"token", "summary"}…]}`（`summary` 同安裝的格式，多 `link`） |
| `POST /api/packs/link/confirm` | `{"token", "trust", "trust_publisher"}` | `confirm_link`＋重新載入 |
| `GET /api/packs/links` | — | `links()`＋每個 `changed` 的 `changed_report` |
| `POST /api/packs/link/reapprove` | `{"name", "trust_publisher"}` | `reapprove`＋重新載入 |
| `POST /api/packs/link/unlink` | `{"name"}` | `unlink`＋重新載入 |

這幾個算「裝／移除工具」那一類敏感動作：開著「危險的動作也要先解鎖」時要先解鎖（ADR 0025 決定 5）。每一次都記進安全紀錄（`data/security_audit.jsonl`；路徑照記，因為那是這台電腦自己的檔）。

## 不做的事

- **監看檔案、自動重載**：不做。改了要人按。
- **把專案本體放進鎖或掃描**：不做。照實寫它不在鎖裡。
- **「只改說明就自動放行」**：不做。
- **純文字的技能（只有 `SKILL.md`、沒有工具）**：這一版不接。
- **執行 `scripts/` 裡的東西**：不做。
- **接遠端或網路磁碟上的資料夾、接符號連結**：拒。
- **替使用者建專案的環境、替他裝套件**：不做（`runtime.python: "auto"` 那一套只給裝進來的工具；本機專案用自己的環境）。
- **伺服器版的成員接本機專案**：不做，只有擁有者。

## 測試怎麼寫

照 SYNOX 的規矩：暫存資料夾、假的 pack、**不執行任何外部程式**、不開埠。

`tests/test_pack_link.py`：

1. `find_packs`：四種位置各一個；順序（有第 1 種就不看第 2 種）；`skills/` 底下兩個＝回兩個；都沒有＝空清單；不往更深找。
2. `path_problem`：不存在、是檔案、UNC（`\\host\share\x`、`//host/share/x`）、裝置路徑、路徑上有符號連結或連接點、工具資料夾裡有符號連結、
   SYNOX 自己的 `packs/`／`data/`、名字跟已載入的相同、群組相同、太長、有控制字元——各拒，訊息點名。
   （符號連結在沒有權限建立的 Windows 上跳過那一個案例，並在測試裡寫明。）
3. 連結 → 載入：`stage_link` 不寫任何檔；`confirm_link` 之後鎖裡有 `linked: true` 與 `link.source`、`data/links/<名字>/pack.json` 存在、
   `config.json` 的 `packs.dirs` 多了**工具資料夾**（其他欄位逐字不變）；`load_all` 的狀態是 `loaded`、指令在。
4. 沒有複製：SYNOX 的 `packs/` 底下沒有多任何東西。
5. 改 `SKILL.md` → `changed`、不載入、指令不在、通知一次（同樣的改動第二次載入不再通知）；`changed_report` 的 `only_docs` 是真、`alert` 是假；
   `reapprove` 之後載入。
6. `pack.json` 多一個 DANGER 指令 → `changed_report.alert` 是真、那一條在紅字裡；`reapprove` 之後那個指令才存在。
7. `pack.json` 的 `cli.argv` 換了程式 → 紅字；T2 的重新確認要 `trust_publisher`，沒給＝拒。
8. 改了之後第 1 關不過（指令沒寫 effect）→ `reapprove` 拒、舊鎖不動、狀態還是 `changed`。
9. 已經載入之後才改：下一次呼叫不執行（假的 JobRunner 沒被叫到）、狀態變 `changed`。
10. 沒有 `linked` 的工具被改：照舊是 `tampered`（既有測試不改就過）。
11. `unlink`：`packs.dirs` 拿掉、鎖沒了、`data/links/<名字>/` 沒了；專案資料夾的檔一個都沒少；工具的資料檔還在。
12. 工具資料夾整個不見：`links()` 的狀態 `missing`；SYNOX 照常啟動。
13. T2：沒給 `--trust-publisher`＝拒；給錯＝拒；給對＝過。報告最上面有「🔗 接本機專案」那一塊與「未鎖定執行環境」。
14. 寫法 A 與寫法 B 的假 pack 各一個：第 2 關的結果照第 1 節的表（實測之後把預期值補上）。
15. `confirm_link` 中途失敗（把 `config.json` 弄成唯讀）：鎖與 `data/links/` 都還原、沒有半套。
16. `python -m synox link`／`unlink`／`links` 的結束碼與輸出（用 `__main__` 的函式直接叫，不開子程序）。

`tests/test_pack_link_web.py`（`WebUI.route()`，不開伺服器）：

17. 擁有者＋本機的請求：`stage` → `confirm` → `links` 走得完。
18. 不是擁有者、沒有 CSRF、不是本機的請求（手機入口的標頭）＝各拒。
19. 開著驗證器保護、沒解鎖＝拒並說要先解鎖；解鎖後過。
20. `path` 有控制字元、太長＝在輸入檢查就拒。
21. 回的 `summary` 過安裝頁既有的格式檢查；頁面上的字都走 `textContent`（既有的網頁安全測試那一類）。
22. 每一次都在安全紀錄裡留一筆。

文件：`docs/install-packs.md` 多一節「接本機專案」；`docs/pack-format.md` 多一節「synox-agent 結構」；`docs/security.md`「五關」多上面第 4 節那張表。

## 跟規劃不一樣的地方

| 規劃 | 這份 | 為什麼 |
|---|---|---|
| 把資料夾寫進 `packs.dirs` | 寫的是**工具資料夾本身**，不是專案的根目錄或 `skills/` | 寫上一層的話，之後那裡多出來的每個資料夾都會變成「沒經過安裝頁」的通知 |
| 「權限變大了嗎」用 `packs/upgrade.py` 現成的比較 | 多存一份核准當時的 pack.json（`data/links/<名字>/pack.json`） | 現成的比較要舊的宣告；鎖裡只有雜湊（**已查證**），接本機又沒有 `_removed/` 那份舊版可以讀 |
| 啟動檔 | 兩種寫法（模組／啟動檔），建議模組；並把「旁邊的環境」放寬到兩層 | 啟動檔一定會被第 2 關標成 `exec`（改模組搜尋路徑、匯入外部模組，**已查證** `packs/scan.py`）；模組的寫法工具資料夾裡完全沒有程式。兩種都還是 T2 |
| 載入時才發現改過 | 載入之後才改的也算 `changed`（那一次不執行） | 現成的即時檢查（`LiveCheck`）本來就會擋；要讓它說對的話 |
| 沒寫 | 要先解鎖、要記安全紀錄 | 「裝／移除工具」在 ADR 0025 就是敏感動作，接本機是同一類 |
