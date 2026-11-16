# ADR 0029：工具登記與索引（pack.json 的 `agent` 區塊、相依、系統層同一個登記口）

- 日期：2026-11-16
- 狀態：已採用（分支 `feat/core-w3-register`）
- 程式：`src/synox/agent/index.py`（新）、`src/synox/packs/manifest.py`（`parse_agent`、`required_packs`／`required_system`、
  `agent_trust_problem`）、`loader.py`（相依順序與檢查、第三方的 `agent.always`、結尾彙整）、`scan.py`（安裝報告那一段）、
  `upgrade.py`（`agent_changes`、第三方拒升級）、`admin.py`（安裝與核准時對信任）、`agent/toolpick.py`（觸發字加分、
  `keep_for`／`pick_for`，拿掉寫死的 `SYSTEM_PREFIXES`）、`agent/skills.py`（主題檔、`topic` 參數）、`agent/validate.py`
  （`skill_read` 收 `topic`）、`doctor.py`（`agent_lines`）、`sdk/__init__.py`（新工具骨架帶 `agent` 區塊）
- 測試：`tests/test_agent_index.py`、`tests/test_toolpick.py`
- 文件：[pack-format.md](../pack-format.md)「`agent` 區塊」「`requires.packs`／`requires.system`」

## 背景

AI 的系統提示裡「已裝的功能」「技能」兩段是每輪從工具清單直接拼出來的：每個工具一行 summary、每個 SKILL.md 一行 description。
它有三個缺口：

1. **沒有上限**：工具越裝越多，固定提示跟著變長；本地小模型的脈絡先被它吃掉。
2. **工具沒辦法說「什麼時候找我」**：summary 是給人看的 /help 標題，不是給 AI 的路由；使用者說「午餐花了 120」時，
   本地模型每輪只給 12 個工具，靠字面相似挑，挑不到記帳工具。
3. **系統層各自寫死**：提醒的工具名開頭寫死在挑工具的程式裡（`toolpick.SYSTEM_PREFIXES = ("remind__",)`），
   系統群組另外一份（`loader.SYSTEM_GROUPS_KEY`）；外掛與核心是兩套規則。
   另外，「哪個指令成功之後 AI 可以說『會…』」沒有地方宣告，承諾把關（之後的工作）沒有資料可讀。

先前的聊天機器人用過「群組索引一行＋要用才載入工具規格＋說明書按需讀」的分層做法（索引有字數上限、超過逐級縮短每行），
效果很好；它的弱點是登記靠寫程式掛、路由行靠人手寫進固定提示，沒有「裝一個工具 → 索引自動多一行」。

## 決定

1. **pack.json 新增選填的 `agent` 區塊**：`index`（一行、60 字內）、`triggers`（≤12 個、每個 ≤12 字）、
   `load`（`on_trigger` 預設｜`on_call`｜`always`）、`skill.file`／`skill.topics`（說明書與主題檔）、`provides`（能力代號）、
   `promises`（指令 → `schedule`｜`watch`）、`always`（≤200 字，每輪進提示）。規則與範例在 pack-format.md。
   給 AI 看的字（`index`、`triggers`、`always`）跟 `commands[].ai.scenario` 同一套檢查（不准網址、信箱、像在下指令、要跳過確認、分隔符）。
   安裝時寫錯＝拒裝；已裝的寫壞了＝那一項當作沒寫（跟 `category`、`health`、`help` 同一個原則：新欄位不讓舊工具突然載不起來）。
2. **`requires.packs`、`requires.system`**：相依的工具（含版本條件，寫法同 `requires.synox`）與系統能力。
   loader 先讀完全部 pack.json，被依賴的排在前面載入；缺了（沒裝、版本不合、自己沒載入成功）或系統能力不在＝狀態 `missing`、
   detail 說缺什麼。格式寫錯＝pack.json 不合（兩種模式都是：相依靜默消失比載不起來更危險）。
3. **索引**：`load_all` 結尾呼叫 `agent.index.build`，每項一筆 `Entry`（名稱、標題、那一行、觸發字、載入方式、
   指令與危險程度、說明書主題、`promises`、`always`、每輪佔用、pack.json 雜湊）。記憶體一份（`app.extras`），
   `data/agent_index.json` 一份（健康檢查、網頁）。沒寫 `agent` 區塊的工具＝summary 當那一行、沒有觸發字、`on_trigger`。
