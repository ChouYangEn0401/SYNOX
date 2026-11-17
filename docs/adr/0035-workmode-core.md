# ADR 0035：工作模式的核心——一個不依賴任何 host 的檔案（`workmode.py`）與它在 SYNOX 的掛點

- 日期：2026-11-17
- 狀態：**提案（契約定稿，還沒有程式）**。分支 `docs/core-unification-adr`。
- 基準：分支 `dev`，commit `86a930d`。文中的 `檔案:行號` 都是這個 commit 的。
- 來源：合一規劃（維護者的私有文件庫，2026-11-17）第 11.7 節。
- 前面：[0033](0033-work-protocol-work1.md)（工具回什麼）、[0034](0034-pack-agent-work.md)（工具怎麼宣告）。
  後面：[0036](0036-triangle-review.md)（挑錯者與驗證者）、[0037](0037-approval-cards-upgrade.md)（卡怎麼畫）、[0038](0038-wake-ai-after-card.md)（套用後叫醒 AI）。
- 程式（新）：`src/synox/agent/workmode.py`（純邏輯）、`src/synox/agent/workhost.py`（SYNOX 這一側的接線）。
- 測試：`tests/test_workmode_core.py`、`tests/test_workmode_host.py`、`tests/fixtures/workmode/*.json`。

## 背景

提示詞叫 AI「先查、再算、再給人看」沒有用：那次失誤裡 AI 知道規則，還是一筆一筆改了。要的是**程式強制的順序**。

SYNOX 的迴圈是自己跑的，每個工具呼叫都經過同一個函式（`AgentLoop._call_tool`，`src/synox/agent/loop.py:812`），所以掛一個地方就擋得住。
規則本身（什麼時候擋、擋下時說什麼、現在第幾步）跟 host 無關：把它寫成一個只用標準函式庫的檔，另一個 host 需要時可以原樣複製，
兩邊跑同一份驗收劇本。

## 決定

| # | 題目 | 決定 |
|---|---|---|
| 1 | 規則放哪 | `src/synox/agent/workmode.py`：只用標準函式庫、**不 import `synox`、`isdtelekit` 或任何 host**；沒有檔案讀寫、沒有時鐘（`now` 由呼叫端給）、沒有亂數。有一個測試檢查它的 import |
| 2 | 在哪裡跑 | 同一段對話，不另開規劃員的 session |
| 3 | 怎麼判定「這是批次改動」 | 結構判定，不靠模型：同一句話之內第 2 筆會改會刪的寫入，或新增與改／刪混在一起 |
| 4 | 擋什麼 | 五個閘門 G1–G5（下面）。只擋「這一類的批次寫入」；單筆改、單筆刪、只新增、無關的寫入不擋 |
| 5 | 套用 | 永遠在卡片後面（`auto_apply = "never"`） |
| 6 | 核對沒過 | 不自動退；列差異＋一鍵整批退回（`on_mismatch = "report"`） |
| 7 | 誰能關 | 只有人（`/work_off`）。AI 沒有任何工具能關掉工作模式 |
| 8 | 狀態 | 每個聊天、每種工作一份，放 `data/`、保管箱加密；閒置過期要明說 |

## 1. `workmode.py` 的契約

