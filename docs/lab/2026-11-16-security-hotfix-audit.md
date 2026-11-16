# 2026-11-16 安全修補：安裝／載入／畫面信任面的稽核

- 分支 `security-hotfix`（基準 `dev` = `dd873e2`）；設計：[ADR 0028](../adr/0028-pack-signatures-official-badge.md)。
- 起因：擁有者得知兩個漏洞（手放進 `packs/` 的工具不經安裝頁就載入；第三方面板跟主控台同源），要求一次修好、順便把整個「裝進來／載入／畫面上誰能騙誰」的面都看過。
- 範圖：任何不經擁有者確認就能裝或載入 pack 的路（API、CSRF、暫存 token、zip 路徑、報告與安裝之間的空檔、升級、工具庫下載、檔案關聯／拖放、命令列）；
  任何能讓確認畫面誤導人的路（報告偽裝、Unicode 相似字、確認疲勞）；面板／工具畫面逃出去的路；新簽章機制自己的攻擊面。
- 行號是基準 `dd873e2` 的。嚴重度：critical＝不經確認就能跑別人的程式／奪走主控台；high＝能讓官方／非官方分不清、或繞過安裝頁的一環；medium＝要配合別的條件；low＝資訊或已有邊界。
- 稽核者沒有瀏覽器、不開埠：全部是讀程式＋跑測試得出的，**沒有任何畫面在真的瀏覽器裡看過**（最後一節）。

## 一、發現清單

