# 沙盒與「帶警告的 pack」真機測試清單

> **這份清單全部勾完才算過關。** 自動測試全綠不等於過關：第三節以後每一項都要在**另一台電腦**上由人（或那台電腦上的 session）
> 照步驟走一遍、填結果欄。有任何一項「失敗」或空著，這一批（S1、S2、S4）就不算驗收完成。
> 某一項因為那台機器沒有條件做不了（例如沒有 Linux），結果欄寫「略過：原因」，並在第六節的總表寫明；**略過不算通過**，要擁有者明確接受才算。

- 對應：[ADR 0041 §5](../adr/0041-pack-warnings.md)（S1、S2、S4）、[ADR 0022](../adr/0022-ecosystem-bridge-and-sandbox.md)（沙盒的整體設計）、
  程式 `src/synox/sandbox.py`（`isolation_note`、`required`、`restricted_reason`、`JobObjectSandbox`、`ContainerSandbox`）、
  自動測試 `tests/test_sandbox_ready.py`、`tests/test_sandbox.py`、`tests/test_container_sandbox.py`。
- 交接書（為什麼、怎麼準備、失敗怎麼回報）：[docs/handoff/sandbox-real-machine.md](../handoff/sandbox-real-machine.md)。先讀那份再做這份。
- 容器旗標本身（`--cap-drop`、`--read-only`、記憶體、程序數…）的逐項驗證在 [docs/handoff/container-verification.md](../handoff/container-verification.md)；
  這份只驗跟「帶警告的 pack」與「這台實況」有關的部分，重疊的地方直接引用那份的項目編號。
- 結果欄怎麼填：`通過`／`失敗（一句話原因）`／`略過（原因）`、日期 `YYYY-MM-DD`、驗證者（代號即可，不寫真名、不寫信箱）。

## 一、規矩（每一項都適用）

- **測試用的 pack 一律是第二節的假 pack**（自己寫、只用 Python 標準函式庫、沒有網路下載）。不裝、不叫任何第三方 pack 的指令。
- **不改防火牆、不開對外的埠**。SYNOX 的網頁只綁 `127.0.0.1`；自己開的程序（SYNOX、console）記下 pid，測完關掉，確認埠已放掉。
- **不執行下載來的東西**（安裝檔、別人的腳本、壓縮包裡的程式）。容器映像的規則見交接書「容器映像」一節。
- 不要為了騰記憶體去關別人的程式；這份清單的記憶體測試只用自己的探針（上限 256 MB）。
- 發現問題：照交接書「失敗時怎麼回報」一件一檔，不要直接改程式。

## 二、自動測試涵蓋什麼（`python -m pytest -q -p no:cacheprovider tests/test_sandbox_ready.py`）

這些不用人工再驗；列出來是讓驗收的人知道**哪些沒被自動測到**（第三節以後）。所有自動測試的後端與容器引擎都是假的（`which` 是假的，不執行 podman／docker）。

| 範圍 | 測什麼 | 測試名 |
|---|---|---|
| 沒有警告＝不變 | 沒有 `warnings` 的 pack：沒有實況那一行、報告的 `pack_warnings` 沒有 `isolation` 鍵、`/api/settings` 那一列沒有 `isolation`、`agent_index.json` 沒有 `isolation`、能力清單那一行一字不變、doctor 不多一行 | `test_no_warnings_no_note`、`test_no_warning_install_report_unchanged`、`test_settings_api_rows`、`test_web_upload_report_has_line`、`test_agent_entry_line_and_file`、`test_agent_index_built_with_note`、`test_doctor_line`、`test_packs_status_and_lock_print_line` |
| S1 各種狀態的字 | 沒有隔離（none）、jobobject、bwrap（假）、有提供容器（偵測到／沒偵測到引擎）、選了容器有引擎、選了容器沒引擎、選了「不用容器」、外觀包、只登記、遠端 MCP；每一種都不說「已在 sandbox」 | `test_cli_no_isolation_on_this_machine`、`test_cli_jobobject_is_not_isolation`、`test_cli_real_host_isolation`、`test_windows_personal_default_is_no_isolation`、`test_installing_container_offered`、`test_installed_container_*`、`test_other_kinds` |
| S1 顯示的地方 | 安裝報告（終端機，緊接在警告下面）、`synox install`、`packs lock`、`packs status`、網頁安裝報告 JSON、設定頁 API、`app.html` 兩處、doctor、給 AI 的能力清單與 `agent_index.json` | `test_install_report_line_under_warnings`、`test_cli_install_prints_line`、`test_packs_status_and_lock_print_line`、`test_web_upload_report_has_line`、`test_settings_api_rows`、`test_web_page_renders_line`、`test_doctor_line`、`test_agent_*` |
| S4 | `kind=python`＋警告：紅字「沒有任何後端能把它關起來」，**照樣能裝** | `test_python_pack_says_nothing_can_box_it`、`test_python_pack_still_installs_with_red_line` |
| S2 | 伺服器版：cli 帶 `vendor_no_security_guarantee` → 一定要沙盒（不管 trust、`required_for`）；none／jobobject → 只給擁有者；bwrap（假）或容器 → 給成員；python 帶這個 code → 一律只給擁有者；別的 code 不受影響；個人版不變；loader 真的把群組改成只給擁有者、成員叫不到 | `test_required_and_reason_for_vendor_cli`、`test_vendor_cli_with_container_is_open_to_members`、`test_vendor_python_pack_owner_only_on_server`、`test_server_loader_hides_vendor_pack_from_members`、`test_server_loader_vendor_pack_open_with_real_isolation`、`test_personal_loader_unchanged` |

