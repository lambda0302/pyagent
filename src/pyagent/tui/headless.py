"""单次问答（非 TUI）模式下的纯文本渲染器。

直接把助手文本流式写到 stdout，让 ``pyagent "prompt"`` 读起来像普通 CLI。
权限与 diff 确认在 stdin 为终端时仍会提示（这样危险命令可以被拒绝）；当输入
被管道接管 / 非交互时回退为自动放行。
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
