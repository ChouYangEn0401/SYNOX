# 金流簿（記帳專案）的 synox-pack 跟上 0.18.x

- 狀態：**待處理**（由擁有者轉交給 `C:\Users\user\Documents\記帳專案` 的 session；SYNOX 這邊不改對方的檔）
- 寫的時間：2026-11-12（SYNOX dev，合併 `debug/setup-python-telegram` 之後）
- 對象：記帳專案 `synox-pack/`（`pack.json`、`SKILL.md`、`README.md`）

## 擁有者原話

「我要你去幫我把 synox 稍為更新一下，目前 synox 最後一次更新完以後，telegram bot 有大更新，記帳本現在也在 update，我感覺這邊的核心也會需要更新一下。」

## 問題一句話

金流簿 2026-11-12 出了 0.18.0～0.18.4（撥額度、挪用、帳戶綁用途、依現在的錢估每天、待解決），但 `synox-pack/` 還停在 0.17.0（11-09），
SYNOX 上的人用不到新的指令，AI 手冊也不知道有這些。

## 脈絡

- SYNOX 這邊用 SYNOX 的安裝檢查（第 1、2 關，`admin.run_gates`）唯讀跑過**目前的** `記帳專案/synox-pack`：沒有 problem，T2
  （`../.venv` 的 Python 與 `-m moneybook` 在 pack 外，照舊要 publisher）。現在的 pack 能裝、能用，只是沒有新功能。
- SYNOX 的測試 fixture（`tests/fixtures/moneybook_pack/`）已經對齊 0.17.0（含 `positional`）。對方改了之後要再對一次，
  差異只該剩 SYNOX 多寫的 `surfaces`／`data` 兩行（見下面第 2 項；對方補上之後就完全一樣）。
- 0.18.x 裡 CLI 新的（`src/moneybook/cli/reviewcmd.py`、`ledger.py`）：
  - `plan move --from= --to= --amount= [--note= --period=]`、`plan move --undo=<編號>`、`plan moves [--period=]`（ADR 0028）
  - `inbox conflicts`（只列不改，ADR 0029）
  - `summary` 多 `data.estimate` 與一行字（依現在的錢估每天；既有的 `summary` 指令自動就有，不用新指令）
  - `account add/edit --bucket=`（空字串＝清掉，ADR 0031）、`plan bucket <格子> --set-aside=yes --to=<帳戶|預繳>`（ADR 0026）
  - 欠款（7840375，`owed`）目前看起來只有網站，沒有 CLI——不用包。
- SYNOX 的 cli 樣板規則（`docs/pack-format.md`）：**沒填的欄位整個 `--k={v}` 會被拿掉**，所以「給空字串＝清掉」寫不出來；
  要清就另開一個指令，argv 直接寫死 `--bucket=`。

## 選項

| 選項 | 一句話 | |
|---|---|---|
| A. 加讀的＋挪用：`moves`、`conflicts`（read）、`move`（write）、`move_undo`（danger），SKILL.md 補「挪用」「待解決」「每天可以花多少看 summary」，版本 0.18.4 | 手機上最常用的兩件（挪額度、看待解決）能用，帳戶設定留在網站 | **建議（預設）** |
| B. A＋帳戶綁用途、撥額度（`account_bucket`、`account_unbind`、`set_aside`） | 全部能在聊天做，但這幾個是設定類、一年改幾次，AI 誤用的成本比好處大 | |
| C. 只把版本號改成 0.18.4、不加指令 | 最小，但 SYNOX 上的人用不到新功能 | |

另外不管選哪個都建議一起做：

1. `pack.json` 明寫 `"surfaces": ["dm"]`、`"data": "user"`（SYNOX 0.2.0 起建議明寫；沒寫時 SYNOX 推斷成同樣的值，但安裝報告會標「（沒寫，照預設推的）」）。
2. `README.md` 的「SYNOX loader 要替換的佔位字（提案，SYNOX v0 還沒做）」那段已經過時：SYNOX 0.2.0 已經支援
   `runtime.python`／`python_posix`、最上層 `env`、`{user_data_dir}`、`commands[].positional`。改成一句「SYNOX ≥ 0.2 都支援」並加
   `"requires": {"synox": ">=0.2"}`（舊版 SYNOX 會明說要先更新，而不是載入後行為不對）。
3. `move_undo` 用 `effect: "danger"`（跟 `undo` 一樣，AI 叫會先送確認卡）。

## 驗收

- 記帳專案：`tests/test_synox_pack.py` 照舊過（它用 SYNOX 的 manifest 檢查器驗）；新指令的 argv 用 `--json` 真的吃得下。
- SYNOX：把 `synox-pack/pack.json`、`SKILL.md` 複製到 `tests/fixtures/moneybook_pack/`，跑
  `.venv\Scripts\python.exe -m pytest -q tests/test_security.py tests/test_perm2.py tests/test_review_b_exec.py tests/test_review_c.py` 全過；
  `test_moneybook_pack_shape_resolves` 的指令數字若有寫死要跟著改。

## 不要做的事

- 不要把 SYNOX 的程式複製進記帳專案（`test_synox_pack.py` 只載 `manifest.py` 一支、找不到就跳過，維持這樣）。
- 不要讓 pack 的指令碰到 `MONEYBOOK_HOME` 以外的路徑（伺服器版一人一本靠它）。
- 不要在 SKILL.md 叫 AI 自己挪額度或撤銷：挪用要使用者說了才做，撤銷一律走確認卡。
