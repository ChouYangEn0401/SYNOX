"""
對話助理的離線評測（evals/assistant/README.md）：固定的題目＋假工具＋照劇本回話的假 AI，
接在**真的** AgentLoop 上重放，量「改了系統提示／工具說明之後有沒有變好」。

    cases.load_dir(資料夾)            → 題目（cases.py：格式、檢查、題數分配）
    replay.run_case(題目, 劇本)        → 一題跑完的紀錄（replay.py；fake_tools.py 把假工具掛進指令樹）
    checks.evaluate(題目, 紀錄)        → 沒過的硬檢查（checks.py）
    report.build(…)／text／dumps      → 每題、每類、tune／holdout、簡體字統計（report.py）

全部離線：不連網、不開埠、不呼叫任何真的 AI；這裡沒有「真跑」的路徑（要做之前先決定的事寫在 README）。
"""
