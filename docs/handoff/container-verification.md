# 交接：容器隔離與 Linux 沙盒的真機驗證

狀態：**待驗證**（2026-11-10 寫；分支 `feat/isolation`）
為什麼要這份：寫程式的那台 Windows 開發機**不跑任何容器、VM**（擁有者的規定），容器後端（S0–S2）和原本的 bwrap／systemd 後端
（PERM-7）都只比對過「SYNOX 組出來的指令字串」。這份是帶到**另一台機器**（學校實驗室的 Linux 優先；Windows＋Docker Desktop 其次）
真的跑一次的清單。背景與每個旗標防什麼：[`docs/discussions/2026-11-10-isolation-howto.md`](../discussions/2026-11-10-isolation-howto.md)。

開始之前（擁有者做）：
1. 把分支帶過去：在開發機 `git push origin feat/isolation`（或 `git bundle create isolation.bundle dev..feat/isolation` 用隨身碟帶）。
2. 那台機器要有：Python 3.10 以上、git、podman（建議）或 Docker；Linux 的話另外 `bubblewrap`、`systemd`（多半內建）、`util-linux`（prlimit）。
3. 把下面「給那台 Claude 的 prompt」整段貼過去。

---

## 1. 給那台機器上的 Claude 的 prompt（整段貼上）

```
你在一台用來做驗證的機器上（不是擁有者的開發機）。任務：驗證 SYNOX 分支 feat/isolation 的「容器後端」與「Linux 沙盒後端」
真的有隔離效果，結果寫成紀錄回報。只驗證、不改 SYNOX 的程式、不合併任何分支。

準備
1. git clone（或 fetch）SYNOX，git checkout feat/isolation。建 venv：python3 -m venv .venv && .venv/bin/pip install -e . pytest
2. 先跑一次單元測試確認環境：.venv/bin/python -m pytest -q（應該全過；記下 passed 數）。
3. 讀 docs/handoff/container-verification.md 的第 2 節以後，照清單逐項做。

可以跑的
- podman／docker 的：pull（只限 docker.io/library/python 的官方映像，照 digest 用）、image inspect、run（只用清單裡的旗標組合，
  或 SYNOX 自己印出來的 argv）、ps、stop、rm、info、version。
- bwrap、systemd-run（--user 或用 SYNOX 帳號能用的範圍）、prlimit、cat /proc/...、id、stat。
- python -m synox install／packs／doctor／console（用清單裡的探針 pack；config.json 用 mode=server、llm.kind=none）。

絕對不要碰
- 不改防火牆、不開任何網路埠：不要用 -p／--publish、不要 --network host、不要起任何伺服器。
- 不要 --privileged、--cap-add、--device、不要掛 /var/run/docker.sock 或任何 *.sock。
- 不要 pull 或執行第三方（非官方 python）映像、不要裝任何第三方 pack、不要執行網路上抓來的腳本或安裝檔。
- 不要用 sudo 改系統設定（subuid、cgroup、套件）——缺什麼就記下來、停在那一項，請擁有者決定。
- 不要 push、不要合併、不要改 SYNOX 的原始碼（發現 bug 就寫紀錄，附重現步驟）。
- 不要把任何 token、密碼貼進紀錄。

怎麼回報
- 每一個失敗或意外各寫一個檔：<repo>/_inbox/YYYYMMDD-HHMMSS-<slug>.md（沒有 _inbox/ 就建一個，不要進 git）。
  檔頭：標題（第一個 # ）、狀態：待處理、機器（發行版／核心／podman 或 docker 版本／rootless 與否／cgroup 版本）。
  內容：做了什麼（完整指令）、預期、實際（原樣貼輸出）、你判斷代表什麼、建議的修法（附選項與你的建議）。
- 全部做完再寫一份總表 <repo>/_inbox/YYYYMMDD-HHMMSS-container-verification-summary.md：
  每一項（C1…、B1…）一行：通過／失敗／略過＋原因＋對應的紀錄檔名。結論先講，用條列與表格。
```

---

## 2. 準備（照做一次）

