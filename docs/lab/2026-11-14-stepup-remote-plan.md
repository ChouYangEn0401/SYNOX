# 門禁核心、手機驗證器、手機入口：實作計畫（一條線做到底，含工具服務的八包）

- 狀態：**待處理**（提案；[ADR 0025](../adr/0025-guard-core-and-stepup.md)、[ADR 0026](../adr/0026-remote-tool-apps.md) 等擁有者核准。核准前不動 `src/`）
- 寫的時間：2026-11-14（分支 `feat/remote-access`，基準 `dev` 的 `6b4253c`）
- 讀者：**一個**實作的 session，照下面 S1→S15 的順序一包一包做（擁有者要求：一個 session 依序做，不要一次開很多代理）。手上只有這份文件、兩份 ADR、工具服務的 ADR 與計畫、repo。
- 相關：工具服務＝分支 `feat/tool-apps` 的 `docs/adr/0023-tool-apps-services.md`（第三版）與 `docs/lab/2026-11-14-tool-apps-implementation-plan.md`。
  **注意**：寫這份的時候，那份計畫還停在第二版（用 cookie 進門），ADR 已經是第三版（不用 cookie、交接票）。動手前先看那個分支最新的計畫；兩邊不一致時以 ADR 第三版為準，並回報。

## 擁有者的話（協調者轉述；原話是中文語音，這裡拿到的是整理過的英文摘要，照錄不改）

> My MyFirstTelegramClawBot already built a 2FA verification. For dangerous commands, why not copy it? That architecture is already complete, so make the authenticator a SYNOX core feature that users can register. Don't force users to install it, but tell them they need it for dangerous commands, and give a toggle so dangerous commands (now and in the future) are protected by it.

> I want the service to open on my phone: like now, from Telegram I open my local service, then I can open a website and operate it on my phone, look around, then close it. I want the whole flow simple, done by SYNOX, but security becomes very important. What I'm most worried about is someone using holes to get around my network, attack my computer, or steal my data … check every user input, block malicious attacks as much as possible, and verify whether an input came from the user, from an agent, or from someone else.

> Hackers find holes anyway, so verify in many places and grant permissions exactly as wide as needed.

協調者補充：要簡單；要別人（寫工具的人、其他專案）也能用——一個清楚的核心層、小而穩定的介面，一個地方執行、一個地方測試；範圍就是兩步驗證＋安全地開通道＋中間的檢查與防護，不要再擴大。

## 問題一句話

危險的動作現在只靠「是不是這個 Telegram 帳號／這個瀏覽器登入」；工具的畫面只有本機打得開；SYNOX 分不出一個動作是人、AI、排程還是外面的人引起的。

## 脈絡（動手前要知道的）

- 權限唯一的交會點：`src/synox/policy.py` 的 `decide`（接在 `registry.authorize`，invariant 11）。新的判斷**加在它裡面**，不另開第二個交會點。
- SDK 已經有驗證器：`vendor/isdtelekit/security/totp.py`（計算）、`stepup.py`（單人、明文檔）、`packs/sudo.py`（`/sudo`、`SudoContinue`）；`registry.authorize` 認 `elevated`（`vendor/isdtelekit/core/registry.py:435-452`）。
  `build_app` 預設就建了一個 `StepUp`（`vendor/isdtelekit/host/app.py:231-232`），SYNOX 沒接完——所以伺服器版現在給不了別人管理員（ADR 0025 G5）。**`vendor/` 不改**，只 import。
- 確認卡按 ✅ 時本來就用按的人的身分再 authorize 一次（`src/synox/agent/approve.py:107`）。
- 網頁：所有判斷在 `WebUI.route()`（`src/synox/web/server.py:314`），測試直接呼叫、不開埠；主機台送出的字經 `dispatcher.handle`（`server.py:720`、`:754`）。
- 欄位檢查：`src/synox/packs/kit.py:133-169` 的 `parse_args`（工具服務 WP1 會抽出 `check_values`）。AI 的第 4 關：`src/synox/agent/validate.py:168`。
- 保管箱：`vault.save_json／load_json`，伺服器版 `vault.for_user(tg_id)`（`src/synox/vault/vault.py`）。
- 背景工作只能登記成 runtime 任務（invariant 18）。

## 鐵則（每一包都要守；違反就不收）

1. **這台電腦不開任何網路埠、不動防火牆、不開通道、不跑下載來的程式。** 不啟動 SYNOX、不跑 `synox run`、不裝也不執行 `cloudflared`、不用瀏覽器或無頭瀏覽器、不連網。
   驗證只用：`handle()`／`route()` 直接呼叫、假時鐘、假的 listener、假的通道、記憶體裡的假連線、node 跑純 JS。
2. 測試：做的時候只跑自己那幾個檔；每一包交件前跑一次全部，一定加 `--deselect tests/test_web.py::test_port_already_in_use_is_a_bind_failure`。不同時跑兩份、不跑 Unity、不裝套件。
3. 新的測試檔一律 `pytestmark = pytest.mark.usefixtures("no_sockets")`（工具服務計畫定的 fixture；S1 先把它加進 `tests/conftest.py`）。S13 起再加 `no_subprocess`（`subprocess.Popen` 一叫就失敗）。
4. 不新增任何第三方相依。`vendor/` 不改。
5. Git：整件事在**一個**工作樹、一條整合分支 `feat/secure-apps`（從最新的 `dev` 開；先用 `git merge --no-ff` 把 `feat/remote-access` 與 `feat/tool-apps` 的文件合進來）。
   每一包開自己的分支 `feat/secure-apps-s<NN>-<短名>`，做完 `git merge --no-ff` 回整合分支，訊息寫這包做了什麼、為什麼。**不要合進 `dev`、不要推**；全部做完回報。
6. 給使用者看的字：白話繁體中文、每個檔一張字串表（`TEXT`）；主流程不出現 TOTP、2FA、step-up、session、token、tunnel、port 這些詞。
7. repo 裡不寫真名、帳號、本機絕對路徑、Telegram id（invariant 8）。log、稽核、例外訊息裡**沒有**驗證碼、金鑰、備用碼、cookie、對方送來的原始字串。
8. 下面的「合約」是各包之間的介面：不要自己改名字或形狀；覺得有問題，停下來回報。
9. 被記憶體保護擋下、或任何一步需要真的開埠才驗得了：跳過那一步，在回報裡寫清楚，不要找別的路繞。

---

## 合約

### K1 門禁核心的版面（`src/synox/guard/`；除 `__init__.py`、`store.py`、`commands.py`、`web_api.py` 以外的檔**不 import synox 其他模組**）

