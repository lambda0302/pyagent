"""The GUI renderer: implements the renderer protocol for the desktop app.

Events are pushed onto a thread-safe ``queue.Queue`` that the SSE handler
drains.  ``confirm_permission`` and ``show_diff`` push an event, register a
pending request under a uuid, then **block** on a ``threading.Event`` until the
HTTP layer resolves it (``POST /api/permission`` / ``POST /api/diff``).  A
timeout guards against a disconnected client so a run degrades gracefully
instead of hanging.
"""

from __future__ import annotations

import queue
import threading
import uuid
from typing import Any

from pyagent.tools.registry import ToolResult


class PendingRequest:
    """A blocking confirmation waiting for a decision from the web UI."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None


class GUIRenderer:
    """Renderer that emits SSE events and blocks on user confirmations."""

    #: permissions.py only prompts when this is truthy — the GUI always prompts.
    interactive = True

    def __init__(
        self,
        events: queue.Queue,
        pending: dict[str, PendingRequest],
        timeout: float = 600.0,
    ):
        self.events = events
        self.pending = pending
        self.timeout = timeout
        self._lock = threading.Lock()

    # -- protocol: non-blocking events ----------------------------------
    def on_assistant_delta(self, text: str) -> None:
        self.events.put({"type": "assistant_delta", "text": text})

    def on_tool_start(self, name: str, preview: str) -> None:
        self.events.put({"type": "tool_start", "name": name, "preview": preview})

    def on_tool_result(self, result: ToolResult) -> None:
        self.events.put(
            {"type": "tool_result", "name": result.name, "ok": result.ok, "content": result.content}
        )

    def on_final(self, content: str) -> None:
        self.events.put({"type": "final", "content": content})

    # -- protocol: blocking confirmations -------------------------------
    def _block(self, payload: dict) -> Any:
        req_id = uuid.uuid4().hex
        req = PendingRequest()
        with self._lock:
            self.pending[req_id] = req
        self.events.put({**payload, "id": req_id})
        if not req.event.wait(self.timeout):
            with self._lock:
                self.pending.pop(req_id, None)
            raise TimeoutError(f"GUI did not respond to {payload['type']} within {self.timeout}s")
        with self._lock:
            self.pending.pop(req_id, None)
        return req.result

    def confirm_permission(self, action: str, target: str) -> tuple[str, bool]:
        result = self._block({"type": "permission", "action": action, "target": target})
        return result["decision"], result["remember"]

    def show_diff(self, path: str, diff: str) -> bool:
        result = self._block({"type": "diff", "path": path, "diff": diff})
        return bool(result["apply"])
