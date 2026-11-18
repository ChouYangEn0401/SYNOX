"""
保持清醒（docs/adr/0006）：任務 system.keep_awake。它像一個穩定的 heartbeat——維持系統運轉（maintain），
但螢幕可以暗（保護螢幕或省電）。電腦不要睡著，螢幕照常可以熄，動滑鼠或鍵盤 Windows 自己會點亮。
**預設關**；打開＝覆蓋 Windows 電源選項裡的「睡眠」設定（NOTICE，網頁與 doctor 都顯示這段）。

    ka = KeepAwake(loop, settings=config.runtime["keep_awake"])
    ka.register()        任務每 60 秒確認一次請求還在（被別的程式清掉就重要一次）
    ka.release()         App 停止時放掉（程式結束 Windows 也會自己放掉，不會留著）
    ka.update(enabled=, screen_off_after_min=)

螢幕（screen_off_after_min）：
    0   ＝照 Windows 電源計畫（只請求「系統清醒」、不請求「螢幕常亮」，計畫裡「幾分鐘後關閉螢幕」照樣生效）。
    N>0 ＝閒置 N 分鐘關螢幕：把目前電源計畫的「關閉顯示器前的時間」（VIDEOIDLE，插電＋電池）設成 N 分鐘，
          由 Windows 自己關（動滑鼠或鍵盤就亮）。關掉保持清醒、改回 0／-1、App 停止時改回原本的值
          （只在值還是我們寫的那個時才改回；使用者自己在 Windows 設定改過就不動）。不設上限（只防溢位）。
    -1  ＝螢幕永不關（另外請求 PowerRequestDisplayRequired）。

2026-11-13 hotfix：以前 N>0 是閒置到了就廣播 SC_MONITORPOWER 關螢幕。在現代待命機型上 Windows 把它當成按了睡眠鍵
（事件記錄 Kernel-Power 506「The system is entering Modern Standby — Reason: SC_MONITORPOWER」、
566「Reason SleepButton」），螢幕一關電腦就跟著睡——跟要的相反。電源計畫自己的「關閉螢幕」計時只關螢幕，
不會讓電腦進入待命（睡眠由「睡眠啟動時間」＋我們的系統清醒請求決定），所以改用它。**不要再用 SC_MONITORPOWER。**

做不到的（照實說）：闔上筆電蓋、按電源鍵／開始選單的睡眠、電池快沒電、Windows Update 重開機，這個請求都擋不住。
只有 Windows 有作用；其他系統任務會顯示「idle：這個系統不支援」，不算失敗（不會吵心跳）。

現代待命（Modern Standby／S0 低電源閒置，ADR 0006 附記）：同一個請求物件同時設 PowerRequestSystemRequired 與
PowerRequestExecutionRequired（後者盡力而為：設不上不算失敗）。Microsoft 文件：插電時電源請求會讓系統一直停在進入待命前的
階段（不會睡）、用電池時最多 5 分鐘；使用者主動睡眠（電源鍵、闔蓋、開始選單）會終止所有請求。
是不是現代待命機型用 CallNtPowerInformation(SystemPowerCapabilities).AoAc 判斷，view()／doctor 多一行說明（MS_NOTE）。
除了上面 N>0 時暫時改「關閉顯示器前的時間」，不修改任何電源設定。
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Callable, Optional

TASK_ID = "system.keep_awake"
TASK_NAME = "保持清醒（電腦不睡著）"
INTERVAL_S = 60.0
TIMEOUT = 20.0
SCREEN_NEVER = -1                               # 螢幕永不關
MAX_SCREEN_OFF_MIN = 525600                     # 一年：實際上不設限，只防溢位（VIDEOIDLE 以秒存成 DWORD）

R_OFF = "沒有開（runtime.keep_awake.enabled=false）。"
R_UNSUPPORTED = "這個系統不支援（只有 Windows 有作用）。"

# 打開它的每個地方都要顯示這段（網頁設定頁、doctor、runtime-api.md、ADR 0006）
TAGLINE = "像一個穩定的 heartbeat：維持系統運轉，但螢幕可以暗（保護螢幕或省電）。"
NOTICE = ("開啟後會覆蓋 Windows 電源選項裡的「睡眠」設定：電腦不再自動睡眠。螢幕仍可照電源計畫，"
          "或設定「閒置 N 分鐘後主動關螢幕」變暗／關閉，以保護螢幕、省電。"
          "闔上筆電蓋、手動睡眠、低電量、Windows Update 重開機擋不住。")
MS_NOTE = ("這台是「現代待命」（Modern Standby）機型：系統清醒請求在現代待命的效果有限"
           "（插電時可擋住閒置睡眠；用電池時 Windows 最多再撐 5 分鐘；闔蓋、按電源鍵仍會睡）。"
           "若 Google Drive 仍斷線，請見 docs/keep-awake-troubleshooting.md 的排查步驟。")

# Windows 常數
POWER_REQUEST_CONTEXT_VERSION = 0
POWER_REQUEST_CONTEXT_SIMPLE_STRING = 0x1
POWER_REQUEST_DISPLAY_REQUIRED = 0              # PowerRequestDisplayRequired（screen_off_after_min=-1）
POWER_REQUEST_SYSTEM_REQUIRED = 1               # PowerRequestSystemRequired
POWER_REQUEST_EXECUTION_REQUIRED = 3            # PowerRequestExecutionRequired（Windows 8 起）
SYSTEM_POWER_CAPABILITIES = 4                   # POWER_INFORMATION_LEVEL：SystemPowerCapabilities
AOAC_OFFSET = 20                                # SYSTEM_POWER_CAPABILITIES.AoAc 的位移（winnt.h：15 個 BOOLEAN＋5 個位元組之後）
CAPABILITIES_SIZE = 76
SUB_VIDEO = "7516b95f-f776-4464-8c53-06167f40cc99"
VIDEOIDLE = "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"   # 關閉顯示器前的時間（秒，0＝永不）


class WinPower:
    """Windows 的電源請求與「關閉顯示器前的時間」（ctypes）。獨立出來，測試換假的。"""

    available = sys.platform == "win32"

    def __init__(self):
        self._handle = None
        self.execution = False                       # PowerRequestExecutionRequired 有沒有設上（盡力而為）
        self.display = False                         # PowerRequestDisplayRequired（螢幕永不關）
        self._aoac: Optional[bool] = None

    def hold(self, reason: str) -> bool:
        """請求「系統清醒」（不含螢幕）＋「行程繼續執行」。已經有就不重複；系統清醒成功＝True。"""
        if self._handle:
            return True
        import ctypes
        from ctypes import wintypes

        class _Reason(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("Flags", wintypes.DWORD), ("SimpleReasonString", wintypes.LPWSTR)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.PowerCreateRequest.restype = wintypes.HANDLE
        k32.PowerCreateRequest.argtypes = [ctypes.POINTER(_Reason)]
        k32.PowerSetRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
        ctx = _Reason(POWER_REQUEST_CONTEXT_VERSION, POWER_REQUEST_CONTEXT_SIMPLE_STRING, reason)
        handle = k32.PowerCreateRequest(ctypes.byref(ctx))
        if not handle or handle == wintypes.HANDLE(-1).value:
            return False
        if not k32.PowerSetRequest(handle, POWER_REQUEST_SYSTEM_REQUIRED):
            k32.CloseHandle(handle)
            return False
        # 現代待命（ADR 0006 附記）：ExecutionRequired 讓行程不被行程生命週期管理暫停；S3 機型上它本來就含 SystemRequired。
        # 舊版 Windows 不認得就算了，不影響上面那個。
        self.execution = bool(k32.PowerSetRequest(handle, POWER_REQUEST_EXECUTION_REQUIRED))
        if not self.execution:
            logging.info("[KEEPAWAKE] PowerRequestExecutionRequired not accepted (older Windows?); system request still held")
        self._handle = handle
        return True

    def keep_display(self, on: bool) -> None:
        """螢幕永不關（PowerRequestDisplayRequired）開／關；要先 hold()。"""
        if not self._handle or bool(on) == self.display:
            return
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if on:
            if not k32.PowerSetRequest(self._handle, POWER_REQUEST_DISPLAY_REQUIRED):
                raise RuntimeError("Windows 不肯接受「螢幕常亮」請求")
        else:
            k32.PowerClearRequest(self._handle, POWER_REQUEST_DISPLAY_REQUIRED)
        self.display = bool(on)

    def release(self) -> None:
        if not self._handle:
            return
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if self.display:
            k32.PowerClearRequest(self._handle, POWER_REQUEST_DISPLAY_REQUIRED)
        if self.execution:
            k32.PowerClearRequest(self._handle, POWER_REQUEST_EXECUTION_REQUIRED)
        k32.PowerClearRequest(self._handle, POWER_REQUEST_SYSTEM_REQUIRED)
        k32.CloseHandle(self._handle)
        self._handle = None
        self.execution = False
        self.display = False

    # ── 電源計畫「關閉顯示器前的時間」（screen_off_after_min=N）──────────────
    @staticmethod
    def _guid(text: str):
        import ctypes
        import uuid
        return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)

    @staticmethod
    def _active_scheme():
        """目前電源計畫的 GUID（複製一份，Windows 給的那份用 LocalFree 還回去）。"""
        import ctypes
        pp = ctypes.WinDLL("powrprof")
        ptr = ctypes.c_void_p()
        if pp.PowerGetActiveScheme(None, ctypes.byref(ptr)) != 0 or not ptr.value:
            raise RuntimeError("讀不到目前的電源計畫")
        try:
            return (ctypes.c_ubyte * 16).from_buffer_copy(ctypes.string_at(ptr.value, 16))
        finally:
            ctypes.windll.kernel32.LocalFree(ptr)

    def display_timeout(self) -> tuple:
        """目前電源計畫「關閉顯示器前的時間」：(插電秒數, 電池秒數)；0＝永不。"""
        import ctypes
        from ctypes import wintypes
        pp = ctypes.WinDLL("powrprof")
        scheme, sub, setting = self._active_scheme(), self._guid(SUB_VIDEO), self._guid(VIDEOIDLE)
        out = []
        for fn in (pp.PowerReadACValueIndex, pp.PowerReadDCValueIndex):
            value = wintypes.DWORD()
            if fn(None, ctypes.byref(scheme), ctypes.byref(sub), ctypes.byref(setting), ctypes.byref(value)) != 0:
                raise RuntimeError("讀不到「關閉顯示器前的時間」")
            out.append(int(value.value))
        return tuple(out)

    def set_display_timeout(self, ac: int, dc: int) -> None:
        """改目前電源計畫「關閉顯示器前的時間」並立刻生效（跟 powercfg /change monitor-timeout-ac 一樣，不用管理員）。"""
        import ctypes
        from ctypes import wintypes
        pp = ctypes.WinDLL("powrprof")
        scheme, sub, setting = self._active_scheme(), self._guid(SUB_VIDEO), self._guid(VIDEOIDLE)
        for fn, value in ((pp.PowerWriteACValueIndex, ac), (pp.PowerWriteDCValueIndex, dc)):
            if fn(None, ctypes.byref(scheme), ctypes.byref(sub), ctypes.byref(setting), wintypes.DWORD(value)) != 0:
                raise RuntimeError("改不了「關閉顯示器前的時間」")
        if pp.PowerSetActiveScheme(None, ctypes.byref(scheme)) != 0:
            raise RuntimeError("電源計畫改了，但套用不上")

    def modern_standby(self) -> Optional[bool]:
        """這台是不是現代待命（S0 低電源閒置）：CallNtPowerInformation(SystemPowerCapabilities).AoAc。只讀；量不到＝None。"""
        if self._aoac is not None:
            return self._aoac
        try:
            import ctypes
            buf = (ctypes.c_ubyte * CAPABILITIES_SIZE)()
            status = ctypes.WinDLL("powrprof").CallNtPowerInformation(
                SYSTEM_POWER_CAPABILITIES, None, 0, ctypes.byref(buf), CAPABILITIES_SIZE)
            if status != 0:
                return None
            self._aoac = bool(buf[AOAC_OFFSET])
        except Exception:
            return None
        return self._aoac


def valid_minutes(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and SCREEN_NEVER <= value <= MAX_SCREEN_OFF_MIN


class KeepAwake:

    def __init__(self, loop, *, settings: dict, power: Optional[WinPower] = None):
        self.loop = loop
        self.settings = dict(settings)
        self.power = power if power is not None else WinPower()
        self._lock = threading.Lock()
        self._applied_min = 0                  # 目前寫進電源計畫的分鐘（0＝沒寫）
        self._saved: Optional[tuple] = None    # 寫之前電源計畫原本的（插電, 電池）秒數
        self._written: Optional[tuple] = None  # 我們寫進去的值：還是它才改回去
        self.last_result: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("enabled", False))

    @property
    def screen_off_after_min(self) -> int:
        return int(self.settings.get("screen_off_after_min", 0))

    def register(self) -> None:
        task = self.loop.register(TASK_ID, TASK_NAME, fn=self.run, interval=INTERVAL_S if self.enabled else None,
                                  timeout=TIMEOUT)
        task.set_schedule_text("" if self.enabled else "關閉")
        if self.enabled:
            try:
                self.run()                     # 一開機就請求，不等一個間隔
            except Exception:
                logging.exception("[KEEPAWAKE] first request failed")   # 任務之後每 60 秒會再試，失敗會被看見

    def update(self, *, enabled: Optional[bool] = None, screen_off_after_min: Optional[int] = None) -> dict:
        if screen_off_after_min is not None:
            if not valid_minutes(screen_off_after_min):
                raise ValueError("熄螢幕的閒置分鐘要是整數：-1＝螢幕永不關、0＝照 Windows 電源計畫、N＝閒置 N 分鐘關螢幕。")
            self.settings["screen_off_after_min"] = screen_off_after_min
        if enabled is not None:
            self.settings["enabled"] = bool(enabled)
        if self.enabled:
            self.loop.reschedule(TASK_ID, INTERVAL_S)
            try:
                self.run()
            except Exception as e:
                self.last_result = f"沒成功：{e}"
        else:
            self.release()
            self.loop.reschedule(TASK_ID, None)
        task = self.loop.task(TASK_ID)
        if task is not None:
            task.set_schedule_text("" if self.enabled else "關閉")
        return self.view()

    def modern_standby(self) -> Optional[bool]:
        if not self.power.available:
            return None
        probe = getattr(self.power, "modern_standby", None)
        try:
            return probe() if callable(probe) else None
        except Exception:
            return None

    def view(self) -> dict:
        ms = self.modern_standby()
        holding = bool(getattr(self.power, "_handle", None)) if self.power.available else False
        return {"enabled": self.enabled, "supported": bool(self.power.available),
                "holding": holding, "execution_required": holding and bool(getattr(self.power, "execution", False)),
                "display_required": holding and bool(getattr(self.power, "display", False)),
                "screen_off_after_min": self.screen_off_after_min, "max_screen_off_min": MAX_SCREEN_OFF_MIN,
                "last_result": self.last_result, "tagline": TAGLINE, "notice": NOTICE,
                "modern_standby": ms, "modern_standby_note": MS_NOTE if ms else ""}

    def run(self, ctx=None) -> str:
        with self._lock:
            if not self.enabled:
                self.release()
                result = R_OFF
            elif not self.power.available:
                result = R_UNSUPPORTED
            else:
                result = self._tick()
            self.last_result = result
            if ctx is not None:
                ctx.log(result)
            return result

    def _tick(self) -> str:
        try:
            if not self.power.hold("SYNOX 背景任務執行中，請不要讓電腦睡著"):
                raise RuntimeError("Windows 不肯接受電源請求")
        except Exception as e:
            logging.warning("[KEEPAWAKE] cannot hold power request: %s", e)
            raise RuntimeError(f"沒辦法請 Windows 保持清醒：{e}")
        minutes = self.screen_off_after_min
        try:
            self.power.keep_display(minutes == SCREEN_NEVER)
        except Exception as e:
            logging.warning("[KEEPAWAKE] display request: %s", e)
        if minutes > 0:
            if self._applied_min != minutes:     # 只在設定變了才寫：使用者之後自己在 Windows 改，不跟他搶
                try:
                    self._apply_timer(minutes)
                except Exception as e:
                    logging.warning("[KEEPAWAKE] screen timer: %s", e)
                    return f"電腦保持清醒中，但沒辦法設定閒置 {minutes} 分鐘關螢幕：{e}。"
            return f"電腦保持清醒中；閒置 {minutes} 分鐘 Windows 會關螢幕（動滑鼠或鍵盤就亮）。"
        self._restore_timer()
        if minutes == SCREEN_NEVER:
            return "電腦保持清醒中；螢幕永不關。"
        return "電腦保持清醒中（螢幕照 Windows 電源計畫，動滑鼠或鍵盤就亮）。"

    def _apply_timer(self, minutes: int) -> None:
        want = (minutes * 60, minutes * 60)
        current = tuple(self.power.display_timeout())
        if self._saved is None and current != want:
            self._saved = current
        if current != want:
            self.power.set_display_timeout(*want)
        self._written = want
        self._applied_min = minutes

    def _restore_timer(self) -> None:
        """改回電源計畫原本的「關閉螢幕」時間——只在值還是我們寫的那個時（使用者自己改過就不動）。"""
        saved, written = self._saved, self._written
        self._saved = self._written = None
        self._applied_min = 0
        if not saved or not written:
            return
        try:
            if tuple(self.power.display_timeout()) == written:
                self.power.set_display_timeout(*saved)
        except Exception as e:
            logging.warning("[KEEPAWAKE] restore screen timer: %s", e)

    def release(self) -> None:
        if self.power.available:
            self._restore_timer()
        try:
            self.power.release()
        except Exception:
            logging.exception("[KEEPAWAKE] release failed")
