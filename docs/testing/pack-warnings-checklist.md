# pack 標記警告（`warnings`）測試清單

> **這份清單全部勾完才算過關。** 自動測試全綠不等於過關：第二節每一項都要在真機上由人走一遍、填結果欄。
> 有任何一項「失敗」或空著，這個功能就不算驗收完成。

- 對應：[ADR 0041](../adr/0041-pack-warnings.md)、程式 `src/synox/packs/packwarn.py`、自動測試 `tests/test_pack_warnings.py`。
- 欄位格式（不變）：`"warnings": [{"code": "vendor_no_security_guarantee", "text": "官方不保證安全", "advice": "建議在 docker 或 sandbox 執行"}]`
- 結果欄怎麼填：`通過`／`失敗（一句話原因）`、日期 `YYYY-MM-DD`、驗證者（代號即可，不寫真名、不寫信箱）。
- **真機驗證的規矩**：用來測的 pack 只拿來「安裝、看畫面、確認」；**不要真的叫它的指令**（不執行第三方程式）。
  需要一個帶警告的 pack 時，用 `synox-sdk init` 做一個只有 `pack.json` 的假工具，自己加上 `warnings`；
  或拿工具庫裡已經帶警告的 pack（例如 DesktopAgent 的 `web-ddgs`），一樣只裝、不叫。

## 一、自動測試涵蓋什麼（`python -m pytest -q -p no:cacheprovider tests/test_pack_warnings.py`）

這些不用人工再驗；表列出來是讓驗收的人知道**哪些沒被自動測到**（第二節）。

| 範圍 | 測什麼 | 測試名 |
|---|---|---|
| 欄位形狀 | 好的格式照收；沒有 `warnings` 欄位＝跟以前一樣（鎖不多欄位、/help 與 AI 清單一個字不變） | `test_parse_good_shape`、`test_absent_field_is_old_behaviour`、`test_old_pack_lock_has_no_accepted_field` |
| 清理 | 換行、控制字元、零寬、雙向控制字元拿掉；60／120 字截斷 | `test_clean_control_zero_width_bidi_and_length` |
| 壞格式 | 不是清單、`null`、某條不是物件、code 不合格式 → 換成 `malformed_warning`，不讓 pack 掛掉；不認得的欄位照收、記問題；載入時寫 log | `test_malformed_becomes_visible_malformed_warning`、`test_unknown_keys_kept_but_reported`、`test_load_logs_problems` |
| 內建字與上限 | 認得的 code 沒寫字用內建的；同 code 只留第一條；最多 5 條 | `test_defaults_for_known_code_and_duplicates_and_cap` |
| 冒充與注入 | 像在對 AI 下指令、要跳過確認、夾分隔符、含「✅」→ 換成內建的字 | `test_text_that_talks_to_ai_or_fakes_badge_is_replaced` |
| 簽章涵蓋 | 拿掉／清空／改掉 `warnings` → `pack.sig.json` 驗不過；裝好後在 `packs/` 裡改 → `tampered` | `test_signature_covers_warnings`、`test_editing_warnings_after_install_is_tampered` |
| 官方＋不保證安全 | 暫存時、安裝的第 3 關、載入時都拒 | `test_official_plus_vendor_warning_refused_at_stage`、`test_install_gate_refuses_official_plus_vendor`、`test_official_plus_vendor_rejected_at_load` |
| 第一次啟用要確認 | 安裝少一個 code 就不裝；核准、升級沿用舊的、新 code 要再確認；鎖裡沒確認＝`unaccepted` 不載入 | `test_install_requires_accept`、`test_approve_installed_accept_and_carry_over`、`test_upgrade_new_code_needs_accept_old_code_carries`、`test_loader_unaccepted_then_accepted` |
| 終端機 | `--accept-warning` 旗標（install、tools install／update、packs lock）、說明文字 | `test_cli_install_accept_warning_flag`、`test_cli_help_lists_accept_warning` |
| 顯示（文字與 API） | 安裝報告紅字位置、/help 標題、`/api/tools`、`/api/settings`、工具庫清單、doctor | `test_install_report_text_is_prominent`、`test_help_title_and_help_page`、`test_tools_and_settings_api`、`test_tools_api_rows_have_warnings`、`test_catalog_and_local_library_show_warnings`、`test_doctor_lines_show_warning` |
| 網頁安裝 API | 沒勾的 code 送出去被拒；提示裡有「勾選」 | `test_web_install_needs_checkbox`、`test_web_hint_mentions_checkbox` |
| 給 AI | `data/agent_index.json` 的結構化 `warnings`；能力清單縮短也不丟警告；技能索引、`skill_read`、工具說明帶標記 | `test_agent_index_has_structured_warnings`、`test_agent_line_never_drops_warning`、`test_skills_and_skill_read_and_tool_description` |
| 外部 pack 的欄位 | 拿 DesktopAgent `web-ddgs` 的 pack.json 的 `warnings` 原樣餵 `packwarn.parse`：沒有問題、code 是 `vendor_no_security_guarantee` | `test_desktopagent_web_ddgs_shape` |

