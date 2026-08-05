"""危险操作（写文件、Shell 命令）的 allow/deny 规则。

规则按目标记忆：写操作的目标是路径（glob），bash 是命令前缀。规则持久化到
JSON 文件，因此「记住此规则」在重启后依然有效。当没有规则命中时，调用方可
提示用户（TUI）或回退到配置默认值（无头）。
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: action 名称
ACTION_WRITE = "write"
ACTION_BASH = "bash"


class PermissionDeniedError(Exception):
    """用户/规则拒绝某操作时抛出。"""


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
            # 损坏的规则文件不应让 agent 瘫痪；忽略之。
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
        """若某条规则命中 ``target`` 则返回 'allow' 或 'deny'，否则返回 None。"""
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
    """用路径 glob 或命令前缀模式匹配目标。"""
    pattern_n = pattern.replace("\\", "/")
    target_n = target.replace("\\", "/")
    # 对 bash：pattern 是对命令串的前缀匹配。
    if pattern.startswith("cmd:"):
        prefix = pattern[4:]
        return target.lstrip().lower().startswith(prefix.lower())
    # 对 write：对整个（归一化后的）路径做 fnmatch。
    return fnmatch.fnmatch(target_n, pattern_n)


def ensure_allowed(permissions, renderer, config, action: str, target: str, remember_hint=None) -> str:
    """为 ``action``/``target`` 解析一个权限判定。

    解析顺序：
      1. 命中的已记忆规则（直接返回）；
      2. 交互式提示（渲染器），如用户要求则记住规则；
      3. 配置默认值（无头 / 非交互）。

    返回 ``"allow"`` 或 ``"deny"``。判定为 ``deny`` 时抛出
    :class:`PermissionDeniedError`。
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

    # 非交互路径：没有实时用户可询问——套用配置默认值。
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
