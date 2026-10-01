"""Self-test against a real AutoCAD: `uv run autocad-mcp-selftest`.

Run it with AutoCAD started and a drawing open, and do not touch the keyboard meanwhile.
It leaves the drawing unchanged and prints a report that can be sent to support as is.
"""

from __future__ import annotations

import json
import platform
import sys
import traceback
from typing import Any, Callable

from . import server
from .errors import AutoCADError


def _expect_error(code: str, needle: str) -> str:
    try:
        server._run_lisp(code, undo=False, timeout=20)
    except AutoCADError as e:
        if needle not in str(e):
            raise AssertionError(f"error text without {needle!r}: {e}")
        return "error reported"
    raise AssertionError("no error was raised")


def _equal(got: Any, want: Any) -> str:
    if got != want:
        raise AssertionError(f"got {got!r}, expected {want!r}")
    return json.dumps(got, ensure_ascii=False)


def _status() -> str:
    st = json.loads(server.autocad_status())
    if not st.get("running"):
        raise AssertionError(st.get("error") or "AutoCAD is not running")
    if st.get("drawing_open") is False:
        raise AssertionError("no drawing is open: create or open one first")
    return f"{st.get('title')!r}"


def _console() -> str:
    r = server._run_lisp('(princ "\\nmcp-selftest-marker") 1', undo=False, console=True, timeout=20)
    if "mcp-selftest-marker" not in r["console"]:
        return "WARNING: command line output is not captured (results still work)"
    return "captured"


def _screenshot() -> str:
    img = server.autocad_screenshot(max_size=800)
    size = server.BRIDGE_DIR.joinpath("screenshot.png").stat().st_size
    if size < 2000:
        raise AssertionError(f"screenshot file is only {size} bytes")
    return f"{img.path} ({size} bytes)"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("AutoCAD is running with a drawing", _status),
    ("arithmetic", lambda: _equal(server._run_lisp("(+ 1 2)", undo=False, timeout=20), 3)),
    ("Cyrillic text both ways", lambda: _equal(
        server._run_lisp('(strcat "Стены" " ё")', undo=False, timeout=20), "Стены ё")),
    ("lists and pairs as JSON", lambda: _equal(
        server._run_lisp('(list (cons "pt" (list 1.5 -0.25 0)) (cons "on" T))', undo=False, timeout=20),
        {"pt": [1.5, -0.25, 0], "on": True})),
    ("LISP errors are reported", lambda: _expect_error("(+ 1 nil)", "numberp")),
    ("command line output", _console),
    ("create, read and erase a line", lambda: _equal(
        server._run_lisp(
            '(entmake (list (cons 0 "LINE") (cons 8 "0") (cons 10 (list 0 0 0)) (cons 11 (list 123 0 0))))'
            " (setq e (entlast) d (entget e)) (entdel e) (list (cdr (assoc 0 d)) (cdr (assoc 11 d)))",
            timeout=20),
        ["LINE", [123, 0, 0]])),
    ("a command through (command ...)", lambda: _equal(
        json.loads(server.autocad_command(["_.REGEN"], timeout=20))["created"], None)),
    ("drawing info", lambda: json.loads(server.autocad_drawing_info())["dwgname"]),
    ("screenshot", _screenshot),
]


def main() -> int:
    print(f"autocad-mcp self-test | python {platform.python_version()} | {platform.platform()}")
    try:
        print(f"backend: {server._backend().name} | bridge folder: {server.BRIDGE_DIR}")
    except AutoCADError as e:
        print(f"FAIL  backend: {e}")
        return 1
    failed = 0
    for name, check in CHECKS:
        try:
            print(f"PASS  {name}: {check()}")
        except Exception as e:  # report everything, the output goes to support
            failed += 1
            print(f"FAIL  {name}: {e}")
            if not isinstance(e, (AutoCADError, AssertionError)):
                print(traceback.format_exc())
            if name.startswith("AutoCAD is running"):
                break
    print(f"\n{failed} of {len(CHECKS)} checks FAILED" if failed else f"\nall {len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
