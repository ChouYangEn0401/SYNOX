# 沙盒與 skill 容器化：調查與設計（給擁有者討論）

狀態：**待討論**（這是調查與設計文件，不是實作；沒有改任何程式）
日期：2026-11-10　分支：`feat/doc-sandbox`
標示：**已查證**＝有來源（附連結）；**推測**＝照經驗判斷，沒逐字查到；**待實測**＝要真的跑過才知道；**待查**＝這次沒查到。

---

## 0. 結論先講

| 擁有者的問題 | 一句話答案 |
|---|---|
| (1) 我們有可能自己做沙盒嗎？一定得用別人的？ | **隔離的「牆」一定用作業系統／hypervisor 現成的（Linux namespaces、KVM、Hyper-V…），不能自己寫；SYNOX 能自己做、也應該自己做的是「編排層與政策」**：決定哪個 pack 用哪道牆、牆裡掛什麼、給不給網路、記進 packs.lock、doctor 報告。`src/synox/sandbox.py` 現在就是這一層的雛形（bwrap／systemd 只是「組 argv」），方向對了，接下來是把「容器」和「VM」也加進同一個介面。 |
| (2) 借用 OSWorld 的 VM 概念 | **可以借的是架構形狀**：一個抽象環境（`DesktopEnv`）＋可換的 provider（vmware／virtualbox／docker／aws…）＋「快照→還原」當 reset。**不要借的是連線方式**：OSWorld 在 VM 裡跑一個 HTTP 服務（5000 埠）、再加 VNC／Chrome 除錯埠，這跟 SYNOX「不開埠」的家規相反；SYNOX 要用 stdio（`docker run -i`、`VBoxManage guestcontrol`／`vmrun`）跟裡面講話。 |
| (3) 使用者自己下載 installer，SYNOX 能不能「自己處理掉」 | **能偵測、能引導、預設不代為執行。** SYNOX 不散布別人的安裝檔（Docker Desktop、VirtualBox 擴充包、VMware 都不能重新散布；見 §E）。使用者把 installer 放進 `installers/`，doctor／精靈認得檔名、請使用者從官方頁面貼 SHA-256 比對、再給他一鍵「我自己跑」或「請 SYNOX 替我啟動（逐步確認）」。 |
| (4) 要求每個 skill（pack）提供 Docker 化方式；裝好後可選「用容器／不用」 | **建議：pack.json 加 `runtime.container`；個人版「建議提供」、伺服器版的第三方 pack 與所有 T2 pack「沒提供就只給擁有者」（沿用現在 PERM-7 的機制，不是拒裝）。** 安裝報告上選「用容器／不用」，記進 `packs.lock`；SYNOX 新增一個 `container` 沙盒後端，kind=cli 與 kind=mcp stdio 都走同一個 `box.wrap()`。 |

**建議路線（§F 詳細）**：先做 Linux 伺服器上的 `container` 後端（rootless podman 優先、Docker 次之）＋ pack.json 欄位＋安裝選項；再做 Windows 開發機的 Docker Desktop（WSL2）偵測與引導；VM 後端（VirtualBox／VMware）排最後、只給「GUI 或完全不信任的工具」。這台開發機只用假後端測 argv；真容器、真 VM 一律到別台機器驗。

**最想先請擁有者決定的 3 題**（全部 6 題在 §G）：
1. 容器要求的強度：所有 pack 強制、還是「建議＋伺服器版第三方／T2 強制」（建議後者）。
2. 容器引擎的首選：Linux 伺服器用 rootless podman 還是 Docker（建議 podman 優先、兩者都支援）。
3. 這台開發機要不要裝 Docker Desktop 來測（Docker Desktop 本身與官方 base image 都是「網路上抓來的東西」；建議：裝可以，但只跑 SYNOX 自己建、`FROM` 官方 Python 映像的測試容器，第三方 pack 的映像仍不在這台跑）。

---

## A. 「自己做沙盒」的現實

### A1. 作業系統提供的隔離積木

| 積木 | 在哪 | 擋什麼 | 不擋什麼／代價 | 狀態 |
|---|---|---|---|---|
| **Linux namespaces**（pid／net／mnt／user／ipc／uts） | Linux 核心 | 看不到別的程序、沒有網路介面、只看得到掛進來的檔案 | 核心本身是共用的：核心漏洞＝整台被穿。user namespace 要核心允許非 root 建立 | 已查證（bubblewrap README：靠 user namespaces 讓任何使用者都能用）[^bwrap] |
| **seccomp** | Linux 核心 | 限制能叫哪些系統呼叫（縮小核心的攻擊面） | 政策要自己寫、寫錯就程式跑不起來 | 已查證（bubblewrap 支援傳入 seccomp 過濾器）[^bwrap] |
| **cgroups** | Linux 核心 | 記憶體、CPU、程序數上限 | 不是隔離，是資源限制 | 已查證（systemd-run 的 MemoryMax／TasksMax 就是這個；現有 `SystemdSandbox`） |
| **Job Object** | Windows 核心 | 記憶體、程序數、整組一起結束 | **不限制檔案與網路**（現有 `JobObjectSandbox` 的文件已經說明） | 已查證（現有程式） |
| **AppContainer／受限 token** | Windows 核心 | 檔案、登錄檔、網路、憑證、裝置、視窗都預設拒絕，用 capability 開回（例如 `internetClient`） | 要對每個要碰的資料夾加 ACL；Python 直譯器在 AppContainer 裡能不能正常跑**待實測**；SYNOX 現在只有介面 | 已查證（Microsoft：AppContainer 的檔案、網路、程序、憑證隔離）[^appcontainer] |
| **Hypervisor（KVM、Hyper-V、VirtualBox、VMware）** | 硬體虛擬化 | 整個作業系統都是另一份：核心漏洞也穿不過（要靠 hypervisor 漏洞） | 開機秒級、記憶體 GB 級；GUI 可以；這台 Windows 10 Home **沒有 Hyper-V**，VirtualBox 可以 | 已查證（Windows Sandbox／Hyper-V 不支援 Home）[^wsb] |
| **gVisor（runsc）** | Linux，接在 Docker／Kubernetes 上 | 在使用者空間重做一個 Linux 核心（Sentry，Go 寫的），容器叫的系統呼叫先到它，不直接到真核心 | 不是每個系統呼叫、`/proc`、`/sys` 都有，可能不相容；只有 Linux | 已查證[^gvisor] |
| **Firecracker（microVM）** | Linux＋`/dev/kvm`，x86_64／aarch64 | 每個工作一個迷你 VM，有自己的核心，啟動約一百多毫秒 | 要 KVM（雲端要 `.metal` 機型）；沒有 Windows 版 | 已查證（Firecracker getting-started）[^firecracker] |