```sh
# 機器資訊（貼進總表）
uname -a; cat /etc/os-release | head -3
podman version || docker version
podman info --format '{{.Host.Security.Rootless}} {{.Host.CgroupsVersion}}'     # 期望：true v2
stat -fc %T /sys/fs/cgroup                                                      # 期望：cgroup2fs
grep "^$(whoami):" /etc/subuid /etc/subgid                                      # rootless 要有

# 官方 Python 映像，照 digest 用（SYNOX 執行時帶 --pull=never，不會自己拉）
podman pull docker.io/library/python:3.12-slim
podman image inspect docker.io/library/python:3.12-slim --format '{{.Digest}}'  # → sha256:<64 hex>，記成 $DIGEST
```

SYNOX 設定（repo 根目錄的 `config.json`，**只給這次驗證用**）：

```json
{"owner_id": 1, "mode": "server", "data_dir": "data", "llm": {"kind": "none"}, "vault": {"mode": "file"},
 "policy": {"sandbox": {"backend": "auto", "engine": "auto", "mem_mb": 256, "max_procs": 32}}}
```

### 探針 pack（寫在 repo 外，例如 `~/probe/`）

`~/probe/pack.json`（把 `<DIGEST>` 換成上面查到的 64 個 16 進位字）：

```json
{"name": "probe", "title": "容器探針", "summary": "驗證容器旗標", "version": "0.1.0", "kind": "cli",
 "skill": "SKILL.md", "access": "member", "publisher": "SYNOX-verification", "data": "user",
 "capabilities": ["filesystem:any"],
 "runtime": {"container": {"image": "docker.io/library/python@sha256:<DIGEST>", "network": false}},
 "cli": {"argv": ["{python}", "./tool.py"], "json_flag": null,
         "commands": [{"name": "report", "effect": "READ", "default": true, "argv": ["report"]},
                      {"name": "hog", "effect": "READ", "argv": ["hog"]}]}}
```

`~/probe/SKILL.md`：

```
---
name: probe
description: 容器探針（驗證用）
---
```

`~/probe/tool.py`：

```python
import json, os, sys

def status(key):
    for line in open("/proc/self/status"):
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""

def can_write(path):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("x")
        return True
    except OSError as e:
        return f"no ({type(e).__name__})"

cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
if cmd == "hog":
    blob = bytearray(600 * 1024 * 1024)            # 上限 256 MB：應該被殺或 MemoryError
    print(json.dumps({"message": f"配到了 {len(blob)} bytes（不該發生）"}))
    sys.exit(0)
home = os.environ.get("SYNOX_USER_DATA_DIR", "")
out = {"uid": os.getuid(), "gid": os.getgid(), "cwd": os.getcwd(), "python": sys.executable,
       "CapEff": status("CapEff"), "NoNewPrivs": status("NoNewPrivs"),
       "pack_dir": os.environ.get("SYNOX_PACK_DIR"), "user_dir": home, "HOME": os.environ.get("HOME"),
       "write_own": can_write(os.path.join(home, "probe", "w.txt")),
       "write_root": can_write("/usr/local/x.txt"), "write_pack": can_write("/pack/x.txt"),
       "write_tmp": can_write("/tmp/x.txt"),
       "data_listing": sorted(os.listdir("/data")) if os.path.isdir("/data") else None,
       "user_listing": sorted(os.listdir(home)) if os.path.isdir(home) else None}
print(json.dumps({"message": json.dumps(out, ensure_ascii=False)}))
```

打包並安裝（用容器）：

```sh
cd ~/probe && zip -r ../probe.synoxpack . && cd -
.venv/bin/python -m synox install ~/probe.synoxpack --yes --runtime container
.venv/bin/python -m synox doctor --offline      # 看「容器引擎」與 probe 的「🧱 容器（podman）」那兩行
```

### 印出 SYNOX 實際會跑的指令（之後幾項要用）

```sh
.venv/bin/python - <<'EOF'
from synox import sandbox
from synox.config import SynoxConfig
from synox.packs import loader
from synox.packs.manifest import read
cfg = SynoxConfig.load("config.json", require_token=False)
m = read("packs/probe")
box = sandbox.box_for(cfg, m)
ph = loader.placeholders(m, cfg, None)
g = sandbox.grants_for(m, cfg, ph)
for d in g.write:
    __import__("os").makedirs(d, exist_ok=True)
view = sandbox.view_for(box, ph)
env = loader.context_env(m, cfg, view)
argv, _ = box.wrap(loader.cli_prefix(m, view), env, m.folder, g)
print(box.describe())
print(" ".join(argv))
EOF
```

