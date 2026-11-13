# 隔離／容器：具體要怎麼做（給擁有者看的操作版）

狀態：**調查完成，S0–S2 已在分支 `feat/isolation` 實作（只組指令、不執行）；真機驗證見 `docs/handoff/container-verification.md`**
日期：2026-11-10　前一份（為什麼、比較表、階段 S0–S8）：`docs/lab/discussions/2026-11-10-sandbox-and-skill-containers.md`
標示：**已查證**＝有官方來源（附連結）；**推測**＝照經驗判斷；**待實測**＝要在真的機器上跑過才知道。
這份文件是用**唯讀**的方式查官方網頁寫的：沒有下載、安裝、執行任何容器引擎或映像。

---

## 0. 結論先講

| 問題 | 一句話答案 |
|---|---|
| 容器到底替我們擋什麼？ | 把一個 pack 的程式關進「只看得到自己 pack 資料夾＋自己那一格資料夾、沒有網路、不能變 root、記憶體與程序數有上限」的小房間。房間的牆是 Linux 核心做的，SYNOX 只負責**把門窗的設定寫對**。 |
| Linux 伺服器要準備什麼？ | 裝 **podman**（建議，rootless：不用 root 就能跑）或 Docker Engine；確認 `/etc/subuid`、`/etc/subgid` 有 SYNOX 帳號那一行、系統是 cgroup v2（不然記憶體／程序數上限不生效）；把 pack 要的映像先拉下來（照 digest）。 |
| Windows 實驗室機器要準備什麼？ | 使用者自己下載安裝 **Docker Desktop（WSL 2 後端）**；Home 版可以跑 Linux 容器。VirtualBox 是另一條路（整台 VM），SYNOX 這一版還沒有 VM 後端（S7）。 |
| SYNOX 現在做到哪？ | pack.json 可以寫 `runtime.container`（第 1 關檢查、Dockerfile 第 2 關掃描）；SYNOX 會組出一整串安全旗標的 `podman run`／`docker run` 指令；安裝報告讓擁有者選「用容器／不用」並記進 `packs.lock`；伺服器版的第三方／T2 pack 選了容器、這台又找得到引擎 → 可以開給成員。**映像的拉取與建置（S3）、MCP 長駐容器的收尾（S4）、installer 偵測（S6）、VM（S7）都還沒做。** |
| 這台開發機？ | 什麼容器、VM 都不跑。測試只比對「組出來的指令」字串。 |

---

## 1. 容器在擋什麼（白話）

把 pack 的程式想成一個租客：

- **沒有容器**：租客住在你家，所有房間（整台電腦的檔案、網路、你的保管箱檔）都走得進去。
- **有容器**：租客住在一間小套房。套房裡只有：一份 pack 資料夾的**影本**（唯讀，改不了）、一個「他自己的」置物櫃（可寫，就是他那一格資料夾）、一個暫存抽屜（`/tmp`，關門就清空）。套房沒有對外的窗（沒網路，除非 pack 宣告要連網）、住戶不能升級成房東（不能變 root）、電費有上限（記憶體、程序數）。

這個比喻**不擋的事**（誠實版）：
- 牆是共用同一個 Linux 核心：核心本身有漏洞，住戶有機會穿牆（VM 才擋得住，見 §6）。
- 宣告了 `network` 的 pack：容器裡可以連外，連去哪 SYNOX 管不到。
- 置物櫃裡的東西（那個人自己的資料）住戶本來就能讀寫——容器防的是「讀到別人的」。
- 映像裡裝了什麼 SYNOX 不看（跟 npm 套件一樣）。

---

## 2. 最小可行的旗標組（SYNOX 實際組的指令）

`src/synox/sandbox.py` 的 `ContainerSandbox.wrap()` 組出來的樣子（podman；docker 只差使用者那一行）：

