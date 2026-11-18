# ADR 0034：pack.json 的 `agent.work`——工具宣告「我支援批次改動」

- 日期：2026-11-17
- 狀態：**提案（契約定稿，還沒有程式）**。分支 `docs/core-unification-adr`。
- 基準：分支 `dev`，commit `86a930d`。
- 來源：合一規劃（維護者的私有文件庫，2026-11-17）第 11.5 節。
- 前一份：[0033](0033-work-protocol-work1.md)（七個角色各回什麼）。下一份：[0035](0035-workmode-core.md)（核心怎麼用這份宣告把關）。
- 會動到的程式：`src/synox/packs/manifest.py`（`AGENT_KEYS`、`parse_agent`）、`loader.py`（載入後對指令、把 `revert` 設成不給 AI）、
  `upgrade.py`（`agent_changes`）、`scan.py`（安裝報告那一段）、`agent/index.py`（彙整成 `WorkSpec`）、`sdk/`（`synox-sdk check`）。
- 文件：實作 PR 更新 [pack-format.md](../pack-format.md) 的「`agent` 區塊」。

## 背景

[0033](0033-work-protocol-work1.md) 規定了七個角色，但沒有規定指令叫什麼。核心要知道三件事：

1. 這個工具的哪個指令扮哪個角色；
2. 哪些指令是「一筆一筆改」的（AI 連續叫它們時要擋下來、改走方案）；
3. 幾個數字（重算幾次、方案留多久、閒置多久算過期）。

`agent` 區塊（[0030](0030-tool-registration-index.md)）本來就是「工具給 AI 的登記」，所以放在那裡。

## 決定

1. `agent` 區塊多一個選填的鍵 `work`：一個清單，一項是一種批次工作。
2. **只會多擋、不會放行**：權限仍然只有 `policy.decide`（invariant 11）。宣告 `agent.work` 不會讓任何指令變得更容易被叫到。
3. 第三方工具可以宣告（不需要「核心」信任）：它只能點名**自己的**指令。
4. 安裝時（第 1 關）檢查名字與 effect；不合＝拒裝。已經裝著的寫壞了＝那一項當作沒寫、工具照樣載入（跟 `agent` 其他欄位同一條規則）。
5. `revert` 的指令載入時一律設成不給 AI；`apply` 的指令一定要給 AI（呼叫＝開卡）。

## 契約

```json
"agent": {
  "work": [{
    "kind": "schedule", "title": "排程／重排", "protocol": "work/1",
    "query": "event_query", "plan": "plan_make", "check": "plan_check", "show": "plan_show",
    "apply": "plan_apply", "verify": "plan_verify", "revert": "plan_revert",
    "batch": ["cal_add", "cal_edit", "cal_del"], "adds": ["cal_add"],
    "replan_max": 2, "plan_ttl_hours": 12, "idle_hours": 12
  }]
}
```

| 欄位 | 必 | 規則 |
|---|---|---|
| `kind` | ✅ | `^[a-z][a-z0-9_]{0,23}$`；同一個工具裡不重複。核心用「工具名＋`kind`」認一種工作，所以不同工具可以用同一個 `kind` |
| `title` | ✅ | 給人與 AI 看的名字：一行、24 字內，過 `agent.index` 同一套文字檢查（不准網址、信箱、像在對 AI 下指令、分隔符） |
| `protocol` | | 只收 `"work/1"`；沒寫＝`work/1`。不認得的值＝拒（之後有 `/2` 時，舊版 SYNOX 才不會誤用） |
| `query`、`plan`、`show`、`apply`、`verify`、`revert` | ✅ | 這個工具宣告過的指令名（`COMMAND_RE`）。`query` 與 `plan` 可以同名；其他五個彼此不能同名，也不能跟 `query`／`plan` 同名 |
| `check` | | 同上；沒寫＝核心用方案自己帶的 `violations` |
| `batch` | ✅ | 「一筆一筆改」的指令名清單：1–16 個，不能是上面七個角色的任何一個 |
| `adds` | | `batch` 的子集：**只新增、不改也不刪**的指令。沒寫＝`[]`（`batch` 裡每一個都當成會改會刪，最嚴） |
| `replan_max` | | 0–5 的整數，預設 2：同一句話之內 AI 最多重算幾次 |
| `plan_ttl_hours` | | 1–72，預設 12：核准卡的期限上限（工具回的 `expires` 比較早就用它的） |
| `idle_hours` | | 1–72，預設 12：這件事多久沒動就收掉 |

不認得的鍵＝拒（訊息列出認得的）。整個 `work` 最多 4 項。

### 第 1 關檢查（`manifest.parse_agent`，嚴格模式＝拒裝）

1. 每個名字都是這個工具宣告過的指令：kind=cli 對 `commands`、kind=mcp 對 `tools_allow`（用 `declared_commands`）。
   kind=python 的指令寫在程式裡：安裝時只看名字格式，**載入後**對不到＝那一項整個丟掉並記 log（同 `agent.promises`）。
2. effect：
   - `apply`、`revert`＝`DANGER`；
   - `query`、`plan`、`check`、`show`、`verify`＝`READ`；
   - `batch` 的每一個＝`WRITE` 或 `DANGER`。
   kind=cli 讀 `commands[].effect`，kind=mcp 讀 `mcp.effects`；kind=python 載入後讀節點的 effect。
