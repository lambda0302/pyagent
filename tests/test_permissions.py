"""F4: permission system — rules, prompting, deny, remember-rule persistence."""

from __future__ import annotations

import json

import pytest

from pyagent.config import Config
from pyagent.tools.permissions import (
    ACTION_BASH,
    ACTION_WRITE,
    PermissionDeniedError,
    PermissionManager,
    Rule,
    ensure_allowed,
)
from pyagent.tools.registry import ToolContext


class TestRules:
    def test_no_rule_returns_none(self, permissions):
        assert permissions.decide(ACTION_WRITE, "C:/x/y.txt") is None

    def test_write_glob_rule_matches(self, permissions):
        permissions.rules.append(Rule(ACTION_WRITE, "**/*.md", "allow"))
        assert permissions.decide(ACTION_WRITE, "C:/a/b/readme.md") == "allow"
        assert permissions.decide(ACTION_WRITE, "C:/a/b/main.py") is None

    def test_command_prefix_rule_matches(self, permissions):
        permissions.rules.append(Rule(ACTION_BASH, "cmd:python", "deny"))
        assert permissions.decide(ACTION_BASH, "python main.py") == "deny"
        assert permissions.decide(ACTION_BASH, "git status") is None

    def test_add_rule_persists_to_file(self, tmp_path):
        rules_file = str(tmp_path / "rules.json")
        mgr = PermissionManager(rules_file=rules_file)
        mgr.add_rule(ACTION_WRITE, "C:/x/*.txt", "deny")
        assert (tmp_path / "rules.json").exists()
        # a fresh manager loads the remembered rule
        reloaded = PermissionManager(rules_file=rules_file)
        reloaded.load()
        assert reloaded.decide(ACTION_WRITE, "C:/x/secret.txt") == "deny"


class TestEnsureAllowed:
    def test_default_allow_when_noninteractive_prompt(self, permissions, config):
        # no renderer + default "prompt" resolves to allow in headless runs
        assert ensure_allowed(permissions, None, config, ACTION_WRITE, "C:/x/y.txt") == "allow"

    def test_default_deny_raises(self, permissions):
        config = Config()
        config.permissions.default_write = "deny"
        with pytest.raises(PermissionDeniedError):
            ensure_allowed(permissions, None, config, ACTION_WRITE, "C:/x/y.txt")

    def test_noninteractive_renderer_falls_back_to_config_default(self, permissions):
        """A renderer that is not interactive must not auto-allow; the config
        default (deny) must apply instead."""
        config = Config()
        config.permissions.default_bash = "deny"

        class NonInteractiveRenderer:
            interactive = False

            def confirm_permission(self, action, target):  # pragma: no cover
                raise AssertionError("should not prompt when non-interactive")

        with pytest.raises(PermissionDeniedError):
            ensure_allowed(permissions, NonInteractiveRenderer(), config, ACTION_BASH, "echo x")

    def test_stored_rule_wins(self, permissions):
        permissions.add_rule(ACTION_WRITE, "C:/x/*.txt", "deny")
        with pytest.raises(PermissionDeniedError):
            ensure_allowed(permissions, None, Config(), ACTION_WRITE, "C:/x/secret.txt")

    def test_deny_via_renderer_raises_and_can_remember(self, permissions, config):
        class Renderer:
            def __init__(self):
                self.asked = []

            def confirm_permission(self, action, target):
                self.asked.append((action, target))
                return "deny", True

        renderer = Renderer()
        with pytest.raises(PermissionDeniedError):
            ensure_allowed(permissions, renderer, config, ACTION_WRITE, "C:/x/y.txt")
        # the deny rule was remembered
        assert permissions.decide(ACTION_WRITE, "C:/x/y.txt") == "deny"

    def test_allow_via_renderer(self, permissions, config):
        class Renderer:
            def confirm_permission(self, action, target):
                return "allow", False

        assert ensure_allowed(permissions, Renderer(), config, ACTION_WRITE, "C:/x/y.txt") == "allow"


class TestDeniedOperationDoesNotExecute:
    def test_write_is_blocked_when_denied(self, tmp_path, registry, config):
        """deny 后操作不执行并给出明确反馈（写文件）。"""
        target = tmp_path / "forbidden.txt"
        permissions = PermissionManager(rules_file="")
        permissions.add_rule(ACTION_WRITE, str(target), "deny")
        ctx = ToolContext(cwd=tmp_path, config=config, permissions=permissions, renderer=None)
        result = registry.execute(
            "write_file", json.dumps({"path": str(target), "content": "x"}), ctx
        )
        assert not result.ok
        assert "denied" in result.content
        assert not target.exists()
