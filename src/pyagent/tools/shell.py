"""bash 工具：在宿主机上运行 Shell 命令并返回输出。

v1 直接在本机执行命令（不做沙箱——这是明确列出的非目标），用权限系统作为
安全兜底。工具受 ``bash`` 权限管控；记忆的规则以命令前缀为键。
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
    """取第一个空白分隔的 token，去掉引号，转小写。"""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return ""
    return tokens[0].lower()
