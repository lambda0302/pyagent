"""F3 (config): TOML loading, validation errors, key resolution."""

from __future__ import annotations

import pytest

from pyagent.config import Config, ConfigError, load_config


def _write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadConfig:
    def test_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PYAGENT_CONFIG", raising=False)
        # Point the default location at a path that does not exist so the test
        # does not depend on the developer's real ~/.pyagent/config.toml.
        monkeypatch.setattr("pyagent.config.DEFAULT_CONFIG_PATH", tmp_path / "missing.toml")
        config = load_config()
        assert config.model.model == "gpt-4o-mini"
        assert config.permissions.default_write == "prompt"

    def test_valid_file_parsed(self, tmp_path):
        path = _write(
            tmp_path,
            """
            [model]
            base_url = "https://api.deepseek.com/v1"
            model = "deepseek-chat"
            api_key_env = "DEEPSEEK_API_KEY"
            max_turns = 5
            [session]
            dir = "sessions_dir"
            [permissions]
            default_write = "deny"
            """,
        )
        config = load_config(path)
        assert config.model.base_url == "https://api.deepseek.com/v1"
        assert config.model.model == "deepseek-chat"
        assert config.model.max_turns == 5
        assert config.session.dir.endswith("sessions_dir")
        assert config.permissions.default_write == "deny"

    def test_invalid_toml_raises_clear_error(self, tmp_path):
        path = _write(tmp_path, "[model\nbase_url = ")
        with pytest.raises(ConfigError, match="invalid TOML"):
            load_config(path)

    def test_unknown_section_raises(self, tmp_path):
        path = _write(tmp_path, "[bogus]\nkey = 1\n")
        with pytest.raises(ConfigError, match="unknown section"):
            load_config(path)

    def test_wrong_type_raises(self, tmp_path):
        path = _write(tmp_path, "[model]\nmax_turns = \"twenty\"\n")
        with pytest.raises(ConfigError, match="max_turns"):
            load_config(path)

    def test_bad_default_raises(self, tmp_path):
        path = _write(tmp_path, "[permissions]\ndefault_write = \"sometimes\"\n")
        with pytest.raises(ConfigError, match="default_write"):
            load_config(path)

    def test_missing_explicit_file_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nope.toml")


class TestApiKeyResolution:
    def test_literal_key_wins(self, monkeypatch):
        config = Config()
        config.model.api_key = "literal"
        monkeypatch.setenv("OPENAI_API_KEY", "from_env")
        assert config.model.resolve_api_key() == "literal"

    def test_env_key_fallback(self, monkeypatch):
        config = Config()
        monkeypatch.setenv("OPENAI_API_KEY", "from_env")
        assert config.model.resolve_api_key() == "from_env"
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert config.model.resolve_api_key() is None
