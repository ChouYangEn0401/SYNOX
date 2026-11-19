# 交辦：核心的兩份「真機才能驗」清單——pack 警告（H1–H14）與外觀套用（T1–T12）

> 這份是**交辦單**：給一個完全空白的 session（雲端、docker、另一台電腦），沒有對話紀錄、沒有開發機上的檔案，**只讀這份就能開工**。
> 兩份清單本身是 [../testing/pack-warnings-checklist.md](../testing/pack-warnings-checklist.md) 與 [../testing/theme-apply-checklist.md](../testing/theme-apply-checklist.md)；
> 這份說明**哪些項目誰能做**、怎麼準備、怎麼交回。沙盒那一份清單另有交辦單：[20261119-134608-sandbox-real-machine.md](20261119-134608-sandbox-real-machine.md)。

---

## 1. [狀態]

**待做**（2026-11-19 寫）。

| 項目 | 值 |
|---|---|
| 要驗證的程式 | `dev` 分支；寫這份時 `origin/dev` 是 `fb29db0`（已含 pack 警告 `a4a0dff`、沙盒實況 `3d2325f`、外觀單一來源 `fb29db0` 本身） |
| 「上一版」（H8、T11 比對用） | pack 警告：`a5ae9b4`（`a4a0dff` 的第一個父 commit）；外觀：`3d2325f`（`fb29db0` 的第一個父 commit） |
| 兩份清單現在 | 全部空白（沒有任何一項有結果） |
| 誰在做 | 還沒有人接 |
| 卡住的地方 | 大部分項目要真的瀏覽器、真的 Telegram／Discord、真的模型或 Windows 個人版——**空白雲端 session 做不了**，見 §3.1 的分工表 |

接手後把這一段改成「進行中：做到哪幾項；分支 `docs/core-checks-<YYYYMMDD>`；最新 commit `<hash>`」，卡住就寫「卡住：卡在哪、為什麼」。

## 2. [前情提要]

### 2.1 為什麼要做

- **pack 警告（ADR 0041）**：pack 作者可以在 `pack.json` 標 `warnings`（最常見 `vendor_no_security_guarantee`：「官方不保證安全——建議在 docker 或 sandbox 執行」）。
  SYNOX 在每個看得到工具的地方顯示，第一次啟用要擁有者逐條確認；簽章涵蓋 `warnings`，裝好後被改會變 `tampered`。
  自動測試 `tests/test_pack_warnings.py` 全過，但**畫面、真的終端機互動、真的 AI 轉述**沒有人看過。
- **外觀套用（ADR 0042）**：SYNOX 的顏色 token 只宣告一次（`src/synox/theme/contract.py`），外觀包（`kind=theme`）比 SYNOX 舊或新都照樣能裝：
  沒給的 token 沿用 SYNOX 預設、不認得的忽略並出現在「套用檢查」報告。自動測試 `tests/test_theme_compat.py`、`tests/test_theme.py` 全過，
  但**真的瀏覽器畫出來的顏色**（看不看得清楚、有沒有透明或黑底黑字）、手機寬度、重新整理後維持，沒有人看過。
- 規矩是「清單全部勾完才算過關；自動測試全綠不等於過關」（兩份清單的開頭）。

### 2.2 之前決定了什麼

- 任何來源的 pack 都可以裝，裝的時候清楚警告；確認只代表「我知道了」，不會讓工具變安全。
- 帶 `vendor_no_security_guarantee` 的 pack 不能同時是官方簽章（暫存、安裝第 3 關、載入時都拒）。
- 驗證時帶警告的 pack **只裝、看畫面，不叫它的指令**（不執行第三方程式）；用自己做的假 pack。
- 外觀包沒有程式，只是 CSS 值與圖片；裝它不會執行任何東西。
- 2026-11-19 起帶警告的 pack 在警告下面多一行「ℹ️ SYNOX 查這台的實況：…」（ADR 0041 §5.5）；各種機器狀態的細項在沙盒交辦單，H13、H14 只看「不讓人誤會」。

