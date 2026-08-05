"""Desktop GUI tests — headless, no pywebview or display required.

Covers the GUIRenderer (event emission + blocking confirmations) and the
GuiServer (HTTP endpoints + SSE streaming + permission resolution E2E).
"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from conftest import MockLLMClient
from pyagent.config import Config
from pyagent.core.loop import AgentLoop
from pyagent.core.messages import Session
from pyagent.core.model import LLMResponse, ToolCall
from pyagent.gui.renderer import GUIRenderer
from pyagent.tools.permissions import PermissionManager
from pyagent.tools.registry import build_default_registry

_STOP = object()


def _tool_response(name="write_file", arguments=None) -> LLMResponse:
    if arguments is None:
        arguments = json.dumps({"path": "hello.txt", "content": "hello agent"})
    return LLMResponse(tool_calls=[ToolCall(id="call_1", name=name, arguments=arguments)])


def _make_responder(events, pending, records, allow=True):
    """Drain events, auto-resolve permission/diff blocks, record everything."""

    def run():
        while True:
            msg = events.get()
            if msg is _STOP:
                return
            records.append(msg)
            if msg.get("type") == "permission":
                req = pending[msg["id"]]
                req.result = {"decision": "allow" if allow else "deny", "remember": False}
                req.event.set()
            elif msg.get("type") == "diff":
                req = pending[msg["id"]]
                req.result = {"apply": True}
                req.event.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Renderer unit tests
# ---------------------------------------------------------------------------


class TestRenderer:
    def test_pushes_delta_tool_and_final_events(self, tmp_path):
        events: queue.Queue = queue.Queue()
        pending = {}
        renderer = GUIRenderer(events, pending)
        records = []
        responder = _make_responder(events, pending, records)

        loop = AgentLoop(
            llm=MockLLMClient([_tool_response(), LLMResponse(content="done")]),
            registry=build_default_registry(),
            config=Config(),
            session=Session(session_id="s"),
            cwd=tmp_path,
            permissions=PermissionManager(),
            renderer=renderer,
        )
        result = loop.run(prompt="create hello.txt")
        events.put(_STOP)
        responder.join(timeout=5)

        assert result == "done"
        assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello agent"
        types = [r["type"] for r in records]
        assert "tool_start" in types and "tool_result" in types and "final" in types
        tool_start = next(r for r in records if r["type"] == "tool_start")
        assert tool_start["name"] == "write_file"
        tool_result = next(r for r in records if r["type"] == "tool_result")
        assert tool_result["ok"] is True

    def test_confirm_permission_blocks_and_resolves(self):
        events: queue.Queue = queue.Queue()
        pending = {}
        renderer = GUIRenderer(events, pending)
        outcome = {}

        def caller():
            outcome["result"] = renderer.confirm_permission("write", "C:/x/y.txt")

        t = threading.Thread(target=caller, daemon=True)
        t.start()
        msg = events.get(timeout=5)
        assert msg["type"] == "permission"
        assert msg["action"] == "write" and msg["target"] == "C:/x/y.txt"
        pending[msg["id"]].result = {"decision": "deny", "remember": False}
        pending[msg["id"]].event.set()
        t.join(timeout=5)
        assert outcome["result"] == ("deny", False)
        assert not pending  # cleaned up

    def test_show_diff_blocks_and_resolves(self):
        events: queue.Queue = queue.Queue()
        pending = {}
        renderer = GUIRenderer(events, pending)
        outcome = {}

        def caller():
            outcome["result"] = renderer.show_diff("a.py", "--- a\n+++ b")

        t = threading.Thread(target=caller, daemon=True)
        t.start()
        msg = events.get(timeout=5)
        assert msg["type"] == "diff"
        assert "+++" in msg["diff"]
        pending[msg["id"]].result = {"apply": False}
        pending[msg["id"]].event.set()
        t.join(timeout=5)
        assert outcome["result"] is False

    def test_block_times_out(self):
        events: queue.Queue = queue.Queue()
        renderer = GUIRenderer(events, {}, timeout=0.1)
        outcome = {}

        def caller():
            try:
                renderer.confirm_permission("write", "x")
            except TimeoutError as exc:
                outcome["error"] = exc

        t = threading.Thread(target=caller, daemon=True)
        t.start()
        t.join(timeout=5)
        assert isinstance(outcome.get("error"), TimeoutError)
        assert not renderer.pending

    def test_full_loop_permission_gate(self, tmp_path):
        """The whole block/unblock path: a write_file tool call is gated behind
        the GUI permission decision and only lands when allowed."""
        events: queue.Queue = queue.Queue()
        pending = {}
        renderer = GUIRenderer(events, pending)
        records = []
        responder = _make_responder(events, pending, records, allow=True)

        loop = AgentLoop(
            llm=MockLLMClient([_tool_response(), LLMResponse(content="ok")]),
            registry=build_default_registry(),
            config=Config(),
            session=Session(session_id="s"),
            cwd=tmp_path,
            permissions=PermissionManager(),
            renderer=renderer,
        )
        loop.run(prompt="write")
        events.put(_STOP)
        responder.join(timeout=5)

        assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello agent"
        assert any(r["type"] == "permission" for r in records)


# ---------------------------------------------------------------------------
# Server integration tests (urllib)
# ---------------------------------------------------------------------------


def _start_server(tmp_path: Path, llm):
    from pyagent.gui.server import GuiServer

    server = GuiServer(
        Config(),
        session_dir=str(tmp_path / "sessions"),
        cwd=str(tmp_path),
        llm=llm,
        port=0,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _request(base: str, path: str, data: dict | None = None) -> tuple[int, dict]:
    """Return (status, parsed-json-body), tolerating non-2xx responses."""
    if data is None:
        req = urllib.request.Request(f"{base}{path}")
    else:
        req = urllib.request.Request(
            f"{base}{path}",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(base: str, path: str) -> tuple[int, dict]:
    return _request(base, path)


def _post(base: str, path: str, data: dict) -> tuple[int, dict]:
    return _request(base, path, data)


@pytest.fixture
def server(tmp_path):
    servers = []

    def make(llm):
        s = _start_server(tmp_path, llm)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.shutdown()


class TestServer:
    def test_index_serves_html(self, server):
        s = server(MockLLMClient([]))
        with urllib.request.urlopen(f"http://127.0.0.1:{s.port}/", timeout=30) as resp:
            body = resp.read().decode("utf-8")
        assert 'id="input"' in body and "<title>pyagent</title>" in body

    def test_api_health(self, server):
        s = server(MockLLMClient([]))
        status, health = _get(f"http://127.0.0.1:{s.port}", "/api/health")
        assert status == 200 and health["ok"] is True and health["model"]

    def test_sessions_and_resume(self, server):
        s = server(MockLLMClient([LLMResponse(content="hi")]))
        base = f"http://127.0.0.1:{s.port}"

        _, new = _post(base, "/api/new", {})
        assert new["ok"] and new["session_id"]

        # run a quick chat so the session gets persisted with history
        _, chat = _post(base, "/api/chat", {"prompt": "hi"})
        assert chat["ok"]

        _, sessions = _get(base, "/api/sessions")
        assert any(x["session_id"] == new["session_id"] for x in sessions["sessions"])

        _, resumed = _post(base, "/api/resume", {"session_id": new["session_id"]})
        assert resumed["ok"]
        assert any(m["role"] == "user" for m in resumed["messages"])

        status, missing = _post(base, "/api/resume", {"session_id": "ghost"})
        assert status == 404 and missing["ok"] is False

    def test_chat_streams_and_resolves_permission(self, server):
        s = server(MockLLMClient([_tool_response(), LLMResponse(content="done")]))
        base = f"http://127.0.0.1:{s.port}"
        events = []

        def read_stream():
            with urllib.request.urlopen(f"{base}/api/stream", timeout=30) as resp:
                for raw in resp:
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue
                    msg = json.loads(line[6:])
                    events.append(msg)
                    if msg["type"] == "permission":
                        _post(base, "/api/permission", {"id": msg["id"], "decision": "allow", "remember": False})
                    if msg["type"] == "run_end":
                        break

        reader = threading.Thread(target=read_stream, daemon=True)
        reader.start()
        time.sleep(0.3)  # let the SSE connection establish
        _, chat = _post(base, "/api/chat", {"prompt": "create hello.txt"})
        assert chat["ok"]
        reader.join(timeout=30)

        types = [e["type"] for e in events]
        assert "assistant_delta" in types
        assert "tool_start" in types and "tool_result" in types
        assert "permission" in types
        assert "final" in types and "run_end" in types
        assert (s.cwd / "hello.txt").read_text(encoding="utf-8") == "hello agent"

    def test_chat_rejects_concurrent_run(self, server):
        # The write tool will block on a permission that nobody resolves, so the
        # first run stays in flight long enough for the second POST to collide.
        s = server(MockLLMClient([_tool_response(), LLMResponse(content="done")]))
        base = f"http://127.0.0.1:{s.port}"

        _, first = _post(base, "/api/chat", {"prompt": "create hello.txt"})
        assert first["ok"]

        status, second = _post(base, "/api/chat", {"prompt": "again"})
        assert status == 409 and second["ok"] is False

        # resolve the pending permission so the daemon agent thread can finish
        while True:
            msg = s.events.get(timeout=5)
            if msg.get("type") == "permission":
                break
        s.pending[msg["id"]].result = {"decision": "allow", "remember": False}
        s.pending[msg["id"]].event.set()
        # the write happens on the (async) agent thread — poll for it
        target = s.cwd / "hello.txt"
        deadline = time.time() + 10
        while time.time() < deadline and not target.exists():
            time.sleep(0.05)
        assert target.read_text(encoding="utf-8") == "hello agent"
