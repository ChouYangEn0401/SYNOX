# ADR 0028：工具的簽章與「官方」標章——誰做的、有沒有被改過，由 SYNOX 自己驗、自己畫

- 日期：2026-11-16
- 狀態：**已採用**（擁有者 2026-11-16 的決定：ADR 0022 修正 O1「所有來源一律可以安裝、一律顯示安全提醒；官方工具以擁有者簽章辨識」，
  加上同日對兩個漏洞的指示——「沒有經過安裝頁的工具不載入」、「第三方面板要隔開（選項 B）」）。
  凡是標 **「實作時決定，待擁有者確認」** 的，是這一輪實作時自己定的，擁有者看過不同意可以改；其他照擁有者的話。
- 基準：分支 `dev`，commit `dd873e2`；程式在分支 `security-hotfix`。稽核紀錄：[lab/2026-11-16-security-hotfix-audit.md](../lab/2026-11-16-security-hotfix-audit.md)。
- 前提：[ADR 0022](0022-ecosystem-bridge-and-sandbox.md)（R1「只有一個入口」、決定 23、26、27、修正 O1、第 13–14 節）、
  [ADR 0023](0023-updates-and-hotfixes.md) §7（SYNOX 發佈的簽章；本文沿用它的零件）、[ADR 0024](0024-tool-apps-services.md)（第三方畫面怎麼隔開）。
- 平台現實：開發機不開埠、不開瀏覽器。iframe 隔離、CSP `sandbox`、`Access-Control-Allow-Origin: null` 在**真的瀏覽器裡的行為沒有看過**，
  標「待實測」的要擁有者在自己的電腦上開一次網頁確認（本文最後一節列了怎麼看）。

> **給使用者的一句話**：以後裝工具的時候，報告最上面會有一個 SYNOX 自己畫的標章——✅ 官方、✍️ 作者簽章、⚠️ 不是官方、⛔ 被改過——
> 這個標章只看簽章驗出來的結果，工具自己寫什麼名字、什麼說明都影響不了它。不管哪一種，裝之前都會先看報告、你按確認才裝。

## 0. 這份 ADR 決定什麼（一行一題）

| # | 題目 | 決定 |
|---|---|---|
| S1 | 簽什麼 | **每個 `.synoxpack` 自己帶簽章**：zip 裡多一個 `pack.sig.json`，列出其他每個檔的路徑＋sha256，再用 Ed25519 簽這份清單。少一個檔、多一個檔、改一個位元組都驗不過 |
| S2 | 用哪種鑰匙、幾把 | Ed25519（沿用 `src/synox/update/signing.py` 的零件）。**兩組鑰匙分開**：發 SYNOX 本體的（`update/signing.py` 的 `RELEASE_PUBLIC_KEYS`，已有）、簽官方工具的（新的 `src/synox/packs/signing.py` 的 `OFFICIAL_PACK_PUBLIC_KEYS`）。每組可以同時放現用＋備用兩把（換鑰匙時並存） |
| S3 | 私鑰在哪 | **只在擁有者手上、在家離線產生**；不進 repo、不進 SYNOX、不進測試、不經任何代理。測試一律在測試裡現產拋棄式鑰匙 |
| S4 | 誰可以簽 | **任何人**都能簽自己的工具（SDK 給 `keygen`／`sign`／`verify`）。只有鑰匙在 `OFFICIAL_PACK_PUBLIC_KEYS` 裡的才叫「官方」；其他有效簽章叫「作者簽章」，一樣不是官方 |
| S5 | 報告上顯示什麼 | 四選一：**✅ 官方**（官方鑰匙驗過）／**✍️ 作者簽章**（別把鑰匙驗過；升級時鑰匙要跟第一次裝的一樣，不一樣就紅字）／**⚠️ 不是官方**（沒有簽章：可以裝，提醒更強）／**⛔ 被改過**（有簽章但驗不過：**拒裝**，沒有任何覆寫方式） |
| S6 | 標章誰畫 | **只有 SYNOX 從伺服器驗出來的結果畫**。工具自己能控制的字（name、title、summary、description、SKILL.md、面板、工具畫面）一律不能讓東西看起來像官方；名字／標題／說明裡出現「官方」「official」「SYNOX」「✅」而它不是官方 → 報告紅字標出來（**實作時決定，待擁有者確認**：標紅、不拒裝，理由在 §4.3） |
| S7 | 裝好之後 | 簽章結果寫進 `data/packs.lock` 那一筆（`signature`：status、key_id、public_key）；之後靠既有的逐檔雜湊鎖守著，不重驗簽章 |
| S8 | 目錄（工具庫的 `index.json`）要不要一起簽 | **這一輪不簽，列為下一步**（ADR 0022 決定 26／27 的目錄簽章與撤銷清單）。理由在 §6 |
| S9 | 沒有經過安裝頁的工具 | **不載入**（漏洞一）。手放進 `packs/`、`packs.dirs` 指過去、沒有 `packs.lock` 那一筆的 → 狀態「沒有經過安裝頁」，擁有者看到白話提示，一鍵送進正常的安裝流程 |
| S10 | 第三方面板（`web.panel`） | **一律隔開**（漏洞二，擁有者選 B）：官方的也隔，不特殊處理。隔法在 §5。SDK 範本不再預設產生面板（ADR 0022 決定 23） |

