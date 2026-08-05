"""桌面应用的 GUI 渲染器：实现桌面应用的渲染器协议。

事件被推入线程安全的 ``queue.Queue``，由 SSE 处理器排空。
``confirm_permission`` 与 ``show_diff`` 先推一个事件、在 uuid 下注册一个
挂起请求，然后**阻塞**在 ``threading.Event`` 上，直到 HTTP 层解析它
（``POST /api/permission`` / ``POST /api/diff``）。超时兜底防止客户端断连
时让运行挂死——而是优雅降级。
"""

from __future__ import annotations

import queue
import threading
import uuid
from typing import Any

from pyagent.tools.registry import ToolResult


class PendingRequest:
    """等待 Web UI 决定的一个阻塞式确认。"""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None


class GUIRenderer:
    """会发出 SSE 事件并在用户确认上阻塞的渲染器。"""

    #: permissions.py 仅在该值为真时提示——GUI 总是提示。
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

    # -- 协议：非阻塞事件 --------------------------------------------
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

    # -- 协议：阻塞式确认 --------------------------------------------
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