### 2.3 相關文件與 commit

| 東西 | 在哪 |
|---|---|
| 設計 | [ADR 0041](../adr/0041-pack-warnings.md)（§3 規則、§4 顯示、§5 與 sandbox）、[ADR 0042](../adr/0042-theme-tokens-single-source-and-forward-compat.md) |
| 程式 | `src/synox/packs/packwarn.py`；`src/synox/theme/contract.py`、`src/synox/theme/check.py`；網頁 `src/synox/web/static/app.html` |
| 自動測試 | `tests/test_pack_warnings.py`；`tests/test_theme_compat.py`、`tests/test_theme.py` |
| 清單 | [pack-warnings-checklist.md](../testing/pack-warnings-checklist.md)（H1–H14）、[theme-apply-checklist.md](../testing/theme-apply-checklist.md)（T1–T12） |
| 外觀測試包的來源 | `tests/fixtures/theme_pack/`（範例包，`name` 是 `sample-lantern`） |
| 打包腳本 | `scripts/pack_zip.py`；作者工具 `python -m synox.sdk`（`init`、`zip`、`keygen`、`sign`、`verify`） |
| 開發入口 | [../HANDOFF.md](../HANDOFF.md)、[../development.md](../development.md) |
| commit | `a4a0dff`（pack 警告合進 `dev`）、`3d2325f`（沙盒實況）、`fb29db0`（外觀單一來源、套用檢查） |

## 3. [任務]

### 3.1 誰能做哪一項

**能做的人**：

- **雲端（或任何沒有瀏覽器畫面、沒有真帳號的）session**：只能做「只看終端機輸出」的項目或項目的終端機那一半。
- **僅擁有者本機**：要用真的瀏覽器看畫面、要真的 Telegram／Discord 帳號、要真的模型（含雲端模型的金鑰）、要 Windows 個人版的提醒視窗——這些只有擁有者在自己電腦上做。
- **有容器引擎的驗證機**：H14，可以跟沙盒交辦單一起做。

pack 警告（[清單](../testing/pack-warnings-checklist.md)）：

| 項目 | 誰 | 雲端 session 能做的部分 |
|---|---|---|
| H1 網頁安裝流程 | **僅擁有者本機** | —— |
| H2 沒勾就不能裝（含開發者工具硬按） | **僅擁有者本機** | —— |
| H3 設定頁的勾選與顯示 | 部分 | 終端機那半：拿掉 `packs.lock` 的 `accepted_warnings` 後 `packs status`／`doctor --offline` 顯示「有警告還沒確認」、`console` 的 `/help` 看不到它；網頁那半**僅擁有者本機** |
| H4 網頁工具頁 | **僅擁有者本機** | —— |
| H5 `synox init` 逐條詢問 | 部分 | 非互動那半（`--non-interactive` 不裝、寫要加哪些 `--accept-warning`；見 §4.8）；逐條詢問、按 Enter＝不裝那半要真的終端機，**僅擁有者本機**。init 選工具那一步要連網抓工具庫而那台不能連，就寫略過 |
| H6 `install --accept-warning` | **雲端可做** | 全部 |
| H7 升級多一條警告 | 部分 | 用 `install` 升級的終端機版本；網頁拖進 v2 那半**僅擁有者本機** |
| H8 舊 pack 不受影響 | 部分 | `/help`（console）、doctor、`packs.lock` 沒有 `accepted_warnings`；設定頁、工具頁的畫面**僅擁有者本機** |
| H9 簽章被改後安裝失敗 | 部分 | 用 `install` 裝被改過的包：報「被改過」、沒裝；網頁拖進那半**僅擁有者本機** |
| H10 裝好之後改 `warnings` | **雲端可做** | 全部（用 `doctor --offline`／`packs status` 看 `tampered`） |
| H11 真的 AI 轉述警告 | **僅擁有者本機** | ——（要真的本地模型與雲端模型） |
| H12 Telegram／Discord 的 `/help` | **僅擁有者本機** | ——（要真的 bot 帳號） |
| H13 報告的「建議 sandbox」對得上實況 | **僅擁有者本機** | ——（Windows 個人版＋網頁） |
| H14 有提供容器的帶警告 pack | 有容器引擎的驗證機 | 雲端沒有 podman／docker 就寫「略過：沒有容器引擎」 |