## 1. 簽章檔 `pack.sig.json`

放在 pack 最上層，跟 `pack.json` 並排。內容（JSON，UTF-8，`ensure_ascii`）：

```json
{
  "version": 1,
  "algorithm": "ed25519",
  "key_id": "3f9a1c0e7b2d4a66",
  "public_key": "<32 位元組公鑰的 base64，44 字>",
  "files": {
    "pack.json": "<sha256 十六進位 64 字>",
    "pack.py": "…",
    "SKILL.md": "…"
  },
  "signature": "<64 位元組 Ed25519 簽章的 base64>"
}
```

- **簽的位元組**＝`{"algorithm","files","key_id","public_key","version"}` 這五個欄位（不含 `signature`）用
  `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` 編成 UTF-8。排序固定、沒有空白、全 ASCII，所以不同機器算出來一樣。
- `files`：zip 裡（去掉唯一的最上層資料夾之後）**除了 `pack.sig.json` 本身、`__pycache__/` 底下的檔**以外的**每一個檔**，路徑用 `/` 接、跟 `admin._safe_parts` 的結果一樣。
  `__pycache__` 不算：SYNOX 安裝時本來就不解出來（P7），作者打包時也不該放。
- `key_id`＝`sha256(32 位元組原始公鑰)` 十六進位的前 16 字。只是給人、給鎖認鑰匙用的名字；驗章用 `public_key`。
- `public_key` 放在檔裡：第三方作者的鑰匙 SYNOX 不認識，要靠它驗；官方的也放（驗完再比對是不是官方鑰匙）。
- `pack.json` 的 `integrity.sha256`（`synox-sdk zip` 寫的）照舊；`pack.sig.json` 不列在 `integrity` 裡（`lock.check_integrity` 跳過它），
  所以**先 zip、再 sign**：簽章涵蓋已經寫好 `integrity` 的 `pack.json`。

### 1.1 驗章（`packs/signing.py`，在 `admin.stage` 解完壓縮、跑第 1 關之前）

