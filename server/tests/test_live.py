"""Runs against a real AutoCAD with a drawing open. Opt in: AUTOCAD_MCP_LIVE=1 uv run pytest tests/test_live.py

Everything here leaves the drawing as it was (objects created by a test are erased in the same call).
"""

import json
import os

import pytest

from autocad_mcp import server
from autocad_mcp.errors import AutoCADError

pytestmark = pytest.mark.skipif(os.environ.get("AUTOCAD_MCP_LIVE") != "1", reason="needs a running AutoCAD")


def test_status():
    st = json.loads(server.autocad_status())
    assert st["running"] is True and st["drawing_open"] is not False


def test_arithmetic():
    assert server._run_lisp("(+ 1 2)", undo=False) == 3


def test_json_shapes():
    v = server._run_lisp(
        '(list (cons "name" "Стены \\"A\\"") (cons "pt" (list 1.5 -0.25 0)) (cons "on" T) (cons "none" nil))',
        undo=False,
    )
    assert v == {"name": 'Стены "A"', "pt": [1.5, -0.25, 0], "on": True, "none": None}


def test_list_that_starts_with_a_string():
    v = server._run_lisp('(list (list "VIEWPORT" "0" "Layout1") (list "VIEWPORT" "0" "Layout2"))', undo=False)
    assert v == {"VIEWPORT": ["0", "Layout2"]} or v == [["VIEWPORT", "0", "Layout1"], ["VIEWPORT", "0", "Layout2"]]


def test_user_variables_do_not_break_the_bridge():
    # AutoLISP is dynamically scoped; these names used to be mcp:run's own variables
    assert server._run_lisp('(setq out "x" res 1 json 2 tmp 3 fn 4 undo 5 old-echo 6) 42', undo=False) == 42


def test_lisp_error_is_reported():
    with pytest.raises(AutoCADError, match="numberp"):
        server._run_lisp("(+ 1 nil)", undo=False)


def test_error_inside_a_user_function_is_reported():
    with pytest.raises(AutoCADError, match="numberp"):
        server._run_lisp("(defun mcp-test-f (a / h) (+ a h)) (mcp-test-f 1)", undo=False)


def test_mcp_fail_message():
    with pytest.raises(AutoCADError, match="no entity with handle FFFFFF"):
        server.autocad_get_entity("FFFFFF")


def test_console_output_is_captured():
    r = server._run_lisp('(princ "\\nmcp-live-marker") 1', undo=False, console=True)
    assert r["value"] == 1 and "mcp-live-marker" in r["console"]


def test_create_read_and_erase_an_entity():
    r = server._run_lisp(
        "(entmake (list (cons 0 \"LINE\") (cons 8 \"0\") (cons 10 (list 0 0 0)) (cons 11 (list 123 0 0))))"
        " (setq e (entlast) d (entget e)) (entdel e) (list (cdr (assoc 0 d)) (cdr (assoc 11 d)))",
    )
    assert r == ["LINE", [123, 0, 0]]


def test_command_reports_nothing_created_for_zoom():
    out = json.loads(server.autocad_command(["_.REGEN"]))
    assert out["created"] is None


def test_drawing_info():
    info = json.loads(server.autocad_drawing_info())
    assert info["dwgname"].lower().endswith(".dwg") and "0" in info["layers"]
