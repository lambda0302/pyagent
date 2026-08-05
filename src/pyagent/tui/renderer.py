"""Rich-based interactive renderer for TUI mode.

Implements the renderer protocol consumed by :class:`AgentLoop` and the tool
layer: streaming deltas, tool status panels, diff previews, permission dialogs.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from pyagent.tools.registry import ToolResult
from pyagent.tui import prompts


class TUIRenderer:
    def __init__(self, interactive: bool = True, console: Console | None = None):
        self.console = console or Console()
        self.interactive = interactive

    # -- assistant streaming ---------------------------------------------
    def on_assistant_delta(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def on_final(self, content: str) -> None:
        self.console.print()
        self.console.print(Panel(Text(content, style="green"), title="[b]pyagent[/b]", border_style="green"))

    # -- tool status -------------------------------------------------------
    def on_tool_start(self, name: str, preview: str) -> None:
        self.console.print(
            Panel(
                Text(f"{name}  {preview}", style="cyan"),
                title="[b]⟳ tool[/b]",
                border_style="cyan",
            )
        )

    def on_tool_result(self, result: ToolResult) -> None:
        if result.ok:
            label = Text(f"✓ {result.name} succeeded", style="green")
        else:
            label = Text(f"✗ {result.name} failed: {result.content}", style="red")
        self.console.print(label)

    # -- diff preview ------------------------------------------------------
    def show_diff(self, path: str, diff: str) -> bool:
        if not self.interactive:
            return True
        self.console.print(Rule(f"diff: {path}"))
        self.console.print(Syntax(diff, "diff", theme="ansi_dark"))
        return prompts.ask_confirm("Apply this change?", default=False, interactive=True)

    # -- permission --------------------------------------------------------
    def confirm_permission(self, action: str, target: str) -> tuple[str, bool]:
        if not self.interactive:
            return "allow", False
        self.console.print(
            Panel(
                Text(f"{action} on: {target}", style="yellow"),
                title="[b]permission required[/b]",
                border_style="yellow",
            )
        )
        return prompts.ask_permission(action, target, interactive=True)
