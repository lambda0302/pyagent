"""Plain-text renderer for single-shot (non-TUI) runs.

Streams assistant text straight to stdout so ``pyagent "prompt"`` reads like a
normal CLI.  Permission and diff confirmations still prompt when stdin is a
terminal (so dangerous commands can be denied), and fall back to auto-allow
when piped / non-interactive.
"""

from __future__ import annotations

import sys

from pyagent.tools.registry import ToolResult
from pyagent.tui import prompts


class CLIRenderer:
    def __init__(self, interactive: bool = True):
        self.interactive = interactive

    def on_assistant_delta(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def on_final(self, content: str) -> None:
        print()

    def on_tool_start(self, name: str, preview: str) -> None:
        print(f"\n⟳ [{name}] {preview}", flush=True)

    def on_tool_result(self, result: ToolResult) -> None:
        mark = "✓" if result.ok else "✗"
        print(f"  {mark} {result.name}", flush=True)
        if not result.ok:
            print(f"    {result.content}", flush=True)

    def show_diff(self, path: str, diff: str) -> bool:
        if not self.interactive:
            return True
        print(f"\n── diff preview: {path} ──\n{diff}")
        return prompts.ask_confirm("Apply this change?", default=False, interactive=True)

    def confirm_permission(self, action: str, target: str) -> tuple[str, bool]:
        return prompts.ask_permission(action, target, interactive=self.interactive)
