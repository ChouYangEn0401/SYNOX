# 簽章：在家產生鑰匙、簽官方工具、簽 SYNOX 發佈

給 SYNOX 擁有者的照做清單（第 1～5、7、8 節），以及想簽自己工具的作者（第 6 節）。
規格與理由在 [adr/0028](adr/0028-pack-signatures-official-badge.md)（工具）與 [adr/0023](adr/0023-updates-and-hotfixes.md) §7（SYNOX 本體）；
使用者看到的標章說明在 [security.md](security.md)「簽章與官方標章」。這一頁只寫怎麼做。

## 1. 三十秒看懂

- **私鑰＝你的印章**，只在你家的電腦＋一份離線備份。**公鑰＝印章的樣本**，寫進 SYNOX 的程式、隨版本發給大家。
- 簽章**不是加密**：檔案照樣看得到，簽章只證明「是這把鑰匙簽的、簽完沒有人改過」。
- 兩組鑰匙，不混用：**工具鑰匙**簽 `.synoxpack`（公鑰在 `src/synox/packs/signing.py` 的 `OFFICIAL_PACK_PUBLIC_KEYS`）；
  **發佈鑰匙**簽 SYNOX 本體的 `release.json`（公鑰在 `src/synox/update/signing.py` 的 `RELEASE_PUBLIC_KEYS`，`Update.bat` 驗）。每組一把現用＋一把備用，兩把公鑰都寫進去。
- 使用者裝工具時看到的四種標章：

  | 標章 | 意思 | 能不能裝 |
  |---|---|---|
  | ✅ 官方 | 你的工具鑰匙簽的、沒被改過 | 可以 |
  | ✍️ 作者簽章 | 別人的鑰匙簽的、沒被改過；**不是官方** | 可以 |
  | ⚠️ 不是官方 | 沒有簽章 | 可以，提醒更強 |
  | ⛔ 被改過 | 有簽章但對不上（多、少、改一個檔都算） | **拒裝**，沒有覆寫 |

- 在你把公鑰貼進去、發出新版之前，**所有工具（包括工具庫的）都顯示「⚠️ 不是官方」**，`Update.bat` 也要 `-AllowUnsigned` 才換。

## 2. 第一次：在家產生鑰匙（一次）