1. zip 先過既有的檢查（`_members`／`_strip_root`：絕對路徑、`..`、連結、Windows 保留名、看不見的字元…），**另外新加**：同一個路徑出現兩次、或兩個路徑只差大小寫（Windows 會蓋掉其中一個）→ 拒（這兩條不只為簽章，是「報告看到的就是裝進去的」的前提）。
2. 解到暫存資料夾之後，對**磁碟上**的檔算 sha256（不是對 zip 的項目算）：這樣驗的就是待會真的會裝進去、第 2 關掃的那一份。
3. 沒有 `pack.sig.json` → `status = "none"`。
4. 有：解析（格式不對、`version` 不是 1、`algorithm` 不是 ed25519、base64 不對、長度不對 → 一律 `invalid`）；`files` 跟磁碟上的清單**完全一樣**（多、少、改都不行）；
   用檔裡的 `public_key` 驗 `signature`；過了 → 這把鑰匙在 `OFFICIAL_PACK_PUBLIC_KEYS` 裡 ＝ `official`，不在 ＝ `author`；任何一步不過 ＝ `invalid`。
5. `invalid` → `GateRefused`（跟第 1、2 關沒過一樣：暫存清掉、報告給看、**沒有確認鈕**）。字：「⛔ 被改過：這個工具有簽章，但檔案跟簽章對不上——簽章之後有人改過它，或是檔案在傳輸中壞掉。不能裝。請重新下載一次，或向給你這個檔的人要一份新的。」
6. `official`／`author`／`none` 繼續第 1、2 關；結果放進摘要的 `signature` 區塊（§3）。

### 1.2 想過的攻擊

| 攻擊 | 怎麼擋 |
|---|---|
| 改任何一個檔 | sha256 清單對不上 → ⛔ |
| 多放一個檔（例如 `sitecustomize.py`）、少一個檔 | 清單要**完全一樣** → ⛔ |
| 改 `pack.sig.json` 的清單再自己簽 | 鑰匙變了：官方的變成不是官方（標章變）；作者的升級時鑰匙對不上 → 紅字 |
| 把簽章檔拿掉 | 變成「⚠️ 不是官方」——可以裝，但報告上明白寫沒有簽章；升級時「以前有簽章、這一版沒有」紅字 |
| zip 裡同一個路徑兩個項目（一個給人看、一個真的解出來） | 現在拒收；而且雜湊一律對磁碟上解出來的那一份算 |
| `a.py` 與 `A.py`（Windows 只留一個） | 拒收 |
| 路徑寫法不同（`\`、`./`、尾巴空白、雙向控制字元） | 正規化照 `_safe_parts`；看不見的字元本來就拒 |
| 把舊的、簽過的版本拿來蓋新的（降級） | 簽章擋不了（舊版本來就是真的）。靠既有的升級規則：版本要比裝著的新，否則要明確勾「降級／重裝」（`upgrade.py`）；報告會寫「這是降級」 |
| 用「官方」「SYNOX」「✅」取名字騙人 | 標章只看簽章；非官方的名字裡有這些字 → 紅字（§4.3） |
| 偷到擁有者的私鑰 | 換鑰匙：發一版把那把公鑰拿掉、加新的（兩把並存就是為了這個）；照 SECURITY.md 發公告。這份 ADR 擋不了私鑰外流，只能讓事後處理有路 |
| 改 `data/packs.lock` 把 `signature.status` 寫成 official | 這是本機檔案。能改它的人也能改 SYNOX 自己的程式——**這條界線這份 ADR 不假裝守得住**（§7 誠實清單） |

## 2. 鑰匙

| 用途 | 公鑰常數（寫在 SYNOX 裡） | 誰產生 | 檔名建議 |
|---|---|---|---|
| 發 SYNOX 本體（ZIP／安裝程式；`Update.bat` 驗） | `src/synox/update/signing.py` 的 `RELEASE_PUBLIC_KEYS`（已有，現在是空的） | 擁有者，`python scripts/release.py keygen --out <repo 以外>/synox-release.pem` | `synox-release.pem` |
| 簽官方工具（`.synoxpack`） | `src/synox/packs/signing.py` 的 `OFFICIAL_PACK_PUBLIC_KEYS`（新，現在是空的） | 擁有者，`synox-sdk keygen --out <repo 以外>/synox-packs.pem` | `synox-packs.pem` |
| 第三方作者簽自己的工具 | 不寫進 SYNOX（簽章檔自帶公鑰） | 作者，`synox-sdk keygen --out <任何地方>/my-pack-key.pem` | 自己取 |

- 兩個常數都是 `Sequence[str]`，每一項是 32 位元組原始公鑰的 base64（44 字，結尾 `=`）；可以放兩把（現用＋備用）。寫壞的那一項不算（跟 `update/signing.public_keys` 同一個規則）。
- 私鑰檔：PEM（PKCS8），**用密語加密**（`keygen` 會問兩次；`release.py keygen` 原本只看環境變數 `SYNOX_RELEASE_KEY_PASSWORD`，這一輪改成沒設就問，兩邊一致）。
  `sign` 讀私鑰時問密語（或環境變數 `SYNOX_PACK_KEY_PASSWORD`／`SYNOX_RELEASE_KEY_PASSWORD`）。放在 repo 資料夾裡的私鑰檔一律拒用（沿用 `release.py` 的 `_inside` 檢查）。
- **公鑰怎麼進 SYNOX**：擁有者把 `keygen` 印出的那一行貼進對應的常數，隨下一版發出去。在那之前所有工具（包括官方工具庫下載的）都會顯示「⚠️ 不是官方」——報告上會寫明「這一版 SYNOX 還沒有官方鑰匙」。
- 測試：`tests/` 用 `Ed25519PrivateKey.generate()` 現產鑰匙，再 `monkeypatch.setattr(signing, "OFFICIAL_PACK_PUBLIC_KEYS", (...))` 當官方；**沒有**任何環境變數能在正式路徑加鑰匙（跟 `update/signing.py` 的 `SYNOX_UPDATE_TEST_PUBKEY` 不同，那一條只給更新測試）。

## 3. 安裝報告與 `packs.lock`

`admin.summary_of` 多兩塊；終端機的 `format_summary` 與網頁的報告都照它畫：

```json
"signature": {"status": "official|author|none", "label": "✅ 官方", "key_id": "…", "public_key": "…",
              "text": "SYNOX 驗過擁有者的簽章：這個檔是官方發的，而且沒有被改過。",
              "lookalike": ["title 裡有「官方」"], "no_official_keys": false},