```
podman run --rm -i --pull=never --name synox-weather-123-ab12cd34 --label synox.pack=weather
  --network none
  --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m
  --cap-drop ALL --security-opt no-new-privileges
  --pids-limit 64 --memory 512m --memory-swap 512m [--cpus 1]
  --userns=keep-id                       （docker：--user <SYNOX 的 uid>:<gid>）
  --mount type=bind,source=/srv/synox/packs/weather,target=/pack,readonly
  --mount type=bind,source=/srv/synox/data/users/123/weather,target=/data/user/weather
  --workdir /pack
  --env HOME=/tmp --env SYNOX_USER_DATA_DIR --env WEATHER_API_KEY …   （只有名字；值從 SYNOX 自己的環境帶進去）
  ghcr.io/example/weather@sha256:<64 個 16 進位字>
  python3 /pack/tool.py …                （pack 原本的 argv，路徑換成容器裡的）
```

| 旗標 | 防什麼（白話） | 狀態 |
|---|---|---|
| `--rm` | 跑完就把容器丟掉，下次是乾淨的，不會累積垃圾或被留下的東西 | 已查證[^dockerrun][^podmanrun] |
| `-i` | 讓 stdin 保持打開：cli 的輸入、MCP 的 JSON-RPC 都走這條管線，**不用開任何網路埠** | 已查證[^dockerrun][^podmanrun] |
| `--pull=never` | 執行時**絕不**自己上網抓映像（映像要事先照 digest 拉好）；避免「跑一次指令就偷偷下載東西」 | 已查證（docker：`never`＝即使沒有也不拉）[^dockerrun]；podman 同義[^podmanrun] |
| `--network none` | 沒有網路卡：連不了外、也連不回本機的服務（SYNOX 的網頁、資料庫） | 已查證（podman：「建立網路命名空間但不設定任何介面」）[^podmanrun]；docker 的 `none` 網路見 networking 文件（推測同義） |
| `--read-only` | 容器自己的系統檔案唯讀：程式改不了 `/usr`、`/etc`，沒辦法把自己藏進系統裡 | 已查證[^dockerrun][^podmanrun] |
| `--tmpfs /tmp:…,noexec,…` | 給一個關門就消失的暫存區；`noexec` 讓放進去的檔不能直接當程式執行 | 已查證（podman 預設就是 rw,noexec,nosuid,nodev）[^podmanrun] |
| `--cap-drop ALL` | 拿掉 Linux 的所有「特權小鑰匙」（改網路設定、改檔案擁有者、掛載磁碟…） | 已查證[^dockerrun][^podmanrun] |
| `--security-opt no-new-privileges` | 就算裡面有 setuid 程式（例如 `sudo`），也不能藉它變成更高權限 | 已查證[^dockerrun][^podmanrun] |
| `--pids-limit` | 程序數上限：擋「無限開分身」把整台機器拖垮 | 已查證；**rootless 時要 cgroup v2 才生效**[^rootlessdocker][^podmanrootless] |
| `--memory`、`--memory-swap` 一樣大 | 記憶體上限（不准用 swap 超出）：擋吃光記憶體 | 同上（cgroup v2） |
| `--cpus` | CPU 上限（pack 有寫才加） | 同上 |
| `--userns=keep-id`（podman）／`--user uid:gid`（docker） | 容器裡**不是 root**：podman 讓程式以 SYNOX 帳號的 uid 跑（寫進置物櫃的檔案擁有者正確）；docker 直接指定 SYNOX 的 uid | 已查證（keep-id：「init 程序以目前使用者的 UID 執行」）[^podmanrun]；docker `--user` 格式已查證[^dockerrun] |
| `--mount …,readonly` 只掛 pack 資料夾 | 程式只看得到自己的 pack（唯讀）；其他 pack、`config.json`、保管箱、別人的 `data/users/` **根本不在房間裡** | 已查證（bind mount 預設可寫，加 readonly 才唯讀）[^bind] |
| `--mount`（可寫）只掛那個人的那一格 | 寫得進自己的資料夾、碰不到別人的 | 同上 |
| `--env NAME`（不寫值） | 密鑰的值不出現在命令列（`ps` 看不到）：docker／podman 從自己的環境變數拿值 | 已查證（docker、podman 都是「沒寫值就看本機環境」）[^dockerrun][^podmanrun] |
| 映像一定 `@sha256:…` | 指名「這一份內容」：tag（`:latest`）可以被換掉，digest 不行 | 已查證（「tag 可以重用或改，digest 不可變」）[^digest] |
| **絕對不加** `--privileged`、`--network host`、`-v /var/run/docker.sock`、`--cap-add`、`--device` | 這幾個任何一個都等於把牆打掉：`docker.sock` ＝能叫 Docker 開一個掛整台硬碟的新容器；docker 群組本身就等於 root | 已查證（「docker 群組給的是 root 等級的權限」）[^dockergroup]；SYNOX 第 1 關一律拒 |

