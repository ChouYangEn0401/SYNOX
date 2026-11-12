# 兩台 SYNOX 連線（Link）：主控台派任務、哨兵做事

> 🧪 **實驗品（experimental）**。擁有者 2026-11-12 的方向：SYNOX 核心維持空殼、指令盡量少，所以 link **不算核心的一部分**，
> 之後很可能整包搬出去成獨立套件（或 pack），也可能拿掉。config.json 沒開 `link` 時它完全不存在（沒有指令、沒有執行緒、沒有檔案）。
> 它只碰核心的幾個介面，清單在下面「要搬出去時」。
>
> 另外這一塊**還沒在真機上跑過**（只在開發機用記憶體傳輸、socketpair 與 127.0.0.1 的 TCP 驗過）。
> 調查與設計的來龍去脈：[discussions/2026-11-12-link-architecture.html](discussions/2026-11-12-link-architecture.html)；
> 實作現況、沒做的、要擁有者決定的：[discussions/2026-11-12-link-implementation.html](discussions/2026-11-12-link-implementation.html)。

一台 SYNOX 當**主控台**（console），其他台當**哨兵**（worker）。你在主控台的 Telegram 打 `/link_run 客廳 /note 買牛奶`，
客廳那台就以**它自己擁有者**的身分跑 `/note 買牛奶`，把回覆送回來；做完主控台通知你。可以重做、交給另一台（交接）、取消。

**安全的部分跟走哪條路無關**：每一封信都是端對端加密＋簽章的「信封」（X25519 ＋ ChaCha20-Poly1305 ＋ Ed25519，
每封換金鑰、有重放防護），傳輸層只搬密文。所以同一套東西可以走區域網路 TCP、共用資料夾（NAS／Syncthing／USB），
之後也可以走 MQTT、序列埠（Arduino）而不用改安全這一層。沒有伺服器、沒有第三方服務、不碰公網。

## 三步接起來

1. **兩台的 `config.json` 各加一塊 `link`**（改完重開 bot）：

   ```json
   "link": {"enabled": true, "role": "console", "name": "主控台",
            "transport": {"kind": "tcp", "listen": "0.0.0.0:8831"}}
   ```
   ```json
   "link": {"enabled": true, "role": "worker", "name": "客廳",
            "transport": {"kind": "tcp", "connect": "192.168.1.10:8831"}}
   ```
   哨兵**主動連**主控台，所以只有主控台要開一個埠（而且只建議開在區域網路／WireGuard 裡，見下面）。
   沒辦法開埠？用共用資料夾（兩邊都寫 `{"kind": "folder", "dir": "Z:/synox-link"}`，不用開任何埠）。

2. **配對**（配對碼是祕密，**不經聊天**，只在兩台電腦上貼）：
   ```
   主控台電腦：  python -m synox link pair             → 印一行 SYNOX-PAIR-1:…（10 分鐘內有效、只能用一次）
   哨兵電腦：    python -m synox link join "<那一行>"
   ```
   兩台的 bot 都在跑的話，幾秒內就配好（主控台 log 會寫 `paired worker`；`/link_status` 看得到 🟢）。
   沒有網路、或想完全手動：`python -m synox link card` 印名片，對方 `python -m synox link trust "<名片>" --role worker`（兩邊都做）。

3. **派任務**（在主控台的 Telegram）：

   | 打 | 做什麼 |
   |---|---|
   | `/link_status`、`/link_peers` | 這台的角色、名單、誰在線（兩邊都有） |
   | `/link_run <哨兵> <指令…>` | 派一個指令（哨兵可以寫名字或 node_id 前幾碼）；做完通知你 |
   | `/link_tasks`、`/link_task <編號>` | 最近的任務、一個任務的回覆全文 |
   | `/link_redo <編號>` | 同一台再做一次（新任務，歷史不動） |
   | `/link_handoff <編號> <哨兵> [新指令…]` | 交給另一台，帶著上一個任務的結果（交接） |
   | `/link_cancel <編號>` | 取消（對方已經開始做就會做完，但結果不記） |
   | `/link_forget <哨兵>` | 從名單拿掉（它寄來的信從此不收） |

   有接 AI 的話直接說「叫客廳那台記一筆買牛奶」也行（`/link_run` 是 AI 看得到的工具；哨兵那邊照樣過它自己的關）。

## 哨兵會做什麼、不會做什麼

- 只收**名單上 role=console** 那台的任務；名單外的信直接丟掉（不回任何東西）。
- 指令要在哨兵的指令樹上、不能是群組或互動式（會問問題的）指令。
- `effect_of(args)`（read／write／danger，包著別的指令的連裡面一起算）**不能超過哨兵 `link.max_effect`**（預設 `write`：
  刪全部筆記這種 DANGER 指令預設不接；真的要就在哨兵的 config 寫 `"max_effect": "danger"`）。
