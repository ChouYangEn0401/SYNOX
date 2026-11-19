# 外觀包的套用：向前相容與套用檢查（真機清單）

> **這份清單全部勾完才算過關。** 自動測試全綠不等於過關：第二節每一項都要在真機上由人走一遍、填結果欄。
> 有任何一項「失敗」或空著，這個功能就不算驗收完成。

- 對應：[ADR 0042](../adr/0042-theme-tokens-single-source-and-forward-compat.md)、程式 `src/synox/theme/contract.py`、
  `src/synox/theme/check.py`、自動測試 `tests/test_theme_compat.py`、`tests/test_theme.py`。
- 結果欄怎麼填：`通過`／`失敗（一句話原因）`、日期 `YYYY-MM-DD`、驗證者（代號即可，不寫真名、不寫信箱）。
- 只裝外觀包、看畫面；外觀包沒有程式，不會執行任何東西。

## 一、自動測試涵蓋什麼（`python -m pytest -q -p no:cacheprovider tests/test_theme_compat.py tests/test_theme.py`）

| 範圍 | 測什麼 | 測試名 |
|---|---|---|
| 單一來源 | 送出去的 `:root` 三段＝contract；app.html 的 token 區沒有顏色、沒有留下記號 | `test_contract_tokens_are_defined_and_defaults_match_app_html` |
| 單一來源 | 提醒視窗、登入小頁從 contract 拿；`kit.css`、手機入口的副本值對得上 | `test_other_places_take_colours_from_the_contract`、`test_static_copies_still_match_the_contract` |
| 沒有缺色 | 網頁（含 include 的 CSS／JS、預覽頁）用到的 `var(--x)` 都有定義；預設的字對比度 ≥ 4.5 | `test_every_var_used_by_the_web_ui_is_declared`、`test_synox_defaults_are_readable` |
| 舊包 | 只有核心 12 色的包照裝，每個 token 都有值、沒有要注意的 | `test_old_pack_with_only_the_core_colours_passes_and_every_token_has_a_value` |
| 新 SYNOX＋舊包 | 假裝 SYNOX 多一個 token：照裝；網頁（淺色、深色）與預覽頁都有值；外觀包的 CSS 不蓋它；清單標「要注意」 | `test_newer_synox_old_pack_falls_back_to_synox_defaults`、`test_newer_synox_old_pack_applies_in_the_real_page` |
| 新包＋舊 SYNOX | 不認得的 token、slot、`var(--x)`：照裝、忽略、出現在報告；值不合照樣拒 | `test_newer_pack_installs_and_ignores_what_synox_does_not_know`、`test_value_problems_are_still_refused` |
| 清單與 CLI | 每個 token 淺色深色分開、slot 一段；摘要、`--details`、`--json`、`install --details` | `test_full_pack_check_lists_every_token_per_mode`、`test_cli_theme_check_summary_details_and_json`、`test_cli_entry_points` |

**自動測試沒涵蓋的**：真的瀏覽器畫出來的顏色（看得清楚、沒有透明或黑底黑字）、「展開看每一項」實際的樣子、重新整理之後還在、
手機寬度。這些都在第二節。

## 二、準備測試用的外觀包（假資料）

都從 `tests/fixtures/theme_pack` 複製一份出來改 `pack.json`，再用 `python scripts/pack_zip.py <資料夾>` 打包成 `.synoxpack`
（`name` 各改一個，例如 `test-old`、`test-full`、`test-newer`，才不會互相覆蓋）。

| 包 | 怎麼改 `pack.json` |
|---|---|
| **舊包** `test-old` | `theme.tokens.light`、`dark` 只留 `bg surface text muted line accent accent-ink accent2 soft ok warn bad` 這 12 個 |
| **完整包** `test-full` | 不改 token（範例包本來就給了核心色、吉祥物色、圓角、字型） |
| **比 SYNOX 新的包** `test-newer` | `tokens.light` 加 `"glow-x": "#ff00aa"`；`tokens.dark.soft` 改成 `"color-mix(in srgb, var(--future-tone) 20%, transparent)"`；`slots` 加 `"mascot.dance": "slots/idle.svg"` |

（「SYNOX 比外觀包新」這個情況現在的 SYNOX 沒有新 token 可以真的試；由自動測試假裝多一個 token 驗。真機用「舊包」驗沒給的都有值。）

## 三、必須在真機人工驗證的項目

每一項：照步驟做 → 對照預期 → 填結果。沒做到的不要勾。

### 3.1 安裝報告

