# 自動建置 Windows 安裝程式（GitHub Actions）

- 狀態：**workflow 已寫好，但還沒在 GitHub 上跑過一次**（寫的那台沒有 Windows）。第一次跑請照下面「第一次跑要看什麼」。
- 檔案：[`.github/workflows/build-installer.yml`](../.github/workflows/build-installer.yml)、[`scripts/installer_ci.py`](../scripts/installer_ci.py)
  （下載＋驗 sha256、安全解壓縮、讀版本）、測試 `tests/test_installer_ci.py`。
- 設計：[ADR 0003 B](adr/0003-distribution-git-clone-and-installer.md)；空白電腦實測：[handoff/clean-machine-test.md](handoff/clean-machine-test.md)。
- 跑在 GitHub 的 `windows-latest`（全新、乾淨的機器，每次都一樣）：這就是 ADR 說的「發佈機」，不是擁有者的電腦。
  不用任何 secret；做出來的 exe **沒有簽章**。

## 怎麼開始建置

**A. 手動（最常用）**：GitHub 上 SYNOX repo → **Actions** → 左邊 **Build Windows installer** → 右邊 **Run workflow** →
選分支（例如 `dev`）→ **Run workflow**。約 10～20 分鐘。附的 Python 一定有 tkinter（視窗精靈），不用再勾選。

**B. 打 tag（要發版時）**：tag 一定要是 `v`＋`pyproject.toml` 的版本（例如版本 `0.2.0` → `v0.2.0`），不一樣會在第一步就失敗。

```
git tag v0.2.0
git push origin v0.2.0
```

tag 會多做一件事：把 exe 和 `SHA256SUMS.txt` 放進一個 **草稿（draft）release**。**workflow 永遠不會公開發佈**：
你測完之後自己到 **Releases** → 那個草稿 → **Edit** → **Publish release**。同一個 tag 重跑只會換掉草稿裡的檔案；
已經公開的 release 它不會碰（會直接失敗）。

## 去哪裡下載

- 手動或 tag 都有：那次執行的頁面（Actions → 點那一次）最下面 **Artifacts**：
  - `SYNOX-Setup-<版本>-<commit 前 7 碼>`：zip，裡面是 `SYNOX-Setup-<版本>.exe` 與 `SHA256SUMS.txt`；
  - `build-records-<版本>`：這次用的 `requirements.lock`（有 sha256）、`requirements-unhashed.lock`、`STAGE-MANIFEST.txt`（每個 wheel 與工具的 sha256）。
  - 保留 30 天。執行頁面的 **Summary** 也印出 exe 的 sha256、大小、各個版本。
- tag：**Releases** 裡的草稿（只有有寫入權限的人看得到）。
- 下載後核對：PowerShell `Get-FileHash .\SYNOX-Setup-0.2.0.exe`（或 `certutil -hashfile SYNOX-Setup-0.2.0.exe SHA256`），要跟
  `SHA256SUMS.txt` 一樣。

## 在空白的 Windows 11 上測

照 [handoff/clean-machine-test.md](handoff/clean-machine-test.md) 的 **0（準備）** 和 **B-2（B1～B7）**；B-1（在發佈機上自己做 exe）
**改由這個 workflow 代做**，可以跳過。

- 用 VM、Windows Sandbox 或新的**一般使用者**帳號；不要用開發機。B3 建議先斷網（安裝是完全離線的）。
- **SmartScreen**：沒簽章，第一次執行會出現「Windows 已保護您的電腦」→ 點 **其他資訊** → **仍要執行**。從瀏覽器下載的 zip
  也可能被標記，解壓前可以在 zip 的「內容」勾「解除封鎖」。防毒有沒有叫、叫什麼，請記下來（回報格式在那份文件最後）。
- 不需要管理員（沒有 UAC 盾牌）；裝到 `%LOCALAPPDATA%\Programs\SYNOX`。

## workflow 做了什麼（跟 ADR 0003 B 的步驟對照）