| # | 嚴重度 | 在哪（`dd873e2`） | 失敗情境 | 修了？ |
|---|---|---|---|---|
| F1 | **critical** | `src/synox/packs/loader.py:974–987`（`load_all`）、`:410–419`（`unlocked_scan`） | 任何能寫 `packs/` 的程式（瀏覽器下載、同步軟體、USB、另一個工具）放一個資料夾進去，重開 SYNOX 就載入：個人版連第 2 關都不跑，kind=python 的 `pack.py` 在 SYNOX 程序裡用你的帳號權限執行。`packs.dirs` 一樣 | **是**：沒有 `packs.lock` 那一筆＝`unapproved`、不載入、通知一次、設定頁「送去安裝頁檢查」（`packs/adopt.py`）；`unlocked_scan` 拿掉。`97f005f`、`24b4807`、`d62ad2c`（合併 `c449d90`） |
| F2 | **critical** | `src/synox/web/static/tools.js:373–378`（`sandbox="allow-scripts allow-same-origin"`）、`src/synox/web/server.py:624–633`（`panel`） | 面板的 JS 跟主控台同源：`fetch("/api/me")` 拿 CSRF、`fetch("/api/packs/install", …)` 替你按確認、改主頁 DOM 假造報告、按任何按鈕、聽 `synox:install-step`、叫 `window.SynoxInstall`。一個「有面板」的 T1 pack 就夠，掃描看不到 HTML | **是**：`sandbox="allow-scripts"`＋回應 CSP `sandbox allow-scripts`＋每個登入一張票（`/packs/<name>/panel/<票>/`、`…/api/<route>` 只認票、`Access-Control-Allow-Origin: null`）；舊網址 404；面板上方 SYNOX 畫的風險說明。官方的也隔。`7f5dcce`、`cd0ab85`、`89346cf`（合併 `91b981f`） |
| F3 | **high** | `src/synox/packs/catalog.py:316–327`（只對大小與 sha256）、`admin.py` 沒有任何來源判斷 | 官方工具庫的檔跟任何人做的 `.synoxpack` 在報告上長得一模一樣；工具庫目錄被換（GitHub 帳號、轉址）或任何人把檔名取成官方的名字，使用者分不出來。`publisher` 只是字串 | **是**：`pack.sig.json`＋Ed25519（`packs/signing.py`）、四種標章（✅ 官方／✍️ 作者簽章／⚠️ 不是官方／⛔ 被改過＝拒）、寫進鎖、工具頁／設定頁／doctor 顯示；SDK `keygen／sign／verify`。`cf73633`、`58fc53b`、`e211bda`（合併 `067320f`）。**公鑰還是空的**：擁有者在家產生後貼進 `OFFICIAL_PACK_PUBLIC_KEYS` 才會有「官方」 |
| F4 | **high** | `src/synox/web/static/app.html:2467`（`showReview` 第一行就是 `s.title`）、`manifest.py:1210`（title 只檢查非空） | 工具把 `title` 寫成「✅ 官方 記帳（SYNOX）」、`publisher` 寫「SYNOX 官方」、SKILL.md description 寫「SYNOX 官方工具」：報告最上面就是這行字，使用者以為是官方。`textContent` 擋得了 HTML，擋不了「字本身在騙人」 | **是**：報告第一列改成 SYNOX 畫的標章（只看伺服器驗出來的結果），工具的字在它下面；非官方的名字／標題／說明／publisher／SKILL.md description／web.app.title 含「官方」「official」「SYNOX」「✅」（NFKC、去零寬、不分大小寫）→ 紅字。`cf73633`、`89346cf`。**不拒裝**（ADR 0028 §9 第 1 點，待擁有者確認） |
| F5 | **medium** | `src/synox/packs/manifest.py:1210`（strict 也只查 title／summary／publisher 是不是非空字串） | `title` 可以放 U+202E（從右到左覆寫）、零寬字元：報告上「yp.kcap」顯示成別的、「官​方」躲過字串比對；稽核時實測 `read(strict=True)` 接受 `"‮官方 ✅ SYNOX"` | **是**：安裝時（strict）`title`／`summary`／`publisher` 不能有雙向控制、零寬、BOM、換行、控制字元；載入時（非 strict）照舊，舊工具不受影響。`cf73633` |
| F6 | **medium** | `src/synox/packs/admin.py:105–134`（`_members`／`_strip_root`） | zip 同一個路徑兩個項目（第二個蓋掉第一個），或 `a.py` 與 `A.py`（Windows 只留一個）。報告與鎖算的是磁碟上那一份，所以「看到的＝裝的」成立，但簽章清單的對應、`_strip_root` 的判斷都會混；對作者端 `sign_zip` 更要緊 | **是**：兩種都拒（白話訊息）。`cf73633` |
| F7 | **medium** | `src/synox/packs/admin.py:118–120`（`total += info.file_size`，只信宣告）、`:408`（`copyfileobj`） | 壓縮炸彈：宣告 1 KB、實際解出幾 GB；`MAX_UNZIPPED` 只加宣告值，`copyfileobj` 寫到磁碟滿才在 CRC 失敗。上傳 5 MB 上限、擁有者才能上傳，所以是「擁有者自己上傳才會被塞滿磁碟」 | **是**：`_copy_member` 一邊解一邊數，比宣告的大或總量超過 20 MB 就停。`cf73633` |
| F8 | **medium** | `src/synox/packs/admin.py:710–748`（`approve_installed`，`packs lock --approve`） | 開發者命令列：跑 1、2 關、印報告就寫鎖，沒有「看完再按一次」。它是擁有者在這台電腦上明確下的命令，不是遠端或程式能觸發的 | **部分**：保留為 `packs.dirs` 的開發者路徑（F1 修好後它是唯一讓 `packs.dirs` 載入的方法）；現在也會驗簽章（⛔ 時拒）、寫 `signature`。**待擁有者確認**是否要再加 `--yes`（ADR 0028 §9 第 2 點） |
| F9 | **medium**（界線） | `data/packs.lock`、`src/synox/`、`.venv` | 能寫 SYNOX 檔案的攻擊者改 `packs.lock` 把雜湊換掉、把 `signature.status` 寫成 official、或直接改 `loader.py`。SYNOX 守不了 | **不修（寫明）**：`docs/security.md`「沒有做的保護」、ADR 0028 §7。簽章與鎖守的是「檔案是不是從你按過確認的那份變來的」 |
| F10 | **medium** | `src/synox/packs/catalog.py`（`index.json` 沒簽） | 目錄被換：可以把官方的檔換成任何人的檔（F3 修好後顯示「⚠️ 不是官方」，看得到）、或指向舊版（升級規則擋、要明確勾降級）。做不到讓非官方的顯示成官方 | **不修，列為下一步**：ADR 0028 §6（目錄簽章＋撤銷清單是一個完整的小設計：序號、新鮮度、撤銷格式；用同一套零件） |
| F11 | **low** | `src/synox/sdk/__init__.py:377–420`（`init_pack` 一定寫 `panel.html`＋`web.panel`） | 每個用範本做的工具都有面板→每個都踩到 F2 | **是**：預設不產生，`--panel` 才有（新範本用相對網址）。`58fc53b` |
| F12 | **low** | `scripts/release.py:533–548`（`keygen` 沒設環境變數就寫**不加密**的 PEM） | 擁有者在家 keygen 忘了設 `SYNOX_RELEASE_KEY_PASSWORD`，私鑰明文落地 | **是**：終端機上沒設就問兩次密語（非終端機照舊）；`synox-sdk keygen` 一致（空密語要 `--no-passphrase`）。`58fc53b` |
| F13 | **low** | `src/synox/web/server.py:1724–1743`（`pack_upload`）、`:1864–1885`（`pack_install`）、`:452–457`（`/api/` 的 `sec-fetch-site`＋CSRF） | 遠端觸發安裝：`/api/` 非 GET 要 `X-SYNOX-CSRF`＋`Origin`＝`Host`、拒 `same-site`／`cross-site`；上傳與安裝只有擁有者；暫存 token 128 bit、只在擁有者的頁面與 `?pack=` 網址出現（`history.replaceState` 拿掉、Referrer-Policy no-referrer） | 沒有問題；F2 修好後同源的第三方腳本也不存在了 |
| F14 | **low** | `src/synox/packs/admin.py:664–707`（`install_staged`：再跑 1、2 關、雜湊要等於看報告時的、再 `shutil.move`） | 報告與安裝之間的 TOCTOU：雜湊比完到 `move` 之間換檔，需要能寫 `data/web_uploads/`＝F9 的界線。`_install_python` 載入時再對一次來源雜湊 | 沒有問題（界線寫在 F9） |
| F15 | **low** | `Install-Pack.bat`、`src/synox/__main__.py:515–588`（`cmd_install`）、`static/packdrop.js` | 點兩下、拖到 bat、拖進網頁：都只到 `stage`→開報告，確認還是在網頁或 `--yes`。`packdrop` 只把檔交給原本的上傳鈕 | 沒有問題 |
| F16 | **low** | `src/synox/web/server.py:1828–1862`（`library_install`） | 工具庫下載：名字／版本／是不是外觀包跟目錄不一樣就丟掉暫存；大小與 sha256 對目錄；轉址只跟 GitHub | 沒有問題（目錄本身見 F10） |
| F17 | **low** | `app.html:3061–3066`（「全部更新」佇列） | 確認疲勞：一個一個給報告、每個都要按確認；T2 仍要輸入 publisher | 沒有問題；每份報告現在多一段安全提醒（不會因為是第 N 個就少） |
| F18 | **low** | `src/synox/web/apps/`（工具服務 `127.0.0.2`） | 工具畫面能不能框住主控台、postMessage、opener：主控台 `frame-ancestors 'none'`、`X-Frame-Options: DENY`、COOP `same-origin`；`app.html`／`static/*.js` 沒有任何 `message` 事件監聽 | 沒有問題 |
| F19 | **low** | `loader.py:375–385`（`BUNDLED`、`is_bundled`） | 假冒出廠：`BUNDLED` 是空的→永遠 False；加名字就是開門 | 沒有問題；loader 註解加「不要再把名字加回 BUNDLED」；`tests/test_unapproved.py` 斷言 `BUNDLED == ()` |
| F20 | **low** | `src/synox/packs/upgrade.py:581`（`rollback`） | 退回到 `_removed/` 裡一份當時就沒鎖的（或檔案對不上鎖），退回之後沒有鎖＝現在不載入（以前照舊載入）。只影響「手放→升級→退回」這種少見的順序 | **沒修**：`rollback` 已經回 `lock: unlocked／mismatch` 並叫使用者重新核准；現在那一步變成必要。建議（下一步）：rollback 之後直接開 adopt 的報告 |
| F21 | **low**（新機制） | `src/synox/packs/signing.py`（新） | 簽章自己的攻擊面：欄位多一個、`key_id` 跟公鑰不符、`version` 不是 1、base64 長度不對、`files` 不是精確相等、簽章檔是連結、大於 1 MB → 一律 `invalid`（拒）。降級用簽過的舊版→升級規則；私鑰外流→換鑰匙（兩把並存）。測試 `tests/test_pack_signing.py`（含改一個位元組、多／少一個檔、改清單、換鑰匙） | 已涵蓋；界線寫在 ADR 0028 §1.2、§7 |

