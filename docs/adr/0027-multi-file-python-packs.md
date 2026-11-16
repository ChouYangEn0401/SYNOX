# ADR 0027：kind=python 的工具可以是多個檔（`python.package`）

- 日期：2026-11-15
- 狀態：已採用（分支 `feat/pack-package`）
- 程式：`src/synox/packs/pkgload.py`（新）、`loader.py`（`_install_python`、`load_all` 安裝失敗時清模組）、
  `admin.py`（`reload` 清模組）、`manifest.py`（`python.package` 型別）、`scan.py`（`import` 這一種 finding）、
  `upgrade.py`（升級報告比 `python.package`）
- 測試：`tests/test_pack_package.py`
- 文件：[pack-format.md](../pack-format.md)「三種 kind → python → 多檔工具」

## 背景

kind=python 的工具以前只能是一個 `pack.py`：loader 用 `spec_from_file_location` 從原始碼編譯、執行那一個檔，
沒有子模組搜尋。工具一大（幾十個模組的引擎＋畫面轉接層），一個檔放不下；改用 kind=cli 又拿不到完整網頁畫面
（`web.app` 只給 kind=python）。

## 決定

1. pack.json 的 `python` 多一個選填鍵 `"package": true`。沒寫（或 `false`）＝單檔，行為完全不變；
   不是布林值＝pack.json 不合（安裝拒、已裝的不載入）；只有 kind=python 可以寫。
2. `package: true` 時 `pack.py` 以套件 `synox_pack_<名字>` 載入（`__path__` 是空的清單），工具自己的模組只能用
   **相對 import**（`from .engine import db`）。
3. SYNOX 在 `sys.meta_path` 最前面放一個載入器（`pkgload._Finder`），**只管登記過的 `synox_pack_<名字>.` 開頭的名字**：
   - 一律從 `.py` 原始碼編譯：不讀 `__pycache__`，不收 `.pyc`／`.pyw`／`.pyd`／`.so`；
   - 有 `packs.lock` 時，讀進來的那一份 bytes 先對鎖裡的 sha256 才編譯；被改過或鎖裡沒有這個檔＝`ImportError`；
   - 每一段名字都要是識別字、大小寫跟磁碟上一樣；`realpath` 不准跑出工具資料夾（符號連結／junction 指到外面＝`ImportError`）；
   - 主模組（`pack.py`）不能再被當子模組 import 一次；
   - 沒有 `__init__.py` 的資料夾當作空的套件。
4. 重新載入（`admin.reload`）、安裝失敗、單檔與多檔之間切換時，`pkgload.forget(名字)` 拿掉登記，
   `sys.modules` 裡 `synox_pack_<名字>` 與它底下的模組全部清掉。
5. 第 2 關（`scan.py`）：資料夾裡每一個 `.py` 本來就逐一被掃；相對 import 不算 exec、不用多宣告能力；
   **絕對 import 另一個工具的模組（`synox_pack_別人`）是新的一種 finding `import`，一律拒裝**（不是能力，宣告什麼都沒用）。
   絕對 import 自己（`synox_pack_<自己>.engine`）算認得的模組。
6. 升級報告：`python.package` 改了算「執行方式改了」（紅字），跟 `python.module` 一樣。

## 為什麼不把工具資料夾加進 sys.path

- `sys.path` 是整個程序共用的：兩個工具都有 `engine/` 時，先載入的那個會被另一個 `import engine` 拿到
  （互相干擾，也是一條跨工具讀別人程式／資料的路）。
- 標準的 `FileFinder` 會讀 `__pycache__` 裡的 `.pyc`。`.pyc` 雖然在鎖的雜湊範圍內，但它是編譯過的東西，
  第 2 關掃不到內容；單檔的 `pack.py` 早就刻意不讀 `.pyc`，多檔不能比它鬆。
- 標準載入器不會在編譯前對 `packs.lock`；載入時第 3 關驗完到函式裡延後 import 之間檔案被換掉就抓不到。
- 工具資料夾在 `sys.path` 裡，連 `import json` 都可能先找到工具資料夾裡的 `json.py`（換掉標準函式庫）。

## 已知代價

- 工具只能用相對 import 取用自己的模組；`import engine` 這種絕對寫法找不到（照搬別的專案的程式要改 import）。
- 不產生、不使用 `.pyc`：每次載入都從原始碼編譯，模組很多時啟動稍慢（幾十個檔是毫秒到幾十毫秒等級）。
- 有鎖時每個子模組在 import 當下多算一次 sha256（檔案小，成本低）。
- 工具裡的 `importlib.resources`、`pkgutil` 這類依賴標準載入器的功能不保證能用（`__path__` 是空的）；
  要讀工具資料夾裡的資料檔用 `os.path.dirname(__file__)`。
- `sys.meta_path` 多一個 finder（整個程序只有一個），對不是 `synox_pack_` 開頭的名字直接放行，成本可以忽略。
- 第 2 關擋的是「直接寫出另一個工具的模組名」；用字串組名字再動態 import 本來就是 exec（要宣告、會被看見），
  這一關仍是「擋明顯的、逼作者宣告」，不是沙盒。