| # | 步驟 | 失敗就停？ |
|---|---|---|
| 1 | checkout（不留 token）；`actions/setup-python` 裝**同一個 X.Y** 的 CPython（只拿來建 venv、挑 cp312 wheel；不會附進安裝程式） | 是 |
| 2 | `installer_ci.py version`：`pyproject.toml` 與 `synox.__version__` 要一樣；tag 要等於 `v<版本>` | 是 |
| 3 | `scripts/prepublish_check.py --worktree-only`（密鑰、本機路徑、個人信箱）；接著 `installer_ci.py check-iss`（安裝程式腳本的靜態檢查） | 是 |
| 4 | 下載兩個外部檔，**每個都先對 sha256**：SYNOX_Libs 的 tools zip、Inno Setup 安裝檔；再檢查 Inno 安裝檔的 Authenticode 簽章（發行者要對） | 是 |
| 5 | 靜默安裝 Inno Setup 到暫存資料夾；接著 `installer_ci.py check-iss --inno-default <Inno>\Default.isl`：我們自己的三個 Inno 語言檔要涵蓋這個 Inno 的 `Default.isl` 每一個 key | 是 |
| 6 | 乾淨 venv `pip install .` → `lock_deps.py` → `pip download`（`--only-binary=:all:`，cp312／win_amd64）＋ pip、setuptools → `lock_deps.py --wheelhouse`（寫進 sha256）→ `--check` | 是 |
| 7 | `stage_installer.py --fetch-python --wheelhouse … --tools …`：照 `setup/bootstrap.ps1` 釘的網址下載 SYNOX 自己的 Python、對 sha256、檢查路徑後解到 `runtime\python`（跟 ZIP 的 `Setup.bat` 下載的是**同一個檔案**） | 是 |
| 8 | `ISCC.exe /DAppVersion=<版本> /DStageDir=<stage> setup\installer\synox.iss` → 算 sha256 → 上傳 artifact | 是 |
| 9 | **離線煙霧測試**：複製一份 stage，照 bootstrap 對 `runtime\python` 做的事做一次（`python -m venv .venv` → `--no-index` 裝 lock → `--no-deps -e .`）→ import、`synox tools list`、`.venv` 裡 `import tkinter` 載得起 Tcl（不行就停）；`doctor --offline` 只出警告 | 是（但 exe 已經先上傳了，方便查） |
| 10 | `scripts/clean_room_check.py --tools …` | **否**（先觀察；在 CI 上綠過之後可以把 `continue-on-error` 拿掉） |
| 11 | （只有 tag）另一個 job，只有這裡有 `contents: write`：建立／更新**草稿** release | 是 |

權限：整份預設 `contents: read`；只有 tag 的 release job 有 `contents: write`。所有第三方 action 都釘在完整的 commit SHA（註解寫版本）。

## 釘住的版本與 sha256（從哪裡來）

都在 workflow 最上面的 `env:`，只有附的 Python 例外：它釘在 `setup/bootstrap.ps1`（`$PythonVersion`、`$PythonBuild`、
`$PythonSha256`、`$PythonUrl`），ZIP 的 `Setup.bat` 和這裡的 `stage_installer.py --fetch-python` 都讀那四行，所以兩邊一定是同一個
Python。`tests/test_installer_ci.py` 會檢查格式，也檢查這份文件跟 workflow、bootstrap 的值一樣。

| 東西 | 版本 | sha256 | 來源／怎麼核對 |
|---|---|---|---|
| SYNOX 自己的 Python（附在安裝程式裡；ZIP 由 `Setup.bat` 下載） | CPython 3.12.16，python-build-standalone `20261026`，`x86_64-pc-windows-msvc-install_only_stripped.tar.gz` | `1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149` | 網址：`https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz`。三個來源一致：那個 release 的 `SHA256SUMS`、uv 0.13.6 內建的下載清單、2026-11-13 實際下載後自己算。只有 `.tar.gz`（沒有 zip）。這個專案的執行檔**沒有 Authenticode 簽章**，所以只靠 sha256。裡面有 python.exe、pip、venv、tkinter＋Tcl/Tk 8.6、vcruntime |
| CI 建置用的 CPython（`actions/setup-python`） | 3.12.10 | 不附進安裝程式 | 只用來建 venv、下載 cp312 wheel。3.12 之後的修補版在 python.org 只有原始碼，setup-python 沒有 Windows 版，所以停在 3.12.10；X.Y 跟上面一樣就好（測試會檢查） |
| SYNOX_Libs tools | `v0.2.0` / `tools-0.2.0.zip` | `f573252dfbbb374c427bc7b2091ac09cacf50b3747ec0b9c970517d047d6658c` | 下載後自己算，並且跟 GitHub releases API 給這個 asset 的 `digest` 一致 |
| Inno Setup | 6.7.4（`is-6_7_4`） | `a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c` | 從 `jrsoftware/issrc` 的 GitHub release 下載後自己算（jrsoftware.org 這台也連不到）；CI 另外檢查簽章發行者是 `Pyrsys B.V.`（安裝檔裡的憑證）。授權：該 tag 的 `license.txt`，可商用。選 6 不選 7：`synox.iss` 是照 6 寫的，7 要另外測 |
| pip／setuptools | 26.3／84.2.1 | 不釘；每個 wheel 的 sha256 在 `STAGE-MANIFEST.txt` | PyPI。不再需要 virtualenv：附的 Python 有 `venv`（`.venv` 裡先用它自帶的 pip，再從 wheelhouse 離線裝） |
| SYNOX 的相依 | 每次建置當下產生 `requirements.lock` | 寫在 lock 裡（`--hash=sha256:`） | 有 commit 進 git 的 `requirements.lock` 時先照它裝 |
| actions/checkout | v7.0.1 | commit `3d3c42e5aac5ba805825da76410c181273ba90b1` | `git ls-remote --tags` |
| actions/setup-python | v7.1.0 | commit `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` | 同上 |
| actions/upload-artifact | v7.0.2 | commit `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | 同上 |
| actions/download-artifact | v8.0.2 | commit `9000827ccba6bdab643e8b6fd33ac0654aef8333` | 同上 |

**換版本**：版本和 sha256 一起改。檔案的 sha256 自己下載後算（PowerShell `Get-FileHash`），能的話再跟官方頁面公布的值比；
action 用 `git ls-remote --tags https://github.com/<owner>/<repo>.git` 找 tag 指的 commit。換附的 Python：只改
`setup/bootstrap.ps1` 那四行（sha256 抄那個 release 的 `SHA256SUMS`，再自己下載算一次），X.Y 變了的話 workflow 的
`PYTHON_VERSION` 也要跟著換（測試會檢查兩邊的 X.Y 一樣）。

