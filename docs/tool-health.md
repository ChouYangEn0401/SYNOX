# 工具健康：失敗信封與隔離清單

工具（pack）壞掉時，SYNOX 記得「哪個工具壞了、為什麼、可以怎麼補救」，並且**暫時不給 AI 用**，免得 AI 一直叫、一直失敗、白花 token。
程式在 `src/synox/health/`；工具作者那一側是 SDK 的 `fail()`（[sdk.md](sdk.md)「fail()」）。

**這一版不做自動修復**：失敗信封裡的補救建議只寫出來給人看，SYNOX 不執行任何補救動作（重新檢查以外）。

## 一張圖

```
工具失敗 ──▶ 失敗信封 v1（正規化、截長、遮密鑰）──▶ AI 收到固定格式的一行；人看到原因（多一行類別與建議）
                                         └──▶ 隔離清單：同一個根因連續 N 次 → 暫停；工具自己說要人處理 → 立刻停
暫停的工具 ──▶ 不在給 AI 的工具清單（系統提示最後一行原因）──▶ 冷卻到了：pack.json 的自我檢查（不叫 AI）──▶ 過了放回
```

## 失敗信封 v1

在原本的 JSON 信封上多一個 `failure` 物件（舊版 SYNOX 看不懂就忽略；舊工具沒有它，SYNOX 依類別碼補預設值）：

```json
{"ok": false, "error": "資料來源的回傳格式變了，解析不出價格。", "code": "upstream_changed",
 "failure": {"v": 1, "scope": "tool", "retry": {"ok": false, "after_s": null},
             "remedy": {"kind": "needs_update", "id": "upgrade", "summary": "要換成 1.3.0 以上的版本。"},
             "diag": {"tool_version": "1.2.0", "upstream": "KeyError: 'price'"}}}
```

| 欄位 | 說明 |
|---|---|
| `error` | 給人看的原因，**最多 300 字** |
| `code` | 穩定的類別碼（下表）；不認得的一律 `unclassified`。SDK 舊版的 `usage`／`bad_value`＝`bad_input`、`internal`＝`unclassified`、`spec`＝`internal_bug` |
| `failure.scope` | `input`（參數錯）｜`user`（只跟這個人有關，例如他的憑證）｜`tool`｜`pack`｜`environment`。**只有後三種算進門檻**；`user` 只記在那個人身上 |
| `failure.retry` | `ok`（能不能重試）、`after_s`（知道要等多久才帶） |
| `failure.remedy` | `kind`：`auto_fixable`｜`needs_update`｜`needs_config`｜`needs_owner`｜`none`；`id`：短代號（`[a-z0-9_]{1,32}`）；`summary`：人話。**看起來像指令的整段丟掉**（命令列、管線、網址、程式碼），換成固定的一句「請看工具說明。」 |
| `failure.diag` | 只給擁有者與 log 看，**不進 AI 的提示**、不存檔；每個值最多 200 字、整包最多 1 KB |

所有文字欄位先過 `synox.packs.kit.TOKEN_PATTERNS`（跟 log 遮罩同一份：`sk-…`、`Bearer …`、Telegram bot token…）再存、再顯示。

### 類別碼表（`health/failure.py` 的 `CODES`）

| 碼 | 預設 scope | 預設可重試 | 算進門檻 | 預設補救 |
|---|---|---|---|---|
| `bad_input` | input | 否 | 否 | none |
| `not_found` | input | 否 | 否 | none |
| `needs_config` | pack | 否 | 是 | needs_config |
| `config_invalid` | pack | 否 | 是 | needs_config |
| `auth_missing` | user | 否 | 否（只記在那個人） | needs_config |
| `auth_expired` | user | 否 | 否（只記在那個人） | needs_config |
| `permission_denied` | user | 否 | 否（只記在那個人） | needs_owner |
| `rate_limited` | environment | 是 | 否 | none |
| `network_unreachable` | environment | 是 | 是 | none |
| `upstream_unavailable` | tool | 是 | 是 | none |
| `upstream_changed` | tool | 否 | 是 | needs_update |
| `dependency_missing` | pack | 否 | 是 | needs_update |
| `dependency_outdated` | pack | 否 | 是 | needs_update |
| `unsupported_platform` | environment | 否 | 是 | needs_owner |
| `resource_exhausted` | environment | 是 | 是 | needs_owner |
| `timeout` | tool | 是 | 是 | none |
| `internal_bug` | tool | 否 | 是 | needs_update |
| `unclassified` | tool | 否 | 是 | none |

SYNOX 自己推的：cli 叫不起來（結束碼 -1）＝`dependency_missing`、子程序逾時＝`timeout`、沒有 JSON＝`unclassified`；
kind=python 丟的例外＝`unclassified`（SDK 的 `ToolFailure`／`ToolError` 照它的碼）；MCP 連線出錯＝`upstream_unavailable`／`timeout`。

### AI 收到什麼

一行、最多 300 字、不含金鑰、不含 diag：

```
FAIL <類別碼> retry=<yes|no|after Ns> | <人話原因> | 下一步：<SYNOX 依類別碼產生的建議>
```

「下一步」由 SYNOX 產生（`CODES[碼].next`），**不採用工具自己的文字**（避免工具結果夾帶指令）。整行照舊包在這一輪的分隔符裡（第 5 關）。
給人看的訊息照舊是「❌ 指令：原因」，認得的類別再多一行（類別、補救建議、幾秒後可以再試）。

