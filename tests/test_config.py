"""Configuration tests use temporary files and never contact an LLM."""

from dataclasses import replace
from pathlib import Path
import tomllib

import pytest

from aios.config import Config, load_config


def test_defaults_do_not_create_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    config = load_config()

    assert config.provider == "ollama"
    assert config.model == "qwen3"
    assert config.ollama_url == "http://127.0.0.1:11434"
    assert config.data_dir == tmp_path / ".local/share/simple-aios"
    assert config.log_level == "INFO"
    assert config.filesystem_roots == (tmp_path / "AIOS-Workspace",)
    assert not config.filesystem_roots[0].exists()
    assert not config.data_dir.exists()


def test_full_override(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "settings.toml"
    path.write_text(
        'provider = "custom"\nmodel = "small-local:latest"\n'
        'ollama_url = "https://localhost:1234/api"\n'
        'data_dir = "~/aios-data"\nlog_level = "debug"\n',
        encoding="utf-8",
    )

    config = load_config("~/settings.toml")

    assert config.provider == "custom"
    assert config.model == "small-local:latest"
    assert config.ollama_url == "https://localhost:1234/api"
    assert config.data_dir == tmp_path / "aios-data"
    assert config.log_level == "DEBUG"
    assert not config.data_dir.exists()


def test_partial_file_keeps_other_defaults(tmp_path):
    path = tmp_path / "partial.toml"
    path.write_text('model = "another-model"\n', encoding="utf-8")

    assert load_config(path) == replace(load_config(), model="another-model")


def test_empty_file_uses_defaults(tmp_path):
    path = tmp_path / "empty.toml"
    path.touch()

    assert load_config(path) == load_config()


def test_relative_data_path_stays_relative(tmp_path):
    path = tmp_path / "relative.toml"
    path.write_text('data_dir = "data"\n', encoding="utf-8")

    assert load_config(path).data_dir == Path("data")


def test_example_matches_defaults():
    example = Path(__file__).resolve().parents[1] / "config/example.toml"

    assert load_config(example) == load_config()


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ('provdier = "ollama"', "Unknown configuration keys"),
        ('provider = ""', "provider must be a non-empty string"),
        ('model = "   "', "model must be a non-empty string"),
        ('model = 42', "model must be a non-empty string"),
        ('data_dir = false', "data_dir must be a non-empty string"),
        ('log_level = "verbose"', "Invalid log_level"),
        ('ollama_url = "localhost:11434"', "ollama_url must be"),
        ('ollama_url = "ftp://localhost"', "ollama_url must be"),
        ('ollama_url = "http://"', "ollama_url must be"),
        ('ollama_url = "http://local host"', "ollama_url must be"),
        ('ollama_url = "http://localhost:invalid"', "ollama_url must be"),
        ('ollama_url = "http://localhost:65536"', "ollama_url must be"),
        ('ollama_url = "http://localhost:0"', "ollama_url must be"),
    ],
)
def test_invalid_settings_are_rejected(tmp_path, contents, message):
    path = tmp_path / "invalid.toml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_malformed_toml(tmp_path):
    path = tmp_path / "malformed.toml"
    path.write_text('model = "unfinished', encoding="utf-8")

    with pytest.raises(tomllib.TOMLDecodeError):
        load_config(path)


def test_explicit_missing_file_is_not_silently_ignored(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.toml")


def test_filesystem_roots_replace_default_expand_home_and_keep_order(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "settings.toml"
    path.write_text('filesystem_roots = ["~/travail", "/srv/aios partagé"]\n')
    blocked = lambda *_args, **_kwargs: pytest.fail("No root lookup or creation while loading config")
    for method in ("resolve", "mkdir", "stat"):
        monkeypatch.setattr(Path, method, blocked)
    config = load_config(path)
    assert config.filesystem_roots == (tmp_path / "travail", Path("/srv/aios partagé"))
    assert tmp_path / "AIOS-Workspace" not in config.filesystem_roots


def test_empty_filesystem_roots_disable_access_without_restoring_default(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("filesystem_roots = []\n")
    assert load_config(path).filesystem_roots == ()
    assert Config(filesystem_roots=[]).filesystem_roots == ()


def test_python_config_copies_roots_and_remains_immutable(tmp_path):
    roots = [tmp_path / "first"]
    config = Config(filesystem_roots=roots)
    roots.append(tmp_path / "second")
    assert config.filesystem_roots == (tmp_path / "first",)
    with pytest.raises(AttributeError):
        config.filesystem_roots = ()


@pytest.mark.parametrize("value", [
    '"~/workspace"', 'true', '42', '{}', '[true]', '[42]', '[[]]', '[{}]', '[""]', '["  "]',
    '["relative"]', '["~someone/workspace"]', '["/tmp/../workspace"]', '["/tmp/./workspace"]',
    '["/tmp//workspace"]', '["/tmp/workspace/"]', '["//tmp/workspace"]', '["/."]', '["~/."]',
    '["~/"]', '["/tmp/w\\nork"]', '["/tmp/w\\u0000ork"]', '["/tmp/w\\u007fork"]',
    '["/tmp/a\\\\b"]', '["/tmp/a", "/tmp/a"]',
])
def test_invalid_filesystem_roots_are_rejected(tmp_path, value):
    path = tmp_path / "invalid.toml"
    path.write_text("filesystem_roots = " + value + "\n")
    with pytest.raises(ValueError):
        load_config(path)


def test_duplicate_expanded_roots_and_invalid_direct_config_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError, match="duplicates"):
        Config(filesystem_roots=["~/workspace", tmp_path / "workspace"])
    for values in (None, str(tmp_path), [True], ["../outside"], ["/bad\ud800"]):
        with pytest.raises(ValueError):
            Config(filesystem_roots=values)