"safety_notice": "安全提醒：公開流通的工具裡，有一些帶著會偷資料或做壞事的程式。不管來源是哪裡，裝之前請看完這份報告；不確定就不要裝。"
```

| status | 標章（網頁的 chip、終端機的第一行） | 說明文字 |
|---|---|---|
| official | ✅ 官方 | SYNOX 驗過擁有者的簽章：這個檔是官方發的，而且沒有被改過。 |
| author | ✍️ 作者簽章 | 作者自己簽的，**不是官方**。SYNOX 只能確認「檔案跟作者簽的時候一樣」，不能確認作者是誰。（升級時再加：鑰匙跟第一次裝的一樣／**不一樣**） |
| none | ⚠️ 不是官方 | 沒有簽章：SYNOX 無法確認是誰做的、有沒有被改過。只裝你信得過的人給的。 |
| invalid | ⛔ 被改過 | （§1.1 第 5 點；不會有確認鈕） |

- `no_official_keys = True`（`OFFICIAL_PACK_PUBLIC_KEYS` 是空的）→ 說明後面多一句「（這一版 SYNOX 還沒有官方鑰匙，所以暫時沒有工具會顯示官方）」。
- `safety_notice` 每一次都顯示（修正 O1），不分來源，不點名哪一家。
- **網頁的畫法**（`app.html` 的 `showReview`）：報告卡的**第一列**是 SYNOX 畫的標章 chip（`class="badge sig-official|sig-author|sig-none"`，字由 `s.signature.label` 給）＋說明；
  **第二列才是**工具自己的標題。工具的字一律 `textContent`、放在標章下面、不能有自己的樣式，所以蓋不到標章。安全提醒放在確認鈕的正上方。
- `packs.lock` 那一筆多 `"signature": {"status": "official|author|none", "key_id": "…", "public_key": "…"}`（none 只有 status）。
- 工具頁（`/api/tools`）、設定頁的工具清單（`/api/settings` 的 `packs`）、`doctor`、`packs status` 都從**鎖**讀 `signature.status` 給同一個標章；
  沒有鎖＝沒有標章（也不會載入，§4）。

### 3.1 升級（`upgrade.report_for` 多出的紅字）

| 舊鎖 → 新檔 | 報告 |
|---|---|
| official → official（同鑰匙或另一把官方鑰匙） | 「✅ 官方」一行 |
| official → author／none | 🔴 「以前是官方的，這一版**不是官方**」 |
| author（key_id X）→ author（key_id Y） | 🔴 「簽章的鑰匙跟第一次裝的不一樣（可能換人做了，或有人冒名）」 |
| author → none | 🔴 「以前有作者簽章，這一版沒有」 |
| none → author／official | 一般（不是紅字）：「這一版有簽章了」 |
| 任何 → invalid | 拒裝（跟全新安裝一樣，沒有確認鈕） |

紅字只是警告，擁有者看過還是可以按確認（擁有者 2026-11-16：所有來源一律可以裝）；只有 ⛔ 不行。

## 4. 沒有經過安裝頁的工具不載入（漏洞一，S9）

**以前**：`packs/loader.py` 對沒有 `packs.lock` 那一筆、又不是出廠（`BUNDLED`）的 pack 照舊載入、標「未鎖定」；伺服器版載入前補跑第 2 關，個人版連掃都不掃。
放一個資料夾進 `packs/`（任何能寫這個資料夾的程式、瀏覽器下載、同步軟體、USB 自動執行都做得到）就等於裝好了，沒有報告、沒有確認。

**現在**：

- `load_all`：`pack_lock.verify` 回 `unlocked` 而且 `not is_bundled(m)` → 狀態 **`unapproved`**，**不載入**（跟 `tampered` 同一層），detail 白話：
  「這個工具不是從安裝頁裝的，SYNOX 沒有載入它。要用它：到網頁「設定 → 功能與安裝」按「送去安裝頁檢查」，看過報告、按確認才會裝。」
  通知擁有者一次（同一個 pack 只通知一次，`packs_tamper_notified.json` 同一個機制、不同的指紋）。
- `unlocked_scan`（伺服器版補掃）失去用途，拿掉；`PackStatus.scan` 欄位留著（相容），永遠是 `""`。
- `BUNDLED` 是空的（2026-11-12 起出廠不帶工具），`is_bundled` 永遠 False——**不能被假冒**：它只認名字在 `BUNDLED`、而且資料夾就在內建的 `packs/` 底下；
  表是空的就什麼都不是。**不要再把名字加回 `BUNDLED`**（加了就是替那個名字開一道不經安裝頁的門）。
- **送進安裝流程**（網頁）：設定頁的工具清單裡，`unapproved` 的那一列有「送去安裝頁檢查」鈕 → `POST /api/packs/adopt {"name"}` →
  伺服器把 `packs/<name>/` 原地壓成 zip 的位元組（只拿檔案，不執行任何東西）→ `admin.stage`（跟上傳同一條路：zip 檢查、簽章、第 1、2 關）→ 同一份報告、同一個確認鈕。
  按確認 → `adopt.install`：確認 `packs/<name>` 現在**仍然**沒有鎖、把它搬到 `packs/_removed/<name>-<版本>-<時間>`（不刪）、再照一般安裝把暫存那一份搬進來、寫鎖。
  工具的資料不在 pack 資料夾（在 `data/`），不受影響。
- `packs.dirs`（工程師把別的 repo 裡的 pack 原地接進來）：一樣不載入。那個資料夾不是 SYNOX 管的，不提供「送去安裝頁」（搬不了）；detail 多一句
  「進階：這是 config.json packs.dirs 指過去的資料夾。要用它，在電腦上跑 `python -m synox packs lock --approve <name>`（會先檢查、印報告再鎖）。」
  `packs lock --approve` 是明確的開發者動作：跑第 1、2 關、印報告、T2 要 `--trust-publisher`，寫鎖之後才載入；報告也顯示簽章標章（手放的通常是「⚠️ 不是官方」）。
  **實作時決定，待擁有者確認**：這條開發者路徑保留，不另加旗標。
- **升級 SYNOX 的人**：以前手放、沒鎖的工具在新版會變成「沒有經過安裝頁」，不會被刪、資料不動；啟動時通知一次、設定頁列出來、一鍵送進安裝流程。
- **`packs.lock` 本身**：是 `data/` 裡的一個檔。能改它的攻擊者也能改 `src/synox/` 的任何程式、換掉 `.venv` 的 Python——SYNOX 守不了這條線，
  也不假裝守得了（`docs/security.md`「沒有做的保護」）。簽章與鎖守的是「檔案是不是從你按過確認的那份變來的」，不是「你的電腦有沒有被人拿走」。

## 5. 第三方面板隔開（漏洞二，S10）

**以前**：`web.panel` 的 HTML 由主機台同源送出（`/packs/<name>/panel`），工具頁用 `<iframe sandbox="allow-scripts allow-same-origin">` 掛——
`allow-same-origin` 等於沒隔：面板的 JS 讀得到 `/api/me` 的 CSRF token、打得到所有 `/api/`（含 `/api/packs/install`）、改得了主頁 DOM、按得了按鈕。

**現在**（擁有者選 B：照樣可以裝、照樣顯示，但隔開、標風險；官方的也一樣隔）：

| 項目 | 以前 | 現在 |
|---|---|---|
| iframe 屬性 | `sandbox="allow-scripts allow-same-origin"` | **`sandbox="allow-scripts"`**（沒有 same-origin、沒有 forms、popups、top-navigation）→ 面板是 opaque origin：沒有 cookie、碰不到主頁、`/api/` 的 cookie 登入對它無效 |
| 面板網址 | `/packs/<name>/panel` | **`/packs/<name>/panel/<ticket>/`**：工具頁先 `POST /api/packs/<name>/panel-ticket`（要 CSRF）拿一張票，票綁 pack 名字＋這個 session、有效 8 小時（提案值），session 登出就作廢 |
| 面板的回應標頭 | CSP 沒有 `sandbox` | CSP 多 **`sandbox allow-scripts`**（就算哪個地方忘了 iframe 屬性，瀏覽器也把它當 opaque origin）；其餘照舊：`default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'`；`X-Frame-Options: SAMEORIGIN` |
| 面板的資料 | `fetch("/api/packs/<name>/<route>", {credentials: "same-origin"})`（靠 cookie） | **`fetch("api/<route>")`**（相對網址 → `/packs/<name>/panel/<ticket>/api/<route>`）：伺服器只認票，不看 cookie、不要 CSRF（只有 GET、只有這個 pack 在 `web.api` 宣告的 route、以發票的那個人的身分呼叫）；回應加 `Access-Control-Allow-Origin: null`（opaque origin 送出的 `Origin` 是 `null`；不帶 credentials） |
| 這條路放在哪 | — | `WebUI.route` 裡在「`/api/` 的 `sec-fetch-site` 檢查」**之前**另開 `^/packs/<name>/panel/<ticket>/(api/<route>)?$`，不走 `/api/` 那套（那套要 cookie＋同站） |
| 舊的 `/api/packs/<name>/<route>` | 面板用 | 留著（cookie 登入、主頁自己用得到）；從隔開的面板打它會 401——**舊面板要改一行**（`docs/pack-format.md`、CHANGELOG 寫明） |
| 風險標示 | 沒有 | iframe 上方一行 SYNOX 畫的字：「這個小畫面是工具作者做的。SYNOX 把它隔開了：它碰不到你的登入，只能讀這個工具自己的資料；畫面裡的字和按鈕都是作者寫的，不是 SYNOX 的。」＋標章（從鎖讀的 `signature.status`） |
| SDK 範本 | `synox-sdk init` 一定產生 `panel.html` | **預設不產生**；`--panel` 才產生（新範本用相對網址 `api/summary`） |