### A2. 我們能自己寫的是哪一層

```
┌────────────────────────────────────────────────────────────┐
│ SYNOX 能自己寫的：編排層＋政策層                             │
│  • 看 pack.json 決定：哪個後端、掛哪些資料夾、給不給網路、    │
│    記憶體上限、timeout、stdio 怎麼接                        │
│  • 記進 packs.lock（用了哪個映像、哪個 digest、誰確認的）     │
│  • doctor／安裝報告：這台有哪些引擎、哪個 pack 跑在哪裡        │
│  • fail closed：要隔離卻沒有 → 只給擁有者                    │
├────────────────────────────────────────────────────────────┤
│ 借現成的：牆本身                                            │
│  bwrap／systemd-run／podman／docker／VBoxManage／vmrun／     │
│  Job Object／AppContainer API                               │
├────────────────────────────────────────────────────────────┤
│ 絕對不碰：核心層                                            │
│  namespaces、seccomp、KVM、Hyper-V 的實作                   │
└────────────────────────────────────────────────────────────┘
```

**為什麼從零寫核心級隔離不切實際且危險**（推測，但業界共識）：
- 隔離的保證來自核心或 hypervisor 的程式碼，那些是幾十萬行、被幾千人盯了幾十年的東西；自己寫的版本沒人審、沒人打過、漏洞只有攻擊者會先找到。
- 「做得到隔離」和「證明它真的隔離」是兩件事：bubblewrap 自己的 README 都說它「不是一個現成的、有固定安全政策的沙盒」，保護強度完全看呼叫它的人傳什麼參數[^bwrap]。連專門做這件事的工具都把責任交給政策層，SYNOX 該做的也是把政策寫對、寫清楚，不是再造一道牆。
- SYNOX 的價值在「pack 作者寫一次宣告，使用者在報告上看得懂、決定得了」，那是編排層與政策層的事。

**現狀對照**：`src/synox/sandbox.py` 已經是這個形狀（`Sandbox.wrap(argv, env, cwd, grants)`、`grants_for` 從宣告算範圍、`resolve` 挑後端、`restricted_reason` fail closed）。要加的是兩個新後端（`container`、`vm`）和 pack.json 的對應欄位，不是推翻。

---

## B. 後端比較表

欄位說明：「隔離強度」1～5（5＝整個 OS 都是另一份）；「Win Home 可行」指這台開發機（Windows 10 Home，沒有 Hyper-V）；「Linux VPS 可行」指多人伺服器；「實作難度」指 SYNOX 這邊要寫多少。

| 後端 | 隔離強度 | 啟動延遲 | 資源成本 | Win Home 可行 | Linux VPS 可行 | 使用者要自己下載的元件與授權 | SYNOX 實作難度 | 備註 |
|---|---|---|---|---|---|---|---|---|
| `none`（現有） | 0 | 0 | 0 | 是 | 是 | — | 已有 | 不是隔離 |
| `jobobject`（現有） | 1（只限資源） | ～0 | 0 | 是 | 否 | — | 已有 | 檔案、網路不擋 |
| **bwrap**（現有，Linux） | 3 | 毫秒 | 幾乎 0 | 否（WSL2 裡可以，但那是另一台機器） | 是（要核心允許非 root user namespace） | `bubblewrap` 套件（LGPL，發行版自帶） | 已有（未真機驗證） | 共用核心；網路只有「斷／不斷」 |
| **systemd-run**（現有，Linux） | 3 | 毫秒～百毫秒 | 幾乎 0 | 否 | 是（要能開 system 或 user 服務） | systemd（發行版自帶） | 已有（未真機驗證） | 同上；user 服務的 PrivateNetwork 在舊系統可能不生效（現有註解） |
| **rootless podman**（Linux） | 3.5 | 百毫秒～秒 | 低（映像幾十～幾百 MB） | 否（WSL2 裡可以） | **是（建議）** | `podman`（Apache-2.0，發行版自帶）；映像另算 | 中：組 `podman run` argv＋映像管理＋digest | 沒有 root daemon：容器逃出也只是普通使用者[^podman]；OCI 映像跟 Docker 共用 |
| **Docker Engine**（Linux） | 3 | 百毫秒～秒 | 低 | 否 | 是 | Docker Engine（Apache-2.0）；映像另算 | 中（跟 podman 同一組 argv，差 daemon） | daemon 是 root：能用 docker socket 的人等於 root[^podman]；rootless 模式可開但不是預設 |
| **Docker Desktop on Windows（WSL2）** | 3（在 WSL2 的 Linux VM 裡）＋ VM 一層 | 秒級（WSL2 VM 要先起來） | 中（WSL2 VM 常駐記憶體 GB 級） | **是**（Home 要 WSL2 後端，Win10 21H2／build 19044 以上）[^dockerwin] | 不適用 | **Docker Desktop**：個人、教育、非商業開源、250 人以下且年營收 1000 萬美元以下的公司免費；超過要付費[^dockerlic]。**不能由 SYNOX 散布** | 中：同 Docker，另加「偵測 Desktop 在不在、WSL 起來沒」 | 開發機測試用；要被歸類成「網路上抓來的東西」還是「開發工具」請擁有者決定（§G Q3） |
| **VirtualBox VM** | 5 | 10 秒～分鐘（快照還原較快） | 高（每個 VM 記憶體 GB、磁碟 GB） | **是**（不需要 Hyper-V） | 是（VPS 要巢狀虛擬化，常常沒有） | **VirtualBox 本體 GPLv3，可以重新散布；Extension Pack 是 PUEL，只准個人／教育用，不准重新散布，試用期已取消；商用要 Enterprise 授權**[^vboxlic] | 高：映像製作、`VBoxManage` 編排、快照、guestcontrol | SYNOX 用不到 Extension Pack（USB 2/3、RDP、磁碟加密才需要）——**文件要寫清楚「不要裝擴充包」** |
| **VMware Workstation Pro** | 5 | 同上 | 高 | 是 | 是（同樣要巢狀虛擬化） | **17.5.2 起個人、教育、商用都免費，不需金鑰；下載要 Broadcom 帳號**[^vmwarelic]。不能由 SYNOX 散布 | 高：`vmrun` 編排（OSWorld 就是這樣做） | 跟 VirtualBox 二選一即可；OSWorld 預設用它 |
| **Windows Sandbox** | 5（Hyper-V 容器） | 秒級 | 中 | **否（Home 不支援）**[^wsb] | 不適用 | Windows Pro／Enterprise／Education 內建 | 低（`.wsb` 檔）但每次都是全新、不能存狀態 | 開發機用不到；之後給 Pro 使用者可以當選項 |
| **AppContainer**（Windows） | 2.5 | ～0 | 0 | 是 | 不適用 | 內建 | **高**：Win32 API（`CreateAppContainerProfile`＋`SECURITY_CAPABILITIES`）、每個資料夾加 ACL、Python 在裡面能不能跑待實測 | 現在只有介面；是 Windows 個人版唯一「不裝別人的東西」的真隔離路 |
| **gVisor**（Linux，接在 Docker／podman 上） | 4 | 毫秒～百毫秒 | 低 | 否 | 是（要裝 runsc） | gVisor（Apache-2.0） | 低（在 container 後端多一個 `--runtime=runsc` 開關） | 相容性有缺口[^gvisor]；當「容器後端的加強選項」最划算 |
| **Firecracker** | 5 | 約 125 ms（來源不一致，待實測） | 低～中 | 否 | 要 `/dev/kvm`（VPS 通常沒有；實驗室實體機可以） | Firecracker（Apache-2.0） | 高：要自己準備 rootfs、kernel、vsock 通訊 | 對 SYNOX 現階段過重；記下來當未來選項 |
| **雲端容器／沙盒服務**（例如 OSWorld 接的 Modal、Daytona） | 5（在別人的機器上） | 秒級 | 按用量付費 | 是（只是打 API） | 是 | 帳號、API key | 中 | 跟「資料不出這台」的設計相衝（pack 的資料、secret 要送出去）；只適合「完全不碰使用者資料」的工具 |

