# packs/：你裝的工具放這裡

SYNOX 出廠**不帶任何工具**（2026-11-12 起，連接 Notion／Todoist／Google 日曆／Apple 的也在工具庫；為什麼見
[../legacy/builtin-packs.md](../legacy/builtin-packs.md)、[../legacy/connectors.md](../legacy/connectors.md)）。
這個資料夾是安裝的落點：你裝的每個工具會變成這裡的一個子資料夾（`packs/<名字>/`），移除或升級時舊的搬到 `packs/_removed/`。
裡面的東西不進 git（`.gitignore`），只有這份說明。

## 工具從哪裡來

工具放在另一個專案 **SYNOX_Libs（工具庫）**：每個工具一個 `.synoxpack` 壓縮檔，加一份目錄 `index.json`（名稱、版本、說明、建議群組、雜湊）。
挑你要的裝就好。工具庫在哪裡，問給你 SYNOX 的人；也可以寫進 `config.json` 的 `packs.library`，`doctor`、`/help`、網頁就會提示那個位置。

## 怎麼裝（四條路都跑同一條安全檢查，按確認才裝；詳細見 [../docs/install-packs.md](../docs/install-packs.md)）

1. 點兩下 `.synoxpack`（`Setup.bat` 替這個 Windows 使用者登記了檔案類型與圖示；就是 `Install-Pack.bat`）。
2. 把 `.synoxpack` 拖到 `Install-Pack.bat` 上。
3. 拖進 SYNOX 網頁（任何一頁），或「設定 → 功能」選檔按「上傳並檢查」，看完報告按確認。
4. 終端機：`.venv\Scripts\python.exe -m synox install <檔案>.synoxpack`。

開發工具的人也可以不裝、直接讓 SYNOX 讀一個資料夾：`config.json` 的 `"packs": {"dirs": ["<工具庫>/packs"]}`。

**不要手動複製資料夾進來**：沒走安裝流程的工具沒有 `packs.lock`（雜湊鎖），伺服器版會當成第三方、只給擁有者。
