# 保持清醒開著，Google Drive 還是斷線？——現代待命機型的排查步驟

保持清醒（[ADR 0006](adr/0006-keep-awake-screen-may-sleep.md)）像一個穩定的 heartbeat：維持系統運轉，但螢幕可以暗（保護螢幕或省電）。
它只**請求** Windows 不要自動睡眠；它**不會修改**你的電源設定。下面每一步也都只是「看」，要不要改設定由你決定。

> ⚠️ 開啟後會覆蓋 Windows 電源選項裡的「睡眠」設定：電腦不再自動睡眠。螢幕仍可照電源計畫，或設定「閒置 N 分鐘後主動關螢幕」
> 變暗／關閉，以保護螢幕、省電。闔上筆電蓋、手動睡眠、低電量、Windows Update 重開機擋不住。

## 先知道：現代待命是什麼、SYNOX 擋得住哪些

很多新筆電沒有傳統的「睡眠（S3）」，而是「現代待命」（Modern Standby，又叫 S0 低電源閒置）：螢幕一關，Windows 就開始一步步
讓程式安靜下來，最後由「桌面活動調節器」（Desktop Activity Moderator，DAM）**暫停所有桌面程式**——Google Drive 桌面版就是
桌面程式，被暫停就斷線。`doctor` 或網頁設定頁會告訴你這台是不是現代待命機型。

Microsoft 文件（[Prepare software for modern standby](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/prepare-software-for-modern-standby)、
[PowerSetRequest](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-powersetrequest)）寫的行為：

| 狀況 | SYNOX 的清醒請求 |
|---|---|
| **插電**、閒置逾時 | 擋得住：Windows 停在進入待命前的階段，不會走到 DAM 暫停程式（螢幕照樣可以關） |
| **用電池**、閒置逾時 | 只多撐 **5 分鐘**，之後請求被 Windows 終止 |
| 按電源鍵、闔上蓋子、開始選單「睡眠」 | 擋不住：使用者主動睡眠會終止所有請求 |
| 低電量、Windows Update 重開機、當機 | 擋不住 |

所以最常見的斷線原因是：**用電池**、**闔蓋**、或**網路卡自己省電斷線**（不是整台睡著）。

## 排查步驟

1. **看 SYNOX 的請求有沒有真的在**（以系統管理員身分開「終端機」或「命令提示字元」）：

   ```
   powercfg /requests
   ```

   保持清醒開著時，`SYSTEM:` 底下應該看得到 SYNOX 的 Python（原因寫「SYNOX 背景任務執行中，請不要讓電腦睡著」），
   新版 Windows 的 `EXECUTION:` 底下也會有。沒有＝SYNOX 沒在跑、或保持清醒沒開（網頁設定頁看狀態）。

2. **看斷線那段時間電腦到底在做什麼**（系統管理員）：

   ```
   powercfg /sleepstudy
   ```

   會在目前資料夾產生 `sleepstudy-report.html`。用瀏覽器打開，找 Google Drive 斷線的時間：
   - 那段是 **Screen off**（螢幕關、系統醒著）還是 **Sleep**（真的進待命）？
   - 進待命的原因（Entry reason）是電源鍵、闔蓋、還是閒置？是不是在用電池？
   - 「Networking in standby」是 connected 還是 disconnected？
   事件檢視器也看得到：Windows 記錄 → 系統，來源 `Kernel-Power`，事件 506（進入現代待命）、507（離開）。

3. **網路卡的省電**：裝置管理員 → 網路介面卡 → 你的 Wi-Fi（或有線網路卡）→ 內容 → 「電源管理」分頁，
   看「**允許電腦關閉這個裝置以節省電源**」有沒有勾。勾著時，系統沒睡、網路卡也可能被關掉，Google Drive 一樣斷線。
   要不要取消勾選由你決定（SYNOX 不會替你改）。

4. **DAM（桌面活動調節器）**：一旦真的進入現代待命，桌面程式（包括 Google Drive）一定會被暫停，這是 Windows 的設計，
   沒有程式能例外。要它不斷線，只能讓電腦不要進待命：插電、不要闔蓋、不要按電源鍵。

5. 還是不行：把步驟 2 的報告（只看時間與原因那幾列，報告裡有電腦名稱，不要整份貼到公開的地方）帶去問。

## SYNOX 做了什麼、沒做什麼

- 做了：同一個請求物件設「系統清醒」（`PowerRequestSystemRequired`）與「行程繼續執行」（`PowerRequestExecutionRequired`，
  舊版 Windows 沒有就略過）；用 `CallNtPowerInformation(SystemPowerCapabilities)` 的 `AoAc` 判斷是不是現代待命，顯示上面的說明。
- 沒做：不改電源計畫、不改網路卡設定、不改登錄檔、不阻止你手動睡眠。SYNOX 結束時 Windows 會自動收回請求。