## .exe 和 ZIP 用同一個 Python

- 不用 uv，也不再附 python.org 的可攜版（embeddable，沒有 tkinter）。兩條路都是 python-build-standalone 的同一個
  `install_only_stripped` 檔案（釘在 `setup/bootstrap.ps1`）：
  - **.exe**：建置時 `stage_installer.py --fetch-python` 下載、對 sha256、解到 `runtime\python`，附在安裝程式裡；使用者那邊不用連網。
  - **ZIP**：`Setup.bat` 看到沒有 `runtime\python` 才下載同一個檔案、對 sha256（不對就刪掉、停下來），用 Windows 內建的
    `%SystemRoot%\System32\tar.exe` 解開（Windows 10 1803 以後才有；PowerShell 5.1 的 `Expand-Archive` 只會解 zip）。
- 兩邊接下來都一樣：`runtime\python\python.exe -m venv .venv` → 有 `wheelhouse\` 就離線裝。第 9 步的煙霧測試就是照這套指令寫的。
- 安裝程式更新時（`synox.iss` 的 `[InstallDelete]`）先刪掉舊的 `runtime\python` 和 `.venv`：舊版附的可攜版留下的
  `python312._pth` 會讓新的 python.exe 進入隔離模式；`.venv` 由安裝完跑的 `Setup.bat` 離線重建。

## 第一次跑要看什麼

1. 第 4 步：兩個 sha256 和 Inno 的簽章都過；第 7 步：附的 Python 的 sha256 過（`STAGE-MANIFEST.txt` 第一行印出來）。
2. 第 6 步印出的 `requirements.lock` 與 wheel 清單：每個都是 `cp312`／`win_amd64` 或 `py3-none-any`。
3. 第 9 步：`python -m venv` 能不能建出 `.venv`、`tools list` 列出 9 個工具、tkinter 那行印出 `tcl 8.6.x`
   （Tcl 能在 `.venv` 裡載入；真的開視窗還是要在空白電腦上看）。
4. 第 10 步的結果（只是參考）。
5. 下載 exe，到空白 Windows 11 跑 B1～B7。

## 安裝程式的畫面與語言（擁有者 2026-11-13 的決定）

規格：[installer/spec.html](installer/spec.html) 第 8 節 Q1～Q9。`setup/installer/synox.iss` 現在是這樣走：

**選語言 → 歡迎 → 建議｜自訂 → 安裝中 → 完成**（自訂多兩頁：安裝位置、要準備哪些東西）。

- **語言（Q7）**：Inno Setup 自己的選語言視窗，每次都出現，預選 Windows 的顯示語言（對不上就 English）；12 種，每種寫
  「原文名 (拉丁字母名)」。選的語言寫進 SYNOX 資料夾的 `lang.txt`，再用 `Setup.bat -Lang <代號>` 交給設定精靈。
  Inno 的視窗是下拉選單＋「確定」，清單照名字排序（不是我們的順序）；要做成規格圖上那種清單，得用 `CreateCustomForm` 自己畫，之後再說。
- **歡迎（Q4）**：沒有「我同意」那一頁（不設 `LicenseFile`）。歡迎頁一句「歡迎使用 SYNOX，用得開心。」、四個短點，最下面一行
  「個人使用免費。要拿去做商業用途，請看 AGPL-3.0 授權條款」，點了用記事本打開 `LICENSING.md`（中文介面）或 `LICENSE`（其他語言）。
  兩個檔照樣裝進 SYNOX 資料夾。左邊與右上角的圖拿掉了（`WizardImageFile=`、`WizardSmallImageFile=`），比較乾淨。
- **建議（Q3、Q1）**：SYNOX 自己的 Python、桌面與開始功能表捷徑、`.synoxpack` 點兩下安裝、開機自動啟動、教學；不裝工具。
  選「建議」時按鈕直接寫「安裝」。**自訂**：同樣的預設值，多一項「全部官方工具都裝（不建議）」預設不勾；勾了的話，安裝程式只把它記在
  `installer-choices.json`，真正的安裝在設定精靈按「完成並開始」時從 `tools\`（安裝程式附的）做（`synox tools install --all --yes`，
  照原本的安全檢查，T2 不自動裝），安裝程式本身不連網。
- **Claude Code（Q2）**：安裝中的最後一步，只在這台還沒有時才裝，`setup\installer\claude-code.ps1` 跑官方的
  `irm https://claude.ai/install.ps1 | iex`（裝在使用者資料夾、不用管理員），最多等 15 分鐘；失敗或逾時不算安裝失敗，完成頁說之後去設定精靈補。
