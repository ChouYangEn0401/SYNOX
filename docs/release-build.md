# 自動建置 Windows 安裝程式（GitHub Actions）

- 狀態：**workflow 已寫好，但還沒在 GitHub 上跑過一次**（寫的那台沒有 Windows）。第一次跑請照下面「第一次跑要看什麼」。
- 檔案：[`.github/workflows/build-installer.yml`](../.github/workflows/build-installer.yml)、[`scripts/installer_ci.py`](../scripts/installer_ci.py)
  （下載＋驗 sha256、安全解壓縮、讀版本）、測試 `tests/test_installer_ci.py`。
- 設計：[ADR 0003 B](adr/0003-distribution-git-clone-and-installer.md)；空白電腦實測：[handoff/clean-machine-test.md](handoff/clean-machine-test.md)。
- 跑在 GitHub 的 `windows-latest`（全新、乾淨的機器，每次都一樣）：這就是 ADR 說的「發佈機」，不是擁有者的電腦。
  不用任何 secret；做出來的 exe **沒有簽章**。

## 怎麼開始建置

**A. 手動（最常用）**：GitHub 上 SYNOX repo → **Actions** → 左邊 **Build Windows installer** → 右邊 **Run workflow** →
選分支（例如 `dev`）→ 「Bundle tkinter…」預設打勾（帶視窗精靈；取消就只有文字版 `synox init`）→ **Run workflow**。
約 10～20 分鐘。

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
| 1 | checkout（不留 token）；`actions/setup-python` 裝**同一版**完整 CPython（建 venv、挑 wheel、拿 tkinter） | 是 |
| 2 | `installer_ci.py version`：`pyproject.toml` 與 `synox.__version__` 要一樣；tag 要等於 `v<版本>` | 是 |
| 3 | `scripts/prepublish_check.py --worktree-only`（密鑰、本機路徑、個人信箱） | 是 |
| 4 | 下載三個外部檔，**每個都先對 sha256**：python.org 的 embeddable zip、SYNOX_Libs 的 tools zip、Inno Setup 安裝檔；再檢查 `python.exe` 與 Inno 安裝檔的 Authenticode 簽章（發行者要對） | 是 |
| 5 | 靜默安裝 Inno Setup 到暫存資料夾 | 是 |
| 6 | 乾淨 venv `pip install .` → `lock_deps.py` → `pip download`（`--only-binary=:all:`，cp312／win_amd64）＋ pip、virtualenv、setuptools → `lock_deps.py --wheelhouse`（寫進 sha256）→ `--check` | 是 |
| 7 | `stage_installer.py --python-embed … --wheelhouse … --tools … [--tk-from <setup-python 的資料夾>]` | 是 |
| 8 | `ISCC.exe /DAppVersion=<版本> /DStageDir=<stage> setup\installer\synox.iss` → 算 sha256 → 上傳 artifact | 是 |
| 9 | **離線煙霧測試**：複製一份 stage，照 bootstrap 對 `runtime\python` 做的事做一次（wheelhouse 裝 pip／virtualenv → `virtualenv .venv` → `--no-index` 裝 lock → `--no-deps -e .`）→ import、`synox tools list`；`doctor --offline` 與 tkinter 只出警告 | 是（但 exe 已經先上傳了，方便查） |
| 10 | `scripts/clean_room_check.py --tools …` | **否**（先觀察；在 CI 上綠過之後可以把 `continue-on-error` 拿掉） |
| 11 | （只有 tag）另一個 job，只有這裡有 `contents: write`：建立／更新**草稿** release | 是 |

權限：整份預設 `contents: read`；只有 tag 的 release job 有 `contents: write`。所有第三方 action 都釘在完整的 commit SHA（註解寫版本）。

## 釘住的版本與 sha256（從哪裡來）

都在 workflow 最上面的 `env:`；`tests/test_installer_ci.py` 會檢查格式，也檢查這份文件跟 workflow 的值一樣。

| 東西 | 版本 | sha256 | 來源／怎麼核對 |
|---|---|---|---|
| Python embeddable（64-bit） | 3.12.10 | `4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3` | 寫的那台**連不到 python.org**，所以這個值是跟 8 個互不相關的公開 repo 釘的同一個檔案交叉比對出來的（8 個都一樣）。CI 另外檢查 `python.exe` 是 Python Software Foundation 簽的。**請擁有者到 python.org 的 3.12.10 release 頁面核對一次**。3.12.10 是 3.12 最後一個有 Windows 二進位檔的版本，也是 `setup/bootstrap.ps1` 的 `$EmbedVersion` |
| SYNOX_Libs tools | `v0.2.0` / `tools-0.2.0.zip` | `f573252dfbbb374c427bc7b2091ac09cacf50b3747ec0b9c970517d047d6658c` | 下載後自己算，並且跟 GitHub releases API 給這個 asset 的 `digest` 一致 |
| Inno Setup | 6.7.4（`is-6_7_4`） | `a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c` | 從 `jrsoftware/issrc` 的 GitHub release 下載後自己算（jrsoftware.org 這台也連不到）；CI 另外檢查簽章發行者是 `Pyrsys B.V.`（安裝檔裡的憑證）。授權：該 tag 的 `license.txt`，可商用。選 6 不選 7：`synox.iss` 是照 6 寫的，7 要另外測 |
| pip／virtualenv／setuptools | 26.3／21.15.6／84.2.1 | 不釘；每個 wheel 的 sha256 在 `STAGE-MANIFEST.txt` | PyPI。virtualenv 自己的相依（distlib、filelock、platformdirs、packaging、python-discovery）建置當下解析 |
| SYNOX 的相依 | 每次建置當下產生 `requirements.lock` | 寫在 lock 裡（`--hash=sha256:`） | 有 commit 進 git 的 `requirements.lock` 時先照它裝 |
| actions/checkout | v7.0.1 | commit `3d3c42e5aac5ba805825da76410c181273ba90b1` | `git ls-remote --tags` |
| actions/setup-python | v7.1.0 | commit `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` | 同上 |
| actions/upload-artifact | v7.0.2 | commit `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | 同上 |
| actions/download-artifact | v8.0.2 | commit `9000827ccba6bdab643e8b6fd33ac0654aef8333` | 同上 |

**換版本**：版本和 sha256 一起改。檔案的 sha256 自己下載後算（PowerShell `Get-FileHash`），能的話再跟官方頁面公布的值比；
action 用 `git ls-remote --tags https://github.com/<owner>/<repo>.git` 找 tag 指的 commit。換 Python 時也要看
`setup/bootstrap.ps1` 的 `$EmbedVersion`（測試會檢查兩邊的 X.Y 一樣）。

