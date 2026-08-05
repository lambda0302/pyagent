"""Command-line entry: argument parsing, single-shot mode, TUI mode.

``pyagent``            → interactive TUI
``pyagent "prompt"``   → single-shot answer (streamed to stdout)
``pyagent --version``  → print version
``pyagent --resume ID``→ continue a saved session (TUI)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyagent import __version__
from pyagent.config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"pyagent {__version__}")
        return 0

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    session_dir = Path(config.session.dir)
    resume_id = args.resume
    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()

    if args.prompt:
        return _run_single(config, session_dir, args.prompt, resume_id, cwd)
    return _run_tui(config, session_dir, resume_id, cwd)


def _force_utf8_stdio() -> None:
    """Use UTF-8 with lossy replacement for stdin/stdout/stderr so Unicode
    (✓, Chinese, ...) never crashes on a GBK/CP936 Windows console and piped
    UTF-8 input never produces lone surrogates (which would corrupt the LLM
    request body)."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # not a real text stream / already configured


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyagent",
        description="A Codex-style terminal coding agent (CLI + TUI).",
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--config", metavar="PATH", help="path to a TOML config file")
    parser.add_argument("--resume", metavar="SESSION_ID", help="resume a saved session by id")
    parser.add_argument("--cwd", metavar="PATH", help="working directory for tools (default: current)")
    parser.add_argument(
        "prompt",
        nargs="?",
        help="single-shot prompt; when omitted the interactive TUI starts",
    )
    return parser


def _run_single(config, session_dir: Path, prompt: str, resume_id: str | None, cwd: Path) -> int:
    from pyagent.core.context import ContextManager
    from pyagent.core.loop import AgentLoop
    from pyagent.core.messages import Session, new_session_id
    from pyagent.core.model import ModelError, OpenAILLMClient
    from pyagent.tools.permissions import PermissionManager
    from pyagent.tools.registry import build_default_registry
    from pyagent.tui.headless import CLIRenderer

    registry = build_default_registry()
    permissions = PermissionManager(rules_file=config.permissions.rules_file)
    permissions.load()

    try:
        llm = OpenAILLMClient(config.model, registry.openai_schemas())
    except ModelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if resume_id:
        try:
            session = Session.load(session_dir, resume_id)
        except FileNotFoundError:
            print(f"error: no saved session with id {resume_id!r}", file=sys.stderr)
            return 2
    else:
        session = Session(session_id=new_session_id())

    interactive = sys.stdin.isatty()
    renderer = CLIRenderer(interactive=interactive)
    loop = AgentLoop(
        llm=llm,
        registry=registry,
        config=config,
        session=session,
        cwd=cwd,
        permissions=permissions,
        context=ContextManager(llm=llm),
        renderer=renderer,
    )

    try:
        loop.run(prompt=prompt)
    except ModelError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n(interrupted)", file=sys.stderr)

    try:
        session.save(session_dir)
    except Exception as exc:  # noqa: BLE001 - serialisation issues are non-fatal
        print(f"warning: could not save session: {exc}", file=sys.stderr)
    else:
        print(f"\n── session saved: {session.session_id} (resume: pyagent --resume {session.session_id})")
    return 0


def _run_tui(config, session_dir: Path, resume_id: str | None, cwd: Path) -> int:
    from pyagent.core.messages import Session, new_session_id
    from pyagent.tui.app import make_app

    if resume_id:
        try:
            session = Session.load(session_dir, resume_id)
        except FileNotFoundError:
            print(f"error: no saved session with id {resume_id!r} (see pyagent --help)", file=sys.stderr)
            return 2
    else:
        session = Session(session_id=new_session_id())

    try:
        app = make_app(config, session_dir)
    except Exception as exc:  # noqa: BLE001 - fail with a clear message
        print(f"error: {exc}", file=sys.stderr)
        return 1

    app.session = session
    app.loop.session = session
    app.loop.cwd = cwd
    app.run()
    return 0