## 隔離清單

| 狀態 | 意思 | 給 AI | 怎麼回來 |
|---|---|---|---|
| `healthy` | 正常 | ✅ | — |
| `broken` | 同一個根因連續失敗，冷卻中 | ❌ | 冷卻到了自動重新檢查；人手動成功一次 |
| `needs_action` | 工具自己說要人處理（設定、憑證、更新） | ❌ | 擁有者在網頁按「重新檢查」；人手動成功一次。**不自動檢查** |
| `quarantined` | 24 小時內好壞反覆太多次 | ❌ | **只有擁有者能解除**（網頁「解除隔離」） |

- **指紋**＝pack＋指令＋類別碼＋工具版本＋正規化後的上游錯誤（`diag.upstream`，沒有就用原因；去掉數字、路徑、時間、長的十六進位）。
  同一個根因只累加次數；只存雜湊。
- **門檻**：同一指紋連續 3 次，或 10 分鐘內 5 次（中間成功也算進這 5 次）→ `broken`。沒有宣告合約（沒有 `failure` 物件）的工具與匯入的工具（kind=mcp）連續 2 次。
  工具自己明說 `needs_config`、`dependency_missing`、`auth_expired`，或 `remedy.kind` 寫 `needs_update` → 立刻 `needs_action`（`health.trust_self_report=false` 可以關掉）。
  SYNOX 自己推的碼（例如叫不起來＝`dependency_missing`）不算「工具明說」。
- **冷卻**：300、900、3600、21600、86400 秒依序拉長（自我檢查沒過、試用失敗就進下一段；放回之後再壞，從比較長的那段開始）；
  24 小時內第 3 次壞掉 → `quarantined`。
- **重新檢查**：runtime 任務 `system.health`（每 60 秒看一次，**不另開執行緒**）。只用 pack.json 宣告的自我檢查
  `"health": {"check": "<這個 pack 裡的一個唯讀指令名>"}`（[pack-format.md](pack-format.md)），走既有的工具執行路徑（`ProbeApi`：
  同步、有工具自己的逾時、什麼都不送給使用者），**過程不叫 AI**。沒有宣告自我檢查的工具：冷卻結束後放回清單**試用一次**
  （24 小時內最多 4 次），成功就放回、失敗進下一段冷卻。
- **給 AI 的工具清單**：拿掉不給 AI 的工具，系統提示最後最多加 5 行「暫時不能用的功能：<指令>（<原因>）」——原因是 SYNOX 依狀態與類別碼產生的字。
  AI 硬叫被拿掉的工具＝直接回那一行，不執行。
- **人自己打指令**（Telegram／Discord／網頁）：這一版照常執行，只在前面多一行「⚠️ 這個工具目前…」；成功就算一次重新檢查通過。
  （kind=python 的 pack 人打字那條路還沒接：只有 AI 呼叫時的例外會記。）
- **權限判斷不變**：能不能用一個工具仍然只由 `policy.decide` 決定；健康狀態只管「現在好不好」。
- **fail open**：健康管理器自己出錯、存檔讀不開、設定關掉 → 所有工具一律當成正常（記 log）。

## 存檔

`data/health/tools.json.enc`，**經保管箱加密**（`Vault.at(data/health)`，跟 pack 資料同一把主金鑰）。只存狀態、類別碼、次數、時間、
指紋雜湊與截短（120 字、遮過密鑰）的原因；diag 不存。沒有保管箱＝只在記憶體。讀不開（金鑰不對、檔案壞掉）＝這次執行一律當作沒有紀錄、
**也不寫回去**（照保管箱的規則：解不開絕不當成空的再蓋過去）；doctor 會說，擁有者處理後重開。

## 設定（`config.json` 的 `health`，選填）

```json
"health": {"enabled": true, "consecutive": 3, "window_count": 5, "window_s": 600, "untrusted_consecutive": 2,
           "cooldowns_s": [300, 900, 3600, 21600, 86400], "flip_limit": 3, "flip_window_s": 86400,
           "daily_trials": 4, "prompt_lines": 5, "trust_self_report": true, "check_interval_s": 60}
```

沒寫＝上面的預設值。寫錯（型別、範圍、`cooldowns_s` 沒有越來越長、不認得的鍵）＝啟動時一句清楚的錯誤（`ConfigError`）。
檢查在 `src/synox/health/settings.py`。

## 在哪裡看

- `python -m synox doctor`：「• 工具健康」一段，每個不正常的工具一行（狀態、類別碼、原因、下次檢查時間）。只讀，不產生金鑰。
- 網頁「工具」頁：每張指令卡有狀態徽章與原因（文字一律 `textContent`）；擁有者看得到「重新檢查」「解除隔離」／「標成正常」
  （`POST /api/tools/health {"key", "action": "recheck"|"release"}`，要 CSRF header、只有擁有者）。成員只看得到整個工具的狀態與自己的。

## 不做的事（之後的任務）

自動修復、讓 AI 觸發修復、自動更新或重建環境；通知（推播「某工具壞了」）、指標儀表板、斷網合併、MCP 伺服器重啟上限、多機匯總、
安裝時的作者規範檢查。
