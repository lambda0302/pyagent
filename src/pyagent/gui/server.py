"""为桌面 GUI 提供动力的本地 HTTP + SSE 服务。

持有全部跨线程共享状态（事件队列、挂起确认、活跃会话/循环、运行锁），并负责：

- 提供静态前端（``index.html`` / ``app.js`` / ``style.css``），
- 一个长连接 SSE 流（``/api/stream``）：连接时先回放当前对话记录，之后持续
  推送实时事件，
- 若干小 JSON 端点：聊天、权限/diff 决定、会话与恢复。

agent 循环运行在后台线程；``GUIRenderer`` 把事件推入队列，并阻塞在挂起确认
上，由 HTTP 端点解除。
"""

from __future__ import annotations

import json
import queue
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from pyagent import __version__
from pyagent.config import Config
from pyagent.core.context import ContextManager
from pyagent.core.loop import AgentLoop
from pyagent.core.messages import Session, list_sessions, new_session_id
from pyagent.core.model import LLMClient, ModelError, OpenAILLMClient
from pyagent.gui.renderer import GUIRenderer, PendingRequest
from pyagent.tools.permissions import PermissionManager
from pyagent.tools.registry import ToolRegistry, build_default_registry

_STATIC_DIR = Path(__file__).parent / "static"
_HEARTBEAT_SECONDS = 15.0


