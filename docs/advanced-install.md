# 進階安裝（給工程師）

一般人照 [README](../README.md) 雙擊 `Setup.bat` 就好。這一頁給想自己控制環境的人：從原始碼裝、用 Docker、放到伺服器上、當背景服務跑。
只寫重點，細節連到各自的文件。

標示：✅ 這一版有、寫這頁時實際跑過｜🧪 程式有，但寫這頁時沒能實際跑過｜⏳ 還沒做（或還沒合進主線）

---

## 1. 從原始碼裝（venv）

需要 **Python 3.11 以上**（`pyproject.toml` 的 `requires-python`）與 git。相依只有三個：`requests`、`cryptography`、`websocket-client`
（[`requirements.txt`](../requirements.txt)＝[`pyproject.toml`](../pyproject.toml) 的 `dependencies`）。SDK `isdtelekit` 原樣放在
`vendor/isdtelekit/`，`pip install -e .` 會一起裝好（`src/` 與 `vendor/` 兩個來源目錄）。

```bash
git clone <SYNOX 的 repo 網址> SYNOX
cd SYNOX
python3 -m venv .venv                       # Windows：py -3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt   # Windows：.venv\Scripts\python.exe（下同）
.venv/bin/python -m pip install -e .
```

選用的 extras：

| 指令 | 裝什麼 |
|---|---|
| `pip install -e ".[dev]"` | pytest（跑測試用） |
| `pip install -e ".[llm]"` | `ntu_easy_llm`（用 API 金鑰的 AI：openai／anthropic／gemini／openai_compat）。它不在 PyPI，pyproject 用 GitHub release 的 wheel 網址，**要能連 github.com**。Claude Code、本地模型、`fake`、`none` 不需要它 |

> 沒有鎖檔進 git。`requirements.lock` 與離線用的 `wheelhouse/` 是發佈時由 `scripts/lock_deps.py` 產生的（`Setup.bat` 看到才用）；
> 從原始碼裝就是照上面的版本範圍裝。

### 設定與執行

```bash
.venv/bin/python -m synox init              # 文字版設定引導：模式、Telegram token、AI、工具庫（寫 config.json）
.venv/bin/python -m synox doctor --offline  # 健康檢查（不實際打 AI）
.venv/bin/python -m synox run --no-browser  # 開 bot＋網頁介面（前景；Ctrl+C 或另一個終端機 synox stop）
.venv/bin/python -m synox open              # 印出擁有者的一次性網頁登入連結（SYNOX 要已經在跑）
```

- 還沒有 Telegram token：`synox init --non-interactive --llm none` 寫一份只開網頁的設定（網頁在 `http://127.0.0.1:8830/`）。
- 不連 Telegram、在終端機試：`synox console --llm fake`。
- 有視窗的電腦可以改用視窗版精靈：`synox wizard`（要 tkinter）。
- 全部子指令：`python -m synox --help`。`pip install -e .` 之後 venv 裡也有 `synox`、`synox-sdk` 兩個指令。
- Discord：`synox discord token`（bot token 存進保管箱）→ `synox discord pair`，`config.json` 的寫法見 [discord.md](discord.md)。

Windows 的 `.bat` 都只是包一層 `.venv\Scripts\python.exe -m synox …`，手動建好 `.venv` 與 `config.json` 之後就能直接用：

| 檔案 | 等於 |
|---|---|
| `Start.bat` | 開一個最小化視窗跑 `synox run`（`Start.bat --no-browser`＝設 `SYNOX_NO_BROWSER=1`，只開網頁時不跳瀏覽器） |
| `Stop.bat` | `synox stop` |
| `Console.bat` | `synox console` |
| `Open-SYNOX.bat` | `synox open`（沒在跑就先叫 `Start.bat`） |

### 設定與資料在哪

「SYNOX 資料夾」照這個順序決定（[`src/synox/config.py`](../src/synox/config.py) 的 `default_root`；`synox about`、`synox doctor` 會印出來）：

1. 環境變數 `SYNOX_HOME`；
2. 原始碼的版面（`<SYNOX>/src/synox/…`，git clone 與 `pip install -e .` 都是這種）→ repo 的根目錄；
3. 其他（非 editable 的 `pip install`）→ 目前所在的資料夾。

裡面有：`config.json`（設定；**Telegram token 是明文**）、`data/`（加密的資料、保管箱 `data/secrets.json.enc`、主金鑰 `data/.synox.key`、
執行中的鎖 `data/host.lock`）、`packs/`（裝好的工具）、`tools/`（選用的工具庫）。`config.json`、`data/`、`packs/*` 都在 `.gitignore`。
格式範例：[`config.example.json`](../config.example.json)。

主金鑰：Windows 預設用 DPAPI 包起來；**Linux／macOS 是明文檔**（`vault.mode = file`），保護好 `data/`。Windows 的 `data/` 不能直接搬到 Linux
（DPAPI 解不開）。細節：[security.md](security.md)。

### 更新

```bash
git pull
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .        # pyproject 有改（相依、指令名）時才真的需要；跑了也無害
```

先 `synox stop`，更新完再 `synox run`。版本號規則見 [versioning.md](versioning.md)。