| 檔 | 對外 |
|---|---|
| `origin.py` | `KINDS = ("telegram","discord","web","console","remote","ai","schedule","system","unknown")`；`HUMAN = ("telegram","discord","web","console")`；`@dataclass(frozen=True) Origin(kind="unknown", user_id=0, surface="", on_behalf=None)`，`.human`、`.caller`（`"human"｜"remote"｜"ai"｜"schedule"｜"system"｜"unknown"`）；`current() -> Origin`；`using(origin)`（context manager，可巢狀）；`from_inbound(channel, via) -> Origin` |
| `inputs.py` | `class Bad(ValueError)`（`.code` 是固定代碼：`type`／`long`／`nul`／`control`／`encoding`／`bidi`／`field`／`many`／`path`／`json`／`dupkey`／`deep`；`.text` 是固定的白話）；`text(value, *, max=2000, multiline=False) -> str`；`values(names, raw, *, max_fields=20, max=2000) -> dict`；`rel_path(raw) -> str`；`json_object(body, *, max_bytes, max_depth=4) -> dict`。**只擋、不改字** |
| `limits.py` | `Attempts(max_fail=5, window=900, lock=900, clock=time.time)`：`fail(key) -> bool`（回 True＝這一下剛被鎖）、`ok(key)`、`locked(key) -> float`（還要等幾秒）；`Rate(per_min, clock)`：`allow(key) -> bool` |
| `audit.py` | `Audit(path, clock)`：`write(event, *, by=0, origin="", target="", ok=True, code="", **nums)`；`tail(limit)`。`nums` 只收數字。1 MB 換檔留一份、寫檔持鎖。檔：`data/security_audit.jsonl` |
| `stepup.py` | K2 |
| `scope.py` | K4 |
| `qr.py` | `matrix(text: str) -> List[str]`（每列一串 `0`／`1`；位元組模式、容錯等級 M、版本 1–10；放不下丟 `ValueError`） |
| `http.py` | K6 |
| `store.py` | `VaultStore(vault, server_mode)`、`MemoryStore()`：`load(user_id) -> dict`、`save(user_id, data)`、`delete(user_id)`；保管箱的名字 `stepup` |
| `__init__.py` | `install(app, config, vault) -> Guard`；`of(app) -> Guard`（`app.extras["synox_guard"]`）；`Guard` 有 `.stepup`、`.scope`、`.audit` |
| `testing.py` | `as_origin(kind, user_id=…)`（測試用的 context manager）、`code_for(secret, clock)`（算出現在的碼）、`enroll(guard, user_id, clock) -> secret` |

### K2 驗證器（`guard/stepup.py`）

```python
class Result(NamedTuple): ok: bool; code: str; text: str     # code：""｜"unset"｜"bad"｜"replay"｜"locked"｜"not_human"｜"recovery_here"
class StepUp:
    def __init__(self, store, *, owner_id, minutes=15, clock=time.time, audit=None, notify=None)
    def enrolled(self, user_id) -> bool
    def begin(self, user_id) -> dict            # {"secret", "uri", "expires_in": 600}；只在記憶體；已設定 → ValueError
    def confirm(self, user_id, code) -> List[str]   # 對了：存檔、回 10 組備用碼（只有這一次）；不對：丟 Refused(Result)
    def verify(self, user_id, code, *, origin, purpose, allow_recovery=False) -> Result   # 一次性，不開視窗
    def unlock(self, user_id, code, *, origin, allow_recovery=False) -> Result            # verify＋開視窗（鍵＝user_id＋origin.surface）
    def unlocked(self, user_id, origin) -> bool
    def remaining(self, user_id, origin) -> int
    def lock(self, user_id, origin=None) -> bool                # origin=None＝這個人的全部入口
    def protects_danger(self, user_id) -> bool                  # 沒設定＝False
    def set_protect(self, user_id, on, *, origin) -> Result     # 關：要 unlocked
    def new_recovery(self, user_id, code, *, origin) -> List[str]   # 要一組新碼
    def disable(self, user_id, code, *, origin, allow_recovery=True) -> Result   # 要一組新碼或備用碼；之後叫 on_disable 的聽眾
    def reset_local(self, user_id) -> None                      # 只給命令列
    def status(self, user_id, origin) -> dict                   # K5 的 GET /api/stepup
    def on_disable(self, fn) -> None
    def sdk(self) -> object                                     # K3
```

- 計算一律用 `isdtelekit.security.totp`（`match(secret, code, now, window=1)` 回那組碼屬於哪個時段）。
- `verify`／`unlock`：`origin.kind` 不在 `HUMAN + ("remote",)` → `not_human`，**不計次、不碰金鑰**。沒設定 → `unset`。鎖著 → `locked`。
  時段等於上次用過的 → `replay`（不計次）。對不上、或時段比上次舊 → `bad`，`Attempts.fail(user_id)`；剛被鎖的那一下呼叫 `notify(user_id, 文字)`。
  成功：把時段寫回 store（**每次成功都存**）、`Attempts.ok`。
- 備用碼：字母表 `abcdefghjkmnpqrstuvwxyz23456789`、格式 `xxxxx-xxxxx`、10 組；存 `HMAC-SHA256(salt, 正規化後的碼)` 的十六進位；
  只在 `allow_recovery=True` 時試（呼叫端只在「本機的主機台請求」與命令列給 True；其他地方打備用碼 → `recovery_here`，文字「備用碼只能在這台電腦的 SYNOX 網頁上用」）。
  用掉一組：記時間、`notify`「你用掉了一組備用碼，還剩 N 組」。
- store 裡的形狀：`{"v": 1, "secret", "created", "last_counter", "protect_danger", "recovery_salt", "recovery": [{"h", "used"}]}`。
- 解鎖視窗與 `begin` 的暫存只在記憶體；SYNOX 重開＝全部上鎖。
- 稽核事件（`guard.audit`）：`stepup_enroll`、`stepup_unlock`、`stepup_fail`、`stepup_locked`、`stepup_recovery_used`、`stepup_protect`、`stepup_disable`、`stepup_reset`。

### K3 接到 SDK 與 `policy.decide`

- `guard.install`（在 `app.build` 裡，`app.extras["vault"]` 設好之後、`basics.install` 之前呼叫；保管箱打不開時用一個「永遠沒設定」的 store）：
  1. `registry.stepup = forms._stepup = hub.sdk()`。`sdk()` 的物件提供 SDK `StepUp` 的那組方法：`configured`（擁有者設定了沒）、`is_elevated(tg_id)`（＝`unlocked(tg_id, origin.current())`）、
     `remaining(tg_id)`、`elevate(tg_id, code)`、`verify_once(code, factor="A")`（擁有者的；`factor="B"` 一律失敗）、`has_factor`、`check`、`drop(tg_id)`、`issue_ticket()`（丟 `NotImplementedError`）、
     `on_bad_code`、`need_message`、`unset_message`（SYNOX 的白話，不是 SDK 那句命令列）。
  2. `app.stepup`：擁有者沒設定時設成 `None`；`confirm` 成功與 `disable` 之後更新（ADR 0025 §5.6）。
  3. 包一層 `app.dispatcher.handle`：外面已經有來源就沿用；沒有就 `origin.from_inbound(inbound.channel, via)`（`telegram`／`discord`／`console`／`routine`→`schedule`／其他→`unknown`），`user_id=inbound.user_id`，`surface=kind`。
     先確認 SDK 的各個入口是用 `dispatcher.handle(...)` 呼叫（實例屬性蓋得到，跟 `policy.install` 蓋 `_hidden_from` 同一招）；蓋不到的入口，在 SYNOX 自己的那一層設來源。
  4. `policy.HIDDEN_GROUPS` 加 `"unlock"`。
- 其他入口自己設來源：`WebUI.route`（認出登入之後：`Origin("web", tg_id, surface="web:"+登入雜湊前 16 碼)`）、`agent/loop.py` 執行工具的函式（`Origin("ai", user_id, on_behalf=這一輪開始時的來源)`）、
  `schedule/runner.py`（`schedule`）、runtime 任務與 `health` 的重新檢查（`system`）。
- `policy.decide` 在「能力上限」之後、呼叫 SDK authorize 之前，多兩步：

