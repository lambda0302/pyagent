"""D1: TUI command dispatch, /quit exit, Ctrl+C handling, session save."""

from __future__ import annotations

import io

from rich.console import Console

from pyagent.config import Config
from pyagent.core.messages import Session
from pyagent.tui.app import PyAgentApp


class _FakeLoop:
    renderer = None

    def __init__(self, session):
        self.session = session
        self.prompts = []

    def run(self, prompt=None):
        self.prompts.append(prompt)
        self.session.append_user(prompt or "")
        self.session.append_assistant("ok")
        return "ok"


class _Input:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self, prompt_text=""):
        if not self.values:
            raise EOFError
        return self.values.pop(0)


def test_quit_exits_and_saves_session(tmp_path, monkeypatch):
    config = Config()
    session = Session(session_id="q-session")
    loop = _FakeLoop(session)
    app = PyAgentApp(
        config=config,
        session=session,
        loop=loop,
        session_dir=tmp_path,
        console=Console(file=io.StringIO()),
    )
    app._prompt = None
    monkeypatch.setattr("builtins.input", _Input(["/quit"]))
    app.run()  # should return cleanly, not raise
    assert (tmp_path / "q-session.json").exists()


def test_keyboard_interrupt_is_caught(tmp_path, monkeypatch):
    config = Config()
    session = Session(session_id="int-session")
    loop = _FakeLoop(session)
    app = PyAgentApp(
        config=config,
        session=session,
        loop=loop,
        session_dir=tmp_path,
        console=Console(file=io.StringIO()),
    )
    app._prompt = None

    calls = []

    def interrupting_input(_prompt_text=""):
        calls.append(1)
        if len(calls) == 1:
            raise KeyboardInterrupt
        return "/quit"

    monkeypatch.setattr("builtins.input", interrupting_input)
    app.run()  # Ctrl+C must not crash the TUI
    assert (tmp_path / "int-session.json").exists()


def test_task_runs_loop_and_autosaves(tmp_path, monkeypatch):
    config = Config()
    session = Session(session_id="task-session")
    loop = _FakeLoop(session)
    app = PyAgentApp(
        config=config,
        session=session,
        loop=loop,
        session_dir=tmp_path,
        console=Console(file=io.StringIO()),
    )
    app._prompt = None
    monkeypatch.setattr("builtins.input", _Input(["create a file", "/quit"]))
    app.run()
    assert loop.prompts == ["create a file"]
    assert len(session.messages) == 2
    # auto-saved after the task and again on exit
    assert (tmp_path / "task-session.json").exists()


def test_resume_swaps_session(tmp_path, monkeypatch):
    from pyagent.core.messages import Session as Sess

    saved = Sess(session_id="old-session")
    saved.append_user("earlier")
    saved.save(tmp_path)

    config = Config()
    loop = _FakeLoop(Sess(session_id="new-session"))
    app = PyAgentApp(
        config=config,
        session=loop.session,
        loop=loop,
        session_dir=tmp_path,
        console=Console(file=io.StringIO()),
    )
    app._prompt = None
    monkeypatch.setattr("builtins.input", _Input(["/resume old-session", "/quit"]))
    app.run()
    assert loop.session.session_id == "old-session"
    assert len(loop.session.messages) == 1