**不在最小組、留給之後的**：`--ipc none`（有些程式需要 `/dev/shm`，推測會壞 Python multiprocessing，待實測）、自訂 seccomp 政策、gVisor（`--runtime=runsc`，前一份 §A）。

---

## 3. (a) Linux 伺服器：從零到「SYNOX 把第三方 pack 放進容器跑」

假設：實驗室的一台 Linux（Ubuntu／Debian／Fedora 類），SYNOX 用一個專用帳號（例如 `synox`）跑。

| 步驟 | 做什麼 | 狀態 |
|---|---|---|
| 1 | 用系統的套件管理裝 podman（`apt install podman`／`dnf install podman`）。**不要**用網路上的一鍵安裝腳本。要用 Docker 的話裝 Docker Engine（官方套件庫），並看步驟 7 | podman 在主流發行版都有套件：推測（常識）；rootless 教學[^podmantut] |
| 2 | 確認 `synox` 帳號有 subuid／subgid：`grep ^synox: /etc/subuid /etc/subgid`；沒有就請管理者 `usermod --add-subuids 100000-165535 --add-subgids 100000-165535 synox` | 已查證[^podmantut] |
| 3 | 確認是 cgroup v2：`stat -fc %T /sys/fs/cgroup` 應該是 `cgroup2fs`。是 v1 的話 rootless 的記憶體／程序數上限**會被忽略** | 已查證（podman：「cgroups v1 上不支援資源限制」；docker rootless：v1 上 `--memory`、`--pids-limit` 被忽略）[^podmanrootless][^rootlessdocker]；檢查指令是推測 |
| 4 | `synox` 帳號要有 systemd 使用者 session（`loginctl enable-linger synox`），不然登出後 rootless 容器可能被收掉 | 推測（docker rootless 文件對 dockerd 有同樣建議[^rootlessdocker]），待實測 |
| 5 | 以 `synox` 帳號跑 `podman info`：看 `rootless: true`、`cgroupVersion: v2` | 推測，待實測 |
| 6 | 把 pack 要的映像**照 digest** 拉下來：`podman pull ghcr.io/example/weather@sha256:…`（SYNOX 執行時帶 `--pull=never`，不會自己拉；S3 之後改由 SYNOX 經 JobRunner 拉並比對 digest） | 已查證（照 digest 拉＝拿到的就是那一份）[^digest] |
| 7 | 用 Docker 的話：`synox` 帳號要能叫 docker。**加進 docker 群組＝給它 root**，比較好的是 Docker 的 rootless 模式（要 `uidmap` 套件、`dockerd-rootless-setuptool.sh install`，由那個帳號自己跑） | 已查證[^dockergroup][^rootlessdocker] |
| 8 | SYNOX 設定（`config.json`）：`"mode": "server"`；`policy.sandbox.engine` 留 `auto`（先 podman 再 docker）或寫死 `podman`／`docker` | 這個分支已實作 |
| 9 | 裝 pack：`python -m synox install x.synoxpack --yes --runtime container`（網頁：報告上「🧱 執行環境」選「用容器」）。pack.json 沒有 `runtime.container` 就只能選「不用容器」 | 這個分支已實作 |
| 10 | `python -m synox doctor`：看「容器引擎：podman ✅」、那個 pack 的「🧱 容器（podman）」；伺服器版第三方 pack 不再寫「只對擁有者開放」 | 已實作；真機待實測 |
| 11 | 照 `docs/handoff/container-verification.md` 的清單驗：斷網、唯讀、讀不到別人的資料夾、記憶體上限、MCP 長駐 | 待實測 |

