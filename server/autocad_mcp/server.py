"""MCP server for AutoCAD (Mac and Windows).

The bridge is the same on both systems:

  1. The server writes the request as an AutoLISP file into BRIDGE_DIR.
  2. The backend makes AutoCAD run the one-liner `(progn (load "<request>"))`:
     on macOS by typing it into the command line (helper/acadctl), on Windows through COM.
  3. mcp_lib.lsp evaluates the code with errors caught and writes a JSON result file,
     which the server polls for. What AutoCAD printed meanwhile comes back as "console".
"""

from __future__ import annotations

import json
import locale
import os
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

from .errors import AutoCADError

ROOT = Path(__file__).resolve().parents[2]
LIB_SRC = ROOT / "lisp" / "mcp_lib.lsp"
BRIDGE_DIR = Path(os.environ.get("AUTOCAD_MCP_DIR", Path.home() / ".cad-mcp" / "autocad")).expanduser()


def make_backend() -> Any:
    if sys.platform == "darwin":
        from .backend_mac import MacBackend
        return MacBackend()
    if sys.platform == "win32":
        from .backend_win import WinBackend
        return WinBackend()
    raise AutoCADError(f"unsupported platform: {sys.platform} (AutoCAD runs on macOS and Windows)")


backend: Any = None  # created on first use; tests put a fake here
_trusted_checked = False


def _backend() -> Any:
    global backend
    if backend is None:
        backend = make_backend()
    return backend


INSTRUCTIONS = """\
Controls a running AutoCAD through AutoLISP.

How to work:
- Start with autocad_status. If no drawing is open, call autocad_new_drawing.
- autocad_eval_lisp is the universal tool: any AutoLISP runs there and its return value comes back as JSON.
- autocad_command runs one AutoCAD command with arguments, like (command ...).
- After drawing, check the result with autocad_screenshot (zoom first: autocad_command ["_.ZOOM","_E"]).

AutoLISP rules that matter here:
- Write portable code: entmake/entmod/entget/ssget/tblsearch/command. vla-*/vlax-*/vlr-* do not exist on Mac.
- Use English command names with the "_." prefix and "_" before options: "_.LINE", "_.ZOOM" "_E".
- Points are lists: (list x y 0). "" in (command ...) is Enter.
- entmake is the fastest and most exact way to create 2D objects, e.g.
  (entmake (list '(0 . "LINE") '(8 . "0") (cons 10 '(0 0 0)) (cons 11 '(100 0 0))))
- Symbols are case-insensitive (h and H are the same variable) and scoping is dynamic:
  declare locals after "/" in defun and do not reuse a global's name for a local.
- Set OSMODE to 0 before (command ...) with points and restore it afterwards, or object snaps move the points.
- 3D: (command "_.BOX" corner1 corner2-at-the-same-z height) - the height is a separate number.
  After (command "_.UCS" origin ...) the next points are measured from the NEW origin; always end with (command "_.UCS" "_W").
- Never call functions that wait for the user (getpoint, getstring, entsel, ssget without a mode,
  or commands that expect clicks or open dialogs). Nobody can answer them and the call will time out.
- Each call is one undo group, so a single _.UNDO 1 reverts it.
"""

mcp = FastMCP("autocad", instructions=INSTRUCTIONS)


# ---------------------------------------------------------------- helpers

def _console_since(before: str, *, hide: str | None = None) -> str:
    """Text AutoCAD printed to its command line after `before` was captured."""
    after = _backend().history()
    new = after[len(before):] if after.startswith(before) else after[-2000:]
    lines = [
        ln for ln in new.splitlines()
        if ln.strip() not in ("", "Command:", "Command: *Cancel*") and not (hide and hide in ln)
    ]
    return "\n".join(lines)[-4000:]


def _lisp_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _lisp_path(p: Path) -> str:
    """Path as an AutoLISP string literal; forward slashes work on both systems."""
    return _lisp_str(p.as_posix())


