# 交接：到另一台電腦做真機測試

開發用的電腦只用程式內的假傳輸測過 connector 和 Discord；這個資料夾是「帶到另一台可以上網的電腦，用真的帳號試」的全部東西。

| 文件／程式 | 做什麼 | 先讀順序 |
|---|---|---|
| [real-service-testing.md](real-service-testing.md) | 準備那台電腦、Notion／Todoist／Google 日曆／Apple 提醒事項的憑證與設定、跑煙霧測試、錯誤排除、清理、回報格式、安全守則 | 1 |
| [discord-handoff.md](discord-handoff.md) | Discord 從零到上線：建 bot、intent、邀請、id、存 token、配對、config 範例（私訊型、頻道型、多 bot、頻道 AI）、排查、D1–D18 測試清單、已知限制 | 2 |
| [clean-machine-test.md](clean-machine-test.md) | 空白 Windows（VM 或新的使用者帳號）上裝 SYNOX：git clone 路線、安裝程式的建置（發佈機）與安裝、可勾選的步驟與預期、失敗時回報什麼 | 另一條線（安裝，QL4） |
| [container-verification.md](container-verification.md) | 容器隔離（podman／Docker）與 Linux 沙盒（bwrap／systemd）的真機驗證：給那台 Claude 的 prompt、探針 pack、C／M／B 檢查清單（每項：做什麼、預期、失敗代表什麼） | 另一條線（Linux 實驗室） |
| [`scripts/smoke_real.py`](../../scripts/smoke_real.py) | 煙霧測試：用各 connector 自己的程式逐一試唯讀操作；`--write` 才做一個建立後立刻刪掉的小寫入（要輸入 yes）；最後印一段可貼進部署測試板的摘要 | 照第 1 份第 3 節跑 |

最短路徑：

```
git clone https://github.com/ChouYangEn0401/SYNOX.git && cd SYNOX && git checkout dev
Setup.bat                                             （或自己建 .venv、pip install -e .）
Console.bat → /notion_token、/todoist_token、/gcal_setup …（存憑證）
Connect-Apple.bat                                     （Apple）
.venv\Scripts\python.exe -m synox discord token        （Discord）
.venv\Scripts\python.exe scripts\smoke_real.py         （唯讀測試，把最後那段貼進部署測試板）
```

三條守則：token 不貼到任何聊天、`config.json` 和 `data` 不進 git、測試用專用帳號。