3. `apply` 的指令不可以寫 `"ai": false`（寫了＝拒：AI 叫不到就開不了卡）。也不可以寫 `"confirm": true`（核心已經會開卡，不要兩層）。
4. `revert` 的指令：pack.json 寫 `"ai": true` 或沒寫都**不算錯**；載入時 loader 一律把它設成不給 AI，安裝報告寫一行「↩ 退回只能由人按」。
5. `adds` ⊆ `batch`。

### 載入之後

- `agent/index.py` 把每個載入成功的工具的 `work` 彙整成 `WorkSpec`（[0035](0035-workmode-core.md)）：指令名換成 AI 看到的工具名
  （`<群組>__<指令>`，`tools_mod.SEP`），多一個 `pack`（工具名）。入口：`index.work_specs(app) -> tuple[WorkSpec, ...]`。
- `AGENT_DEFAULT` 多 `"work": []`；沒宣告的工具完全不受影響。
- 被停用、沒載入、被隔離（工具健康）的工具，它的 `WorkSpec` 不在清單裡——那時它的 `batch` 指令本來就叫不到。

### 安裝報告與升級報告

安裝報告「🧠 給 AI 的登記」多一段：

```
🛠 批次改動：排程／重排
   AI 連續改好幾筆時會被要求先算方案，再給你一張卡；套用後會自動核對，可以整批退回。
   算方案：plan_make　套用：plan_apply（⚠ 危險）　退回：plan_revert（只能由人按）
   一筆一筆改的指令：cal_add、cal_edit、cal_del
```

升級報告（`upgrade.agent_changes`）：

| 改了什麼 | 字 |
|---|---|
| 新增一項 `work`、`batch` 多了指令、數字變小（更嚴） | 一般字 |
| **拿掉一項 `work`、`batch` 少了指令、`adds` 多了指令**（把關變鬆） | 紅字 |
| `apply`／`revert`／`plan` 換成另一個指令 | 紅字 |
| `replan_max`、`plan_ttl_hours`、`idle_hours` 變大 | 一般字 |

### `synox-sdk check`

多跑上面第 1 關的五項；kind=python 只檢查格式並提醒「名字要載入後才對得到」。

## 不做的事

- **不收跨工具的名字**：一項 `work` 只能點名自己這個工具的指令。
- **不讓 `agent.work` 影響權限、能力、信任等級**：宣告了也不會多一個能力，不需要「核心」信任。
- **不在這裡宣告習慣的鍵**（`agent.prefs` 是另一份 ADR 的事）。
- **不支援 kind=connector、kind=theme**（它們沒有指令）。
- **不自動猜**：沒宣告 `agent.work` 的工具，核心不會因為它的指令名字像 `plan`／`apply` 就當它支援。

## 測試怎麼寫

`tests/test_agent_work_manifest.py`（暫存資料夾、假的 pack.json、不執行任何程式）：

1. 合格的宣告：`parse_agent` 回的 `work` 一項、欄位補了預設值、`adds` 沒寫＝`[]`。
2. 逐項壞掉各一個案例，問題訊息要點名欄位：指令不存在；`apply` 是 WRITE；`plan` 是 WRITE；`batch` 裡有 READ 的；`batch` 裡有角色指令；
   `adds` 不在 `batch` 裡；`kind` 重複；`protocol` 是 `work/2`；少 `show`；`apply` 寫了 `"ai": false`；多了不認得的鍵；超過 4 項；`replan_max` 是 9。
3. `query` 與 `plan` 同名＝合格（對帳那一類）；`show` 與 `plan` 同名＝拒。
4. 嚴格模式（安裝）有問題＝拒裝；非嚴格（已裝的）＝那一項丟掉、工具照樣載入、其他 `agent` 欄位不受影響。
5. kind=python：安裝時只看格式；載入後有一個名字對不到＝那一項丟掉、log 一行。
6. 載入後 `revert` 的節點不在 AI 的工具清單裡（即使 pack.json 寫 `"ai": true`）；`apply` 的節點在。
7. `index.work_specs(app)` 回的工具名是 `<群組>__<指令>`；停用的工具不在裡面。
8. 升級報告：拿掉 `work`、`batch` 少一個、`adds` 多一個＝alert；新增 `work`＝一般字。
9. 第三方信任（不是 core）的工具宣告 `agent.work`＝裝得進來（跟 `agent.always` 不一樣）。
10. `tests/test_pack_docs.py` 那一類的文件測試：pack-format.md 的範例 JSON 過 `parse_agent`。

## 跟規劃不一樣的地方

| 規劃 | 這份 | 為什麼 |
|---|---|---|
| 七個角色都要寫 | `check` 選填 | 見 [0033](0033-work-protocol-work1.md)：對帳沒有獨立的檢查 |
| 沒有 `adds` | 多一個選填的 `adds` | 規劃同時說「只新增不擋」與「新增混刪改要擋」，核心要分得出哪個指令是新增。沒寫就是最嚴（第 2 筆就擋） |
| 沒有 `protocol` | 多一個選填的 `protocol` | 之後有 `work/2` 時舊版要能拒絕 |
| 沒寫升級報告 | 把關變鬆＝紅字 | 跟 `callers`／`stepup`「只能收緊，放寬要標紅」同一個原則（ADR 0025） |
