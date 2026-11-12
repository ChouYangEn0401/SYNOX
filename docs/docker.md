# 用 Docker 開發與執行 SYNOX

> 狀態：**映像檔沒有實際建置過、容器沒有實際跑過**（寫這些檔案的那台電腦不跑容器）。
> 這裡的檔案只做過靜態檢查（本頁最後的「檢查表」）；第一次在有 Docker 的機器上用，請照「驗證」一節跑一遍，結果回報給維護者。

SYNOX 平常的裝法是 Windows 上的 `Setup.bat`（[README](../README.md)）。Docker 是給**貢獻者**和**想在 Linux／NAS／伺服器上跑**的人的另一條路：

| 想做什麼 | 用什麼 | 檔案 |
|---|---|---|
| 改 SYNOX 的程式、跑測試，不想在自己電腦裝 Python | **開發容器**（VS Code Dev Containers／GitHub Codespaces） | [`.devcontainer/devcontainer.json`](../.devcontainer/devcontainer.json) |
| 長時間跑 SYNOX（Telegram／Discord bot＋網頁介面） | **執行用映像檔**＋compose | [`Dockerfile`](../Dockerfile)、[`docker-compose.yml`](../docker-compose.yml)、[`.env.example`](../.env.example)、[`.dockerignore`](../.dockerignore)、[`docker/healthcheck.py`](../docker/healthcheck.py) |

兩者都**不需要開任何對外的網路埠**：Telegram、Discord、AI 都是 SYNOX 往外連；網頁介面只在你這台電腦的 `127.0.0.1` 上。

---

## 1. 開發容器（`.devcontainer/`）

### 開起來

1. 裝 Docker（Windows／macOS：Docker Desktop；Linux：Docker Engine 或 rootless podman）與 VS Code 的 **Dev Containers** 擴充功能。
2. 用 VS Code 打開 SYNOX 資料夾 → 命令選擇區 **Dev Containers: Reopen in Container**。
3. 第一次會下載 `mcr.microsoft.com/devcontainers/python:1-3.11-bookworm`，再自動跑
   `pip install -r requirements.txt` 與 `pip install -e '.[dev]'`（`postCreateCommand`）。

容器裡是 Linux＋Python 3.11，工作資料夾就是你的 SYNOX 資料夾（直接掛進去，改的檔案就是你電腦上的檔案）。

### 跑測試

```
python -m pytest -q
python -m pytest -q tests/test_web_bind.py                  只跑一個檔
python -m pytest -q --deselect tests/test_web.py::test_port_already_in_use_is_a_bind_failure
```

最後一行：整套測試裡只有那一個會在 `127.0.0.1` 暫時 listen 一個埠（測獨佔綁定）；在容器裡跑沒關係（是容器自己的 loopback），
要「一個埠都不開」就加 `--deselect`。VS Code 的「測試」面板也已經設好用 pytest。

> 測試大多在 Windows 上寫、在 Windows 上跑；在 Linux 開發容器裡**還沒有整套跑過**。有只在 Windows 才成立的測試（DPAPI、Job Object 之類）
> 失敗或被略過時，請開 issue 附上輸出。

### 在開發容器裡跑 SYNOX

原始碼的版面下，SYNOX 資料夾（`config.json`、`data/`）預設就是工作資料夾——也就是**你電腦上那一份**。
如果你在主機上也跑過 SYNOX，裡面的 `data/.synox.key` 可能是 Windows DPAPI 包的，Linux 打不開。在容器裡試用時，請另外指一個資料夾：

```
export SYNOX_HOME=~/synox-dev                      容器自己的資料夾（重建容器就沒了，試用剛好）
python -m synox console --llm fake                 終端機模式，不連 Telegram、不連網
python -m synox init                               文字版設定引導（寫進 $SYNOX_HOME/config.json）
python -m synox run --no-browser                   真的開 bot＋網頁介面
python -m synox doctor --offline
```

跑測試時**不要**設 `SYNOX_HOME`（有幾個測試要讀 repo 本身的檔案）。

### 網頁的埠：只轉到你電腦的 localhost

- 開發容器裡的 SYNOX 照舊只綁容器裡的 `127.0.0.1:8830`。VS Code 的埠轉送是從容器**裡面**連過去，所以不用改綁位址，
  也**不需要** `SYNOX_WEB_BIND`。
