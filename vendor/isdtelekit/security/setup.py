"""
設定 /sudo 用的手機驗證器（TOTP）。只能在 bot 所在的電腦上執行：密鑰永遠不經過 Telegram。

    .venv\\Scripts\\python.exe -m isdtelekit.security.setup              第一次設定（已設定過就只做驗證）
    .venv\\Scripts\\python.exe -m isdtelekit.security.setup --reset      換新密鑰（舊的驗證器失效）
    .venv\\Scripts\\python.exe -m isdtelekit.security.setup --factor B   第二組驗證器（B）；也可以加 --reset
    ... --data <資料夾>                                                  bot 的資料夾不是 ./data 時

步驟：
  1. 手機打開 Google Authenticator / Microsoft Authenticator（或任何 TOTP App）
  2. 「新增 → 輸入設定金鑰」，帳號名稱隨意，金鑰貼上下面印出的那一串，類型選「時間型」
  3. 把 App 上現在的 6 位數打回這裡，對了才算設定完成
之後在 Telegram 私訊 bot：/sudo 123456 解鎖 🔐 指令。

第二組（B）只給風險最高的動作用。**放在跟 A 不同的地方**：另一個帳號的驗證器 App、另一支手機、或密碼管理器——
一支手機或一個帳號被拿走時，另一組還在，對方湊不齊兩組。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, List, Optional

from isdtelekit.security import totp
from isdtelekit.security.stepup import FACTOR_A, FACTOR_B, StepUp


def main(argv: Optional[List[str]] = None, ask: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(prog="python -m isdtelekit.security.setup",
                                     description="設定 /sudo 用的手機驗證器（TOTP）")
    parser.add_argument("--data", default="data", help="bot 的資料夾（預設 ./data）")
    parser.add_argument("--factor", default=FACTOR_A, choices=(FACTOR_A, FACTOR_B), type=str.upper)
    parser.add_argument("--reset", action="store_true", help="換新密鑰（舊的驗證器失效）")
    parser.add_argument("--issuer", default="ISDTeleKit", help="驗證器 App 裡顯示的名字")
    args = parser.parse_args(argv)

    stepup = StepUp(os.path.join(args.data, "stepup_totp.json"))
    factor = args.factor
    path = stepup.path_b if factor == FACTOR_B else stepup.path
    label = "第二組驗證器（B）" if factor == FACTOR_B else "驗證器"
    if stepup.has_factor(factor) and not args.reset:
        print(f"{label}已經設定過（{path}）。要換新密鑰請加 --reset。")
    else:
        secret = stepup.create_secret(factor)
        grouped = " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
        print(f"在{'另一個帳號／另一支手機的' if factor == FACTOR_B else '手機'}驗證器 App "
              "選「輸入設定金鑰」，貼上這串（空格可有可無）：\n")
        print(f"    {grouped}\n")
        print("或用支援 otpauth 連結的 App：")
        print(f"    {totp.provisioning_uri(secret, 'owner-B' if factor == FACTOR_B else 'owner', args.issuer)}\n")
        print("⚠️ 這串只顯示這一次，也不要貼到 Telegram 或任何聊天裡。\n")
        if factor == FACTOR_B:
            print("⚠️ 跟第一組（A）放在不同的地方，不然兩組等於一組。\n")

    for _ in range(3):
        code = ask("輸入 App 上現在的 6 位數驗證：").strip()
        if stepup.check(code, factor):
            print("✅ 驗證成功。重啟 bot 之後生效。")
            return 0
        print("❌ 不對（App 的時間要準；每 30 秒換一組）。")
    print("三次都不對。密鑰已存，可以再跑一次這支程式重新驗證。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