class GuiServer:
    """GUI 背后的本地 Web 服务与 agent 运行时。"""

    def __init__(
        self,
        config: Config,
        session_dir: str | Path,
        cwd: str | Path,
        llm: LLMClient | None = None,
        port: int = 0,
    ):
        self.config = config
        self.session_dir = Path(session_dir)
        self.cwd = Path(cwd)
        self.registry: ToolRegistry = build_default_registry()

        self.permissions = PermissionManager(rules_file=config.permissions.rules_file)
        self.permissions.load()

        self.events: queue.Queue = queue.Queue()
        self.pending: dict[str, PendingRequest] = {}
        self.renderer = GUIRenderer(self.events, self.pending)

        self.session = Session(session_id=new_session_id())
        self.llm = llm
        self.loop: AgentLoop = self._build_loop()

        self._running = False
        self._run_lock = threading.Lock()
        self._sse_stop = threading.Event()
        self._sse_handlers: list[BaseHTTPRequestHandler] = []

        self._httpd: ThreadingHTTPServer = self._make_httpd(port)
        self.port: int = self._httpd.server_address[1]

    # -- 运行时装配 ---------------------------------------------------
    def _build_loop(self) -> AgentLoop:
        if self.llm is None:
            self.llm = OpenAILLMClient(self.config.model, self.registry.openai_schemas())
        return AgentLoop(
            llm=self.llm,
            registry=self.registry,
            config=self.config,
            session=self.session,
            cwd=self.cwd,
            permissions=self.permissions,
            context=ContextManager(llm=self.llm),
            renderer=self.renderer,
        )

    def _set_session(self, session: Session) -> None:
        self.session = session
        self.loop.session = session

    # -- 服务生命周期 --------------------------------------------------
    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        """停止 SSE 流与 HTTP 服务（须从非 serve 线程调用）。"""
        self._sse_stop.set()
        for handler in list(self._sse_handlers):
            try:
                handler.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            self._httpd.shutdown()
        except Exception:  # noqa: BLE001 - 已在关闭中
            pass
        try:
            self._httpd.server_close()
        except Exception:  # noqa: BLE001
            pass

    def _make_httpd(self, port: int) -> ThreadingHTTPServer:
        server = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "pyagent-gui"

            def log_message(self, *args) -> None:  # noqa: ARG002 - 静默请求日志
                pass

            def do_GET(self) -> None:
                server._handle_get(self)

            def do_POST(self) -> None:
                server._handle_post(self)

        return ThreadingHTTPServer(("127.0.0.1", port), _Handler)

    # -- GET 路由 --------------------------------------------------------
    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        path = urlparse(handler.path).path
        if path in ("/", "/index.html"):
            self._serve_file(handler, "index.html", "text/html; charset=utf-8")
        elif path == "/app.js":
            self._serve_file(handler, "app.js", "application/javascript; charset=utf-8")
        elif path == "/style.css":
            self._serve_file(handler, "style.css", "text/css; charset=utf-8")
        elif path == "/api/health":
            self._send_json(
                handler,
                200,
                {
                    "ok": True,
                    "version": __version__,
                    "model": self.config.model.model,
                    "base_url": self.config.model.base_url,
                    "cwd": str(self.cwd),
                    "session_dir": str(self.session_dir),
                },
            )
        elif path == "/api/sessions":
            self._send_json(handler, 200, {"sessions": list_sessions(self.session_dir)})
        elif path == "/api/stream":
            self._handle_sse(handler)
        else:
            self._send_json(handler, 404, {"ok": False, "error": "not found"})

    def _serve_file(self, handler: BaseHTTPRequestHandler, name: str, content_type: str) -> None:
        try:
            body = (_STATIC_DIR / name).read_bytes()
        except OSError:
            self._send_json(handler, 404, {"ok": False, "error": f"missing asset {name}"})
            return
        self._send_bytes(handler, 200, body, content_type)

    # -- SSE ----------------------------------------------------------------
    def _handle_sse(self, handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        handler.end_headers()
        try:
            handler.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

        self._sse_handlers.append(handler)
        try:
            self._send_sse(
                handler,
                {"type": "snapshot", "session_id": self.session.session_id, "messages": self.session.messages},
            )
            while not self._sse_stop.is_set():
                try:
                    payload = self.events.get(timeout=_HEARTBEAT_SECONDS)
                except queue.Empty:
                    self._write_sse_frame(handler, ": ping\n\n")
                    continue
                self._send_sse(handler, payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # 客户端断连
        finally:
            if handler in self._sse_handlers:
                self._sse_handlers.remove(handler)

    def _send_sse(self, handler: BaseHTTPRequestHandler, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        self._write_sse_frame(handler, f"data: {data}\n\n")

    def _write_sse_frame(self, handler: BaseHTTPRequestHandler, frame: str) -> None:
        handler.wfile.write(frame.encode("utf-8"))
        handler.wfile.flush()

    # -- POST 路由 ---------------------------------------------------------
    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length", 0))
        raw = handler.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except json.JSONDecodeError:
            self._send_json(handler, 400, {"ok": False, "error": "invalid JSON body"})
            return
        if not isinstance(data, dict):
            self._send_json(handler, 400, {"ok": False, "error": "JSON body must be an object"})
            return

        path = urlparse(handler.path).path
        if path == "/api/chat":
            self._handle_chat(handler, data)
        elif path == "/api/permission":
            self._handle_permission(handler, data)
        elif path == "/api/diff":
            self._handle_diff(handler, data)
        elif path == "/api/resume":
            self._handle_resume(handler, data)
        elif path == "/api/new":
            self._handle_new(handler)
        else:
            self._send_json(handler, 404, {"ok": False, "error": "not found"})

    def _handle_chat(self, handler: BaseHTTPRequestHandler, data: dict) -> None:
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            self._send_json(handler, 400, {"ok": False, "error": "empty prompt"})
            return
        with self._run_lock:
            if self._running:
                self._send_json(handler, 409, {"ok": False, "error": "a task is already running"})
                return
            self._running = True
        self._send_json(handler, 200, {"ok": True, "session_id": self.session.session_id})
        threading.Thread(target=self._run_agent, args=(prompt,), daemon=True).start()

    def _run_agent(self, prompt: str) -> None:
        try:
            self.loop.run(prompt=prompt)
        except ModelError as exc:
            print(f"[pyagent] model error: {exc}", file=sys.stderr)
            self.events.put({"type": "error", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - 兜底暴露任何意外失败
            print(f"[pyagent] error: {exc!r}", file=sys.stderr)
            self.events.put({"type": "error", "message": repr(exc)})
        finally:
            try:
                self.session.save(self.session_dir)
            except Exception:  # noqa: BLE001 - 会话保存是尽力而为
                pass
            self.events.put(
                {"type": "run_end", "session_id": self.session.session_id, "saved": True}
            )
            with self._run_lock:
                self._running = False

    def _handle_permission(self, handler: BaseHTTPRequestHandler, data: dict) -> None:
        req = self.pending.get(data.get("id"))
        decision = data.get("decision")
        if req is None or decision not in ("allow", "deny"):
            self._send_json(handler, 404, {"ok": False, "error": "unknown or invalid request"})
            return
        req.result = {"decision": decision, "remember": bool(data.get("remember", False))}
        req.event.set()
        self._send_json(handler, 200, {"ok": True})

    def _handle_diff(self, handler: BaseHTTPRequestHandler, data: dict) -> None:
        req = self.pending.get(data.get("id"))
        if req is None:
            self._send_json(handler, 404, {"ok": False, "error": "unknown request"})
            return
        req.result = {"apply": bool(data.get("apply", False))}
        req.event.set()
        self._send_json(handler, 200, {"ok": True})

    def _handle_resume(self, handler: BaseHTTPRequestHandler, data: dict) -> None:
        if self._running:
            self._send_json(handler, 409, {"ok": False, "error": "a task is already running"})
            return
        sid = data.get("session_id")
        if not sid:
            self._send_json(handler, 400, {"ok": False, "error": "missing session_id"})
            return
        try:
            session = Session.load(self.session_dir, str(sid))
        except FileNotFoundError:
            self._send_json(handler, 404, {"ok": False, "error": f"no session {sid!r}"})
            return
        self._set_session(session)
        self._send_json(
            handler, 200, {"ok": True, "session_id": session.session_id, "messages": session.messages}
        )

    def _handle_new(self, handler: BaseHTTPRequestHandler) -> None:
        if self._running:
            self._send_json(handler, 409, {"ok": False, "error": "a task is already running"})
            return
        self._set_session(Session(session_id=new_session_id()))
        self._send_json(handler, 200, {"ok": True, "session_id": self.session.session_id})

    # -- 响应辅助 ------------------------------------------------------------
    def _send_bytes(self, handler: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)
        handler.wfile.flush()

    def _send_json(self, handler: BaseHTTPRequestHandler, status: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(handler, status, body, "application/json; charset=utf-8")
