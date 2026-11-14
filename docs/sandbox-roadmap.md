# 沙盒路線圖（徵求協助）

> **English summary.** SYNOX runs third-party tools ("packs") as subprocesses and wants to isolate each one so it can
> only touch its own folder and the network hosts it declared. Today that is **only partly true**: on Linux there are
> real isolation backends (bubblewrap, systemd-run, per-pack containers), but they are used only by the server
> edition and have **not yet been verified on a real machine**; the personal edition and **Windows have no isolation**
> (default backend `none`; the optional `jobobject` backend only limits memory and process count). The "sandbox mode"
> switch in the web UI is a disabled placeholder. This page lists the Windows options we found (MXC, a hand-built
> AppContainer, a dedicated local account + WFP firewall filtering, restricted tokens, Windows Sandbox,
> Docker Desktop / WSL 2) with their trade-offs, explains how volunteers can run our **read-only probe scripts** on
> their own Windows PCs and share the results, and lists concrete "help wanted" tasks with acceptance criteria.
> Ideas and results go to GitHub Discussions; **security vulnerabilities go privately via [SECURITY.md](../SECURITY.md),
> never in public**. Design decisions live in [ADR 0022](adr/0022-ecosystem-bridge-and-sandbox.md) (a proposal,
> not yet approved by the owner).

- 狀態：**公開的路線圖與徵求協助**。這裡寫的設計都還是[ADR 0022](adr/0022-ecosystem-bridge-and-sandbox.md) 的**提案**，擁有者還沒核准；
  核准之前 SYNOX 的程式（`src/`）不會為了這件事改動。
- 最後更新：2026-11-14。對過的程式：`src/synox/sandbox.py`、`src/synox/packs/container.py`、`src/synox/web/static/app.html`（`set-sandbox` 卡片）。
- 有想法、有實測結果 → GitHub Discussions（討論串草稿：[community/discussion-ecosystem-and-sandbox.md](community/discussion-ecosystem-and-sandbox.md)）。
  **發現安全漏洞 → 照 [SECURITY.md](../SECURITY.md) 私下寄信，不要開公開 issue、不要貼在討論區。**
- 連到 `docs/lab/` 的連結只在 GitHub 上（或 `git clone`）看得到；發佈 ZIP 與安裝程式不帶這個資料夾。

## 一、為什麼要沙盒

SYNOX 可以裝別人做的工具（pack）。工具會在你的電腦上跑程式。安裝前 SYNOX 會檢查、給你看報告、要你按確認
（[security.md](security.md)「五關」），但**檢查只是提醒，不是保證**：惡意作者可以寫出掃不到的程式。

沙盒想做到的是：就算裝到有問題的工具，它也**只碰得到自己的資料夾、只連得到它申請的網站**，碰不到你的文件、
你的帳號、本機的其他服務（例如 Ollama 的 11434 埠、SYNOX 自己的 8830 埠）。

之後如果 SYNOX 能匯入 OpenClaw、Hermes Agent 等生態的技能（[ADR 0022](adr/0022-ecosystem-bridge-and-sandbox.md) 第 1 節），
會有更多不是 SYNOX 維護者寫的程式在使用者電腦上跑，沙盒就更重要。

## 二、現在的狀態（老實版）

| 平台／版本 | 預設後端 | 檔案隔離 | 網路隔離 | 有沒有在真機驗證 | 依據 |
|---|---|---|---|---|---|
| **Linux 伺服器版** | `auto`＝有 bwrap 用 bwrap，沒有就 systemd-run，都沒有＝`none` | **有**（設計上） | 有／沒有兩種：沒宣告 `network` 就斷網；宣告了就**完全不限**（沒有網域名單） | **沒有**：只測過「組出來的指令」，bwrap、systemd-run 一次都沒在真機跑過 | `src/synox/sandbox.py` 的 `resolve()`；`docs/security.md`「運行空間」 |
| **Linux 個人版** | `none` | 無 | 無 | — | `resolve()`：`mode != "server"` 一律 `none` |
| **任何平台，pack 自帶容器** | 擁有者安裝時選「用容器」、這台找得到 podman／docker 才用 | **有**（設計上） | 同上（`--network none` 或全開） | **沒有**（只比對組出來的指令字串） | `src/synox/sandbox.py` 的 `ContainerSandbox`；`src/synox/packs/container.py`（第 1、2 關）；[handoff/container-verification.md](handoff/container-verification.md) |
| **Windows（個人版、伺服器版）** | `none` | **無** | **無** | — | `resolve()`：不是 Linux 一律 `none` |
| Windows，手動設 `jobobject` | `jobobject` | **無**（只限記憶體、程序數、launcher 結束整組關） | **無** | — | `JobObjectSandbox.isolates = False` |
| Windows，手動設 `appcontainer` | 退回 `none` | — | — | **還沒實作**：只有介面，`wrap` 丟 `NotImplementedError` | `AppContainerSandbox`；`resolve()` 對 `appcontainer` 回 `NoneSandbox` 並寫原因 |

