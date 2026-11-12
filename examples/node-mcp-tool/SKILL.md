---
name: node-mcp-tool
description: 使用者想知道一段文字有幾個字、幾行，或想擲骰子時使用（Node 寫的 MCP 工具範例）。
---

# 🎲 Node MCP 範例

## 什麼時候用
- 「這段話有幾個字」→ `nodemcp__count_words`：text＝那段文字（必填）
- 「擲兩顆骰子」→ `nodemcp__roll_dice`：times=2；要別的面數給 sides（2 到 100，預設 6）

## 注意
- 參數名就是欄位名；值一律是字串（SYNOX 會先照工具的 inputSchema 檢查格式）。
- 骰子結果是隨機的，不要自己編數字，照工具回的轉述。