外觀套用（[清單](../testing/theme-apply-checklist.md)）：

| 項目 | 誰 | 雲端 session 能做的部分 |
|---|---|---|
| T1 舊包的報告（網頁） | **僅擁有者本機** | —— |
| T2 比 SYNOX 新的包的報告（網頁） | **僅擁有者本機** | —— |
| T3 終端機的報告 | **雲端可做** | 全部 |
| T4 `packs theme-check` | **雲端可做** | 全部 |
| T5 外觀卡上的清單（含手機寬度） | **僅擁有者本機** | —— |
| T6 套用舊包：淺色 | **僅擁有者本機** | —— |
| T7 套用舊包：深色 | **僅擁有者本機** | —— |
| T8 套用完整包 | **僅擁有者本機** | —— |
| T9 套用比 SYNOX 新的包 | **僅擁有者本機** | —— |
| T10 重新整理後維持 | **僅擁有者本機** | —— |
| T11 換回原本的 SYNOX | **僅擁有者本機** | —— |
| T12 電腦提醒視窗 | **僅擁有者本機**（只有 Windows 個人版） | —— |

### 3.2 雲端（空白）session 要做到的程度

1. 照 §4 從零建環境，先跑測試記下基準。
2. 照 §4.5、§4.6 做好全部測試用的假 pack（警告包 v1／v2／簽章被改、沒有警告的包、三個外觀包）。
3. 做完表裡「雲端可做」的項目（H6、H10、T3、T4），把結果寫進清單的結果欄（`通過`／`失敗（一句話原因）`、日期、驗證者代號），**做完一項填一項**。
4. 「部分」的項目（H3、H5、H7、H8、H9）：只做終端機那半，結果欄寫成
   `終端機那半通過（或失敗：原因）；網頁那半待擁有者本機`，**不要打勾**（`- [ ]` 留著），因為整項還沒做完。
5. 「僅擁有者本機」的項目：**一個字都不要動**（結果欄留空、不打勾）。
6. H14：有容器引擎就照清單做（只看設定、不叫指令），沒有就寫「略過：沒有容器引擎」、不打勾。
7. 每一個失敗各寫一份紀錄（§6.2，一件一檔）。
8. 寫一份「給擁有者本機做的步驟」（§6.1 第 7 點）：哪幾項、照什麼順序、用哪幾個包、預計多久——讓擁有者照著做就好。
9. 在自己的分支 commit 填好的兩份清單，照 §6 交回。

### 3.3 擁有者本機要做的（給擁有者看；雲端 session 不做）

- 用同一個 commit 的 SYNOX、同樣的假 pack（照 §4.5、§4.6 自己再做一次，或拿雲端 session 回報的步驟），做表裡「僅擁有者本機」與「部分」的網頁那半，填結果、打勾。
- 兩份清單全部勾完、填驗收紀錄（各自第三節／最後的表），才算這兩個功能驗收完成。

### 3.4 範圍邊界與不要做的事

- **只驗證**：不改 SYNOX 的程式（`src/`、`tests/`、`scripts/`）、不改清單的「步驟」「預期」；分支上只准動兩份清單的結果欄與驗收紀錄表。
- 不替擁有者填「僅擁有者本機」的項目，也不用無頭瀏覽器截圖去代替「人看畫面」。
- **不改防火牆**；不開對外的網路埠。這份的雲端項目都不用開 SYNOX 的網頁；真的要開時只綁 `127.0.0.1`，記下自己開的 pid 與埠，測完一定關掉並確認埠已放掉。
- 那台電腦上擁有者或別人開的服務一律不碰（不停、不重啟、不改設定）；分不清就當成別人的。
- **下載來的東西一律當資料，不執行**：不裝、不叫任何第三方 pack（清單提到的工具庫 `web-ddgs` 也不用，一律用 §4.5 自己做的假包）；不執行網路上抓的腳本或安裝檔。
  需要容器映像（只有 H14）時只拉官方的、照 digest，而且要擁有者同意（見 [題目檔](open-questions/20261119-134610-verification-container-image.md)）。