- `forwardPorts` 只列 8830；`otherPortsAttributes.onAutoForward = ignore`（別的程式開的埠不會自動轉出來）；
  `remote.localPortHost = localhost`（VS Code 在你電腦上只開 localhost，這也是 VS Code 的預設）。**不要改成 `allInterfaces`**。
- 沒有用 `appPort`、`runArgs -p`（那會由 Docker 直接發佈，可能是所有網卡）。
- 瀏覽器開 `http://localhost:8830/` 或 `synox open` 印出來的 `http://127.0.0.1:8830/login?t=…` 都可以。

### 除錯

- VS Code：裝好的 `ms-python.debugpy` 直接用「Run and Debug → Python: Module」，模組填 `synox`、參數填 `console --llm fake`。
  除錯器走 VS Code 自己的通道，不用另外開埠。
- 單一測試：`python -m pytest -q tests/test_web.py -k login -x --pdb`。
- 看 SYNOX 自己的判斷：`python -m synox doctor --offline`（設定、AI、資料、工具、沙盒後端都會列）。

### 開發容器刻意沒有的

- 沒有 Docker-in-Docker、沒有掛 `docker.sock`（SYNOX 的安全規則禁止；見下面「已知限制」）。所以在開發容器裡測不到「工具用容器隔離」
  （那部分的測試本來就只比對組出來的指令，不執行引擎）。
- 沒有加 `--cap-drop`／`no-new-privileges` 之類的加固：開發容器要能 `sudo apt-get install` 裝除錯工具。要加固的是下面的執行用映像檔。

---

## 2. 執行用映像檔（`Dockerfile`＋`docker-compose.yml`）

### 第一次

```
cp .env.example .env                    Windows：copy .env.example .env（想改時區、埠、資源上限就改 .env）
docker compose build
docker compose run --rm synox init      文字版設定引導：模式、Telegram token、配對、AI、要裝的工具
docker compose up -d
docker compose logs -f                  看到「SYNOX 開始收訊息了」就好了（Ctrl+C 只是不看 log）
docker compose exec synox synox open    印出擁有者的一次性登入連結，複製到你電腦的瀏覽器打開
```

- 還沒接 Telegram／Discord 也可以：`docker compose run --rm synox init --non-interactive --llm none` 會寫一份只開網頁的設定。
- 沒跑 `init` 就 `up`：SYNOX 找不到 `config.json` 會結束，容器會一直重啟（`restart: unless-stopped`）——先 `docker compose down`，跑完 `init` 再 `up`。
- `docker compose exec` 不經過映像檔的 ENTRYPOINT，所以要寫兩次 `synox`（服務名＋指令）；`docker compose run` 會經過，寫一次就好。
- 網頁介面也可以直接開 `http://127.0.0.1:8830/`：個人版在**這台電腦**的瀏覽器網址列打開會自動登入擁有者（跟不用 Docker 時一樣）。

### 日常

| 做什麼 | 指令 |
|---|---|
| 停／開 | `docker compose stop`／`docker compose start` |
| 看狀態（含健康檢查） | `docker compose ps` |
| SYNOX 自己的健康檢查（設定、AI、工具） | `docker compose exec synox synox doctor --offline` |
| 裝工具 | 網頁「設定 → 裝功能」上傳 `.synoxpack`；或把工具庫掛進來（compose 裡註解掉的 `./tools:/synox/tools:ro`）後 `docker compose exec synox synox tools list` |
| 工具要的帳號密碼 | `docker compose exec synox synox connect <pack>`（getpass，帳密不經聊天） |
| 更新 SYNOX | `git pull` → `docker compose build` → `docker compose up -d`（資料在 volume，不受影響） |
| 完全移除 | `docker compose down`（留資料）；`docker compose down -v` **連資料一起刪**，刪之前先備份 |

### 資料在哪

一個具名 volume `synox-home` 掛在容器的 `/synox`，就是 SYNOX 資料夾（`SYNOX_HOME=/synox`，走 `config.py` 的 `default_root`，沒有另外的機制）：