```python
o = guard.origin.current()
caller = "ai" if via == AI else "schedule" if via in (ROUTINE, SCHEDULE) else o.caller      # unknown 就是 "unknown"
if not scope.allows(node, caller):          return Decision(False, "caller", scope.TEXT["caller"])
need_always = node.policy.elevated or scope.always_stepup(node)
need_toggle = node.effect == DANGER and stepup.protects_danger(user.tg_id)
if via != ROUTINE and (need_always or need_toggle) and not (via == AI and not node.policy.elevated):
    if not stepup.enrolled(user.tg_id):     # 只有 need_always 會走到這裡（沒設定時 need_toggle 是 False）
        return Decision(False, "stepup_unset", stepup.TEXT["unset"])
    if not stepup.unlocked(user.tg_id, o):  return Decision(False, "stepup", stepup.TEXT["need"])
```

  `scope.allows`：這個節點沒有收緊過 → True（**包括 `unknown`**，所以既有測試不受影響）；收緊過 → 只收列出來的類別。
  `via == AI` 而節點是 `elevated`：照 SDK 原本的路（`needs_sudo`，AI 得到「請使用者自己解鎖」）。
  `authorize_for`（給 SDK 的那一層）把 `"caller"` 當成一般的拒絕（回那句話），不當成「不存在」。

### K4 範圍（`guard/scope.py` 與 `pack.json`）

```python
CALLERS = ("human", "remote", "ai", "schedule", "system")
class Scope: restrict(path, *, callers=None, stepup=False); allows(node, caller) -> bool; always_stepup(node) -> bool; of(path) -> dict
```

- `pack.json` 新增兩個**可選**的頂層欄位：`"callers": {"<指令名>": ["human", …]}`、`"stepup": ["<指令名>", …]`。
  第 1 關（`manifest.py`）：指令名要是這個工具宣告過的；`callers` 的值是 `CALLERS` 的非空子集；危險的指令不准列 `remote`；不認得的鍵與值＝拒（strict）／當作沒寫（已裝的舊工具）。
- loader 掛指令時呼叫 `scope.restrict(node.path, …)`；重新載入時先清掉那個工具的。對照表放在 `Guard.scope`（不動 vendor 的 `Node`）。
- 報告（`admin.summary_of`／`warnings_for`）多一行白話；升級（`upgrade.py`）：拿掉或放寬一條＝紅字，新增或收緊＝一般字。
- 工具端（SDK 0.2.x 只加不改）：`kit.caller() -> kit.Caller(kind: str, human: bool)`、`kit.require_human()`（不是人 → 丟 `kit.Refused("這個動作要你本人在 Telegram 或 SYNOX 網頁做")`，沿用現有回給使用者錯誤的那個例外型別；沒有就新增）、
  `kit.checks`：把現有的檢查函式整理成一個命名空間，缺的補上 `positive_int`、`amount`、`iso_date`、`one_line`、`max_len(n)`。
- 核心先收緊的（`callers=("human",)`）：`unlock` 群組全部、`/web`、`/web_off`、S14 的 `/app_remote`。

### K5 主機台的驗證器 API（都要登入；POST 要防偽造 token；來源是 `web`）

| 路由 | 內容 → 回應 |
|---|---|
| `GET /api/stepup` | `{"enrolled", "protect_danger", "unlocked", "unlock_left_s", "recovery_left", "locked_for_s", "minutes", "can_enroll_here", "why_not": ""}` |
| `POST /api/stepup/begin` | → `{"secret": "ABCD EFGH …", "uri": "otpauth://…", "qr": ["0101…"] 或 null, "expires_in": 600}`。不是 `can_enroll_here` → 403 |
| `POST /api/stepup/confirm` | `{"code", "protect": true}` → `{"ok": true, "recovery": ["xxxxx-xxxxx", …]}` |
| `POST /api/stepup/unlock`／`/lock` | `{"code"}` → `{"ok", "left_s"}`；錯 → 403 `{"error", "code"}` |
| `POST /api/stepup/protect` | `{"on": bool}` |
| `POST /api/stepup/recovery` | `{"code"}` → `{"recovery": […]}` |
| `POST /api/stepup/disable` | `{"code"}`（本機才收；收備用碼） |

- `can_enroll_here`：請求是本機的（`Host` 是 `127.0.0.1:<埠>`／`localhost:<埠>`，而且沒有 `Forwarded`、`X-Forwarded-*`、`Via`）；
  或者：不是擁有者、`web.public_url` 是 https、這個登入建立不到 10 分鐘。備用碼只在「本機的請求」收。
- 敏感動作（開關那一類）：`guard.stepup.gate(user, action) -> Optional[Resp]`，接在這些路由的最前面：`/api/packs/install`、`/api/packs/remove`、`/api/packs/library/install`、
  `/api/settings/llm`、`/api/settings/channels/telegram`、`/api/settings/channels/discord`、`/api/backup`、`/api/accounts/role`。沒過 → 403 `{"error": 白話, "code": "stepup"}`；畫面跳輸入框，解鎖後自動重送。
  清單是 `guard/stepup.py` 的常數 `SENSITIVE`（路由 → 白話的動作名），測試鎖住「清單裡每一條都真的擋得到」。

### K6 請求檢查（`guard/http.py`；ADR 0026 §5 的表就是規格）

```python
@dataclass(frozen=True) class Limits: header_bytes=16384; headers=60; header_value=4096; body=65536; target=2048; query=1024; params=20
@dataclass(frozen=True) class Request: method; path; query: Dict[str, str]; headers: Dict[str, str]; body: bytes
class Reject(Exception): status: int; code: str        # 400 bad_request／404 not_found／405 method／413 too_large／429 slow_down
def parse(method, target, header_items: List[Tuple[str, str]], body: bytes, *, host: str, limits=Limits()) -> Request
def reply(status, code="") -> Resp                      # 固定的小頁／小 JSON，沒有任何細節
class GuardedHandler(BaseHTTPRequestHandler)            # 給 listen.py 用的另一種薄殼：timeout=15、讀內容前先對大小、Transfer-Encoding 一律拒、
                                                        # 把 headers 以「清單」（保留重複）交給 server.ui.handle_raw(method, target, items, body)；同時連線上限 16
```

### K7 手機入口（`src/synox/web/remote/`）

設定（`config.json`，全部有預設；不合＝`ConfigError` 一句白話）：

```json
"web": { "remote": { "enabled": false, "minutes": 30, "max_minutes": 120, "idle_min": 10, "gate_port": 8861,
                     "tunnel": { "kind": "cloudflared", "path": "" } } }
```

`data/remote.json`：`{"binary": {"path", "sha256", "size", "approved_at"}, "tools": {"money": true}}`。