**推測的排序（給 SYNOX）**：Linux 伺服器：rootless podman ＞ Docker ＞ bwrap（已有，保留）＞ systemd（已有，保留）；要再硬一點加 gVisor。Windows 個人版：Docker Desktop（使用者自己裝）＞ AppContainer（未來）＞ jobobject（現有，只限資源）。VM 只給 GUI 或「不信任到連容器都不放心」的工具。

---

## C. OSWorld 的做法（只寫查到的）

來源：OSWorld 的 `README.md`、`SETUP_GUIDELINE.md`、`desktop_env/desktop_env.py`、`desktop_env/providers/__init__.py`、`providers/docker/provider.py`、`providers/vmware/manager.py`（2026-11-10 讀取）[^osworld]。

### C1. 架構（已查證）

- **`DesktopEnv`**：Gym 風格的環境物件，包住一台 VM。建構時 `create_vm_manager_and_provider(provider_name, region)` 拿到一對 **Manager（管映像、下載、登記哪台 VM 空著）＋ Provider（開機、關機、拿 IP、快照、還原）**。
- **`provider_name`**（`providers/__init__.py`）：`vmware`（預設）、`virtualbox`、`aws`、`azure`、`docker`、`aliyun`、`volcengine`、`fastvm`、`daytona`、`modal`、`pyromind`，共 11 種；不認得的名字丟 `NotImplementedError`。providers 資料夾裡另有 `gcp`（`__init__` 沒列，待查）。
- **快照／還原**：`snapshot_name` 預設 `"init_state"`；`reset()` 呼叫 `provider.revert_to_snapshot(path, "init_state")`，再重開、重做任務設定（最多重試 5 次）。`vmware`／`virtualbox` 被標成「髒的開始」（要先還原），`docker`／雲端是「乾淨的開始」（每次全新容器）。
- **VM 內的控制服務與埠**：VM 裡跑一個 HTTP 伺服器，`server_port = 5000`（`PythonController` 經它截圖、拿 accessibility tree、執行 Python／指令；`SetupController` 經它上傳檔案、下指令）；另有 `chromium_port = 9222`（Chrome 遠端除錯）、`vnc_port = 8006`、`vlc_port = 8080`。AWS 版再開 5910（noVNC）、22、80、8081。guest 密碼預設 `"password"`（AWS 版 `"osworld-public-evaluation"`）。

### C2. 映像怎麼取得與重置（已查證）

- **VMware**：Manager 從 Hugging Face `xlangai/ubuntu_osworld`（`Ubuntu-x86.zip`／`Ubuntu-arm.zip`）、`xlangai/windows_osworld`（`Windows-x86.zip`）下載（支援續傳），解到 `./vmware_vm_data/<名字>/`，改寫 `.vmx`（新 UUID、MAC），用 `vmrun -T ws start … nogui` 開機、`getGuestIPAddress -wait` 拿 IP、等 `:5000/screenshot` 回應後 `vmrun snapshot … init_state`。VM 的登記寫在 `.vmware_vms` 檔（每行 `路徑|free或PID`）＋檔案鎖。**程式不檢查 `vmrun` 裝了沒**，只在 Windows 把預設安裝資料夾加進 PATH；沒裝就是一連串失敗。
- **Docker**：固定用映像 `happysixd/osworld-docker`，把 `.qcow2` 磁碟**唯讀**掛進 `/System.qcow2`，有 `/dev/kvm` 就傳進去（沒有就 `KVM=N` 並警告），設 `RAM_SIZE`／`CPU_CORES`／`DISK_SIZE`；也就是說 **Docker 這條其實是「容器裡再跑一個 QEMU VM」**，容器只是包裝。埠 8006／5000／9222／8080 從本機找空埠對應出來；每秒打 `http://localhost:<port>/screenshot`，300 秒內沒回 200 就放棄並刪容器。
- **README 對使用者的要求**：「Install VMware Workstation Pro」並設定 `vmrun`，連到 VMware 官方下載頁（另有 `INSTALL_VMWARE.md`）；VirtualBox 是「VMware 有問題時的替代」；Docker 這條「建議有 KVM」、macOS 通常沒有。「setup script 會自動下載需要的虛擬機並設定環境」——**映像是他們自己做的、自己放在 Hugging Face，所以可以自動下載；hypervisor 是別人的，請使用者自己裝。** 這正是擁有者要的分法。
- `SETUP_GUIDELINE.md` 本身講的是 Google 帳號、代理、AWS 評測平台，**沒有**講 VM 安裝步驟與授權（待查：`INSTALL_VMWARE.md` 這次沒讀）。

### C3. 哪些適合 SYNOX、哪些不適合