## 跟「bootstrap 改用 uv 管理的私有 Python」的關係

另一個工作正在把 `Setup.bat`／`setup/bootstrap.ps1` 改成用 uv 準備一份私有 Python。安裝程式這邊**不受影響**：

- 安裝程式照 ADR 0003 仍然附 `runtime\python`（官方 embeddable）＋ `wheelhouse\`；bootstrap 找 Python 時**第一個**就是
  `runtime\python`，所以安裝程式版不會去叫 uv、也不用連網。
- 那邊改完後，請確認兩件事還成立（第 9 步的煙霧測試就是照「現在的」bootstrap 寫的）：
  1. 有 `runtime\python` 時仍然先用它，並且從 `wheelhouse\` 離線裝 pip、virtualenv、相依；
  2. 如果 bootstrap 改用別的方式建 `.venv`（例如 `uv venv`），wheelhouse 也要有它需要的東西，或者在 workflow 第 6 步多下載；
     第 9 步也要跟著改成同一套指令。

## 第一次跑要看什麼

1. 第 4 步：三個 sha256 和兩個簽章都過（python.org 的值是交叉比對來的，這一步就是真正的核對）。
2. 第 6 步印出的 `requirements.lock` 與 wheel 清單：每個都是 `cp312`／`win_amd64` 或 `py3-none-any`。
3. 第 9 步：`virtualenv` 能不能從 embeddable Python 建出 `.venv`、`tools list` 列出 9 個工具；tkinter 那行是警告還是印出 `tcl 8.6.x`
   （這回答了 ADR 0003 的 QD3 的一半：Tcl 能不能在 `.venv` 裡載入；真的開視窗還是要在空白電腦上看）。
4. 第 10 步的結果（只是參考）。
5. 下載 exe，到空白 Windows 11 跑 B1～B7。

## 還沒驗證的

- 整個 workflow 沒跑過：PowerShell 步驟、Inno Setup 的靜默安裝參數、簽章發行者字串、`gh release` 那段都只有語法檢查
  （YAML 解析＋ actionlint 1.7.12＋ shellcheck，0 個問題）。
- Python embeddable 的 sha256 沒有直接從 python.org 核對（見上表）。
- exe 本身的安裝／解除安裝沒有在 CI 跑：`synox.iss` 的 `[Run]` 那行（跑 `Setup.bat`）沒有 `skipifsilent`，用 `/VERYSILENT` 裝會直接
  開 Setup.bat 問語言而卡住。所以 CI 只測 stage（第 9 步），安裝程式本身靠 B1～B7。
- 視窗精靈（tkinter）在 `.venv` 裡能不能開視窗、SmartScreen 與防毒的反應：只能在真的電腦上看。
- 第三方授權清單（handoff B-1 第 11 項）還沒放進 stage。
- `ntu_easy_llm` 不在 wheelhouse（lock 不含 `llm` 組）：安裝程式版用 API 金鑰的 AI 仍要另外裝（QD2）。

## 留給擁有者決定的

1. **簽章（QD1）**：要簽的話，`synox.iss` 打開 `SignTool=`／`SignedUninstaller=yes`，workflow 加一步簽章（憑證或 Azure Trusted Signing
   放 GitHub secret，最好再用 GitHub Environment 要人核准）。到那時這份 workflow 才會需要 secret。
2. **`requirements.lock` 要不要進 git**：有 sha256 的那份只對 Python 3.12＋Windows 64 位元有效（`cffi`、`charset-normalizer`
   是 cp312 專屬的 wheel）；git clone 的人用 3.11／3.13 照它裝會因為雜湊對不上而失敗。要進 git 的話建議 commit
   `build-records` 裡的 `requirements-unhashed.lock`（改名成 `requirements.lock`）。
3. `synox.iss` 的 `[Run]` 要不要加 `skipifsilent`（這樣 CI 和大量部署可以用 `/VERYSILENT`）；那個檔不在這次的範圍。
4. 什麼時候升 Inno Setup 7；clean-room 檢查要不要改成會擋（`continue-on-error` 拿掉）；tkinter 要不要一直預設帶。
5. `pyproject.toml` 的 `license = {text = …}`：新版 setuptools 說 2027-02-18 之後不再支援這種寫法。這裡釘了 setuptools 84.2.1
   （現在只是警告），之後要升 setuptools 前先改成 SPDX 字串（例如 `license = "AGPL-3.0-or-later AND Apache-2.0"`）。