| 檔 | 對外 |
|---|---|
| `tunnel.py` | `class Tunnel(Protocol)`：`start(target_url, timeout=45.0) -> str`（公開網址；失敗丟 `TunnelError(code)`）、`stop()`、`alive() -> bool`；`CloudflaredTunnel(path)`（ADR 0026 §7 的跑法與停法；`URL_RE = ^https://[a-z0-9-]{1,63}\.trycloudflare\.com$`）；`make(config) -> Tunnel` |
| `binary.py` | `find(config) -> Optional[str]`；`describe(path) -> {"path", "size", "sha256", "signer"}`；`approved(path, record) -> bool` |
| `gate.py` | `RemoteGate(manager, link, app_site, *, clock)`：`handle_raw(method, target, header_items, body) -> Resp`（順序照下面） |
| `manager.py` | `RemoteManager(app, config, apps, guard, *, tunnel=None, listen=None, clock=time.time)`：`available() -> (bool, code, text)`、`open(name, user, code, *, origin, minutes=None) -> dict`、`close(reason, *, by=0) -> bool`、`status(user) -> dict`、`tick()`、`set_enabled(on, user, origin)`、`allow_tool(name, on, user, origin)`、`approve_binary(user, origin) -> dict` |
| `commands.py` | `/app_remote <名字> [分鐘]`（群組 `apps`；`owner_only`、`private_only`、`interactive=True`、`ai=False`、`callers=("human",)`）：問一組碼（120 秒的問答，照 SDK `sudo` 的寫法）→ `manager.open` |
| `web_api.py` | `GET /api/remote`、`POST /api/remote/open` `{"name","code","minutes"}`、`/close`、`/enabled` `{"on"}`、`/allow` `{"name","on"}`、`/binary/approve`（後三個要已解鎖） |
| `testing.py` | `FakeTunnel(url=…, fail=None, dies_after=None)`、`RemoteClient(manager)`（假手機：`enter(link, code)`、`get`、`read`、`do`、`raw`） |
| `static/remote_enter.html`、`.js`、`.css` | SYNOX 自己的進門頁（不含任何工具的檔；CSP 同工具服務的那一條） |

`open` 依序（任何一步不過＝`RemoteError(code, text)`，並記稽核）：`origin.kind` 是 `telegram`／`web`／`console`（否則 `not_human`）→ 是擁有者 → `available()`（`web.remote.enabled`、不是容器、工具服務可用）→
驗證器已設定（`stepup_unset`）→ `stepup.verify(owner, code, origin=origin, purpose="remote_open")`（`bad_code`）→ 通道程式找得到而且雜湊等於核准的（`no_binary`／`binary_changed`）→
這個工具宣告了 `web.app.remote` 而且 `tools[name]` 是 True（`not_remote_tool`／`tool_not_allowed`）→ 沒有別條入口（`busy`）→ 服務沒開就開（記 `started_here`）→
開閘門的 listener（`listen.open_listener(gate, gate_port, handler=GuardedHandler)`；`port`）→ `tunnel.start("http://127.0.0.2:<gate_port>")`（`tunnel_failed`；失敗要把前面開的都收掉）→
建 `Link(id, host, key_digest, entry_deadline=now+300, hard_deadline=now+分鐘, state="waiting")` → 回 `{"url": "https://<host>/#k=<key>", "minutes"}`。

`RemoteGate.handle_raw` 依序：入口已關 → 404；`http.parse(…, host=link.host)`；次數（`Rate`）；
`GET /`（沒有有效 cookie）→ 進門頁；`GET /_synox/enter.js|css`；`POST /_synox/enter` `{"k","code"}`：`state == "waiting"`、沒過 `entry_deadline`、`compare_digest(digest(k), key_digest)`、
`stepup.verify(owner, code, origin=Origin("remote", …), purpose="remote_enter")` → 成功：`state = "entered"`、發 cookie
`__Host-synox_remote=<sid>; Secure; HttpOnly; SameSite=Strict; Path=/`（只存雜湊、記下 `User-Agent` 的雜湊）、向工具站要一張交接票、回 `{"ok": true, "next": "/#t=<票>"}`、通知擁有者；
失敗：一律同一句、`Attempts.fail`，滿 5 次 `manager.close("bad_code")`；
其他路徑：cookie 有效（否則 404）→ 路由在白名單（ADR 0026 §4；否則 404）→ POST 對 `Origin` → 標頭只留白名單、`host`／`origin` 換成工具站認得的 →
`with origin.using(Origin("remote", owner, surface="remote:"+link.id)): resp = app_site.handle(...)` → 回應拿掉 `Set-Cookie`、加 ADR 0026 §5 的那幾個標頭 → `apps.touch(name)`、更新閒置時間、記稽核。

`tick()`（runtime 任務 `system.remote`，有入口時每 15 秒、沒有就不排）：過 `hard_deadline` → `close("time")`；`waiting` 過 `entry_deadline` → `close("no_entry")`；閒置過 `idle_min` → `close("idle")`；
`not tunnel.alive()` → `close("tunnel_down")`；剩 5 分鐘時提醒一次。
`close`：先標成關（閘門立刻全回 404）→ 作廢登入與鑰匙 → `tunnel.stop()` → 關 listener（等它真的放掉）→ `started_here` 就關服務 → 稽核 → 通知擁有者一則（原因用白話）。
一定會關的掛點：工具服務「服務停了」的通知、`/web_off`、`app.on_stop`、`stepup.on_disable`。

稽核事件：`remote_open`、`remote_refused`、`remote_enter`、`remote_enter_fail`、`remote_reject`（同一個原因代碼每分鐘最多一行）、`remote_action`（交給工具站的那些由工具站自己的稽核記）、`remote_close`。

---

## 順序（一條線；括號裡是它依賴誰）

```
S1  門禁核心的基礎：來源、輸入、次數、紀錄              （無）
S2  驗證器核心：保管、解鎖、接上 decide、/unlock       （S1）
S3  驗證器的畫面：註冊、備用碼、開關、命令列、doctor     （S2）
S4  範圍宣告：callers／stepup、報告、升級紅字、kit 的小介面（S1、S2）
S5  工具服務 WP0 主機台加固                            （無；放這裡是因為 S6 起都動 server.py）
S6  工具服務 WP1 宣告與檢查          ＋對接 a、b        （S4）
S7  工具服務 WP3 共用元件            ＋對接 c           （無）
S8  工具服務 WP2 核心執行            ＋對接 d、e、f      （S1、S6）
S9  工具服務 WP4 主機台畫面與 API                       （S8）
S10 工具服務 WP5 Telegram 指令與 doctor ＋對接 g        （S8）
S11 工具服務 WP6 SDK 與文件                             （S6、S7）
S12 工具服務 WP7 記帳 app（SYNOX_Libs 的工作樹）         （S6–S8、S11）
S13 請求檢查與遠端閘門                                  （S2、S8）
S14 通道、開關、指令、主機台畫面                         （S13、S9、S10）
S15 攻擊測試、文件、收尾（記帳宣告 remote）              （全部）
```

為什麼這樣排：擁有者要先有兩步驗證（S1–S4 做完就能用，跟工具服務無關）；工具服務的八包照它自己的合併順序（0→1→3→2→4→5→6→7）；
手機入口一定在工具服務的核心（S8）之後。S12 之後擁有者就能在本機用記帳畫面；S14 之後才有手機入口。**每一包做完都是可以停下來的狀態**（測試全過、沒有做到一半的開關）。

對接事項（做那一包時順手做，等於 ADR 0026「對工具服務 ADR 的請求」Q2–Q6；Q1 改號在 S15）：