另外（不是漏洞）：`tests/test_web_report.py::test_owner_summary_has_versions_kinds_packs_and_redacted_errors` 在這台機器基準就會失敗（擁有者 id `100` 出現在 Windows 版號 `26100` 裡），跟本次無關；三個代理的最後一次全套都過了，主線的全套只剩它。

## 二、修法摘要（對應 ADR 0028）

| 區塊 | 檔 | 測試 |
|---|---|---|
| 簽章與標章（S1–S8） | `packs/signing.py`（新）、`admin.py`、`lock.py`、`upgrade.py`、`manifest.py`、`sdk/__init__.py`、`scripts/release.py`、`docs/sdk.md`、`sdk/README.md` | `tests/test_pack_signing.py`（none／author／official／invalid、竄改、dup／case、炸彈、鎖、升級紅字、look-alike、bidi）、`tests/test_sdk_sign.py`（keygen／sign／verify 來回、`--panel`、repo 裡沒有私鑰） |
| 沒經過安裝頁的不載入（S9） | `packs/loader.py`、`packs/adopt.py`（新）、`doctor.py`、`__main__.py`、`docs/install-packs.md`、`tests/conftest.py`（`lock_all`、`make_bot(lock_packs=)`） | `tests/test_unapproved.py`（個人／伺服器、通知一次、packs.dirs、BUNDLED 空、adopt stage／install／競態／連結、`packs lock --approve`、doctor）、`test_perm8.py` 重寫 |
| 面板隔開（S10） | `web/server.py`、`web/paneltickets.py`（新）、`web/tokens.py`、`static/tools.js`、`static/tools.css`、`static/app.html`、`docs/ui/preview.html`、`docs/pack-format.md`（`web.panel`） | `tests/test_panel_isolation.py`（票要 CSRF、壞票 404、CSP `sandbox`、無 cookie＋`Origin: null` 能讀、票打不到 `/api/`、`/api/tools`／`/api/settings` 帶 `signature`、adopt 路由） |

