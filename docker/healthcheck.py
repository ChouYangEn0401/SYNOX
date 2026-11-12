"""SYNOX 容器的健康檢查（Dockerfile 的 HEALTHCHECK；docs/docker.md）。

不經任何對外的埠、不連網、不改任何檔：
1. 讀 SYNOX_HOME 的 config.json（不要 token）→ data/host.lock 記的那支 SYNOX 還活著（os.kill(pid, 0)）；
2. 網頁介面開著（web.enabled，預設是）→ 連容器自己的 127.0.0.1:<web.port> 連得上。
   擁有者用 /web_off 關掉網頁的那段時間會被標成 unhealthy；重開容器就好（docs/docker.md「已知限制」）。

結束碼 0＝健康、1＝不健康（Docker 的規定）。只印一行原因，不印設定內容。
"""

from __future__ import annotations

import json
import os
import socket
import sys


def main() -> int:
    try:
        from synox.config import CONFIG_PATH, SynoxConfig
        config = SynoxConfig.load(CONFIG_PATH, require_token=False)
    except Exception as e:                                  # 還沒跑 init、config.json 壞了
        print(f"unhealthy: config ({type(e).__name__})")
        return 1
    try:
        with open(config.path("host.lock"), "r", encoding="utf-8") as f:
            held = json.load(f)
        pid = int(held.get("pid") or 0) if isinstance(held, dict) else 0
    except (OSError, ValueError, TypeError):
        pid = 0
    if pid <= 0:
        print("unhealthy: SYNOX is not running (no data/host.lock)")
        return 1
    if os.name == "nt":                                     # 只給 Linux 容器用：Windows 的 os.kill(pid, 0) 會送 Ctrl+C
        print("unhealthy: this check is for the Linux container only")
        return 1
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        print(f"unhealthy: pid {pid} in data/host.lock is gone")
        return 1
    except PermissionError:
        pass                                                # 程序在（只是不是同一個帳號）
    web = getattr(config, "web", {}) or {}
    port = int(web.get("port") or 0)
    if web.get("enabled", True) and port:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=3).close()
        except OSError as e:
            print(f"unhealthy: web UI not answering on the container's own 127.0.0.1:{port} ({type(e).__name__})")
            return 1
    print("healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