```python
STEPS = ("query", "plan", "check", "critic", "card", "apply", "verify", "report")
CRITIC_BOUNCES_MAX = 2        # 挑錯者最多退回幾次（提案值）
CRITIC_RUNS_MAX = 4           # 一件事最多叫幾次挑錯者（提案值）
REVERT_MINUTES = 30           # 「↩ 整批退回」按鈕留多久（提案值）

@dataclass(frozen=True)
class WorkSpec:                       # 來自 pack.json agent.work（ADR 0034）；名字都是 AI 看到的工具名
    pack: str; kind: str; title: str
    query: str; plan: str; show: str; apply: str; verify: str; revert: str
    check: str = ""
    batch: tuple[str, ...] = (); adds: tuple[str, ...] = ()
    replan_max: int = 2; plan_ttl_hours: int = 12; idle_hours: int = 12
    auto_apply: str = "never"         # 這一版只有 never
    on_mismatch: str = "report"       # 這一版只有 report

    @property
    def key(self) -> str: ...         # "<pack>.<kind>"

@dataclass(frozen=True)
class Action:                         # 「這一句話」之內的一筆寫入
    tool: str
    state: str                        # "done"（執行成功）｜"carded"（在卡上等人按）

@dataclass
class WorkState:                      # 一個聊天、一種工作一份；怎麼存由 host 決定
    chat: str; pack: str; kind: str; step: str; request: str
    plan_id: str = ""; fingerprint: str = ""; plan_expires: float = 0.0
    violations: tuple[tuple[str, str, str], ...] = ()     # (rule, where, say)
    unplaced: int = 0; waived: tuple[str, ...] = (); stale: bool = False
    replans: int = 0
    critic_plan: str = ""; critic_runs: int = 0; critic_rounds: int = 0
    critic_blocking: bool = False; critic_reached: bool | None = None
    open_faults: tuple[str, ...] = (); low_faults: tuple[str, ...] = ()
    batch_id: str = ""; verify: dict | None = None
    started: float = 0.0; touched: float = 0.0

@dataclass(frozen=True)
class Block:                          # 被擋下：給 AI 的一句話（含下一步）
    gate: str; say: str

def spec_for(specs, tool) -> WorkSpec | None           # 這個工具屬於哪一種工作（角色或 batch）
def detect(specs, actions, trying) -> str | None       # 結構判定；回 WorkSpec.key
def start(chat, spec, request, now) -> WorkState
def gate(state, spec, tool, args, actions, now) -> Block | None       # G1–G4；state 可以是 None
def advance(state, spec, tool, envelope, now) -> WorkState            # 工具回了信封（原始的，不是截短的）
def card_event(state, what, now) -> WorkState          # what: carded｜approved｜cancelled｜expired｜voided｜lost
def critic_due(state, spec) -> bool
def with_critic(state, high, low, reached, now) -> WorkState
def on_human(state, now) -> WorkState                  # 人說了新的一句：重算次數歸零
def status_line(state, spec) -> str                    # 「[工作模式：排程／重排｜第 3 步 檢查｜下一步 cal__plan_apply]」
def card_head(state, spec) -> list[str]                # 卡片最上面由系統寫的那幾行
def report(state, spec, verify_envelope) -> dict       # G5：{"ok", "headline", "diff_lines", "can_revert"}
def expired(state, spec, now) -> str | None            # 閒置過期：回一句要告訴人的話
def to_dict(state) -> dict
def from_dict(data) -> WorkState | None                # 看不懂＝None（當作沒有狀態）
```

### 1.1 「這一句話」是什麼

`actions` 由 host 給：**從這個人上一句話開始**，到現在為止，這個聊天裡 AI 做的每一筆寫入——包含被系統叫醒的那幾輪
（[0038](0038-wake-ai-after-card.md)）。人說了新的一句就清空。

只算「同一輪」不夠：核准卡執行完會叫醒 AI，它可以在叫醒的那一輪接著改下一筆；那在使用者眼裡還是同一件事。

### 1.2 結構判定 `detect`

對每個 `WorkSpec`，看 `actions` 裡 `tool` 在 `spec.batch` 的那幾筆，加上正要叫的 `trying`：

- 「會改會刪的」＝在 `batch`、不在 `adds`；「只新增的」＝在 `adds`。
- 成立的條件（任何一個）：會改會刪的 ≥ 2 筆；或同時有只新增的與會改會刪的。
- `adds` 是空的（工具沒宣告）＝`batch` 全部算會改會刪的：**第 2 筆就成立**。

只新增很多筆（例如排一整個月的新課表）不成立。

### 1.3 閘門

