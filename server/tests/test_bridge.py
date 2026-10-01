"""The request/response bridge, against a fake AutoCAD."""

import json
import time
from pathlib import PureWindowsPath

import pytest

from autocad_mcp import server
from autocad_mcp.errors import AutoCADError


def test_value_comes_back(fake):
    fake.answer = lambda body: {"ok": True, "value": 3}
    assert server._run_lisp("(+ 1 2)") == 3
    assert fake.bodies == ["(+ 1 2)"]
    assert fake.undo_flags == ["T"]


def test_undo_flag_and_console(fake):
    def answer(body):
        fake.log += "привет из lisp\n"
        return {"ok": True, "value": {"a": 1}}
    fake.answer = answer
    r = server._run_lisp('(princ "x")', undo=False, console=True)
    assert r == {"value": {"a": 1}, "console": "привет из lisp"}
    assert fake.undo_flags == ["nil"]


def test_first_call_whitelists_bridge_folder_then_stops(fake):
    server._run_lisp("1")
    server._run_lisp("2")
    first, second = fake.lines
    assert "TRUSTEDPATHS" in first and str(server.BRIDGE_DIR) in first
    assert "TRUSTEDPATHS" not in second
    assert second.startswith("(progn (load ") and second.endswith("))")


def test_whitelisting_repeats_until_a_call_succeeds(fake):
    fake.answer = lambda body: None
    with pytest.raises(AutoCADError):
        server._run_lisp("1", timeout=0.3)
    fake.answer = lambda body: {"ok": True, "value": 1}
    server._run_lisp("1")
    assert all("TRUSTEDPATHS" in ln for ln in fake.lines)


def test_request_files_are_removed(fake):
    server._run_lisp("(+ 1 2)")
    left = sorted(p.name for p in server.BRIDGE_DIR.iterdir())
    assert left == [".lock", "mcp_lib.lsp"]


def test_library_is_installed_in_backend_encoding(fake):
    fake.lisp_encoding = "utf-8-sig"
    server._run_lisp("1")
    assert (server.BRIDGE_DIR / "mcp_lib.lsp").read_bytes().startswith(b"\xef\xbb\xbf")


def test_cyrillic_code_survives_the_round_trip(fake):
    fake.lisp_encoding = "utf-8-sig"
    fake.answer = lambda body: {"ok": True, "value": body}
    code = '(strcat "Стены" "ё")'
    assert server._run_lisp(code) == code


def test_lisp_error_is_raised_with_console(fake):
    def answer(body):
        fake.log += "some output\n"
        return {"ok": False, "error": "bad argument type: numberp: nil"}
    fake.answer = answer
    with pytest.raises(AutoCADError) as e:
        server._run_lisp("(+ 1 nil)")
    assert "bad argument type: numberp: nil" in str(e.value)
    assert "some output" in str(e.value)


def test_timeout_reports_and_cleans_up(fake):
    fake.answer = lambda body: None
    t0 = time.time()
    with pytest.raises(AutoCADError, match="No answer from AutoCAD within 0s"):
        server._run_lisp("(getpoint)", timeout=0.4)
    assert time.time() - t0 < 3
    assert not list(server.BRIDGE_DIR.glob("req_*")) and not list(server.BRIDGE_DIR.glob("res_*"))


def test_error_seen_only_in_console_fails_fast(fake):
    def answer(body):
        fake.log += "; error: malformed list on input\n"
        return None
    fake.answer = answer
    t0 = time.time()
    with pytest.raises(AutoCADError, match="malformed list on input"):
        server._run_lisp("(foo)", timeout=30)
    assert time.time() - t0 < 5


def test_unbalanced_code_is_never_sent(fake):
    with pytest.raises(AutoCADError, match="unclosed"):
        server._run_lisp("(+ 1 2")
    assert fake.lines == []


def test_no_autocad(fake):
    fake.state = {"running": False, "error": "AutoCAD is not running"}
    with pytest.raises(AutoCADError, match="AutoCAD is not running"):
        server._run_lisp("1")
    assert fake.lines == []


def test_no_drawing_open(fake):
    fake.state = {"running": True, "drawing_open": False, "title": "Start"}
    with pytest.raises(AutoCADError, match="No drawing is open"):
        server._run_lisp("1")
    assert fake.lines == []


def test_unknown_drawing_state_is_allowed(fake):
    fake.state = {"running": True, "drawing_open": None, "title": ""}
    fake.answer = lambda body: {"ok": True, "value": 7}
    assert server._run_lisp("7") == 7


def test_ansi_result_from_old_autocad(fake):
    fake.raw_result = json.dumps({"ok": True, "value": "Стены"}, ensure_ascii=False).encode("cp1251")
    import locale
    orig = locale.getpreferredencoding
    try:
        locale.getpreferredencoding = lambda do_setlocale=True: "cp1251"
        assert server._run_lisp('"x"') == "Стены"
    finally:
        locale.getpreferredencoding = orig


def test_result_with_bom(fake):
    fake.raw_result = b"\xef\xbb\xbf" + json.dumps({"ok": True, "value": 5}).encode()
    assert server._run_lisp("5") == 5


def test_half_written_result_is_awaited(fake, tmp_path):
    p = tmp_path / "r.json"
    p.write_text('{"ok": true, "val', encoding="utf-8")
    assert server._read_result(p) is None
    p.write_text('{"ok": true, "value": 1}', encoding="utf-8")
    assert server._read_result(p) == {"ok": True, "value": 1}


def test_windows_paths_in_the_load_line(fake, monkeypatch):
    bridge = PureWindowsPath(r"C:\Users\Иван\.cad-mcp\autocad")
    monkeypatch.setattr(server, "BRIDGE_DIR", bridge)
    monkeypatch.setattr(server.os, "sep", "\\")
    line = server._load_line(bridge / "req_abc.lsp")
    # the load path uses forward slashes, the trusted folder is the native path with escaped backslashes
    assert '(load "C:/Users/Иван/.cad-mcp/autocad/req_abc.lsp")' in line
    assert '"C:\\\\Users\\\\Иван\\\\.cad-mcp\\\\autocad\\\\..."' in line
    server._check_parens(line)
    assert "\n" not in line