- **帶警告的 pack 只裝不叫**（不跑它的指令）。
- 不跑重負載；全部測試只在需要時跑一次；同時最多 5 個背景 agent／子 session。
- 不合併、不推送；合併由驗收者做（`git merge --no-ff`）。
- 清單、紀錄、commit 訊息裡**不寫**真名、信箱、電腦名稱、帳號名、本機路徑（換成 `<home>`）、token、密碼。

## 4. [安裝流程與環境確認]

### 4.1 需要的東西

| 東西 | 版本 |
|---|---|
| git | 任何近期版本 |
| Python | **3.11 以上**（`pyproject.toml` 的 `requires-python`） |
| pytest | 7 以上（`pip install -e ".[dev]"` 會裝） |
| `zip`／`unzip` 或 Python 的 `zipfile` | H9 改包用（下面用 Python 寫，不需要額外工具） |

**不需要任何祕密**。雲端 session 的項目都不用 Telegram／Discord／模型的金鑰。（H11、H12 由擁有者在自己電腦用他自己設好的帳號做；交辦單不寫任何金鑰。）

### 4.2 取得程式

```sh
git clone <SYNOX 的 repo 網址（交辦時由擁有者給；也就是 docs/handoff/README.md「最短路徑」那一行）> synox-checks
cd synox-checks
git fetch origin
git switch -c docs/core-checks-<YYYYMMDD> origin/dev     # 你的工作分支；只在這裡 commit
git log --oneline -1                                       # 記下 commit；寫這份時是 fb29db0
python -m venv .venv
# Linux／macOS： .venv/bin/python -m pip install -e ".[dev]"
# Windows：     .venv\Scripts\python -m pip install -e ".[dev]"
python -c "import synox; print(synox.__file__)"           # 要在 synox-checks/src/synox/ 底下
```

之後指令裡的 `python` 都是這個 `.venv` 的 python。

### 4.3 先跑一次測試，記下基準

```sh
python -m pytest -q -p no:cacheprovider tests/test_pack_warnings.py
python -m pytest -q -p no:cacheprovider tests/test_theme_compat.py tests/test_theme.py
```

**參考基準**（來源：2026-11-19 在 `origin/dev`＝`fb29db0` 的暫時 worktree 實際跑出來；Windows 10 build 19045、Python 3.11.9、pytest 9.2.0）：

| 測試檔 | 結果 |
|---|---|
| `test_pack_warnings.py` | **41 passed**（0 failed） |
| `test_theme_compat.py`＋`test_theme.py` | **104 passed**（0 failed） |

- 以你自己跑出來的為準，寫進回報；跟上面不同（平台差異、有測試被略過）就寫出差在哪。
- 有 **failed** 就先停，照 §6.2 寫紀錄，不要往下做。
- `test_theme.py` 有用到前端時，沒有 node 的測試會自己略過，這不算失敗。

### 4.4 驗證用的 `config.json`（放在 `synox-checks/`；它與 `data/` 都在 `.gitignore` 裡）

```json
{"owner_id": 1, "data_dir": "data", "llm": {"kind": "none"}, "vault": {"mode": "file"}}
```

### 4.5 pack 警告用的假包（放在 repo **外面**，例如 `<home>/core-probe/`；只裝不叫）

```sh
python -m synox.sdk init <home>/core-probe/warnone --kind cli --name warnone --title "警告測試包"
python -m synox.sdk init <home>/core-probe/plainone --kind cli --name plainone --title "沒有警告的測試包"
```