**rootless podman 的已知限制**：不能在家目錄是 NFS／GPFS 的機器上跑（容器的 uid 對不上）；不能綁 1024 以下的埠（SYNOX 本來就不開埠，沒差）[^podmanrootless]。

---

## 4. (b) Windows 實驗室機器

### 4.1 Docker Desktop（WSL 2）——建議

| 步驟 | 做什麼 | 狀態 |
|---|---|---|
| 1 | 確認 Windows 版本：Docker 官方列 Windows 10 22H2（build 19045）以上、64 位元、8 GB RAM、BIOS 開虛擬化；**Home／Education 只能跑 Linux 容器**（SYNOX 只要 Linux 容器） | 已查證[^dockerwin] |
| 2 | WSL 2：系統管理員 PowerShell `wsl --install`，重開機（Windows 10 2004／build 19041 以上） | 已查證[^wsl]；第一次開 WSL 2 要管理員權限[^dockerwin] |
| 3 | **使用者自己**到 Docker 官網下載 `Docker Desktop Installer.exe`，從 release notes 對 SHA-256（官方說校驗碼在 release notes），自己執行、選「Use WSL 2 instead of Hyper-V」 | 已查證[^dockerwin]；SYNOX 不散布、不代為安裝（擁有者決定 Q3／(4)） |
| 4 | 確認授權：個人、教育（學校實驗室）、小公司免費，大公司要付費 | 已查證（前一份 §E2）[^dockerlic] |
| 5 | 開 Docker Desktop 一次、接受條款；PowerShell `docker version` 看得到 Server 那段 | 推測，待實測 |
| 6 | 照 digest 拉映像：`docker pull <image>@sha256:…` | 已查證[^digest] |
| 7 | SYNOX：個人版也可以選容器（安裝時 `--runtime container`）；`policy.sandbox.engine` 寫 `docker` 或 `auto` | 已實作 |
| 8 | 照驗證清單跑（尤其「Windows 路徑當 `--mount source` 能不能用」「關掉 SYNOX 時容器有沒有跟著停」） | 待實測 |

Windows 特有、要實測的地方：
- `--mount type=bind,source=C:\Users\…` 是否被 Docker Desktop 接受（官方說 Desktop 會在背後把本機路徑分享進 Linux VM，細節在另一頁「Windows 路徑轉換」）[^bind]——**待實測**。
- Windows 上 SYNOX 用 Job Object 包住的是 `docker.exe` 這支**用戶端**，不是容器本身；SYNOX 掛掉時用戶端死了，容器可能還活著（推測）。所以每個容器有固定名字 `synox-<pack>-<人>-<亂數>` 與 label `synox.pack=<pack>`，S4 會補「收掉時先 `docker stop <名字>`」。
- `--userns=keep-id` 是 podman 才有；Docker Desktop 用 `--user 65534:65534`（nobody）。bind mount 的寫入權限在 Desktop 上是模擬的，nobody 寫不寫得進置物櫃**待實測**。

### 4.2 VirtualBox（整台 VM）——下一階段

- 適合：GUI 工具、或「連容器都不放心」的 pack。隔離最強（自己的核心），代價是開機秒到分鐘、記憶體 GB 級。
- 使用者自己下載 VirtualBox 本體（GPLv3）；**不要裝 Extension Pack**（只准個人／教育、不能散布，SYNOX 用不到）[^vboxlic]。
- SYNOX 跟 VM 講話要走 `VBoxManage guestcontrol run --wait-stdout`（不開埠）；能不能當 MCP 長駐管線**待實測**（推測不行，要每次呼叫一個程序）。
- **這一版沒做**：屬於 S7（`VmSandbox`），以及 S6（installer 偵測與引導）。

---

## 5. MCP stdio 長駐程序放進容器

