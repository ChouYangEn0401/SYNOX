# 交接：2026-11-13～14 這兩輪（接在 docs/lab/HANDOFF-2026-11-13-round2.md 之後）

**給誰**：接手 SYNOX 的下一個人（或下一個 Claude）。照順序讀，先看「沒在 Windows 上試過」那一節。
**依據**：`git log dev`（2026-11-13 下午～2026-11-14 凌晨的合併）、`CHANGELOG.md` 最上面幾節「未發佈」、`docs/artifacts.json`。
兩邊不一樣時以程式為準。

---

## 1. 這兩輪合進 SYNOX `dev` 的東西

| 合併 | 內容 | 細節在哪 |
|---|---|---|
| `96110fb` | **新手教學引擎** `/tutorial`（也可以打「開始教學」、`/start tutorial`）：網頁上把要按的地方圈起來；Telegram、Discord 用步驟卡。第一次開網頁問「要不要我帶你走一遍？（約 5 分鐘）」。內建一份 `src/synox/tour/tours/basics.json`；工具也能附自己的教學 | `src/synox/tour/`、`static/tour.js`、`docs/tutorials-engine.md` |
| `cfb86ea` | **「🙋 遇到問題？」回報面板**（設定頁分頁＋側欄小連結）：三步，回報內容先遮掉金鑰、token、email、含使用者名稱的路徑；SYNOX 不連網、不自己送出。GitHub 白話問題單表單 | `static/report.js`、`src/synox/web/report.py`、`.github/ISSUE_TEMPLATE/problem.yml` |
| `36f294f` | **版本與發佈規則**＋`scripts/release.py`（bump／check／notes）；ADR 0023 自己更新與緊急修補（**提案**）；`synox about`／`doctor` 多一行發佈頁網址 | `docs/versioning.md`、`docs/adr/0023-updates-and-hotfixes.md` |
| `53ad319` | **進階安裝**（給工程師）：原始碼＋venv、Docker、無畫面、背景服務，每項標 ✅／🧪／⏳ | `docs/advanced-install.md` |
| `6b4253c` | **不用 uv**：Setup.bat 直接下載釘死網址＋SHA256 的 python-build-standalone CPython 3.12.16，用 Windows 內建 `tar.exe` 解到 `runtime\python`，再 `python -m venv`。.exe 與 ZIP 用同一份。Setup.bat 先問語言，再「Enter 照建議／C 自訂」 | `setup/bootstrap.ps1`、`setup/lang/*.psd1` |
| `5f6007f`、`04381f7` | **安裝程式 .exe 的頁面流程**照擁有者 11-13 的決定（先選語言、沒有「我同意」頁、建議／自訂、最後可選裝 Claude Code、解除安裝可勾「連資料一起刪」）。繁中、簡中、印地文的 Inno 內建字用 **SYNOX 自己翻的** `setup/installer/lang/inno/*.isl`（293 個 key 全翻，`installer_ci.py check-iss` 檢查；待母語者校對） | `setup/installer/synox.iss`、`docs/release-build.md`、`docs/installer/spec.html` |
| `7f1d31a` | **外觀（換裝）**：外觀包 `.synoxpack`（`kind=theme`），token＋slot 合約第 1 版，設定 →「🎨 外觀」套用／換回原本的 SYNOX、淺色／深色、「自己貼」SVG。SVG／CSS 一律消毒 | `src/synox/theme/`、`docs/themes.md` |
| `6f17801` | **標語只放一個地方**：`src/synox/brand.py` 的 `SLOGAN`（暫用「先問你，再動手。」，**大標語還沒定案**）；上面那行小字 `EYEBROW` 維持「住在你自己電腦裡的 AI 助理」。拿掉「資料不出門」 | `src/synox/brand.py`、`docs/lab/slogan/index.html` |
| `d2eb284` | **整理資料夾**：`docs/handoffs/` → `docs/lab/cross-repo/`、`docs/discussions/` → `docs/lab/discussions/`、`legacy/` → `docs/legacy/`、`QuestionToUser.md` → `docs/`，拿掉 `connectors/` | `docs/README.md`、`docs/AGENT.md` |
| `748db2f` | **發佈物只帶使用者要的**：`scripts/make_zip.py` 的 `INTERNAL`（`tests/`、`evals/`、`docs/lab/`、`docs/artifacts/`、`docs/artifacts.json`、`docs/QuestionToUser.md`、`docs/ui/`、`docs/installer/`、`.github/` 的 CI 與範本、`.devcontainer/`）。`.gitattributes` 的 export-ignore 與 `synox.iss` 的 `[InstallDelete]` 用同一份（`tests/test_release_layout.py` 檢查）。拿掉 `Connect-Apple.bat`（改 `python -m synox connect apple-reminders`）；`GOVERNANCE.md`／`MAINTAINERS.md`／`TRADEMARK.md` 搬進 `.github/` | `CHANGELOG.md` 最上面一節 |
| `f343d20`、`7b929f5` | **線上頁面登記表＋頁面版本**：每一份線上 Artifact 都要有本機副本、頁尾有線上網址與 `<span data-stamp>`；`scripts/page_stamp.py` 蓋章、`tests/test_artifact_registry.py` 擋。舊頁面的本機副本收進 `docs/artifacts/`（`registry-archive.json`） | `docs/artifacts.json`、`docs/AGENT.md` |