| OSWorld 的概念 | 適合？ | 說明 |
|---|---|---|
| Manager＋Provider 拆開、`provider_name` 字串選後端 | **適合** | 跟 `sandbox.resolve()` 同形；建議 SYNOX 的 `vm` 後端也拆成「映像管理」與「開機／快照／執行」兩個物件 |
| 「快照 `init_state` → 每次還原」當 reset | **適合（VM 後端）** | 給 GUI／不可信工具：每次呼叫都從乾淨快照開始，呼叫完丟掉。容器後端用「每次新容器」達到同樣效果 |
| hypervisor 由使用者自己裝、映像由專案自己發 | **適合** | SYNOX 可以自己建並發布「SYNOX 基底映像」（Debian＋Python，我們自己 build、自己簽），但 Docker Desktop／VirtualBox／VMware 一律引導使用者去官方下載 |
| VM 裡跑 HTTP 服務（5000）＋ VNC／Chrome 除錯埠 | **不適合** | 違反「不開埠」；而且 guest 的 HTTP 服務沒有認證（靠密碼 `password`）。SYNOX 改走 stdio：容器用 `docker run -i`／`podman run -i`（stdin／stdout 就是管線）；VM 用 `VBoxManage guestcontrol run --wait-stdout --wait-stderr`（VirtualBox）或 `vmrun -gu/-gp runProgramInGuest`（VMware）。**VirtualBox guestcontrol 的 stdin 能不能當 MCP 的長駐管線用：待實測**（推測不行，要改成「每次呼叫一個程序」或在 VM 裡跑一個 stdio 轉接程式） |
| 預設 guest 密碼、以 root 跑 | 不適合 | SYNOX 的映像要用非 root 使用者、沒有密碼登入路徑 |
| 從 Hugging Face 自動下載 GB 級映像 | 部分適合 | SYNOX 自己的基底映像可以自動下載（固定 digest、HTTPS、顯示大小、要確認）；第三方 pack 的映像只能從它宣告的來源、固定 digest（§D4） |
| 雲端 provider（AWS、Modal、Daytona…） | 現階段不適合 | pack 的資料和 secret 要送到別人的機器；跟 security.md「資料在哪」的承諾相衝。記成未來選項 |

---

## D. skill 容器化機制設計

### D1. 目標與原則

- **一個介面**：kind=cli 與 kind=mcp stdio 的子程序都經現有的 `box.wrap(argv, env, cwd, grants)`；容器只是另一個 `Sandbox` 子類別（`ContainerSandbox`），回來的 argv 一樣「以原本的 argv 結尾」（JsonCli 在後面接子指令）。
- **宣告在 pack.json、決定在安裝報告、記錄在 packs.lock**：跟 trust、publisher 一樣的三段式。
- **容器是「真隔離」的一種**，跟 bwrap／systemd 並列進 `REAL_ISOLATION`；伺服器版「第三方 cli／mcp pack 沒真隔離只給擁有者」的規則不變，只是多一條路可以滿足它。
- **映像不在這台開發機 build**；伺服器上 build 也只在擁有者確認之後、經 JobRunner、有 log。

### D2. pack.json 新欄位：`runtime.container`

```json
"runtime": {
  "container": {
    "image": "ghcr.io/example/weather-tool@sha256:3b1c…（64 個 16 進位字）",
    "dockerfile": "./Dockerfile",
    "base": "docker.io/library/python:3.12-slim@sha256:9f2e…",
    "entry": "stdio",
    "network": false,
    "resources": {"mem_mb": 512, "cpus": 1, "pids": 64},
    "mounts": {"user_data": "/data/user", "shared_data": "/data/shared", "pack": "/pack"},
    "env_passthrough": ["WEATHER_API_KEY"],
    "user": "nonroot"
  }
}
```

| 欄位 | 必填 | 規則（第 1 關） |
|---|---|---|
| `image` | `image`／`dockerfile` 二擇一（可以都寫：有 `image` 先用，沒拉到才 build） | **一定要帶 `@sha256:` digest**；只收 tag 不收。registry 主機白名單（`docker.io`、`ghcr.io`、`quay.io`；擁有者可在 config 加）。不收 `localhost`、IP、`http://` |
| `dockerfile` | 同上 | pack 資料夾裡的相對路徑（跟 `skill`、`web.panel` 同規則：不准 `..`、不准絕對路徑、不准網路路徑）。**進 packs.lock 的雜湊**（它就是 pack 的檔） |
| `base` | 有 `dockerfile` 時必填 | Dockerfile 的 `FROM` 一定要跟這裡一字不差，而且帶 digest；第 2 關掃 Dockerfile：只准一個 `FROM`、不准 `--network`、不准 `ADD <網址>`、`RUN` 裡的 `curl｜wget｜pip install` 列進報告（提醒不是門） |
| `entry` | 否 | `stdio`（預設；容器的 stdin／stdout 就是 cli／MCP 的管線） |
| `network` | 否 | 預設 `false`（`--network none`）。要 `true` 一定要跟 `capabilities` 的 `network` 一致（一邊有一邊沒有＝拒） |
| `resources` | 否 | 沒寫＝`policy.sandbox` 的 `mem_mb`／`max_procs`；pack 寫的只能**比政策小**，大於政策＝用政策的值並在報告標出 |
| `mounts` | 否 | 只能改「容器裡的路徑」，**不能指定本機路徑**；本機那端一律由 `grants_for` 算（data=user → `<user_data_dir>/<pack>` 可寫；shared → `data/packs/<pack>`；pack 資料夾、`data/envs/<pack>` 唯讀）。沒宣告的本機資料夾根本不掛 |
| `env_passthrough` | 否 | 只能是 `requires.env`／`auth.fields[].env` 已列的名字（同現在的 `keep_env` 規則）；值走 `--env-file`（暫存檔，權限 600，用完刪）或 stdin，**不進 argv** |
| `user` | 否 | `nonroot`（預設：`--user 65534:65534` 或映像自己的非 root 使用者）；`root` 一律拒 |

**容器內的代換**：`{python}`、`{pack_dir}`、`{user_data_dir}`、`{data_dir}` 在容器模式下換成容器裡的路徑（`/pack`、`/data/user`、`/data/shared`），由 loader 的 placeholders 多一組「container view」；`SYNOX_*` 環境變數同樣換成容器內路徑。這樣 pack 的 argv 不用改兩份。

### D3. 作者端要求：強制還是建議