| 容器裡的路徑 | 內容 |
|---|---|
| `/synox/config.json` | 設定（Telegram token、你的 id、AI 設定；明文，跟不用 Docker 時一樣） |
| `/synox/data/` | 筆記、記帳、對話等（密文），**保管箱主金鑰 `data/.synox.key`** |
| `/synox/packs/` | 裝好的工具 |
| `/synox/tools/` | 工具庫（選用，唯讀掛進來） |

- **主金鑰在容器裡是明文檔**：Linux 沒有 Windows 的 DPAPI，SYNOX 自動用 `vault.mode = file`（見 [security.md](security.md)「資料在哪」）。
  所以「拿得到這個 volume 的人＝看得到全部資料」：能跑 `docker` 指令的帳號、宿主的 root、volume 的備份檔都算。
- 備份 volume（在有 Docker 的機器上；`<備份資料夾>` 換成你自己的）：
  `docker run --rm -v synox_synox-home:/from:ro -v <備份資料夾>:/to python:3.11-slim-bookworm tar czf /to/synox-home.tgz -C /from .`
  （compose 的 volume 全名是 `<專案名>_synox-home`，專案名在 compose 檔頂端是 `synox`）。備份檔裡有主金鑰，跟 volume 一樣要保管好。
- Windows 版 SYNOX 的 `data/` **不能**直接搬進容器：那邊的主金鑰是 DPAPI 包的，Linux 解不開；網頁的「下載備份」也綁那把金鑰。

### 為什麼容器裡綁 0.0.0.0 是安全的

SYNOX 的硬規則是「本機服務只綁 127.0.0.1」（[AGENT.md](AGENT.md) invariant 9、[security.md](security.md)「網頁介面」）。
容器有自己的網路：容器裡的 `127.0.0.1` 只有容器自己連得到，宿主經 Docker 發佈的埠連進來時，走的是容器的網卡。
所以容器裡要綁 `0.0.0.0`，再由 compose 決定「宿主那一邊開在哪裡」。程式與設定是這樣把關的：

1. **程式（`src/synox/web/server.py` 的 `bind_host`）**：預設照舊綁 `127.0.0.1`。只有三件事**同時**成立才綁 `0.0.0.0`：
   - `SYNOX_WEB_BIND=0.0.0.0`（compose 設；映像檔本身不設，所以 `docker run` 沒寫這個變數時網頁仍只綁容器的 loopback，宿主連不到＝安全的失敗）；
   - `SYNOX_IN_CONTAINER=1`（映像檔設）；
   - 不是 Windows，而且看得到容器的證據：`/.dockerenv`（Docker）、`/run/.containerenv`（podman）或映像檔自己放的 `/etc/synox/container`。
     有人在一般電腦上照抄這兩個環境變數也不會生效。
   其他值（區網位址、`::`、`localhost`、打錯字）一律拒：**網頁不開**、原因寫進 log，bot 其他部分照常（fail closed；
   只開網頁、沒接聊天軟體的設定會印出原因並停下來）。
   測試：`tests/test_web_bind.py`（預設不變、開關生效、非法值被拒；不開任何埠）。
2. **compose 只發佈到宿主的 127.0.0.1**：`"127.0.0.1:${SYNOX_WEB_PORT:-8830}:${SYNOX_WEB_PORT:-8830}"`。
   宿主上只有這台電腦的程式連得到，跟不用 Docker 時一樣。**不要**寫成 `"8830:8830"` 或 `-p 8830:8830`（那是宿主的所有網卡＝區網連得到）。
3. **專用網路**：compose 的 `synox` 網路上只有 SYNOX 一個容器，別的容器碰不到它的 `0.0.0.0`。不要把別的服務加進同一個網路。
4. **登入連結不變**：仍然是 `http://127.0.0.1:<web.port>/login?t=…`（給宿主的瀏覽器）。所以宿主的埠、容器的埠、`config.json` 的 `web.port`
   三個要同一個數字（compose 用同一個 `SYNOX_WEB_PORT` 寫兩邊；改了埠也要改 `web.port`）。

剩下的風險（照實說）：

- 個人版「在這台電腦的瀏覽器直接開網址就自動登入」靠的是「只有這台電腦連得到」。在容器裡這件事由上面 2、3 點保證，不是由程式綁 127.0.0.1 保證。
  想更保守：`config.json` 的 `web` 加 `"local_auto_login": false`，之後一律用 `docker compose exec synox synox open` 拿一次性連結。