| 閘門 | 條件 | 回給 AI 的（`Block.say` 的樣板） |
|---|---|---|
| **G1** 批次要走方案 | `tool` 在 `spec.batch`，而且 `detect()` 成立 | 「這是批次改動（{title}）：不要一筆一筆改。先 {query} 看現況、再 {plan} 算方案、再 {apply}（會開一張卡給使用者）。」這句話之內已經有新增成功的，多一句「已經新增的 {n} 筆還在，方案會把它們算進去。」 |
| **G2** 有問題不開卡 | `tool` 是 `apply`，而且 `violations` 不是空的；或 `unplaced > 0` 且 `unplaced` 不在 `waived` | 逐條列（最多 6 條）；「改參數重算；改不掉就問使用者要放寬哪一條。」 |
| **G2** 重算太多次 | `tool` 是 `plan`，而且 `replans > replan_max` | 「這句話裡已經重算 {n} 次。把還剩的問題與選項告訴使用者，等他回答。」 |
| **G3** 方案要是這一份、要新鮮 | `tool` 是 `apply`，而且：沒有方案；`args` 的 `plan_id` 不是 `state.plan_id`；`stale`；或 `now >= plan_expires` | 「資料在你規劃之後變了（或方案過期了）：重新 {query}＋{plan}。」沒有方案時：「先用 {plan} 算方案，再用它回的 plan_id 套用。」 |
| **G4** 挑錯者有意見 | `tool` 是 `apply`，而且 `critic_blocking` | 挑錯者列的問題（最多 6 條）；「照這幾點重算。你認為它說得不對，就把理由告訴使用者，不要自己略過。」 |
| **G5** 完成要有核對 | `verify` 沒過 | **不擋回覆**。回覆最上面由系統加差異與退回按鈕（`report()`） |

- 判斷順序：G3 → G2 → G4（先確定是對的方案，再看它有沒有問題，最後才花錢挑錯）。
- G1 不看 `state`：有沒有進工作模式都同一條規則。所以工作模式中的「順便改一筆別的」照樣可以（那會讓方案變舊，G3 接住）。
- `Block.say` 只用樣板＋`spec` 的名字與 `state` 裡的字；樣板是程式裡的常數。
- 被擋下＝這次呼叫 `ok=False`：照舊算進「同一個呼叫連續失敗 3 次就停」（ADR 0012）。

**不擋的**：只新增、單筆改、單筆刪、不在 `batch` 裡的寫入。

### 1.4 步驟與轉移

`step` 是「現在停在哪」：

| `step` | 意思 | 怎麼進來 | `status_line` 的下一步 |
|---|---|---|---|
| `query` | 要先看現況 | G1 擋下時 `start()`；`apply` 回 `stale`；人打 `/work <kind>` | `{query}` |
| `plan` | 有現況，要算方案 | `query` 成功 | `{plan}` |
| `check` | 有方案 | `plan` 成功（AI 直接叫 `plan` 也算，那時 `start()` 之後直接到這一步） | 有違規＝`{plan}`（重算）；沒有＝`{apply}` |
| `critic` | 挑錯者退回了 | `with_critic()` 而且要退回 | `{plan}`（重算） |
| `card` | 卡開著，等人按 | `card_event("carded")` | 「等使用者按卡」 |
| `apply` | 人按了，正在套用 | `card_event("approved")` | — |
| `verify` | 套用成功，要核對 | `apply` 的信封成功 | — |
| `report` | 核對完了，回報 | `verify` 的信封回來（過不過都到這一步） | 「回報結果」 |

`advance()` 讀工具回的信封（[0033](0033-work-protocol-work1.md)）：

