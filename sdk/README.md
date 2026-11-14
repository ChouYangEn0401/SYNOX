# synox-sdk（SYNOX 的工具 SDK，單獨發佈的那一份）

一個檔 `synox_sdk.py`、只用標準函式庫。寫工具的人用它把 Python 函式變成 SYNOX 工具（也是 MCP stdio 工具）。
用法見 [../docs/sdk.md](../docs/sdk.md)；為什麼工具要宣告 SDK 版本見 SYNOX_Libs 的 `docs/adr/0001-tool-library-and-sdk-dependency.md`。

## 怎麼拿

| 情況 | 做法 |
|---|---|
| 工具資料夾裡直接放一份（打包時會一起進 `.synoxpack`） | 複製 `synox_sdk.py`；或 `synox-sdk init --from tool.py` 自動放 |
| 在自己的 venv 裝（開發、測試） | `pip install <SYNOX 資料夾>/sdk` |

## 版本

- 版本只有一個地方：`synox_sdk.py` 的 `SDK_VERSION`（`pyproject.toml` 直接讀它）。
- 工具的 `pack.json` 要寫 `"requires": {"sdk": ">=0.2,<0.3"}`：SYNOX 安裝、載入時對這台的 `SDK_VERSION`，不合就不裝、不載入並說原因。
  `synox-sdk init` 會自動寫好（`synox_sdk.SDK_REQUIRES`）。

## 不要直接改這個檔

正本是 `src/synox/sdk/author.py`；改完跑 `scripts/build_synox_sdk.py` 重產（`--check` 只比對，測試也會比）。
