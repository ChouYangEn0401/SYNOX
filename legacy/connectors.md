# 下架：出廠內建的 4 個 connector（notion、todoist、google-calendar、apple-reminders）

2026-11-12 起 SYNOX 主程式**真的全空**：繼三個內建工具（[builtin-packs.md](builtin-packs.md)）之後，`connectors/` 的 4 個也搬到工具庫，
`connectors/` 只剩一份說明。

## 原本做什麼

| 工具（pack 名字） | 原本的資料夾 | 指令（例） | 做什麼 | 資料（保管箱） |
|---|---|---|---|---|
| 🗂 Notion（`notion`） | `connectors/notion/` | `/notion 會議`、`/notion_read`、`/notion_row`、`/notion_token` | 用你自己的 integration token 搜尋、讀頁面、加資料庫一列、改欄位 | `data/notion.json.enc` |
| ✅ Todoist（`todoist`） | `connectors/todoist/` | `/todoist !! 繳電費 明天`、`/todoist_list`、`/todoist_done 3` | Todoist API v1：看、加、完成、改期 | `data/todoist.json.enc` |
| 📅 Google 日曆（`google-calendar`） | `connectors/google-calendar/` | `/gcal 明天 14:00 看牙醫`、`/gcal_today`、`/gcal_setup` | Calendar API v3＋OAuth（PKCE、貼回網址、不開埠） | `data/google-calendar.json.enc` |
| 🍎 Apple 提醒事項（`apple-reminders`） | `connectors/apple-reminders-caldav/` | `/applerem`、`/applerem_add`、`/applerem_status` | 通用 CalDAV VTODO 用戶端（iCloud 升級過的提醒事項 Apple 不開放） | `data/apple-reminders.auth.json.enc` |

伺服器版是 `data/users/<id>/` 底下同名的檔。四個都是 `kind: python`、`capabilities: ["network"]`、只用 requests，
`src/synox/packs/loader.py` 的 `BUNDLED` 把它們當成「出廠＝信任（core）」，不用安裝、不看 `packs.lock`。
測試（`tests/test_notion.py`、`test_todoist.py`、`test_gcal.py`、`test_apple_reminders.py`）全部用假的 HTTP。

## 為什麼下架

擁有者 2026-11-12 回答 [QuestionToUser.md](../QuestionToUser.md) 的 QL1（「這 4 個要不要也搬去工具庫」，一字不改）：

> QL1 當然要，而且所有工具目前都先幫我註記為 "測試版本 test/alpha/beta' 之類的。

> 我現在就是希望把所有這邊的工具都做統一管理。所以理論上只會剩下：我電腦的原始專案(現在仍會透過 telegram-bot 服務我)，然後就是 synox_lix 裡面的工具 duplication(會做成 public 版本去掉我的隱私項目，提供給別人)

寫死在主程式裡的工具繞過安裝流程（五關、雜湊鎖），而且新裝的 SYNOX `/help` 還是會看到它們（「還沒裝任何工具」的提示得把它們扣掉）。
搬到工具庫之後：主程式沒有任何工具、`BUNDLED` 是空的；四個工具在工具庫宣告 `requires.sdk`、`stage: alpha`、打包成 `.synoxpack`、有自己的測試。

## 搬到哪裡、改了什麼

- 正本：SYNOX_Libs 的 `packs/notion`、`packs/todoist`、`packs/google-calendar`、`packs/apple-reminders`
  （Apple 的資料夾名改成跟 pack 名字一樣；**pack 名字都沒變**，所以保管箱裡存的 token／帳號照用）。來源對照在工具庫的 `docs/sources.md`。
- 測試也搬過去了（工具庫 `tests/test_notion.py`…，測試本體沒改）。
- SYNOX 這邊：`loader.PACK_DIRS` 不再掃 `connectors/`、`loader.BUNDLED` 清空；`scripts/smoke_real.py`（真服務煙霧測試）
  先找這台裝好的工具，沒裝就讀工具庫的原始碼（環境變數 `SYNOX_LIBS`）；`Connect-Apple.bat`／`python -m synox connect apple-reminders`
  照舊，但要先裝好 apple-reminders。
- 伺服器版：以前這 4 個沒鎖也是 core；現在跟其他工具一樣，擁有者安裝時選 trust（core／third-party），third-party 的 python 工具只給擁有者。

## 從舊版更新上來的人

- 更新後 `/help` 裡這 4 組指令會不見，**資料沒有動**（保管箱的檔照舊）。
- 從工具庫裝同名的工具（`notion`、`todoist`、`google-calendar`、`apple-reminders` 的 `.synoxpack`）就回來，token／帳號不用重設。
- 用解壓縮蓋過舊版的：舊的 `connectors/<名字>/` 可能還留在磁碟上，SYNOX 不會再讀它，可以自己刪。

## 怎麼救回（不建議，除非工具庫拿不到）

原始碼在 git 歷史裡，最後一版是搬走那個 commit 的上一個：

```
git log --oneline -1 -- connectors/notion          # 找到「搬走」的那個 commit，它的上一個就是最後一版
git checkout <那個 commit>^ -- connectors tests/test_notion.py tests/test_todoist.py tests/test_gcal.py tests/test_apple_reminders.py
```

再把 `src/synox/packs/loader.py` 的 `PACK_DIRS` 加回 `os.path.join(ROOT, "connectors")`、`BUNDLED` 加回
`("apple-reminders", "google-calendar", "notion", "todoist")`，並把 `tests/conftest.py` 的 `DEFAULT_PACK_DIRS` 加回 `connectors/`。
比較好的做法是直接裝工具庫的 `.synoxpack`（同一份程式，多了 SDK 版本宣告與穩定度標示）。