| | 在哪一包 | 做什麼 |
|---|---|---|
| a | S6 | `web.app` 多收可選的布林 `remote`（預設 false；宣告了才可能從手機用）；報告多一行「這個工具的畫面可以從手機用（要你另外打開）」；升級時 false→true＝紅字 |
| b | S6 | `kit.check_values` 的第一步是 `guard.inputs.values(欄位名, values)`；`Bad` 轉成跟其他欄位錯誤同一種回法 |
| c | S7 | 共用元件讀 `/api/me` 的 `remote`：true 時不畫「回 SYNOX」、不畫匯出、頁首多一個倒數與「關閉手機入口」 |
| d | S8 | `AppSite.handle` 可被同程序直接呼叫；`site.host_header` 屬性；交接票與登入綁的上一層是有 `alive()` 的物件 |
| e | S8 | 讀與動作在 `guard.origin` 底下跑（外面沒設→`web`；已經是 `remote`→沿用）；稽核 `via` 多 `remote`；來源是 `remote`：匯出回 403 `remote_no_export`、危險動作回 403 `remote_no_danger`（工具的函式不會被叫到）；`/api/me` 多 `"remote"` |
| f | S8 | `AppManager.on_stopped(fn)`、公開的 `touch(name)`；`listen.open_listener(site, port, *, handler=None)` |
| g | S10 | `/apps` 多顯示手機入口的狀態；`/app_open <名字> remote` 回一句「用 /app_remote <名字>」（S14 改成直接轉過去） |

---

## 每一包

### S1 門禁核心的基礎

檔案：`src/synox/guard/{__init__,origin,inputs,limits,audit,testing}.py`（K1）、`src/synox/app.py`（呼叫 `guard.install`；這一包的 `install` 只包 `dispatcher.handle` 與建 `Audit`）、
`src/synox/web/server.py`（`route` 認出登入後設來源）、`src/synox/agent/loop.py`、`src/synox/schedule/runner.py`、`src/synox/health/`（重新檢查）、`src/synox/packs/kit.py`（`parse_args` 算出 `values` 之後、跑欄位檢查之前呼叫 `inputs.values`）、
`tests/conftest.py`（fixture `no_sockets`）。

測試 `tests/test_guard_origin.py`、`test_guard_inputs.py`、`test_guard_limits.py`、`test_guard_audit.py`：
- 來源：沒設＝`unknown`；`using` 巢狀與離開後還原；另一條執行緒看不到這條的來源；Telegram 的假訊息進 dispatcher → handler 裡 `current().kind == "telegram"`；主機台 `send`／`press` → `web`、`surface` 兩個不同的登入不一樣；
  AI 呼叫工具 → handler 裡是 `ai` 而且 `on_behalf.kind` 是原本的入口；排程到點 → `schedule`；按確認卡 ✅ → 是按的人的入口、不是 `ai`。
- 輸入：`text` 的每一種拒絕各一例（太長、`\x00`、`\x1b`、落單的 `\ud800`、`‮`），中文、emoji、換行（`multiline=True`）、全形字照過；回傳值等於輸入；`Bad` 的文字裡**沒有**輸入的內容。
  `values`：不認得的鍵、21 個鍵、值不是字串。`json_object`：重複鍵、5 層、陣列、非 UTF-8、超過大小。`rel_path`：ADR 0026 §5 模糊測試清單裡的每一個路徑都 `Bad`；`app.js`、`img/a.png` 過。
- 既有指令：`/money_add` 帶 `\x00` 的備註 → 被拒、訊息是固定的那句；正常輸入的訊息一個字都沒變（現有 `tests/test_packs.py`、`test_tools.py` 不改就過）。
- 次數：4 次錯不鎖、第 5 次鎖、鎖 15 分鐘後解、`ok` 清零、窗口外的錯不算。紀錄：只收數字的額外欄位、換檔、檔案裡找不到測試用的特殊字串。

驗收：測試過；`guard/origin.py`、`inputs.py`、`limits.py`、`audit.py` 沒有 `import synox`（寫一個讀檔的測試鎖住）；全部測試過。

### S2 驗證器核心

檔案：`guard/stepup.py`、`store.py`、`commands.py`（群組 `unlock`「🔐 解鎖」：`/unlock [6 位數]`（`default=True`、`legacy=("sudo",)`）、`/unlock_off`；
只在私訊、`ai=False`、`interactive=True`；伺服器版每個人都能用；重用 `isdtelekit.packs.sudo.SudoContinue` 做「▶ 繼續」）、`guard/__init__.py`（K3 全部）、`src/synox/policy.py`（K3 那幾行；`scope` 這一包先放一個「什麼都沒收緊」的版本）、
`src/synox/config.py`（`stepup_minutes` 預設改 15、範圍 1–120）、`src/synox/agent/`（對話助理收到「整則只有 6 位數（中間可以有一個空白）」而這個人已設定驗證器 → 不送 LLM，回一句與一顆「🔓 拿來解鎖」）、
`src/synox/web/server.py`（`send`：`/unlock <碼>` 存進對話紀錄時遮成 `/unlock ······`）。

測試 `tests/test_stepup_core.py`、`test_stepup_policy.py`、`test_stepup_commands.py`：
- RFC 6238 附錄 B 的 SHA-1 測試值（取後 6 位）對得上；前後一個時段收、兩個時段不收。
- `begin`→`confirm` 錯的碼不存檔；對的才存、回 10 組不重複的備用碼、store 裡找不到明文的備用碼；`begin` 過 10 分鐘失效；已設定再 `begin` 被拒。
- 同一組碼第二次 → `replay`、不計次；**新建一個 `StepUp`（模擬重開）同一組碼仍是 `replay`**；舊時段的碼 → `bad`。錯 5 次 → `locked`、`notify` 被叫一次；鎖著時對的碼也不收；15 分鐘後收。
- 來源：`ai`／`schedule`／`system`／`unknown` 呼叫 `verify`、`unlock` → `not_human`，而且錯的碼不計次、對的碼也不過。
- 解鎖綁入口：Telegram 解鎖 → `unlocked(telegram)` True、`unlocked(web:…)` False；兩個不同的網頁登入互不相通；15 分鐘後 False；`lock` 之後 False。
- 備用碼：`allow_recovery=False` → `recovery_here`；True → 過一次、第二次不過、`notify` 有剩幾組；大小寫與有沒有連字號都認。
- 伺服器版（真的 `vault.for_user`）：甲的碼解不了乙；乙沒設定不影響甲；兩人各自的錯誤次數。保管箱的檔是密文（檔案內容找不到金鑰字串）。
- `decide` 的表格測試：{沒設定、設定＋開關關、設定＋開關開} × {唯讀、寫入、危險、`elevated`} × {`TYPED`、`BUTTON`、`SCHEDULE`、`ROUTINE`、`AI`} × {已解鎖、沒解鎖} → 預期的 `allowed`／`reason`（把 K3 那段規則寫成表，逐格比）。
  特別鎖住：沒設定時，危險指令的結果**跟這一包之前一模一樣**。
- AI：危險指令＋開關開 → 仍然出確認卡（沒有被擋在前面）；按 ✅ 沒解鎖 → 沒執行、回「先解鎖」、卡還在；解鎖後再按 → 執行。AI 的工具清單裡沒有 `unlock`。把 `/unlock 123456` 排進排程 → 被拒。
- 指令：`/unlock` 對的碼 → 解鎖；只打 `/unlock` → 下一則當成碼而且**假的 LLM 沒被呼叫**；被擋的指令解鎖後有「▶ 繼續」；單獨 6 位數 → LLM 沒被呼叫。網頁對話紀錄裡找不到那 6 位數。
- G5：伺服器版、擁有者沒設定 → `/user_role <id> admin` 成功（`app.stepup is None`）；設定之後沒解鎖 → 被擋、訊息是 SYNOX 的白話；解鎖後成功。

