"""Small stdin-based prompt helpers shared by the renderers.

Kept deliberately dependency-light so both the rich TUI renderer and the plain
CLI renderer can reuse the exact same confirmation logic.
"""

from __future__ import annotations

_HELP = "  [y]es once  [n]o once  [a]llow always  [d]eny always"


def ask_permission(action: str, target: str, interactive: bool = True) -> tuple[str, bool]:
    """Ask the user to allow/deny an operation.

    Returns ``(decision, remember)`` where ``decision`` is ``"allow"`` or
    ``"deny"`` and ``remember`` is True when the user asked to remember the rule.
    In non-interactive mode, silently allow (matching the config-default path
    used by headless runs).
    """
    if not interactive:
        return "allow", False
    print(f"⚠  {action} requested on: {target}")
    print(_HELP)
    while True:
        try:
            ans = input("  → ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "deny", False
        if ans in ("y", "yes"):
            return "allow", False
        if ans in ("n", "no"):
            return "deny", False
        if ans in ("a", "always", "allow always", "all"):
            return "allow", True
        if ans in ("d", "deny always", "deny"):
            return "deny", True
        print("  (please answer y / n / a / d)")


def ask_confirm(prompt_text: str, default: bool = False, interactive: bool = True) -> bool:
    """Yes/no confirmation.  Returns True when the user confirms."""
    if not interactive:
        return True
    suffix = " [y/N] " if not default else " [Y/n] "
    while True:
        try:
            ans = input(prompt_text + suffix).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        if ans == "":
            return default
        print("  (please answer y or n)")