### Linux／macOS

- ✅ **Linux**：寫這頁時在 Linux（Python 3.13）上跑過 venv 安裝、`synox --help`、`about`、`init --non-interactive --llm none`、
  `doctor --offline`、`console --llm fake`、`run --no-browser`（網頁回 200）、`open`、`stop`、`discord token`。
- 🧪 **macOS**：程式沒有擋 macOS（非 Windows 都走同一條路：`vault.mode = file`、`synox stop` 送 SIGTERM），但沒有實際跑過。
- ⏳ macOS／Linux 的一鍵安裝器還沒做：`Setup.bat`、桌面捷徑、`.synoxpack` 檔案關聯（`synox filetype`）、開機自動啟動都只有 Windows。
- 保持清醒（`runtime.keep_awake`）是 Windows 的電源設定；在別的系統上不要指望它。
- 工具的沙盒後端在 Linux 是 `bwrap` → `systemd-run` → `none`（[`src/synox/sandbox.py`](../src/synox/sandbox.py)；伺服器版要給成員用第三方工具時才重要，見 [security.md](security.md)「運行空間」）。

---

## 2. Docker／docker compose

完整說明、安全理由、限制與驗證清單在 [docker.md](docker.md)；這裡只列指令。

> 🧪 **映像檔還沒有實際建置、跑過**。寫這頁時只跑了 `docker compose config`（✅ 合法；埠是 `127.0.0.1:8830→8830`、`read_only`、`cap_drop: ALL`）。
> 這台沒有 Docker daemon，所以 build／run 都沒試。第一次用請照 docker.md「4. 驗證」跑一遍。

檔案：[`Dockerfile`](../Dockerfile)（兩段式、非 root uid 10001、`ENTRYPOINT ["synox"]`、預設 `CMD ["run", "--no-browser"]`）、
[`docker-compose.yml`](../docker-compose.yml)、[`.env.example`](../.env.example)、[`.dockerignore`](../.dockerignore)（白名單）、
[`docker/healthcheck.py`](../docker/healthcheck.py)。

```bash
cp .env.example .env                       # 只放「容器怎麼跑」：埠、時區、資源上限；.env 不進 git
docker compose build
docker compose run --rm synox init         # 第一次：互動問 Telegram token、配對、AI（寫進 volume 的 config.json）
docker compose up -d
docker compose logs -f
docker compose exec synox synox open       # 一次性登入連結，在宿主的瀏覽器打開（exec 要寫兩次 synox）
```

| 項目 | 值 |
|---|---|
| 資料 | 具名 volume `synox-home` → 容器的 `/synox`（`SYNOX_HOME=/synox`）：`config.json`、`data/`、`packs/`。`docker compose down -v` 會**連資料一起刪** |
| 埠 | 只發佈到宿主的 `127.0.0.1:${SYNOX_WEB_PORT:-8830}`。宿主埠＝容器埠＝`config.json` 的 `web.port`。**不要**改成 `"8830:8830"` |
| `.env` 的變數 | `SYNOX_WEB_PORT`、`TZ`（提醒、排程照它算）、`SYNOX_MEM_LIMIT`、`SYNOX_CPUS`、`SYNOX_PIDS_LIMIT`，選用 `SYNOX_LLM_API_KEY` |
| compose 自己設的 | `SYNOX_WEB_BIND=0.0.0.0`（只在容器裡生效，見 docker.md「為什麼容器裡綁 0.0.0.0 是安全的」） |
| 對外連線 | Telegram／Discord／AI 都是往外連，不用開任何對外的埠、不用 webhook |
| 映像檔沒有的 | `claude` 命令列、`ntu_easy_llm`（要自己疊一層，見 docker.md）、Node.js、podman／docker |

### token 怎麼放（不進 git、不進 compose 檔）

- **Telegram**：`docker compose run --rm synox init` 互動時貼上，存在 volume 裡的 `config.json`（明文，跟不用 Docker 時一樣）。
  不要用 `--telegram-token` 參數（會留在 shell 歷史）。
- **Discord** 🧪：`init` 不問 Discord，要先在 `config.json` 加 `channels.discord`，再把 token 存進保管箱。容器根目錄唯讀、沒有編輯器，
  用映像檔裡的 Python 改 volume 裡的檔：

  ```bash
  docker compose run --rm --entrypoint python synox -c "import json; p='/synox/config.json'; c=json.load(open(p, encoding='utf-8')); c.setdefault('channels', {})['discord'] = {'enabled': True, 'bot_token': 'vault:discord_bot_token'}; json.dump(c, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)"
  docker compose run --rm synox discord token    # 貼上 bot token（不顯示），存進 /synox/data 的保管箱
  docker compose run --rm synox discord pair     # 照畫面私訊 bot 配對碼
  docker compose restart
  ```

  （同一串指令在非容器的 Linux 上跑過：改 config、`discord token` 存進保管箱、`doctor` 認得到。容器裡沒跑過。）
