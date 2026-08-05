"""渲染器共享的小型 stdin 确认辅助函数。

刻意保持轻依赖，让 rich TUI 渲染器与纯文本 CLI 渲染器复用完全相同的确认逻辑。
"""

from __future__ import annotations

_HELP = "  [y]es once  [n]o once  [a]llow always  [d]eny always"


def ask_permission(action: str, target: str, interactive: bool = True) -> tuple[str, bool]:
    """请求用户允许/拒绝某个操作。

    返回 ``(decision, remember)``，其中 ``decision`` 为 ``"allow"`` 或
    ``"deny"``，``remember`` 在用户要求记住规则时为 True。非交互模式下静默
    放行（与无头运行时使用的配置默认值路径一致）。
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
    """是/否确认。用户确认时返回 True。"""
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