**自動測試沒涵蓋的**：真的瀏覽器裡的畫面（勾選框、按鈕會不會變灰、紅字看不看得清楚）、真的 Windows 安裝流程、真的終端機互動
（`synox init` 的逐條詢問）、真的 AI（本地或雲端模型）會不會把警告轉述給人。這些都在第二節。

## 二、必須在真機人工驗證的項目

每一項：照步驟做 → 對照預期 → 填結果。沒做到的不要勾。

### 2.1 安裝流程（網頁）

- [ ] **H1 帶警告的 pack：install → 確認 → 載入**
  - 步驟：網頁拖進一個帶 `vendor_no_security_guarantee` 的 `.synoxpack` → 看安裝報告 → 逐條勾「我知道」→ 按「確認安裝」→ 到設定頁看狀態。
  - 預期：報告在 SYNOX 標章正下方用紅字列出「⚠️ 這個工具的作者標了 1 個警告」與每條的 text、advice；沒勾之前「確認安裝」按不下去；
    勾完能裝；設定頁這個工具是開著的、旁邊有紅色警告標記；`data/packs.lock` 這一筆有 `accepted_warnings: ["vendor_no_security_guarantee"]`。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **H2 沒勾就不能裝**
  - 步驟：同 H1，但不勾任何一條，試著按確認；再用瀏覽器開發者工具把按鈕的 disabled 拿掉硬按一次。
  - 預期：按不下去；硬按時伺服器回錯誤，訊息寫是哪一條警告沒確認、怎麼確認；`packs/` 裡沒有這個工具。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **H3 網頁設定頁的勾選與顯示**
  - 步驟：設定 →「🧩 功能與安裝」找到這個工具；再找一個「已裝但還沒確認」的（用舊版 SYNOX 裝的，或手動在 `packs.lock` 拿掉 `accepted_warnings` 後重開）。
  - 預期：每列有紅色標記與建議；沒確認的那個寫「有警告還沒確認，先不開」，而且真的沒載入（/help、AI 清單都看不到它）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **H4 網頁工具頁**
  - 步驟：打開「工具」頁看這個工具。
  - 預期：標題旁紅色標記、「⚠️ 作者標的警告」一段每條一行；標章**不是**「✅ 官方」。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 2.2 終端機

- [ ] **H5 `synox init` 逐條詢問**
  - 步驟：在乾淨的資料夾跑 `python -m synox init`，在選工具那一步選一個帶警告的工具。
  - 預期：每條警告各問一次（「⚠️ 〈text〉——〈advice〉　我知道，還是要裝〈名字〉？」），**預設是「不要」**（直接按 Enter＝不裝）；
    每條都答「要」才裝；有一條答「不要」，結果寫「有警告沒確認，沒裝」。不是互動模式（例如 `--yes` 自動跑）時不裝，
    結果寫要加哪些 `--accept-warning` 才裝。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **H6 `install --accept-warning`**
  - 步驟：`python -m synox install <檔>.synoxpack --yes`（不帶旗標）→ 再加 `--accept-warning vendor_no_security_guarantee` 跑一次。
  - 預期：第一次不裝，紅字列出警告與要加的旗標；第二次裝好。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **H7 升級多一條警告**
  - 步驟：裝好 v1（一條警告、已確認）→ 拖進 v2（多一條新 code）。
  - 預期：升級報告紅字列出「新的警告」只有新的那條；舊的沿用不再問；沒勾新的就不升級；升級後鎖裡兩個 code 都在。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 2.3 不影響別的東西

