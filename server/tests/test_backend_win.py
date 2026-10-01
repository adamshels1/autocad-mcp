"""Windows backend against a fake COM AutoCAD (pythoncom/win32com are replaced)."""

import sys
import types

import pytest

from autocad_mcp import backend_win
from autocad_mcp.backend_win import RPC_E_CALL_REJECTED, WinBackend, decode_log
from autocad_mcp.errors import AutoCADError


class ComError(Exception):
    """Stands in for pywintypes.com_error: args[0] is the HRESULT."""

    def __init__(self, hresult):
        super().__init__(hresult, "msg", None, None)
        self.hresult = hresult


class FakeDoc:
    def __init__(self, name="Drawing1.dwg", has_post=True):
        self.Name = name
        self.sent: list[tuple[str, str]] = []
        self.vars = {"LOGFILEMODE": 0, "LOGFILENAME": ""}
        self.busy = 0           # how many calls to reject as "busy" first
        self.activated = False
        self._has_post = has_post
        self.post_error = None

    def _maybe_busy(self):
        if self.busy:
            self.busy -= 1
            raise ComError(RPC_E_CALL_REJECTED)

    def __getattr__(self, name):
        if name == "PostCommand" and self.__dict__.get("_has_post"):
            def post(text):
                self._maybe_busy()
                if self.post_error:
                    raise self.post_error
                self.sent.append(("post", text))
            return post
        raise AttributeError(name)

    def SendCommand(self, text):
        self._maybe_busy()
        self.sent.append(("send", text))

    def GetVariable(self, name):
        return self.vars[name]

    def SetVariable(self, name, value):
        self.vars[name] = value

    def Activate(self):
        self.activated = True


class FakeDocs:
    def __init__(self, app):
        self._app = app

    @property
    def Count(self):
        return len(self._app.docs)

    def Add(self):
        doc = FakeDoc(f"Drawing{len(self._app.docs) + 1}.dwg")
        self._app.docs.append(doc)
        return doc


class FakeApp:
    Caption = "Autodesk AutoCAD 2026 - [Drawing1.dwg]"
    HWND = 1234

    def __init__(self, docs=None):
        self.docs = [FakeDoc()] if docs is None else docs
        self.Documents = FakeDocs(self)

    @property
    def ActiveDocument(self):
        return self.docs[-1]


@pytest.fixture
def com(monkeypatch):
    """Installs fake pythoncom / win32com.client; com.app is the running AutoCAD (None = not running)."""
    holder = types.SimpleNamespace(app=FakeApp(), coinit=0)

    pythoncom = types.ModuleType("pythoncom")

    def co_initialize():
        holder.coinit += 1
    pythoncom.CoInitialize = co_initialize

    client = types.ModuleType("win32com.client")

    def get_active_object(progid):
        assert progid == "AutoCAD.Application"
        if holder.app is None:
            raise ComError(-2147221021)  # MK_E_UNAVAILABLE
        return holder.app
    client.GetActiveObject = get_active_object

    win32com = types.ModuleType("win32com")
    win32com.client = client
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setattr(backend_win.time, "sleep", lambda s: None)
    return holder


def test_status_with_a_drawing(com):
    st = WinBackend().status()
    assert st == {
        "running": True, "drawing_open": True, "documents": 1,
        "title": "Autodesk AutoCAD 2026 - [Drawing1.dwg]", "drawing": "Drawing1.dwg",
    }
    assert com.coinit == 1


def test_status_without_drawings(com):
    com.app = FakeApp(docs=[])
    st = WinBackend().status()
    assert st["running"] is True and st["drawing_open"] is False and "drawing" not in st


def test_status_when_autocad_is_not_running(com):
    com.app = None
    st = WinBackend().status()
    assert st["running"] is False and "not running" in st["error"]


def test_send_line_posts_cancel_line_and_enter(com):
    WinBackend().send_line('(progn (load "C:/x/req_1.lsp"))')
    assert com.app.ActiveDocument.sent == [("post", '\x1b\x1b(progn (load "C:/x/req_1.lsp"))\n')]


