"""Windows backend: talks to a running AutoCAD through its COM (ActiveX) interface.

No keystrokes and no focus changes: the one-line `(progn (load ...))` goes in through
AcadDocument.PostCommand / SendCommand. The command line history is read from AutoCAD's
own log file (LOGFILEMODE=1), which is how LISP errors and princ output reach the caller.

Needs pywin32, and Pillow for screenshots. Full AutoCAD only: AutoCAD LT has no COM.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

from .errors import AutoCADError

# COM "server is busy" results: AutoCAD is in a command, a dialog, or still starting up.
RPC_E_CALL_REJECTED = -2147418111        # 0x80010001
RPC_E_SERVERCALL_RETRYLATER = -2147417846  # 0x8001010A
BUSY = {RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER}
# DISP_E_UNKNOWNNAME / DISP_E_MEMBERNOTFOUND: the method does not exist in this AutoCAD release.
NO_SUCH_MEMBER = {-2147352570, -2147352573}

LOG_TAIL_BYTES = 256 * 1024


def _hresult(e: BaseException) -> Any:
    code = getattr(e, "hresult", None)
    if code is None and e.args:
        code = e.args[0]
    return code


def decode_log(data: bytes) -> str:
    """AutoCAD log files are UTF-16 (with BOM), UTF-8 or the ANSI code page, depending on the release."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if data[:3] == b"\xef\xbb\xbf":
        return data[3:].decode("utf-8", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("mbcs" if os.name == "nt" else "cp1251", errors="replace")


class WinBackend:
    name = "windows-com"
    lisp_encoding = "utf-8-sig"  # AutoCAD for Windows reads .lsp without a BOM as ANSI
    notes = (
        "Platform: AutoCAD for Windows through COM. vla-/vlax- functions are available after (vl-load-com). "
        "AutoCAD stays in the background; nothing is typed on the keyboard."
    )

    def __init__(self) -> None:
        self.progid = os.environ.get("AUTOCAD_PROGID", "AutoCAD.Application")
        self.cancel = os.environ.get("AUTOCAD_MCP_CANCEL", "\x1b\x1b")
        self.busy_retries = int(os.environ.get("AUTOCAD_MCP_BUSY_RETRIES", "40"))
        self.busy_delay = 0.25

    # ---- COM plumbing

    def _app(self) -> Any:
        try:
            import pythoncom
            import win32com.client
        except ImportError as e:
            raise AutoCADError("pywin32 is not installed: run `uv sync` in the server folder on Windows") from e
        pythoncom.CoInitialize()  # per thread, harmless when repeated
        try:
            return win32com.client.GetActiveObject(self.progid)
        except Exception as e:
            raise AutoCADError(
                f"AutoCAD is not running (no COM object {self.progid!r}). Start AutoCAD and open a drawing. "
                "AutoCAD LT is not supported: it has no COM interface."
            ) from e

    def _retry(self, fn: Callable[[], Any]) -> Any:
        for _ in range(self.busy_retries):
            try:
                return fn()
            except AutoCADError:
                raise
            except Exception as e:
                if _hresult(e) in BUSY:
                    time.sleep(self.busy_delay)
                    continue
                raise AutoCADError(f"AutoCAD COM error: {e}") from e
        raise AutoCADError(
            "AutoCAD is busy: a command or a dialog is active. Finish or cancel it (Esc) in AutoCAD and retry."
        )

    def _doc(self) -> Any:
        app = self._app()
        if self._retry(lambda: app.Documents.Count) == 0:
            raise AutoCADError("No drawing is open in AutoCAD. Call autocad_new_drawing or open a .dwg.")
        return self._retry(lambda: app.ActiveDocument)

    # ---- backend interface

    def status(self) -> dict[str, Any]:
        try:
            app = self._app()
            count = self._retry(lambda: app.Documents.Count)
            info: dict[str, Any] = {
                "running": True,
                "drawing_open": count > 0,
                "title": self._retry(lambda: app.Caption),
                "documents": count,
            }
            if count:
                info["drawing"] = self._retry(lambda: app.ActiveDocument.Name)
            return info
        except AutoCADError as e:
            return {"running": False, "error": str(e)}

    def history(self) -> str:
        """Tail of AutoCAD's command line log; empty when it is not available."""
        try:
            doc = self._doc()
            if not self._retry(lambda: doc.GetVariable("LOGFILEMODE")):
                self._retry(lambda: doc.SetVariable("LOGFILEMODE", 1))
            path = self._retry(lambda: doc.GetVariable("LOGFILENAME"))
            if not path or not os.path.exists(path):
                return ""
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(0)
                head = f.read(4)
                if size > LOG_TAIL_BYTES:
                    start = size - LOG_TAIL_BYTES
                    start -= start % 2  # keep UTF-16 code units aligned
                    f.seek(start)
                    bom = head[:2] if head[:2] in (b"\xff\xfe", b"\xfe\xff") else b""
                    data = bom + f.read()
                else:
                    f.seek(0)
                    data = f.read()
            return decode_log(data)
        except (AutoCADError, OSError):
            return ""

    def send_line(self, line: str, *, escape: bool = True, enter: bool = True) -> None:
        doc = self._doc()
        text = (self.cancel if escape else "") + line + ("\n" if enter else "")
        if not text:
            return

        def post() -> None:
            # PostCommand returns at once, so our own timeout stays in charge;
            # SendCommand (older releases) blocks until AutoCAD has run the line.
            try:
                doc.PostCommand(text)
            except AttributeError:
                doc.SendCommand(text)
            except Exception as e:
                if _hresult(e) not in NO_SUCH_MEMBER:
                    raise
                doc.SendCommand(text)

        self._retry(post)

    def screenshot(self, path: Path, max_size: int) -> None:
        try:
            import ctypes

            import win32gui
            import win32ui
            from PIL import Image, ImageGrab
        except ImportError as e:
            raise AutoCADError("screenshots need pywin32 and Pillow: run `uv sync` in the server folder") from e
        app = self._app()
        hwnd = int(self._retry(lambda: app.HWND))
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            raise AutoCADError("AutoCAD window is minimized; restore it to take a screenshot")
        img = None
        hdc = win32gui.GetWindowDC(hwnd)
        src = win32ui.CreateDCFromHandle(hdc)
        mem = src.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        try:
            bmp.CreateCompatibleBitmap(src, w, h)
            mem.SelectObject(bmp)
            # PW_RENDERFULLCONTENT (2) captures hardware-accelerated viewports even when covered.
            if ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2):
                info = bmp.GetInfo()
                img = Image.frombuffer(
                    "RGB", (info["bmWidth"], info["bmHeight"]), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1
                )
        finally:
            win32gui.DeleteObject(bmp.GetHandle())
            mem.DeleteDC()
            src.DeleteDC()
            win32gui.ReleaseDC(hwnd, hdc)
        if img is None:
            img = ImageGrab.grab(bbox=(left, top, right, bottom))  # needs the window to be visible
        img.thumbnail((int(max_size), int(max_size)))
        img.save(str(path))

    def new_drawing(self) -> str:
        app = self._app()
        doc = self._retry(lambda: app.Documents.Add())
        try:
            self._retry(doc.Activate)
        except AutoCADError:
            pass  # the new document is normally active already
        return str(self._retry(lambda: doc.Name))