另外三件要知道的事：

- **`kind=python` 的工具在 SYNOX 自己的程序裡跑，任何後端都包不到。** 伺服器版的第三方 python pack 只給擁有者用。
- **子程序會繼承 SYNOX 的整份環境變數**，只拿掉名字像密鑰的（`API_KEY`、`SECRET`、`PASSWORD`、`_TOKEN` 結尾）。
  systemd 與容器後端只帶列名的變數；bwrap 沒有清環境。
- **網頁上的「沙盒模式」開關是預留位置。** 設定頁的 `set-sandbox` 卡片標「⏳ 尚未完成」，開關是 `disabled`、打不開，
  說明文字寫「在 Windows 上，SYNOX 目前還沒有沙盒」（`src/synox/web/static/app.html`，只有擁有者看得到）。

一句話：**在 Windows 的隔離做好並實測之前，「用沙盒保護你不被惡意工具傷害」這句話對大多數使用者還不成立。**
這段期間的防線是安裝前的報告、確認卡、工具庫的人工整理。

## 三、Windows 有哪些路（研究整理）

完整的來源與標籤在[第 3 階段研究](lab/2026-11-13-ecosystem-security-research.md)主題 4（「已查證」＝讀到一手文件；「待實測」＝還沒有人在真的 Windows 上試過）。
**下表的每一條在 Windows 上都還沒有實測過。**

| 路 | 給什麼 | 使用者要做什麼 | 主要的代價與未知 |
|---|---|---|---|
| **MXC**（Microsoft eXecution Container，Windows 11 內建，2026-10 GA） | 檔案政策（唯讀／可寫／禁止的路徑）＋每個容器自己的對外過濾；網域名單要 SYNOX 自己起一個本機代理 | 把 Windows 11 更新到夠新的 build（24H2 `26100.9278`、25H2 `26200.9278` 起） | **Windows 10 不行**；Home 版能不能用**查不到**；沒有 Python SDK，獨立執行檔 `wxc-exec.exe` 去哪裡拿**查不到**；Node SDK 要 Node ≥ 24 並相依 `node-pty`；長駐的 stdio（MCP 伺服器）行不行**待實測** |
| **AppContainer（自己寫）** | 檔案隔離（要自己對資料夾加 ACL）＋網路「全斷或全開」 | 不用另外裝東西（Windows 8 起內建） | **做不到網域名單**：本機 loopback 也被擋，豁免要系統管理員；裝在使用者資料夾的 Python／Node **推測**讀不到；一般使用者能不能建 profile **待實測**；工程量高（ctypes＋ACL 管理） |
| **專用本機帳號＋WFP 防火牆過濾** | 檔案（NTFS ACL）＋網域名單（經代理） | **第一次要按一次系統管理員同意（UAC）** | 文件自己寫了繞過缺口（換匿名 token、系統服務代送的流量、DNS）；參考實作（Anthropic sandbox-runtime 的 Windows 支援）標 alpha；最低 Windows 版本與 Home 版**查不到** |
| 受限 token＋Job Object | 只能限制**寫入**；讀取與網路都不擋 | 無 | 保護有限；受限 token 下系統的 HTTPS（Schannel）會失敗 |
| Windows Sandbox | 用完即丟的輕量 VM，可以關網路 | 啟用選用功能（推測要管理員） | **Home 版不支援**；接不了長駐的 stdio（推測），不適合當工具的執行環境。只拿來當**研究用的乾淨環境** |
| Docker Desktop／WSL 2 | 最接近 Linux 伺服器版的行為（SYNOX 已有容器後端，未驗證） | **另外安裝** Docker Desktop；第一次啟用 WSL 2 要管理員 | 不符合「容易安裝」；大公司商用要付費；Windows 10 已不在 Microsoft 服務期 |

沒有任何一條路同時滿足「不用另外裝、不要管理員、Windows 10 也行、有網域名單」。