def test_send_line_flags(com):
    be = WinBackend()
    be.send_line("ZOOM", escape=False)
    be.send_line("", enter=False)          # just Escape
    be.send_line("", escape=False, enter=False)  # nothing to send
    assert com.app.ActiveDocument.sent == [("post", "ZOOM\n"), ("post", "\x1b\x1b")]


def test_falls_back_to_sendcommand_without_postcommand(com):
    com.app.docs = [FakeDoc(has_post=False)]
    WinBackend().send_line("REGEN")
    assert com.app.ActiveDocument.sent == [("send", "\x1b\x1bREGEN\n")]


def test_falls_back_to_sendcommand_on_unknown_member(com):
    com.app.ActiveDocument.post_error = ComError(-2147352570)  # DISP_E_UNKNOWNNAME
    WinBackend().send_line("REGEN")
    assert com.app.ActiveDocument.sent == [("send", "\x1b\x1bREGEN\n")]


def test_busy_autocad_is_retried(com):
    com.app.ActiveDocument.busy = 3
    WinBackend().send_line("REGEN")
    assert com.app.ActiveDocument.sent == [("post", "\x1b\x1bREGEN\n")]


def test_busy_forever_gives_a_clear_error(com):
    com.app.ActiveDocument.busy = 10_000
    with pytest.raises(AutoCADError, match="AutoCAD is busy"):
        WinBackend().send_line("REGEN")
    assert com.app.ActiveDocument.sent == []


def test_other_com_errors_are_reported(com):
    com.app.ActiveDocument.post_error = ComError(-2147467259)  # E_FAIL
    with pytest.raises(AutoCADError, match="AutoCAD COM error"):
        WinBackend().send_line("REGEN")


def test_send_line_without_a_drawing(com):
    com.app = FakeApp(docs=[])
    with pytest.raises(AutoCADError, match="No drawing is open"):
        WinBackend().send_line("REGEN")


def test_new_drawing(com):
    assert WinBackend().new_drawing() == "Drawing2.dwg"
    assert len(com.app.docs) == 2 and com.app.docs[-1].activated


@pytest.mark.parametrize("encoding", ["utf-16", "utf-8", "utf-8-sig", "cp1251"])
def test_history_reads_the_log_file(com, tmp_path, monkeypatch, encoding):
    text = "Command: (princ)\nпривет из lisp\n; error: bad argument type\n"
    log = tmp_path / "Drawing1.log"
    log.write_bytes(text.encode(encoding))
    doc = com.app.ActiveDocument
    doc.vars["LOGFILENAME"] = str(log)
    assert WinBackend().history() == text
    assert doc.vars["LOGFILEMODE"] == 1      # logging was switched on


def test_history_of_a_big_log_keeps_the_tail(com, tmp_path, monkeypatch):
    monkeypatch.setattr(backend_win, "LOG_TAIL_BYTES", 64)
    log = tmp_path / "big.log"
    log.write_bytes(("x" * 500 + "\nконец\n").encode("utf-16"))
    com.app.ActiveDocument.vars["LOGFILENAME"] = str(log)
    tail = WinBackend().history()
    assert tail.endswith("\nконец\n") and len(tail) < 40


def test_history_is_empty_when_unavailable(com, tmp_path):
    com.app.ActiveDocument.vars["LOGFILENAME"] = str(tmp_path / "missing.log")
    assert WinBackend().history() == ""
    com.app = None
    assert WinBackend().history() == ""


def test_decode_log_never_fails():
    assert decode_log(b"") == ""
    assert decode_log(b"\xff\xfeh\x00i\x00") == "hi"
    assert isinstance(decode_log(b"\xff\xff\xff"), str)   # garbage is replaced, not raised


def test_missing_pywin32_is_explained(monkeypatch):
    monkeypatch.setitem(sys.modules, "pythoncom", None)
    with pytest.raises(AutoCADError, match="pywin32 is not installed"):
        WinBackend()._app()
