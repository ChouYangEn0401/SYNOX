> 已由交辦單 [20261119-134608-sandbox-real-machine.md](20261119-134608-sandbox-real-machine.md) 取代整理；內容仍有效。

# 交接：沙盒與「帶警告的 pack」——在另一台電腦上做真機驗證

狀態：**待驗證**（2026-11-19 寫；程式在分支 `feat/sandbox-ready`，合併後在 `dev`）

**給誰**：擁有者，或擁有者在另一台電腦上開的 session。讀完這份＋[真機清單](../testing/sandbox-real-machine-checklist.md)就能直接動手，不用回頭問。
**為什麼要另一台**：寫程式的那台開發機不跑容器、不跑 Job Object 的實際限制測試、沒有 Linux；這一批的程式只在「假後端、假 `which`」下測過。

---

## 1. 背景（三分鐘看懂）

1. pack 的作者可以在 `pack.json` 標警告（[ADR 0041](../adr/0041-pack-warnings.md)），最常見的是
   `vendor_no_security_guarantee`：「官方不保證安全——建議在 docker 或 sandbox 執行」。SYNOX 在每個看得到工具的地方都照樣顯示，第一次啟用要擁有者逐條確認。
2. 那句「建議在 sandbox 執行」是**作者的字**。SYNOX 會不會真的把工具關起來，要看這台電腦有什麼（ADR 0041 §5 的分析）：

   | 情況 | 實際的後端 | 算不算隔離 |
   |---|---|---|
   | Windows 個人版（預設 `auto`） | none | 不算：工具用你的帳號權限跑 |
   | Windows 設 `backend: jobobject` | Job Object | 不算：只限記憶體與程序數 |
   | Windows 設 `backend: appcontainer` | 退回 none | 不算：還沒做（只有介面） |
   | Windows 11 的 MXC | —— | 還沒有後端（只有研究時的探測結果） |
   | Linux 伺服器版 | bwrap，沒有就 systemd-run | 算 |
   | pack 宣告 `runtime.container`＋安裝時選「用容器」＋PATH 上有 podman／docker | 容器 | 算 |
   | `kind=python` | 在 SYNOX 自己的程序裡跑 | **任何後端都包不到** |

3. 風險是使用者看到「sandbox」就以為 SYNOX 已經幫他關起來了。所以這一批做了三件事（ADR 0041 §5.4 的 S1、S2、S4），**都還沒在真機上驗過**。

## 2. 目前狀態

### 2.1 已做（程式＋自動測試，`tests/test_sandbox_ready.py`）

| # | 做了什麼 | 影響 |
|---|---|---|
| S1 | 帶警告的 pack，在警告**下面**多一行 SYNOX 自己寫的「ℹ️ SYNOX 查這台的實況：…」，依實際後端與 pack 宣告判斷：沒有隔離＝「會以你的權限直接執行」；有提供容器＝「需要 podman 或 docker，已偵測到／沒偵測到」；python＝「沒有任何後端能把它關起來」；真的有容器或 bwrap 才說「會用 … 包起來跑」。出現在：安裝報告（終端機、網頁）、設定頁、doctor、`packs status`、`packs lock`；給 AI 的能力清單帶短句「〔實況：…〕」、`data/agent_index.json` 帶 `isolation` | **只有顯示文字**，不改任何執行行為。沒有警告的 pack 每個地方一個字都不多 |
| S2 | 帶 `vendor_no_security_guarantee` 的 pack 在**伺服器版**算「一定要沙盒」（跟 T2 同一條路）：cli／mcp stdio 沒有真隔離（none、jobobject）就只給擁有者；有 bwrap／systemd／容器就給成員；python 工具一律只給擁有者 | 只影響伺服器版；個人版完全不變 |
| S4 | `kind=python` 帶警告：只加紅字（就是 S1 的 python 那一句），**不拒裝** | 只有顯示 |

程式在 `src/synox/sandbox.py`（`isolation_note`、`isolation_line`、`no_guarantee`、`required`、`restricted_reason`），
顯示接在 `packs/admin.py`、`packs/loader.py`、`doctor.py`、`__main__.py`、`web/server.py`、`web/static/app.html`、`agent/index.py`。

### 2.2 沒做（要擁有者決定或等別的東西）

- **S3**：隔離做出來以後，這個警告在沒有隔離的電腦上要不要「預設不執行」→ [題目檔](open-questions/20261119-121055-s3-warning-default-off-without-isolation.md)。
- **S5**：要不要要求 web-ddgs 這類帶警告的 pack 宣告 `runtime.container` → [題目檔](open-questions/20261119-121056-s5-require-runtime-container.md)。
- Windows 的真隔離後端（MXC、AppContainer）：還沒有，所以 Windows 個人版目前**沒有任何一條路**能照「在 sandbox 執行」做到。

### 2.3 沒驗證（這份交接要做的）