4. **總量上限 1,500 字**：能力清單超過就把每行說明照 60 → 40 → 28 → 20 → 12 → 0 逐級縮短；只剩標題還超過，才把最後幾行
   併成「…另有 N 項」。每個人看到的清單照群組權限過濾（同 `loop.visible_packs`）。固定守則不在索引裡，不受影響。
5. **系統層走同一個登記口**：`index.register_system(app, name, title=…, index=…, group=…, triggers=…, load=…, promises=…)`。
   出廠的提醒、排程、通知在系統層自己的程式還沒登記之前用 `CORE_ENTRIES` 補上（`ensure_core`，登記過的以登記的為準）。
   `toolpick` 不再寫死 `remind__`：永遠保留的開頭問索引（`keep_for(app)`＝`load: always` 的項目＋`SYSTEM_GROUPS_KEY` 的群組）。
6. **觸發字進挑工具的分數**：`pick(…, triggers=)` 對命中觸發字的工具加一個大的分數（排在只靠字面相似的前面，仍受每輪上限）；
   `pick_for(app, …)` 一次帶好 keep 與觸發字。
7. **主題檔**：`skill_read` 在有工具宣告主題時多一個選填的 `topic` 參數，只讀那一章；沒有任何主題時規格跟以前一模一樣。
8. **信任**：`agent.always` 與 `load: always` 每輪都進提示，**只給系統層與信任選「核心（core）」的工具**。
   第三方寫了：安裝（`admin.install_staged`、`approve_installed`）、升級（`upgrade_staged`）都拒；
   沒鎖、手放的當作第三方（跟 `sandbox.trust_of` 同一條規則），載入時狀態 `rejected`。
9. **承諾**：`promises` 只能指向宣告過的指令；`index.promised_tools(app)` 給承諾把關讀。升級時新增或改了承諾、
   新加或改了 `always`、`load` 改成 `always`＝升級報告紅字。
10. **報告與健康檢查**：安裝報告多一段「🧠 給 AI 的登記」（每輪會多佔約 N 字、那一行、觸發字、承諾、要核心信任的紅字）；
    doctor 列能力清單總量、每個工具的佔用（最大的三個標出來）、缺的相依、第三方的 `always`。
11. **新工具骨架**：`synox-sdk init`（含 `--from`）產生的 pack.json 帶一個 `agent` 區塊（`index` 待改、`triggers` 空、`on_trigger`）。

## 給提示用的介面（`agent/index.py`）

| 函式 | 回什麼 |
|---|---|
| `lines_for(app, user, packs=None, limit=1500)` | 這個人看得到的能力清單（每項一行，已縮短到上限內） |
| `prompt_block(app, user, packs=None)` | 上面那幾行加一個標題（沒有東西＝`""`） |
| `always_lines(app, user, packs=None)` | 每輪都要的那幾段（`agent.always`） |
| `keep_prefixes(app)`／`toolpick.keep_for(app)` | 挑工具時永遠保留的工具名開頭 |
| `trigger_map(app)` | `{工具名開頭: [觸發字]}` |
| `promised_tools(app)` | `{工具名: schedule｜watch}` |
| `system_names(app)` | 這台有的系統能力 |

## 為什麼這樣做

- **選填、舊工具不變**：工具庫的工具要一個一個補，不能要求同一天全部改；沒寫的照 summary，挑法照舊。
- **字數上限放在索引、不放在固定守則**：守則被截掉的後果（AI 不知道要先確認）比少看幾個字的工具說明嚴重。
- **`always` 綁信任**：每輪進提示的字等於改了 AI 的行為守則；第三方工具能寫，就等於能改守則。
- **相依在載入時擋、不在安裝時擋**：被依賴的工具可能之後才裝；安裝報告只列出來，載入時才知道齊不齊。

## 已知代價與後續

- kind=python 的指令寫在程式裡，`promises` 安裝時只能看名字格式，載入後才對得到；對不到的那一條丟掉並記 log。
- 對話迴圈（`agent/loop.py`）的提示與挑工具還是舊的寫法：換成 `index.prompt_block`／`always_lines`、`toolpick.pick_for`、
  `skill_read` 傳 `topic` 由提示分層的工作接手。在那之前，觸發字只在呼叫 `pick_for` 的地方生效、`topic` 參數不會傳到 `read_skill`。
- 網頁的安裝報告畫面還沒畫「🧠 給 AI 的登記」那一段（資料已經在報告的 `agent` 欄位）。