- **完成**：勾著「現在打開設定精靈」→ 跑 `Setup.bat`（會開一個視窗準備套件，再開精靈）。精靈看到 `installer-choices.json`，完成頁
  就只剩「完成後立刻開啟 SYNOX」。開始功能表另有「SYNOX 設定精靈」「解除安裝 SYNOX」。
- **解除安裝（Q9）**：先一個畫面說會移除／會留著什麼，「連我的資料也一起刪除」預設不勾；勾了會再問一次（預設「否」）。不勾就照舊
  留下 `config.json`、`data\`、`packs\`。`/SILENT` 解除安裝一律留資料。
- **不簽章（Q6）**：alpha 先不簽。下載的地方要放 exe 的 **SHA-256** 指紋，並說明 SmartScreen 的兩步：按「**其他資訊**」→ 按「**仍要執行**」。
  核對方法見上面「去哪裡下載」。

靜態檢查：`python scripts/installer_ci.py check-iss`（workflow 第 3 步之後也會跑；`tests/test_installer_script.py`）——頁面相關設定、
12 種語言、每個語言檔的 key 跟英文一樣、自訂頁的預設值、解除安裝不刪資料。**這台沒有 Windows，`synox.iss` 沒有真的編譯過**，
第一次在 CI 跑 ISCC 時請看有沒有錯（Pascal 程式碼的語法只有 ISCC 會檢查）。

### 安裝畫面的語言檔（Inno Setup 的按鈕、「瀏覽…」這些內建的字）

我們自己的字（歡迎、建議／自訂、每個勾選、解除安裝畫面）在 `setup/installer/lang/<代號>.isl`，12 種都有（模型翻的，要母語者校對）；
`lang/en.isl` 先載入，所以哪個語言少了某句就退回英文。Inno 內建的字要靠 Inno 的語言檔：

| 語言 | Inno Setup 6.7.4 | 用哪個檔 |
|---|---|---|
| English | 內建 | `compiler:Default.isl` |
| Español、Français、Deutsch、Português (Brasil)、Русский、العربية、日本語、한국어 | **官方**，隨 Inno Setup 安裝 | `compiler:Languages\Spanish.isl`、`French.isl`、`German.isl`、`BrazilianPortuguese.isl`、`Russian.isl`、`Arabic.isl`、`Japanese.isl`、`Korean.isl` |
| 繁體中文、简体中文、हिन्दी | Inno 沒有官方檔 → **SYNOX 自己翻的**（2026-11-14 擁有者決定） | `setup/installer/lang/inno/ChineseTraditional.isl`、`ChineseSimplified.isl`、`Hindi.isl` |

（2026-11-13 用 `jrsoftware/issrc` 的 `is-6_7_4` tag 核對：`Files/Languages/` 只有上面 8 個官方檔；中文與印地文只有網友貢獻的非官方檔。）

這三個檔是 **SYNOX 自己的翻譯**：照 Inno Setup 6.7.4 `Default.isl` 的 key 逐句翻（只拿它當 key 的清單），沒有用、也沒有抄任何第三方或
網友貢獻的翻譯檔，所以沒有授權要另外處理，也不用放進第三方授權清單。都是模型翻的，**要母語者校對**；有拿不準的句子寧可留英文。
寫法：UTF-8＋BOM、CRLF（`.gitattributes` 管）；按鈕的快速鍵照中日韓的習慣寫成「下一步(&N) >」（印地文也一樣，Alt＋拉丁字母在
任何鍵盤都按得到）；`%1`、`%n`、`[name]` 這些代換符號一個都不能少。繁中用台灣的說法（檔案、資料夾、安裝程式、下一步、瀏覽）。

檢查（`check-iss`，不用 Windows）：`setup/installer/lang/inno/default-keys.txt` 記著 `Default.isl` 的每個 key（293 個：
`[Messages]` 281＋`[CustomMessages]` 12）和各自的代換符號、`&` 的數量（不含英文原文）；三個檔都要剛好有這些 key、一樣的代換符號
與 `&` 數量，英文是空的（`BeveledLabel` 這類）就也要空著，`[LangOptions]` 的 `LanguageID`／`LanguageCodePage` 要對
（`$0404`／950、`$0804`／936、`$0439`／0）。workflow 第 5 步裝好 Inno 之後，再拿**真的** `Default.isl` 比一次這份清單。
**升級 Inno Setup 時**：`python scripts/installer_ci.py inno-keys <Inno>\Default.isl --source "Inno Setup X.Y.Z"` 重寫清單，
`check-iss` 會列出三個檔缺哪些 key，補翻（不確定就先放英文）。

## 還沒驗證的

- 整個 workflow 沒跑過：PowerShell 步驟、Inno Setup 的靜默安裝參數、簽章發行者字串、`gh release` 那段都只有語法檢查
  （YAML 解析＋ actionlint 1.7.12＋ shellcheck，0 個問題）。
- 附的 Python（python-build-standalone）在 Windows 上：只在 Linux 上用同一個 release 的 Linux 版做過「解開 → `-m venv` →
  `import tkinter` → 開 Tk 視窗 → `pip install -e .`」，Windows 版只核對了 sha256、檔案內容（python.exe、venv、tkinter、Tcl/Tk 8.6）
  和 stage 的結果，沒有真的在 Windows 上跑過。
- exe 本身的安裝／解除安裝沒有在 CI 跑：`synox.iss` 的 `[Run]` 那行（跑 `Setup.bat -Lang <代號>`）沒有 `skipifsilent`，用 `/VERYSILENT` 裝
  還是會開 Setup.bat 的視窗（語言已經帶過去、`installer-choices.json` 也在，不會停在語言題或「建議／自訂」那一題）；Claude Code 那一步
  在 `/VERYSILENT` 也會跑（要上網）。所以 CI 只測 stage（第 9 步），安裝程式本身靠 B1～B7。
- 視窗精靈（tkinter）在 `.venv` 裡能不能開視窗、SmartScreen 與防毒的反應：只能在真的電腦上看。
- 第三方授權清單（handoff B-1 第 11 項）還沒放進 stage。
- `ntu_easy_llm` 不在 wheelhouse（lock 不含 `llm` 組）：安裝程式版用 API 金鑰的 AI 仍要另外裝（QD2）。

## 留給擁有者決定的

1. **簽章（QD1）**：2026-11-13 擁有者決定 alpha 先不簽（規格 Q6）；公開宣傳之前再改用雲端簽章服務。要簽的話，`synox.iss` 打開 `SignTool=`／`SignedUninstaller=yes`，workflow 加一步簽章（憑證或 Azure Trusted Signing
   放 GitHub secret，最好再用 GitHub Environment 要人核准）。到那時這份 workflow 才會需要 secret。
2. **`requirements.lock` 要不要進 git**：有 sha256 的那份只對 Python 3.12＋Windows 64 位元有效（`cffi`、`charset-normalizer`
   是 cp312 專屬的 wheel）；git clone 的人用 3.11／3.13 照它裝會因為雜湊對不上而失敗。要進 git 的話建議 commit
   `build-records` 裡的 `requirements-unhashed.lock`（改名成 `requirements.lock`）。
3. `synox.iss` 的 `[Run]` 要不要加 `skipifsilent`（這樣 CI 和大量部署可以用 `/VERYSILENT`）；那個檔不在這次的範圍。
4. 什麼時候升 Inno Setup 7；clean-room 檢查要不要改成會擋（`continue-on-error` 拿掉）。
5. `pyproject.toml` 的 `license = {text = …}`：新版 setuptools 說 2027-02-18 之後不再支援這種寫法。這裡釘了 setuptools 84.2.1
   （現在只是警告），之後要升 setuptools 前先改成 SPDX 字串（例如 `license = "AGPL-3.0-or-later AND Apache-2.0"`）。