| 方案 | 內容 | 優點 | 缺點 |
|---|---|---|---|
| A 全部強制 | 每個 pack 都要 `runtime.container` 才裝得了 | 最一致 | 出廠 pack（notes、money）是 kind=python、在程序裡跑，容器包不到；T0（connector、遠端 MCP）沒有程式可包；個人 Windows 使用者沒裝 Docker 就什麼都裝不了。**不切實際** |
| **B 建議＋分級強制（建議）** | 所有 kind=cli／mcp stdio 的 pack「建議」提供；**伺服器版的第三方 pack 與所有 T2 pack：沒提供（而且這台也沒有 bwrap／systemd）→ 只給擁有者**（沿用 `restricted_reason`）；個人版照用、doctor 提醒 | 跟現有政策完全同形；作者有動機提供；不擋個人版 | 作者可能偷懶不給；靠報告與 doctor 推 |
| C 只建議 | 有就用、沒有就算了 | 最鬆 | 伺服器版拿不到好處 |

另外建議：**synox-sdk `init` 產生的樣板一律附 Dockerfile**（`FROM python:3.12-slim@sha256:…`、複製 pack、非 root 使用者、`ENTRYPOINT ["python", "/pack/tool.py"]`），讓「提供容器化」是預設而不是額外功課。`synox-sdk check` 檢查 Dockerfile 與 `runtime.container` 一致。

### D4. 安裝時的選項與記錄

安裝報告（網頁、終端機）多一段「🧱 執行環境」：

```
🧱 執行環境
  這台可用的後端：podman（rootless）✅、docker ❌（沒裝）、bwrap ✅
  這個 pack 提供容器：是（image ghcr.io/example/weather-tool@sha256:3b1c…，network: false，512 MB）
  要怎麼跑：  (•) 用容器（建議）   ( ) 不用容器，直接在這台跑（bwrap）   ( ) 不用容器、不隔離（只有個人版可選）
```

- 終端機：`python -m synox install <檔> --yes --runtime container|host|none`。
- **記進 `packs.lock`**：`"runtime": {"mode": "container", "backend": "podman", "image": "ghcr.io/…", "digest": "sha256:3b1c…", "built_from": null | {"dockerfile_sha256": "…", "base_digest": "…", "built_at": "…"}, "chosen_by": <tg_id>}`。
- **升級時**：映像 digest 變了、`network` 從 false 變 true、`resources` 變大、`mounts` 多了、`user` 變了 → 紅字（跟現有 `upgrade.py` 的「權限變大」同一個機制）。
- **切換**：`python -m synox packs runtime <name> container|host`（只有擁有者）；切換也寫鎖、也走 doctor。
- **信任政策的關係**：
  - `trust: third-party` ＋ 伺服器版 ＋ 沒選容器又沒 bwrap／systemd → 只給擁有者（現有規則）。
  - **T2 pack 選了容器 → 可以給成員**（這是容器帶來的實質放寬；T2 的 publisher 確認照舊）。
  - **T2 的 python pack 仍然只給擁有者**（在 SYNOX 程序裡跑，容器包不到；要給成員得改寫成 cli 或 mcp stdio）。
  - 個人版選「不隔離」照舊可用，doctor 提醒。

### D5. 映像供應鏈風險與對策

| 風險 | 對策 | 狀態 |
|---|---|---|
| 作者指的映像被換掉（tag 漂移） | 只收 `@sha256:` digest；拉下來之後再比一次 digest（`podman image inspect`） | 推測可行，待實測 |
| 基底映像被換掉 | `base` 一定帶 digest；build 時 `--pull=never` 搭配事先 `pull <base>@digest` | 推測可行 |
| Dockerfile 裡偷連別處下載程式 | 第 2 關掃 Dockerfile（§D2）；build 時 `--network none` 做不到就至少**記錄**；pip 在 Dockerfile 裡的來源 SYNOX 管不到 → 報告寫「映像內容 SYNOX 不看，跟 npm 套件一樣」 | 文件語氣沿用「提醒不是門」 |
| 映像本身是惡意的 | 容器仍然是牆：`--network none`（除非宣告）、只掛 grants 的資料夾、`--read-only`、`--cap-drop ALL`、`--security-opt no-new-privileges`、`--pids-limit`、`--memory`、非 root。惡意映像能做的就是在自己的資料夾裡亂寫 | 待實測（每個旗標在 podman／docker 的行為） |
| 在這台開發機 build 或 run | **不做。** 開發機只測「組出來的 argv」（跟 bwrap 一樣用假後端）。真 build 在伺服器上，經 JobRunner、10 分鐘上限、log 進 `data/job_logs/` | 政策 |
| Docker daemon 是 root（docker socket＝root） | 伺服器優先 rootless podman；用 Docker 時 doctor 寫一行「docker 群組等於 root，SYNOX 的帳號在裡面」 | 已查證[^podman] |
| 映像膨脹、磁碟吃光 | `packs env rebuild`／`packs env prune`；doctor 列每個 pack 的映像大小 | 推測 |

### D6. 跟現有機制的關係

| 現有 | 容器化之後 |
|---|---|
| **T0／T1／T2** | 不變。容器只影響「執行期在哪跑」，不改變「掃得到多少」。T2 仍要輸入 publisher |
| **PERM-7 `policy.sandbox`** | `backend` 多兩個值：`container`（引擎由 `policy.sandbox.engine: auto|podman|docker` 決定）、`vm`（未來）。`auto` 在 Linux 伺服器版：podman → docker → bwrap → systemd → none。`REAL_ISOLATION` 加 `container`、`vm` |
| **`grants_for`** | 不變：read／write／network／mem／procs 就是 `-v …:ro`、`-v …:rw`、`--network none`、`--memory`、`--pids-limit` 的來源。`hide` 在容器裡天然成立（沒掛就看不到） |
| **`envs.py` 自動建置**（`runtime.python: auto` 建 venv） | 有 `runtime.container` 時 **venv 不建**（套件在映像裡）。`Builder.plan()` 多一種計畫：「拉映像 X（digest…）」或「用 Dockerfile 建映像」，同樣經 JobRunner、同樣寫 `data/envs/<pack>/env.json`。`env_problem()` 多一種：「映像不在／digest 不符」 |
| **`packs.lock`** | 多 `runtime` 區塊（§D4）；Dockerfile 本來就在雜湊裡 |
| **LiveCheck**（呼叫前再對鎖） | 容器模式下多比一次「本機映像的 digest 還是鎖裡那個」（便宜：`podman image inspect` 一次，快取 10 分鐘，跟 `FULL_EVERY` 同節奏） |
| **MCP stdio 長駐程序**（`McpPool`） | `StdioBackend.open()` 的 `Popen(argv)` 裡的 argv 已經過 `box.wrap`，所以 `podman run -i --rm … <argv>` 自然就是長駐容器：stdin／stdout 是管線、容器活到程序結束。閒置回收＝`popen.terminate()` → 容器 `--rm` 自己消失；Windows 的 Job Object 包的是 `docker.exe` 用戶端程序，**不是**容器本身——所以回收要改成「先 `docker stop <name>` 再 kill 用戶端」：每個容器給固定名字 `synox-<pack>-<tg_id>-<nonce>`，`close_all` 時逐一 stop。**待實測**：`docker run -i` 在 Windows 用戶端 stdin 關閉時容器會不會跟著結束 |
| **`PerUserScope`**（每人一個程序） | 每人一個容器，掛的 `user_data` 是那個人的；`SharedScope` 仍然只有介面 |
| **確認來回**（`SYNOX_CONFIRMED`、`_meta`） | 不變：環境變數照 `env_passthrough` 規則進容器（這兩個名字由 SYNOX 固定放行） |
| **doctor** | 多列：引擎有沒有、版本、rootless 與否、每個 pack 的 runtime 模式與映像 digest、映像在不在 |

