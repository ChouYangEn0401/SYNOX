# S5：要不要要求 web-ddgs 這類帶警告的 pack 宣告 `runtime.container`

狀態：待處理（要擁有者決定；SYNOX 這邊不用改程式，改的是工具庫與作者端）

## 問題一句話

作者自己標「建議在 docker 執行」的 pack（例如 web-ddgs），要不要請（或要求）它在 `pack.json` 宣告 `runtime.container`，讓 SYNOX 自己的容器路徑能用，而不是只靠 pack 自己設定的外部 worker？

## 脈絡

- SYNOX 只有在三件事都成立時才把工具放進容器：pack 宣告 `runtime.container`、擁有者安裝時選「用容器」、這台 PATH 上有 podman／docker（[ADR 0041 §5.2](../../adr/0041-pack-warnings.md)）。
- web-ddgs（`kind=cli`、要連網、帶 `vendor_no_security_guarantee`）**沒有** `runtime.container`：SYNOX 跑的是它自己的 CLI，用這台的後端（Windows 個人版＝none）；
  它把第三方搜尋套件交給自己設定的隔離 worker，那一層在 SYNOX 外面，SYNOX 看不到、驗證不了。
- S1 之後，這類 pack 的「這台實況」會寫「這台沒有可用的隔離，這個工具會以你的權限直接執行」；宣告了 `runtime.container` 的 pack 會改寫「有提供容器（已偵測到／沒偵測到）」。
- S2 之後，伺服器版這類 pack 沒有真隔離就只給擁有者；有宣告容器、選了容器、有引擎＝給成員。宣告容器對伺服器版的人有直接好處。
- `runtime.container` 的映像要 `docker.io`／`ghcr.io`／`quay.io` 帶 digest（第 1 關），作者要自己發佈映像。
- 宣告 `network: true` 的容器仍然連得到外面（只是看不到主機的檔案）；搜尋類的工具一定要網路。

## 選項

| 選項 | 一句話 | 建議 |
|---|---|---|
| A | 建議但不強制：工具庫的上架說明與 SDK 文件寫「帶 `vendor_no_security_guarantee` 的 pack 請提供 `runtime.container`」，並直接請 web-ddgs 的作者加上 | ✅ 建議（預設做這個） |
| B | 工具庫強制：帶這個警告、又是 `kind=cli`／`mcp stdio` 的 pack，沒有 `runtime.container` 就不上架 | |
| C | SYNOX 強制：安裝時（第 1 關）拒絕這種組合 | 不建議（跟「一律可以安裝」衝突） |
| D | 不做：維持現狀，靠 S1 的實況那一行讓使用者自己判斷 | |

## 驗收

- 選 A：工具庫上架說明與 `docs/pack-format.md`（或 SDK 文件）有一段建議；web-ddgs 的作者收到請求（記錄在工具庫那邊）；
  宣告之後，用真機清單 C-1～C-5 驗一次它的安裝報告與 doctor。
- 選 B：工具庫的打包／上架檢查有這條規則與測試；現有上架的這類 pack 列一張清單、通知作者。
- 選 D：在 ADR 0041 §5.4 把 S5 標成「不做」並寫原因。

## 不要做的事

- 不要替作者寫或發佈他的容器映像，也不要在 SYNOX 裡替沒宣告的 pack 自動開容器。
- 不要放寬第 1 關的映像規則（例如收 `localhost/…`、沒有 digest 的 tag）來遷就作者。
- 不要在這台開發機拉或執行任何第三方映像來試。