- [ ] **H8 舊 pack 不受影響**
  - 步驟：裝一個沒有 `warnings` 欄位的工具（工具庫裡現有的任一個），走完安裝；看 /help、設定頁、工具頁、doctor；再跟這個分支之前的版本比較同一個工具的畫面。
  - 預期：沒有任何警告字、沒有多的勾選框、安裝流程跟以前一樣；`packs.lock` 這一筆**沒有** `accepted_warnings` 欄位。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **H9 簽章被改後安裝失敗**
  - 步驟：拿一個有 `pack.sig.json` 的帶警告 pack，解開 → 把 `pack.json` 的 `warnings` 整段刪掉（或改一個字）→ 重新壓成 `.synoxpack` → 拖進網頁。
  - 預期：報告最上面是「⛔ 被改過」，沒有確認鈕，`packs/` 裡沒有它。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **H10 裝好之後改 `warnings`**
  - 步驟：裝好一個帶警告的工具 → 直接在 `packs/<名字>/pack.json` 刪掉 `warnings` → 重開 SYNOX。
  - 預期：這個工具狀態是「被改過」（`tampered`），不載入；doctor 說明原因。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 2.4 給 AI 看的部分

- [ ] **H11 AI 對話中警告有被轉述**
  - 步驟：用真的模型（本地模型與一個雲端模型各一次），對 AI 說「用〈這個工具〉幫我查 X」。**在核准卡出現時按「不要」或取消**（不讓第三方程式真的跑）。
  - 預期：AI 在要用這個工具之前，先把警告原文（「官方不保證安全」與建議）告訴使用者；沒有把它說成官方或安全的。記下模型名稱。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿　模型：＿＿＿＿

- [ ] **H12 /help 與 Telegram／Discord 的清單**
  - 步驟：在 Telegram（或 Discord）打 `/help`，找這個工具所在的群組。
  - 預期：群組標題帶「⚠️ 官方不保證安全」；卡片的標籤也帶；其他沒有警告的群組標題不變。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 2.5 執行環境（跟沙盒的關係，見 ADR 0041 §6）

- [ ] **H13 報告上的「建議在 docker 或 sandbox 執行」對得上這台的實際狀況**
  - 步驟：在 Windows 個人版（沒有裝 docker）看 H1 的報告與設定頁「沙盒模式」那張卡；再看 doctor 的「沙盒」那一行。
  - 預期：設定頁與 doctor 照實寫「這台目前沒有沙盒」；報告上作者的建議照樣顯示（它是作者的字），使用者不會因為看到「sandbox」而以為 SYNOX 已經幫他隔離了。
    如果畫面讓人誤會，記「失敗」並寫哪一句讓人誤會。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **H14 有提供容器的帶警告 pack**（這台有 docker 或 podman 才做；沒有就寫「略過：沒有容器引擎」）
  - 步驟：裝一個 pack.json 有 `runtime.container`、又帶 `vendor_no_security_guarantee` 的工具，在報告的「🧱 執行環境」選「用容器」。
  - 預期：裝好後 doctor／`packs status` 那一行寫「🧱 容器（docker 或 podman）」；**不要真的叫它的指令**，只看設定。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

## 三、驗收紀錄

| 輪次 | 日期 | SYNOX 版本／commit | 機器（只寫作業系統與版本） | 全部通過？ | 驗證者 |
|---|---|---|---|---|---|
| 1 | | | | | |
