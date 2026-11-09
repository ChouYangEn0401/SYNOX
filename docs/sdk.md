# synox.sdk：把任何工具包成 SYNOX 的 pack

**工具是什麼都行，接口只有 CLI。** 你的工具可以是 exe、Node 腳本、Go 程式、另一個 Python 專案——SYNOX 只用一種方式叫它：
`kind: cli` 的 pack 照 `pack.json` 的 argv 樣板組出命令列（經 JobRunner：argv 陣列、不開視窗、有逾時），
工具做完在**最後一行印一個 JSON 物件**，結束碼 0＝成功。有用 SDK 的信封、宣告了 `web.panel`／`web.api` 的工具，
Web UI 的工具頁就替它長出一頁面板；沒有的也一樣能用，只是只有指令卡。

## 三種回法（JSON 信封）

| 情況 | 印出來的那一行 | 結束碼 | SYNOX 怎麼顯示 |
|---|---|---|---|
| 成功 | `{"ok": true, "message": "記了 120 元", "data": {...}}` | 0 | 直接回 `message`；沒有 message 就列出 data 的簡單欄位 |
| 失敗 | `{"ok": false, "error": "找不到這筆", "code": "not_found"}` | 1 | `❌ <指令>：找不到這筆` |
| 要確認 | `{"ok": true, "needs_confirm": true, "summary": "要刪 3 筆", "confirm_token": "…", "message": "…"}` | 0 | 這一版只顯示 message（按鈕來回還沒做，見最後一節） |

Python 寫的工具直接用：

```python
import sys
from synox.sdk import reply_ok, reply_error

sys.exit(reply_ok({"count": 3}, "共 3 筆"))        # 印信封、回結束碼
```

別的語言照上面的形狀自己印就好（`console.log(JSON.stringify({ok: true, message: "…"}))`）。
前面多印幾行 log 沒關係：SYNOX 取**最後一個** JSON 物件。

## 十行把一支命令列工具包成 pack

假設你有一支 `weather.exe`，`weather.exe today --city=台北 --json` 會印 `{"ok": true, "message": "台北 23 度"}`。
新增一個資料夾 `weather/`，放 `pack.json`：

```json
{
  "name": "weather", "title": "🌤 天氣", "summary": "看今天的天氣", "version": "0.1.0", "kind": "cli",
  "skill": "SKILL.md", "capabilities": [], "publisher": "你的名字",
  "cli": {"argv": ["{pack_dir}/weather.exe"], "json_flag": "--json", "timeout": 30,
          "commands": [{"name": "today", "effect": "READ", "default": true, "summary": "今天天氣",
                        "argv": ["today", "--city={city}"],
                        "fields": [{"name": "city", "ask": "哪個城市", "default": "台北"}]}]}
}
```

再放一份 `SKILL.md`（給 AI 看什麼時候用）。完成：`/weather 高雄` 在 Telegram 能用，AI 也多了一個 `weather__today` 工具。

規則（安裝時第 2 關會檢查）：

- argv 樣板只能有字面字、**單獨一段**的 `{欄位}`、或 `--旗標={欄位}`（一段）。`["--city", "{city}"]` 會被拒：值要跟旗標黏成一段。
- 每個 command 一定要寫 `effect`：`READ`（只看）、`WRITE`（改東西）、`DANGER`（刪、付錢…，AI 呼叫一律先送確認卡給人按）。
- 欄位的值以 `-` 開頭、有換行、像密鑰的檔名（`.env`、`id_rsa`、`*.pem`…）都會在呼叫前被擋。欄位 `"kind": "path"` 的值一定要在使用者自己的資料夾裡。
- 欄位可以標型別 `"kind"`：`int`、`number`、`bool`、`choice`（配 `"choices": [...]`）、`path`、`text`（預設）。SYNOX 先檢查格式再叫你的工具，
  `bool` 一律傳 `true`／`false`，所以工具那邊不用自己解析「是／否」。
- 工具要 API 金鑰之類的密鑰：放在環境變數，並寫進 `"requires": {"env": ["WEATHER_API_KEY"]}`。SYNOX 叫工具時會拿掉所有像密鑰的環境變數，
  **只放行 `requires.env` 列的名字**（沒列＝工具看不到）。