把印出來的那一行存成 `$SYNOX_ARGV`（到映像名字為止的前半段記成 `$RUN`，例如 `podman run --rm -i … docker.io/library/python@sha256:…`），
下面「C」開頭的項目會把後半段換成一行 Python 來試。

---

## 3. 容器（C）檢查清單

每一項：做什麼 → 預期 → 失敗代表什麼。指令裡的 `$RUN` 是上一節存的前半段（含映像）。

| # | 做什麼 | 預期 | 失敗代表什麼 |
|---|---|---|---|
| C1 | `.venv/bin/python -m synox console --as 1`，打 `/probe` | 回一段 JSON：`uid` 不是 0（rootless podman＝你的 uid）、`python` 是 `/usr/local/bin/python3`、`pack_dir`＝`/pack`、`user_dir`＝`/data/user`、`HOME`＝`/tmp` | 容器根本跑不起來（看錯誤：映像沒拉、`--pull=never`、`--userns=keep-id` 不支援、`--mount` 語法不合）→ S1 的 argv 要改 |
| C2 | 看 C1 的 `CapEff` | `0000000000000000` | `--cap-drop ALL` 沒生效 |
| C3 | 看 C1 的 `NoNewPrivs` | `1` | `--security-opt no-new-privileges` 沒生效 |
| C4 | 看 C1 的 `write_root`、`write_pack` | 都是 `no (OSError)`／`no (PermissionError)` 這類 | `--read-only` 或 pack 的 `readonly` 掛載沒生效 |
| C5 | 看 C1 的 `write_own`、`write_tmp` | 都是 `true`；本機的 `data/users/1/probe/w.txt` 真的出現、擁有者是 SYNOX 帳號（`ls -ln`） | 可寫掛載或 uid 對應有問題（rootless 的 keep-id；docker 的 `--user`） |
| C6 | 看 C1 的 `data_listing`、`user_listing` | `/data` 底下只有 `user`（和 `shared` 不在：data=user 的 pack 不掛共用的）；`/data/user` 底下只有 `probe` | 掛了不該掛的資料夾（別人的 `data/users/`、整個 `data/`） |
| C7 | 斷網：`$RUN python3 -c "import socket; socket.create_connection(('1.1.1.1', 443), 3)"` | `OSError: [Errno 101] Network is unreachable`（或類似） | `--network none` 沒生效 |
| C8 | 斷網也連不回本機：`$RUN python3 -c "import socket; socket.create_connection(('127.0.0.1', 22), 3)"` | 連不上 | 容器跟主機共用網路 |
| C9 | 讀不到主機的檔：`$RUN python3 -c "print(open('/etc/hostname').read())"`，再 `$RUN ls /home /root /srv` | 印出的是容器的 hostname（不是主機的）；`/home` 空、`/root` 讀不了或空、沒有 SYNOX 的路徑 | 有東西把主機掛進來了 |
| C10 | 記憶體上限：console 打 `/probe_hog` | 回錯誤（程式被殺，exit 137 或 MemoryError），**不會**印「配到了」 | `--memory` 沒生效（cgroup v1 上 rootless 會被忽略：記下 cgroup 版本） |
| C11 | 程序數上限：`$RUN python3 -c "import os\nfor i in range(200):\n    os.fork() or os._exit(0)"`（要真的換行，可以寫成檔再 `-` 讀） | 大約第 32 個左右 `BlockingIOError: Resource temporarily unavailable` | `--pids-limit` 沒生效 |
| C12 | 沒有 swap 溢出：`$RUN python3 -c "b=bytearray(400*1024*1024); print('ok')"`（上限 256 MB） | 被殺 | `--memory-swap` 跟 `--memory` 一樣大沒生效 |
| C13 | 環境變數不進 argv：照第 2 節印出的 argv 找 `--env`，確認只有名字（`SYNOX_TG_ID`…），沒有任何 `=值`（`HOME=/tmp` 除外） | 只有名字 | 密鑰可能出現在 `ps` |
| C14 | 執行時不會自己拉映像：`podman rmi <probe 用的映像>` 之後 console 打 `/probe` | 失敗、說映像不在；**沒有**開始下載 | `--pull=never` 沒生效（會偷偷連網） |
| C15 | 收尾：C1 跑完 `podman ps -a --filter label=synox.pack=probe` | 空（`--rm` 刪掉了） | 容器沒清掉，會累積 |
| C16 | 選「不用容器」：`.venv/bin/python -m synox packs runtime probe host`，再 doctor | probe 那行說「有提供容器，目前選「不用容器」」；伺服器版第三方的 probe 標「只對擁有者開放」（除非 bwrap／systemd 可用） | 切換沒寫進 packs.lock 或可見性沒跟著變 |
| C17 | 引擎拿掉：`PATH` 裡暫時拿掉 podman（例如 `env PATH=/usr/bin/nonexistent .venv/bin/python -m synox doctor --offline`） | 「容器引擎：podman —、docker —」、probe 說「選了容器，但這台找不到」 | 偵測或退回的邏輯有錯 |
| C18 | Docker（有裝的話）：`policy.sandbox.engine` 改 `docker`，重做 C1–C15 | 同上，C1 的 `uid` 是 SYNOX 帳號的 uid（`--user`） | docker 的旗標語法跟 podman 不同（記下哪一個） |