**自動測試沒涵蓋的**：真的 Job Object 有沒有限制住、真的 podman／docker 跑不跑得起來、容器裡是不是真的看不到主機、真的 bwrap、
瀏覽器裡的畫面、真的 Telegram／console 上的可見性、Windows MXC 的實際能力。這些都在下面。

## 三、準備（照交接書第 3 節做完再開始）

假 pack 的內容、`config.json` 的寫法、打包指令都在交接書第 3 節。這裡只列代號：

| 代號 | 是什麼 | 用在 |
|---|---|---|
| `warnpy` | `kind=python`＋`vendor_no_security_guarantee` | S1、S2、S4 |
| `warncli` | `kind=cli`＋`vendor_no_security_guarantee`，**沒有** `runtime.container`；指令 `peek`（讀不讀得到自己放的假檔）、`ok` | S1、S2、沒有隔離時是不是真的沒有 |
| `warnbox` | 同 `warncli`，再加 `runtime.container`（`network: false`）；多一個指令 `net`（試連外，預期連不到） | 容器、S1 的容器狀態 |
| `jobprobe` | `kind=cli`，**沒有警告**；指令 `hog`（要 600 MB）、`spawn`（開 20 個子程序）、`ok` | jobobject 的限制 |
| `plaincli` | `kind=cli`，**沒有警告**（其他跟 `warncli` 一樣） | 「沒有警告的輸出完全不變」 |

- [ ] **P0 環境記錄**
  - 步驟：照交接書 3.1 記下作業系統與版本、Python 版本、`podman version`／`docker version`（有的話）、SYNOX 的 commit（`git log --oneline -1`）。
  - 預期：寫進第六節總表那一列。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **P1 單元測試基準**
  - 步驟：`python -m pytest -q -p no:cacheprovider tests/test_sandbox_ready.py tests/test_sandbox.py tests/test_container_sandbox.py`
  - 預期：全部通過（記下 passed 數）。不通過就先停，照交接書回報。
  - 結果：＿＿＿＿　passed：＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

## 四、Windows（個人版）

### 4.1 doctor／設定頁顯示的隔離狀態跟實際一致

- [ ] **W1 預設（`backend: auto`）＝沒有隔離，而且真的沒有**
  - 步驟：用交接書的「個人版」`config.json`（`policy.sandbox` 不寫）。裝 `warncli`（`python -m synox install warncli.synoxpack --yes --accept-warning vendor_no_security_guarantee`）。
    `python -m synox doctor --offline`；打開網頁設定頁的「沙盒模式」那張卡；再 `python -m synox console`，打 `/warncli_peek`。
  - 預期：doctor「• 沙盒：後端 none（不隔離…）；真隔離：否」；設定頁照實寫還沒有沙盒（不是「已啟用」）；
    `/warncli_peek` 回 `readable: true`（讀得到你放在家目錄的假檔）——**跟「沒有隔離」一致**。如果讀不到，記「失敗」（代表顯示跟實際不符）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **W2 `backend: jobobject` 也算「沒有隔離」**
  - 步驟：`config.json` 的 `policy.sandbox` 改 `{"backend": "jobobject", "mem_mb": 256, "max_procs": 8}`，重開；doctor；console 打 `/warncli_peek`。
  - 預期：doctor「後端 jobobject（只限制記憶體與程序數；檔案、網路不限制，不算隔離）；真隔離：否」；`/warncli_peek` 還是 `readable: true`。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 4.2 jobobject 的限制真的生效（用 `jobprobe`，沒有警告的假 pack）