- 用到新版 SYNOX 才有的東西：寫 `"requires": {"synox": ">=0.3"}`，舊的 SYNOX 就不會載入它，並告訴使用者要更新。
- AI 呼叫你的指令時會等它做完、把結果交給 AI 轉述；所以一般指令要在 `timeout` 內做完，很久的工作請標 `"background": true`。
- 系統代換：`{python}`、`{node}`、`{pack_dir}`、`{data_dir}`、`{user_data_dir}`（伺服器版每人一個）、`{tg_id}`，argv、`env`、`cwd` 都可以用。
  Python 工具要用自己的 venv：`"cli": {"python": "venv"}`（＝`<pack>/../.venv`）或 `"runtime": {"python": "../.venv/Scripts/python.exe"}`（相對於 pack 資料夾）。
- **要第三方套件、又不想叫使用者自己裝**：寫 `"runtime": {"python": "auto", "python_posix": "auto"}`＋
  `"requires": {"pip": ["requests==2.32.3", "idna==3.7"]}`（一定要 `==` 釘死版本，相依的也要列，因為裝的時候用 `--no-deps`；只裝現成 wheel）。
  Node 工具寫 `"runtime": {"node": "auto"}`、argv 用 `{node}`，pack 裡放 `package.json`＋`package-lock.json`（`npm ci --ignore-scripts`）。
  使用者按確認安裝後 SYNOX 會在 `data/envs/<pack>/` 建好；失敗時 doctor 會說原因，修好後 `python -m synox packs env rebuild <pack>`。
  格式細節見 [pack-format.md](pack-format.md)「依賴與環境自動建置」。

## 給它一頁面板

在 `pack.json` 加：

```json
"web": {"panel": "panel.html", "api": ["GET /summary"]}
```

cli pack 的 `GET /summary` 由同名的 command 回答（要是 `READ`、沒有必填欄位；名字不同用 `"routes": {"summary": "today"}`）。
`panel.html` 是一頁純 HTML，用 `fetch("/api/packs/weather/summary")` 拿那個 command 印的 JSON。面板放在 sandbox iframe 裡，
但跟 Web UI 同源——它是「你決定要不要信任」的程式碼。`synox-sdk init` 會給你一份最小的範本。

## 工具：init、check、zip

```
synox-sdk init weather --kind cli --name weather --title "🌤 天氣"   產生 pack.json、SKILL.md、README.md、panel.html、tool.py（範例）
synox-sdk check weather                                             跑 SYNOX 安裝時的宣告檢查＋靜態掃描，列出每一個發現
synox-sdk zip weather                                               → dist/weather-0.1.0.synoxpack（算好 integrity.sha256）
```

（還沒有 `synox-sdk` 指令時：`.venv\Scripts\python.exe -m synox.sdk …`；專案裡也有 `scripts\pack_zip.py`。）

`--kind python` 產生的是 python pack：`pack.py` 的 `install(app, pack)` 直接在 SYNOX 裡面掛指令（見 [pack-format.md](pack-format.md)）。
它的程式碼會被靜態掃描：用到網路、子程序、pack 以外的檔案、動態執行，都要寫進 `capabilities`，不然拒裝。

## 給別人裝

把 `.synoxpack` 給對方。對方在 SYNOX 的網頁設定頁上傳，或（精靈裡勾過的話）**點兩下**檔案：
SYNOX 跑宣告檢查與靜態掃描、把報告給他看，他按「確認安裝」才裝，並把每個檔的雜湊寫進 `data/packs.lock`；
之後檔案被改過就不會載入。細節：[security.md](security.md) 的「五關」。

## 還沒做的

- `reply_confirm` 的按鈕來回：SYNOX 現在只顯示 `message`。要讓人按「確認」再呼叫一次（帶 `confirm_token`），之後再做；
  需要確認的動作現在請標 `effect: DANGER`，由 SYNOX 的確認卡在呼叫**之前**擋。
- `synox-sdk` 這個指令要重新 `pip install -e .` 才會出現（這台開發機沒有 `wheel`、不連網，所以還沒裝上；`python -m synox.sdk` 一樣能用）。
