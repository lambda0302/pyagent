"""The interactive TUI: prompt loop, slash commands, session lifecycle."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.rule import Rule

from pyagent.config import Config
from pyagent.core.loop import AgentLoop
from pyagent.core.messages import Session, list_sessions, new_session_id
from pyagent.tui.renderer import TUIRenderer

_BANNER = """[bold cyan]pyagent[/bold cyan] — terminal coding agent
Type a task in natural language, or use a slash command:
  /help            show this help
  /save            save the current session
  /sessions        list saved sessions
  /resume <id>     load a saved session by id
  /clear           start a fresh conversation (history kept on disk)
  /quit            exit and save"""


class PyAgentApp:
    def __init__(
        self,
        config: Config,
        session: Session,
        loop: AgentLoop,
        session_dir: Path,
        console: Console | None = None,
    ):
        self.config = config
        self.session = session
        self.loop = loop
        self.session_dir = Path(session_dir)
        self.renderer = loop.renderer or TUIRenderer()
        self.console = console or Console()
        self._prompt = None  # lazily created prompt_toolkit session, or None

    def run(self) -> None:
        self.console.print(_BANNER)
        try:
            while True:
                try:
                    text = self._get_input()
                except KeyboardInterrupt:
                    self.console.print("\n(interrupted — press Ctrl+C again or type /quit to exit)")
                    continue
                except EOFError:
                    break

                text = text.strip()
                if not text:
                    continue
                if not self._dispatch(text):
                    break
        finally:
            self._save_session()
            self.console.print(
                f"\n[saved session {self.session.session_id} — resume with /resume {self.session.session_id}]"
            )

    def _get_input(self) -> str:
        """Read one line of user input.

        Uses prompt_toolkit when a Windows console is available; falls back to
        plain ``input()`` otherwise (pipes, non-console terminals, tests) so the
        TUI never crashes just because there is no interactive console.
        """
        if self._prompt is None:
            self._prompt = _try_create_prompt_session()
        if self._prompt is not None:
            try:
                return self._prompt.prompt("pyagent> ")
            except Exception:  # noqa: BLE001 - fall back on any prompt_toolkit failure
                self._prompt = None
        return input("pyagent> ")

    # -- command dispatch --------------------------------------------------
    def _dispatch(self, text: str) -> bool:
        if text.startswith("/"):
            return self._slash(text)
        self._run_task(text)
        return True

    def _slash(self, text: str) -> bool:
        cmd, _, arg = text.partition(" ")
        arg = arg.strip()
        if cmd in ("/quit", "/exit", "/q"):
            return False
        if cmd in ("/help", "/h"):
            self.console.print(_BANNER)
        elif cmd == "/save":
            self._save_session()
            self.console.print(f"✓ session saved: {self.session.session_id}")
        elif cmd == "/sessions":
            self._list_sessions()
        elif cmd == "/resume":
            self._resume(arg)
        elif cmd == "/clear":
            self._clear()
        else:
            self.console.print(f"unknown command: {cmd} (try /help)")
        return True

    def _run_task(self, prompt: str) -> None:
        self.console.print(Rule("task"))
        try:
            self.loop.run(prompt=prompt)
        except KeyboardInterrupt:
            self.console.print("\n(task interrupted)")
        except Exception as exc:  # noqa: BLE001 - surface, never crash the TUI
            self.console.print(f"[red]error:[/red] {exc}")
        self._save_session()

    def _save_session(self) -> None:
        try:
            self.session.save(self.session_dir)
        except Exception as exc:  # noqa: BLE001 - never let a save failure kill the TUI
            self.console.print(f"[red]failed to save session:[/red] {exc}")

    def _list_sessions(self) -> None:
        entries = list_sessions(self.session_dir)
        if not entries:
            self.console.print("no saved sessions yet.")
            return
        self.console.print("saved sessions:")
        for e in entries:
            self.console.print(
                f"  {e['session_id']}  {e['title'][:40]:<40} {e['message_count']} msgs"
            )

    def _resume(self, arg: str) -> None:
        if not arg:
            self.console.print("usage: /resume <session-id>")
            return
        try:
            self.session = Session.load(self.session_dir, arg)
            self.loop.session = self.session
            self.console.print(f"✓ resumed session {arg} ({len(self.session.messages)} messages)")
        except FileNotFoundError:
            self.console.print(f"[red]no saved session with id {arg!r} (see /sessions)[/red]")

    def _clear(self) -> None:
        keep = [m for m in self.session.messages if m.get("role") == "system"]
        self.session = Session(
            session_id=new_session_id(),
            messages=keep,
            title=self.session.title or "untitled",
        )
        self.loop.session = self.session
        self.console.print("✓ new conversation started")


def _try_create_prompt_session():
    """Create a prompt_toolkit PromptSession, or None when unavailable."""
    try:
        from prompt_toolkit import PromptSession

        return PromptSession()
    except Exception:  # noqa: BLE001 - no console output available
        return None


def make_app(config: Config, session_dir: Path) -> PyAgentApp:
    """Build the default TUI app wiring (used by the CLI)."""
    from pyagent.core.context import ContextManager
    from pyagent.core.messages import Session
    from pyagent.core.model import OpenAILLMClient
    from pyagent.tools.permissions import PermissionManager
    from pyagent.tools.registry import build_default_registry

    registry = build_default_registry()
    permissions = PermissionManager(rules_file=config.permissions.rules_file)
    permissions.load()
    llm = OpenAILLMClient(config.model, registry.openai_schemas())
    session = Session(session_id=new_session_id())
    renderer = TUIRenderer()
    loop = AgentLoop(
        llm=llm,
        registry=registry,
        config=config,
        session=session,
        cwd=Path.cwd(),
        permissions=permissions,
        context=ContextManager(llm=llm),
        renderer=renderer,
    )
    return PyAgentApp(config=config, session=session, loop=loop, session_dir=session_dir, console=Console())