同一段時間也合了：設定頁的官方工具庫（`d042282`）、品牌提案頁（`b99e9df`）、安裝程式規格頁（`3000776`）、一步一步教學頁（`ac98969`）、
Windows 安裝程式的 GitHub Actions workflow（`b197afd`，**還沒跑過**）、ADR 0022 生態系橋接與沙盒（**提案**，`d9313f1`）。

這一輪（2026-11-14）另外改了：一步一步教學 `docs/guide/index.html`（下載改走發佈頁 ZIP、約 4 MB；Setup.bat 新流程；裝好之後
`/tutorial` → 設定 → 功能與安裝挑工具 → 🎨 外觀 → 🙋 遇到問題？；共 28 步）、安裝程式規格 `docs/installer/spec.html`（Q10 已決定、
更新時刪舊檔、ZIP 適合誰）。兩頁都重蓋了頁面版本，**線上版要重新發佈到原本的網址**才會跟本機一致。

---

## 2. 線上頁面與本機副本

規則：每一份線上頁面都有本機 HTML 副本，頁尾寫線上網址與頁面版本；改了內容就 `python scripts/page_stamp.py <檔> --online <網址>` 重蓋，
再發佈到**同一個網址**。登記表：`docs/artifacts.json`（現役）、`docs/artifacts/registry-archive.json`（較早的 16 頁，只留副本）。

| 頁面 | 線上 | 本機 |
|---|---|---|
| 介紹頁 | https://claude.ai/artifact/SNsSkbcVQm7BU22BBZN3gW | `docs/landing/index.html`（原稿 `page.html`，`scripts/make_landing.py` 組） |
| 安裝教學（一步一步） | https://claude.ai/artifact/96iWvykYyUfAC5pkYUrC6F | `docs/guide/index.html` |
| 安裝程式規格（擁有者指定永久保留） | https://claude.ai/artifact/3oCmmu4Epmqf2raNAaoavB | `docs/installer/spec.html` |
| 品牌提案（會繼續加系列） | https://claude.ai/artifact/QqdEnR3s25c7tPUW23zfoz | `docs/lab/design/2026-11-13-brand-explorations.html` |
| 品牌提案 — 內部首發 share（固定 A–F） | https://claude.ai/artifact/QPvmTVeneWme8mBnHiSnuM | `docs/lab/design/2026-11-13-brand-explorations-share.html` |
| 標語預覽 | https://claude.ai/artifact/M21htYntoVQut9nVFBz9kw | `docs/lab/slogan/index.html` |
| Telegram／Discord 圖文教學 | SjWBzQkdDpUNymrQEZRKHe／21KFtvB7EVKsV4bjCE5h1h | `docs/tutorials/telegram/`、`docs/tutorials/discord/`（登記在 archive） |
| 工具庫入口＋9 個工具頁 | M8zGBGy9kRtGTjNS24wBVL 等（見 `docs/artifacts.json`，`repo: SYNOX_Libs`） | SYNOX_Libs 的 `docs/site/*.html`（那邊用 `scripts/site_stamp.py`） |

