"""Shared path checks and read-only directory access for filesystem tools."""

from contextlib import contextmanager
import os
from pathlib import Path


def workspace_path(workspace: Path | None) -> Path:
    # The workspace is chosen by trusted Python code, never by tool arguments.
    root = Path(workspace) if workspace is not None else Path.home() / "AIOS-Workspace"
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("workspace must be an absolute path without traversal")
    return root


def validate_relative_path(path: object) -> str:
    if (
        not isinstance(path, str) or not path.strip()
        or len(path.encode("utf-8")) > 4096 or "\\" in path
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
        or (path != "." and any(part in {"", ".", ".."} for part in path.split("/")))
    ):
        raise ValueError("path must be an unambiguous relative path")
    return path


@contextmanager
def open_directory(workspace: Path, path: str):
    parts = workspace.parts[1:] + (() if path == "." else tuple(path.split("/")))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open("/", flags)
    try:
        # Anchor each component to its open parent, never following a link.
        for part in parts:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        yield directory
    finally:
        os.close(directory)
