# ADR 0013：工具說明精簡化：pack.json 的 commands[].ai.scenario（EasyTool）

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/small_model_harness`）
- 依據：研究交接書前 8 項的第 5 項（卡片 D1）
- 程式：`src/synox/agent/tools.py`（`description(node, app)`、`scenario_of`）、`src/synox/packs/manifest.py`（`scenario_problem`、`scenario_of`、`ai_problems`）、`src/synox/packs/loader.py`（`synox_tool_meta[path]["scenario"]`）、`src/synox/sdk/author.py`（`@tool(scenario=)`，SDK 0.2.2）

## 決定

1. pack.json 的 `commands[].ai` 除了 `true`／`false`，也收 `{"scenario": "一句話"}`（＝給 AI，附使用情境）。
   第 1 關：一行、120 字內；不准夾網址、信箱、像在對 AI 下指令（忽略／改掉規則）、要跳過確認、分隔符
   （沿用 `runtime/ledger.py` 的 `risk_flags` 規則，只取這幾類；「提到寄送／執行」不算，工具本來就做這些事）。
   載入時寬鬆：壞的 scenario 當作沒寫。
2. 有 scenario 的工具，給 AI 的說明＝「{summary}。情境：{scenario}。」，危險的加「需使用者確認（系統會先送確認卡）。」；
   **不放「人打的用法」**（那是給 /help 的）。
3. **沒寫 scenario＝說明一個字都不變**（含人打的用法）。所以既有的 pack、雲端來源的結果都不變；作者加了 scenario 才換成精簡說明，
   而且這是對所有 AI 來源都一樣（說明是工具的屬性，不看 adapter）。
4. SDK：`@tool(..., scenario="")` 產生 `"ai": {"scenario": …}`；`ai=False` 時不寫 scenario。只加 API，所以
   `SDK_VERSION` 升 **PATCH**（0.2.1 → 0.2.2），`requires.sdk` 範圍不變。

## 跟規格不同

- 規格寫「SDK_VERSION 升 MINOR」。docs/sdk.md 的政策是「只加 API＝0.x 升 PATCH」；升 MINOR 會讓所有寫著
  `requires.sdk: ">=0.2,<0.3"` 的既有工具裝不上、載入不了。所以升 PATCH。
- 規格寫「拿掉人打的用法」對所有工具；為了向後相容，只對寫了 scenario 的工具拿掉。
- python pack（自己 `install()` 掛節點）與 MCP 工具沒有 commands[]，維持原本的說明。

## 還沒做

- SYNOX_Libs 裡每個工具的 pack.json 還沒補 scenario（另一個 repo）；9b 前後對照（pass 數、平均 prompt tokens）要人工、夜間跑。