在你家的電腦、SYNOX 的 git clone 裡開 PowerShell。私鑰檔放在 **repo 以外、也不在任何 git 資料夾裡**（指令會拒絕），例如 `D:\keys\`。

```
.venv\Scripts\synox-sdk.exe keygen --out D:\keys\synox-packs.pem
.venv\Scripts\synox-sdk.exe keygen --out D:\keys\synox-packs-backup.pem
.venv\Scripts\python.exe scripts\release.py keygen --out D:\keys\synox-release.pem
.venv\Scripts\python.exe scripts\release.py keygen --out D:\keys\synox-release-backup.pem
```

- 每一道都會**問密語兩次**（打字不顯示）。兩個指令都不收空密語（直接按 Enter＝不產生鑰匙）。
  四把可以用同一句密語，也可以不同；忘了就等於鑰匙丟了（第 7 節）。
- 不會蓋掉已經存在的檔；印出的東西要**抄下來**（放在備份旁邊，之後貼進程式）：
  - `synox-sdk keygen`：`public_key: <44 字>` 與 `key_id: <16 字>`。
  - `release.py keygen`：第一行就是公鑰（44 字），下面接著印 `key_id: <16 字>`。
- 私鑰檔開頭是 `BEGIN ENCRYPTED PRIVATE KEY`（看到 `BEGIN PRIVATE KEY` 沒有 ENCRYPTED＝沒加密，刪掉重做）。
- **備份**：四個 `.pem` 複製到 USB 隨身碟（或密碼管理器的附件）、拔下來收好；密語另外記在密碼管理器。
  其他開發機、雲端硬碟、聊天、issue、CI secret 都**不要有私鑰**。別台電腦只負責寫程式與打包，簽章只在家做。
- `.venv\Scripts\synox-sdk.exe` 是 `pip install -e .[dev]` 裝出來的；沒有它就用 `.venv\Scripts\python.exe -m synox.sdk keygen …`（下面的 `sign`／`verify` 一樣）。

## 3. 把公鑰放進 SYNOX

1. `src/synox/packs/signing.py`，把四個公鑰裡**工具的兩把**（現用＋備用）貼進去：

   ```python
   # 之前
   OFFICIAL_PACK_PUBLIC_KEYS: Sequence[str] = ()
   # 之後（兩行都是 keygen 印的 public_key，44 字、結尾 =）
   OFFICIAL_PACK_PUBLIC_KEYS: Sequence[str] = (
       "<synox-packs 的 public_key>",
       "<synox-packs-backup 的 public_key>",
   )
   ```

2. `src/synox/update/signing.py` 的 `RELEASE_PUBLIC_KEYS` 同樣貼**發佈的兩把**。
3. 兩個測試現在寫死「還沒有鑰匙」，貼了之後要跟著改成「就是這兩把」：
   `tests/test_pack_signing.py::test_no_official_key_shipped_and_no_env_backdoor`、
   `tests/test_update.py::test_no_public_key_is_shipped_yet_and_no_private_key_anywhere`。
4. 跑：`.venv\Scripts\python.exe -m pytest -q tests\test_pack_signing.py tests\test_sdk_sign.py tests\test_update.py`，再跑全部。
5. 自己驗一次：用現用工具鑰匙簽任何一個 `.synoxpack`（第 4 節），再 `.venv\Scripts\synox-sdk.exe verify <那個檔>`——
   要印 `✅ 官方（official）`（verify 用的就是這份程式裡的常數）。改回 `⚠️`／`✍️` 就是貼錯了。
6. commit（只有這三類檔：兩個 `signing.py`、兩個測試；`git status` 確認沒有 `.pem`）→ 照 [release-playbook.md](release-playbook.md) 發一版。
   `scripts/prepublish_check.py` 與 `tests/test_update.py` 會掃 repo 裡有沒有私鑰檔頭。

**在這一版到使用者手上之前**，每個人看到的仍然是「⚠️ 不是官方」、`Update.bat` 仍要 `-AllowUnsigned`；這一版本身也只能這樣裝（舊版沒有公鑰可驗）。從下一版開始才會驗。

## 4. 每次發佈官方工具

單一個工具（例如自己試的）：

```
.venv\Scripts\synox-sdk.exe zip <pack 資料夾>                                   → dist\<name>-<版本>.synoxpack
.venv\Scripts\synox-sdk.exe sign dist\<name>-<版本>.synoxpack --key D:\keys\synox-packs.pem
.venv\Scripts\synox-sdk.exe verify dist\<name>-<版本>.synoxpack
```

- `sign` 問一次密語（腳本裡用環境變數 `SYNOX_PACK_KEY_PASSWORD`），在 zip 裡加 `pack.sig.json`，預設覆寫原檔（`--out` 另存），印 `✅ 簽好了：…` 與 `key_id`。
  **先 zip 再 sign**；簽完再動任何一個檔（含重新 zip）都要重簽。
- `verify` 結束碼：0＝有效簽章（official 或 author）、1＝沒有簽章、2＝被改過或檔不對。在貼了公鑰的 SYNOX 裡跑，第一行要是 `✅ 官方（official）`。

**SYNOX_Libs（工具庫）一整批**（完整的發佈步驟在 [release-playbook.md](release-playbook.md) 第 3 節）：

1. 在 SYNOX_Libs 跑 `python scripts/build.py`（產生 `dist/` 的每個 `.synoxpack`、別名、`tools-<VERSION>.zip`、`index.json`、`SHA256SUMS`）。
2. 把 `dist/` 複製到家裡的電腦（或就在家裡 build），**每一個** `.synoxpack` 都 `sign` 一次（別名檔也要是簽過的那一份），每一個都 `verify`。
3. **簽完檔案就變了**：SYNOX 的工具庫頁對每個檔都要「大小與 sha256 跟 `index.json` 一樣，不一樣就不裝」（`src/synox/packs/catalog.py`），
   所以 `index.json` 每一筆的 `sha256`／`size`、`SHA256SUMS`、`tools-<VERSION>.zip` 都要用**簽過的檔**重算、重包。
   這份文件寫的時候 `build.py` 還不知道簽章這回事——在它學會「先簽再算」之前，要自己補算（PowerShell：`Get-FileHash -Algorithm SHA256 <檔>`、`(Get-Item <檔>).Length`）。
4. 上傳順序照手冊：先 `.synoxpack`、zip、`SHA256SUMS`，**最後才換 `index.json`**。
5. 目錄 `index.json` 本身**還沒簽**（ADR 0028 §6，下一步）：目錄被換掉最多把官方檔換成「⚠️ 不是官方」的，標章會變、使用者看得到。

## 5. 每次發佈 SYNOX 本身

照 [release-playbook.md](release-playbook.md) 第 1 節；簽章那一步在家做，用**發佈鑰匙**：

```
.venv\Scripts\python.exe scripts\make_zip.py --tools <SYNOX_Libs 的 dist>
gh release download <tag> -R ChouYangEn0401/SYNOX -p "SYNOX-Setup-*.exe" -D dist        （有安裝程式才有）
.venv\Scripts\python.exe scripts\release.py sign --dist dist --key D:\keys\synox-release.pem [--security] [--summary "一句白話"]
```

- `release.py sign` 會在終端機上**問密語**（打字不顯示）。不在終端機上跑（腳本）時改讀環境變數 `SYNOX_RELEASE_KEY_PASSWORD`。
  `--key` 也可以改用環境變數 `SYNOX_RELEASE_KEY_FILE`（放路徑）。
- 寫出 `dist\SHA256SUMS.txt`、`dist\release.json`、`dist\release.json.sig`；安全修正加 `--security`。`dist\` 裡要先有 `SYNOX-<版本>.zip`。
- 上傳四個檔：`SYNOX-<版本>.zip`、`SHA256SUMS.txt`、`release.json`、`release.json.sig`。
- `release.py sign --key D:\keys\synox-release.pem --show-public` 只印公鑰（對照 `RELEASE_PUBLIC_KEYS` 貼對沒）。

## 6. 給其他作者

```
synox-sdk keygen --out D:\keys\my-pack-key.pem          一次：產生鑰匙（問密語兩次；放在專案與 git 以外）
synox-sdk zip .                                         打包
synox-sdk sign dist\<name>-<版本>.synoxpack --key D:\keys\my-pack-key.pem
synox-sdk verify dist\<name>-<版本>.synoxpack           會看到 ✍️ 作者簽章（author）
```

- 你的標章是 **✍️ 作者簽章**，永遠不會是 ✅ 官方；它證明「檔案跟你簽的時候一樣」，證明不了你是誰。公鑰不用給任何人，它就在 `pack.sig.json` 裡。
- **之後每一版都用同一把鑰匙**：換了鑰匙，使用者升級時會看到紅字「簽章的鑰匙跟第一次裝的不一樣」；拿掉簽章也是紅字。所以鑰匙要備份。
- 名字、標題、說明裡別寫「官方」「official」「SYNOX」「✅」：不是官方的工具寫這些，報告會紅字標出來。
- 細節（印出什麼、環境變數、單檔版 SDK 沒有簽章）在 [sdk.md](sdk.md)「簽章」。

## 7. 出事怎麼辦

| 情況 | 做法 |
|---|---|
| **工具私鑰外流**（有人拿到 `synox-packs.pem`＋密語） | ① 之後的工具一律用 `synox-packs-backup.pem` 簽（備用公鑰早就在 SYNOX 裡，使用者看到的還是 ✅）。② 馬上發一版 SYNOX：`OFFICIAL_PACK_PUBLIC_KEYS` 拿掉外流那把、再 keygen 一把新的備用貼進去；改測試；照 `SECURITY.md` 發公告。③ 還沒更新到這版的人，看到外流鑰匙簽的檔仍是 ✅——所以②要快。更新到這版之後，那把簽的新檔只會是「✍️ 作者簽章」（有效但不是官方）；已經裝好的工具標章從 `packs.lock` 讀，不會變 |
| **發佈私鑰外流** | 同上，用 `synox-release-backup.pem` 簽下一版，`RELEASE_PUBLIC_KEYS` 拿掉外流那把、補一把新備用，`release.py sign --security`，發公告 |
| **私鑰弄丟／忘了密語**（沒外流） | 跟外流一樣換成備用那把；不急著公告，但下一版還是要拿掉舊公鑰（你驗不了它、也不該再信它）、補新的備用 |
| **現用＋備用都沒了** | keygen 兩把新的、貼進去、發一版。那一版本身沒有能驗它的舊鑰匙：使用者要 `Update.bat -AllowUnsigned` 或重新下載（跟第一次一樣） |

換鑰匙的通則（[release-build.md](release-build.md)「發佈簽章金鑰」）：新公鑰**先**隨一版發出去、舊的先留著，之後才用新私鑰簽；確定大家都更新了再拿掉舊的。
備用鑰匙就是為了把這個等待省掉。

## 8. 不要做的事

- 不要把 `.pem` 放進 repo、任何 git 資料夾、雲端硬碟、聊天、issue、CI secret；不要貼進任何 AI 對話。`synox-sdk keygen`／`sign` 會拒絕 git 資料夾裡的私鑰，但擋不了你複製過去。
- 不要在別台開發機簽章；別台只 build，簽在家。
- 不要用 `--no-passphrase`。
- 不要把密語打在命令列上（`$env:X = "…"` 會留在 PowerShell 歷史）；讓指令在終端機上問你就好。
- 不要把工具鑰匙拿來簽發佈、或反過來（兩邊的 `sign` 都吃得下去，但驗的是另一組公鑰：工具會變成 ✍️ 作者簽章、`Update.bat` 會因為簽章對不上而拒絕更新）。
- 不要簽完再碰檔案；不要在 `tools-<VERSION>.zip`、`index.json` 裡混進沒簽的那一份。
- 不要用加了公鑰的那一版去「證明」自己：第一版沒有舊鑰匙可驗，這是正常的。
