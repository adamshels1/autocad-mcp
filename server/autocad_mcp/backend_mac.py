"""macOS backend: AutoCAD for Mac has no COM, so everything goes through its command line.

`helper/acadctl` (Swift) brings AutoCAD to the front, focuses the command line through the
Accessibility API and types Unicode key events; it also reads the command history.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .errors import AutoCADError

ROOT = Path(__file__).resolve().parents[2]


class MacBackend:
    name = "mac"
    lisp_encoding = "utf-8"
    notes = (
        "Platform: AutoCAD for Mac. vla-*, vlax-*, vlr-* (ActiveX, reactors) do NOT exist: "
        "use entmake/entmod/entget/ssget/tblsearch/command. AutoCAD comes to the front for a moment on every call."
    )

    def __init__(self) -> None:
        self.acadctl = Path(os.environ.get("ACADCTL", ROOT / "helper" / "acadctl"))
        self.bundle_id = os.environ.get("ACAD_BUNDLE_ID", "com.autodesk.AutoCAD2026")
        self.restore_focus = os.environ.get("AUTOCAD_MCP_RESTORE_FOCUS", "1") != "0"

    def _ctl(self, *args: str, timeout: float = 30) -> str:
        if not self.acadctl.exists():
            raise AutoCADError(
                f"helper not built: {self.acadctl}. Run: swiftc -O helper/acadctl.swift -o helper/acadctl"
            )
        p = subprocess.run([str(self.acadctl), *args], capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise AutoCADError(p.stderr.strip() or f"acadctl {args[0]} failed with code {p.returncode}")
        return p.stdout

    def _window(self) -> dict[str, Any]:
        return json.loads(self._ctl("window"))

    def status(self) -> dict[str, Any]:
        try:
            w = self._window()
        except AutoCADError as e:
            return {"running": False, "error": str(e)}
        title = w.get("title") or ""
        return {
            "running": True,
            # The title is empty without Screen Recording permission; then we cannot tell.
            "drawing_open": (".dw" in title.lower()) if title else None,
            "title": title,
            "window": w,
        }

    def history(self) -> str:
        try:
            return self._ctl("history", timeout=10)
        except (AutoCADError, subprocess.TimeoutExpired):
            return ""

    def send_line(self, line: str, *, escape: bool = True, enter: bool = True) -> None:
        args = ["type"]
        if not escape:
            args.append("--no-escape")
        if not enter:
            args.append("--no-enter")
        if self.restore_focus:
            args.append("--restore-focus")
        args.append(line)
        self._ctl(*args)

    def screenshot(self, path: Path, max_size: int) -> None:
        w = self._window()
        p = subprocess.run(["screencapture", "-x", "-o", f"-l{w['id']}", str(path)], capture_output=True, text=True)
        if p.returncode != 0 or not path.exists():
            raise AutoCADError(f"screencapture failed: {p.stderr.strip()} (Screen Recording permission?)")
        subprocess.run(["sips", "-Z", str(int(max_size)), str(path)], capture_output=True)

    def new_drawing(self) -> str:
        before = self._window().get("title") or ""
        script = (
            f'tell application id "{self.bundle_id}" to activate\n'
            "delay 0.3\n"
            'tell application "System Events" to tell process "AutoCAD" to '
            'click menu item "New Drawing..." of menu "File" of menu bar 1'
        )
        p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
        if p.returncode != 0:
            raise AutoCADError(f"could not open File > New Drawing...: {p.stderr.strip()}")
        time.sleep(1.5)
        self._ctl("key", "36")  # Return: open the preselected template
        for _ in range(60):
            time.sleep(0.25)
            title = self._window().get("title") or ""
            if title != before and ".dw" in title.lower():
                return title
        raise AutoCADError("new drawing did not open; check with autocad_screenshot")