MCP 的 stdio 規格本來就是「client 把 server 當子程序開，stdin 進 JSON-RPC、stdout 出 JSON-RPC、一行一則、stderr 是 log，結束時關 stdin 再 terminate」[^mcp]。所以：

```
SYNOX ──stdin/stdout 管線──▶ podman run --rm -i … <image> python3 /pack/server.py
                              └── 容器裡的 MCP 伺服器（stdout 只准 JSON-RPC）
```

- `-i` 讓 stdin 一直開著；**不加 `-t`**（終端機模式會把換行改成 `\r\n`、把 stdout/stderr 混在一起，JSON-RPC 會壞）——推測，常見做法。
- 不開任何埠、不用 `-p`：管線就是 podman／docker 用戶端程序的 stdin／stdout。
- 容器活多久＝那個用戶端程序活多久：SYNOX 閒置 10 分鐘關 stdin → 伺服器結束 → `--rm` 把容器刪掉（推測，待實測）。
- 已實作：`StdioBackend.open()` 的 argv 經 `box.wrap()`，選了容器的 MCP pack 自動變成上面那一行；`{python}`／`{pack_dir}`／`{user_data_dir}` 換成容器裡的路徑。
- 還沒做（S4）：`close_all` 時用名字 `stop` 容器；Windows 用戶端與容器的壽命對齊；env 指紋加映像 digest。

---

## 6. 容器的誠實限制

- **共用核心**：容器擋得住「一般的壞程式」，擋不住「打核心漏洞的壞程式」。真的不信任→VM（S7）或 gVisor。
- **rootful Docker**：daemon 是 root，SYNOX 帳號在 docker 群組＝SYNOX 被入侵就等於 root。伺服器建議 rootless podman（擁有者 Q2 的決定）。
- **映像內容不看**：SYNOX 只保證「跑的是 digest 那一份」，不保證那一份是好的。
- **有宣告 network 的 pack** 在容器裡可以連外。
- **這台開發機沒有跑過任何一次**：全部旗標只用「比對組出來的字串」測過；每一條都要在實驗室驗（交接單）。

---

## 7. 建議的實作順序

| 順序 | 階段 | 內容 | 在哪驗 |
|---|---|---|---|
| ✅ 1 | S0 | `runtime.container` 第 1 關、Dockerfile 第 2 關、`tier.assess` 帶容器資訊、文件 | 這台（單元測試） |
| ✅ 2 | S1 | `ContainerSandbox`（podman／docker）組 argv、容器內路徑（container view）、`REAL_ISOLATION` 含 container、引擎選擇 | 這台（假 which） |
| ✅ 3 | S2 | 安裝報告「用容器／不用」、`--runtime`、網頁下拉、`packs.lock` 的 `runtime`、`packs runtime` 切換、伺服器版開給成員的條件、doctor 顯示引擎（只用 which） | 這台（假後端） |
| 4 | **S5a 真機驗證（先做）** | 照交接單在 Linux 驗 S0–S2 的旗標；同時驗原本沒驗過的 bwrap／systemd（PERM-7） | 實驗室 Linux |
| 5 | S3 | 映像供應：SYNOX 經 JobRunner 照 digest 拉／用 Dockerfile 建（base 先照 digest 拉）、`env.json` 記 digest、`packs env prune`；容器模式下不建 venv | 這台（假 JobRunner）＋實驗室 |
| 6 | S4 | MCP 長駐容器的收尾：名字 stop、Windows 用戶端壽命、env 指紋含 digest | 這台（假 spawner）＋實驗室 |
| 7 | S6 | installer 偵測與引導（只看檔名、算 SHA-256、使用者貼官方校驗碼、預設「我自己執行」） | 這台（假檔案）＋Windows 實驗室 |
| 8 | S7／S8 | VM 後端（VirtualBox 優先）、AppContainer | 實驗室 |

理由：S3 之前「映像要營運者自己照 digest 拉好」，這樣反而讓第一輪真機驗證最單純（不牽涉 SYNOX 自己下載東西）；驗過旗標真的生效，再讓 SYNOX 自己管映像。

---