驗收：測試過；`git grep -n "stepup_totp.json" src/` 沒有結果（SDK 的明文檔那條路沒有被用到）；`docs/security.md`「誰能用你的 bot」最後一條改寫。

### S3 驗證器的畫面

檔案：`guard/web_api.py`（K5；`server.py` 的 `api()` 開頭把 `/api/stepup` 前綴轉過去，照 `/api/runtime/` 的寫法）、`guard/qr.py`、`src/synox/web/static/security.js`＋`security.css`（設定頁新分頁「🔐 安全」，用 `INCLUDE` 機制放進 `app.html`；
共用一個 `SynoxStepUp.ask(retry)`：任何 API 回 403 `code: "stepup"` 時跳輸入框、解鎖後重送）、`src/synox/__main__.py`（`stepup setup｜status｜reset`；`setup` 在終端機印金鑰與用方塊字畫的 QR，問一組碼）、
`src/synox/doctor.py`（一行：「手機驗證器：沒設定（危險的動作目前只靠你的 Telegram 帳號與瀏覽器登入；到 SYNOX 網頁 → 設定 → 安全）」／「已設定，危險的動作要先解鎖」／「已設定，但危險的動作沒有開保護」）、
K5 的 `SENSITIVE` 掛到那八條路由、`tests/js/test_security.js`。

畫面（字照 ADR 0025「給使用者的說法」）：狀態卡 → 設定三步（QR＋金鑰文字＋打碼）→ 備用碼（只這一次；要勾「我抄好了」才關得掉）→ 開關（預設勾，擁有者決定第 3 題）→
之後的卡：狀態、開關、剩幾組備用碼、「產生新的備用碼」、「關掉驗證器」（紅色、要碼）、現在這個瀏覽器解鎖了沒與「馬上鎖回去」。不是本機 → 不顯示設定的按鈕，顯示「請在跑 SYNOX 的那台電腦上設定」。
第一次用到危險指令而沒設定：只提示一次（每人一次，記在 `data/`）：「💡 這類動作可以多一道手機驗證：SYNOX 網頁 → 設定 → 安全。」

測試 `tests/test_stepup_web.py`（`tests/test_web.py` 的假瀏覽器）、`test_guard_qr.py`、`test_stepup_cli.py`：
- K5 每條路由：沒登入 401、沒防偽造 token 403；`begin` 在本機 Host → 有金鑰；Host 是別的、帶 `X-Forwarded-For` → 403 而且回應裡沒有金鑰；伺服器版成員、https 的 `public_url`、新登入 → 可以，登入超過 10 分鐘 → 不行；擁有者從對外網址 → 不行。
- `confirm` 之後 `GET /api/stepup` 的形狀；備用碼只在 `confirm`／`recovery` 的回應出現一次，之後任何 GET 都拿不到；`disable` 用備用碼在本機可以、非本機不行。
- `SENSITIVE` 的每一條：沒設定 → 照舊；設定＋開關開＋沒解鎖 → 403 `stepup` 而且**原本的動作沒發生**；解鎖後過。在 Telegram 解鎖不會讓網頁過。
- QR：測試裡寫一個小解碼器（讀格式資訊、去遮罩、照順序讀碼字、驗錯誤更正碼的餘數是 0、取出位元組）→ 讀回來等於輸入；三個長度（20、60、120 字）；定位圖形在三個角；放不下丟錯。
- 命令列：假的輸入函式走完 `setup`；`reset` 之後沒設定；`status` 不印金鑰。`doctor` 三種輸出。
- JS：403 `stepup` → 出現輸入框 → 解鎖成功後原本的請求重送一次；取消 → 不重送；字都在 `TEXT`，沒有 TOTP、2FA、token。

驗收：測試過；`render_app()` 的頁面仍只有 nonce 的 script／style；新增 `docs/security.md` 一節「手機驗證器」（保護什麼、不保護什麼、手機不見怎麼辦）。

### S4 範圍宣告

檔案：`guard/scope.py`（K4）、`src/synox/packs/manifest.py`、`loader.py`、`admin.py`、`upgrade.py`、`kit.py`（`caller`、`require_human`、`checks`）、`src/synox/sdk/`（版本只加不改；單檔版重產）、
`docs/pack-format.md`、`docs/sdk.md`、`tests/fixtures/` 加一個小工具 `scoped`（一個指令 `callers: ["human"]`、一個 `stepup`）。

測試 `tests/test_scope.py`：
- 第 1 關：不認得的指令名、空清單、不認得的類別、危險指令列 `remote` → 拒，訊息點名；沒寫的工具跟以前一模一樣（報告、信任層級逐欄比）。
- 執行：`callers: ["human"]` 的指令——人打字過；AI 的工具清單裡**沒有它**、硬叫回「沒有這個工具」；排進排程被拒；`unknown` 來源被拒；`remote` 來源被拒。沒收緊的指令在 `unknown` 來源照過。
- `stepup` 的指令：沒設定的人 → `stepup_unset` 與去哪裡設定；設定沒解鎖 → 擋；解鎖 → 過；不管開關開不開。
- 升級：拿掉 `callers` 的一條＝紅字；新增＝一般字。重新載入之後對照表沒有殘留。
- `kit.caller()` 在四種入口回對的 `kind`；`kit.require_human()` 在 AI 呼叫時丟出去、使用者看到那句白話。`kit.checks` 每個函式一對好壞例子。

驗收：測試過；`docs/pack-format.md` 有 `callers`／`stepup` 一節與範例；`docs/AGENT.md` 加 invariant（見 S15 的文字）。

### S5–S12 工具服務的八包

照 `feat/tool-apps` 最新的計畫做（WP0、WP1、WP3、WP2、WP4、WP5、WP6、WP7，各自的檔案、測試、驗收以那份為準），加上面的對接 a–g。對接多出來的測試：

- a：`remote` 不是布林 → 拒；沒寫＝false；報告與升級紅字。
- b：工具畫面的動作帶 `\x00`、超長的值 → 400，而且訊息跟 Telegram 那條同一句；`check_values` 與 `parse_args` 對同一組壞輸入給同樣的錯誤。
- c：`remote: true` 時沒有「回 SYNOX」的連結、`download` 不送任何請求；`false` 時跟原本一樣。
- d、e：直接呼叫 `site.handle`（外面包 `origin.using(Origin("remote", …))`）：讀與寫入動作成功、稽核那一行的 `via` 是 `remote`；匯出 → 403 `remote_no_export`、危險動作 → 403 `remote_no_danger`，**工具的函式沒被叫到**（計數器）；
  上一層的 `alive()` 變 False → 下一個請求 401。沒包來源時 handler 裡是 `web`。
- f：`on_stopped` 在每一種停法（手動、閒置、重新載入、`/web_off`）都被叫到一次；`open_listener(handler=X)` 把 X 交給假的伺服器類別。
- g：`/apps` 的字。

S12 在 SYNOX_Libs 的工作樹做（照那邊的 ADR-0003）；先不宣告 `remote`（S15 才加）。

### S13 請求檢查與遠端閘門

檔案：`guard/http.py`（K6）、`src/synox/web/remote/{__init__,gate,manager,testing}.py`（K7；這一包的 `manager` 用 `FakeTunnel` 就能完整運作，`tunnel.py` 只放 `Protocol` 與 `TunnelError`）、
`src/synox/web/static/remote_enter.{html,js,css}`、`src/synox/config.py`（K7 的設定與檢查）、`config.example.json`、`tests/conftest.py`（`no_subprocess`）。