### venv 的 Python 能不能在容器裡用（決定 S3 怎麼做）

| # | 做什麼 | 預期 | 代表什麼 |
|---|---|---|---|
| V1 | 主機上 `python3 -m venv /tmp/v && ls -l /tmp/v/bin/python`，再 `$RUN` 前面加 `--mount type=bind,source=/tmp/v,target=/venv,readonly`，後面換成 `/venv/bin/python -c "print(1)"` | **推測失敗**：venv 的 python 是指到主機 `/usr/bin/python3` 的捷徑，容器裡沒有 | 失敗＝S3 的做法對：容器模式不建 venv、套件放進映像（Dockerfile `pip install`）；成功＝可以考慮掛 venv（但版本要跟映像一致） |
| V2 | 映像裡的 Python：`$RUN python3 -c "import sys; print(sys.version)"` | 3.12.x | 映像對 |

### MCP stdio 長駐（S4 前的現況）

`~/probe-mcp/` 三個檔（pack.json 的 `<DIGEST>` 同上）：

```json
{"name": "probemcp", "title": "MCP 探針", "summary": "s", "version": "0.1.0", "kind": "mcp", "skill": "SKILL.md",
 "publisher": "SYNOX-verification", "data": "user", "capabilities": ["subprocess"],
 "runtime": {"container": {"image": "docker.io/library/python@sha256:<DIGEST>"}},
 "mcp": {"transport": "stdio", "argv": ["{python}", "./server.py"], "tools_allow": ["whoami"],
         "effects": {"whoami": "READ"}}}
```

`server.py`（只用標準函式庫，一行一個 JSON-RPC）：

```python
import json, os, sys
for line in sys.stdin:
    msg = json.loads(line)
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        continue
    if method == "initialize":
        res = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
               "serverInfo": {"name": "probe", "version": "0"}}
    elif method == "tools/list":
        res = {"tools": [{"name": "whoami", "description": "who", "inputSchema": {"type": "object", "properties": {}}}]}
    elif method == "tools/call":
        res = {"content": [{"type": "text", "text": json.dumps({"pid": os.getpid(), "uid": os.getuid(),
                                                                 "dir": os.environ.get("SYNOX_USER_DATA_DIR")})}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "no"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}), flush=True)
```

加上 `SKILL.md`，打包、`install --yes --runtime container`。

| # | 做什麼 | 預期 | 失敗代表什麼 |
|---|---|---|---|
| M1 | console 打兩次 `/probemcp_whoami` | 兩次的 `pid` 一樣（同一個長駐容器）、`dir`＝`/data/user`；`podman ps --filter label=synox.pack=probemcp` 有一個在跑 | stdio 沒接好（`-i` 沒生效、stdout 被加了 `\r`）或每次都重開 |
| M2 | 結束 console（Ctrl+D／`/exit`），再 `podman ps -a --filter label=synox.pack=probemcp` | 空（關 stdin → 伺服器結束 → `--rm`） | 收尾不乾淨：S4 要補「先 `stop <名字>`」 |
| M3 | console 開著時 `kill -9` SYNOX 的 python 程序，再看 `podman ps` | 記下容器還在不在、多久後消失 | 決定 S4 要不要在啟動時清掉 label=synox.pack 的殘留容器 |
| M4 | 閒置回收：開著 console 等 11 分鐘以上（`IDLE_SECONDS`＝600）再看 `podman ps` | 容器消失 | 閒置回收在容器模式沒生效 |