| 工具 | 信封 | 狀態怎麼變 |
|---|---|---|
| `query` | 成功 | 記 `fingerprint`、`stale = False`；`step` 是 `query` 時 → `plan` |
| `plan` | 成功 | 記 `plan_id`、`fingerprint`、`plan_expires`（`expires` 與 `now + plan_ttl_hours` 取早的）、`violations`、`unplaced`、`waived`（`loosened[].rule`）；之前已經有方案＝`replans += 1`；清掉 `open_faults`、`critic_blocking`；→ `check` |
| `check` | 成功 | 換掉 `violations` |
| `show` | 成功 | `fresh` 是 `false`＝`stale = True`；`state` 是 `expired`＝`plan_expires = now` |
| `apply` | 成功 | 記 `batch_id` → `verify` |
| `apply` | `stale` | `stale = True` → `query` |
| `apply` | `plan_expired`、`violations`、`not_found` | → `plan`（要重算） |
| `apply` | `already_applied` | 記 `data.batch_id` → `verify` |
| `apply` | `busy` | → `check`（方案還在，可以再開一次卡） |
| `apply` | `apply_failed` | → `check`；`report()` 會照實說 |
| `apply` | `rollback_failed` | → `report`；`report()` 用紅字說資料停在半路。之後 `apply` 一律被 G3 擋（要重新 `query`） |
| `verify` | 任何 | `verify = data`（叫不動＝`None`）→ `report` |
| 其他工具 | — | 只更新 `touched` |

`card_event`：`cancelled`、`expired`、`voided`、`lost`（重開之後卡不見了）都回到 `check`——方案還在，可以再開一次卡。

### 1.5 挑錯者（跟 [0036](0036-triangle-review.md) 的接口）

- `critic_due(state, spec)`：有方案、這份方案還沒看過（`critic_plan != plan_id`）、`critic_runs < CRITIC_RUNS_MAX`。開不開三角審查由 host 決定，不在這裡。
- `with_critic(state, high, low, reached, now)`：`critic_plan = plan_id`、`critic_runs += 1`、`critic_reached = reached`、
  `open_faults = high`、`low_faults = low`。`high` 不是空的而且 `critic_rounds < CRITIC_BOUNCES_MAX`＝`critic_rounds += 1`、`critic_blocking = True`、`step = "critic"`；否則不退回。
- 所以：前 2 次有嚴重問題會退回給 AI 重算；第 3 次起照樣開卡，問題寫在卡片最上面，由人決定。

### 1.6 系統寫的字

`card_head(state, spec)`（卡片最上面，照這個順序；每行都是樣板＋資料）：

1. `waived` 的每一條：「⚠ 這次放寬了：{say}」（`say` 來自工具的 `loosened[]`）。
2. `unplaced` 被放寬時：「⚠ 有 {n} 筆排不進去，這次先不管。」
3. `open_faults`：「⚠ 挑錯者指出、還沒解決：{where}：{why}」（最多 5 行，多的併成「…另有 N 點」）。
4. `low_faults`：「💬 挑錯者提醒：…」（最多 3 行）。
5. `critic_reached is False`：「（這次沒有挑錯：叫不動）」；達到 `CRITIC_RUNS_MAX`：「（這次沒有挑錯：已達上限）」。

`report(state, spec, verify_envelope)`：

| 情況 | `ok` | `headline` | `diff_lines` | `can_revert` |
|---|---|---|---|---|
| 核對過了 | `True` | 「🔎 套用後核對：{matched}/{total} 筆對上、範圍內沒有多的、規則檢查 0 條」 | `[]` | `True` |
| 核對沒過 | `False` | 「⚠ 套用後核對沒過：{matched}/{total} 筆對上」 | 差異最多 6 行（少的、多的、不一樣的、違規的各自的 `show`），多的併成「…另有 N 筆」 | `True` |
| 核對叫不動 | `False` | 「⚠ 已經套用，但核對叫不動（沒有核對）」 | `[]` | `True` |
| `apply_failed` | `False` | 「❌ 套用到第 {failed_step} 步失敗，已經整批還原，資料沒有變。」 | `[]` | `False` |
| `rollback_failed` | `False` | 「🛑 套用到第 {failed_step} 步失敗，而且還原也失敗：資料停在半路，請自己檢查。」 | `[]` | `False` |

