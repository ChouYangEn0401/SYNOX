# 工具生態：怎麼找、裝、更新、移除工具，怎麼給別人做工具，之後的路

給三種人：**使用者**（想多裝幾個工具）、**作者**（想做一個工具給人裝）、**維護者**（每次發版要更新哪些文件）。
每一段先寫**現在程式真的會做的**，標「提案」的是還沒決定、還沒寫程式的想法。

- [工具從哪裡來](#工具從哪裡來)
- [使用者：找、裝、更新、移除](#使用者找裝更新移除)
- [作者：做一個工具給人裝](#作者做一個工具給人裝)
- [之後的路（提案）](#之後的路提案)
- [文件維護清單（每次發版）](#文件維護清單每次發版)

## 工具從哪裡來

SYNOX 出廠**不帶任何工具**（2026-11-12 起；為什麼：[legacy/builtin-packs.md](legacy/builtin-packs.md)）。
提醒（`/remind_*`）與排程（`/schedule_*`）是 SYNOX 本體的系統指令，不用裝；其他全部是工具。

| 來源 | 是什麼 | 現況 |
|---|---|---|
| **SYNOX 工具庫（SYNOX_Libs）** | 另一個 repo。官方工具的正本：記帳 `money`、隨手記 `notes`、接 Notion／Todoist／Google 日曆／Apple 提醒事項的工具。打包成一堆 `.synoxpack`＋一份目錄 `index.json`（名稱、版本、標題、說明、建議組合 `bundles`、`requires.sdk`、sha256） | ✅ 已實作。發佈版把打包好的工具庫放在 SYNOX 資料夾的 `tools\`；工具目前全部標 🧪 alpha |
| **別人給你的 `.synoxpack`** | 任何人用 SDK（或自己手寫）做的 pack，壓成 zip | ✅ 已實作：走同一套安裝檢查 |
| **別人架的遠端 MCP、本機 MCP、Claude 技能** | 不是 pack 的東西 | 遠端 MCP：自己寫一份只有宣告的 `pack.json` 就能裝（T0）；本機 MCP 可以但沒有沙盒；技能現在不能直接用。怎麼判斷、怎麼做：[install-third-party-tools.md](install-third-party-tools.md) |
| **直接讀一個資料夾** | 開發工具的人不打包，讓 SYNOX 讀原始資料夾 | ✅ `config.json` 的 `"packs": {"dirs": ["<資料夾>"]}`，再 `synox packs lock --approve <名字>`（跑第 1、2 關、寫鎖；**沒有鎖的不載入**，改了檔要再 approve，[adr/0028](adr/0028-pack-signatures-official-badge.md) §4）；伺服器版當第三方、只給擁有者 |
| 官方工具庫的線上清單 | 網頁「設定 → 🧩 功能與安裝 → 工具庫（官方）」、`synox tools check`／`synox tools update` | ✅ 只在使用者按按鈕或打指令時連網，網址寫死在 `src/synox/packs/catalog.py`（只讀 SYNOX_Libs 的發佈頁），下載後對大小與 sha256，再走同一份報告與確認 |
| 其他線上目錄、商店 | 任意網址的目錄、別人的商店 | ❌ 還沒有（見「之後的路」）。`packs.library` 寫網址時 SYNOX 只會顯示，**不會自動下載** |

工具庫在哪裡：`config.json` 的 `packs.library`（相對於 SYNOX 資料夾，或絕對路徑）；沒寫就找 SYNOX 資料夾裡的 `tools\`（要有 `index.json` 才算）。
`doctor`、`/help`（還沒裝工具時）、網頁設定頁都會提示這個位置。規則在 `src/synox/wizard/tools.py`、`src/synox/packs/library.py`。

## 使用者：找、裝、更新、移除

下面的 `synox` 是 `.venv\Scripts\synox`（或 `.venv\Scripts\python.exe -m synox`）。

### 找

```
synox tools list          工具庫有哪些、哪些已裝（✅ 已裝）、建議組合（bundles）
synox doctor              「• 工具：…」那一行：裝了幾個、工具庫在哪、指錯位置會說
```

網頁「工具」頁只列**已裝**的；「設定 → 功能（pack）」列每個 pack 的狀態（可以用／還沒接上／掃描沒過／版本不合）與原因。

### 裝（三條路，跑同一套檢查）

| 路 | 怎麼做 | 適合 |
|---|---|---|
| 從工具庫挑 | `synox tools install notes money`（名字或組合代號，逗號或空白分開；**不支援「全部」**） | 發佈版、第一次裝 |
| 點兩下 `.synoxpack` | 安裝精靈勾了「點兩下安裝」才有（HKCU 登記 `Install-Pack.bat`）；或把檔拖到 `Install-Pack.bat` 上。SYNOX 在跑的話會開網頁設定頁顯示報告與確認鈕 | 別人傳給你一個檔 |
| 網頁「設定 → 裝功能」 | 上傳 `.synoxpack`，看報告，按確認 | 坐在電腦前 |
| 終端機 | `synox install <檔>.synoxpack`（`--yes` 跳過問答；T2 要 `--trust-publisher "<pack.json 的 publisher>"`；`--runtime container\|host`） | 工程師、腳本 |

每一條都是：工具庫來的先對 sha256 → 第 1 關宣告檢查 → 第 2 關靜態掃描 → **報告給你看，你按確認** → 第 3 關寫 `data/packs.lock`（每個檔的雜湊）→ 要建環境的（`runtime.*: auto`）這時才 pip／npm。
報告上會看到：穩定度（🔧 test／🧪 alpha／🚧 beta／⭐ stable）、要什麼權限、信任層級 T0／T1／T2（T2＝附執行檔或外部程式，要**一字不差**輸入 `publisher` 才裝得了）、`requires.sdk` 合不合。
細節：[security.md](security.md)「五關」「信任層級」。

裝好之後：`/help` 多一組、AI 讀它的 `SKILL.md` 自己學會、網頁工具頁多一個分頁。要填帳號／token 的工具到工具頁「連接」（或 `synox connect <pack>`），**不要在聊天裡打密碼**。

### 更新（升級）

**同名再裝一次就是升級**：從工具庫 `synox tools install <名字>`、上傳新的 `.synoxpack`、或 `synox install`。SYNOX 比對新舊兩版：

- 報告列「改了什麼」：版本（semver，往回退會說）、權限變大（紅字）、執行方式改了、publisher 變了（紅字，要重新輸入）、T1 → T2（紅字）。
- 舊的搬到 `packs/_removed/<名字>-<版本>-<時間>/`，旁邊留舊鎖；資料**不在** pack 資料夾，不會動（資料格式升級由工具自己負責）。
- 退回：`synox packs rollback <名字>`（把 `_removed/` 裡最近一份搬回、鎖改回）。

**檢查有沒有新版**：`synox tools check`（問官方工具庫的線上清單，只看不裝；結束碼 10＝有新版）、`synox tools update <名字…>`／`--all`（每一個都照樣下載、檢查、給你看報告，你核准了才換）。網頁「設定 → 🧩 功能與安裝」的工具庫卡片也會標「有新版」。只有按了才連網。`synox tools list` 看的是本機的工具庫資料夾，不比較版本號。

### 移除

- 網頁「設定 → 功能（pack）」每一列的「移除」：pack 資料夾搬到 `packs/_removed/`，鎖拿掉，**資料檔留著**（`data/<pack>.json.enc`，裝回同名工具就接上）。
- 暫時關掉不移除：`config.json` 的 `"packs": {"disabled": ["money"]}`，重開 bot。
- 終端機沒有 `packs remove`（現在只有 `status`／`lock`／`rollback`／`env`／`runtime`）；要在終端機移除就用網頁，或手動把資料夾搬到 `packs/_removed/` 後 `packs lock` 重整（不建議）。

## 作者：做一個工具給人裝

**從 [tools.md](tools.md) 開始**（三條接入路怎麼選、十行入門、權限欄位、secret、確認來回、測試、安全自檢表）；欄位規則在 [pack-format.md](pack-format.md)；Python SDK 在 [sdk.md](sdk.md)；可以照抄的在 [../examples/](../examples/)。
授權：SDK 與範例是 Apache-2.0，你的工具授權自己決定（[../LICENSING.md](../LICENSING.md)）。

最短路徑：

```
pip install <SYNOX 資料夾>/sdk                              或把 sdk/synox_sdk.py 複製到工具旁邊
synox-sdk init --from tool.py --name hello --title "👋 打招呼"   產生 pack.json（含 requires.sdk）＋SKILL.md
synox-sdk run greet Amy style=formal                           本機試跑，不用開 SYNOX
synox-sdk check .                                              裝的人會看到的報告：第 1、2 關、信任層級、會被擋的原因（結束碼 2＝一定裝不了）
synox-sdk zip .                                                → dist/hello-0.1.0.synoxpack
```

發佈前的清單：

1. `pack.json` 寫好 `version`（semver）、`requires.sdk`（`synox-sdk init` 會寫）、`stage`（不寫＝alpha）、`category`（網頁工具頁的建議群組）、`publisher`（T2 一定要）。
2. `README.md` 寫清楚：有哪些指令、資料存哪、連哪些外面的服務、要填什麼帳號（裝的人會看「連哪裡」決定要不要信你）。
3. `synox-sdk check` 沒有紅字；有第三方套件就 `requires.pip` 釘 `==版本`（建議加 `--hash=sha256:`）。
4. 把 `.synoxpack` 給人：現在就是傳檔案（任何方式）。要進官方工具庫，到 SYNOX_Libs 那個 repo 開 PR（它會檢查每個工具的 `requires.sdk` 跟打包用的 SYNOX 相容，並寫進 `index.json` 的 sha256）。交原始碼就好、**不用簽章**：官方簽章由擁有者在發佈時加（[signing.md](signing.md) 第 4 節）。自己發給別人的工具可以用自己的鑰匙簽（✍️ 作者簽章，[sdk.md](sdk.md)「簽章」）。
5. 升級版：版本號往上、不要偷偷變大權限（會紅字）、資料格式自己做相容。

## 之後的路（提案）

下面**都還沒做、還沒拍板**，列出來是讓大家知道方向，不是承諾。每一項寫了為什麼現在沒做。

| 提案 | 想做什麼 | 現在為什麼沒有 | 要先決定的事 |
|---|---|---|---|
| **線上目錄（registry／index）** | `packs.library` 寫網址時，SYNOX 真的去抓 `index.json` 與 `.synoxpack`；`synox tools list` 看得到線上的、`install` 直接下載 | 現在 `index.json` 只有本機資料夾；SYNOX 刻意**不連網**做安裝（除了建環境的 pip／npm）。要加「從網址下載」就多了一條會出門的路、要處理代理、快取、下載到一半 | 誰架目錄、放哪、要不要 HTTPS 以外的驗證、離線發佈版怎麼共存 |
| **目錄的簽章與撤銷清單** | 工具庫的目錄 `index.json` 也簽名、可以撤銷外流的鑰匙 | **每個 `.synoxpack` 的簽章已經做了**（[adr/0028](adr/0028-pack-signatures-official-badge.md)：`pack.sig.json`、✅ 官方／✍️ 作者簽章／⚠️ 不是官方／⛔ 被改過，官方公鑰由擁有者貼進程式）；目錄本身還沒簽（ADR 0028 §6） | 撤銷清單放哪、怎麼發 |
| **本機工具庫的檢查更新** | `synox tools list` 比對本機工具庫資料夾（`tools\`）與已裝版本、標「有新版」 | 官方工具庫的線上清單**已經可以**檢查與更新（`synox tools check`／`update`、網頁的工具庫卡片）；本機資料夾那條還沒寫 | 要不要自動更新（建議不要：升級報告要人看） |
| **評分與回報** | 工具頁上看別人用得怎樣、回報問題 | 需要線上服務與帳號，跟「本機優先」有張力 | 先用 GitHub issue 就好？ |
| **從介紹頁一鍵安裝** | [landing/index.html](landing/index.html) 上按一下就裝 | 網頁介面只聽 127.0.0.1，外面的頁面碰不到；要做得先有 registry 與 `synox://` 之類的協定登記 | 等 registry |
| **macOS／Linux 安裝器** | `Setup.bat` 以外的一鍵安裝 | 程式跨平台，但只做了 Windows 的安裝路徑與 DPAPI 保管箱；其他平台主金鑰是明文 | 保管箱在其他平台怎麼保護 |

已經有、常被誤會成沒有的：升級與退回（上面）、T2 要輸入發行者、`requires.sdk` 版本相容、工具庫 sha256、穩定度標示。

## 文件維護清單（每次發版）

這些檔案互相指來指去，改一處就查一遍。

| 改了什麼 | 要跟著動的 |
|---|---|
| 版本號（`pyproject.toml`） | `CHANGELOG.md` 開一節；[landing/index.html](landing/index.html) 右上角的版本徽章與頁尾；`setup/installer/synox.iss` 的 `/DAppVersion`；README 頂端 alpha 說明仍屬實？ |
| 安裝流程（精靈頁面、`Setup.bat`、安裝程式） | README「快速開始」；[tutorials/telegram/](tutorials/telegram/)、[tutorials/discord/](tutorials/discord/)（截圖要重拍）；landing 的「三步裝好」「安裝」兩節；[handoff/clean-machine-test.md](handoff/clean-machine-test.md) |
| Discord 的設定方式或名詞 | [discord.md](discord.md)、[discord-concepts.md](discord-concepts.md)、[tutorials/discord/](tutorials/discord/) |
| 網頁介面的畫面 | 重跑 `scripts/make_ui_preview.py`（`tests/test_ui_preview.py` 會擋沒同步的）；重拍 `docs/ui/screenshots/*.png`；[ui/redesign-notes.md](ui/redesign-notes.md)；介紹頁的截圖重拍、重組：`python scripts/make_landing.py --shoot`（原稿 `docs/landing/page.html`，截圖在 `docs/landing/shots/`，組出 `index.html`；之後重新發佈成 Artifact，網址在 README） |
| pack.json 欄位、SDK 介面（`SDK_VERSION`） | [pack-format.md](pack-format.md)、[sdk.md](sdk.md)、[tools.md](tools.md)、`sdk/synox_sdk.py` 重產（`scripts/build_synox_sdk.py`）、`examples/*/pack.json` 的 `requires.sdk`；通知 SYNOX_Libs 重新打包 |
| 工具庫的工具（新增、下架、改穩定度） | SYNOX_Libs 的 `index.json` 與 README；這裡的 README「每天怎麼用」表（指令範例）、[../packs/README.md](../packs/README.md)、landing「它是什麼」的工具庫那格 |
| 安全邊界（新的關卡、沙盒、驗證過的東西） | [security.md](security.md)「能保證什麼」「沒有做的保護」；README 頂端的 alpha 警告；landing「安全」「現在的狀態」「接下來」三節；[AGENT.md](AGENT.md) 的 invariants 與 Known limitations |
| 這份文件的「提案」有一項真的做了 | 把它從「之後的路」搬到對應的「現在」段落；landing「接下來」那一欄跟著搬 |

發版前照舊跑 [AGENT.md](AGENT.md)「公開前檢查清單」（`scripts/prepublish_check.py`、全部測試）；[README.md](README.md) 的索引有沒有列到新文件。