- 面板能做的事（隔開之後）：畫自己那一格、讀自己 pack 的 `web.api`。不能：讀 cookie／CSRF、打 `/api/`、動主頁、開新視窗、送表單、導頁、蓋住主頁的任何按鈕（它只在自己的框裡）。
- 主頁沒有任何 `message` 事件監聯（查過 `app.html`、`static/*.js`），面板 `postMessage` 進來沒人聽。
- 安裝頁、確認鈕所在的 `app.html` 本來就是 `frame-ancestors 'none'`、`X-Frame-Options: DENY`、COOP `same-origin`、所有 `/api/` 非 GET 要 CSRF 標頭＋`Origin` 等於 `Host`；`window.SynoxInstall`、`synox:install-step` 只有同源腳本碰得到，而隔開之後**沒有任何第三方腳本是同源的**（外觀包的 CSS／SVG 走白名單重建，沒有腳本）。
- **待實測**（真的瀏覽器）：(a) CSP `connect-src 'self'` 在 opaque origin 的文件裡是否仍以**網址**的來源算（規格說是；若不是，改成明寫 `http://<host>:<port>`）；(b) `Access-Control-Allow-Origin: null` 讓 `fetch` 讀得到回應（Chromium、Firefox 都支援，但規格不鼓勵——這裡只配合「票」用，沒有 cookie，所以 `null` 不會放大權限）；(c) 面板在 iframe 裡的捲動與高度。
- 為什麼不搬到工具服務的 `127.0.0.2`（ADR 0024）：那條路是「要用才開一個埠」；面板是工具頁上一直顯示的小格子，每個有面板的工具都開一個埠不合理。
  以後 `web.panel` 的替代品仍然是工具服務（ADR 0022 決定 23 的 b）；這一輪只把現有面板隔開。