## 三、沒修的、為什麼

- F8 `packs lock --approve` 不加第二次確認：它是擁有者在本機下的命令、已經印完整報告；加 `--yes` 只是形式。等擁有者決定。
- F9 本機寫入權：不是程式能守的線；寫進文件。
- F10 目錄簽章與撤銷：下一步（ADR 0028 §6）。
- F20 rollback 之後沒鎖：訊息已經說要重新核准；「退回就自動開 adopt 報告」留給下一輪。
- 名字像官方的只標紅不拒（F4）：官方工具庫自己的工具在公鑰貼進去之前也是「不是官方」，拒了會連官方的都擋掉；標章不看名字，紅字夠醒目。擁有者可以改成拒（把 `signing.lookalike_problems` 的結果接進 `run_gates` 的 problems）。

## 四、沒有驗證的（請擁有者在自己的電腦做；ADR 0028 §10）

- **真的瀏覽器裡的面板**：`sandbox="allow-scripts"` 的 iframe 裡 `fetch("api/summary")` 讀不讀得到（CSP `connect-src 'self'` 對 opaque origin 的文件怎麼算；`Access-Control-Allow-Origin: null` 瀏覽器收不收）；面板裡 `fetch("/api/me")` 是不是 401／403；iframe 的高度與捲動；風險說明那一行跟標章的樣子。
- **安裝報告的樣子**：標章 chip、紅字、安全提醒的位置；「⛔ 被改過」沒有確認鈕；「送去安裝頁檢查」的按鈕與流程（原地那份收到 `_removed`）。
- **啟動時的通知**（Telegram／Discord）：手放一個資料夾進 `packs/` 重開 SYNOX。
- `synox-sdk keygen` 在真的主控台問密語（測試只走環境變數）；`release.py keygen` 的提問同理。
- 所有 Windows 檔案系統上的行為只在這台開發機跑過測試（junction 的拒收有真的跑；symlink 在這台做不出來，測試退到 monkeypatch）。
- 工具庫（SYNOX_Libs）的工具重新打包、簽章、上架：這一輪沒碰那個 repo。工具庫現在發的檔都會顯示「⚠️ 不是官方」，直到擁有者簽過、貼公鑰、兩邊都發新版。

## 五、代理與合併

| 分支 | 代理 | 內容 | 合併 |
|---|---|---|---|
| `sec/sign` | A | 簽章、標章、zip 三條檢查、manifest 看不見字元、SDK `keygen／sign／verify`、`init --panel`、`release.py keygen` 密語 | `067320f` |
| `sec/panel` | B | 面板票與隔離、報告第一列標章、adopt 路由與按鈕、技能卡改字、UI 預覽 | `91b981f` |
| `sec/loader` | C | `unapproved`、`adopt.py`、doctor／`packs status`、conftest `lock_all`、`test_unapproved.py` | `c449d90` |

主 session（稽核者）：ADR `93b34ee`、文件與字句 `9fa35a8`、本文件。三個臨時分支與工作樹合併後刪除。
