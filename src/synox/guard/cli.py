"""命令列：`python -m synox stepup setup｜status｜reset`（ADR 0025 §5.2 第 5 點）。給沒有瀏覽器的伺服器、容器。

- setup：在終端機印金鑰（四個字一組）與方塊字畫的 QR，問一組碼；對了印 10 組備用碼（只這一次），再問開關（預設要）。
- status：設定了沒、開關、剩幾組備用碼。**不印金鑰**。
- reset：不用碼（能在這台電腦用跑 SYNOX 的帳號執行程式的人，本來就能改設定檔）；先問一次確定。
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from synox.guard import qr
from synox.guard.origin import Origin, using
from synox.guard.stepup import Refused, StepUp, group_secret
from synox.guard.store import VaultStore

TEXT = {
    "already": "已經設定過手機驗證器了。要重設：python -m synox stepup reset",
    "scan": "① 打開手機的驗證器 App（Google Authenticator、Microsoft Authenticator…）→ 新增 → 掃描下面的方塊：",
    "manual": "② 掃不到的話，選「手動輸入」，打這串字：",
    "ask_code": "③ 打 App 上現在顯示的 6 位數（直接按 Enter 取消）：",
    "cancel": "（取消了，什麼都沒存）",
    "recovery": "設定好了。下面是 10 組備用碼（手機不見時用；只顯示這一次，請抄在紙上）：",
    "protect": "危險的動作也要先解鎖嗎？（建議）[Y/n]：",
    "protect_on": "好，危險的動作要先解鎖（/unlock <6 位數>）。",
    "protect_off": "好，先不開；之後可以到 SYNOX 網頁 → 設定 → 🔐 安全 打開。",
    "not_set": "手機驗證器：沒設定",
    "status": "手機驗證器：已設定｜危險的動作要先解鎖：{p}｜備用碼還剩 {n} 組",
    "reset_ask": "確定要重設手機驗證器嗎？之後要重新設定（危險的動作回到只靠 Telegram 帳號與瀏覽器登入）[y/N]：",
    "reset_done": "已重設。要再設定：python -m synox stepup setup，或 SYNOX 網頁 → 設定 → 🔐 安全。",
    "too_many": "錯太多次了，先停在這裡（什麼都沒存）。",
}


def run(action: str, config, vault, *, user: Optional[int] = None, ask: Callable[[str], str] = input,
        out: Callable[[str], None] = print, clock: Callable[[], float] = time.time) -> int:
    owner = int(getattr(config, "owner_id", 0) or 0)
    uid = int(user or owner)
    server = getattr(config, "mode", "personal") == "server"
    hub = StepUp(VaultStore(vault, server), owner_id=owner, minutes=int(getattr(config, "stepup_minutes", 15) or 15),
                 clock=clock)
    with using(Origin("console", uid, surface="console")):
        if action == "status":
            s = hub.status(uid, Origin("console", uid, surface="console"))
            out(TEXT["status"].format(p="是" if s["protect_danger"] else "否", n=s["recovery_left"])
                if s["enrolled"] else TEXT["not_set"])
            return 0
        if action == "reset":
            if not hub.enrolled(uid):
                out(TEXT["not_set"])
                return 0
            if ask(TEXT["reset_ask"]).strip().lower() not in ("y", "yes", "是"):
                out(TEXT["cancel"])
                return 1
            hub.reset_local(uid)
            out(TEXT["reset_done"])
            return 0
        if action != "setup":
            return 2
        if hub.enrolled(uid):
            out(TEXT["already"])
            return 1
        started = hub.begin(uid)
        out(TEXT["scan"])
        try:
            out(qr.terminal(qr.matrix(started["uri"])))
        except ValueError:
            pass
        out(TEXT["manual"])
        out("    " + group_secret(started["secret"]))
        for _ in range(3):
            code = ask(TEXT["ask_code"]).strip()
            if not code:
                out(TEXT["cancel"])
                return 1
            try:
                codes = hub.confirm(uid, code)
            except Refused as e:
                out(e.result.text)
                if e.result.code in ("expired", "locked"):
                    return 1
                continue
            out(TEXT["recovery"])
            for c in codes:
                out("    " + c)
            yes = ask(TEXT["protect"]).strip().lower() in ("", "y", "yes", "是")
            hub.set_protect(uid, yes, origin=Origin("console", uid, surface="console"))
            out(TEXT["protect_on"] if yes else TEXT["protect_off"])
            return 0
        out(TEXT["too_many"])
        return 1


def doctor_line(data: Optional[dict]) -> str:
    """doctor 的那一行（給 doctor.py；data＝擁有者的保管內容，None＝沒設定）。"""
    if not data:
        return "  手機驗證器：沒設定（危險的動作目前只靠你的 Telegram 帳號與瀏覽器登入；到 SYNOX 網頁 → 設定 → 安全）"
    if data.get("protect_danger"):
        return "  手機驗證器：已設定，危險的動作要先解鎖"
    return "  手機驗證器：已設定，但危險的動作沒有開保護（SYNOX 網頁 → 設定 → 安全 打開）"
