"""
現成的指令組：每一個都是 install(app, …)，要哪個裝哪個。

    basics      /start、/exit、bot 離線時累積的舊指令先問
    help        /help（分頁＋按鈕）、打群組名列出那組
    sudo        /sudo、/sudo_off；被 🔐 擋下後解鎖，附「繼續」
    accounts    /me、/me_upgrade、/me_role、/me_op；管理員的 /user_list、/user_role、/user_deny 與審核按鈕
    limits      /limit_*（封鎖、罰則、豁免、重置）與 /me_quota_reset、/me_quota_free 的申請按鈕
    passes      通行證：/pass_new 發碼、/join <碼>（或 t.me/<bot>?start=<碼>）拿到角色
    jobs_admin  /sys_jobs、/sys_job_cancel：看與停掉 bot 啟動的外部程式

群組沒有在 bot 自己的 layout 定義過的話，pack 用自己的預設（標題、權限）定義；定義過就照 layout。
"""