def _check_parens(code: str) -> None:
    depth = 0
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        if c == ";":
            if code.startswith(";|", i):  # block comment ;| ... |;
                j = code.find("|;", i + 2)
                i = n if j < 0 else j + 2
                continue
            j = code.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == '"':
            i += 1
            while i < n and code[i] != '"':
                i += 2 if code[i] == "\\" else 1
            if i >= n:
                raise AutoCADError("unterminated string literal in AutoLISP code")
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                raise AutoCADError("unbalanced parentheses: extra ')'")
        i += 1
    if depth:
        raise AutoCADError(f"unbalanced parentheses: {depth} unclosed '('")


@contextmanager
def _lock():
    """One request at a time, also across several server processes."""
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    with open(BRIDGE_DIR / ".lock", "a+") as f:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def _ensure_drawing() -> None:
    st = _backend().status()
    if not st.get("running"):
        raise AutoCADError(f"{st.get('error') or 'AutoCAD is not running'}. Start AutoCAD first.")
    if st.get("drawing_open") is False:
        raise AutoCADError(
            f"No drawing is open in AutoCAD (window title: {st.get('title')!r}). "
            "Call autocad_new_drawing or open a .dwg."
        )


def _install_lib() -> Path:
    """Copy mcp_lib.lsp into the trusted bridge folder in the encoding this AutoCAD reads."""
    lib = BRIDGE_DIR / "mcp_lib.lsp"
    if not lib.exists() or lib.stat().st_mtime < LIB_SRC.stat().st_mtime:
        lib.write_text(LIB_SRC.read_text(encoding="utf-8"), encoding=_backend().lisp_encoding)
    return lib