- 再過一次 `policy.decide(哨兵的擁有者, via=ROUTINE)`：跟排程觸發走同一個 authorize。
- 跑的時候走 `dispatcher.handle`，跟你在哨兵那台打字一模一樣；回覆全部收起來當結果送回。出按鈕的指令會說「按鈕不能隔著 link 按」。
- 同時最多 4 個任務；一個任務最多 `link.task_timeout` 秒（預設 120）等 cli pack 的背景工作。
- 主控台那邊**是誰下的任務，哨兵不管也不信**：信任的邊界是名單（配對），不是人。

## 設定全部欄位

| 欄位 | 預設 | 說明 |
|---|---|---|
| `enabled` | false | 開關 |
| `role` | console | `console`（派任務）｜`worker`（做任務） |
| `name` | 主機名 | 名片上的名字（1–40 字） |
| `transport.kind` | tcp | `tcp`｜`folder` |
| `transport.listen` | 127.0.0.1:8831 | 主控台（tcp）聽哪裡；`0.0.0.0:8831` 才對區域網路開 |
| `transport.connect` | — | 哨兵（tcp）連哪裡 |
| `transport.dir` | — | folder：兩台都看得到的資料夾（每台一個子資料夾 `<dir>/<node_id>/`） |
| `max_effect` | write | 哨兵接受的最高效果 |
| `task_timeout` | 120 | 哨兵：一個任務最多等幾秒 |
| `heartbeat` | 30 | 幾秒送一次心跳（0＝不送；folder 傳輸建議 0 或調大，不然每 30 秒多一個小檔） |
| `poll` | 2 | folder：每幾秒看一次資料夾 |

## 安全邊界（老實說）

- **信封**：X25519（一次性＋長期）→ HKDF → ChaCha20-Poly1305，Ed25519 簽章；`to`／`seq`／`ts` 都在 AAD 裡，改一個字就驗不過。
  重放：ts ±5 分鐘、同一寄件者 seq 只能往上（兩邊都存在保管箱，重開不會倒退）、視窗內同一封不收兩次。兩台的時鐘要大致對。
- **金鑰**：私鑰、名單、任務簿都在保管箱（`data/link_*.json.enc`）。拿到 `data/` 的人等於拿到這台（跟現在一樣）。
- **TCP 沒有 TLS**：因為信封本身已經端對端加密，TLS 只會多一層憑證要管。但沒驗過的連線能做的只有「送一堆被丟掉的東西」，
  所以對外聽的埠**只建議開在區域網路或 WireGuard 裡**，不要直接開到公網（可以撐，但沒必要）。
- **配對碼**：拿到 10 分鐘內有效的碼的人，能以哨兵身分進名單（主控台之後可能派任務給它）；它拿不到主控台的資料、也不能對主控台下指令。
  碼只在自己的電腦貼、不要傳進聊天（Telegram 看得到聊天）。
- **主控台被攻破＝所有哨兵都聽它的**（在 `max_effect` 之內）。主控台要是你最信任的那台。
- 沒做的：NAT 穿透、公網 relay、MQTT／序列埠傳輸、任務的中途進度（哨兵現在只回最後結果）、per-哨兵的指令白名單
  （只有 `max_effect`）、Windows 實機驗證。清單在 [AGENT.md](AGENT.md)「Known limitations」。

## 要搬出去時（切面）

`src/synox/link/` 只從 SYNOX 拿這幾樣，搬成獨立套件就是把這幾條線接回去：

| link 用到 | 在哪 | 搬出去時 |
|---|---|---|
| 保管箱 `Vault.load_json／save_json／exists` | `app.extras["vault"]` | 任何「存 JSON、保完整性」的東西都行 |
| 指令樹 `registry.ensure_group／leaf`、`loader.group_policy` | `commands.py` | 變成 pack 的話改用 pack.json 宣告指令 |
| `app.dispatcher.handle` ＋ `Inbound(channel="link")`、`policy.decide(via=ROUTINE)` | `roles.py` 哨兵跑指令 | 這是唯一真的要核心配合的點（同一個 authorize） |
| `app.notify`、`app.on_start／on_stop`、`app.extras` | `__init__.py`、`roles.py` | 主動通知與生命週期 |
| `SynoxConfig.from_dict` 解析 `link` 區塊、doctor 一行、`__main__` 的 `link` 子指令 | 核心各一處 import | 拿掉這四個 import，核心就乾淨了 |

核心其他地方不 import `synox.link`。信封、身分、名單、配對、傳輸、事件匯流排（`envelope／identity／peers／pairing／transport／bus`）
完全不依賴 SYNOX，可以原封搬走。

## 跟 IoT（攝影機、Arduino、樹莓派）的關係

硬體掛在**哨兵**身上、當成那台的 pack：攝影機（`cv2.VideoCapture`／樹莓派 `picamera2`）、Arduino（`pyserial`＋Firmata）、
GPIO（`gpiozero`）都是哨兵上的 kind=cli 或 kind=python 工具；主控台不用懂硬體，只會 `/link_run 門口 /cam_snap`。
樹莓派上跑 SYNOX 哨兵就是一台普通的 Linux 哨兵（程式本身跨平台；安裝器只有 Windows，手動 `pip install -e .` 即可）。
細節與建議的套件在調查文件。