測試 `tests/test_guard_http.py`、`test_remote_gate.py`、`test_remote_manager.py`、`test_remote_fuzz.py`（全部 `no_sockets`＋`no_subprocess`；用工具服務的 `counter` fixture，替它宣告 `remote: true`）：
- `parse`：ADR 0026 §5 那張表每一列至少一個壞例子與一個好例子；`Reject` 的狀態與代碼對。`GuardedHandler`：把位元組放進記憶體裡的假連線（`makefile` 回 `BytesIO`）——
  `Transfer-Encoding: chunked`、兩個 `Content-Length`、`Content-Length` 大於上限（**內容沒有被讀**）、標頭太多、請求行太長 → 固定的拒絕；沒有任何例外漏出來。
- `open` 的每一個前提各一個不過的例子（K7 的每個錯誤代碼）＋稽核有 `remote_refused`；`open` 成功後：假 listener 被要求開的是 `127.0.0.2` 與 `gate_port`、`FakeTunnel.start` 收到的就是那個位址、回的網址以 `#k=` 結尾、資料檔與稽核裡找不到鑰匙。
  通道起不來 → listener 與服務都收掉、狀態是關的。來源是 `ai`／`schedule`／`unknown`／`remote` → `not_human`，而且驗證碼沒被消耗。
- 進門：沒 cookie 的 `GET /` 是 SYNOX 的進門頁、裡面沒有工具的任何字；對的鑰匙＋對的新碼 → 200、`Set-Cookie` 有 `__Host-`、`Secure`、`HttpOnly`、`SameSite=Strict`；
  **用開入口的同一組碼進門 → 不過**；同一把鑰匙第二次 → 不過；鑰匙過 5 分鐘 → 不過而且入口被收掉；錯 5 次 → 入口收掉、擁有者被通知一次；失敗的回應全部一模一樣（位元組比對）。
- 進門之後（`RemoteClient`）：`/api/me` 有 `remote: true`；讀、寫入動作成功，結果跟 Telegram 打同一個指令一樣；危險動作、匯出 → 403；`/api/keep`、主機台的任何路徑（`/api/apps`、`/api/me` 的主機台版、`/login`）、別的工具的路徑 → 404。
  沒 cookie、錯的 cookie、別條入口留下的 cookie、`User-Agent` 換了 → 404（跟不存在的路徑同一個回應）。`Host` 不是這次的網域 → 404。POST 的 `Origin` 是別的網站 → 拒。回應裡永遠沒有 `Access-Control-*`、有 HSTS 與 `noindex`。
  交給工具站的標頭裡沒有 `cf-*`、`x-forwarded-*`、`cookie`。工具站收到的來源是 `remote`。
- 時間（假時鐘、`tick()`）：30 分鐘 → 關、通知；閒置 10 分鐘 → 關；有請求就重算；剩 5 分鐘提醒一次；`FakeTunnel` 中途死掉 → 關；`minutes` 超過 `max_minutes` → 夾到上限。
- 關：之後同一個 cookie → 404；`FakeTunnel.stop` 被叫一次；listener 被關；`started_here` 時服務也關、原本就開著的服務還開著；工具服務那邊自己停了 → 入口跟著關；`stepup.disable` → 關；`/web_off` → 關。
- 次數：沒進門每分鐘第 61 個請求 → 429；被拒累計 300 → 入口收掉。稽核裡找不到測試送進去的特殊路徑字串。
- 模糊（`test_remote_fuzz.py`）：ADR 0026 §5 清單的每一條都是一個參數化的案例；再用固定種子的亂數產生 2000 個請求（隨機位元組、隨機拼接清單裡的片段）餵給 `handle_raw` 與 `GuardedHandler`——
  斷言：狀態只會是 400／404／405／413／429，沒有例外，工具的函式呼叫次數是 0，回應裡沒有輸入的任何片段。

驗收：測試過；`git grep -n "_Server(" src/` 仍然只有 `server.py` 原本那一處與 `web/apps/listen.py`；`git grep -n "subprocess" src/synox/web/remote/` 這一包沒有結果。

### S14 通道、開關、指令、主機台畫面

檔案：`web/remote/tunnel.py`（`CloudflaredTunnel`：`subprocess.Popen` 用參數清單、`stdin=DEVNULL`、最小的環境、空的暫存工作資料夾、讀輸出的執行緒只留符合 `URL_RE` 的那一段、`stop` 先 `terminate` 等 5 秒再 `kill`；
Windows 上跟著 SYNOX 一起結束的做法先看 `src/synox/sandbox.py` 有沒有現成的工作物件函式可以共用）、`binary.py`、`commands.py`、`web_api.py`、
`src/synox/web/static/apps.js`（工具卡片多一列「📱 手機入口」：前提沒齊就列出缺哪一樣與去哪裡做；齊了有「開手機入口」→ 問碼 → 顯示網址與 QR、倒數、「關閉」）、
`security.js`（總開關、通道程式的核准卡：路徑、大小、SHA-256、簽署者、「請跟官方發佈頁上的雜湊對一下」）、`src/synox/doctor.py`（手機入口：關／缺什麼／可以用；使用者資料夾有 `cloudflared` 設定檔時提醒；**不執行通道程式、不連任何埠**）、
工具服務的 `/app_open <名字> remote` 改成直接轉給 `/app_remote`。

測試 `tests/test_remote_tunnel.py`、`test_remote_commands.py`、`test_remote_console.py`（**不執行任何真的程式**：`subprocess.Popen` 換成假的類別，記下收到的參數、吐出預先寫好的輸出行）：
- `CloudflaredTunnel.start`：參數清單一字不差（`[path, "tunnel", "--no-autoupdate", "--url", "http://127.0.0.2:8861"]`）、`shell` 不是 True、環境裡沒有保管箱與 token 相關的變數；
  輸出裡有網址 → 回它；輸出裡是 `https://evil.example/`、`http://…trycloudflare.com`、帶路徑的 → 不收；45 秒沒有 → `TunnelError("timeout")` 而且程序被結束；`stop` 的兩段式。
- `binary`：找不到 → `no_binary`；核准後檔案內容改一個位元組 → `binary_changed`、`Popen` 沒被叫；核准要已解鎖、來源是人。
- 指令：`/app_remote counter` → 問碼 → 對 → 回覆裡有網址、有「只能用一次」「幾分鐘後自動關」「怎麼關」；群組裡打 → 擋；成員打 → 跟不存在一樣；AI 的工具清單沒有它；排進排程被拒；
  每個前提不過時的白話（照 K7 的代碼各一句，都說下一步去哪裡做）；`/app_close counter` → 入口與服務都關；`/apps` 顯示入口與剩幾分鐘。回覆送出時關掉連結預覽。
- 主機台：`/api/remote` 的形狀；`open` 沒帶碼、碼錯；`enabled`／`allow`／`binary/approve` 沒解鎖 → 403 `stepup`；成員 → 403。JS：前提清單、問碼、倒數、字都在 `TEXT`。

驗收：測試過；整個 repo 新增的 `subprocess.Popen` 只有 `tunnel.py` 那一處；`README.md`、`docs/tools.md` 各補一段。

### S15 攻擊測試、文件、收尾