設定同 W2（`mem_mb: 256`、`max_procs: 8`）。裝 `jobprobe`（沒有警告，不用 `--accept-warning`）。

- [ ] **J1 正常指令照跑**：console 打 `/jobprobe_ok` → 回 `ok`。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **J2 記憶體上限**：console 打 `/jobprobe_hog`
  - 預期：回「MemoryError（上限生效）」或指令失敗（程式被結束）；**不會**回「配到了 … bytes（不該發生）」。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **J3 程序數上限**：console 打 `/jobprobe_spawn`
  - 預期：回「開到 N 個子程序；OSError …」，N 明顯小於 20、不超過 8（`max_procs`；探針自己也算一個程序，
    Windows 的 venv `python.exe` 還會多開一個真正的 Python，所以 N 可能只有 3～7）；**不會**回「沒有被擋（不該發生）」。
  - 結果：＿＿＿＿　N＝＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **J4 收尾**：J3 跑完 10 秒後，工作管理員（或 `Get-Process python`）裡沒有 `jobprobe` 留下來的子程序。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **J5 設回 auto 不受影響**：`policy.sandbox` 拿掉、重開，`/jobprobe_hog` 這次**會**回「配到了」（沒有限制，跟 doctor 說的一致）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 4.3 帶警告的 pack 的「這台實況」（S1、S4）——沒有容器引擎時

設定回到預設（`auto`）。PATH 上**沒有** podman、docker（`where.exe podman docker` 都找不到；有的話這一節改到 4.4 之後、暫時從 PATH 拿掉再做）。

- [ ] **S1-a 終端機安裝報告**
  - 步驟：`python -m synox install warncli.synoxpack`（不加 `--yes`）、`warnpy.synoxpack`、`warnbox.synoxpack` 各一次，看印出來的報告。
  - 預期：每一個都在「⚠️ 這個工具的作者標了 1 個警告」那幾行**正下方**多一行「ℹ️ SYNOX 查這台的實況：…」，而且紅字：
    - `warncli`：「這台沒有可用的隔離，這個工具會以你的權限直接執行（讀得到你的檔案、連得到網路）」
    - `warnpy`：「這是 Python 工具，在 SYNOX 自己的程序裡跑：沒有任何後端（沙盒、容器）能把它關起來…」（S4）
    - `warnbox`：「這個工具有提供容器（需要 podman 或 docker，這台沒偵測到）：現在用不了容器，這台沒有可用的隔離…」
    - 三個都**沒有**「已在 sandbox」「已隔離」「安全」這類字。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **S1-b 網頁安裝報告**：開 SYNOX，網頁「設定 → 功能與安裝」拖進同三個檔。
  - 預期：每條警告的勾選框下面一行同樣的字（紅色）；勾完照樣能裝（`warnpy` 也能裝＝S4 不拒裝）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **S1-c 設定頁那一列**：裝好後看「🧩 功能與安裝」的清單。
  - 預期：三個工具的紅色警告標記下面各有「ℹ️ SYNOX 查這台的實況：…」（跟 S1-a 一樣的意思，`warnbox` 這時寫「目前選「不用容器」」或「沒偵測到」）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **S1-d doctor 與 `packs status`**：`python -m synox doctor --offline`、`python -m synox packs status`。
  - 預期：每個帶警告的工具，警告那行下面一行實況；`plaincli`、`jobprobe` 那幾行**跟這個版本之前一樣**（拿上一版 SYNOX 跑同一份資料比對，或對照 S1-g）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **S1-e 給 AI 的清單**：開過一次 SYNOX（或 console）之後，打開 `data/agent_index.json`。
  - 預期：`warncli`、`warnpy`、`warnbox` 有 `isolation` 欄位（短句，例如「沒有隔離，以使用者的權限執行」「Python 工具，沒有任何後端能把它關起來…」）；
    `plaincli`、`jobprobe` **沒有** `isolation` 這個鍵。（能力清單裡「〔實況：…〕」的位置由自動測試 `test_agent_index_built_with_note` 驗；這裡只看檔案。）
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **S1-f 真的 AI 不會說成「已在沙盒」**（有本地模型或雲端模型才做；沒有就寫略過）
  - 步驟：對 AI 說「用 warncli 幫我看一下」，**核准卡出現時按取消**。
  - 預期：AI 轉述警告；如果它提到沙盒，說法跟實況一致（沒有隔離），不說「已經在沙盒裡」。記下模型名稱。
  - 結果：＿＿＿＿　模型：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **S1-g 沒有警告的 pack 完全不變**
  - 步驟：用上一個版本（這個分支合併前的 commit）跟這個版本，各裝一次 `plaincli`，存下 `install`（不加 `--yes`）的輸出、`doctor --offline` 中 `plaincli` 那一段、`/api/settings` 裡 `plaincli` 那一列（瀏覽器開發者工具的 Network 分頁）。
  - 預期：兩個版本逐字相同（時間、路徑以外）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 4.4 有 podman 或 docker 時（Docker Desktop；沒有就整節寫「略過：沒有容器引擎」）

