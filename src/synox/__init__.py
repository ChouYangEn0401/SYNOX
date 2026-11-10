"""
SYNOX：ISDTeleKitSDK（vendor/isdtelekit）＋可換的 LLM adapter＋skill pack 載入器＋加密保管箱＋一鍵安裝精靈。

    python -m synox run | console | wizard | doctor | stop

地圖與不變式在 docs/AGENT.md；給人看的在 README.md。
"""

import os
import sys

__version__ = "0.2.0"

# vendor/isdtelekit 是 SDK 的原樣複製（scripts/vendor_sdk.py）。`pip install -e .` 已經讓它可以 import；
# 沒裝、直接從原始碼跑（例如 PYTHONPATH=src）時，補上 vendor/ 這一層。
try:
    import isdtelekit  # noqa: F401
except ImportError:  # pragma: no cover
    _vendor = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "vendor")
    if os.path.isdir(_vendor):
        sys.path.insert(0, _vendor)
