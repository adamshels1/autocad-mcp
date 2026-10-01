"""The self-test script itself, against the fake AutoCAD."""

from autocad_mcp import selftest


def lisp_answers(fake):
    def answer(body):
        if body == "(+ 1 2)":
            return {"ok": True, "value": 3}
        if "Стены" in body:
            return {"ok": True, "value": "Стены ё"}
        if '(cons "pt"' in body:
            return {"ok": True, "value": {"pt": [1.5, -0.25, 0], "on": True}}
        if body == "(+ 1 nil)":
            return {"ok": False, "error": "bad argument type: numberp: nil"}
        if "mcp-selftest-marker" in body:
            fake.log += "mcp-selftest-marker\n"
            return {"ok": True, "value": 1}
        if "entmake" in body:
            return {"ok": True, "value": ["LINE", [123, 0, 0]]}
        if "_.REGEN" in body:
            return {"ok": True, "value": None}
        if body == "(mcp:info)":
            return {"ok": True, "value": {"dwgname": "Drawing1.dwg"}}
        raise AssertionError(f"unexpected code: {body}")
    return answer


def test_all_checks_pass(fake, capsys):
    fake.answer = lisp_answers(fake)
    fake.screenshot = lambda path, max_size: path.write_bytes(b"x" * 5000)
    assert selftest.main() == 0
    out = capsys.readouterr().out
    assert out.count("PASS") == len(selftest.CHECKS) and "FAIL" not in out
    assert f"all {len(selftest.CHECKS)} checks passed" in out


def test_stops_early_without_autocad(fake, capsys):
    fake.state = {"running": False, "error": "AutoCAD is not running"}
    assert selftest.main() == 1
    out = capsys.readouterr().out
    assert out.count("FAIL  ") == 1 and "PASS" not in out and "AutoCAD is not running" in out


def test_failures_are_counted(fake, capsys):
    answer = lisp_answers(fake)
    fake.answer = lambda body: {"ok": True, "value": 4} if body == "(+ 1 2)" else answer(body)
    fake.screenshot = lambda path, max_size: path.write_bytes(b"x" * 5000)
    assert selftest.main() == 1
    out = capsys.readouterr().out
    assert "FAIL  arithmetic: got 4, expected 3" in out
    assert f"1 of {len(selftest.CHECKS)} checks FAILED" in out
