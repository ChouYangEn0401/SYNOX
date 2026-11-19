"""
synox.datastore：持久化資料的版本與自動升級（ADR 0044；給人看的版本在 docs/data-migrations.md）。

    versioned.py   版本號放哪裡（JSON 頂層鍵、SQLite user_version、旁檔 .schema）、原子寫入、檔案鎖、備份
    migrate.py     Chain（一種資料的 v→v+1 步驟）、逐版連續升級、Outcome（給人看的結果）
    core.py        SYNOX 核心自己的檔（config.json、packs.lock、pack_data.json）
    packdata.py    工具的資料（pack.json 的 data_schema；python 的 migrations 模組、cli 的 migrate 子命令）

規則一句話：每一份持久化資料都有版本號；改資料格式＝加一個遷移步驟＋測試；不服務降級。
"""

from synox.datastore.migrate import Chain, Outcome, run_steps, upgrade_file  # noqa: F401
from synox.datastore.versioned import (BusyError, DataError, GapError, StepError, TooNewError)  # noqa: F401
