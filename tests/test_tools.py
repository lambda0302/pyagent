"""C1–C5: the six core tools each pass unit tests and behave on a real dir."""

from __future__ import annotations

import json


def _run(registry, name, args, ctx):
    return registry.execute(name, json.dumps(args), ctx)


class TestReadFile:
    def test_reads_existing_file(self, tool_ctx, registry):
        (tool_ctx.cwd / "a.txt").write_text("line1\nline2\n", encoding="utf-8")
        result = _run(registry, "read_file", {"path": "a.txt"}, tool_ctx)
        assert result.ok
        assert "line1" in result.content

    def test_missing_file_returns_error_not_crash(self, tool_ctx, registry):
        result = _run(registry, "read_file", {"path": "missing.txt"}, tool_ctx)
        assert not result.ok
        assert "not found" in result.content


class TestWriteFile:
    def test_creates_file_with_parent_dirs(self, tool_ctx, registry):
        result = _run(registry, "write_file", {"path": "sub/dir/b.txt", "content": "data"}, tool_ctx)
        assert result.ok
        assert (tool_ctx.cwd / "sub" / "dir" / "b.txt").read_text(encoding="utf-8") == "data"

    def test_overwrites_existing(self, tool_ctx, registry):
        (tool_ctx.cwd / "c.txt").write_text("old", encoding="utf-8")
        result = _run(registry, "write_file", {"path": "c.txt", "content": "new"}, tool_ctx)
        assert result.ok
        assert (tool_ctx.cwd / "c.txt").read_text(encoding="utf-8") == "new"


class TestEditFile:
    def _sample(self, tool_ctx):
        (tool_ctx.cwd / "d.py").write_text("def greet():\n    return 1\n", encoding="utf-8")

    def test_applies_patch(self, tool_ctx, registry):
        self._sample(tool_ctx)
        result = _run(
            registry,
            "edit_file",
            {"path": "d.py", "old_string": "return 1", "new_string": "return 2"},
            tool_ctx,
        )
        assert result.ok
        content = (tool_ctx.cwd / "d.py").read_text(encoding="utf-8")
        assert "return 2" in content and "return 1" not in content

    def test_mismatch_is_diagnostic_not_silent(self, tool_ctx, registry):
        self._sample(tool_ctx)
        result = _run(
            registry,
            "edit_file",
            {"path": "d.py", "old_string": "does not exist", "new_string": "x"},
            tool_ctx,
        )
        assert not result.ok
        assert "not found" in result.content
        # file unchanged
        assert "return 1" in (tool_ctx.cwd / "d.py").read_text(encoding="utf-8")


class TestGlobGrep:
    def test_glob_matches(self, tool_ctx, registry):
        (tool_ctx.cwd / "src").mkdir()
        (tool_ctx.cwd / "src" / "a.py").write_text("", encoding="utf-8")
        (tool_ctx.cwd / "src" / "b.py").write_text("", encoding="utf-8")
        (tool_ctx.cwd / "src" / "c.txt").write_text("", encoding="utf-8")
        result = _run(registry, "glob", {"pattern": "src/*.py"}, tool_ctx)
        assert result.ok
        lines = result.content.splitlines()
        assert len(lines) == 2
        assert all("/" in ln and ln.endswith(".py") for ln in lines)  # windows-safe path

    def test_grep_finds_matches(self, tool_ctx, registry):
        (tool_ctx.cwd / "code.py").write_text("import os\ndef foo():\n    return os.name\n", encoding="utf-8")
        result = _run(registry, "grep", {"pattern": "def foo", "path": "."}, tool_ctx)
        assert result.ok
        assert "code.py:2" in result.content

    def test_grep_no_match(self, tool_ctx, registry):
        (tool_ctx.cwd / "code.py").write_text("nothing here\n", encoding="utf-8")
        result = _run(registry, "grep", {"pattern": "zzz", "path": "."}, tool_ctx)
        assert result.ok
        assert "no matches" in result.content


class TestBash:
    def test_echo_output_returned(self, tool_ctx, registry):
        result = _run(registry, "bash", {"command": "echo ok"}, tool_ctx)
        assert result.ok
        assert "ok" in result.content
        assert "exit code 0" in result.content

    def test_failure_reports_exit_code(self, tool_ctx, registry):
        result = _run(registry, "bash", {"command": "exit 3"}, tool_ctx)
        assert result.ok  # tool itself succeeded in running
        assert "exit code 3" in result.content


class TestRegistry:
    def test_six_tools_registered(self, registry):
        assert set(registry.names()) == {
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "bash",
        }
        assert len(registry.openai_schemas()) == 6

    def test_unknown_tool_returns_error(self, registry, tool_ctx):
        result = registry.execute("nope", "{}", tool_ctx)
        assert not result.ok
        assert "unknown tool" in result.content

    def test_invalid_arguments_return_error(self, registry, tool_ctx):
        result = registry.execute("read_file", "{not json", tool_ctx)
        assert not result.ok
        assert "invalid JSON" in result.content