`expired(state, spec, now)`：`now - touched > idle_hours`＝回「上次那件「{title}」停在第 {n} 步，超過 {h} 小時沒動，已經收掉了。要重來嗎？」；否則 `None`。

## 2. 在 SYNOX 的掛點（`agent/workhost.py`）

| 掛點 | 做什麼 |
|---|---|
| `AgentLoop._call_tool`（`loop.py:812`）：第 4 關與必填檢查之後、`needs_card` 之前 | `workhost.before_call()`：找 `spec_for`、組 `actions`、叫 `workmode.gate()`。被擋＝回 `(Block.say, False, False)`。G1 擋下而還沒有狀態＝`start()` |
| 同上，`tool` 是 `apply` 而閘門放行 | 核心自己叫 `check`（有宣告的話）與 `show` → `advance()` → 再過一次 `gate()`（G2／G3 用最新的結果）→ `critic_due()` 而且三角審查開著＝叫挑錯者（[0036](0036-triangle-review.md)）→ `with_critic()` → 再過 `gate()`（G4）→ 都過了才開卡 |
| `AgentLoop.tool_result`（`loop.py:872`） | `workhost.after_call()`：拿工具回的**原始信封**叫 `workmode.advance()` |
| `agent/prompt.py` 第 7 層（本輪規則那一層、時間那一行之前） | 每個進行中的狀態一行 `status_line()`。每行上限 160 字，不算進 `TURN_RULES_MAX`，context 預算不截它（跟固定守則同一個待遇） |
| `agent/toolpick.py` 的永遠保留清單 | 有進行中的狀態時，那個 `WorkSpec` 給 AI 的六個工具（`query`、`plan`、`check`、`show`、`apply`、`verify`）一定在這一輪的清單裡 |
| `agent/approve.py` | `apply` 的卡（[0037](0037-approval-cards-upgrade.md)）：內容來自 `show`、最上面是 `card_head()`、期限到 `plan_expires`。按 ✅ → 以人的身分再 authorize → 執行 `apply` → 成功就叫 `verify` → `report()` → 結果訊息 → 叫醒 AI（[0038](0038-wake-ai-after-card.md)） |
| 人說了新的一句（`run_turn`） | `actions` 清空、每個進行中的狀態 `on_human()`；`expired()` 有回字的＝收掉狀態、把那句話放在這一輪回覆的最上面 |

核心自己叫 `check`／`show`／`verify` 的規則：

- 以**卡片主人**的身分叫，來源標 `system`（ADR 0025 §2），照常過 `policy.decide`。被拒＝當作叫不動。
- 只叫 READ 的角色。`apply` 與 `revert` 只在人按了按鈕之後才叫。
- 叫不動（逾時、失敗信封、被拒）：`check`＝用方案自己帶的 `violations`；`show`＝**不開卡**，回 AI「讀不到方案，重新 {plan}」；`verify`＝`report()` 的「核對叫不動」。

原始信封：`CaptureApi` 要留著工具回的最後一個信封（完整的 `data`，在截短給 AI 之前）。給 AI 結構化結果的那個實作分支如果已經提供就用它的；
沒有就在工作模式的 PR 加 `capture.envelope`。**工作模式讀的一律是這一份，不是 AI 看到的那一份。**

### 結果訊息與退回按鈕

按 ✅ 之後送給人的那一則（系統寫的，不經過 AI）：

```
✅ 已套用：{summary}（{applied}/{steps} 步）
🔎 套用後核對：26/26 筆對上、範圍內沒有多的、規則檢查 0 條
[↩ 整批退回]
```

- 「↩ 整批退回」綁在核心的節點 `work.revert`（DANGER、不給 AI）：`registry.bind_callback("work_rv:", "work.revert", …)`。
  按的時候先以按的人 authorize `work.revert`，再對**工具的 `revert` 指令** authorize 一次（via=BUTTON），通過才叫，`force=false`。