### Windows 實驗室機器（Docker Desktop，有的話）

只做：C1–C7、C10、C13–C15、M1–M2，`engine` 設 `docker`。另外記：
- `--mount type=bind,source=C:\…` 是否被接受（C1 失敗就看這個）。
- C5 用 `--user 65534:65534` 寫不寫得進本機資料夾。
- M2：關掉 SYNOX 後 `docker ps` 還有沒有 probemcp 的容器（Job Object 只包住 docker.exe 用戶端）。

---

## 4. Linux 沙盒後端（B）——原本未驗證的 PERM-7

把 probe 切成不用容器：`.venv/bin/python -m synox packs runtime probe host`；`policy.sandbox.backend` 依序設 `bwrap`、`systemd`
（systemd 用 `systemd_scope: "user"` 或 SYNOX 帳號能開的範圍），每次用第 2 節的腳本印 argv（`box.describe()` 會是 bwrap／systemd）。
探針在主機上跑時 `/data`、`/pack` 不存在，看的是 `user_dir`、`write_own`、`write_root`。

| # | 做什麼 | 預期 | 失敗代表什麼 |
|---|---|---|---|
| B1 | bwrap：console 打 `/probe` | 跑得起來；`write_own` true；`write_root` false | bwrap 在這個帳號開不了 user namespace（記 `sysctl kernel.unprivileged_userns_clone`、AppArmor 設定） |
| B2 | bwrap 斷網：把印出的 argv 最後換成 `python3 -c "import socket; socket.create_connection(('1.1.1.1',443),3)"` | 連不上 | `--unshare-net` 沒生效 |
| B3 | bwrap 讀不到別人的：先 `mkdir -p data/users/2/probe && echo secret > data/users/2/probe/x`，argv 最後換成 `cat <絕對路徑>/data/users/2/probe/x` | `No such file or directory` | 別人的資料夾看得到（嚴重） |
| B4 | bwrap＋venv：`runtime.python` 改成 pack 旁邊的 venv（或用 SYNOX 自己的 .venv），console 打 `/probe` | 跑得起來（venv 的 python 是指到 `/usr` 的捷徑，`/usr` 有唯讀掛進去） | 系統資料夾清單（`SYSTEM_RO`）不夠 |
| B5 | prlimit：`policy.sandbox.mem_mb` 設 256，console 打 `/probe_hog` | 失敗（MemoryError） | `prlimit --as` 沒生效或找不到 prlimit（doctor 有說） |
| B6 | systemd：console 打 `/probe` | 跑得起來；`write_own` true | `systemd-run --pipe --wait` 在這個帳號開不了（記錯誤） |
| B7 | systemd 斷網、讀不到別人的：同 B2、B3 | 同上 | `PrivateNetwork`／`InaccessiblePaths＋BindPaths` 巢狀不如預期 |
| B8 | systemd 的 `--setenv=名字`：看印出的 argv 只有名字；探針裡 `SYNOX_USER_DATA_DIR` 有值 | 有值 | 這版 systemd 不支援只給名字（值沒帶進去） |
| B9 | systemd 記憶體：`/probe_hog` | 被殺 | `MemoryMax` 沒生效（user scope 可能要 cgroup 委派） |

---

## 5. 驗完之後

- 總表（`_inbox/…-container-verification-summary.md`）給擁有者看：哪些通過、哪些失敗、哪些因為環境略過。
- 擁有者決定要修的，開新分支修；**`docs/security.md` 的「還沒證明的」那幾句，要等這份清單過了才改成「驗過」**。
- 清理：`podman rmi docker.io/library/python@sha256:<DIGEST>`、刪 `~/probe*`、`data/`、`config.json`（驗證用的）。