def _read_result(path: Path) -> dict[str, Any] | None:
    """Parsed result file, or None while AutoCAD is still writing it."""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:  # AutoCAD older than 2021 writes the ANSI code page
        text = data.decode(locale.getpreferredencoding(False), errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _load_line(req: Path) -> str:
    """The one line AutoCAD is asked to run. The first one also whitelists our folder:
    with SECURELOAD on, (load) from a folder outside TRUSTEDPATHS is silently cancelled."""
    load = f"(load {_lisp_path(req)})"
    if _trusted_checked:
        return f"(progn {load})"
    folder = _lisp_str(str(BRIDGE_DIR))
    entry = _lisp_str(str(BRIDGE_DIR) + os.sep + "...")
    return (
        f'(progn (if (not (vl-string-search {folder} (getvar "TRUSTEDPATHS"))) '
        f'(setvar "TRUSTEDPATHS" (if (= "" (getvar "TRUSTEDPATHS")) {entry} '
        f'(strcat (getvar "TRUSTEDPATHS") ";" {entry})))) {load})'
    )


def _run_lisp(body: str, *, undo: bool = True, timeout: float = 60, console: bool = False) -> Any:
    """Evaluate AutoLISP forms inside AutoCAD and return the decoded JSON value.

    With console=True returns {"value": ..., "console": <new command line output>}.
    """
    global _trusted_checked
    _check_parens(body)
    _ensure_drawing()
    be = _backend()
    with _lock():
        lib = _install_lib()
        rid = uuid.uuid4().hex[:12]
        req = BRIDGE_DIR / f"req_{rid}.lsp"
        res = BRIDGE_DIR / f"res_{rid}.json"
        req.write_text(
            f"(load {_lisp_path(lib)})\n"
            f"(mcp:run {_lisp_path(res)} (quote (lambda ()\n{body}\n)) {'T' if undo else 'nil'})\n",
            encoding=be.lisp_encoding,
        )
        try:
            before = be.history()
            be.send_line(_load_line(req))

            deadline = time.time() + timeout
            next_console_check = time.time() + 1.0
            while time.time() < deadline:
                if res.exists():
                    data = _read_result(res)
                    if data is None:
                        time.sleep(0.05)
                        continue
                    _trusted_checked = True
                    out = _console_since(before, hide=rid)
                    if not data.get("ok"):
                        raise AutoCADError(
                            f"AutoLISP error: {data.get('error')}" + (f"\nConsole:\n{out}" if out else "")
                        )
                    if console:
                        return {"value": data.get("value"), "console": out}
                    return data.get("value")
                if time.time() >= next_console_check:
                    # An error outside vl-catch-all-apply (a syntax error, a cancelled command) stops
                    # mcp:run before it writes the result; the console is the only place it shows up.
                    next_console_check = time.time() + 1.0
                    out = _console_since(before, hide=rid)
                    if "; error:" in out:
                        time.sleep(0.3)
                        if not res.exists():
                            raise AutoCADError(f"AutoLISP error (code did not finish):\n{out}")
                time.sleep(0.1)

            out = _console_since(before, hide=rid)
            raise AutoCADError(
                f"No answer from AutoCAD within {timeout:.0f}s. It may be waiting for input (a dialog, "
                "a prompt or a command that expects clicks). Check with autocad_screenshot; autocad_type with "
                "an empty text and enter=False sends Escape." + (f"\nConsole:\n{out}" if out else "")
            )
        finally:
            for p in (req, res):
                p.unlink(missing_ok=True)


def _to_lisp(v: Any) -> str:
    """Convert a JSON value into an AutoLISP literal for (command ...)."""
    if v is None:
        return '""'
    if isinstance(v, bool):
        return "T" if v else "nil"
    if isinstance(v, (int, float)):
        return repr(float(v)) if isinstance(v, float) else str(v)
    if isinstance(v, str):
        return _lisp_str(v)
    if isinstance(v, (list, tuple)):
        return "(list " + " ".join(_to_lisp(x) for x in v) + ")"
    raise AutoCADError(f"unsupported argument type: {type(v).__name__}")


DXF_NAMES = {
    -1: "ename", 0: "type", 1: "text", 2: "name", 3: "text2", 5: "handle", 6: "linetype", 7: "style",
    8: "layer", 10: "p10", 11: "p11", 12: "p12", 13: "p13", 38: "elevation", 39: "thickness",
    40: "r40", 41: "r41", 42: "r42", 43: "r43", 48: "ltscale", 50: "angle", 51: "angle2",
    62: "color", 70: "flags", 71: "i71", 72: "i72", 90: "count", 210: "normal", 330: "owner",
    370: "lineweight", 420: "truecolor", 440: "transparency",
}
POINT_KEYS = ("p10", "p11", "p12", "p13", "normal")


def _dxf_dict(items: Any) -> Any:
    """[[0,"LINE"],[10,x,y,z],...] -> {"type":"LINE","p10":[x,y,z],...}; repeated codes become lists."""
    if not (isinstance(items, list) and items and all(isinstance(x, list) and x and isinstance(x[0], int) for x in items)):
        return items
    out: dict[str, Any] = {}
    seen: set[str] = set()
    for it in items:
        code, val = it[0], (it[1] if len(it) == 2 else it[1:])
        key = DXF_NAMES.get(code, str(code))
        if key not in out:
            out[key] = val
        elif key in seen:
            out[key].append(val)
        else:
            seen.add(key)
            out[key] = [out[key], val]
    return out


def _result(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- tools

@mcp.tool()
def autocad_status() -> str:
    """Is AutoCAD running, which drawing is open. Does not touch AutoCAD's UI."""
    be = _backend()
    st = dict(be.status())
    st["platform"] = be.name
    st["notes"] = be.notes
    st["bridge_dir"] = str(BRIDGE_DIR)
    return _result(st)


@mcp.tool()
def autocad_eval_lisp(code: str, undo_group: bool = True, timeout: float = 60) -> str:
    """Run arbitrary AutoLISP code in the active drawing and return the value of the last form as JSON.

    `code` may contain several forms, defun, loops, (command ...), entmake, etc.
    Lists of ("key" . value) pairs come back as JSON objects, entity names as {"handle": ...},
    selection sets as {"selection_count", "handles"}. "console" is what AutoCAD printed.
    undo_group=True wraps the call in one UNDO group.
    """
    return _result(_run_lisp(code, undo=undo_group, timeout=timeout, console=True))


@mcp.tool()
def autocad_command(args: list[Any], timeout: float = 60) -> str:
    """Run one AutoCAD command through (command ...).

    args: command name then its inputs. Strings stay strings, numbers stay numbers,
    a list of numbers becomes a point, null becomes Enter ("").
    Examples:
      ["_.CIRCLE", [0,0], 50]
      ["_.LINE", [0,0], [100,0], [100,50], null]
      ["_.ZOOM", "_E"]
      ["_.-LAYER", "_M", "WALLS", "_C", "1", "", null]
    Returns the entity the command created ("created": null for commands like ZOOM).
    """
    if not args:
        raise AutoCADError("args must start with a command name")
    body = (
        "(setq *mcp-last* (entlast))\n"
        f"(command {' '.join(_to_lisp(a) for a in args)})\n"
        "(if (equal *mcp-last* (entlast)) nil (entlast))"
    )
    r = _run_lisp(body, timeout=timeout, console=True)
    return _result({"created": r["value"], "console": r["console"]})


@mcp.tool()
def autocad_drawing_info() -> str:
    """Drawing summary: file name, units, extents, entity count, layers, blocks, text styles, linetypes."""
    return _result(_run_lisp("(mcp:info)", undo=False))


@mcp.tool()
def autocad_list_layers() -> str:
    """All layers with color, on/off, frozen, locked, linetype."""
    return _result(_run_lisp("(mcp:layers)", undo=False))


@mcp.tool()
def autocad_list_entities(entity_type: str | None = None, layer: str | None = None, limit: int = 200) -> str:
    """List entities in the drawing with their main DXF data (handle 5, type 0, layer 8, points 10/11,
    radius 40, text 1, ...). Filters use ssget wildcards: entity_type="LINE,CIRCLE", layer="WALL*"."""
    flt = []
    if entity_type:
        flt.append(f"(cons 0 {_lisp_str(entity_type)})")
    if layer:
        flt.append(f"(cons 8 {_lisp_str(layer)})")
    ss = f'(ssget "_X" (list {" ".join(flt)}))' if flt else '(ssget "_X")'
    r = _run_lisp(f"(mcp:ss->summaries {ss} {int(limit)})", undo=False)
    items = [_dxf_dict(e) for e in (r.get("items") or [])]
    return json.dumps({"total": r.get("total"), "items": items}, ensure_ascii=False, separators=(",", ":"))


@mcp.tool()
def autocad_get_entity(handle: str) -> str:
    """Full DXF data (entget, including xdata) of one entity by its handle."""
    body = (
        f"(if (setq *mcp-e* (handent {_lisp_str(handle)})) (entget *mcp-e* (list \"*\")) "
        f"(mcp:fail {_lisp_str('no entity with handle ' + handle)}))"
    )
    return json.dumps(_dxf_dict(_run_lisp(body, undo=False)), ensure_ascii=False, separators=(",", ":"))


@mcp.tool()
def autocad_screenshot(max_size: int = 1600) -> Image:
    """Screenshot of the AutoCAD window, to check visually what was drawn."""
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    path = BRIDGE_DIR / "screenshot.png"
    _backend().screenshot(path, max_size)
    return Image(path=str(path))


@mcp.tool()
def autocad_type(text: str, enter: bool = True, escape_first: bool = True) -> str:
    """Send raw text to the AutoCAD command line, exactly like a user typing (space acts as Enter outside LISP).
    Use for things LISP cannot do; check the result with autocad_screenshot.
    Empty text with enter=False just sends Escape (cancels a hanging command)."""
    _ensure_drawing()
    be = _backend()
    with _lock():
        before = be.history()
        be.send_line(text, escape=escape_first, enter=enter)
        time.sleep(1.0)
        return _result({"sent": text, "console": _console_since(before)})


@mcp.tool()
def autocad_new_drawing() -> str:
    """Create a new drawing from the default template and make it the active one."""
    with _lock():
        return _result({"opened": _backend().new_drawing()})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
