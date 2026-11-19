# MXC 探針（`wxc-exec.exe`）能不能在驗證機上跑

狀態：待處理（要擁有者決定；沒決定＝不跑，清單 M-3 寫略過）

## 問題一句話

沙盒真機清單的 M-3 要用 Microsoft 的 `wxc-exec.exe`（從官方 npm 套件取出的執行檔）跑一次 MXC 探針；這是「執行下載來的程式」，驗證機上可不可以跑？

## 脈絡

- SYNOX **還沒有** MXC 後端；M-1（只讀盤點）與 M-2（SYNOX 不會因為「這台能跑 MXC」就說有隔離）不用下載任何東西，照常做。
- M-3 只是多一份「這台實際上 MXC 能做到什麼」的資料，給之後的 Windows 後端設計用；不做不影響 S1／S2／S4 的驗收。
- 取得與執行的作法寫在 `docs/lab/tools/windows-sandbox-probe/README.md`：從官方 npm registry 抓 `@microsoft/mxc-sdk` 的壓縮檔、不跑安裝腳本、先看 Authenticode 簽章；
  探針會建一個暫存資料夾、開一個只綁 127.0.0.1 的監聽埠，`--net` 時試連外一次；MXC 會送幾種關不掉的遙測給 Microsoft（README 有寫）。
- 規則：下載來的東西一律當資料、不在本機執行；真的要執行要先問擁有者、提出隔離的作法。
- Windows 上 AppContainer／MXC 的取捨另有研究，待擁有者決定後再開交辦；M-3 的結果會是那個決定的參考之一。
- MXC 要 Windows 11、build ≥ 26200.9278（M-1 會記下來）；build 不夠的機器 M-3 本來就做不了。

## 選項

| 選項 | 一句話 | 建議 |
|---|---|---|
| A | 不跑：M-3 寫「略過（擁有者未同意）」，等 Windows 後端那個決定做了再說 | ✅ 建議（預設做這個） |
| B | 只在一台拋棄式的 Windows 11 VM（或 Windows Sandbox 裡）跑，照 README 的作法；結果只帶回 JSON 與文字 | |
| C | 在驗證機上直接跑（照 README，驗簽章、不加 `--net`） | 不建議（驗證機也是實體電腦，遙測關不掉） |

## 驗收

- 選 A：清單 M-3 是「略過（擁有者未同意）」，第六節備註寫擁有者接受。
- 選 B／C：回報裡有 `wxc-exec.exe` 的版本、簽章檢查的輸出（`Status: Valid`、簽署者是 Microsoft）、探針結果 JSON；探針開的埠在結束後已放掉。

## 不要做的事

- 沒有擁有者明確同意，不要下載或執行 `wxc-exec.exe`，也不要用 npm 安裝 `@microsoft/mxc-sdk`。
- 不要在擁有者平常用的開發機上跑。
- 不要因為 M-3 的結果就去寫 MXC 後端（那是另一張交辦單）。