1. **`warnone` v1**：在 `warnone/pack.json` 加
   `"warnings": [{"code": "vendor_no_security_guarantee", "text": "官方不保證安全", "advice": "建議在 docker 或 sandbox 執行"}]`，`version` 設 `0.1.0`。
   `python scripts/pack_zip.py <home>/core-probe/warnone --out <home>/core-dist` → `warnone-0.1.0.synoxpack`。
2. **`warnone` v2**（H7）：複製成 `warnone-v2/`，`version` 改 `0.2.0`，`warnings` 多一條
   `{"code": "sends_data_to_vendor", "text": "會把查詢送到作者的伺服器", "advice": "不要查私人資料"}`，打包 → `warnone-0.2.0.synoxpack`。
3. **`plainone`**（H8）：不加 `warnings`，打包。
4. **簽章被改的包**（H9）：

   ```sh
   python -m synox.sdk keygen --out <home>/core-keys/fake-test-key.pem --no-passphrase   # 假鑰匙，只給這次測試，放 repo 外
   python -m synox.sdk sign <home>/core-dist/warnone-0.1.0.synoxpack --key <home>/core-keys/fake-test-key.pem --out <home>/core-dist/warnone-signed.synoxpack
   python -m synox.sdk verify <home>/core-dist/warnone-signed.synoxpack        # 結束碼 0＝有簽章
   python - <<'EOF'
   import json, zipfile
   src, dst = "<home>/core-dist/warnone-signed.synoxpack", "<home>/core-dist/warnone-tampered.synoxpack"
   with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
       for item in zin.infolist():
           data = zin.read(item.filename)
           if item.filename == "pack.json":
               m = json.loads(data); m.pop("warnings", None); data = json.dumps(m, ensure_ascii=False).encode("utf-8")
           zout.writestr(item, data)
   EOF
   python -m synox.sdk verify <home>/core-dist/warnone-tampered.synoxpack      # 結束碼 2＝被改過
   ```

   （`<home>` 換成實際路徑；Windows 沒有 heredoc 時，把 Python 那段存成 repo 外的 `.py` 再跑。）

### 4.6 外觀用的假包（照 [theme-apply-checklist.md](../testing/theme-apply-checklist.md) 第二節）

```sh
cp -r tests/fixtures/theme_pack <home>/core-probe/test-old      # test-full、test-newer 各複製一份
```

| 包 | 改 `pack.json` |
|---|---|
| `test-old` | `name` 改 `test-old`；`theme.tokens.light`、`dark` 只留 `bg surface text muted line accent accent-ink accent2 soft ok warn bad` 這 12 個 |
| `test-full` | `name` 改 `test-full`；token 不改 |
| `test-newer` | `name` 改 `test-newer`；`tokens.light` 加 `"glow-x": "#ff00aa"`；`tokens.dark.soft` 改成 `"color-mix(in srgb, var(--future-tone) 20%, transparent)"`；`slots` 加 `"mascot.dance": "slots/idle.svg"` |

每個都 `python scripts/pack_zip.py <home>/core-probe/<名字> --out <home>/core-dist`。

### 4.7 開工前確認（全部是「是」才開始）

- [ ] 分支是 `docs/core-checks-<YYYYMMDD>`、基底是 `origin/dev` 最新（或擁有者指定的 commit）。
- [ ] `synox.__file__` 在 `synox-checks/` 底下。
- [ ] §4.3 的基準跑過、沒有 failed。
- [ ] `git status` 看不到 `config.json`、`data/`；假包、假鑰匙都在 repo 外面。

### 4.8 雲端項目的指令對照（照清單的步驟，換成終端機的寫法）