[^dockerrun]: Docker docs「docker container run」：`--read-only`、`--cap-drop`、`--security-opt no-new-privileges`、`--pids-limit`、`--memory`、`--memory-swap`、`--cpus`、`--user`、`--pull`（missing／never／always；never＝「Do not pull the image, even if it's missing」）、`--rm`、`-i`、`--tmpfs`、`--mount`、`-e NAME`（沒有 `=` 時「the Docker CLI client checks the value the variable has in your local environment」）。https://docs.docker.com/reference/cli/docker/container/run/ （2026-11-10 讀取）
[^podmanrun]: podman docs「podman-run」：`--network none`（「Create a network namespace for the container but do not configure network interfaces for it」）、`--pull never`、`--read-only`、`--cap-drop … all`、`--security-opt no-new-privileges`、`--pids-limit`、`--memory`、`--env` 沒寫值時看 host 環境、`--tmpfs` 預設 `rw,noexec,nosuid,nodev`、`--mount` 的 `ro／readonly`、`--userns=keep-id`（「the init process within the container will run under the current user's UID」）。https://docs.podman.io/en/latest/markdown/podman-run.1.html
[^bind]: Docker docs「Bind mounts」：bind mount 預設可寫，`readonly`／`ro` 才唯讀；建議用 `--mount`；Docker Desktop 的 daemon 在 Linux VM 裡，Desktop 會把本機路徑分享進去。https://docs.docker.com/engine/storage/bind-mounts/
[^digest]: Docker docs「Image digests」：「Unlike tags, which can be reused or changed, a digest is immutable」；`docker pull <image>@sha256:<digest>`。https://docs.docker.com/dhi/core-concepts/digests/
[^dockergroup]: Docker docs「Linux post-installation steps」：「The docker group grants root-level privileges to the user.」https://docs.docker.com/engine/install/linux-postinstall/
[^rootlessdocker]: Docker docs「Rootless mode」與「Troubleshooting」：要 `newuidmap`／`newgidmap`（uidmap 套件）、`/etc/subuid`／`/etc/subgid`；「cgroup is supported only when running with cgroup v2 and systemd」；cgroup v1 上 `--cpus`、`--memory`、`--pids-limit` 被忽略。https://docs.docker.com/engine/security/rootless/ 、https://docs.docker.com/engine/security/rootless/troubleshoot/
[^podmantut]: podman「Basic Setup and Use of Podman in a Rootless environment」：rootless 要 `/etc/subuid`、`/etc/subgid` 有那個使用者的範圍（`usermod --add-subuids`）；網路用 pasta。https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md
[^podmanrootless]: podman「Shortcomings of Rootless Podman」：「No support for setting resource limits on systems using cgroups v1」；不能綁 1024 以下的埠；家目錄在 NFS／GPFS 不行。https://github.com/containers/podman/blob/main/rootless.md
[^dockerwin]: Docker docs「Install Docker Desktop on Windows」：WSL 2 後端要 Windows 10 22H2（build 19045）以上、WSL 2.1.5 以上、BIOS 開虛擬化、8 GB RAM；「Windows Home or Education editions only allow you to run Linux containers」；第一次開 WSL 2 要管理員；「For checksums, see Release notes」。https://docs.docker.com/desktop/setup/install/windows-install/
[^wsl]: Microsoft Learn「Install WSL」：Windows 10 2004（build 19041）以上；系統管理員 PowerShell `wsl --install` 後重開機。https://learn.microsoft.com/en-us/windows/wsl/install
[^dockerlic]: 見前一份文件 §E2（Docker Subscription Service Agreement）。https://docs.docker.com/subscription/desktop-license/
[^vboxlic]: 見前一份文件 §E2（VirtualBox Licensing FAQ）。https://www.virtualbox.org/wiki/Licensing_FAQ
[^mcp]: MCP 規格 2025-06-18「Transports」：stdio＝client 把 server 當子程序開；stdin／stdout 一行一則 JSON-RPC；stdout 只能是 MCP 訊息；stderr 是 log；結束時關 stdin、終止子程序。https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