### D7. `ContainerSandbox.wrap()` 組出來的 argv（示意，待實測）

```
podman run --rm -i --name synox-weather-123-ab12 \
  --network none --read-only --tmpfs /tmp:rw,size=64m \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 512m \
  --user 65534:65534 \
  -v /srv/synox/packs/weather:/pack:ro \
  -v /srv/synox/data/users/123/weather:/data/user:rw \
  --env-file /run/synox/env-ab12 \
  -w /pack \
  ghcr.io/example/weather-tool@sha256:3b1c… \
  python /pack/tool.py          ← 原本的 argv（代換成容器內路徑）
```

Docker 同一組旗標（`docker run`）。Windows 上的 `-v` 本機路徑要轉成 Docker Desktop 認得的形式（`C:\…` 直接可用；WSL2 後端會經 9p 分享，效能較差——推測）。

---

## E. 「installer 自己處理掉」：偵測、引導與授權

### E1. 流程（建議）

```
使用者把安裝檔放進 <SYNOX>/installers/   （或精靈／doctor 顯示「把檔案放這裡」）
        │
        ▼
doctor／精靈「沙盒引擎」頁
  1. 偵測已裝的引擎：PATH 上的 docker／podman／VBoxManage／vmrun；Windows 另看
     `wsl --status`、登錄檔的 Docker Desktop 安裝紀錄。已裝 → 顯示版本，結束。
  2. 偵測 installers/ 裡的檔案：只看檔名樣式（Docker Desktop Installer.exe、
     VirtualBox-7.x.x-*-Win.exe、VMware-workstation-full-17.x.x-*.exe、
     Oracle_VirtualBox_Extension_Pack-*.vbox-extpack）與大小。認不得的檔不理。
  3. 請使用者從官方頁面貼 SHA-256（顯示官方校驗頁的連結），SYNOX 本機算一次比對；
     不符＝紅字、不往下走。沒有貼＝黃字「沒驗過」、也不往下走（預設）。
  4. 給三個按鈕：
     (•) 我自己執行（SYNOX 顯示要跑的指令與建議選項，不動手）        ← 預設
     ( ) 請 SYNOX 替我啟動安裝程式（逐步：顯示指令 → 擁有者按確認 → 開視窗跑，
         不用靜默旗標、不加 --quiet，裝完回來按「重新偵測」）
     ( ) 略過，現在不裝（pack 照 host／none 模式跑，doctor 持續提醒）
  5. 裝好 → 重新偵測 → 寫 config.json policy.sandbox.engine。
```

- **Extension Pack 特別處理**：偵測到 `.vbox-extpack` 就顯示「SYNOX 不需要擴充包；它的授權只准個人／教育用途，商用要另買」，不提供安裝按鈕。
- **不做的事**：不內建任何第三方安裝檔；不從網路替使用者下載 installer（連「幫你開下載頁」都只是開瀏覽器）；不靜默安裝；不改防火牆（Docker Desktop／VirtualBox 安裝時自己會加規則，那是它們的事，SYNOX 不碰）；不在偵測步驟執行任何 installer（只讀檔名、大小、算雜湊）。
- **校驗碼來源**：VirtualBox 官方有每版的 `SHA256SUMS`（推測記得網址在 `virtualbox.org/download/hashes/<版本>/`，待確認）；Docker Desktop 的校驗碼在 release notes 或下載頁（待查）；VMware 在 Broadcom 下載頁顯示（待查）。無論如何都是「使用者貼上」，SYNOX 不自己去抓（抓了也是從網路來的、沒比較可信）。

### E2. 授權／散布注意事項

| 元件 | 查到的條件 | 對 SYNOX 的意義 | 狀態 |
|---|---|---|---|
| **Docker Desktop** | 「Docker Subscription Service Agreement」：250 人以下**且**年營收 1000 萬美元以下的公司、個人非商業、學生與學術機構、非商業開源專案免費；較大的組織、公部門與政府、超出免費範圍的商用要付費訂閱。授權按使用者算，不按機器 | 個人版使用者多半免費；**學校實驗室（學術機構）免費**；公司使用者要自己看。SYNOX 的文件要寫一句「請確認你符合 Docker 的免費條件」，不能替人判斷。不能重新散布安裝檔 | 已查證[^dockerlic] |
| **Docker Engine（Linux）** | Apache-2.0 | 伺服器版沒有授權問題 | 已查證（常識；docs.docker.com/engine） |
| **podman** | Apache-2.0，發行版套件 | 沒有授權問題 | 已查證（常識） |
| **VirtualBox 本體** | GPLv3，可以重新散布 | 理論上 SYNOX 可以帶，但**建議仍由使用者自己下載**（省掉版本維護與我們替它背書的問題） | 已查證[^vboxlic] |
| **VirtualBox Extension Pack** | PUEL：只准個人（單一主機、非商業）與教育用；**30 天試用已取消**；**不准重新散布**；商用要 Enterprise 授權（Named User 最少買 100 套） | **SYNOX 的 VM 後端設計成不需要擴充包**（不用 USB 直通、RDP、磁碟加密）；文件明寫「不要裝擴充包」 | 已查證[^vboxlic] |
| **VMware Workstation Pro／Fusion Pro** | Broadcom 2024-11-11 公告：17.5.2／13.5.2 起**商用、教育、個人都免費**，不需要金鑰；下載要 Broadcom Support Portal 帳號 | 使用者自己到 Broadcom 下載（要註冊帳號）；SYNOX 不能散布 | 已查證[^vmwarelic] |
| **Windows Sandbox** | Windows Pro／Enterprise／Education 內建；**Home 不支援** | 這台開發機用不到；Pro 使用者未來可以當選項 | 已查證[^wsb] |
| **gVisor、Firecracker、bubblewrap** | Apache-2.0／LGPL，發行版或 GitHub | 伺服器上由營運者裝 | 已查證（專案頁） |
| **SYNOX 自己的基底映像** | 我們自己 build（`FROM python:3.12-slim@sha256:…`），AGPL 的核心不進映像（映像只放 pack 的執行環境），可以自己發 | 等同 OSWorld 自己發 VM 映像 | 推測（LICENSING.md 要補一段） |