| 項目 | 指令 | 看什麼（以清單的「預期」為準） |
|---|---|---|
| H6 | `python -m synox install <home>/core-dist/warnone-0.1.0.synoxpack --yes` → 再加 `--accept-warning vendor_no_security_guarantee` | 第一次不裝、紅字列警告與要加的旗標；第二次裝好 |
| H7（終端機） | 裝好 v1 後 `python -m synox install <home>/core-dist/warnone-0.2.0.synoxpack --yes` → 再加 `--accept-warning sends_data_to_vendor` | 第一次只列新的那條、不升級；第二次升級；`data/packs.lock` 裡 `accepted_warnings` 兩個 code 都在 |
| H3（終端機） | 編輯 `data/packs.lock` 拿掉 `warnone` 的 `accepted_warnings` → `python -m synox packs status`、`python -m synox doctor --offline`、`python -m synox console` 打 `/help` | 寫「有警告還沒確認，先不開」；`/help` 看不到它。做完把鎖改回來（或重裝 v1） |
| H5（非互動） | 在另一個乾淨的 clone 裡 `python -m synox init --non-interactive --library <工具庫資料夾> --tools warnone`（`init` 沒有 `--yes`；工具庫資料夾要有 `.synoxpack`＋`index.json`，格式見 `python -m synox tools --help` 與 `docs/` 的工具庫說明） | 帶警告的工具沒裝，結果寫要加哪些 `--accept-warning`。做不出本機工具庫（`index.json` 不確定怎麼寫）就寫「略過：沒有本機工具庫」，整項留給擁有者本機——**不要**為了這項去下載真的工具庫 |
| H8（終端機） | `python -m synox install <home>/core-dist/plainone-0.1.0.synoxpack --yes`；`doctor --offline`；console `/help`；看 `data/packs.lock` | 沒有警告字；鎖裡這一筆**沒有** `accepted_warnings` 鍵 |
| H9（終端機） | `python -m synox install <home>/core-dist/warnone-tampered.synoxpack --yes --accept-warning vendor_no_security_guarantee` | 「⛔ 被改過」、沒裝（`data/packs/` 裡沒有新的） |
| H10 | 裝好 `warnone` 後，編輯 `data/packs/warnone/pack.json` 刪掉 `warnings` → `python -m synox doctor --offline`、`packs status` | 狀態 `tampered`、不載入、doctor 說明原因 |
| T3 | `python -m synox install <home>/core-dist/test-newer-1.0.0.synoxpack`（版本照範例包的 `1.0.0`）（不加 `--yes`）→ 再加 `--details` | 摘要＋要注意 3 項＋最後提示 `--details`；第二次多三段 |
| T4 | 三個都裝好後 `python -m synox packs theme-check test-old; echo $?`、`… test-newer --details; echo $?`、`… test-full --json` | 結束碼 0、10；JSON 有 `tokens.light`、`tokens.dark`、`slots`、`counts`、`issues`、`blocking: false` |

（`data/` 的實際位置以 `config.json` 的 `data_dir` 為準；H9、H10 之間如果互相影響，就刪掉 `data/` 重新來。）

## 5. [驗證清單集]

給高水準模型（驗收者）在 merge 前逐項確認。`<base>`＝`git merge-base origin/dev <branch>`，`<branch>`＝接手者的分支。
**每一項都要實際跑或實際看，列出沒過的項目與留下的問題；沒有全部通過就不准 merge。**