## 6. 目錄（`index.json`）這一輪不簽的理由

- 目錄現在的保護：只在按按鈕時連、網址寫死、轉址只跟 GitHub、大小上限、**每個檔的大小與 sha256 要跟目錄一樣**（`packs/catalog.py`）。
- 每個 `.synoxpack` 現在自帶簽章之後，目錄被換掉能做到的只剩：把「官方的檔」換成「不是官方的檔」——報告的標章會從 ✅ 變成 ⚠️，擁有者看得到；
  或指向舊版（降級）——升級規則會擋、要明確勾。它**做不到**讓一個非官方的檔顯示成官方。
- 目錄簽章真正多出來的是**新鮮度與撤銷**（決定 27：撤銷清單跟目錄一起發）：擁有者發現某一版有問題，想讓 SYNOX 在按安裝之前就擋。這需要序號／日期、
  撤銷清單格式、「目錄太舊」怎麼辦——是一個完整的小設計，不該塞進緊急修補。
- 所以：**同一套零件**（`packs/signing.py` 的 canonical JSON＋Ed25519、`OFFICIAL_PACK_PUBLIC_KEYS`）留給目錄簽章用；下一步寫在 ADR 0022 決定 26／27 那一格。

## 7. 誠實清單（這份 ADR 擋不了的）