- `tests/test_attack_matrix.py`：照 [web-threats.md](../security/web-threats.md) 的表，每一列「已做」的防護至少有一個點名的測試（表裡的測試名稱要真的存在——寫一個測試去讀那份文件、檢查每個反引號裡的 `tests/…::…` 都找得到）。
- 文件：`docs/security.md`（新增「門禁核心」「手機驗證器」「手機入口」三節＋兩份 ADR 的「擋不住的」）；`docs/security/web-threats.md` 的狀態欄更新成實際的；
  `docs/AGENT.md`：invariant 9 改寫（主機台 `127.0.0.1`；工具服務與遠端閘門只綁 `127.0.0.2`、只由 `web/apps/listen.py` 開）、新增三條——
  「來源：每個入口都要設 `guard.origin`；沒設＝不明＝收緊的地方一律拒」「驗證碼只從人的入口進來；任何給 AI 的工具都不能有收驗證碼的欄位」「通道程式只由 `web/remote/tunnel.py` 啟動，啟動前對雜湊；測試不執行它」；Map 加 `guard/`、`web/remote/`。
  `CHANGELOG.md`；`docs/tool-apps.md`（給寫工具的人：`remote`、`callers`、`stepup`、`kit.caller`）。
- 改號：工具服務的 ADR 改成 0024（檔名、內文、兩邊計畫與 SYNOX_Libs 的連結）。
- SYNOX_Libs：記帳的 `pack.json` 加 `"remote": true`；它的 app 測試加一段用 `RemoteClient` 走一遍（進門、看這個月、記一筆、刪一筆被拒）。
- 兩份 ADR 的狀態改成「已採用」＋實際的分支與 commit；這份計畫的狀態改成「已修」＋ merge commit。

驗收：下面「驗收（整體）」。

---

## 只有擁有者能做的實測（他選的電腦、真的手機；開發機不做）

失敗就把畫面與 `data/security_audit.jsonl` 最後幾行帶回來。先做工具服務計畫自己的那一張實測表。

| # | 做什麼 | 預期 |
|---|---|---|
| P1 | 主機台 → 設定 → 安全 → 設定手機驗證器，用手機掃 QR | 掃得到；打碼後看到 10 組備用碼。掃不到就用手動輸入，並記下手機與 App |
| P2 | Telegram 打一個危險的指令（例如刪一筆） | 被擋、叫你 `/unlock`；解鎖後有「▶ 繼續」；15 分鐘內不再問 |
| P3 | 請 AI 刪一筆 | 出確認卡；沒解鎖按 ✅ 被擋、解鎖後再按才做 |
| P4 | 手機關機，用備用碼在主機台關掉驗證器 | 可以；Telegram 收到通知 |
| P5 | 裝 `cloudflared`（自己裝）→ 主機台核准（對過官方的雜湊）→ 打開總開關與記帳的「可以從手機用」 | 三樣都顯示完成 |
| P6 | Telegram `/app_remote money` → 打碼 | 幾十秒內收到連結（記下實際幾秒） |
| P7 | 手機點連結 → 再打一組碼 | 進到記帳畫面；Telegram 收到「有人進來了」 |
| P8 | 在手機上看這個月、記一筆、試著刪一筆、試著匯出 | 前兩個可以；後兩個被擋並說回電腦做。電腦上 `/money_list` 看得到剛記的 |
| P9 | 把連結貼到另一台裝置的瀏覽器 | 進不來（連結用過了） |
| P10 | 在手機瀏覽器把網址改成 `/api/apps`、`/../config.json`、`/login` | 都是同一個「找不到」 |
| P11 | 放著不動 10 分鐘；另一次用滿 30 分鐘 | 自動關、Telegram 收到通知；網址打不開 |
| P12 | 開著的時候在電腦上看有哪些程式在聽埠（`netstat -ano`） | 只有本機位址（`127.0.0.1`、`127.0.0.2`）；沒有 `0.0.0.0`；關掉之後閘門的埠與 `cloudflared` 都不見 |
| P13 | 開著的時候 `/app_close money` | 幾秒內手機畫面顯示已關、`cloudflared` 的程序不見 |
| P14 | 用 Telegram 內建瀏覽器與 Safari／Chrome 各做一次 P7 | 都進得去；記下哪個不行 |

## 選項表（實作中遇到要選的；預設照建議，不用回頭問）

| 題目 | 選項 | 建議（預設做這個） |
|---|---|---|
| 解鎖指令的名字 | `/unlock`＋別名 `/sudo`／只用 `/sudo` | **`/unlock`＋別名** |
| QR 做不出可靠的 | 先只給手動輸入／卡住等它 | **先只給手動輸入**，QR 留一張問題單（`_inbox/` 或專案的 issues 資料夾，一件一檔） |
| 稽核要不要進保管箱 | 明文 JSONL、不記內容／加密 | **明文、不記內容**（SYNOX 沒開時也要能看） |
| 成員能不能設定驗證器 | 能（K5 的條件）／只有擁有者 | **能** |
| 通道斷了 | 整條收掉／自動重開 | **收掉**（重開會換網址） |
| 閘門的埠被占用 | 回報、不換埠／自動換 | **回報**（跟工具服務第三版一致） |
| `Windows` 上通道程式跟著結束的做法接不乾淨 | 用 `atexit`＋`on_stop` 兩層保險／卡住 | **兩層保險**，並在實測表 P13 驗 |

擁有者真的要決定的四題在兩份 ADR 的最後（開關預設、通道選哪種、進門要不要再打碼、遠端能不能做危險動作）；沒回就照建議做，不要自己往別的選項做。

## 驗收（整體）

- S1–S15 各自的驗收都過；全部測試（加那個 `--deselect`）過；新增的測試沒有一個真的開埠、開子程序、連網。
- 沒設定驗證器的安裝：每一個既有指令、主機台每一條既有路由的行為跟合併前一樣（唯一的例外：伺服器版擁有者現在給得了管理員，ADR 0025 G5）。
- `git grep -n "_Server(" src/`：`server.py` 原本那一處＋`web/apps/listen.py`。`git grep -n "Popen" src/synox/web/`：只有 `web/remote/tunnel.py`。
- 驗證碼、金鑰、備用碼、遠端的鑰匙與 cookie：在 `data/` 的任何明文檔、log、稽核裡都找不到（測試用特殊字串去找）。
- 給使用者看的每一句新字都在某個 `TEXT` 表；主流程沒有 TOTP、2FA、token、tunnel、port。
- web-threats.md 每一列的狀態是真的（有測試名的找得到測試）。

## 不要做的事

- 不要在這台電腦開埠、跑伺服器、開瀏覽器、動防火牆、下載或執行 `cloudflared`；不要為了「驗一下」破例。
- 不要改 `vendor/`；不要讓任何給 AI 的工具有收驗證碼的參數；不要讓驗證碼、金鑰經過 Telegram 的訊息以外的任何紀錄；不要把金鑰顯示在非本機的請求（K5 的例外除外）。
- 不要讓通道指到主機台或工具服務的埠；不要加 CORS；不要讓 `config.json` 決定綁哪個位址；不要自動下載、自動更新通道程式。
- 不要做兩份 ADR「不做」裡的任何一項（第二組驗證器、成員的手機入口、遠端的危險動作與匯出、具名通道、私人網路、容器版…）。
- 不要把安全等級、自由度、出口白名單、簽章這些別份研究的東西做進來。
- 不要合進 `dev`、不要推；不要改這份計畫的合約而不回報。
