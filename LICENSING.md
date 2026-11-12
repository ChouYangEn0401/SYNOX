# SYNOX 授權說明

SYNOX 用**兩種授權**，目的是讓「接工具」很容易，同時讓「把 SYNOX 當服務架起來賣」要遵守開源規則。

| 範圍 | 授權 | 全文 |
|---|---|---|
| SYNOX 核心：`src/synox/`（SDK 目錄除外）、`docs/`、`tests/`、`packs/`、`connectors/`、安裝器與腳本 | **AGPL-3.0-or-later** | [LICENSE](LICENSE) |
| 工具 SDK：`src/synox/sdk/`、`sdk/`（`synox_sdk.py`、`pyproject.toml`、`README.md`）、`scripts/build_synox_sdk.py`、`examples/` | **Apache-2.0** | [LICENSE-APACHE](LICENSE-APACHE) |
| `vendor/isdtelekit/`（Telegram 通道函式庫的複本，來自上游） | **跟隨上游 isdtelekit 的授權** | 以上游 repo 為準（目前待維護者確認，見下方） |

Apache-2.0 的檔案開頭都有 `SPDX-License-Identifier: Apache-2.0`。沒有標示的檔案屬於核心，適用 AGPL-3.0。

## 這對你代表什麼

**你只是在用 SYNOX（自己用、公司內部用）**：隨便用，包括商用，不需要公開任何東西。

**你寫工具（pack）接進 SYNOX**：用 SDK（Apache-2.0）寫的工具，你可以自己決定授權，閉源、商用都可以。你的工具若只是透過 pack.json 與 SDK 被 SYNOX 載入，不會因此變成 AGPL。

**你改了 SYNOX 核心，而且把它架成網路服務給別人用**：AGPL 要求你把修改後的原始碼提供給使用這個服務的人。這是 AGPL 與 GPL 最大的差別。

**你想在不受 AGPL 限制的情況下使用或散布核心**（例如放進閉源產品）：需要向著作權人取得另外的商業授權。聯絡：`mi.anthony.chou@gmail.com`（同 [CONTRIBUTING.md](CONTRIBUTING.md)「聯絡」）。

## 著作權、署名與商標

- 著作權署名：**ChouYangEn and the SYNOX Team**。創始者的地位與署名保留方式見 [GOVERNANCE.md](GOVERNANCE.md)、[NOTICE](NOTICE)。

- 著作權屬於各貢獻者；專案維護者依 [CONTRIBUTING.md](CONTRIBUTING.md) 的貢獻者同意書取得再授權的權利，才能同時提供開源授權與商業授權。
- 「SYNOX」這個名稱與標誌不在授權範圍內，使用規則見 [TRADEMARK.md](TRADEMARK.md)。

## 還沒決定、需要維護者補上的事

- `vendor/isdtelekit/` 的授權：它是創始者自己的上游函式庫，請在上游 repo 加上授權（建議 Apache-2.0 或與核心一致），再把這份文件的對應列改成確定的授權。
- 這份文件不是法律意見。收費、簽商業合約或要註冊商標之前，請找懂開源授權的人看過。