- 舊版 Docker Engine 在 Linux 上有「同一個區網的別台機器直接路由到容器 IP」的已知問題（發佈到 127.0.0.1 的埠也可能被繞過）。
  請用新版 Docker Engine，並在部署的機器上做「驗證」的 V8。
- 要讓別台電腦（手機）用網頁：跟不用 Docker 時一樣，自己架反向代理＋TLS、設 `web.public_url`（[security.md](security.md)「網頁介面」）。
  反向代理也放在宿主或同一個 compose 裡，不要把 8830 直接發佈到外面。

### 映像檔裡有什麼、沒有什麼

- 有：Python 3.11（官方 `python:3.11-slim-bookworm`）、SYNOX 與它的相依（`requests`、`cryptography`、`websocket-client`）、`tzdata`、授權檔。
- 沒有：`claude` 命令列（所以 AI 來源 `claude_code` 不能用）、`ntu_easy_llm`（所以用 API 金鑰的 AI——`openai`、`anthropic`、`gemini`、
  `openai_compat`——要自己加，見下面）、Node.js（要 `node` 的工具不能用）、`docker`／`podman`、`bwrap`、`sudo`、`curl`。
- 能用的 AI：`none`、`fake`；加了 `ntu_easy_llm` 之後是四種用金鑰的。

**加 `ntu_easy_llm`**（它還沒上 PyPI；上了之後維護者會把它直接寫進 Dockerfile，見最後「待決定」）：先 `docker compose build`，
再在**另一個只放那個 wheel 的資料夾**（`.dockerignore` 是白名單，SYNOX 資料夾裡的 wheel 進不了 build context）寫一個 `Dockerfile`：

```
FROM synox-synox:latest
USER root
COPY ntu_easy_llm-0.5.0-py3-none-any.whl /tmp/
RUN python -m pip install /tmp/ntu_easy_llm-0.5.0-py3-none-any.whl && rm -f /tmp/ntu_easy_llm-0.5.0-py3-none-any.whl
USER synox:synox
```

`docker build -t synox-synox:latest <那個資料夾>` 蓋過同名映像檔，然後 `docker compose up -d`（不要加 `--build`，不然會蓋回沒有它的版本）。
它會從 PyPI 裝 openai、anthropic、google-genai 三個 SDK（建置時連網，執行時不用）。

---

## 3. 已知限制

### 工具的容器隔離：在 SYNOX 的容器裡只能用 host（程序）模式

SYNOX 的工具可以選擇「用容器隔離執行」（`pack.json` 的 `runtime.container`；後端是 `src/synox/sandbox.py` 的 `ContainerSandbox`，
規則見 [security.md](security.md)「運行空間」）。它的做法是由 SYNOX 呼叫 `podman`／`docker` 替每個工具開一個容器。

在 SYNOX **自己的**容器裡，這條路刻意不通：

- **不掛 `docker.sock`、不做巢狀容器**。掛 `docker.sock`＝容器裡的程式能叫宿主的 Docker 開任何容器（包含 `--privileged`、掛宿主的 `/`），
  等於把宿主的 root 交給 SYNOX 和它裝的每一個工具；巢狀容器要 `--privileged` 或放寬 seccomp。兩個都違反 SYNOX 的安全規則
  （`ContainerSandbox` 本身也絕不加 `--privileged`、`docker.sock`；[handoff/container-verification.md](handoff/container-verification.md) 同樣禁止）。
- 映像檔裡沒有 `podman`／`docker`，`sandbox.pick_engine` 找不到引擎 → 選了容器的工具**自動退回 host 模式**，`doctor`／`packs status`
  會寫「選了容器，但這台找不到 podman 或 docker：改用 …」。
- `bwrap`（Linux 沙盒）在 `cap_drop: ALL`＋Docker 預設 seccomp 下開不了 user namespace，映像檔也沒裝；所以容器裡的沙盒後端是 `none`。
- 結果：**容器裡的工具都在 SYNOX 的程序旁邊跑**，看得到 `/synox` 裡的全部資料。SYNOX 的容器把「SYNOX＋工具」整包跟宿主隔開，
  但不把工具彼此、或工具跟 SYNOX 的資料隔開。伺服器版裡「要真隔離」的第三方 cli 工具會照規則**只給擁有者**（fail closed），不會因為在容器裡就放寬。