- 期限 `REVERT_MINUTES`（30 分鐘，不超過 SDK 對危險按鈕的 `button_ttl`）。過期按了回「⌛ 過期了，沒有退回」。之後要退：自己打工具的退回指令。
- 退回的結果也是系統寫的：「↩ 已退回 {reverted} 筆」＋`skipped` 最多 6 行＋「（這幾筆之後又被改過，沒有動）」。退回之後叫醒 AI 一次。

### 狀態怎麼存

- `data/work/<使用者>.json`（保管箱開著＝`.json.enc`，用那個人自己的金鑰；跟通知清單同一套）。內容：`{記憶鍵: {WorkSpec.key: to_dict(state)}}`。
  記憶鍵＝`AgentLoop.memory_key()`（網頁的每一段對話各自一份）。
- 每個聊天每種工作最多一份進行中的狀態；同一種的新狀態取代舊的。
- 重開 SYNOX：核准卡只在記憶體，重開就沒了。讀到 `step` 是 `card` 或 `apply` 的狀態＝`card_event("lost")`，下一輪開頭由系統說
  「上次那張卡因為 SYNOX 重開作廢了；方案還在，要再開一次卡嗎？」
- `/data/work/` 要在 `.gitignore`。

### 指令

系統群組 `work`（跟提醒、排程同一種登記），整組**不給 AI**（`ai=False`），只給這段對話的主人：

| 指令 | 做什麼 |
|---|---|
| `/work` | 列出這個聊天進行中的每一件：哪一種、第幾步、方案編號、卡開著沒、還剩多久過期 |
| `/work_off [kind]` | 收掉（沒給 `kind`＝全部）。開著的卡一起作廢。不退回任何已經套用的東西 |

指令名由路徑產生（SDK 的規則），所以是 `/work_off`，不是 `/work off`。

## 不做的事

- **另開一段乾淨的 session 當規劃員**：不做。哪天本機小模型的脈絡不夠用再回來看。
- **只新增很多筆時的檢查**：這一版不擋、也不事後檢查（見最後一節的待決定）。
- **用模型判定「這句話是不是批次工作」**：不做。只有結構判定與人自己開。
- **自動套用、自動退回**：`auto_apply`、`on_mismatch` 這一版各只有一個值；欄位留著是為了之後不改格式。
- **縮小工具清單**（工作模式中只給那幾個工具）：這一版只保證那六個一定在；不拿掉別的。
- **跨聊天共用狀態**：Telegram 開的事不會在網頁的另一段對話裡繼續。
- **`workmode.py` 不碰卡片、不叫模型、不讀寫檔**：那些都在 `workhost.py`。

## 測試怎麼寫

### 共用劇本（`tests/fixtures/workmode/*.json`，跟 host 無關）

```json
{"name": "incident_strict",
 "specs": [{"pack": "cal", "kind": "schedule", "title": "排程／重排",
            "query": "cal__event_query", "plan": "cal__plan_make", "check": "cal__plan_check", "show": "cal__plan_show",
            "apply": "cal__plan_apply", "verify": "cal__plan_verify", "revert": "cal__plan_revert",
            "batch": ["cal__cal_add", "cal__cal_edit", "cal__cal_del"], "adds": []}],
 "now": 1000,
 "steps": [
   {"human": "把沒看完的往後排"},
   {"call": {"tool": "cal__cal_add", "args": {}}, "expect": {"gate": null}, "result": {"ok": true}},
   {"call": {"tool": "cal__cal_add", "args": {}},
    "expect": {"gate": "G1", "say_has": ["cal__event_query", "cal__plan_make", "cal__plan_apply"], "step": "query"}},
   {"tick": 60}
 ]}
```