- **AI 金鑰**：建議在 `init` 互動時貼（存保管箱，不會出現在 `docker inspect`）。要走環境變數：`.env` 填 `SYNOX_LLM_API_KEY`、
  把 `docker-compose.yml` 那一行的 `#` 拿掉、`config.json` 的 `llm.api_key` 寫 `"env:SYNOX_LLM_API_KEY"`。

### 更新

```bash
git pull
docker compose build
docker compose up -d        # 資料在 volume，不受影響
```

開發容器（VS Code Dev Containers／Codespaces，[`.devcontainer/devcontainer.json`](../.devcontainer/devcontainer.json)）也在 docker.md 第 1 節。

---

## 3. 伺服器、無畫面的機器、哨兵模式

| 東西 | 狀態 | 說明 |
|---|---|---|
| 沒有螢幕的機器（SSH／VPS／NAS） | ✅ | 文字版 `synox init`、`synox run --no-browser`（環境變數 `SYNOX_NO_BROWSER=1` 也行）、`synox open` 印連結。網頁只綁 `127.0.0.1`；從別台用要自己架反向代理＋TLS 並設 `web.public_url`（[security.md](security.md)「網頁介面」），**不要**把 8830 直接開出去 |
| 伺服器版（一群人用） | ✅ | `config.json` 的 `"mode": "server"`（`init --mode server` 或精靈第一頁）。這是「誰能用」的模式，跟有沒有螢幕無關：訪客／成員／管理員、每人一份資料、成員的 AI 月額度。營運者看得到所有人的資料，見 [security.md](security.md)「伺服器版」 |
| 哨兵模式（SYNOX Link：一台當主控台派任務，其他電腦當哨兵執行） | ⏳ | 實驗中，**在另一個分支，還沒合進 `dev`**；這一版的 `synox` 沒有 `link` 子指令，`config.json` 寫 `link` 也不會生效 |

---

## 4. 當背景服務跑

| 平台 | 狀態 | 怎麼做 |
|---|---|---|
| Windows：登入後自動開 | ✅ | 精靈勾「開機自動啟動」→ 在啟動資料夾（`shell:startup`）放 `SYNOX.cmd`（路徑有中文時是 `SYNOX.lnk`），內容是 `Start.bat --no-browser`（[`src/synox/wizard/shortcuts.py`](../src/synox/wizard/shortcuts.py)）。刪掉那個檔就不會自動開。這是「使用者登入後」開一個最小化視窗，**不是** Windows 服務 |
| Windows 服務（不用登入就跑） | ⏳ | 沒有做 |
| Docker | 🧪 | compose 已設 `restart: unless-stopped`＋健康檢查；宿主開機時 Docker 起來就會跟著起來 |
| Linux systemd | 🧪 | repo **沒有附** unit 檔（測試裡的 systemd 是工具沙盒的 `systemd-run`，不是服務）。前景的 `synox run` 在 Linux 跑得起來，可以自己寫一個，下面是範例（沒有實際用 systemd 跑過） |

`~/.config/systemd/user/synox.service`（`<SYNOX 資料夾>` 換成你的絕對路徑）：

```ini
[Unit]
Description=SYNOX
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=<SYNOX 資料夾>
ExecStart=<SYNOX 資料夾>/.venv/bin/python -m synox run --no-browser
Environment=PYTHONUNBUFFERED=1 SYNOX_NO_BANNER=1
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now synox
journalctl --user -u synox -f              # log 都寫在 stdout
loginctl enable-linger "$USER"             # 沒登入也要跑時
```

- 用 user unit，不要用 root 跑。資料夾要放別處就加 `Environment=SYNOX_HOME=…`。
- `config.json` 不存在時 `synox run` 會直接結束：先跑過 `synox init` 再 enable。
- 一個 SYNOX 資料夾同時只能有一支在跑（`data/host.lock`）；用 systemd 管就不要再手動 `synox run`。

---

## 5. 測試、打包、SDK

```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

- 跑測試時**不要**設 `SYNOX_HOME`（有測試要讀 repo 本身的檔案）。
- 測試大多在 Windows 上寫：在 Linux 上會有一些 Windows 專用的測試失敗或被略過；精靈（tkinter）的測試在沒有螢幕的機器上要包
  `xvfb-run -a`。整套只有 `tests/test_web.py::test_port_already_in_use_is_a_bind_failure` 會在 `127.0.0.1` 開一個暫時的埠。
- 給人的 zip：`python scripts/make_zip.py [--out dist] [--tools <工具庫 dist>] [--wheelhouse <資料夾>]` → `dist/SYNOX-<版本>.zip`
  （只收 git 追蹤的檔，不含 `.venv`、`data`、`config.json`）。✅ 寫這頁時在 Linux 上產生過。
- Windows 安裝程式（exe）：GitHub Actions 建置，見 [release-build.md](release-build.md)。
- 寫工具：[sdk.md](sdk.md)（`synox-sdk` 指令、單檔 [`sdk/synox_sdk.py`](../sdk/synox_sdk.py)）；接入方式總覽在 [tools.md](tools.md)。

## 6. 版本與更新

版本號怎麼訂、怎麼看自己裝的是哪一版、更新的規則：[versioning.md](versioning.md)。目前的版本：`synox about`。