**不在 repo 裡**：擁有者私人的內部品牌頁。擁有者自己保管，不要加進登記表、不要放進 repo。

---

## 3. SYNOX_Libs（工具庫）

- `main`＝`v0.2.0`（GitHub 上標成 pre-release；SYNOX 的網頁工具庫固定讀這一版的 `index.json`）。
- `dev`：工具庫網站（入口頁＋每個工具一頁，都有線上網址與頁面版本）。
- `costume-wardrobe`（從 `dev` 分出來）：**SYNOX 衣櫃**——26 套外觀包（`costumes/costume-*`，從品牌提案頁產生）、`scripts/build_costumes.py`
  （extract／pack／page／check）、`tests/test_costumes.py`、公開頁 `docs/site/wardrobe.html`（線上 https://claude.ai/artifact/USzGNERZ2477E7XzPaPCsR ）。
  最新一個 commit「make all 26 costumes pass SYNOX's real theme contract and sanitizer」。
- **等擁有者**：把 `dev`、`costume-wardrobe` 合進 `main`。
- **要上傳的發佈附檔**：衣櫃頁的下載連結指向 `releases/download/v0.2.0/costume-*-1.0.0.synoxpack`，這些檔還要 `build_costumes.py pack`
  做出來、上傳到那個 release（上傳前連結會 404）；`index.json` 也要重新產生（`scripts/build.py` 會把衣櫃一起寫進去，`kind=theme`）。
  上傳完再確認 SYNOX 設定頁「載入工具清單」看得到，並把教學頁「官方的外觀包還沒正式發佈」那句拿掉。

---

## 4. 怎麼跑測試、打包、發版

**測試**（Linux 也能跑；Windows 專屬的測試會略過）：

```
PYTHONPATH=$PWD/src python -m pytest -q -p no:cacheprovider
```

2026-11-14 在 Linux 雲端：**2608 過、14 沒過、52 略過**。這 14 個是已知的基準線（Windows 路徑／Windows 行為、缺 `ntu_easy_llm`、
這個環境沒有的東西），跟這兩輪的改動無關。新的失敗只要不在這張清單上，就是真的壞了：

```
tests/test_brand.py::test_prog_name_follows_how_synox_was_started
tests/test_llm.py::test_openai_tool_call_round_trip
tests/test_llm.py::test_openai_no_tools_flag_and_errors
tests/test_llm.py::test_anthropic_wire_and_parse
tests/test_llm.py::test_openai_and_gemini_kinds_use_their_endpoints
tests/test_llm.py::test_errors_are_chinese
tests/test_mcp_stdio.py::test_server_roles_and_per_user_processes
tests/test_perm8.py::test_path_of_blocks_escape[parts4]
tests/test_review_a.py::test_typed_path_must_stay_in_own_folder
tests/test_review_b_exec.py::test_repro_cli_python_powershell_is_refused_at_gate1
tests/test_root_dir.py::test_root_from_synox_home_is_absolute
tests/test_sdk.py::test_synoxpack_registry_keys
tests/test_security.py::test_path_field_must_stay_in_user_dir
tests/test_wizard.py::test_startup_cmd_text
```

改頁面或發佈清單時至少跑：`tests/test_artifact_registry.py tests/test_clean_room.py tests/test_clean_room_check.py tests/test_release_layout.py`。