一步是下面其中一種：`human`（新的一句）、`call`（AI 想叫什麼；`expect.gate` 是 `null` 或閘門名；放行的帶 `result`＝工具回的信封）、
`critic`（`{"high": […], "low": […], "reached": true}`）、`card`（`carded`｜`approved`｜`cancelled`｜`expired`｜`lost`）、
`tick`（時間往前幾秒）、`expect_status`（`status_line` 要含的字）、`expect_report`（`report()` 的 `ok` 與 `headline_has`）、
`expect_expired`（`expired()` 要含的字或 `null`）。

`tests/test_workmode_core.py` 用純函式重放每一份劇本。至少要有：

| 劇本 | 驗什麼 |
|---|---|
| `incident_strict` | 事故重演（連叫 12 次新增＋幾次刪除），`adds` 沒宣告：第 2 筆被 G1 擋，回的字有下一步的三個工具名 |
| `incident_adds_declared` | 同一串呼叫，`adds` 有宣告：新增放行，第 1 筆刪除被 G1 擋，回的字說「已經新增的 N 筆還在」 |
| `add_only` | 連續新增 20 筆：全部放行、沒有進工作模式 |
| `single_edit` | 一句話只改一筆：放行。下一句再改一筆：放行（`human` 清空了 `actions`） |
| `woken_turn_counts` | 第 1 筆改在卡上（`carded`），沒有新的 `human`，叫醒後再改一筆：G1 擋 |
| `happy_path` | query → plan（沒違規）→ apply 放行 → carded → approved → apply 成功 → verify 過 → `report.ok` |
| `violations_block` | plan 有違規 → apply 被 G2 擋 → 重算（帶 `waive`）→ `card_head` 有「這次放寬了」 |
| `unplaced_block` | `unplaced > 0` 沒放寬＝G2；放寬了＝放行、`card_head` 有那一行 |
| `replan_limit` | 同一句話重算超過 `replan_max`：`plan` 被 G2 擋；`human` 之後又可以算 |
| `stale` | apply 回 `stale` → `step` 回 `query`；沒重新規劃就再叫 apply＝G3 |
| `plan_expired` | 時間過了 `plan_expires`：apply 被 G3 擋 |
| `wrong_plan_id` | `args.plan_id` 不是最新那一份：G3 |
| `critic_bounce_twice` | 挑錯者連三次有嚴重問題：前兩次 G4 擋，第三次放行、`card_head` 有「還沒解決」 |
| `critic_low_only` | 只有輕微問題：不擋、`card_head` 有「提醒」 |
| `critic_unreachable` | `reached=false`：不擋、`card_head` 有「這次沒有挑錯：叫不動」 |
| `verify_mismatch` | verify 少兩筆：`report.ok` 是 `false`、`diff_lines` 兩行、`can_revert` |
| `verify_unreachable` | verify 的信封是 `null`：「核對叫不動」 |
| `apply_failed` | `apply_failed`：`can_revert` 是 `false`、headline 說已經整批還原 |
| `card_cancelled` | 取消／過期／lost：回到 `check`，可以再 apply |
| `idle_expired` | 閒置超過 `idle_hours`：`expired()` 回的字有工作名與第幾步 |
| `reconcile` | 對帳那一類（`query` 與 `plan` 同一個工具、沒有 `check`）：整條走得完 |

另外的單元測試：

1. `workmode.py` 的 import 只有標準函式庫（用 `ast` 讀原始碼檢查：每個 import 的頂層模組都要在 `sys.stdlib_module_names` 裡，所以 `synox`、`isdtelekit` 和任何 host 的套件都擋得下）。
2. `to_dict`／`from_dict` 來回一樣；壞掉的 dict＝`None`。
3. `status_line` 每一步都在 160 字內；`Block.say`、`card_head`、`report` 的字裡沒有來自 `args` 的任何內容。
4. 同樣的輸入叫兩次結果一樣（沒有時鐘、沒有亂數）。

### host（`tests/test_workmode_host.py`；假的 CLI 工具＋真的 `app.build`，不叫真的模型、不執行外部程式）