| # | 檢查什麼 | 指令／怎麼看 | 預期 |
|---|---|---|---|
| V1 | 分支名與基底 | `git log --oneline -1 <base>`；`git branch -r --contains <base>` | 分支叫 `docs/core-checks-<YYYYMMDD>`；基底在 `origin/dev` 上 |
| V2 | 只改了兩份清單 | `git diff --name-only <base> <branch>` | 只有 `docs/testing/pack-warnings-checklist.md`、`docs/testing/theme-apply-checklist.md` |
| V3 | 沒改步驟與預期 | `git diff <base> <branch> -- docs/testing/` 逐段看 | 只有「結果：」行、`模型：` 欄、驗收紀錄表被改；`步驟：`、`預期：` 一個字都沒動 |
| V4 | 雲端可做的都做了 | 看 H6、H10、T3、T4 的結果欄 | 四項都有 `通過` 或 `失敗（原因）`、日期、驗證者代號，並且打勾 `- [x]`（失敗的不打勾） |
| V5 | 部分項目寫法正確 | 看 H3、H5、H7、H8、H9 | 結果欄有「終端機那半…；網頁那半待擁有者本機」（H5 是「互動那半待擁有者本機」）；**沒有打勾** |
| V6 | 僅擁有者本機的沒被動到 | `git diff <base> <branch>` 裡找 H1、H2、H4、H11、H12、H13、T1、T2、T5～T12 | 這些項目沒有任何變動（除非 commit 明確由擁有者做；那要在回報裡寫） |
| V7 | H14 有結果或略過 | 看 H14 | `通過` 或「略過：沒有容器引擎」；略過不打勾 |
| V8 | 失敗都有紀錄 | 對照回報 | 每個「失敗」都有一份 §6.2 格式的紀錄（一件一檔） |
| V9 | 基準 | 看回報 | 兩行 passed／failed 數、0 failed；跟 41／104 不同的話有解釋 |
| V10 | 自動測試在驗收者這邊也全過 | 在 `<branch>`：`python -m pytest -q -p no:cacheprovider tests/test_pack_warnings.py tests/test_theme_compat.py tests/test_theme.py` | 0 failed；passed ≥ 145（41＋104；平台不同時以驗收者那台在 `<base>` 上先跑的數字為準） |
| V11 | T4 的結束碼真的對 | 驗收者自己照 §4.6 做 `test-old`、`test-newer`，跑 `python -m synox packs theme-check …; echo $?` | 0 與 10（跟接手者填的一致） |
| V12 | H6 真的會擋 | 驗收者照 §4.5 做 `warnone` v1，`python -m synox install … --yes`（不帶旗標） | 沒裝、輸出列出 `--accept-warning vendor_no_security_guarantee`（跟接手者填的一致） |
| V13 | 給擁有者的步驟可以照做 | 讀回報的「給擁有者本機做的步驟」 | 列出每一個「僅擁有者本機」與「部分」的項目、順序、用哪個包、怎麼開／關 SYNOX（只綁 127.0.0.1、測完關掉）；沒有要擁有者回頭問的地方 |
| V14 | 沒有私人資訊 | 下面的指令 A | 沒有輸出 |
| V15 | 沒有密鑰（含假鑰匙沒被 commit） | 下面的指令 B；`git diff --name-only <base> <branch> \| grep -Ei "\.pem$\|key"` | 都沒有輸出 |
| V16 | 公開前檢查腳本 | `python scripts/prepublish_check.py --worktree-only`（沒有私人詞清單時加 `--allow-no-terms`） | 沒有新的問題（跟 `<base>` 上跑的結果相比） |
| V17 | 沒有 TODO／半成品 | 下面的指令 C | 沒有輸出（「待擁有者本機」是刻意的寫法，不算） |
| V18 | 沒有用第三方 pack | 回報與 diff | 沒有裝過 `web-ddgs` 或任何工具庫的 pack；只有 §4.5、§4.6 的假包 |
| V19 | 收尾 | 回報的「收拾」一段 | 沒開過網頁就寫「沒開」；開過就有 pid、埠與「已放掉」的確認輸出；假包、假鑰匙、`data/`、`config.json` 已刪 |
| V20 | commit 訊息 | `git log <base>..<branch>` | 每個 commit 寫做了什麼、為什麼；agent 做的有共同作者行 |

V14、V15、V17 的指令（bash；Windows 用 Git Bash）：

