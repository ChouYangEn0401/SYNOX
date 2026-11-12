# 常駐助理／心跳／任務狀態的網頁 API（runtime API）

給**主控面板**（前端）用的合約。後端在 `src/synox/runtime/`，網頁入口在 `src/synox/web/server.py` 轉給
`src/synox/runtime/web_api.py`。設計與理由見 [adr/0001-runtime-loop-heartbeat-mother-session.md](adr/0001-runtime-loop-heartbeat-mother-session.md)。

## 共同規則（跟其他 `/api/...` 一樣）

- **只給擁有者**（`registry.is_owner`）。沒登入 → `401`；登入了但不是擁有者 → `403`。伺服器版的成員、管理員也一樣是 `403`。
- 非 GET（`POST`、`PUT`）一律要帶 `X-SYNOX-CSRF: <GET /api/me 的 csrf>`；有 `Origin` 的話要跟 `Host` 一樣。缺 → `403`。
- 送出的 body 是 JSON 物件（`Content-Type: application/json`）；不是 JSON → `400`，不是物件 → `400`。
- 回應都是 JSON。錯誤一律 `{"error": "<一句給人看的話>"}`（狀態碼 400／401／403／404／405／503）。
- **時間**一律 ISO 8601、帶時區（本機時區，例如 `2026-11-12T14:30:00+08:00`），還沒發生過＝`null`。
- 沒有啟用 runtime（不會發生在正常的 SYNOX；只有測試或裝壞了）→ `503 {"error": "…"}`。
- 下面的範例都是**佔位資料**。

## `GET /api/runtime/status`

整體狀態：心跳、常駐助理、所有任務。

```json
{
  "heartbeat": {
    "enabled": true,
    "interval_min": 45,
    "last_run_at": "2026-11-12T14:30:00+08:00",
    "next_run_at": "2026-11-12T15:15:00+08:00",
    "last_result": "巡過了，沒有要通知你的事。",
    "min_interval_min": 15,
    "max_interval_min": 1440,
    "quiet_hours": "23:00-08:00"
  },
  "mother": {
    "state": "idle",
    "ai": true,
    "last_active_at": "2026-11-12T14:30:04+08:00",
    "soul_updated_at": "2026-11-10T21:02:11+08:00"
  },
  "tasks": [
    {"id": "system.heartbeat", "name": "心跳（常駐助理巡一次）", "owner": "system", "schedule": "每 45 分鐘",
     "state": "ok", "last_run_at": "2026-11-12T14:30:00+08:00", "last_message": "巡過了，沒有要通知你的事。"},
    {"id": "system.schedule", "name": "提醒與排程", "owner": "system", "schedule": "每 30 秒",
     "state": "ok", "last_run_at": "2026-11-12T14:59:30+08:00", "last_message": "沒有到點的項目"},
    {"id": "pack.weather", "name": "🌤 天氣", "owner": "weather", "schedule": "自己回報",
     "state": "failed", "last_run_at": "2026-11-12T13:02:00+08:00", "last_message": "API 回 503"}
  ]
}
```

| 欄位 | 說明 |
|---|---|
| `mother.ai` | 有沒有設定 AI 來源（`false`＝設定頁選了「先不用 AI」，這時 `state` 一定是 `off`；到設定頁存好 AI 來源就立刻變 `true`，不用重開） |
| `heartbeat.enabled` | 心跳開著沒（`config.json` 的 `runtime.heartbeat.enabled`，預設 `true`） |
| `heartbeat.interval_min` | 幾分鐘巡一次（預設 45） |
| `heartbeat.last_run_at` | 上一次巡的時間；從沒巡過＝`null` |
| `heartbeat.next_run_at` | 下一次預定的時間；關掉、或 SYNOX 只開了終端機模式（沒有跑排程迴圈）＝`null` |
| `heartbeat.last_result` | 上一次的結果，一句給人看的話；從沒巡過＝`null` |
| `heartbeat.min_interval_min`、`max_interval_min` | **合約外多給的**（前端可以不用）：間隔的上下限，表單可以拿來做檢查 |
| `heartbeat.quiet_hours` | **合約外多給的**：安靜時段（`"HH:MM-HH:MM"`，空字串＝沒有），這段時間巡了也不通知 |
| `mother.state` | `"idle"`（在、閒著）｜`"running"`（正在巡）｜`"off"`（沒有 AI 可用，或 `runtime.mother.enabled=false`） |
| `mother.last_active_at` | 常駐助理上一次真的叫 AI 的時間；`null`＝沒叫過 |
| `mother.soul_updated_at` | soul.md 上一次被改（你改或助理追加）的時間；`null`＝還是預設內容 |
| `tasks[]` | 每個登記的任務。順序：系統的在前（`system.*`），再來 pack 回報的（`pack.*`），各自照 id 排 |
| `tasks[].id` | `system.<名字>` 或 `pack.<pack 名>`；只有 `[a-z0-9._-]`，最多 64 字 |
| `tasks[].owner` | `"system"` 或 pack 名 |
| `tasks[].schedule` | 一句給人看的話：`"每 30 秒"`、`"每 45 分鐘"`、`"關閉"`、`"自己回報"` |
| `tasks[].state` | `"ok"`｜`"running"`｜`"failed"`｜`"idle"`（登記了還沒跑過、或關掉了） |
| `tasks[].last_message` | 最後一則訊息（最多 200 字）；沒有＝`null`。重開 SYNOX 後是 `null`（訊息只在記憶體） |