全部在真機清單裡：Job Object 的限制是不是真的生效、容器是不是真的看不到主機、沒有引擎時的降級、各種機器狀態下 S1 的字對不對、S2 在伺服器版的可見性、MXC 探測結果的解讀、Linux／macOS。

## 3. 環境準備

### 3.1 先記下機器資訊

```powershell
# Windows（PowerShell）
[System.Environment]::OSVersion.VersionString
(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuild
python --version
podman version; docker version      # 沒有就會說找不到，照實記
```

```sh
# Linux／macOS
uname -a; cat /etc/os-release | head -3
python3 --version
podman version || docker version
```

只記作業系統、版本、有沒有 podman／docker；**不要記電腦名稱、帳號名、路徑**。

### 3.2 取得程式（用一個專門給驗證用的資料夾，不要用平常在用的 SYNOX）

```sh
git clone <SYNOX 的 repo 網址> synox-verify
cd synox-verify
git checkout dev            # 合併之前用 feat/sandbox-ready
python -m venv .venv
# Windows：.venv\Scripts\pip install -e . pytest      Linux／macOS：.venv/bin/pip install -e . pytest
```

之後的指令裡的 `python` 都是這個 `.venv` 的 python。先跑一次單元測試當基準：

```sh
python -m pytest -q -p no:cacheprovider tests/test_sandbox_ready.py tests/test_sandbox.py tests/test_container_sandbox.py
```

### 3.3 驗證用的 `config.json`（放在 `synox-verify/`，只給這次驗證用）

個人版：

```json
{"owner_id": 1, "data_dir": "data", "llm": {"kind": "none"}, "vault": {"mode": "file"}}
```

伺服器版（4.6、第五節用）：

```json
{"owner_id": 1, "mode": "server", "data_dir": "data", "llm": {"kind": "none"}, "vault": {"mode": "file"}}
```

jobobject（4.2 用；Windows）：在上面任一份加 `"policy": {"sandbox": {"backend": "jobobject", "mem_mb": 256, "max_procs": 8}}`。

網頁那幾項（S1-b、S1-c、S1-g 的 API）：用同一個驗證資料夾跑 `Setup.bat`（或照 README 的進階安裝）開 SYNOX；網頁只綁 `127.0.0.1`（SYNOX 預設），**不要改成別的位址**。
開了 SYNOX 就記下它的 pid 與埠，測完用 `Stop.bat`（或結束那個 pid）關掉，再確認埠已經放掉（`Get-NetTCPConnection -LocalPort <埠>` 沒有東西）。

### 3.4 假 pack（全部自己寫，放在驗證資料夾外面，例如家目錄的 `probe/`）

所有假 pack 都只用 Python 標準函式庫，不連網、不下載任何東西。每個資料夾三個檔：`pack.json`、`SKILL.md`、程式。

**共用的假檔**（`peek` 用來確認「讀不讀得到你的檔案」）：在家目錄建 `synox-probe-secret.txt`，內容寫 `fake`。

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

**`probe/warncli/tool.py`**

```python
import json, os, sys

cmd = sys.argv[1] if len(sys.argv) > 1 else "ok"
if cmd == "peek":
    path = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        with open(path, encoding="utf-8") as f:
            readable = f.read(16) == "fake"
    except OSError as e:
        readable = f"no ({type(e).__name__})"
    print(json.dumps({"message": json.dumps({"readable": readable, "cwd": os.getcwd()})}))
else:
    print(json.dumps({"message": "ok"}))
```

