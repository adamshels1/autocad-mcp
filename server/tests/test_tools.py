"""MCP tools build the right AutoLISP and shape the answers."""

import json

import pytest

from autocad_mcp import server
from autocad_mcp.errors import AutoCADError


def test_status(fake):
    st = json.loads(server.autocad_status())
    assert st["running"] is True and st["drawing_open"] is True
    assert st["platform"] == "fake" and "bridge_dir" in st


def test_eval_lisp_returns_value_and_console(fake):
    fake.answer = lambda body: {"ok": True, "value": [1, 2]}
    assert json.loads(server.autocad_eval_lisp("(list 1 2)")) == {"value": [1, 2], "console": ""}


def test_command_builds_a_command_call(fake):
    fake.answer = lambda body: {"ok": True, "value": {"handle": "2CC"}}
    out = json.loads(server.autocad_command(["_.LINE", [0, 0], [100, 0], None]))
    assert out == {"created": {"handle": "2CC"}, "console": ""}
    assert '(command "_.LINE" (list 0 0) (list 100 0) "")' in fake.bodies[0]
    server._check_parens(fake.bodies[0])


def test_command_that_creates_nothing(fake):
    fake.answer = lambda body: {"ok": True, "value": None}
    assert json.loads(server.autocad_command(["_.ZOOM", "_E"]))["created"] is None


def test_command_needs_a_name(fake):
    with pytest.raises(AutoCADError):
        server.autocad_command([])


def test_list_entities_filters_and_shapes(fake):
    fake.answer = lambda body: {"ok": True, "value": {"total": 1, "items": [[[0, "CIRCLE"], [5, "2A"], [8, "СТЕНЫ"], [10, 0, 0, 0], [40, 50]]]}}
    out = json.loads(server.autocad_list_entities(entity_type="CIRCLE", layer="СТЕН*", limit=10))
    assert out == {"total": 1, "items": [{"type": "CIRCLE", "handle": "2A", "layer": "СТЕНЫ", "p10": [0, 0, 0], "r40": 50}]}
    assert fake.bodies[0] == '(mcp:ss->summaries (ssget "_X" (list (cons 0 "CIRCLE") (cons 8 "СТЕН*"))) 10)'
    assert fake.undo_flags == ["nil"]


def test_list_entities_without_filters_and_empty_drawing(fake):
    fake.answer = lambda body: {"ok": True, "value": {"total": 0, "items": None}}
    assert json.loads(server.autocad_list_entities()) == {"total": 0, "items": []}
    assert fake.bodies[0] == '(mcp:ss->summaries (ssget "_X") 200)'


def test_get_entity(fake):
    fake.answer = lambda body: {"ok": True, "value": [[0, "LINE"], [5, "2CD"]]}
    assert json.loads(server.autocad_get_entity("2CD")) == {"type": "LINE", "handle": "2CD"}
    assert '(handent "2CD")' in fake.bodies[0]
    server._check_parens(fake.bodies[0])


def test_type_sends_raw_text(fake, monkeypatch):
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    out = json.loads(server.autocad_type("REGEN"))
    assert out["sent"] == "REGEN" and fake.lines == ["REGEN"]


def test_new_drawing(fake):
    assert json.loads(server.autocad_new_drawing()) == {"opened": "Drawing2.dwg"}


def test_screenshot(fake):
    img = server.autocad_screenshot(max_size=800)
    assert fake.screenshots == [(server.BRIDGE_DIR / "screenshot.png", 800)]
    assert str(img.path) == str(server.BRIDGE_DIR / "screenshot.png")


def test_lisp_library_is_well_formed():
    text = server.LIB_SRC.read_text(encoding="utf-8")
    server._check_parens(text)
    for name in ("mcp:run", "mcp:json", "mcp:info", "mcp:layers", "mcp:ss->summaries", "mcp:fail"):
        assert f"(defun {name} " in text
    # must run on AutoCAD for Mac too: no ActiveX there
    code = "\n".join(ln.split(";")[0] for ln in text.splitlines())
    assert "(vla-" not in code and "(vlax-" not in code and "(vlr-" not in code