- [ ] **C-1 偵測到引擎時的安裝報告**
  - 步驟：`python -m synox install warnbox.synoxpack`（不加 `--yes`）。
  - 預期：實況那一行「這個工具有提供容器（需要 podman 或 docker，這台已偵測到 docker）：在下面「🧱 執行環境」選「用容器」才會在容器裡跑；不選的話，這台沒有可用的隔離…」；「🧱 執行環境」那段顯示 docker ✅。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **C-2 選容器之後真的在容器裡跑**
  - 步驟：照交接書 3.4 準備映像，`python -m synox install warnbox.synoxpack --yes --runtime container --accept-warning vendor_no_security_guarantee`；doctor；console 打 `/warnbox_peek`。
  - 預期：doctor 那個工具寫「🧱 容器（docker）」＋實況「SYNOX 會用 docker 的容器跑這個工具（只掛它自己的資料夾，沒宣告網路就斷網）」；
    `/warnbox_peek` 回 `readable` 不是 `true`（容器裡看不到你家目錄的假檔）、`cwd` 是 `/pack`。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **C-3 網路旗標生效**：console 打 `/warnbox_net`。
  - 預期：回「連不到（OSError …）」。（`warnbox` 沒宣告 network ＝ `--network none`。）
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **C-4 容器旗標的其餘項目**：照 [container-verification.md](../handoff/container-verification.md) 的「Windows 實驗室機器」那一節做（C1–C7、C10、C13–C15），把結果填在那份或這裡的備註。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **C-5 切回「不用容器」**：`python -m synox packs runtime warnbox host`；doctor；`/warnbox_peek`。
  - 預期：實況改成「這個工具有提供容器（需要 podman 或 docker，這台已偵測到 docker），目前選「不用容器」：這台沒有可用的隔離…（改用容器：python -m synox packs runtime warnbox container）」；`/warnbox_peek` 回 `readable: true`。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 4.5 沒有 podman／docker 時的降級與訊息

- [ ] **D-1 選了容器、引擎不見了**
  - 步驟：C-2 之後（`runtime` 是 container），開一個新的 PowerShell，把 docker 從這個視窗的 PATH 拿掉（`$env:PATH = ($env:PATH -split ';' | ? { $_ -notmatch 'Docker' }) -join ';'`），在這個視窗跑 doctor 與 `packs status`，再開 console 打 `/warnbox_peek`。
  - 預期：「容器引擎：podman —、docker —」；這個工具寫「🧱 ⚠️ 選了容器，但這台找不到 podman 或 docker…：退回這台的沙盒後端」；
    實況「選了容器，但這台沒偵測到 podman 或 docker：這台沒有可用的隔離，這個工具會以你的權限直接執行…」；`/warnbox_peek` 照跑而且 `readable: true`（跟實況一致）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 4.6 伺服器模式（S2）

用交接書的「伺服器版」`config.json`（`mode: server`）。Windows 上伺服器版的 `auto` 也是 none。

- [ ] **S2-a 非擁有者看不到、叫不到**
  - 步驟：裝 `warncli`、`warnpy`、`plaincli`（安裝時選 trust core：`--trust core`）。`python -m synox console`（擁有者）打 `/user_role 2 member`，結束；
    `python -m synox console --as 2`，打 `/help`、`/warncli_ok`、`/warnpy`、`/plaincli_ok`。
  - 預期：使用者 2 的 `/help` 裡**沒有** `warncli`、`warnpy`；叫它們被拒（沒有這個指令或沒有權限）；`/plaincli_ok` 照常回 `ok`（沒有警告、core：不受影響）。
    doctor 這兩個工具寫「🔐 只對擁有者開放：作者標了「官方不保證安全」…」。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **S2-b 擁有者照用**：擁有者 console 打 `/warncli_ok`、`/warnpy` → 照常回應。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **S2-c 有容器就給成員**（有 docker 才做）：`warnbox` 用容器裝（同 C-2，加 `--trust core`），使用者 2 打 `/warnbox_ok` → 回 `ok`；doctor 沒有「只對擁有者開放」。拿掉引擎（D-1 的作法）再看 → 又變回只給擁有者。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **S2-d 個人版不受影響**：`mode` 改回個人版（拿掉 `mode`），重開；doctor 這幾個工具**沒有**「只對擁有者開放」這一行（個人版本來就只有擁有者在用）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 4.7 Windows MXC 探測結果的解讀（只讀，不下載）