- 本機有寫入權的攻擊者（改 `packs.lock`、改 `src/synox`、換 `.venv`）。
- 擁有者的私鑰外流（只能事後換鑰匙）。
- 作者簽章證明不了作者是誰，只證明「跟簽的時候一樣」；第一次裝的時候你信的還是那個人。
- 簽章不看內容：官方的也可能有 bug；第 2 關掃描仍然是提醒不是門（`docs/security.md`）。
- 面板隔離在真的瀏覽器裡的行為沒看過（§5 待實測）。

## 8. 指令（給擁有者的在家流程寫手用；這裡只列事實）

照做的清單（產生四把鑰匙、貼公鑰、每次發佈、換鑰匙）在 [../signing.md](../signing.md)。

| 要做什麼 | 指令 | 結果 |
|---|---|---|
| 產生官方工具鑰匙（一次） | `synox-sdk keygen --out <repo 以外的路徑>\synox-packs.pem` | 問密語兩次；寫加密的 PEM（0600）；印出 `public_key`（base64 一行）與 `key_id` |
| 簽一個工具 | `synox-sdk sign <dist>\<name>-<版本>.synoxpack --key <路徑>\synox-packs.pem` | 問密語（或 `SYNOX_PACK_KEY_PASSWORD`）；在 zip 裡加 `pack.sig.json`（原檔覆寫；`--out` 另存）；印 key_id |
| 驗一個工具 | `synox-sdk verify <檔>.synoxpack` | 印 official／author／none／invalid 與原因；結束碼 0＝有效簽章（official 或 author）、1＝沒有簽章、2＝被改過或檔不對 |
| 檢查、打包（既有） | `synox-sdk check <資料夾>`、`synox-sdk zip <資料夾>` | 先 zip 再 sign |
| 發 SYNOX 本體的鑰匙（既有，另一把） | `python scripts\release.py keygen --out <repo 以外>\synox-release.pem` | 現在也會問密語（沒設 `SYNOX_RELEASE_KEY_PASSWORD` 時） |
| 簽 SYNOX 發佈（既有） | `python scripts\release.py sign --dist dist --key <路徑>\synox-release.pem` | 照 ADR 0023 |
| 公鑰貼哪裡 | `src/synox/packs/signing.py` → `OFFICIAL_PACK_PUBLIC_KEYS = ("<base64>",)`；本體的在 `src/synox/update/signing.py` → `RELEASE_PUBLIC_KEYS` | 隨下一版發出去 |