1. 假工具照 [0033](0033-work-protocol-work1.md) 回信封（用黃金檔）；`FakeAdapter` 照劇本叫工具。
2. 事故重演：第 2 筆批次寫入拿到 G1 的字、沒有執行；AI 那一輪的記憶裡有這一句。
3. 有違規：AI 叫 `apply` → 沒有卡。
4. 沒問題：AI 叫 `apply` → 一張卡：內容是 `show` 的 `changes[].show`、最上面是 `card_head`、期限是方案的。
5. 按 ✅：以人的身分 authorize；執行；核心自己叫了 `verify`；結果訊息最上面是 `report` 的 headline；有「↩ 整批退回」。
6. 核對沒過：結果訊息有差異行；AI 被叫醒的那一輪拿到同一份核對結果。
7. 按「↩ 整批退回」：叫的是工具的 `revert`、`force=false`；30 分鐘後按＝過期；別人按＝「這不是你的按鈕」。
8. `stale`：按 ✅ 時工具回 `stale` → 結果訊息說「資料變了，沒有套用」→ 叫醒 AI → 狀態回到 `query`。
9. 核心叫 `show` 叫不動：不開卡。
10. `status_line` 出現在第 7 層；把 context 預算壓到很小時它還在。
11. 每輪工具數上限開著（`llm.max_tools = 3`）：工作模式中那六個工具都在。
12. 狀態存在保管箱的密文裡；重開（重新 `app.build`）後 `step=card` 的狀態變成 `check`，下一輪開頭有那句話。
13. `/work`、`/work_off`：AI 的工具清單裡沒有它們；`/work_off` 之後舊卡按了＝過期。
14. 閒置過期：下一輪回覆最上面有 `expired()` 那句。
15. 伺服器版：成員甲的狀態成員乙讀不到、`/work` 只列自己的。

## 跟規劃不一樣的地方

| 規劃 | 這份 | 為什麼 |
|---|---|---|
| `detect(specs, pending_actions)`：「同一輪」第 2 筆 | `actions` 的範圍是「這一句話」（含被叫醒的那幾輪） | 核准後會叫醒 AI；只算同一輪的話，它可以一輪改一筆繞過去 |
| 沒有 `adds` | 「會改會刪的」與「只新增的」分開算 | 見 [0034](0034-pack-agent-work.md) |
| `WorkState` 沒有 `violations`、`unplaced`、`plan_expires`、`stale`、挑錯者那幾欄 | 加上 | G2／G3／G4 要有東西可以判斷；`gate()` 是純函式，不能自己去問工具 |
| `gate` 一個函式做完 | 多 `spec_for`、`start`、`card_event`、`critic_due`、`with_critic`、`on_human`、`card_head`、`to_dict`／`from_dict` | 卡片、挑錯者、新的一句、存檔都會改狀態；都放在純函式裡，另一個 host 才能原樣用 |
| G2 只管 `apply` | 也管「重算太多次」與「排不進去的」 | 規劃第 4 節的步驟表有這兩條，閘門表漏了 |
| `/work off` | `/work_off` | SDK 的指令名由路徑產生 |
| 狀態「每個聊天一份」 | 每個聊天、每種工作一份 | 排程排到一半順便對帳，兩件事不該互相蓋掉 |
| 「↩ 整批退回」綁在哪沒寫 | 核心節點 `work.revert` 再轉給工具的 `revert` | 一個按鈕前綴只能綁一個節點（SDK 的規則） |

## 待決定（給擁有者；不答就照建議）

| 題目 | 選項 | 建議 |
|---|---|---|
| 只新增很多筆（`adds` 有宣告時）要不要也管 | **A** 不管（這一版）。**B** 一句話新增 2 筆以上時，這一輪結束由核心叫一次 `check`（帶那幾筆），有 ⚠ 就由系統寫在回覆最上面。**C** 超過幾筆就擋下、要走方案 | **A**，下一階段做 **B**。C 需要工具的 `plan` 能從零排新東西，現在的排程方案只會搬既有的 |