**打包 ZIP**：`python scripts/make_zip.py --tools <SYNOX_Libs 的 dist>` → `dist/SYNOX-<版本>.zip`（裡面一個 `SYNOX\` 資料夾；不帶 `INTERNAL`、
`.venv`、`data`、`config.json`）。不加 `--tools` 約 3.8 MB；`--wheelhouse` 可以附離線套件。

**打包安裝程式 .exe**：GitHub Actions → **Build Windows installer** → Run workflow（或推 `v*` tag，exe 放進**草稿** release）。
步驟與第一次跑要看什麼：`docs/release-build.md`。**這個 workflow 一次都還沒跑過。**

**發版**：照 `docs/versioning.md` 第 4 節（dev → `release/X.Y.Z` → main，tag `vX.Y.Z`，`release.py bump／check／notes`）。
SYNOX **還沒發過任何 release、沒打過 tag**。下一版＝**`0.2.1-beta.1`**，前提是先在真的 Windows 上用 ZIP 裝過一次（下一節）。
發佈頁要附 `SYNOX-0.2.1-beta.1.zip`＋`SHA256SUMS.txt`，勾 pre-release。教學頁的下載步驟就是指向這個發佈頁。

---

## 5. 沒有任何東西在真的 Windows 上試過

這兩輪全部在 Linux 雲端寫、用假的東西測。下面是**先要試的**，順序就是優先順序（清單與預期：`docs/handoff/clean-machine-test.md`）：

1. **`Setup.bat`（ZIP 路線）**：選語言（Enter＝Windows 語言）→ 先說清楚 → Enter 照建議／C 自訂 → 精靈。A1～A17。
2. **自帶 Python 的下載與解開**：從 GitHub 下載 python-build-standalone、對 SHA256、Windows 內建 `tar.exe` 解到 `runtime\python`、`python -m venv`。
   擋 github.com 時要停下來（A15）；有 Conda 的電腦（A14）。
3. **設定精靈的視窗**（Tk）：「下一步」那一列釘在最下面、完成頁的 `/tutorial` 那一行、開機自動啟動預設勾。
4. **.exe 在 CI 編譯**：第一次跑 `build-installer.yml`，再照 B-2 在空白 Windows 10／11 各裝一次；三個自己翻的 Inno 語言檔要真的編得過。
5. **沙盒探針**：`docs/lab/tools/windows-sandbox-probe/`（`synox-research.wsb`、`win-env-probe.ps1`、`win_appcontainer_probe.py`，說明在那裡的 README）。
   ADR 0022 的沙盒能不能在 Windows 上做，要看這個結果。

其他寫好沒實測的：教學引擎在真的瀏覽器裡圈東西、外觀包的消毒、「遇到問題？」的 GitHub 表單預填、Discord、外部服務（見本資料夾其他文件）。

---

## 6. 要擁有者決定的

1. **大標語**：`brand.SLOGAN` 暫用「先問你，再動手。」，還沒定案（`docs/lab/slogan/index.html` 有預覽）。定了只改 `brand.py`，再跑
   `scripts/make_landing.py`、`scripts/make_cli_welcome.py`。
2. **Gate 1（ADR 0022）**：生態系橋接（OpenClaw、Hermes 的工具）與沙盒是提案，之後再決定；設定頁那兩張卡片都標 ⏳。
3. **公開文件的語氣**：README、介紹頁、教學頁、`docs/versioning.md` 這些給一般人看的文件，請擁有者整體看一次口吻。
4. **`/help` 改版與自訂指令（alias）**：規劃在 `docs/lab/2026-11-13-onboarding-help-aliases-plan.md`，**做到一半**（教學引擎做完了；新 `/help`、範例、alias 還沒）。
5. **Windows 上的沙盒**：等第 5 節的探針結果再決定要不要做、用哪一種。
6. ADR 0023（自己更新）、`docs/versioning.md`（版本規則）都還是草案，要擁有者確認。

## 狀態

- SYNOX：`dev` 的 HEAD 是 `748db2f` 加上這次的教學頁、規格頁、本文件；**沒有 release、沒有 tag**。
- SYNOX_Libs：`main`＝`v0.2.0`；`dev`、`costume-wardrobe` 等合併；衣櫃的 `.synoxpack` 還沒上傳。