---

## F. 建議路線與分階段計畫

每一階段都設計成「一個 opus 5.5-medium agent 可以獨立做完、有測試、不改 vendor」。標示：🖥️＝這台 Windows 開發機用假後端可測；🐧＝一定要到 Linux 伺服器（學校實驗室）驗；🪟＝要一台有 Docker Desktop／VirtualBox 的 Windows 機器驗（不是這台）。

| 階段 | 做什麼 | 產出 | 測試 | 前置 |
|---|---|---|---|---|
| **S0 文件與欄位** 🖥️ | pack.json `runtime.container` 的第 1 關規則（`manifest.py`）、Dockerfile 的第 2 關掃描（`scan.py`：單一 FROM、digest、ADD 網址、RUN 列出）、`pack-format.md` 新段、`tier.assess` 對 `runtime.container` 的處理（不改 tier） | 欄位進 manifest、掃描 finding、文件 | 純單元測試（假 pack） | 擁有者決定 Q1、Q2 |
| **S1 `ContainerSandbox`** 🖥️ | `sandbox.py` 新增 `ContainerSandbox(engine="podman"|"docker")`：只組 argv（同 bwrap 的做法）、`available()` 用 `which`、`describe()`；`resolve()` 的 `auto` 順序；`REAL_ISOLATION` 加 `container`；placeholders 的 container view（`/pack`、`/data/user`…） | 新後端、組出來的 argv 有完整測試（每個旗標都 assert） | 假 which；**絕不真的跑 podman／docker** | S0 |
| **S2 安裝選項與鎖** 🖥️ | 安裝報告「🧱 執行環境」段、`--runtime` 旗標、網頁下拉、`packs.lock` 的 `runtime` 區塊、`packs runtime <name>` 切換指令、升級紅字規則、`restricted_reason` 的新句子（「有容器就能給成員」） | admin／upgrade／lock／doctor 改動 | 假後端＋假 JobRunner | S1 |
| **S3 映像供應** 🖥️ | `envs.py` 多一種 Builder 計畫：拉映像（digest 比對）／用 Dockerfile 建（base digest 先 pull）、`env.json` 記 digest、`env_problem` 新句、`packs env prune` | Builder 擴充 | 假 JobRunner（記錄指令，不執行） | S1 |
| **S4 MCP 長駐容器** 🖥️ | `McpPool`／`StdioBackend`：容器固定命名、`close_all` 先 stop、閒置回收路徑、Windows 用戶端程序與容器的壽命對齊；env 指紋含映像 digest | mcp.py 改動 | 假 spawner | S1 |
| **S5 Linux 真機驗證** 🐧 | 在實驗室機器裝 rootless podman（與 Docker 各一台或同一台兩種），照 security.md「伺服器上要驗的」清單＋容器版清單跑：斷網真的斷、讀不到別人的 `data/users/`、寫得進自己的、`--read-only` 下 Python 能跑、`--pids-limit` 生效、MCP 長駐容器閒置回收真的消失、Dockerfile build 經 JobRunner 10 分鐘內 | 驗證紀錄（一件一檔進 `_inbox/`）、security.md 把「沒驗證」改成「驗過的清單」 | 真機 | S1–S4 |
| **S6 Windows 引擎偵測與引導** 🖥️＋🪟 | doctor／精靈「沙盒引擎」頁：偵測 docker／podman／VBoxManage／vmrun／WSL、`installers/` 檔名與雜湊比對、三個按鈕（預設「我自己執行」）、Extension Pack 的勸阻文案 | doctor、wizard 改動 | 偵測邏輯用假 which／假檔案測；真的裝 Docker Desktop 在別台 Windows 驗 | S2 |
| **S7 VM 後端（可延後）** 🪟🐧 | `VmSandbox`：Manager（映像下載、登記）＋Provider（VBoxManage／vmrun：開機、快照 `init_state`、還原、`guestcontrol run`）；每次呼叫＝還原快照→跑→關；只給 `capabilities` 有 `exec` 或 GUI 的工具 | 新模組 `sandbox_vm.py` | 假 VBoxManage；真 VM 在別台 | 擁有者決定 Q5 |
| **S8 AppContainer（可延後）** 🪟 | Windows 個人版的真隔離：`CreateAppContainerProfile`＋`SECURITY_CAPABILITIES`、對 grants 資料夾加 ACL、沒 network 就不給 `internetClient` | 補完現有介面 | 假 kernel32／advapi32；真的在別台 Windows 驗 | 擁有者決定 Q6 |

**開發機家規對照**：S0–S4、S6 的程式都只組 argv、用假的 which／JobRunner／spawner，**不會在這台跑任何容器、VM 或第三方 installer**；S5、S7、S8 的真機驗證在實驗室或另一台 Windows。就算擁有者在 Q3 選「這台裝 Docker Desktop」，測試套件也不會自動用它（跟現在 bwrap 的做法一樣，`set_factory` 一律給假後端）。

---

## G. 需要擁有者決定的問題（最多 6 題）