替代做法：

| 需要什麼 | 怎麼做 |
|---|---|
| 個人版、只裝自己信任的工具 | 直接用容器版（host 模式就是平常 Windows 上的行為） |
| 伺服器版、要讓成員用第三方 cli 工具 | **不要用容器版**；在 Linux 主機上直接裝 SYNOX（venv），裝 `bubblewrap`（`policy.sandbox.backend: auto`）或 rootless podman，讓每個工具有自己的隔離 |
| 想要「SYNOX 在容器裡＋每個工具也在容器裡」 | 目前不支援。可能的方向（rootless podman 的使用者 socket、sysbox 之類）都要另外評估，先開 issue 討論 |

### Windows／macOS（Docker Desktop）

- Docker Desktop 在一台 Linux VM 裡跑容器；`127.0.0.1:8830` 的發佈會開在你電腦的 loopback，跟 Linux 一樣只有這台電腦連得到。
- **資料用具名 volume**（compose 預設就是），不要改成掛 Windows／macOS 的資料夾：跨 VM 的檔案共享慢、檔案擁有者對不上
  （容器裡是 uid 10001）、檔案鎖的行為也不同。Linux 上真的要掛宿主資料夾，先把那個資料夾交給 uid 10001。
- Docker Desktop 有自己的記憶體／CPU 上限（Windows 的 WSL 2 後端看 `.wslconfig`）；compose 的 `mem_limit` 不能超過它。
- Windows 上 clone 下來的檔案：`.gitattributes` 讓 `.py`、`Dockerfile`、`*.yml` 都是 LF，不用另外處理。
- `Setup.bat`、`Start.bat`、桌面捷徑、`Open-SYNOX.bat`、`Connect-Apple.bat` 都是 Windows 專用，容器裡對應的是上面「日常」那張表的指令；
  安裝精靈（視窗版）也沒有，改用文字版 `synox init`。
- 想用宿主上的服務（例如自己電腦的 Ollama）：Docker Desktop 有 `host.docker.internal`；Linux 要多寫 `extra_hosts`，
  而且那個服務得聽在容器連得到的位址上——這跟「本機服務只綁 127.0.0.1」衝突，比較好的做法是把它也當成容器放進同一個 compose。

### 其他

- **Telegram／Discord 只需要往外連**（HTTPS／WebSocket 到它們的伺服器），不用發佈任何埠、不用設 webhook。容器的網路是一般的 bridge（不是 `internal`），
  因為要連得出去。
- **時區**：提醒、排程照容器的時間算，`.env` 的 `TZ` 要設成你的時區（預設 UTC）。
- **健康檢查**（`docker/healthcheck.py`）：看 `data/host.lock` 那支 SYNOX 還活著，網頁開著的話連容器自己的 `127.0.0.1:<web.port>`；
  不經任何對外的埠。擁有者用 `/web_off` 關掉網頁的那段時間會顯示 unhealthy，重開容器就恢復。
- **唯讀根目錄**：只有 `/synox`（volume）和 `/tmp`（tmpfs，`noexec`，128 MB）能寫。工具的依賴環境（`runtime.python: auto`）建在
  `/synox/data/envs/`，建的時候要連 PyPI（往外）。
- `docker compose exec synox synox open` 只在 SYNOX 已經在跑時有用；沒在跑時它會想開 `Start.bat`（Windows 才有）而失敗——先 `docker compose up -d`。

---

## 4. 驗證（要在有 Docker 的機器上做）

寫這些檔的電腦**沒有**跑過下面任何一步。第一次在有 Docker 的機器上用，請照順序做、把每一項的結果（通過／失敗＋輸出）回報。
只用 compose 檔裡的設定；不要加 `--privileged`、`-p 8830:8830`、`--network host`，不要掛 `docker.sock`。

