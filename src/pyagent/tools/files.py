"""文件工具：read_file / write_file / edit_file / glob / grep。

写操作（write_file、edit_file）都要经过权限系统。``edit_file`` 遵循「生成补丁 →
预览 diff → 确认 → 应用」：存在渲染器时先展示 diff 供批准再写盘；无头运行则
直接应用。
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from pyagent.tools.permissions import ACTION_WRITE, ensure_allowed
from pyagent.tools.registry import ToolContext, ToolError

#: read_file 返回 / grep 命中展示的最大字符数上限。
MAX_READ_CHARS = 60_000
MAX_GREP_HITS = 200
MAX_GREP_LINE_CHARS = 500

_EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".hg", ".svn"}


def read_file(args: dict, ctx: ToolContext) -> str:
    path = args.get("path")
    if not path:
        raise ToolError("read_file: missing required argument 'path'")
    full = ctx.resolve(str(path))
    if not full.exists():
        raise ToolError(f"read_file: file not found: {path}")
    if full.is_dir():
        raise ToolError(f"read_file: {path} is a directory, not a file")
    try:
        content = full.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = _read_binary_as_text(full)
    except OSError as exc:
        raise ToolError(f"read_file: cannot read {path}: {exc}") from exc
    if len(content) > MAX_READ_CHARS:
        content = content[:MAX_READ_CHARS]
        content += f"\n\n[... truncated at {MAX_READ_CHARS} chars ...]"
    return content


def write_file(args: dict, ctx: ToolContext) -> str:
    path = args.get("path")
    content = args.get("content")
    if not path:
        raise ToolError("write_file: missing required argument 'path'")
    if content is None:
        raise ToolError("write_file: missing required argument 'content'")
    full = ctx.resolve(str(path))
    ensure_allowed(
        ctx.permissions, ctx.renderer, ctx.config, ACTION_WRITE, str(full),
        remember_hint=str(full),
    )
    # 约定（README 有说明）：自动创建父目录。
    full.parent.mkdir(parents=True, exist_ok=True)
    try:
        full.write_text(str(content), encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"write_file: cannot write {path}: {exc}") from exc
    return f"Wrote {len(str(content))} chars to {path}"


def edit_file(args: dict, ctx: ToolContext) -> str:
    path = args.get("path")
    old = args.get("old_string")
    new = args.get("new_string")
    if not path:
        raise ToolError("edit_file: missing required argument 'path'")
    if old is None or new is None:
        raise ToolError("edit_file: 'old_string' and 'new_string' are required")
    full = ctx.resolve(str(path))
    if not full.exists():
        raise ToolError(f"edit_file: file not found: {path}")
    original = full.read_text(encoding="utf-8")
    if old not in original:
        raise ToolError(_mismatch_error(path, old, original))

    patched = original.replace(old, new, 1)
    diff = _make_diff(path, original, patched)

    if ctx.renderer is not None:
        proceed = ctx.renderer.show_diff(str(full), diff)
        if not proceed:
            return f"Edit cancelled by user; no changes written to {path}"

    ensure_allowed(
        ctx.permissions, ctx.renderer, ctx.config, ACTION_WRITE, str(full),
        remember_hint=str(full),
    )
    try:
        full.write_text(patched, encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"edit_file: cannot write {path}: {exc}") from exc
    return f"Edited {path} (1 replacement applied):\n{diff}"


def glob(args: dict, ctx: ToolContext) -> str:
    pattern = args.get("pattern")
    if not pattern:
        raise ToolError("glob: missing required argument 'pattern'")
    pattern = str(pattern).replace("\\", "/")
    base = ctx.cwd
    search_root: Path = base
    rel_pattern = pattern

    try:
        if rel_pattern.startswith("/") or ":" in rel_pattern:
            # 视为近似绝对路径：去掉前导斜杠后退回相对 cwd
            rel_pattern = rel_pattern.lstrip("/")
        matches = sorted(search_root.glob(rel_pattern))
    except (ValueError, OSError) as exc:
        raise ToolError(f"glob: bad pattern {pattern!r}: {exc}") from exc

    results = [_win(str(p.relative_to(base)) if p.is_relative_to(base) else str(p)) for p in matches]
    if not results:
        return f"glob: no matches for {pattern!r}"
    return "\n".join(results)


def grep(args: dict, ctx: ToolContext) -> str:
    pattern = args.get("pattern")
    path = args.get("path", ".")
    if not pattern:
        raise ToolError("grep: missing required argument 'pattern'")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"grep: invalid regex {pattern!r}: {exc}") from exc

    root = ctx.resolve(str(path))
    if not root.exists():
        raise ToolError(f"grep: path not found: {path}")

    hits: list[str] = []
    for file_path in _walk_files(root):
        if len(hits) >= MAX_GREP_HITS:
            break
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                line = line[:MAX_GREP_LINE_CHARS]
                rel = _win(str(file_path.relative_to(ctx.cwd)) if file_path.is_relative_to(ctx.cwd) else str(file_path))
                hits.append(f"{rel}:{lineno}: {line}")
                if len(hits) >= MAX_GREP_HITS:
                    break
    if not hits:
        return f"grep: no matches for {pattern!r} under {path}"
    return "\n".join(hits)


# -- 辅助 --------------------------------------------------------------

def _mismatch_error(path: str, old: str, content: str) -> str:
    """edit_file 的 old_string 未找到时给出的诊断信息。"""
    lines = content.splitlines()
    clue = ""
    sample = old.strip()
    if sample:
        close = difflib.get_close_matches(sample, [ln.strip() for ln in lines], n=1, cutoff=0.3)
        if close:
            lineno = next((i + 1 for i, ln in enumerate(lines) if close[0] in ln), None)
            clue = f" Closest matching line is #{lineno}: {close[0]!r}."
    return (
        f"edit_file: old_string not found in {path} (no changes made).{clue} "
        "Make sure the text matches exactly (whitespace matters); use read_file to check."
    )


def _make_diff(path: str, original: str, patched: str) -> str:
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        patched.splitlines(keepends=True),
        fromfile=path,
        tofile=path,
    )
    return "".join(diff).rstrip("\n")


def _read_binary_as_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        text = repr(data[:200])
    return f"[binary file, {len(data)} bytes, decoded as text]\n{text}"


def _walk_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and not any(part in _EXCLUDE_DIRS for part in path.parts):
            yield path


def _win(p: str) -> str:
    return p.replace("\\", "/")
