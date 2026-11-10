---
name: hello
description: 使用者想算含小費的總額，或想跟某人打招呼時使用（synox_sdk 的最小範例）。
---

# 👋 範例

## 什麼時候用
- 「1200 元加 15% 小費多少」→ `hello__tip`：amount=1200、percent=15。參數：amount（帳單金額，必填）、percent（小費幾 %，預設 10）、round_up（要不要進位到整數）
- 「跟 Amy 打個正式的招呼」→ `hello__greet`：name=Amy、style=formal。參數：name（要打招呼的人，必填）、style（casual 或 formal）

## 注意
- 參數名就是欄位名；值一律是字串（SYNOX 會先檢查格式）。
