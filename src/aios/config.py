"""Load optional TOML settings without performing system or network actions."""

from dataclasses import dataclass, field, fields
from pathlib import Path
import tomllib
from urllib.parse import urlsplit

from aios._filesystem import default_filesystem_roots, normalize_filesystem_roots


@dataclass(frozen=True)
class Config:
    provider: str = "ollama"
    model: str = "qwen3"
    ollama_url: str = "http://127.0.0.1:11434"
    data_dir: Path = field(
        default_factory=lambda: Path.home() / ".local" / "share" / "simple-aios"
    )
    log_level: str = "INFO"
    filesystem_roots: tuple[Path, ...] = field(default_factory=default_filesystem_roots)

    def __post_init__(self) -> None:
        object.__setattr__(self, "filesystem_roots", normalize_filesystem_roots(self.filesystem_roots))


def load_config(path: str | Path | None = None) -> Config:
    """Return defaults or override them with an explicitly supplied TOML file.

    Missing/unreadable files raise OSError; invalid contents raise ValueError.
    Data paths expand '~'; relative paths remain relative to the working directory.
    """
    if path is None:
        return Config()

    with Path(path).expanduser().open("rb") as source:
        values = tomllib.load(source)

    unknown = values.keys() - {item.name for item in fields(Config)}
    if unknown:
        raise ValueError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
    for key, value in values.items():
        if key == "filesystem_roots":
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError("filesystem_roots must be a list of strings")
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")

    if "log_level" in values:
        values["log_level"] = values["log_level"].strip().upper()
        if values["log_level"] not in {
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "NOTSET"
        }:
            raise ValueError("Invalid log_level")

    if "ollama_url" in values:
        url = values["ollama_url"]
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and (parsed.port is None or parsed.port > 0)
            )
        except ValueError:
            valid = False
        if not valid or any(character.isspace() for character in url):
            raise ValueError("ollama_url must be an HTTP(S) URL with a valid host and port")

    if "data_dir" in values:
        values["data_dir"] = Path(values["data_dir"]).expanduser()

    return Config(**values)