- [ ] **T1 舊包的報告**
  - 步驟：網頁「設定 → 功能與安裝」上傳 `test-old.synoxpack`，看報告（先不要按確認）。
  - 預期：有「套用檢查」一段：淺色、深色各一行數字（外觀包有給 12、用外觀包自己的顏色算若干、沿用 SYNOX 預設若干）、位置一行；
    「✅ 沒有要注意的」；點「展開看每一項」看得到淺色、深色兩張表和位置表，每一列都有結果。可以照常按確認安裝。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **T2 比 SYNOX 新的包的報告**
  - 步驟：上傳 `test-newer.synoxpack`。
  - 預期：**沒有被拒**；「⚠️ 要注意 3 項」：淺色 `--glow-x` 忽略、深色 `--soft` 沿用 SYNOX 的（寫出 `--future-tone`）、`mascot.dance` 忽略；
    展開後這幾列標 ⚠️。可以照常按確認安裝。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **T3 終端機的報告**
  - 步驟：`python -m synox install test-newer.synoxpack`（不加 `--yes`）→ 再加 `--details` 跑一次。
  - 預期：第一次只有摘要、要注意的 3 項，最後一行提示「加 --details」；第二次多出「淺色的每一個 token」「深色的每一個 token」「位置」三段。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **T4 `packs theme-check`**
  - 步驟：三個包都裝好後，`python -m synox packs theme-check test-old`、`… test-newer --details`、`… test-full --json`。
  - 預期：`test-old` 結束碼 0、`test-newer` 結束碼 10（有要注意的）；`--json` 是一份 JSON，有 `tokens.light`、`tokens.dark`、`slots`、`counts`、`issues`、`blocking: false`。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 3.2 套用（設定 → 外觀）

- [ ] **T5 外觀卡上的清單**
  - 步驟：到「設定 → 🎨 外觀」。
  - 預期：每張外觀卡在「套用」按鈕上面有一行套用檢查（✅ 沒有要注意的／⚠️ 要注意 N 項＋那幾項），「展開看每一項」收著；
    展開後看得到數字和三張表；卡片在手機寬度（約 360px）不會被撐出畫面。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **T6 套用舊包：淺色**
  - 步驟：「預覽」切淺色，套用 `test-old`；外觀的淺色／深色選「淺色」。
  - 預期：整頁換成這套的顏色；側欄、對話泡泡（我的、AI 的）、輸入框、按鈕、狀態標籤（能用／注意／壞了）、等回覆的方塊、
    設定頁每一個分頁的卡片，**沒有一處是透明、看不到字、或黑底黑字**。吉祥物顏色跟著這套的主色（用算的）。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **T7 套用舊包：深色**
  - 步驟：同 T6，淺色／深色改「深色」；再改「跟著系統」，把作業系統切到深色。
  - 預期：同 T6 的每一處都看得清楚；兩種深色（強制、跟著系統）看起來一樣。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **T8 套用完整包**
  - 步驟：套用 `test-full`，淺色、深色各看一次。
  - 預期：清單「✅ 沒有要注意的」；顏色、圓角、字型、吉祥物、開場、字標、分頁圖示、對話背景都換成範例包的；沒有缺色。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **T9 套用比 SYNOX 新的包**
  - 步驟：套用 `test-newer`，淺色、深色各看一次。
  - 預期：**整個外觀有套上**（不是退回原本的 SYNOX）；深色時「主色的淡底」（選到的對話、標籤底色）是 SYNOX 原本的淡青綠，其他是這套的顏色；
    吉祥物照範例包；沒有缺色。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **T10 重新整理後維持**
  - 步驟：T6～T9 每一次套用後按 F5、關掉分頁再打開。
  - 預期：一打開就是套用的那一套（沒有先閃原本的 SYNOX 顏色），淺色／深色的選擇也還在。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

- [ ] **T11 換回原本的 SYNOX**
  - 步驟：按「換回原本的 SYNOX」，淺色、深色各看一次；再看登入卡（登出後的畫面）與登入失敗的小頁。
  - 預期：顏色跟這次改版之前的 SYNOX 一模一樣（可以拿舊版的截圖對）；「原本的 SYNOX」那張卡的預覽跟真的網頁同色。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿

### 3.3 其他跟著外觀走的地方

- [ ] **T12 電腦提醒視窗**（只有 Windows 個人版）
  - 步驟：套用 `test-old` 後，設一個一分鐘後的提醒，等視窗跳出來；再換回原本的 SYNOX 再試一次。
  - 預期：視窗顏色跟著外觀；換回原本的時候跟改版前一樣；字都看得清楚。
  - 結果：＿＿＿＿　日期：＿＿＿＿　驗證者：＿＿＿＿