| # | 問題 | 選項 | 建議 |
|---|---|---|---|
| **Q1** | 容器要求多強？ | A 所有 pack 強制 ／ **B 建議＋伺服器版第三方與 T2 強制（沒提供＝只給擁有者）** ／ C 只建議 | **B**：跟現有 PERM-7／T2 政策同形，不擋個人版，作者仍有動機 |
| **Q2** | Linux 伺服器的容器引擎首選？ | **A rootless podman 優先、Docker 次之（都支援）** ／ B 只支援 Docker ／ C 只支援 podman | **A**：podman 沒有 root daemon；但實驗室機器可能已經裝了 Docker，兩個都認比較實際 |
| **Q3** | 這台開發機要不要裝 Docker Desktop？ | A 不裝（全部用假後端，真容器只在別台） ／ **B 裝，但只跑 SYNOX 自己建、`FROM` 官方 Python 映像的測試容器；第三方 pack 的映像與 exe 仍不在這台跑** ／ C 裝並當一般開發環境 | **B**（前提：擁有者同意把 Docker Desktop 與官方 base image 歸類為「開發工具」而不是「網路上抓來的程式」；不同意就 A）。注意 Docker Desktop 安裝會動 WSL2 與網路介面，但 SYNOX 自己不開埠 |
| **Q4** | SYNOX 要不要自己發一個「基底映像」給作者用？ | **A 要（`synox/base:py3.12@sha256:…`，我們自己 build、在 GitHub release／GHCR 發）** ／ B 不要，作者自己寫 `FROM python:…@sha256` | **A**：作者少踩坑、SYNOX 可以固定非 root 使用者與工作目錄；但要有人維護（每季更新 digest） |
| **Q5** | VM 後端做不做、什麼時候做？ | A 不做（容器夠用） ／ **B 做，排在 S7，只給 GUI／`exec` 工具，VirtualBox 優先（本體 GPL、不用擴充包）** ／ C 做，VMware 優先（OSWorld 同款） | **B**；VMware 現在也免費，可以第二個支援 |
| **Q6** | Windows 個人版的真隔離走哪條？ | A 只靠使用者自己裝 Docker Desktop ／ **B Docker Desktop 為主，AppContainer（S8）排在後面當「不裝任何東西」的選項** ／ C 先做 AppContainer | **B**：AppContainer 的工程量與不確定性最高（Python 在裡面跑不跑得起來待實測），先用現成的 |

---

## 附：對 security.md 的影響（實作時要同步改的句子）

- 「運行空間」的後端表加 `container`（podman／docker）與 `vm` 兩列；`auto` 的順序更新。
- 「要沙盒卻沒有真隔離」那段：加一句「pack 有提供 `runtime.container`、而這台有引擎、擁有者安裝時選了容器 → 算真隔離，T2 的 cli／mcp pack 也能給成員」。
- 「沒有做的保護」：加「映像內容 SYNOX 不看（跟 npm 套件一樣）；Docker daemon 是 root 時 docker 群組等於 root；容器共用主機核心，核心漏洞穿得過（VM 才擋得住）」。
- 「這台電腦（開發機）的家規」：照 Q3 的結論補一句。

---

[^bwrap]: bubblewrap README（containers/bubblewrap，main）：「bubblewrap is not a complete, ready-made sandbox with a specific security policy」「the level of protection between the sandboxed processes and the host system is entirely determined by the arguments passed to bubblewrap」；靠 user namespaces 讓任何使用者能用；setuid 模式已移除；支援 seccomp 過濾器。https://github.com/containers/bubblewrap/blob/main/README.md
[^appcontainer]: Microsoft Learn「AppContainer isolation」（2025-07-08）：憑證、裝置、檔案、網路、程序、視窗隔離；網路可以細分 Internet／Intranet／server。https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation
[^wsb]: Microsoft Learn「Windows Sandbox」：支援 Windows Pro／Enterprise／Education，**Home 不支援**；要硬體虛擬化、4 GB RAM。https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-overview
[^gvisor]: gVisor docs：「an application kernel that implements a Linux-like interface」，Go 寫的；`runsc` 接 Docker／Kubernetes；「gVisor does not presently implement every system call, /proc file, or /sys file so some incompatibilities may occur」。https://gvisor.dev/docs/
[^firecracker]: Firecracker getting-started：Linux x86_64／aarch64，需要 `/dev/kvm` 讀寫權限；EC2 只有 `.metal` 機型支援 KVM。啟動時間（約 125 ms）來自第三方部落格，數字彼此不一致，待實測。https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md
[^podman]: 多篇比較文（TechTarget「Compare Docker vs Podman」等）：Docker daemon 以 root 跑、docker 群組等於 root；rootless podman 把容器的 root 對應到非特權使用者，逃出容器還要再提權；Docker 19.03 起有 rootless 模式但不是預設。https://www.techtarget.com/it-infrastructure/tip/Compare-Docker-vs-Podman-for-container-management
[^dockerwin]: Docker docs「Install Docker Desktop on Windows」：Windows 10／11 Home 用 WSL 2 後端；最低 21H2（build 19044）；WSL 1.1.3.0 以上。https://docs.docker.com/desktop/install/windows-install/
[^dockerlic]: Docker docs「Docker Desktop license agreement」：「Docker Subscription Service Agreement」；免費：fewer than 250 employees AND less than $10 million in annual revenue、個人非商業、學生與學術機構、非商業開源；付費：較大組織、公部門與政府、超出免費範圍的商用。https://docs.docker.com/subscription/desktop-license/
[^vboxlic]: VirtualBox「Licensing FAQ」：本體 GPLv3，可重新散布；Extension Pack 是 PUEL（個人＝單一主機、非商業；教育）；「Trial use has been discontinued with this license」；Extension Pack 不可重新散布；商用要 Enterprise 授權（Named User 最少 100 套）。https://www.virtualbox.org/wiki/Licensing_FAQ
[^vmwarelic]: Broadcom KB 368667「Download and license VMware Desktop Hypervisor」：2024-11-11 起 Workstation Pro 17.5.2／Fusion 13.5.2 以上「available free for Commercial, Educational, and Personal users」，不需金鑰；下載要 Broadcom Support Portal 帳號。https://knowledge.broadcom.com/external/article/368667/download-and-license-information-for-vmw.html
[^osworld]: OSWorld（xlang-ai/OSWorld，main，2026-11-10 讀取）：`README.md`（「Install VMware Workstation Pro」、「Our setup script will automatically download the necessary virtual machines」、Docker 建議 KVM）、`desktop_env/desktop_env.py`（`provider_name="vmware"`、`snapshot_name="init_state"`、`server_port=5000`、`chromium_port=9222`、`vnc_port=8006`、`vlc_port=8080`）、`desktop_env/providers/__init__.py`（11 個 provider）、`providers/docker/provider.py`（`happysixd/osworld-docker`、`.qcow2` 唯讀掛載、`/dev/kvm`）、`providers/vmware/manager.py`（Hugging Face `xlangai/ubuntu_osworld`、`vmrun`、`.vmware_vms` 登記）、`SETUP_GUIDELINE.md`（AWS 評測平台的埠表：5000 backend、5910 noVNC、8006 VNC、8080 VLC、9222 Chrome）。https://github.com/xlang-ai/OSWorld
