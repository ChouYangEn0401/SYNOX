<!-- SPDX-License-Identifier: Apache-2.0 -->
# 📋 任何語言都能寫的 cli 工具（不用 SDK）

SYNOX 跟 kind=cli 工具之間**只有一個純文字協定**：SYNOX 照 pack.json 組好命令列、開子程序，
工具**最後一行印一個 JSON 物件**、用結束碼說成功或失敗。用什麼語言寫都可以；
[synox_sdk](../../docs/sdk.md) 只是幫 Python 作者省事，**不是必要的**。

這個資料夾的 `tool.py` 刻意**不 import synox_sdk**，只用 Python 標準函式庫手寫整個協定，照著它就能翻成任何語言。
（範例用 Python 寫，是因為 SYNOX 本身就帶 Python，`{python}` 一定叫得起來；換成 Go、Rust、C# 編出來的執行檔也一樣，
只是那會變成 T2 pack，見下面「換成別的語言」。）

| 檔案 | 做什麼 |
|---|---|
| `tool.py` | 備忘清單：`list`（看）、`add --text=…`（記一筆）、`clear`（全部刪掉，先要人確認） |
| `pack.json` | 三個指令的 effect、欄位、argv 樣板；`data: user`＋`filesystem:own` |
| `SKILL.md` | 給 AI 看：什麼時候用哪個指令 |

## 協定

### 1. SYNOX 怎麼叫你

```
<cli.argv…> <command 的 argv，欄位代換好> --json
```

本例：`{python} ./tool.py add --text=買牛奶 --json`。

- `cli.argv`＋每個 command 的 `argv` 樣板只能是：字面字、**單獨一段**的 `{欄位}`、或 `--旗標={欄位}`（一段）。
  `["--text", "{text}"]` 這種分兩段的第 1 關就拒。
- 沒填的選填欄位整段拿掉，所以你的程式要有預設值。
- 值不會以 `-` 開頭、不會有換行（SYNOX 先擋）；`kind: int`／`number`／`bool`／`choice` 的值 SYNOX 已經檢查並整理好
  （`bool` 一律是 `true`／`false`、數字拿掉千分位逗號）。
- 長文字可以改走 stdin：command 寫 `"stdin": "{text}"`，那個欄位就不進 argv。
- `cwd` 是 `cli.cwd`（相對於 pack 資料夾）。

### 2. 你拿到的環境變數

| 名字 | 是什麼 |
|---|---|
| `SYNOX_USER_DATA_DIR` | 這個人的資料夾（伺服器版每人一個）。你的檔放 `<這裡>/<pack 名>/` |
| `SYNOX_TG_ID` | 下指令的人的 Telegram id（字串） |
| `SYNOX_MODE` | `personal` 或 `server` |
| `SYNOX_PACK_DIR`、`SYNOX_PACK_NAME` | pack 資料夾、pack 名 |
| `SYNOX_SECRET_ENV` | `auth.fields` 的「欄位名=環境變數名」（只有名字，值在那個環境變數裡） |
| `SYNOX_CONFIRMED`、`SYNOX_CONFIRM_TOKEN` | 確認來回用（下面第 4 點）。`SYNOX_CONFIRMED` 每次都有：`1`＝人按過 ✅ 的重跑，其他一律 `0` |

名字像密鑰的環境變數（`*_TOKEN`、`*_API_KEY`、`*_SECRET`、`*_PASSWORD`…）SYNOX 會拿掉，只放行 pack.json 的
`requires.env` 與 `auth.fields[].env` 列的。

### 3. 你要印什麼

**最後一行**印一個 JSON 物件（前面印 log 沒關係，SYNOX 只看最後一行）：

| 情況 | 最後一行 | 結束碼 |
|---|---|---|
| 成功，有話要說 | `{"ok": true, "message": "記下了（共 3 筆）"}` | 0 |
| 成功，回資料 | `{"ok": true, "data": {"count": 3}}`（SYNOX 攤平成幾行） | 0 |
| 失敗 | `{"ok": false, "error": "找不到這筆", "code": "not_found"}` | 1 |
| 要人確認才做 | `{"ok": true, "needs_confirm": true, "summary": "要刪 3 筆", "confirm_token": "…"}` | 0 |

`message` 會原樣給使用者（AI 呼叫時交給 AI 轉述）；沒有 `message` 就把 `data` 攤平（一個 key 一行、最多 25 行）。
輸出用 UTF-8。

### 4. 確認來回

1. 第一次叫：工具看了資料覺得要問人，印 `needs_confirm`（`confirm_token` 只收英數字與 `. _ : -`、128 字內；建議放「看到的那份資料」的雜湊）。
2. SYNOX 不顯示結果，送一張確認卡給下指令的人。
3. 人按 ✅：SYNOX 用**同一組參數、同一個 argv** 再叫一次，這次 `SYNOX_CONFIRMED=1`、`SYNOX_CONFIRM_TOKEN`＝你給的 token。
   本例比對 token 跟現在清單的雜湊：不一樣（確認之後清單被改過）就不刪。
4. 按 ❌、過期、參數對不上：SYNOX 不會叫你第二次。

「已確認」只會來自 SYNOX 驗過一次性憑證之後明寫的環境變數，AI 改參數、pack.json 的 `cli.env` 都造不出來；
所以**不要**另外做 `--yes` 這種旗標。

## 試試看

```
cd examples/any-language-cli
synox-sdk check .                 第 1 關（宣告）＋第 2 關（靜態掃描）
synox-sdk run add 買牛奶           跟在 Telegram 打 /anylang_add 買牛奶 一樣
synox-sdk run list
synox-sdk run clear               印出 SYNOX 會出的確認卡
synox-sdk run clear --confirmed   當作按了 ✅
```

（還沒有 `synox-sdk` 指令時用 `python -m synox.sdk …`。）`synox-sdk check` 會對 `os.environ.get(...)` 印 ⚠️「讀環境變數」：
那只是列給安裝的人看，不擋。

## 換成別的語言

- 照上面的協定寫就好。pack.json 的 `cli.argv` 改成你的程式，例如 `["./memo.exe"]`（pack 裡的檔）或 `["{node}", "./memo.js"]`。
- **pack 裡附了執行檔**（`.exe`、`.dll`、`.sh`、`.bat`、沒有副檔名但帶執行位元、檔頭是 MZ／ELF／Mach-O…）＝**T2**：
  `capabilities` 一定要加 `exec`、`publisher` 一定要寫，安裝的人要一字不差地輸入你的 publisher 才裝得了。
  `cli.argv` 叫 pack 外的程式（`npx`、`go`、`dotnet`、絕對路徑）也是 T2（報告標「未鎖定執行環境」）。
- 能用純 Python（只有 `.py`）寫完就別附執行檔：T1 的 pack 安裝的人看得到你做什麼，T2 只能「信你」。
  完整的說明見 [docs/tools.md](../../docs/tools.md)。
