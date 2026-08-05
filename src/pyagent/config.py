"""TOML configuration loading and validation.

The config file lives at ``~/.pyagent/config.toml`` (or the path given by
``--config``).  A missing file is fine — sensible defaults are used and the
default path is echoed on startup.  An *invalid* file (unparsable TOML or
unknown/ill-typed keys) raises a clear error instead of silently degrading.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Default config location, overridable via ``PYAGENT_CONFIG`` or ``--config``.
DEFAULT_CONFIG_PATH = Path.home() / ".pyagent" / "config.toml"

#: Default directory for saved sessions.
DEFAULT_SESSION_DIR = Path.home() / ".pyagent" / "sessions"

#: Keys that must exist with the right types.  Nested paths use ``/``.
_REQUIRED_TYPES: dict[str, type] = {
    "model/base_url": str,
    "model/model": str,
    "model/api_key": str,
    "model/api_key_env": str,
    "model/max_turns": int,
    "model/timeout": int,
    "session/dir": str,
    "permissions/default_write": str,
    "permissions/default_bash": str,
    "tools/bash_timeout": int,
}

_ALLOWED_TOP = {"model", "permissions", "session", "tools"}


class ConfigError(Exception):
    """Raised when the configuration file is missing or invalid."""


@dataclass
class Config:
    """Resolved application configuration."""

    model: ModelConfig = field(default_factory=lambda: ModelConfig())
    permissions: PermissionConfig = field(default_factory=lambda: PermissionConfig())
    session: SessionConfig = field(default_factory=lambda: SessionConfig())
    tools: ToolsConfig = field(default_factory=lambda: ToolsConfig())

    @property
    def path(self) -> Path | None:
        return getattr(self, "_path", None)

    @path.setter
    def path(self, value: Path | None) -> None:
        self._path = value


@dataclass
class ModelConfig:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    api_key: str = ""  # optional literal key; takes precedence over the env var
    max_turns: int = 20
    timeout: int = 300

    def resolve_api_key(self) -> str | None:
        """Return the literal key if set, else read from the env var."""
        if self.api_key:
            return self.api_key
        return os.environ.get(self.api_key_env)


@dataclass
class PermissionConfig:
    default_write: str = "prompt"  # "allow" | "deny" | "prompt"
    default_bash: str = "prompt"
    rules_file: str = str(Path.home() / ".pyagent" / "permissions.json")


@dataclass
class SessionConfig:
    dir: str = str(DEFAULT_SESSION_DIR)


@dataclass
class ToolsConfig:
    bash_timeout: int = 120


def _resolve_path(path: str) -> str:
    return str(Path(os.path.expanduser(path)).resolve())


def load_config(path: str | Path | None = None) -> Config:
    """Load and validate configuration.

    Args:
        path: Explicit config file path.  ``None`` uses ``PYAGENT_CONFIG`` then
            the default location.  If neither exists, defaults are returned.
    """
    cfg_path = _find_config_path(path)
    if cfg_path is None:
        config = Config()
        config.path = None
        return config

    try:
        with open(cfg_path, "rb") as fh:
            raw: dict[str, Any] = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {cfg_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read config file {cfg_path}: {exc}") from exc

    _validate(raw, cfg_path)
    config = _apply(raw)
    config.path = cfg_path
    return config


def _find_config_path(explicit: str | Path | None) -> Path | None:
    if explicit is not None:
        p = Path(os.path.expanduser(str(explicit)))
        if not p.exists():
            raise ConfigError(f"config file not found: {p}")
        return p
    env = os.environ.get("PYAGENT_CONFIG")
    if env:
        p = Path(os.path.expanduser(env))
        if not p.exists():
            raise ConfigError(f"config file not found (from PYAGENT_CONFIG): {p}")
        return p
    default = DEFAULT_CONFIG_PATH
    return default if default.exists() else None


def _validate(raw: dict[str, Any], path: Path) -> None:
    for key in raw:
        if key not in _ALLOWED_TOP:
            raise ConfigError(f"{path}: unknown section [{key}] (allowed: {sorted(_ALLOWED_TOP)})")
    for dotted, typ in _REQUIRED_TYPES.items():
        section, _, name = dotted.partition("/")
        if section in raw and name in raw[section]:
            value = raw[section][name]
            if not isinstance(value, typ):
                raise ConfigError(
                    f"{path}: [{section}] {name} must be {typ.__name__}, got {type(value).__name__}"
                )
            if name.endswith("_write") or name.endswith("_bash"):
                if value not in ("allow", "deny", "prompt"):
                    raise ConfigError(
                        f"{path}: [{section}] {name} must be 'allow', 'deny' or 'prompt', got {value!r}"
                    )
            if name == "max_turns" and value < 1:
                raise ConfigError(f"{path}: [model] max_turns must be >= 1")


def _apply(raw: dict[str, Any]) -> Config:
    config = Config()

    model = raw.get("model", {})
    config.model.base_url = str(model.get("base_url", config.model.base_url))
    config.model.model = str(model.get("model", config.model.model))
    config.model.api_key_env = str(model.get("api_key_env", config.model.api_key_env))
    config.model.api_key = str(model.get("api_key", config.model.api_key))
    config.model.max_turns = int(model.get("max_turns", config.model.max_turns))
    config.model.timeout = int(model.get("timeout", config.model.timeout))

    perms = raw.get("permissions", {})
    config.permissions.default_write = str(perms.get("default_write", config.permissions.default_write))
    config.permissions.default_bash = str(perms.get("default_bash", config.permissions.default_bash))
    config.permissions.rules_file = _resolve_path(
        str(perms.get("rules_file", config.permissions.rules_file))
    )

    session = raw.get("session", {})
    config.session.dir = _resolve_path(str(session.get("dir", config.session.dir)))

    tools = raw.get("tools", {})
    config.tools.bash_timeout = int(tools.get("bash_timeout", config.tools.bash_timeout))

    return config