```sh
# A：私人資訊（本機路徑、家目錄、信箱、常見的電腦名稱開頭）
{ git diff <base> <branch>; git log <base>..<branch> --format=%B; } \
  | grep -nEi 'C:\\Users\\|/home/[a-z]|/Users/[a-z]|[a-z0-9._-]+@[a-z0-9-]+\.(com|net|org|tw|io)|DESKTOP-|LAPTOP-'
# B：密鑰
git diff <base> <branch> | grep -nEi 'token\s*[:=]|api[_-]?key\s*[:=]|ghp_|sk-[A-Za-z0-9]{10}|BEGIN [A-Z ]*PRIVATE KEY|AGE-SECRET-KEY'
# C：TODO／沒填完（雲端可做的項目不應該還是空的）
git diff <base> <branch> | grep -nE '^\+.*(TODO|FIXME|XXX|待補)'
```

（`noreply@anthropic.com` 這種共同作者行不算私人資訊，A 搜到可以忽略。）

驗收者回報：「V1～V20 逐項：通過／不通過（原因）」＋「留下的問題」。**有任何一項不通過就不 merge**，把不通過的寫回這份交辦單的 [狀態]。
全部通過才 `git merge --no-ff <branch>` 進 `dev`，merge commit 訊息寫「兩份核心真機清單的雲端那一半：幾項通過、幾項失敗、還剩哪些待擁有者本機」。
**這次 merge 不代表兩個功能驗收完成**：要等擁有者本機把剩下的項目做完、兩份清單全部打勾。

## 6. [交回]

### 6.1 回報內容（一則訊息，結論先講）

1. 結論一句話：雲端項目全部通過／有 N 項失敗；還剩幾項待擁有者本機。
2. 分支名、最新 commit、基底 commit。
3. 環境：作業系統與版本、Python、pytest（不寫電腦名稱、帳號名、路徑）。
4. 基準：§4.3 兩行的 passed／failed 數。
5. 逐項結果表：H1–H14、T1–T12 每項一行（通過／失敗／部分／略過／待擁有者本機）。
6. 每份失敗紀錄的全文（§6.2）。
7. **給擁有者本機做的步驟**：要做的項目清單（依建議順序：T1、T2 → T5～T11 → T12；H1、H2、H4 → H3、H7、H8、H9 的網頁那半 → H5 互動那半 → H13 → H11、H12）、
   用哪個包、怎麼開 SYNOX（只綁 127.0.0.1）與關掉、哪幾項要拿上一版比對（H8、T11）。
8. 「收拾」一段：開過什麼程序與埠（沒有就寫沒有）、刪了哪些檔。
9. §5 的 V2～V9、V13～V20 自查結果。
10. 不確定的地方、要擁有者決定的事（照「一件一檔」題目檔的格式寫在回報裡）。

### 6.2 失敗紀錄的格式（一件一檔）

在 `synox-checks/_inbox/` 寫（不要 commit；雲端做的就把全文貼進回報）。檔名 `YYYYMMDD-HHMMSS-<簡短英文代號>.md`：

```markdown
# <一句話標題>

狀態：待處理
清單項目：H6
環境：<作業系統與版本、Python>
SYNOX commit：<git log --oneline -1>

## 問題一句話
## 脈絡
- 做了什麼（完整指令）
- 預期
- 實際（原樣貼輸出；路徑換成 <home>）
- 我判斷代表什麼
## 選項
| 選項 | 一句話 | 建議 |
|---|---|---|
| A | … | ✅ 建議（預設做這個） |
## 驗收
## 不要做的事
```

### 6.3 收尾流程

1. 接手者：只 commit 在 `docs/core-checks-<YYYYMMDD>`；**不合併、不推送**（擁有者要你推那一條分支給驗收者拿時才推，推之前照 V14、V15 自己掃一次）。
2. 收拾：關掉自己開的 SYNOX／console（有開的話）並確認埠已放掉；刪掉 `<home>/core-probe/`、`<home>/core-dist/`、`<home>/core-keys/`、`data/`、`config.json`。
3. 驗收者：照 §5 逐項確認 → 全過才 `git merge --no-ff` 進 `dev` → 把這份的 [狀態] 改成「雲端那半已完成：merge commit `<hash>`；剩下待擁有者本機：<項目>」。
4. 擁有者本機做完剩下的項目、兩份清單全部打勾後，[狀態] 改成「已完成」。