**ADR 0022 的提案**（等擁有者決定 11–14，**而且先實測再定**）：Windows 11 新版走 MXC；舊系統退到自製 AppContainer（保護等級「基本」：檔案隔離＋全斷或全開網路）；
專用帳號＋防火牆之後做成選配的「加強保護」。Linux 與跨平台的部分（共用的抽象、連外代理、環境變數白名單、網域宣告格式）可以先做。

不管哪條路都有的限制：代理只看用戶端自報的主機名、不解 TLS（有 domain fronting 的空間）；不走代理的程式連不上允許的網站；
UDP／QUIC 出不去；Windows 上 DNS 由系統服務代做，擋不住。

## 四、探測腳本：志願者怎麼幫忙

腳本在 [`docs/lab/tools/windows-sandbox-probe/`](lab/tools/windows-sandbox-probe/)，詳細的說明與「結果怎麼讀」在那個資料夾的 [README](lab/tools/windows-sandbox-probe/README.md)。

> **這三個檔還沒有人在 Windows 上跑過**（在 Linux 上寫的，Python 檔只做過語法檢查）。腳本出錯是腳本的 bug，把錯誤訊息原樣帶回來就很有用。
> 跑之前請先讀過腳本（都很短、只用標準函式庫與 Windows 內建的東西）。在別台電腦或虛擬機上跑更好。

| 檔案 | 做什麼 | 會動到什麼 | 要管理員嗎 |
|---|---|---|---|
| `win-env-probe.ps1` | **只讀**盤點：Windows 版本與 build、是不是 Home 版、虛擬化、node／python／docker／wsl 裝在哪、build 夠不夠用 MXC | 只在腳本旁邊寫 `win-env-probe-result.json`；不安裝、不改設定、不連網 | 不用 |
| `win_appcontainer_probe.py` | 建一個暫時的 AppContainer，做 11 項測試：檔案（F1–F5）、網路（N1–N4）、Python／Node 能不能在裡面啟動（P1、P2） | 暫存資料夾、一個名為 `synox.research.probe` 的 AppContainer profile、一個 127.0.0.1 的監聽埠、最多 2 次連 `example.com`（加 `--no-net` 就不連）；結束時全部刪掉 | 不用（這一點本身也是要驗證的） |
| `synox-research.wsb` | （選做）開一個關網路的 Windows Sandbox | 用完即丟 | 只有 Pro／Enterprise／Education，而且要先啟用「Windows 沙箱」 |

步驟（一般的 PowerShell，**不要**用系統管理員）：