console 裡這樣叫：`/warncli_peek path=<你的家目錄>/synox-probe-secret.txt`（Windows 用 `\` 也可以）。

**`probe/warnbox/`**：把 `warncli` 整個複製一份，`pack.json` 的 `name`／`title`／`group` 改成 `warnbox`，再加一欄
（`<DIGEST>` 見 3.5）：

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

**每個資料夾的 `SKILL.md`**（`name` 換成那個 pack 的名字）：

```
---
name: warncli
description: 驗證用的假工具
---
```

**打包**（每個 pack 一次；壓縮檔裡第一層就是 `pack.json`）：

```powershell
# Windows
Compress-Archive -Path .\probe\warncli\* -DestinationPath .\warncli.zip -Force
Move-Item .\warncli.zip .\warncli.synoxpack -Force
```

```sh
# Linux／macOS
(cd probe/warncli && zip -r ../../warncli.synoxpack .)
```

安裝（帶警告的要明確確認；伺服器版的項目加 `--trust core`）：

```sh
python -m synox install warncli.synoxpack --yes --accept-warning vendor_no_security_guarantee
python -m synox install jobprobe.synoxpack --yes
```

### 3.5 容器映像（只有 4.4、L-5 要）

- SYNOX 的第 1 關**只收** `docker.io`／`ghcr.io`／`quay.io` 上**帶 `@sha256:` digest** 的映像；`localhost/…` 或本機 build 沒推上去的映像會被拒。
  所以 `warnbox` 用的是官方 Python 映像（照 digest），容器裡跑的程式**只有你自己寫、掛進去的 `tool.py`**。
- 只拉這一個官方映像，不 pull、不 run 任何別的映像：

```sh
docker pull docker.io/library/python:3.12-slim          # 或 podman pull
docker image inspect docker.io/library/python:3.12-slim --format "{{index .RepoDigests 0}}"
# → docker.io/library/python@sha256:<64 個 16 進位字>，那 64 個字就是 <DIGEST>
```

- 擁有者如果不同意拉這個官方映像：4.4、4.5、S2-c、L-5 整節寫「略過：未同意拉映像」，在總表註明。

## 4. 逐步驗證

照 [真機清單](../testing/sandbox-real-machine-checklist.md) 從 P0 做到第六節，順序就是清單的順序（Windows → Linux → macOS）。
每做完一項就填結果欄，不要最後一起補。

如果是另一台電腦上的 session 在做，把下面這段整段貼給它：

```
你在一台專門做驗證的電腦上（不是擁有者平常用的電腦）。任務：照 docs/handoff/sandbox-real-machine.md 準備環境，
再照 docs/testing/sandbox-real-machine-checklist.md 逐項驗證 SYNOX 的「帶警告的 pack 的這台實況（S1）」「伺服器版限制（S2）」
「python 工具的紅字（S4）」與沙盒後端，結果填進清單並照交接書第 6 節回報。只驗證、不改 SYNOX 的程式、不合併、不推送。
規矩照交接書第 7 節「不要做的事」，有一條做不到就停在那一項、寫紀錄、請擁有者決定。
```

## 5. 驗收標準

- 真機清單**每一項都勾了**，結果都是「通過」；有「略過」的，擁有者在總表的備註明確寫「接受」。
- 任何一項「失敗」＝這一批不算驗收完成，照第 6 節開紀錄，修好之後**整節重做**（不是只重做那一項）。
- S1 的字在每一種機器狀態下**都沒有**說成「已在 sandbox／已隔離／安全」；說「沒有隔離」的時候，`peek` 真的讀得到假檔；說「容器／bwrap」的時候，`peek` 真的讀不到。
- 沒有警告的 pack（`plaincli`、`jobprobe`）在每個畫面、每個檔案上跟上一版一字不差（S1-g）。

## 6. 失敗時怎麼回報（一件一檔）

在驗證資料夾裡開 `_inbox/`（不要進 git），**每一個失敗或意外各寫一個檔**：`_inbox/YYYYMMDD-HHMMSS-<簡短英文代號>.md`。
全部做完再寫一份總表 `_inbox/YYYYMMDD-HHMMSS-sandbox-real-machine-summary.md`（每一項一行：通過／失敗／略過＋原因＋紀錄檔名；結論先講）。

每個紀錄檔的格式：

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

紀錄裡**不寫**：真名、信箱、電腦名稱、帳號名、本機路徑、token、密碼。

## 7. 不要做的事

- **不要改防火牆**，不要開任何對外的埠；不要用 `-p`／`--publish`、`--network host`。
- 需要在本機開埠（SYNOX 的網頁）時：**只綁 `127.0.0.1`**，開之前記下 pid 與埠，**測完一定關掉自己開的程序**並確認埠已放掉。
  那台電腦上別人（或擁有者自己）開的服務一律不碰：不停、不重啟、不改設定；分不清是不是自己開的就當成別人的。
- **不要執行下載來的東西**：不裝、不叫任何第三方 pack；不執行網路上抓的腳本、安裝檔、壓縮包裡的程式；MXC 的 `wxc-exec.exe` 預設不跑（清單 M-3）。
- 容器：**只用 3.5 的那一個官方 Python 映像（照 digest）**，容器裡只跑自己寫的探針；不要 `--privileged`、`--cap-add`、`--device`、不要掛 `docker.sock`。
- 不要用管理員權限改系統設定（subuid、cgroup、群組原則）；缺什麼就記下來、停在那一項、請擁有者決定。安裝 bubblewrap、podman 這類套件也要擁有者先同意。
- 不要為了騰記憶體去關別人的程式；記憶體測試只用 `jobprobe` 的 600 MB。
- 不要改 SYNOX 的原始碼、不要合併、不要推送；發現 bug 就照第 6 節寫紀錄。
- 不要為了讓某一項通過而改清單的預期或放寬設定（例如把 `mem_mb` 調高）。

## 8. 驗完之後

- 把總表與每個紀錄檔交給擁有者（不經 git）。
- 收拾：結束自己開的 SYNOX、console；`docker rmi docker.io/library/python@sha256:<DIGEST>`（如果這台本來沒有這個映像）；
  刪掉 `probe/`、`*.synoxpack`、家目錄的 `synox-probe-secret.txt`、驗證資料夾裡的 `data/` 與 `config.json`。
- 擁有者看完結果，再決定 S3、S5（`open-questions/` 裡的兩個題目）。
