# 開發指南：從零開始到交 PR、開發 pack、改核心的規則

給要改 SYNOX 的人（或 AI）。先讀過 [HANDOFF.md](HANDOFF.md) 的全貌。指令以 **Linux（含雲端容器、Dev Container、WSL）** 為主，
Windows 寫法列在每段後面。**整個流程不需要任何真的金鑰、token 或帳號。**

- [1. 需要什麼](#1-需要什麼)
- [2. clone 與建環境](#2-clone-與建環境)
- [3. 跑測試](#3-跑測試)
- [4. 不用金鑰的開發設定](#4-不用金鑰的開發設定)
- [5. 開分支、commit、交 PR](#5-開分支commit交-pr)
- [6. 開發 pack 的完整流程](#6-開發-pack-的完整流程)
- [7. 改核心的規則](#7-改核心的規則)
- [8. 交件前檢查表](#8-交件前檢查表)

---

## 1. 需要什麼

| 東西 | 必要？ | 用在哪 |
|---|---|---|
| Python **3.11 以上**（`pyproject.toml` 的 `requires-python`）、`venv`、`pip` | 必要 | 全部 |
| git | 必要 | clone、`tests/test_prepublish_check.py`（沒有 git 就略過） |
| 能連 PyPI | 必要（裝相依時） | `requests`、`cryptography`、`websocket-client`、`pytest` |
| 能連 github.com | 選用 | `pip install -e ".[llm]"`（ntu_easy_llm 是 GitHub release 的 wheel，不在 PyPI） |
| Node.js | 選用 | `tests/js/*.js`（網頁前端的測試；沒有 node 就略過那幾個） |
| SYNOX_Libs（工具庫）的 clone | 選用 | 少數整合測試（設 `SYNOX_LIBS=<資料夾>`，沒有就略過） |
| tkinter＋螢幕 | 選用 | 安裝精靈與提醒視窗的畫面測試（沒有就略過） |

## 2. clone 與建環境

```bash
git clone <SYNOX 這個 repo 的網址> SYNOX       # 已經在 repo 裡（雲端 session 通常是）就跳過
cd SYNOX
git checkout dev                               # 開發主線是 dev；main 只放正式版
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"              # 把 src/ 與 vendor/ 兩個來源目錄都裝成 editable，外加 pytest
# 選用：python -m pip install -e ".[llm]"      # 用 API 金鑰的 AI 介面卡要的 ntu_easy_llm（要能連 github.com）

export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
export SYNOX_NO_BANNER=1 SYNOX_NO_BROWSER=1    # 不印歡迎畫面、不自動開瀏覽器
python -c "import synox, isdtelekit; print(synox.__version__, synox.__file__)"   # 確認 import 的是這份 src/
```

**Windows（PowerShell）**：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'          # 主控台是 cp950 時一定要，不然印 emoji 會當掉
.venv\Scripts\python.exe -m pytest -q
```

**同一台機器有好幾份 checkout（git worktree）時**：editable 安裝只指向**一份** `src/`。在別的 worktree 用同一個 venv，要先把那份放到前面，
並確認印出來的路徑是對的：

```bash
export PYTHONPATH="$PWD/src:$PWD/vendor"          # Windows：$env:PYTHONPATH="$PWD\src;$PWD\vendor"
python -c "import synox; print(synox.__file__)"
```

Dev Container（VS Code）：用 `.devcontainer/` 打開就是上面這套（Python 3.11、環境變數已設好）。容器跑 SYNOX 本體見 [docker.md](docker.md)。

## 3. 跑測試

```bash
python -m pytest -q -p no:cacheprovider                   # 全部（約 3800 個；幾分鐘到十幾分鐘）
python -m pytest -q tests/test_command_tree.py            # 只跑一個檔
python -m pytest -q -k "pack and sign"                    # 照名字挑
```

**測試的規矩**（[AGENT.md](AGENT.md) invariant 7、10、14、15 等）：不連網、不開埠、不連 Telegram、不叫真的 `claude`、不真的 pip／npm install、
不執行 podman／docker／bwrap、不開瀏覽器。需要外面的東西一律用假的（假 session、假 opener、假 runner、假 kernel32、假 Popen、假時鐘）。
新的測試檔建議 `pytestmark = pytest.mark.usefixtures("no_sockets")`（`tests/conftest.py`；另有 `no_subprocess`）。

**唯一會開埠的測試**：`tests/test_web.py::test_port_already_in_use_is_a_bind_failure` 會在 127.0.0.1 暫時 listen 一個埠再關掉。
環境不允許開任何埠時加 `--deselect tests/test_web.py::test_port_already_in_use_is_a_bind_failure`。

**先記基準線**：動手之前，在沒改過的 `dev` 上跑一次全部，把失敗清單存起來；之後只看「新多出來的」失敗。
Linux 上會**略過**或**已知失敗**的，原因都跟你的改動無關：

| 情況 | 會怎樣 | 為什麼 |
|---|---|---|
| Windows 專屬：DPAPI、登錄檔（`.synoxpack` 檔案關聯）、junction、Windows PowerShell | 略過（`skipif(sys.platform != "win32")`） | Linux 沒有這些 |
| 沒有 tkinter 或沒有螢幕 | 略過（`no display`） | 安裝精靈、教學、提醒視窗的畫面測試 |
| 沒有 node | 略過 `tests/js/*` 對應的測試 | 前端 JS 測試用 node 跑 |
| 沒有工具庫（`SYNOX_LIBS`） | 略過 `test_empty_host`、`test_smoke_real`、`test_sdk_p2_secret` 的整合測試 | 工具的正本在另一個 repo |
| 沒裝 ntu_easy_llm | `tests/test_llm.py` 幾個 openai／anthropic／gemini 的測試**失敗**、`test_vision` 有兩個略過 | 介面卡經 ntu_easy_llm 組請求；裝 `.[llm]` 就會過 |
| 幾個寫死 Windows 路徑規則或行為的測試 | **失敗** | 例：`C:\` 開頭算不算絕對路徑、`.synoxpack` 的登錄檔、程式名字怎麼顯示 |

2026-11-18 在 Windows 的實測是「3813 過、16 略過」（略過一個會開埠的測試）。2026-11-14 在 Linux 雲端的實測是「14 個失敗、其他全過或略過」，清單在 [handoff/2026-11-14-session-handoff.md](handoff/2026-11-14-session-handoff.md) 第 4 節。
那之後 repo 又改了很多，**這張清單可能已經過期**——以你自己記的基準線為準；有疑問就在 PR 裡把失敗清單貼出來。

其他常用的檢查：

```bash
python scripts/eval_assistant.py --split all       # 對話助理的離線評測（照劇本重放、不叫真的 AI；evals/assistant/README.md）
python -m synox doctor --offline                   # 健康檢查（不打 AI）
python scripts/prepublish_check.py --worktree-only # 公開前檢查：密鑰、本機路徑、個人信箱、不該提交的檔（只看目前的檔案）
python scripts/clean_room_check.py                 # 在暫存資料夾、清掉這台的環境變數與路徑後跑一遍
python scripts/release.py check                    # 版本一致、SDK 單檔版跟正本一樣（發版前；平常改 SDK 時也可以跑）
```

改到發佈清單或已發佈頁面時至少再跑：`tests/test_artifact_registry.py tests/test_clean_room.py tests/test_clean_room_check.py tests/test_release_layout.py`。

## 4. 不用金鑰的開發設定

| 想做的事 | 怎麼做 |
|---|---|
| 在終端機跟 SYNOX 講話（不連 Telegram、不連網） | `python -m synox console --llm fake`。沒有 `config.json` 時自動用示範設定（擁有者 id 1、假 AI）。`--as 555` 換成別人；在裡面 `!N` 按第 N 顆按鈕、`:as <id>` 換身分、`:q` 離開 |
| 不要把資料寫進 repo 資料夾 | `export SYNOX_HOME=/tmp/synox-dev`（SYNOX 資料夾改成那裡：`config.json`、`data/`、`packs/` 都在那邊）。`data/` 與 `config.json` 本來就在 `.gitignore` |
| 開網頁介面（只用網頁、假 AI） | 在 SYNOX 資料夾寫一份 `config.json`：`{"owner_id": 1, "llm": {"kind": "fake"}, "vault": {"mode": "file"}}`，然後 `python -m synox run --no-browser`，另一個終端機 `python -m synox open` 拿擁有者的一次性登入連結（網頁在 `http://127.0.0.1:8830/`）。**這會開埠**；用完 Ctrl+C 或 `python -m synox stop` |
| 假 AI 照劇本回話（測試裡） | `synox.llm.fake.FakeAdapter(script)`；`tests/conftest.py` 的 `make_bot(script=…)` 直接幫你接好 |
| 假時鐘、同步執行背景任務 | `runtime.of(app).use_fakes(clock=…, now=…, spawn=lambda fn, name: fn())`（[adr/0001](adr/0001-runtime-loop-heartbeat-mother-session.md)） |
| 整支 SYNOX 在記憶體裡跑（測試） | `make_bot(...)`：測試用的 pack（`tests/fixtures/packs`）＋真的保管箱加密＋假通道 `FakeChannel`＋SDK 的 `BotHarness`；`bot.say(user_id, "/指令")`、`bot.talk(...)`（等 AI 那一輪做完）、`bot.press(...)` |
| 假的本地模型伺服器、MCP、HTTP | 換 opener／session（`tests/test_local_llm.py`、`tests/test_mcp_http.py`）；MCP stdio 用本機 Python 子程序（`tests/test_mcp_stdio.py`） |
| 主金鑰 | Linux／macOS 一律 `vault.mode = "file"`（明文的 `data/.synox.key`，開發用沒關係）；Windows 預設 DPAPI |

真的 Telegram、Discord、AI 供應商、外部服務的煙霧測試**只在擁有者準備的電腦上做**（[handoff/](handoff/README.md)）；雲端 session 不做。

## 5. 開分支、commit、交 PR

1. **從最新的 `dev` 開分支**：`git fetch origin && git switch -c feat/<主題> origin/dev`。分支名 `feat/…`（新功能）、`fix/…`（修錯）、`docs/…`（只有文件）。
2. **先跑一次測試記基準線**（第 3 節）。
3. **小步 commit**：一個 commit 做一件事；訊息第一行寫做了什麼（英文或中文都可以），內文寫**為什麼**、做了什麼決定。
   不要 commit `config.json`、`.env`、`data/`、`*.enc`、`packs.lock`、`*.pem`、任何真的 token 或個人資料。
4. **使用者看得到的改變**：在 `CHANGELOG.md` 最上面加（或接著寫）一節 `## 未發佈（<分支或主題>）`，用白話寫「改了什麼、使用者要不要做什麼」。
   發版時 `scripts/release.py bump` 會把這些節收進有版本號的一節（[versioning.md](versioning.md) 第 3 節）。**不要自己改版本號**。
5. **文件**：改了行為就改對應的文件；新文件要登記在 [README.md](README.md)（總目錄）。[ecosystem.md](ecosystem.md)「文件維護清單」列了哪些文件彼此相關。
6. **交件前**：第 8 節的檢查表。
7. **開 PR 到 `dev`**，照 `.github/pull_request_template.md` 填：做了什麼與為什麼、貢獻者同意書那一句（[../CONTRIBUTING.md](../CONTRIBUTING.md)）、
   測試結果（全過，或「基準線之外沒有新失敗」並列出）、安全自檢；**沒在 Windows／真機上試過的東西列出來**。
   不要自己合併、不要直接推 `dev` 或 `main`。

## 6. 開發 pack 的完整流程

### 6.1 新的 pack 放哪個 repo

| 你在做的 | 放哪 |
|---|---|
| 給大家用的官方工具（記帳、筆記、接某個服務…） | **SYNOX_Libs**（工具庫，另一個公開 repo；網址在 [../README.md](../README.md) 頂端）：`packs/<name>/`，照那個 repo 的 README 與它自己的 ADR 0001（工具庫與 SDK 相依）打包進 `index.json` |
| 外觀包（`kind=theme`） | 一樣放 SYNOX_Libs（衣櫃） |
| 教別人怎麼寫的範例 | 這個 repo 的 `examples/`（Apache-2.0；`tests/test_examples.py` 會檢查） |
| 只給 SYNOX 自己的測試用 | `tests/fixtures/`（`tests/fixtures/packs/` 的 money／notes 是凍結的複本，**不加功能**） |
| 自己用、或給朋友的 | 你自己的地方；打成 `.synoxpack` 直接給人 |

**SYNOX 本體不再收工具**（`packs/` 出廠是空的、`loader.BUNDLED` 是空的；[AGENT.md](AGENT.md) invariant 13）。新功能如果是「一個工具」，就做成 pack。
只有系統層的東西（提醒、排程、通知、教學、說明、權限、安裝流程）才改核心。

### 6.2 規格

- 從 [tools.md](tools.md) 開始：三條接入路（`kind=cli` 首選、`python`、`mcp`）怎麼選、十行入門、權限欄位（`access`、`capabilities`、`surfaces`、`data`、每個指令的 `effect`／`ai`／`confirm`）、
  secret、確認來回、環境建置、升級、測試、**安全自檢表**。
- 每個欄位的完整規則：[pack-format.md](pack-format.md)。Python SDK（`@tool`、`serve()`、`secret()`、`fail()`…）：[sdk.md](sdk.md)。
- 給 AI 的登記（pack.json 的 `agent` 區塊、`requires.packs`）：[adr/0030](adr/0030-tool-registration-index.md)。
- 宣告 SDK 版本：`requires.sdk`（`synox-sdk init` 會寫）；SDK 的版本只寫在 `src/synox/sdk/author.py` 的 `SDK_VERSION`。

### 6.3 寫、試、檢查、打包（SDK 指令）

`pip install -e ".[dev]"` 之後有 `synox-sdk` 指令；沒有就用 `python -m synox.sdk …`，一樣。

```bash
synox-sdk init --from tool.py --name hello --title "👋 打招呼"   # 從 @tool 函式產生 pack.json＋SKILL.md
synox-sdk init <資料夾> --kind cli --name hello                    # 不用 @tool 的範本（任何語言）；--panel 才多一個面板
synox-sdk run greet Amy style=formal                             # 本機試跑一個 cli 指令，照 SYNOX 的路走（不用開 SYNOX）
synox-sdk check <資料夾>                                          # 第 1 關（宣告）＋第 2 關（靜態掃描）＋信任層級；結束碼 2＝一定裝不了
synox-sdk zip <資料夾>                                            # 先 check，再打包成 dist/<name>-<version>.synoxpack
```

### 6.4 在 SYNOX 裡試

**沒有經過安裝頁（沒有 `packs.lock` 那一筆）的 pack 一律不載入**（[adr/0028](adr/0028-pack-signatures-official-badge.md) §4）。兩種試法：

1. **直接讀你的資料夾**（開發時方便）：`config.json` 加 `"packs": {"dirs": ["<你的 pack 資料夾，或裝了很多 pack 的資料夾>"]}`，然後
   `python -m synox packs lock --approve <name>`（跑第 1、2 關、印報告，過了才鎖）。**改了檔案要再 approve 一次**，不然雜湊對不上、不載入。
   `python -m synox packs status` 看每個 pack 的狀態與原因。
2. **照使用者的方式裝**：`python -m synox install dist/<name>-<version>.synoxpack --yes`（T2 要加 `--trust-publisher "<pack.json 的 publisher>"`）。
   同名再裝＝升級（會列「改了什麼」），退回 `python -m synox packs rollback <name>`。

然後 `python -m synox console --llm fake` 打你的指令試。用 `SYNOX_HOME` 指到暫存資料夾，就不會弄髒 repo。

### 6.5 測試

- 你的邏輯用你習慣的測試框架直接測（`@tool` 函式就是普通函式）。
- 在 SYNOX 這邊要測「pack 在 host 裡的行為」：參考 `tests/test_examples.py`、`tests/test_empty_host.py`；`make_bot(pack_dirs=…)` 會把沒鎖的先鎖起來（`lock_all`）。
- 同樣的規矩：不連網、不開埠、不真的 pip／npm、不執行下載來的東西。測 T2 用位元組造假檔頭（`tests/test_t2_trust.py` 的 `FAKE_EXE`），不放真的執行檔。

### 6.6 簽章與交件

- 簽章（`pack.sig.json`，Ed25519）證明「檔案跟簽的時候一樣」。**✅ 官方**只能由擁有者的工具鑰匙簽；那把私鑰只在擁有者手上，
  永遠不會出現在任何 repo、CI 或雲端 session。（現在程式裡的官方公鑰 `OFFICIAL_PACK_PUBLIC_KEYS` 還是空的，所以所有工具都顯示「⚠️ 不是官方」，這是正常的。）
- **外部作者、雲端 session 交件時不簽、也不附 `pack.sig.json`**：交原始碼（pack 資料夾）到 SYNOX_Libs 的 PR。官方工具由擁有者在發佈時 build、簽、重算雜湊（[signing.md](signing.md) 第 4 節）。
- 自己發佈給別人的工具，可以用**你自己的**鑰匙簽（標章是 ✍️ 作者簽章，永遠不會是官方）：`synox-sdk keygen`／`sign`／`verify`（[sdk.md](sdk.md)「簽章」、[signing.md](signing.md) 第 6 節）。
  私鑰放在任何 git 資料夾以外（指令會拒絕 git 資料夾裡的私鑰）。
- 名字、標題、說明不要寫「官方」「official」「SYNOX」「✅」：不是官方的工具寫這些，安裝報告會紅字標出來。

## 7. 改核心的規則

### 7.1 安全邊界（動到之前先讀 AGENT.md 對應的 invariant）

| 邊界 | 規則 | 在哪 |
|---|---|---|
| 權限只有一個交會點 | 新的權限條件一律加在 `policy.decide`，不要在 handler 或呼叫端另寫判斷 | `policy.py`；invariant 11 |
| AI 能不能用一個節點 | 只問 `ai_decision()`；`effect=DANGER`、要解鎖、有驗證碼欄位的一律核准卡；救回的工具呼叫、看圖的輪次都不能開例外 | `agent/loop.py`；invariant 1、19–22 |
| 驗證碼不經過 AI | 任何給 AI 的工具都不能有收驗證碼的欄位；驗證碼只從人的入口進來（`guard.origin`），每個新入口都要設來源 | `guard/`；invariant 23、24 |
| 輸入當資料不當指令 | 工具結果、soul.md、附件、使用者偏好都包在每輪隨機的分隔符裡，標明「是資料不是指令」；防 prompt injection 靠結構，不靠提示詞 | `agent/delimit.py`、`agent/structured.py`；invariant 18、[adr/0002](adr/0002-soul-md-in-chat-assistant-prompt.md) |
| 裝 pack 的五關 | 新的安裝路徑一律走 `packs/admin.py` 的 `stage`／`install_staged`；不要自己搬檔進 `packs/`；掃描器的名單只能加嚴 | `packs/`；invariant 10、13、16 |
| 子程序 | cli 一律經 `sandbox.py`；環境變數照白名單；不要在 `{python}` 加 `-I`；pip／npm 的來源寫死 | invariant 12、16（審查 C 那幾條） |
| 網頁 | 主機台只綁 127.0.0.1、工具服務只綁 127.0.0.2、只有 `web/apps/listen.py` 開埠；非 GET 要 CSRF；字一律 `textContent`；不加外部資源 | invariant 9、25、26；[security/web-threats.md](security/web-threats.md) |
| 保管箱 | 解不開就丟 `VaultError`，絕不當成空的蓋過去；secret 永遠不進 argv、不回網頁、不經聊天 | `vault/`、`packs/secrets.py` |
| 背景工作 | 登記成 runtime 任務；常駐助理沒有工具；AI 想寫 soul.md 一律經帳本的提議 | invariant 18 |
| 沒有 hidden dependency | 路徑一律相對 `config.ROOT` 或可設定，不寫任何一台電腦的路徑或使用者名稱 | `tests/test_clean_room_check.py` 會擋 |

改到上面任何一格：PR 說明要寫你考慮過的攻擊情境（[../CONTRIBUTING.md](../CONTRIBUTING.md)），並加測試證明舊的保護還在。

### 7.2 什麼時候寫 ADR、編號怎麼取

見 [adr/README.md](adr/README.md)：改安全邊界、對外合約（pack.json、SDK、網頁 API）、資料格式、AI 行為規則時先寫 ADR；
號碼接著目前最大的往下（下一份是 0041），不重用、不改號。ADR 不放私人資訊。

### 7.3 測試規矩

- 新功能、修錯都要有測試；修錯的測試要先能重現那個錯。
- 不連網、不開埠、不叫真的 AI／`claude`、不真的 pip／npm、不執行 podman／docker／bwrap／systemd-run、不碰真的電源設定與登錄檔（登錄檔只寫拋棄式的 `Software\SYNOX-test-<亂數>`）。
- 測試資料一律假的：佔位的 id（例 `123456789`、`555`）、`example.com` 信箱、假 token（一看就是假的；需要的話那一行加 `prepublish-check: allow`）。
- 網頁測 `WebUI.route()`／`handle()`，不開真的伺服器。

### 7.4 版本、CHANGELOG、alpha

- 版本號只有三種格式：`X.Y.Z`、`X.Y.Z-beta.N`（外部測試）、`X.Y.Z-alpha.N`（**內部測試版一律用 `-alpha.N`**）。升哪個號、分支（dev → release/X.Y.Z → main）、tag 規則在 [versioning.md](versioning.md)。
- 版本號、tag、release 由擁有者決定；PR 只寫 CHANGELOG 的「未發佈」節。
- 動到 SDK 介面（pack.json 格式、子程序環境變數與信封、kind=python 的介面）：升 `SDK_VERSION`（不相容升 MINOR），重產 `sdk/synox_sdk.py`（`python scripts/build_synox_sdk.py`），
  更新 [pack-format.md](pack-format.md)、[sdk.md](sdk.md)、[tools.md](tools.md)、`examples/*/pack.json` 的 `requires.sdk`，並請 SYNOX_Libs 重新打包。

## 8. 交件前檢查表

```
□ 分支從最新的 dev 開；只 commit 在自己的分支
□ 全部測試：基準線之外沒有新失敗（列出失敗清單與原因）
□ 新功能／修錯有測試；測試不連網、不開埠
□ python scripts/prepublish_check.py --worktree-only 沒有發現（或每一筆都說得出為什麼可以）
□ git diff 與 commit 訊息自己看過一次：沒有真名、信箱、本機路徑、token、私人專案名、別人的資料
□ 使用者看得到的改變：CHANGELOG「未發佈」一節、相關文件、docs/README.md 的目錄
□ 動到安全邊界：PR 說明寫了攻擊情境；需要的話寫了 ADR
□ PR 說明：做了什麼與為什麼、CLA 那一句、測試結果、沒在 Windows／真機上試過的東西
```
