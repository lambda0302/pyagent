"""Allow/deny rules for dangerous operations (writes, shell commands).

Rules are remembered per target: for writes the target is a path (glob), for
bash it is a command prefix.  Rules persist to a JSON file so "remember this
rule" survives restarts.  When no rule matches, the caller may prompt the user
(TUI) or fall back to the config default (headless).
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: action names
ACTION_WRITE = "write"
ACTION_BASH = "bash"


class PermissionDeniedError(Exception):
    """Raised when a user/rule denies an operation."""


@dataclass
class Rule:
    action: str
    pattern: str
    decision: str  # "allow" | "deny"


@dataclass
class PermissionManager:
    rules_file: str = ""
    rules: list[Rule] = field(default_factory=list)

    def load(self) -> None:
        if not self.rules_file:
            return
        path = Path(self.rules_file)
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for item in raw.get("rules", []):
                self.rules.append(
                    Rule(
                        action=str(item["action"]),
                        pattern=str(item["pattern"]),
                        decision=str(item["decision"]),
                    )
                )
        except (json.JSONDecodeError, KeyError, OSError):
            # A corrupt rules file should not brick the agent; ignore it.
            self.rules = []

    def save(self) -> None:
        if not self.rules_file:
            return
        path = Path(self.rules_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "rules": [
                {"action": r.action, "pattern": r.pattern, "decision": r.decision}
                for r in self.rules
            ]
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def decide(self, action: str, target: str) -> str | None:
        """Return 'allow' or 'deny' if a rule matches ``target``, else None."""
        for rule in self.rules:
            if rule.action != action:
                continue
            if _matches(rule.pattern, target):
                return rule.decision
        return None

    def add_rule(self, action: str, pattern: str, decision: str, persist: bool = True) -> None:
        self.rules.append(Rule(action=action, pattern=pattern, decision=decision))
        if persist:
            self.save()


def _matches(pattern: str, target: str) -> bool:
    """Match a path glob or a command-prefix pattern against a target."""
    pattern_n = pattern.replace("\\", "/")
    target_n = target.replace("\\", "/")
    # For bash: pattern is a prefix match on the command string.
    if pattern.startswith("cmd:"):
        prefix = pattern[4:]
        return target.lstrip().lower().startswith(prefix.lower())
    # For write: fnmatch on the whole (normalised) path.
    return fnmatch.fnmatch(target_n, pattern_n)


def ensure_allowed(permissions, renderer, config, action: str, target: str, remember_hint=None) -> str:
    """Resolve a permission decision for ``action``/``target``.

    Order of resolution:
      1. a stored rule (return it),
      2. an interactive prompt (renderer), remembering the rule if asked,
      3. the config default (headless / non-interactive).

    Returns ``"allow"`` or ``"deny"``.  Raises :class:`PermissionDeniedError`
    when the decision is ``deny``.
    """
    decision = permissions.decide(action, target)
    if decision is not None:
        if decision == "deny":
            raise PermissionDeniedError(f"{action} denied by rule: {target}")
        return decision

    if renderer is not None and getattr(renderer, "interactive", True):
        decision, remember = renderer.confirm_permission(action, target)
        if remember:
            pattern = remember_hint if remember_hint is not None else target
            permissions.add_rule(action, pattern, decision)
        if decision == "deny":
            raise PermissionDeniedError(f"{action} denied by user: {target}")
        return decision

    # Non-interactive path: no live user to ask — apply the config default.
    default = _default_for(config, action)
    if default == "deny":
        raise PermissionDeniedError(
            f"{action} denied: no rule matched {target!r} and non-interactive default is deny "
            "(use the TUI or allow rules to permit it)"
        )
    return "allow"


def _default_for(config, action: str) -> str:
    if action == ACTION_BASH:
        return config.permissions.default_bash
    return config.permissions.default_write
