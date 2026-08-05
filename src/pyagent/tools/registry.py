"""Tool registry: name → (schema, callable) with execution and error mapping.

The registry is the seam v2 uses to add MCP tools: any callable plus a JSON
schema can be registered and will flow to the model automatically.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyagent.config import Config
from pyagent.tools.permissions import PermissionDeniedError, PermissionManager

#: Signature: (arguments: dict, ctx: ToolContext) -> str
ToolHandler = Callable[[dict[str, Any], "ToolContext"], str]


class ToolError(Exception):
    """Recoverable tool failure — the message goes back to the model."""


@dataclass
class ToolContext:
    """Everything a tool needs at execution time."""

    cwd: Path
    config: Config
    permissions: PermissionManager
    renderer: Any = None  # optional TUI renderer (confirm_permission / show_diff)

    def resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        return p


@dataclass
class ToolResult:
    name: str
    ok: bool
    content: str


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: ToolHandler

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec] | None = None):
        self._tools: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool name: {spec.name}")
        self._tools[spec.name] = spec

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict,
    ) -> Callable[[ToolHandler], ToolHandler]:
        def decorator(fn: ToolHandler) -> ToolHandler:
            self.register(ToolSpec(name=name, description=description, parameters=parameters, handler=fn))
            return fn

        return decorator

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def openai_schemas(self) -> list[dict]:
        return [spec.to_openai_schema() for spec in self._tools.values()]

    def execute(self, name: str, arguments_json: str, ctx: ToolContext) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(name=name, ok=False, content=f"Error: unknown tool {name!r}")
        try:
            args = json.loads(arguments_json) if arguments_json.strip() else {}
            if not isinstance(args, dict):
                raise ToolError(f"tool arguments must be a JSON object, got {type(args).__name__}")
        except json.JSONDecodeError as exc:
            return ToolResult(
                name=name,
                ok=False,
                content=f"Error: invalid JSON arguments for {name}: {exc}",
            )
        try:
            content = spec.handler(args, ctx)
            return ToolResult(name=name, ok=True, content=content)
        except PermissionDeniedError as exc:
            return ToolResult(name=name, ok=False, content=f"Error: {exc}")
        except ToolError as exc:
            return ToolResult(name=name, ok=False, content=f"Error: {exc}")
        except Exception as exc:  # noqa: BLE001 - boundary maps any failure to a message
            return ToolResult(name=name, ok=False, content=f"Error: {name} failed: {exc!r}")


# -- default toolset -------------------------------------------------------

def build_default_registry() -> ToolRegistry:
    """Build the registry with the six core v1 tools."""
    from pyagent.tools import files, shell

    registry = ToolRegistry()
    registry.register_tool(
        "read_file",
        "Read a text file and return its contents. Use this to inspect a file "
        "before editing it. Paths are relative to the working directory.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"},
            },
            "required": ["path"],
        },
    )(files.read_file)

    registry.register_tool(
        "write_file",
        "Create or overwrite a file with the given content. Parent directories "
        "are created automatically. This is a destructive write: it will be "
        "confirmed with the user before applying.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path of the file to write"},
                "content": {"type": "string", "description": "Full new file content"},
            },
            "required": ["path", "content"],
        },
    )(files.write_file)

    registry.register_tool(
        "edit_file",
        "Apply a surgical patch to an existing file by replacing the first "
        "occurrence of old_string with new_string. The diff is previewed and "
        "confirmed before applying. Fails with a diagnostic if old_string is "
        "not found (no silent no-op).",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path of the file to edit"},
                "old_string": {"type": "string", "description": "Exact text to replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    )(files.edit_file)

    registry.register_tool(
        "glob",
        "Find files matching a glob pattern (e.g. 'src/**/*.py'). Returns "
        "matching paths, one per line.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern, relative to the working directory"},
            },
            "required": ["pattern"],
        },
    )(files.glob)

    registry.register_tool(
        "grep",
        "Search file contents with a regular expression. Returns matches as "
        "'path:line: text'.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression to search for"},
                "path": {"type": "string", "description": "Directory to search (default '.')"},
            },
            "required": ["pattern"],
        },
    )(files.grep)

    registry.register_tool(
        "bash",
        "Run a shell command on the host and return its stdout/stderr and exit "
        "code. Commands run in the working directory. Requires user permission.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run"},
            },
            "required": ["command"],
        },
    )(shell.bash)

    return registry
