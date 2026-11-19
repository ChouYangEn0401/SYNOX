# 交辦：沙盒與「帶警告的 pack」——在另一台電腦上做真機驗證

> 這份是**交辦單**：給一個完全空白的 session（另一台電腦、docker、雲端都可以），沒有對話紀錄、沒有開發機上的檔案，**只讀這份就能開工**。
> 舊的交接書 [sandbox-real-machine.md](sandbox-real-machine.md) 與清單 [../testing/sandbox-real-machine-checklist.md](../testing/sandbox-real-machine-checklist.md) 仍然有效；
> 這份把它們整理成固定的六段，並補上舊交接書漏掉的東西（`warnbox` 的 `net` 指令、用 `scripts/pack_zip.py` 打包、測試基準數字）。兩邊說法不同時，以這份為準。

---

## 1. [狀態]

**待做**（2026-11-19 寫）。

| 項目 | 值 |
|---|---|
| 要驗證的程式 | `dev` 分支；寫這份時 `origin/dev` 是 `fb29db0`（已含 `3d2325f Merge feat/sandbox-ready`，也就是 S1、S2、S4） |
| 「上一版」（S1-g 比對用） | `2240a5e`（`feat/sandbox-ready` 合併前，`dev` 的第一個父 commit） |
| 誰在做 | 還沒有人接 |
| 卡住的地方 | 無；但有三件事要擁有者先決定才能做完整（見 [§2.4](#24-要擁有者決定的事開工前先看)），沒決定就照預設（略過那幾項） |

接手後把這一段改成「進行中：做到清單哪一項；分支 `docs/sandbox-verify-<YYYYMMDD>`；最新 commit `<hash>`」，卡住就寫「卡住：卡在哪一項、為什麼」。

## 2. [前情提要]

### 2.1 為什麼要做

1. pack 的作者可以在 `pack.json` 標警告（[ADR 0041](../adr/0041-pack-warnings.md)）。最常見的是 `vendor_no_security_guarantee`：「官方不保證安全——建議在 docker 或 sandbox 執行」。
   SYNOX 在每個看得到工具的地方都照樣顯示，第一次啟用要擁有者逐條確認。
2. 那句「建議在 sandbox 執行」是**作者的字**。SYNOX 會不會真的把工具關起來，要看那台電腦有什麼（ADR 0041 §5.2）：

   | 情況 | 實際的後端 | 算不算隔離 |
   |---|---|---|
   | Windows 個人版（預設 `auto`） | none | 不算：工具用使用者帳號的權限跑 |
   | Windows 設 `backend: jobobject` | Job Object | 不算：只限記憶體與程序數 |
   | Windows 設 `backend: appcontainer` | 退回 none | 不算：只有介面 |
   | Windows 11 的 MXC | —— | 還沒有後端（只有研究時的探測結果） |
   | Linux 伺服器版 | bwrap，沒有就 systemd-run | 算 |
   | pack 宣告 `runtime.container`＋安裝時選「用容器」＋PATH 上有 podman／docker | 容器 | 算 |
   | `kind=python` | 在 SYNOX 自己的程序裡跑 | **任何後端都包不到** |

3. 風險是使用者看到「sandbox」就以為 SYNOX 已經幫他關起來了。所以做了三件事（ADR 0041 §5.4、§5.5），**都只在假後端、假 `which` 下自動測過，沒有在真機上驗過**：
   - **S1**：帶警告的 pack，警告下面多一行 SYNOX 自己寫的「ℹ️ SYNOX 查這台的實況：…」（安裝報告、設定頁、doctor、`packs status`、`packs lock`、給 AI 的清單、`data/agent_index.json` 的 `isolation`）。只改顯示。沒有警告的 pack 一個字都不多。
   - **S2**：伺服器版裡，帶 `vendor_no_security_guarantee` 的 cli／mcp stdio 工具算「一定要沙盒」：沒有真隔離（none、jobobject）就只給擁有者；有 bwrap／systemd／容器才給成員；`kind=python` 帶這個 code 一律只給擁有者。個人版不變。
   - **S4**：`kind=python` 帶警告只加紅字（S1 的 python 那一句），**不拒裝**。
4. 寫程式的那台開發機不跑容器、不跑 Job Object 的實際限制、沒有 Linux，所以要另一台電腦。

### 2.2 之前決定了什麼

- 「一律可以安裝」：任何來源的 pack 都可以裝，裝的時候清楚警告（[ADR 0022](../adr/0022-ecosystem-bridge-and-sandbox.md) 的擁有者修正；ADR 0041 §5.4 S4）。所以 S4 只加紅字、不拒裝。
- 實況那一行**任何狀態都不說「已在 sandbox」「已隔離」「安全」**，只說這台現在的設定會怎麼跑（ADR 0041 §5.5）。
- 容器映像在 SYNOX 安裝的第 1 關只收 `docker.io`／`ghcr.io`／`quay.io` 上帶 `@sha256:` digest 的映像。
- Windows 上 AppContainer／MXC 的取捨另有研究，待擁有者決定後再開交辦；**這份不做 Windows 真隔離後端**。

### 2.3 試過什麼、相關文件

| 東西 | 在哪 |
|---|---|
| 設計與分析 | [ADR 0041 §5](../adr/0041-pack-warnings.md)、[ADR 0022](../adr/0022-ecosystem-bridge-and-sandbox.md)、[../sandbox-roadmap.md](../sandbox-roadmap.md) |
| 程式 | `src/synox/sandbox.py`（`isolation_note`、`isolation_line`、`no_guarantee`、`required`、`restricted_reason`、`JobObjectSandbox`、`ContainerSandbox`）；顯示接在 `src/synox/packs/admin.py`、`packs/loader.py`、`doctor.py`、`__main__.py`、`web/server.py`、`web/static/app.html`、`agent/index.py` |
| 自動測試 | `tests/test_sandbox_ready.py`、`tests/test_sandbox.py`、`tests/test_container_sandbox.py`（另有 `tests/test_container.py`、`tests/test_container_install.py`） |
| 真機清單（照它逐項做） | [../testing/sandbox-real-machine-checklist.md](../testing/sandbox-real-machine-checklist.md)（P0–P1、W1–W2、J1–J5、S1-a～S1-g、C-1～C-5、D-1、S2-a～S2-d、M-1～M-3、L-1～L-5、macOS） |
| 容器旗標本身的驗證（C-4、L-5 引用） | [container-verification.md](container-verification.md) |
| Windows 只讀探測的舊結果 | `docs/lab/2026-11-16-windows-sandbox-probe-results.md`、腳本在 `docs/lab/tools/windows-sandbox-probe/` |
| 相關 commit | `3d2325f`（S1、S2、S4 合進 `dev`）、`a4a0dff`（pack 警告 ADR 0041 合進 `dev`） |

### 2.4 要擁有者決定的事（開工前先看）

| 題目 | 沒決定時的預設 |
|---|---|
| [S3：沒有隔離的電腦上要不要預設不執行](open-questions/20261119-121055-s3-warning-default-off-without-isolation.md) | 不影響這次驗證；驗完才決定 |
| [S5：要不要要求帶警告的 pack 宣告 `runtime.container`](open-questions/20261119-121056-s5-require-runtime-container.md) | 不影響這次驗證 |
| [驗證機能不能拉官方 Python 容器映像](open-questions/20261119-134610-verification-container-image.md) | **不拉**：C-1～C-5、D-1、S2-c、L-5 寫「略過：未同意拉映像」 |
| [驗證機能不能裝 bubblewrap／podman／Docker Desktop](open-questions/20261119-134612-verification-machine-installs.md) | **不裝**：只用那台本來就有的；沒有的那幾項寫「略過：沒有 XXX」 |
| [MXC 探針（`wxc-exec.exe`）能不能在驗證機上跑](open-questions/20261119-134611-mxc-probe-on-verification-machine.md) | **不跑**：M-3 寫「略過（擁有者未同意）」 |

## 3. [任務]

### 3.1 要做到的程度（逐條）

1. 照 §4 準備一台驗證機的環境，先跑一次測試記下基準（清單 P0、P1）。
2. 照真機清單**從 P0 做到第六節**，順序就是清單的順序（Windows → Linux → macOS）。每做完一項就把結果寫進清單的結果欄（`通過`／`失敗（一句話原因）`／`略過（原因）`、日期、驗證者代號），**不要最後一起補**。
3. 那台機器沒有條件做的項目（沒有 Linux、沒有容器引擎、擁有者沒同意拉映像），寫「略過：原因」，並在清單第六節的總表與備註寫明。**略過不算通過**。
4. 每一個「失敗」或意外各寫一個紀錄檔（格式見 §6.2），一件一檔。
5. 全部做完寫一份總表（結論先講；每一項一行：通過／失敗／略過＋原因＋紀錄檔名）。
6. 在自己的分支上 commit「填好結果的清單」，照 §6 交回。

**驗收標準**（跟舊交接書第 5 節一樣）：

- 清單每一項都有結果；略過的，擁有者在總表備註明確寫「接受」才算。
- 任何一項「失敗」＝這一批不算驗收完成；修好之後**整節重做**（不是只重做那一項）。
- S1 的字在每一種機器狀態下**都沒有**說成「已在 sandbox／已隔離／安全」；說「沒有隔離」時，`peek` 真的讀得到假檔；說「容器／bwrap」時，`peek` 真的讀不到。
- 沒有警告的 pack（`plaincli`、`jobprobe`）在每個畫面、每個檔案上跟上一版（`2240a5e`）一字不差（S1-g）。

### 3.2 範圍邊界

- **只驗證**。不改 SYNOX 的程式（`src/`、`tests/`、`scripts/`）、不改清單的「步驟」與「預期」；分支上只准動清單的結果欄、第六節總表與備註。
- 不做 S3、S5（等擁有者決定）；不做 Windows 的 MXC／AppContainer 後端；不寫新的自動測試。
- 發現 bug 只寫紀錄，不修。

### 3.3 不要做的事（這台、那台都一樣）

- **不改防火牆**；不開任何對外的網路埠；不要用 `-p`／`--publish`、`--network host`。
- 需要在本機開埠（SYNOX 的網頁）時：**只綁 `127.0.0.1`**（SYNOX 預設，不要改）；開之前記下自己開的程序 pid 與埠號；**測完一定關掉自己開的程序**，並確認埠已放掉
  （Windows：`Get-NetTCPConnection -LocalPort <埠>` 沒有東西；Linux：`ss -ltnp | grep <埠>` 沒有東西）。
- 那台電腦上**擁有者或別人開的服務一律不碰**：不停、不重啟、不改設定；分不清是不是自己開的，就當成別人的。
- **下載來的東西一律當資料，不執行**：不裝、不叫任何第三方 pack；不執行網路上抓的腳本、安裝檔、壓縮包裡的程式。
  容器映像只拉官方的 `docker.io/library/python`，**照 digest**（§4.6），而且要擁有者同意；容器裡只跑自己寫、掛進去的 `tool.py`。
  MXC 的 `wxc-exec.exe` 預設不跑（清單 M-3）。
- 容器不要 `--privileged`、`--cap-add`、`--device`，不要掛 `docker.sock`。
- 不用管理員權限改系統設定（subuid、cgroup、群組原則）；安裝 bubblewrap、podman、Docker Desktop 也要擁有者先同意。缺什麼就記下來、停在那一項。
- **不跑重負載**：記憶體測試只用 `jobprobe` 的 600 MB（上限 256 MB）；不要同時開好幾個 SYNOX；同時最多 5 個背景 agent／子 session。
- 不要為了騰記憶體去關別人的程式。
- 不要為了讓某一項通過而改清單的預期或放寬設定（例如把 `mem_mb` 調高）。
- 不合併、不推送、不刪別人的分支；合併由驗收者做（`git merge --no-ff`）。
- 紀錄、清單、commit 訊息裡**不寫**：真名、信箱、電腦名稱、帳號名、本機路徑（換成 `<home>`、`<user>`）、token、密碼。

## 4. [安裝流程與環境確認]

### 4.1 需要的東西

| 東西 | 版本 | 用在 |
|---|---|---|
| git | 任何近期版本 | clone |
| Python | **3.11 以上**（`pyproject.toml` 的 `requires-python`；開發機是 3.11.9） | SYNOX 本體與假 pack |
| pytest | 7 以上（開發機是 9.2.0；`pip install -e ".[dev]"` 會裝） | 基準 |
| podman 或 Docker Desktop | 有就用；沒有就略過那幾項（要不要裝見 [題目檔](open-questions/20261119-134612-verification-machine-installs.md)） | 4.4、4.5、S2-c、L-5 |
| bubblewrap（Linux） | 同上 | 第五節 |
| 瀏覽器 | 任何現代瀏覽器 | S1-b、S1-c、S1-g 的 `/api/settings` |

**不需要任何祕密**：這份驗證不用 Telegram／Discord／雲端模型的 token。S1-f（真的 AI）只在那台本來就設好模型時才做；要用雲端模型時，金鑰**從那台環境的 secret 讀 `SYNOX_LLM_API_KEY`（或擁有者另外指定的名字）**，不寫進任何檔案、不貼進紀錄；沒有就寫略過。

### 4.2 先記下機器資訊（清單 P0）

```powershell
# Windows（PowerShell）
[System.Environment]::OSVersion.VersionString
(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuild
python --version
podman version; docker version      # 沒有就會說找不到，照實記
```

```sh
# Linux／macOS
uname -srm; head -3 /etc/os-release
python3 --version
podman version || docker version
```

只記作業系統、版本、有沒有 podman／docker；**不記電腦名稱、帳號名、路徑**。

### 4.3 取得程式（用一個專門給驗證用的資料夾，不要用平常在用的 SYNOX）

```sh
git clone <SYNOX 的 repo 網址（交辦時由擁有者給；也就是 docs/handoff/README.md「最短路徑」那一行）> synox-verify
cd synox-verify
git fetch origin
git switch -c docs/sandbox-verify-<YYYYMMDD> origin/dev     # 你的工作分支；只在這裡 commit
git log --oneline -1                                          # 記下 commit（清單 P0）；寫這份時是 fb29db0
python -m venv .venv
# Windows： .venv\Scripts\python -m pip install -e ".[dev]"
# Linux／macOS： .venv/bin/python -m pip install -e ".[dev]"
```

之後指令裡的 `python` 都是這個 `.venv` 的 python。確認 `import` 到的是這個資料夾的程式：

```sh
python -c "import synox; print(synox.__file__)"     # 要在 synox-verify/src/synox/ 底下
```

### 4.4 先跑一次測試，記下基準（清單 P1）

```sh
python -m pytest -q -p no:cacheprovider tests/test_sandbox_ready.py tests/test_sandbox.py tests/test_container_sandbox.py
python -m pytest -q -p no:cacheprovider tests/test_container.py tests/test_container_install.py
```

**參考基準**（來源：2026-11-19 在 `origin/dev`＝`fb29db0` 的暫時 worktree 實際跑出來；Windows 10 build 19045、Python 3.11.9、pytest 9.2.0）：

| 測試檔 | 結果 |
|---|---|
| `test_sandbox_ready.py`＋`test_sandbox.py`＋`test_container_sandbox.py` | **64 passed**（0 failed） |
| `test_container.py`＋`test_container_install.py` | **74 passed**（0 failed） |

- 你那台跑出來的數字**以你自己的為準**寫進 P1；跟上面不同（例如 Linux 上有測試只在某個平台跑）就在回報裡寫出差在哪。
- 有任何 **failed**：先停，照 §6.2 寫紀錄，請擁有者決定；不要往下做。
- 想要全部測試的基準（`python -m pytest -q -p no:cacheprovider`）可以跑一次記下來，但不是必要；全部測試比較重，跑一次就好。

### 4.5 驗證用的 `config.json`（放在 `synox-verify/`；它與 `data/` 都在 `.gitignore` 裡，不會進 git）

個人版：

```json
{"owner_id": 1, "data_dir": "data", "llm": {"kind": "none"}, "vault": {"mode": "file"}}
```

伺服器版（清單 4.6、第五節）：

```json
{"owner_id": 1, "mode": "server", "data_dir": "data", "llm": {"kind": "none"}, "vault": {"mode": "file"}}
```

jobobject（清單 W2、4.2；Windows）：在上面任一份加 `"policy": {"sandbox": {"backend": "jobobject", "mem_mb": 256, "max_procs": 8}}`。

網頁那幾項（S1-b、S1-c、S1-g）：照 README 的進階安裝開 SYNOX（Windows 也可以用 `Setup.bat`）；網頁只綁 `127.0.0.1`。開了就記下 pid 與埠，測完用 `Stop.bat`（或結束那個 pid）關掉，再確認埠已放掉。

### 4.6 假 pack（全部自己寫，放在 repo **外面**，例如家目錄的 `probe/`）

所有假 pack 只用 Python 標準函式庫、不下載任何東西。每個資料夾三個檔：`pack.json`、`SKILL.md`、程式。

**共用的假檔**：家目錄建 `synox-probe-secret.txt`，內容寫 `fake`（`peek` 用它確認「讀不讀得到你的檔案」）。

**`probe/warncli/pack.json`**

```json
{"name": "warncli", "title": "警告探針（cli）", "summary": "只用來驗證警告與沙盒的顯示", "version": "0.1.0",
 "kind": "cli", "skill": "SKILL.md", "group": "warncli", "access": "member", "publisher": "SYNOX-verification",
 "capabilities": ["filesystem:any"],
 "warnings": [{"code": "vendor_no_security_guarantee", "text": "官方不保證安全", "advice": "建議在 docker 或 sandbox 執行"}],
 "cli": {"argv": ["{python}", "./tool.py"], "json_flag": null,
         "commands": [{"name": "ok", "effect": "READ", "default": true, "argv": ["ok"]},
                      {"name": "peek", "effect": "READ", "argv": ["peek", "{path}"], "fields": [{"name": "path"}]}]}}
```

**`probe/warncli/tool.py`**（`warnbox` 也用同一份；`net` 只有 `warnbox` 的 pack.json 有宣告）

```python
import json, os, socket, sys

cmd = sys.argv[1] if len(sys.argv) > 1 else "ok"
if cmd == "peek":
    path = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        with open(path, encoding="utf-8") as f:
            readable = f.read(16) == "fake"
    except OSError as e:
        readable = f"no ({type(e).__name__})"
    message = json.dumps({"readable": readable, "cwd": os.getcwd()})
elif cmd == "net":
    try:
        socket.create_connection(("example.com", 80), timeout=5).close()
        message = "連得到（沒宣告網路卻連得到＝不該發生）"
    except OSError as e:
        message = f"連不到（{type(e).__name__}: {e}）"
else:
    message = "ok"
print(json.dumps({"message": message}))
```

console 裡這樣叫：`/warncli_peek path=<home>/synox-probe-secret.txt`（`<home>` 換成那台的家目錄；Windows 用 `\` 也可以）。
`net` 只往外連一次 `example.com:80`，**不開任何埠**。

**`probe/warnbox/`**：把 `warncli` 整個複製一份，`pack.json` 的 `name`／`title`／`group` 改成 `warnbox`，`cli.commands` 加一條
`{"name": "net", "effect": "READ", "argv": ["net"]}`，再加一欄（`<DIGEST>` 見 §4.7）：

```json
"runtime": {"container": {"image": "docker.io/library/python@sha256:<DIGEST>", "network": false}}
```

**`probe/plaincli/`**：把 `warncli` 複製一份，`name`／`title`／`group` 改成 `plaincli`，**刪掉整個 `warnings` 欄位**。

**`probe/warnpy/pack.json`** 與 **`probe/warnpy/pack.py`**

```json
{"name": "warnpy", "title": "警告探針（python）", "summary": "只用來驗證警告的顯示", "version": "0.1.0",
 "kind": "python", "skill": "SKILL.md", "group": "warnpy", "access": "member", "publisher": "SYNOX-verification",
 "warnings": [{"code": "vendor_no_security_guarantee", "text": "官方不保證安全", "advice": "建議在 docker 或 sandbox 執行"}]}
```

```python
def install(app, pack):
    pack.group.leaf("ok", lambda api, chat, user, args: api.send_message(chat, "ok"), "回 ok", default=True)
```

**`probe/jobprobe/pack.json`** 與 **`probe/jobprobe/tool.py`**（沒有警告）

```json
{"name": "jobprobe", "title": "Job Object 探針", "summary": "只用來驗證記憶體與程序數上限", "version": "0.1.0",
 "kind": "cli", "skill": "SKILL.md", "group": "jobprobe", "access": "member", "publisher": "SYNOX-verification",
 "capabilities": ["subprocess"],
 "cli": {"argv": ["{python}", "./tool.py"], "json_flag": null, "timeout": 60,
         "commands": [{"name": "ok", "effect": "READ", "default": true, "argv": ["ok"]},
                      {"name": "hog", "effect": "READ", "argv": ["hog"]},
                      {"name": "spawn", "effect": "READ", "argv": ["spawn"]}]}}
```

```python
import json, subprocess, sys

cmd = sys.argv[1] if len(sys.argv) > 1 else "ok"
if cmd == "hog":
    try:
        blob = bytearray(600 * 1024 * 1024)
        message = f"配到了 {len(blob)} bytes（不該發生）"
    except MemoryError:
        message = "MemoryError（上限生效）"
elif cmd == "spawn":
    kids, err = [], ""
    try:
        for _ in range(20):
            kids.append(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"]))
    except OSError as e:
        err = f"{type(e).__name__}: {e}"
    for kid in kids:
        kid.wait()
    message = f"開到 {len(kids)} 個子程序；{err or '沒有被擋（不該發生）'}"
else:
    message = "ok"
print(json.dumps({"message": message}))
```

（J5 在 `auto` 下會真的配 600 MB，只配一次、馬上結束；那台可用記憶體不到 2 GB 就先不做 J5，寫略過。）

**每個資料夾的 `SKILL.md`**（`name` 換成那個 pack 的名字）：

```
---
name: warncli
description: 驗證用的假工具
---
```

**打包**：用 SYNOX 自己的腳本（會照安裝時的格式打包，`pack.json` 在第一層）：

```sh
python scripts/pack_zip.py <home>/probe/warncli --out <home>/probe-dist
# → <home>/probe-dist/warncli-0.1.0.synoxpack；其他四個一樣
```

**安裝**（帶警告的要明確確認；伺服器版的項目加 `--trust core`）：

```sh
python -m synox install <home>/probe-dist/warncli-0.1.0.synoxpack --yes --accept-warning vendor_no_security_guarantee
python -m synox install <home>/probe-dist/jobprobe-0.1.0.synoxpack --yes
```

### 4.7 容器映像（只有清單 4.4、4.5、S2-c、L-5 要；要擁有者先同意，見 [題目檔](open-questions/20261119-134610-verification-container-image.md)）

- 只拉這一個官方映像，不 pull、不 run 任何別的映像：

```sh
docker pull docker.io/library/python:3.12-slim          # 或 podman pull
docker image inspect docker.io/library/python:3.12-slim --format "{{index .RepoDigests 0}}"
# → docker.io/library/python@sha256:<64 個 16 進位字>，那 64 個字就是 <DIGEST>
```

- 記下 `<DIGEST>`，寫進回報；之後一律用 `python@sha256:<DIGEST>` 這個寫法（照 digest），不要用 tag。
- 開工前記下那台**本來有沒有**這個映像（`docker image ls docker.io/library/python`），收尾時只刪自己拉的。

### 4.8 開工前確認（全部是「是」才開始）

- [ ] `git log --oneline -1` 是 `origin/dev` 的最新（或擁有者指定的 commit），記在 P0。
- [ ] `synox.__file__` 在驗證資料夾底下。
- [ ] §4.4 的基準跑過、沒有 failed，數字記在 P1。
- [ ] `config.json`、`data/` 在 `git status` 裡**看不到**（被 `.gitignore` 擋掉）。
- [ ] `probe/`、`probe-dist/`、`synox-probe-secret.txt` 在 repo 外面。
- [ ] §2.4 三個題目，擁有者的決定（或「沒決定＝預設」）寫進清單第六節的備註。

## 5. [驗證清單集]

給高水準模型（驗收者）在 merge 前逐項確認。驗收者在自己的電腦 clone 同一個 repo、fetch 接手者的分支即可（不用重做真機驗證）。
**每一項都要實際跑或實際看，列出沒過的項目與留下的問題；沒有全部通過就不准 merge。**

以下 `<base>`＝接手者分支的基底（`git merge-base origin/dev <branch>`），`<branch>`＝接手者的分支。

| # | 檢查什麼 | 指令／怎麼看 | 預期 |
|---|---|---|---|
| V1 | 分支名與基底 | `git log --oneline -1 <base>`；`git branch -r --contains <base>` | 分支叫 `docs/sandbox-verify-<YYYYMMDD>`；基底在 `origin/dev` 上 |
| V2 | 只改了清單 | `git diff --name-only <base> <branch>` | 只有 `docs/testing/sandbox-real-machine-checklist.md`（沒有 `src/`、`tests/`、`scripts/`、`config.json`、`data/`、`_inbox/`、`probe/`） |
| V3 | 沒改清單的步驟與預期 | `git diff <base> <branch> -- docs/testing/sandbox-real-machine-checklist.md` 逐段看 | 只有「結果：」那幾行、`passed`／`N＝`／`build`／`模型` 欄、第六節總表與備註被填；`步驟：`、`預期：` 一個字都沒改 |
| V4 | 每一項都有結果 | `grep -n "結果：＿＿＿＿" docs/testing/sandbox-real-machine-checklist.md`（在 `<branch>` 上） | 沒有輸出（沒有空著的結果欄） |
| V5 | 每一項都打勾 | `grep -n "^- \[ \]" docs/testing/sandbox-real-machine-checklist.md` | 沒有輸出 |
| V6 | 略過都有原因、擁有者有接受 | `grep -n "略過" docs/testing/sandbox-real-machine-checklist.md`；看第六節備註 | 每個「略過」後面有原因；備註裡擁有者對每一個略過寫「接受」（沒寫＝這項不過） |
| V7 | 失敗都有紀錄 | 對照回報裡的紀錄檔清單 | 每個「失敗」都有一份 §6.2 格式的紀錄（一件一檔），檔名在總表那一列 |
| V8 | P0 環境紀錄完整、沒有私人資訊 | 看清單 P0 與第六節總表 | 有作業系統與版本、Python 版本、podman／docker 有無與版本、SYNOX commit；沒有電腦名稱、帳號名、路徑 |
| V9 | P1 基準 | 看 P1 的 passed 數；對照 §4.4 的參考數字 | 寫了數字、0 failed；跟 64 不同的話回報裡有解釋 |
| V10 | 自動測試在驗收者這邊也全過、沒比基準多壞 | 在 `<branch>` 上：`python -m pytest -q -p no:cacheprovider tests/test_sandbox_ready.py tests/test_sandbox.py tests/test_container_sandbox.py tests/test_container.py tests/test_container_install.py` | 0 failed；passed 數 ≥ 138（64＋74；平台不同時以驗收者那台在 `<base>` 上先跑一次的數字為準） |
| V11 | S1 的字沒有說成已隔離 | 看清單 S1-a～S1-e、C-1、C-5、D-1、L-1、L-4、M-2 的結果與紀錄 | 全部「通過」，或「失敗」有紀錄；沒有任何一項記錄到「已在 sandbox／已隔離／安全」卻標通過 |
| V12 | 「沒有隔離」與 `peek` 一致 | 看 W1、W2、C-5、D-1 | 都寫 `readable: true`（或失敗有紀錄） |
| V13 | 「容器／bwrap」與 `peek` 一致 | 看 C-2、L-1 | `readable` 不是 `true`、C-2 的 `cwd` 是 `/pack`；或「略過＋擁有者接受」 |
| V14 | 沒有警告的 pack 不變 | 看 S1-g（比對 `2240a5e` 與 `<base>`） | 「通過」，或失敗有紀錄 |
| V15 | 伺服器版可見性 | 看 S2-a～S2-d | S2-a、S2-b、S2-d 有結果；S2-c 有結果或「略過＋接受」 |
| V16 | jobobject 限制 | 看 J1～J5（Windows） | J2 沒有「配到了」、J3 的 N ≤ 8、J4 沒有殘留；或「略過＋接受」 |
| V17 | 容器映像照 digest、只拉官方 | 回報裡的映像寫法 | 是 `docker.io/library/python@sha256:<64 字>`；沒有別的映像；擁有者同意紀錄在備註（沒同意＝相關項目全是略過） |
| V18 | MXC 沒有偷跑 | 看 M-3 | 「略過（擁有者未同意）」；寫了別的就要有擁有者明確同意的紀錄 |
| V19 | 沒有私人資訊 | 下面的指令 A（diff 與 commit 訊息都搜） | 沒有輸出（只出現 `<home>`、`<user>` 這種代號） |
| V20 | 沒有密鑰 | 下面的指令 B | 沒有輸出 |
| V21 | 公開前檢查腳本 | `python scripts/prepublish_check.py --worktree-only`（在 `<branch>` 的 checkout；沒有私人詞清單時加 `--allow-no-terms`） | 沒有新的問題（跟在 `<base>` 上跑的結果相比） |
| V22 | 沒有 TODO／半成品 | 下面的指令 C | 沒有輸出 |
| V23 | 收尾 | 看回報的「收拾」一段 | 自己開的 SYNOX、console 已關，埠已放掉（附確認指令的輸出）；自己拉的映像已刪；`probe/`、`probe-dist/`、假檔已刪 |
| V24 | commit 訊息 | `git log <base>..<branch>` | 每個 commit 寫做了什麼、為什麼；結尾有共同作者行（如果是 agent 做的） |

V19～V22 的指令（bash；Windows 用 Git Bash）：

```sh
# A：私人資訊（本機路徑、家目錄、信箱、常見的電腦名稱開頭）
{ git diff <base> <branch>; git log <base>..<branch> --format=%B; } \
  | grep -nEi 'C:\\Users\\|/home/[a-z]|/Users/[a-z]|[a-z0-9._-]+@[a-z0-9-]+\.(com|net|org|tw|io)|DESKTOP-|LAPTOP-'
# B：密鑰
git diff <base> <branch> | grep -nEi 'token\s*[:=]|api[_-]?key\s*[:=]|ghp_|sk-[A-Za-z0-9]{10}|BEGIN [A-Z ]*PRIVATE KEY|AGE-SECRET-KEY'
# C：TODO／沒填完
git diff <base> <branch> | grep -nE '^\+.*(TODO|FIXME|XXX|＿＿＿＿|待補)'
```

（`noreply@anthropic.com` 這種 commit 共同作者行不算私人資訊，A 搜到它可以忽略。）

驗收者回報格式：「V1～V24 逐項：通過／不通過（原因）」＋「留下的問題」清單。**有任何一項不通過就不 merge**，把不通過的項目寫回這份交辦單的 [狀態]（卡住：…）。
全部通過才由驗收者在 `dev` 上 `git merge --no-ff <branch>`，merge commit 訊息寫「真機驗證 S1／S2／S4 的結果：幾項通過、幾項略過（擁有者接受）、發現什麼」。

## 6. [交回]

### 6.1 回報內容（一則訊息，結論先講）

1. 結論一句話：全部通過／有 N 項失敗／有 N 項略過。
2. 分支名、最新 commit（`git log --oneline -1`）、基底 commit。
3. 機器：作業系統與版本、Python、podman／docker 有無與版本（不寫電腦名稱、帳號名、路徑）。
4. 測試基準（§4.4 兩行的 passed／failed 數）。
5. 總表：每一項一行（通過／失敗／略過＋原因＋紀錄檔名）。
6. 每份失敗紀錄的全文（§6.2 格式，已去掉私人資訊）。
7. 用了哪個映像 digest（有拉的話）。
8. 「收拾」一段：關了哪些自己開的程序（pid、埠）、確認埠已放掉的指令輸出、刪了哪些檔與映像。
9. §5 驗證清單集裡你自己能先檢查的項目（V2～V9、V11～V24）逐項的自查結果。
10. 不確定的地方、想請擁有者決定的事（照「一件一檔」另開題目檔的格式寫在回報裡，不要自己改決定）。

### 6.2 失敗紀錄的格式（一件一檔）

在驗證資料夾裡開 `_inbox/`（不要 commit；在雲端或 docker 裡做的，就把全文貼進回報）。每一個失敗或意外各一個檔：`_inbox/YYYYMMDD-HHMMSS-<簡短英文代號>.md`。

```markdown
# <一句話標題，例如：jobobject 沒有擋住 600 MB 的配置>

狀態：待處理
清單項目：J2
機器：<作業系統與版本；有無 podman／docker 與版本>
SYNOX commit：<git log --oneline -1>

## 問題一句話
<…>

## 脈絡
- 做了什麼（完整指令，可以直接複製）
- 預期
- 實際（原樣貼輸出；把帳號名、電腦名、路徑換成 <user>、<home>）
- 我判斷代表什麼

## 選項
| 選項 | 一句話 | 建議 |
|---|---|---|
| A | <…> | ✅ 建議（預設做這個） |
| B | <…> | |

## 驗收
<修好之後要看到什麼才算好>

## 不要做的事
<例如：不要為了讓測試過而放寬上限>
```

### 6.3 收尾流程

1. 接手者：只 commit 在自己的分支 `docs/sandbox-verify-<YYYYMMDD>`；**不合併、不推送**（擁有者另外要你推到遠端讓驗收者拿，才推那一條分支，推之前照 V19、V20 自己掃一次）。
2. 收拾：結束自己開的 SYNOX、console，確認埠已放掉；`docker rmi docker.io/library/python@sha256:<DIGEST>`（只有這台本來沒有這個映像時）；
   刪掉 `probe/`、`probe-dist/`、家目錄的 `synox-probe-secret.txt`、驗證資料夾裡的 `data/` 與 `config.json`。
3. 驗收者：照 §5 逐項確認 → 全過才 `git merge --no-ff` 進 `dev`，merge commit 訊息寫做了什麼、為什麼 → 把這份交辦單的 [狀態] 改成「已完成：merge commit `<hash>`」。
4. 擁有者看完結果，再決定 S3、S5。
