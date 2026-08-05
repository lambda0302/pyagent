"""Shared fixtures: mock LLM client, tool registry, tool context."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyagent.config import Config
from pyagent.core.model import LLMClient, LLMResponse
from pyagent.tools.permissions import PermissionManager
from pyagent.tools.registry import ToolContext, ToolRegistry, build_default_registry


class MockLLMClient(LLMClient):
    """Scripted model: returns responses from a queue, recording every call."""

    def __init__(self, script: list[LLMResponse]):
        self.script = list(script)
        self.calls: list[tuple[list[dict], list[dict] | None]] = []

    @property
    def calls_count(self) -> int:
        return len(self.calls)

    def complete(self, messages, tools=None, stream=False, on_delta=None):
        self.calls.append((messages, tools))
        response = self.script.pop(0)
        if stream and on_delta and response.content:
            for token in response.content.split(" "):
                on_delta(token + " ")
        return response


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def registry() -> ToolRegistry:
    return build_default_registry()


@pytest.fixture
def permissions(tmp_path: Path) -> PermissionManager:
    return PermissionManager(rules_file=str(tmp_path / "rules.json"))


@pytest.fixture
def tool_ctx(config: Config, permissions: PermissionManager, tmp_path: Path) -> ToolContext:
    return ToolContext(cwd=tmp_path, config=config, permissions=permissions, renderer=None)