| # | 做什麼 | 預期 |
|---|---|---|
| V1 | `docker compose config` | 沒有錯誤；`ports` 的 `host_ip` 是 `127.0.0.1`；`read_only: true`；`cap_drop: [ALL]` |
| V2 | `docker compose build` | 兩段都成功；最後一段沒有連網（`--no-index`）；改一行 `src/` 再 build，`pip wheel -r requirements.txt` 那層用快取 |
| V3 | `docker image inspect synox-synox --format '{{.Config.User}} {{json .Config.Healthcheck}} {{json .Config.Env}}'` | `synox:synox`；有 Healthcheck；Env 沒有任何 token／金鑰，**沒有** `SYNOX_WEB_BIND` |
| V4 | `docker compose run --rm synox about` | 印出版本與授權；「裝在哪裡」是 `/synox` |
| V5 | `docker compose run --rm synox init --non-interactive --llm none`，再 `docker compose up -d` | log 有「網頁介面」與「容器模式：綁容器裡的 0.0.0.0:8830」；`docker compose ps` 幾分鐘後是 `healthy` |
| V6 | 宿主上 `curl -sI http://127.0.0.1:8830/`（Windows：`curl.exe -sI …`） | 有 HTTP 回應（200） |
| V7 | `docker compose exec synox synox open` → 宿主瀏覽器打開印出的連結 | 登入確認頁 →「登入」→ 進到網頁介面 |
| V8 | 從**同一個區網的另一台機器**連 `http://<這台的區網 IP>:8830/`，以及（Linux）`http://<容器 IP>:8830/` | 都連不上 |
| V9 | `docker compose exec synox sh -c 'touch /x; touch /synox/ok && rm /synox/ok; id'` | `/x` 失敗（唯讀）；`/synox` 可寫；`uid=10001(synox)` |
| V10 | `docker compose run --rm -e SYNOX_WEB_BIND=192.168.1.10 synox run --no-browser`（另一個終端機看 log，Ctrl+C 結束） | log 有「網頁介面沒有開：SYNOX_WEB_BIND='192.168.1.10' 不收」；bot 其他部分照常（只開網頁的設定會停下來並印原因） |
| V11 | `docker compose exec synox synox doctor --offline` | 沒有紅字的錯誤；沙盒那行是 none；保管箱那行是 file 模式 |
| V12 | 開發容器：Reopen in Container → `python -m pytest -q` | 記下 passed／failed／skipped 數；失敗的貼輸出 |
| V13 | `docker compose down` → `docker compose up -d` | 設定與資料還在（不用重跑 init） |

---

## 5. 檢查表（靜態自查，2026-11-12）

在寫這些檔的電腦上只做了下面這些（**沒有** build、沒有 run）：

- `python -I` 用 PyYAML 解析 `docker-compose.yml`、用 `json` 解析 `.devcontainer/devcontainer.json`：都合法。
- `tests/test_docker_files.py`：把下面幾條關鍵規則寫成測試（只讀檔案字串，不需要 Docker），以後改這些檔時會擋。
- 整套 pytest（排除會開埠的 `test_port_already_in_use_is_a_bind_failure`）。

### Dockerfile

| # | 項目 | 結果 |
|---|---|---|
| B1 | 基底映像檔用明確的 tag（`python:3.11-slim-bookworm`，不是 `latest`）；`ARG PYTHON_IMAGE` 可以換成 `@sha256:` 鎖死 | ✅ tag；digest 沒鎖（待決定 Q-D1） |
| B2 | 兩段式建置：編譯／打包在 `build`，`runtime` 只裝 wheel | ✅ |
| B3 | 快取友善：先 `COPY requirements.txt` 裝相依，再 `COPY` 原始碼 | ✅ |
| B4 | `pip` 不留快取（`PIP_NO_CACHE_DIR`）；`apt-get update` 與 `install` 同一個 `RUN`、`--no-install-recommends`、刪 `/var/lib/apt/lists` | ✅ |
| B5 | 非 root：固定 UID／GID 10001、`nologin`、沒有家目錄；`USER synox:synox` 在最後 | ✅ |
| B6 | 只複製需要的檔：`pyproject.toml`、`requirements.txt`、`src/`、`vendor/`、授權檔、`docker/healthcheck.py`；`.dockerignore` 是白名單 | ✅ |
| B7 | `ENV`／`ARG`／任何一層都沒有 token、金鑰、個人路徑 | ✅ |
| B8 | `HEALTHCHECK` 用 exec 形式，不經對外的埠（看程序＋容器自己的 loopback） | ✅ |
| B9 | `ENTRYPOINT`／`CMD` 用 exec 形式（訊號直接給程式）；compose 另加 `init: true` | ✅ |
| B10 | `EXPOSE` 只是文件，不發佈任何埠；映像檔**不設** `SYNOX_WEB_BIND` | ✅ |
| B11 | 狀態放 `VOLUME /synox`（`SYNOX_HOME`），根目錄可以唯讀 | ✅ |
| B12 | `PYTHONDONTWRITEBYTECODE`、`PYTHONUNBUFFERED`、`PYTHONUTF8` | ✅ |
| B13 | wheel 用 `RUN --mount=type=bind,from=build` 帶進來，不留在映像檔的層裡（需要 BuildKit，新版 Docker 預設就是） | ✅（沒實際 build 過） |
| B14 | runtime 不裝 `curl`、`sudo`、`docker`、編譯器 | ✅ |
| B15 | 授權檔（AGPL／Apache）跟著映像檔走（`/usr/share/doc/synox/`） | ✅ |
| B16 | 第一行 `# syntax=docker/dockerfile:1` | ✅（建置時會去拿這個前端映像檔） |

