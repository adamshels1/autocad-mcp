"""Test doubles: a fake AutoCAD that answers request files the way mcp_lib.lsp does."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from autocad_mcp import server

LOAD_RE = re.compile(r'\(load "([^"]+req_[0-9a-f]+\.lsp)"\)')
RUN_RE = re.compile(r'\(mcp:run "([^"]+)" \(quote \(lambda \(\)\n(.*)\n\)\) (T|nil)\)\n\Z', re.S)


class FakeBackend:
    name = "fake"
    notes = "fake backend"
    lisp_encoding = "utf-8"

    def __init__(self) -> None:
        self.lines: list[str] = []          # everything sent to the command line
        self.bodies: list[str] = []         # AutoLISP bodies that were "executed"
        self.undo_flags: list[str] = []
        self.log = "Command:\n"             # command line history
        self.state = {"running": True, "drawing_open": True, "title": "Drawing1.dwg"}
        self.answer = lambda body: {"ok": True, "value": None}
        self.raw_result: bytes | None = None  # write these bytes instead of JSON
        self.screenshots: list[tuple[Path, int]] = []

    def status(self):
        return dict(self.state)

    def history(self) -> str:
        return self.log

    def send_line(self, line: str, *, escape: bool = True, enter: bool = True) -> None:
        self.lines.append(line)
        self.log += f"Command: {line}\n"
        m = LOAD_RE.search(line)
        if not m:
            return
        req = Path(m.group(1))
        text = req.read_bytes().decode(self.lisp_encoding)
        run = RUN_RE.search(text)
        assert run, f"unexpected request file:\n{text}"
        res_path, body, undo = run.groups()
        self.bodies.append(body)
        self.undo_flags.append(undo)
        result = self.answer(body)
        if result is None:      # AutoCAD never answers
            return
        if self.raw_result is not None:
            Path(res_path).write_bytes(self.raw_result)
        else:
            Path(res_path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    def screenshot(self, path: Path, max_size: int) -> None:
        self.screenshots.append((path, max_size))
        path.write_bytes(b"\x89PNG\r\n\x1a\n")

    def new_drawing(self) -> str:
        return "Drawing2.dwg"


@pytest.fixture
def fake(tmp_path, monkeypatch):
    be = FakeBackend()
    monkeypatch.setattr(server, "backend", be)
    monkeypatch.setattr(server, "BRIDGE_DIR", tmp_path / "bridge")
    monkeypatch.setattr(server, "_trusted_checked", False)
    return be
