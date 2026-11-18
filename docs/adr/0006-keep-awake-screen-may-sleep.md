# ADR 0006：保持清醒——電腦不睡著、螢幕可以熄

- 日期：2026-11-13
- 狀態：已採用（分支 `feat/screen_protect_awaker`）
- 網頁 API：[../runtime-api.md](../runtime-api.md)

## 需求來源

維護者的需求；原文保存在維護者的私有文件，不放在公開 repo。

## 決定

1. **不需要自己做黑螢幕工具。** Windows 的「系統清醒」和「螢幕常亮」是兩個分開的電源請求。只請求前者
   （`PowerCreateRequest` + `PowerRequestSystemRequired`），電源計畫裡「幾分鐘後關閉螢幕」照樣生效，任何滑鼠、鍵盤動作 Windows 自己把螢幕點亮。
   自己寫偵測滑鼠鍵盤的黑畫面程式，要常駐、要全螢幕蓋住、還會擋到真的在用電腦的人，沒有比內建的好。
2. **為什麼是 runtime 任務、不是心跳的 AI 指令。** 心跳每 45 分鐘才一次、常駐助理沒有工具（ADR 0001 §4），而且「電腦睡著」發生在兩次心跳之間。
   所以做成 `system.keep_awake`：每 60 秒確認請求還在，不叫 AI。心跳照舊把它當一般任務看——請求失敗（Windows 不肯接受）＝任務 failed，
   心跳的「失敗狀態沒有變化就不再叫 AI」規則照常適用；非 Windows 顯示 idle，不算失敗。
3. **用請求物件（`PowerCreateRequest`），不用 `SetThreadExecutionState`。** 後者綁在呼叫它的那條執行緒，執行緒結束就失效；任務每次可能在不同執行緒跑。
   請求物件是行程等級，SYNOX 結束 Windows 自己放掉，不會留下改了電腦設定的痕跡。
4. **電源計畫把「關閉螢幕」設成「永不」的人**：`screen_off_after_min`（1～240）。`GetLastInputInfo` 量閒置，超過就送一次 `SC_MONITORPOWER`
   （同一段閒置只送一次，不然一動滑鼠又被關掉）。0＝照電源計畫（預設）。
5. **預設關。** 這會改電腦的睡眠行為，要擁有者自己開（`runtime.keep_awake.enabled`、網頁、`doctor` 會列出現況）。

## 擋不住的
闔上筆電蓋、開始選單手動睡眠、電池快沒電、Windows Update 重開機、當機或斷電。「機器人自己關機」如果其實是重開機或當機，這個沒有用——要看事件檢視器。

## 不做
- 自製黑螢幕程式；macOS／Linux（任務顯示 idle）。網頁開關：2026-11-13 附記時補在**設定頁**的「保持清醒」卡片。

## 附記（2026-11-13，分支 `feat/local_llm_platform`）：現代待命與「打開時要講清楚」

**定位**：它像一個穩定的 heartbeat——維持系統運轉（maintain），但螢幕可以暗（保護螢幕或省電）。

**擁有者的情況**：這台是 Windows「現代待命」（Modern Standby／S0 低電源閒置）機型（`AoAc=1`、沒有 S3），
無故休眠會讓 Google Drive 桌面版斷線。擔心 `PowerRequestSystemRequired` 擋不住現代待命。

**讀了 Microsoft 官方文件**（2026-11-13 讀取）：
- [PowerSetRequest](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-powersetrequest)：
  `PowerRequestExecutionRequired`＝呼叫的行程繼續執行、不被行程生命週期管理暫停或終止（能跑多久看系統與電源政策）；
  **在傳統睡眠（S3）機型上它隱含 SystemRequired**（所以現代待命機型上不隱含，兩個都要設）。
  Remarks 原文要點：現代待命機型**用電池時**，system 與 execution 請求在睡眠逾時到了之後 **5 分鐘**被終止；
  除了 S3 的 AwayMode，**使用者主動睡眠（電源鍵、闔蓋、開始選單睡眠）會終止所有電源請求**。
- [Prepare software for modern standby](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/prepare-software-for-modern-standby)：
  螢幕一關就開始準備進待命；第一個階段（No-CS）等睡眠逾時與電源請求——**插電時電源請求會讓這個階段無限期擋住**，用電池最多 5 分鐘。
  之後的 DAM 階段會**暫停所有桌面程式**（Google Drive 桌面版也是），無法例外。
