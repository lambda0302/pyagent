"""bash tool: run a shell command on the host and return its output.

v1 runs commands directly on the host (no sandbox — that is a stated non-goal)
and relies on the permission system as the safety net.  The tool is gated by
the ``bash`` permission; a remembered rule is keyed on the command prefix.
"""

from __future__ import annotations

import shlex
import subprocess
from datetime import datetime

from pyagent.tools.permissions import ACTION_BASH, ensure_allowed
from pyagent.tools.registry import ToolContext, ToolError


def bash(args: dict, ctx: ToolContext) -> str:
    command = args.get("command")
    if not command or not str(command).strip():
        raise ToolError("bash: missing required argument 'command'")
    command = str(command)

    prefix = _command_prefix(command)
    remember_hint = f"cmd:{prefix}"
    ensure_allowed(ctx.permissions, ctx.renderer, ctx.config, ACTION_BASH, command, remember_hint)

    timeout = ctx.config.tools.bash_timeout
    started = datetime.now().strftime("%H:%M:%S")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(ctx.cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"bash: command timed out after {timeout}s: {command}") from None
    except OSError as exc:
        raise ToolError(f"bash: failed to run command: {exc}") from exc

    elapsed = datetime.now().strftime("%H:%M:%S")
    parts = [f"[exit code {proc.returncode}] (started {started}, ended {elapsed})"]
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"[stderr]\n{stderr}")
    return "\n".join(parts)


def _command_prefix(command: str) -> str:
    """First whitespace-separated token, quotes stripped, lowercase."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return ""
    return tokens[0].lower()