SYNOX **還沒有** MXC 後端（只有研究時的探測紀錄）。這一節只確認「SYNOX 說的跟這台的條件對得上」。

- [ ] **M-1 只讀盤點**
  - 步驟：`powershell -ExecutionPolicy Bypass -File docs\lab\tools\windows-sandbox-probe\win-env-probe.ps1`（SYNOX 自己的只讀腳本：不安裝、不改設定、不連網）。打開它寫的 `win-env-probe-result.json`。
  - 預期：記下 Windows 版本、`EditionID`、build、build 是否 ≥ 26200.9278（MXC 最低）；`ProductName` 寫「Windows 10」不代表是 Windows 10，看 build。
  - 結果：＿＿＿＿　build：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **M-2 SYNOX 的說法不會因為「這台可以跑 MXC」就變成「有隔離」**
  - 步驟：同一台跑 doctor；看 `warncli` 的實況。
  - 預期：不管 M-1 的 build 夠不夠，doctor 都是「真隔離：否」，實況都是「這台沒有可用的隔離…」（因為 SYNOX 還沒有 MXC 後端）。如果出現「MXC」「已隔離」，記失敗。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **M-3（預設略過）真的跑 MXC 探針**：要用 Microsoft 的 `wxc-exec.exe`（從 npm 套件取出的執行檔）。**這是執行下載來的程式，預設不做**；要做必須擁有者另外明確同意，照 `docs/lab/tools/windows-sandbox-probe/README.md` 的作法。
  - 結果：略過（擁有者未同意）／＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

## 五、Linux（伺服器版；有 Linux 機器才做，沒有就整節寫「略過：沒有 Linux」）

`config.json` 用伺服器版。先裝 `bubblewrap`（套件管理員，要擁有者同意）；`python -m synox doctor --offline` 應該寫「後端 bwrap…；真隔離：是」。

- [ ] **L-1 bwrap 的實況**：裝 `warncli`（`--trust core`）。
  - 預期：安裝報告與 doctor 的實況「SYNOX 會用 bwrap 把它包起來跑（只看得到宣告的資料夾，沒宣告網路就斷網）」，不是紅字；`/warncli_peek` 回 `readable` 不是 `true`（跟實況一致）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **L-2 S2 有真隔離就給成員**：使用者 2（`/user_role 2 member`）`/warncli_ok` → 回 `ok`。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **L-3 python 工具有 bwrap 也只給擁有者**：裝 `warnpy`（`--trust core`）；使用者 2 看不到、叫不到；實況是 Python 那一句（紅字）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **L-4 沒有 bwrap**：`policy.sandbox.backend` 寫 `bwrap`，但用一個 PATH 裡沒有 bwrap 的環境（`env PATH=/nonexistent:/usr/local/bin python -m synox doctor --offline`，或先移除 bubblewrap）。
  - 預期：doctor「⚠️ 設定了 bwrap，但這台找不到 bwrap」；`warncli` 實況變回「這台沒有可用的隔離…」；使用者 2 看不到 `warncli`。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
- [ ] **L-5 容器（podman）**：同 4.4 的 C-1～C-5、4.5 的 D-1，引擎換 podman；另外照 container-verification.md 第 3、4 節做。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

**macOS（有的話）**：`auto` 一律 none（不是 Linux）。做 W1、S1-a～S1-e、S1-g；有 Docker Desktop 再做 C-1～C-3、D-1。結果寫在備註。

## 六、驗收紀錄

| 輪次 | 日期 | SYNOX commit | 機器（只寫作業系統與版本、有無 podman／docker） | 通過／失敗／略過 的項目 | 全部通過？ | 驗證者 |
|---|---|---|---|---|---|---|
| 1 | | | | | | |

備註（略過的原因、擁有者是否接受略過）：