- [Network connectivity](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/modern-standby-network-connectivity)：
  Windows 10 2004 起預設「自適應連線待命」，用電池睡著時一般程式沒有網路。

**結論**：插電、閒置逾時這個情境，原本的 SystemRequired 就擋得住（停在 No-CS，到不了 DAM）；用電池只能多撐 5 分鐘；
主動睡眠、闔蓋一定擋不住。ExecutionRequired 補上是盡力而為（文件沒有說它在現代待命能多擋什麼，只保證行程不被 PLM 暫停），
不能當成「現代待命也不會睡」的保證——這點照實寫在 view()／doctor 的說明裡。Google Drive 斷線若不是整台睡著，
更可能是網路卡省電，見 [../keep-awake-troubleshooting.md](../keep-awake-troubleshooting.md)。

**做了**：
1. `WinPower.hold` 在同一個請求物件上再設 `PowerRequestExecutionRequired`（設不上不算失敗；`view()["execution_required"]`）。
2. `CallNtPowerInformation(SystemPowerCapabilities)` 的 `AoAc`（`SYSTEM_POWER_CAPABILITIES` 第 20 個位元組）判斷現代待命；
   doctor 與 `view()["modern_standby_note"]` 多一行：「系統清醒請求在現代待命的效果有限，若 Google Drive 仍斷線請見 docs 的排查步驟」。
3. **預設關**（`runtime.settings.DEFAULT_RUNTIME`；新安裝、舊 config 沒寫都是關，有測試鎖住）。
4. 打開它的每個地方都講清楚（`keepawake.NOTICE`，`view()["notice"]`；網頁設定頁、doctor、runtime-api.md、config.example.json）：
   開啟後會覆蓋 Windows 電源選項裡的「睡眠」設定：電腦不再自動睡眠。螢幕仍可照電源計畫，或設定「閒置 N 分鐘後主動關螢幕」
   變暗／關閉，以保護螢幕、省電。闔上筆電蓋、手動睡眠、低電量、Windows Update 重開機擋不住。
5. 網頁**設定頁**加「保持清醒」卡片（開關＋閒置幾分鐘關螢幕＋上面的提醒），接 `POST /api/runtime/keep-awake`。
6. 排查步驟文件：`powercfg /requests`、`/sleepstudy`（系統管理員）、網路卡「允許電腦關閉這個裝置以節省電源」、DAM。

**沒做**：不修改任何電源設定、網路卡設定或登錄檔（只讀、只請求）；在這台只讀了 `AoAc`，**沒有真的讓它進待命實測**。
提醒文字只有正式中文（網頁介面與 doctor 本來就只有中文）。

## 附記 2026-11-13（hotfix）：SC_MONITORPOWER 在現代待命機型上＝睡眠

實測：閒置 N 分鐘廣播 `SC_MONITORPOWER` 關螢幕後，事件記錄 Kernel-Power 506「The system is entering Modern Standby —
Reason: SC_MONITORPOWER」、566「Reason SleepButton」——**螢幕一關電腦就睡了**，跟本 ADR 要的（螢幕暗、電腦照跑）相反。

改成：
- `screen_off_after_min = N > 0`：把目前電源計畫的「關閉顯示器前的時間」（VIDEOIDLE，插電＋電池）設成 N 分鐘，由 Windows 自己關螢幕
  （這個計時只關螢幕，不讓電腦進入待命；睡眠由「睡眠啟動時間」＋系統清醒請求決定）。只在設定改變時寫一次；停用、改回 0／-1、
  App 停止時改回原值，而且只在值還是 SYNOX 寫的那個時才改回（使用者自己改過就不動）。這推翻上面「不修改任何電源設定」的這一項。
- 不設上限（原本 0～240）；只防溢位（≤ 525600 分鐘）。
- `-1`＝螢幕永不關（PowerRequestDisplayRequired）。
- `SC_MONITORPOWER` 整個拿掉，不要再用。

已知限制：SYNOX 當掉（沒走到 release）時，電源計畫會留著 N 分鐘；下次啟動不會知道原值。