`synox-sdk` 沒有裝成指令時：`python -m synox.sdk keygen|sign|verify …`。這三個子指令需要 `cryptography`（SYNOX 本來就裝）；單檔版 `sdk/synox_sdk.py` 只有標準函式庫，**不含**簽章功能（README 寫明：簽章請用 SYNOX 資料夾裡的 `synox-sdk`）。

## 9. 擁有者要看的（實作時決定，待確認）

1. 名字／標題／說明裡有「官方」「official」「SYNOX」「✅」而不是官方 → **標紅、不拒裝**（§4.3 的理由：官方工具庫自己的工具在鑰匙貼進去之前也是「不是官方」，拒了會把官方的也擋掉；而且標章不看名字，紅字夠醒目）。要改成拒裝只要把 `signing.lookalike_problems` 的結果接到 `run_gates` 的 problems。
2. `packs.dirs` 的開發者路徑保留 `packs lock --approve`，不另加旗標（§4）。
3. 面板票的有效時間 8 小時、綁 session（§5，提案值）。
4. `pack.sig.json` 這個檔名、`version: 1` 的格式（§1）。
5. 目錄簽章列為下一步（§6）。

## 10. 怎麼在真的瀏覽器驗（擁有者，一次）

1. 裝一個有面板的工具（工具庫的記帳），到工具頁：面板上方要看得到那一行風險說明；面板裡要讀得到資料（讀不到＝待實測 (a)／(b) 其中一條不成立，請把瀏覽器主控台的錯誤抄下來）。
2. 在面板的 HTML 裡暫時加 `fetch("/api/me")` → 要是 401／403（碰不到登入）。
3. 上傳一個沒簽章的 `.synoxpack`：報告第一列是「⚠️ 不是官方」；把 `pack.sig.json` 裡任何一個字改掉再上傳：「⛔ 被改過」、沒有確認鈕。
4. 手動把一個 pack 資料夾複製進 `packs/`、重開 SYNOX：有通知、設定頁列「沒有經過安裝頁」、按「送去安裝頁檢查」走到報告。
