import pytest

from autocad_mcp import server
from autocad_mcp.errors import AutoCADError


@pytest.mark.parametrize("code", [
    "(+ 1 2)",
    '(princ "a ) b")',                      # paren inside a string
    '(princ "quote \\" and ) inside")',     # escaped quote inside a string
    "(setq a 1) ; comment with ) and (\n(setq b 2)",
    "(setq a 1) ;| block ) comment |; (setq b 2)",
    "",
])
def test_balanced_code_passes(code):
    server._check_parens(code)


@pytest.mark.parametrize("code, message", [
    ("(+ 1 2", "1 unclosed"),
    ("(defun f () (list 1 2)", "1 unclosed"),
    ("(+ 1 2))", "extra"),
    ('(princ "never closed)', "unterminated string"),
])
def test_unbalanced_code_is_rejected(code, message):
    with pytest.raises(AutoCADError, match=message):
        server._check_parens(code)


def test_lisp_str_escapes():
    assert server._lisp_str('a"b') == '"a\\"b"'
    assert server._lisp_str("C:\\Users\\x") == '"C:\\\\Users\\\\x"'
    assert server._lisp_str("line1\nline2") == '"line1\\nline2"'
    assert server._lisp_str("Привет") == '"Привет"'


def test_to_lisp_values():
    assert server._to_lisp("_.LINE") == '"_.LINE"'
    assert server._to_lisp(50) == "50"
    assert server._to_lisp(2.5) == "2.5"
    assert server._to_lisp([0, 0]) == "(list 0 0)"
    assert server._to_lisp([1.5, -2, 0]) == "(list 1.5 -2 0)"
    assert server._to_lisp(None) == '""'      # Enter
    assert server._to_lisp(True) == "T"
    assert server._to_lisp(False) == "nil"
    with pytest.raises(AutoCADError):
        server._to_lisp({"a": 1})


def test_dxf_dict_names_and_points():
    d = server._dxf_dict([[0, "LINE"], [5, "2CD"], [8, "0"], [10, 0, 0, 0], [11, 100, 0, 0]])
    assert d == {"type": "LINE", "handle": "2CD", "layer": "0", "p10": [0, 0, 0], "p11": [100, 0, 0]}


def test_dxf_dict_repeated_codes_become_lists():
    d = server._dxf_dict([[0, "LWPOLYLINE"], [90, 3], [10, 0, 0], [10, 5, 0], [10, 5, 5], [100, "A"], [100, "B"]])
    assert d["p10"] == [[0, 0], [5, 0], [5, 5]]
    assert d["100"] == ["A", "B"]
    assert d["count"] == 3


def test_dxf_dict_leaves_other_values_alone():
    assert server._dxf_dict(None) is None
    assert server._dxf_dict([]) == []
    assert server._dxf_dict(["a", "b"]) == ["a", "b"]
    assert server._dxf_dict({"total": 1}) == {"total": 1}


def test_console_since_filters_noise(fake):
    before = fake.log
    fake.log += "Command: *Cancel*\nCommand: (progn (load \"x/req_abc123.lsp\"))\nhello\n\n; error: boom\nCommand:\n"
    assert server._console_since(before, hide="req_abc123") == "hello\n; error: boom"


def test_console_since_when_history_was_cut(fake):
    before = "something that is no longer at the start"
    fake.log = "tail of a rotated log\nvalue\n"
    assert server._console_since(before) == "tail of a rotated log\nvalue"