## `POST /api/runtime/heartbeat`

改心跳設定，**存進 `config.json`、馬上生效**（不用重開）。

body（兩個都可以省略；省略＝不改）：

```json
{"enabled": true, "interval_min": 60}
```

- `enabled`：布林。
- `interval_min`：整數，`15`～`1440`（分鐘）。超出、不是整數（`45.5`、`"45"`）→ `400 {"error": "間隔要是 15～1440 的整數（分鐘）。"}`。
- 有其他鍵 → 忽略。

回應 `200`：新的 heartbeat 物件（跟 `status` 裡的 `heartbeat` 一樣）：

```json
{"enabled": true, "interval_min": 60, "last_run_at": "2026-11-12T14:30:00+08:00",
 "next_run_at": "2026-11-12T15:30:00+08:00", "last_result": "巡過了，沒有要通知你的事。",
 "min_interval_min": 15, "max_interval_min": 1440, "quiet_hours": "23:00-08:00"}
```

改間隔之後，下一次＝上一次巡的時間＋新間隔（已經過了就是一分鐘後）；從沒巡過＝現在＋新間隔。

## `POST /api/runtime/heartbeat/run-now`

馬上巡一次（在背景跑，**不等它做完**）。心跳關著也可以按（手動的那一次不看安靜時段）。body 可以是空的 `{}`。

```json
{"ok": true, "message": "開始巡了，做完會更新「上一次的結果」。"}
```

正在巡（上一次還沒做完）：

```json
{"ok": false, "message": "正在巡，等它做完再按。"}
```

兩種都是 `200`；前端看 `ok` 決定顯示成功還是提示。做完之後再 `GET /api/runtime/status` 看 `heartbeat.last_result`。

## `POST /api/runtime/mother/reset-memory`

清空常駐助理自己的記憶（它過去巡的紀錄）。**不動 soul.md**、不動對話助理的記憶。

```json
{"ok": true}
```

## `GET /api/runtime/soul`

```json
{"text": "# soul.md\n\n## 偏好\n- …\n", "updated_at": "2026-11-10T21:02:11+08:00"}
```

`updated_at` 是 `null`＝還是預設內容（沒改過）。

## `PUT /api/runtime/soul`

body：

```json
{"text": "# soul.md\n\n## 偏好\n- 早上不要吵我\n"}
```

- `text` 一定要是字串，最多 6000 字；超過 → `400`。
- **空字串（或只有空白）＝重設**成預設內容（四個空的段落）。
- 內容看起來像密鑰（API key、bot token、私鑰…）→ `400 {"error": "內容看起來有密鑰（…），soul.md 會送給 AI，不能放。"}`。
- 換行一律存成 `\n`。

回應 `200`：

```json
{"ok": true, "text": "# soul.md\n\n## 偏好\n- 早上不要吵我\n", "updated_at": "2026-11-12T15:01:00+08:00"}
```

## `GET /api/runtime/tasks/<id>/log`

那個任務最近的日誌（最多 200 行，舊的在前）。`<id>` 跟 `tasks[].id` 一樣。

```json
{"lines": [
  "2026-11-12T14:30:00+08:00 開始",
  "2026-11-12T14:30:04+08:00 ok 巡過了，沒有要通知你的事。"
]}
```

- 沒有這個 id → `404 {"error": "沒有這個任務。"}`。
- 日誌只在記憶體（重開 SYNOX 就清掉）；每行最多 300 字，像密鑰的片段換成 `***`。

## 不在這個合約裡（之後要加先改這份）

- 暫停／恢復單一任務、刪掉 pack 回報的任務。
- 改安靜時段、每天最多通知幾次（現在只能改 `config.json`）。
- 即時推送（現在前端自己輪詢 `status`；建議 15～30 秒一次，畫面不在前景就停）。