### docker-compose.yml

| # | 項目 | 結果 |
|---|---|---|
| C1 | 埠只發佈到 `127.0.0.1`，宿主埠＝容器埠＝`web.port` | ✅ |
| C2 | 資料用具名 volume `synox-home:/synox` | ✅ |
| C3 | `read_only: true`＋`tmpfs: /tmp`（`noexec,nosuid,nodev`、有大小上限） | ✅ |
| C4 | `cap_drop: [ALL]`，沒有 `cap_add` | ✅ |
| C5 | `security_opt: no-new-privileges:true` | ✅ |
| C6 | 沒有 `privileged`、`docker.sock`、`network_mode: host`、`devices`、`pid: host` | ✅ |
| C7 | 資源上限範例：`mem_limit`、`cpus`、`pids_limit`（`.env` 可調） | ✅ |
| C8 | `init: true`、`restart: unless-stopped`、`stop_grace_period` | ✅ |
| C9 | 專用 bridge 網路（只有 SYNOX） | ✅ |
| C10 | log 輪替（`json-file`，10 MB × 3） | ✅ |
| C11 | 機密不寫在 compose；`.env` 在 `.gitignore`；`.env.example` 只有範例值 | ✅ |
| C12 | 變數都有預設值（`${X:-預設}`），沒有 `.env` 也能跑 | ✅ |

### .devcontainer/devcontainer.json

| # | 項目 | 結果 |
|---|---|---|
| D1 | Python 3.11（`devcontainers/python:1-3.11-bookworm`） | ✅ |
| D2 | `postCreateCommand` 裝 `requirements.txt` 與 `-e .[dev]` | ✅ |
| D3 | 只轉 8830、其他埠不自動轉、`remote.localPortHost = localhost`；沒有 `appPort`、`runArgs -p` | ✅ |
| D4 | 沒有 Docker-in-Docker、沒有掛 `docker.sock` | ✅ |

---

## 待決定（維護者）

| 編號 | 問題 | 選項 | 建議 |
|---|---|---|---|
| Q-D1 | 基底映像檔要不要鎖 digest | A：維持 tag（安全更新自動進來，但不可重現）／B：鎖 `@sha256:`，由維護者定期更新 | **B**，等第一次在有 Docker 的機器上 build 成功後拿到 digest 再鎖 |
| Q-D2 | 容器版要不要預設關掉「本機直接開網址就自動登入」 | A：維持（跟 Windows 版一樣好用）／B：容器裡預設 `local_auto_login=false`，一律用 `synox open` 拿連結 | **A**，文件已寫怎麼關；V8 若發現區網繞得過，再改 B |
| Q-D3 | `ntu_easy_llm` 上 PyPI／GitHub release 之後 | A：Dockerfile 直接裝 `.[llm]`／B：維持現在的「自己疊一層」 | **A**（跟 [AGENT.md](AGENT.md)「ntu_easy_llm」的計畫同一步做） |
| Q-D4 | 要不要發佈官方映像檔（GHCR 之類） | A：不發佈，大家自己 build／B：CI 建置並簽章發佈 | **A**，先等 V1–V13 過了再談 |