1. 開一個空的暫存資料夾（例如 `C:\synox-probe\`），把三個檔複製進去。**不要在 SYNOX 的資料夾裡跑。**
2. `powershell -ExecutionPolicy Bypass -File .\win-env-probe.ps1`
3. `python win_appcontainer_probe.py`（不想連外：加 `--no-net`）。`python` 如果是 Microsoft Store 的別名，改用真的 `python.exe` 的完整路徑。
4. 回報（貼到 GitHub Discussions 的沙盒討論串，或開一個 issue）：
   - 兩個 `*-result.json` 與畫面上印出的表格；
   - Windows 版本（`winver` 視窗上那一行）、是 Home 還是 Pro；
   - 跟「預期」不一樣的項目（表格的 `expect=`）——**不一樣的才是最有用的發現**；
   - 有沒有看到 `CreateAppContainerProfile/Derive failed: HRESULT 0x…`（有的話把 HRESULT 抄下來）。
   - **貼出去之前**：結果檔的路徑裡會有你的 Windows 帳號名，請換成 `<user>`。
5. 清理：刪掉暫存資料夾。profile 與 `%TEMP%\synox-research-*` 由腳本在結束時刪；腳本被強制關掉的話，手動刪 `%TEMP%\synox-research-*`，再跑一次腳本會把 profile 收掉。

我們最想要的組合：**Windows 10 Home**、**Windows 11 Home（新版 build）**、**Windows 11 Pro**；有裝和沒裝 Python／Node 的都要。

## 五、徵求協助（help wanted）

「現在就能做」的不用改 SYNOX 的程式；「等 ADR 0022 核准」的要等擁有者核准設計之後才收 PR（先在 Discussions 講你想做哪一項，避免白做）。

### 現在就能做

| # | 任務 | 驗收條件 |
|---|---|---|
| **H1** | 在你的 Windows 上跑探測腳本，回報結果 | 兩個結果 JSON＋印出的表格；寫明版本、build、Home／Pro；帳號名已遮掉；腳本出錯的話附完整錯誤訊息 |
| **H2** | 修探測腳本在真機上遇到的 bug | 一般（非管理員）帳號在 Windows 10 與 11 上都跑得完；結束後 `synox.research.probe` profile 與暫存資料夾都不在了；腳本碰的東西沒有比 README 寫的多；README 的「跟研究原稿的差別」記下改了什麼 |
| **H3** | 查清楚 MXC：Home 版能不能用、`wxc-exec.exe` 怎麼合法取得與再散布、長駐的 stdio 行不行 | 每一點附 **Microsoft 的一手來源**（官方文件或官方 repo）；查不到的寫「查不到」與找過哪裡；不附一手來源的說法標「二手」 |
| **H4** | 寫 MXC 的探測腳本（等 H3 有答案） | 測跟 AppContainer 腳本同一組項目（F1–F5、N1–N4、P1、P2）＋一個長駐 stdio 的往返；不需要管理員；結束時清乾淨；只用標準函式庫或 Windows 內建的東西 |
| **H5** | 在 Linux 真機上驗證 bwrap／systemd 後端 | 照 [security.md](security.md)「伺服器上要驗的」逐項做並回報：發行版與核心版本、一般帳號能不能開 user namespace（Ubuntu 24.04 的 AppArmor 限制）、斷網是否真的斷、讀不到別人的 `data/users/<id>/`、寫得進自己的資料夾、venv 的 python 跑得起來 |
| **H6** | 在 Linux／Windows 上驗證容器後端 | 照 [handoff/container-verification.md](handoff/container-verification.md) 逐項回報（podman rootless、Docker Engine、Docker Desktop 各算一份） |
| **H7** | 幫研究挑錯，特別是講到其他專案的地方 | 每一處修正附對方的一手來源（官方文件、官方 advisory）；過時的資訊標出日期；語氣維持中性、以相容為目的 |

### 等 ADR 0022 核准之後

| # | 任務 | 驗收條件 |
|---|---|---|
| **H8** | 連外代理（只用標準函式庫）：每個工具一個入口，只放行宣告的主機的 443 | 主機名解析出來是回送、內網、link-local 的一律拒；被擋的連線記主機名；測試不連真的網路、不開對外的埠（`CONTRIBUTING.md` 的規則） |
| **H9** | Linux bwrap：宣告了網路時也拿掉網路命名空間，只經 unix socket 接到代理 | 工具連不到主機的 127.0.0.1（Ollama 11434、SYNOX 8830）；名單上的網站連得到、名單外的被擋；有自動測試（用假後端）＋一份真機驗證紀錄 |
| **H10** | 執行期環境變數改成白名單 | 子程序只拿到系統必要的、pack 宣告的、代理的變數；先警告一個版本再擋；現有工具的測試照過 |
| **H11** | Windows 後端（MXC 或 AppContainer，看實測結果與擁有者的決定） | 只在擁有者決定路線之後開始；`isolates` 照實回報；`doctor` 與設定頁的說明跟實際做到的一致；設定頁的開關只在真的有隔離時才能打開 |

## 六、怎麼參與

- **想法、問題、實測結果**：GitHub Discussions。開討論時寫明你的平台與版本。
- **程式或文件的修改**：照 [CONTRIBUTING.md](../CONTRIBUTING.md)：pull request 描述寫上貢獻者同意書那一句、跑過全部測試、新功能有測試、
  安全相關的修改說明你考慮過的攻擊情境。
- **安全漏洞**：**一律**照 [SECURITY.md](../SECURITY.md) 私下寄信。不要開公開 issue、不要在 pull request 或 Discussions 貼細節——
  包括「我發現沙盒可以這樣繞過」這種。探測腳本的結果（某個機制在你的 Windows 上不照文件運作）不是 SYNOX 的漏洞，可以公開貼。
- **不要附**真的 token、API 金鑰、密碼或別人的個人資料。

## 七、相關文件

| 文件 | 內容 |
|---|---|
| [ADR 0022](adr/0022-ecosystem-bridge-and-sandbox.md) | 設計提案：匯入器、npm、市集、隔離（第 6 節）、預覽；擁有者決定對照表 |
| [第 3 階段研究](lab/2026-11-13-ecosystem-security-research.md) | 查到什麼、每一條的來源與標籤；主題 4 是 Windows 沙盒 |
| [實作計畫](lab/2026-11-13-ecosystem-implementation-plan.md) | 分工與驗收；區塊 C 是隔離 |
| [security.md](security.md) | 現在的安全邊界：五關、信任層級、運行空間（沙盒）、沒有做的保護 |
| [handoff/container-verification.md](handoff/container-verification.md) | 容器後端的驗證清單 |
