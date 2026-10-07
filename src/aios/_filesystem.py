"""Shared path checks and read-only directory access for filesystem tools."""

from contextlib import contextmanager
import os
from pathlib import Path

from aios.tools import Tool


def default_filesystem_roots() -> tuple[Path, ...]:
    return (Path.home() / "AIOS-Workspace",)


def normalize_filesystem_roots(values: object) -> tuple[Path, ...]:
    """Validate trusted configuration without resolving links or accessing roots."""
    if not isinstance(values, (list, tuple)):
        raise ValueError("filesystem_roots must be a list of paths")
    roots = []
    for value in values:
        if not isinstance(value, (str, Path)):
            raise ValueError("filesystem_roots entries must be paths")
        raw = str(value)
        if not (raw.startswith("/") or raw == "~" or raw.startswith("~/")):
            raise ValueError("filesystem_roots must be absolute or start with ~/")
        if raw not in {"/", "~"}:
            relative = validate_relative_path(raw[2:] if raw.startswith("~/") else raw[1:])
            if relative == ".":
                raise ValueError("filesystem_roots must not contain dot components")
        root = Path(raw).expanduser()
        # Check the expanded home as well; never use resolve(), which follows links.
        if not root.is_absolute():
            raise ValueError("filesystem_roots must expand to absolute paths")
        if str(root) != "/":
            validate_relative_path(str(root)[1:])
        if root in roots:
            raise ValueError("filesystem_roots must not contain duplicates")
        roots.append(root)
    return tuple(roots)


class FilesystemTool(Tool):
    """The allowlist comes only from trusted construction, never from the model."""

    def __init__(
        self, workspace: Path | None = None, *,
        filesystem_roots: tuple[Path, ...] | None = None,
    ) -> None:
        if workspace is not None:
            if filesystem_roots is not None:
                raise ValueError("Choose workspace or filesystem_roots, not both")
            filesystem_roots = (workspace,)
        roots = default_filesystem_roots() if filesystem_roots is None else filesystem_roots
        self._workspaces = {str(root): root for root in normalize_filesystem_roots(roots)}

    def validate_workspace(self, arguments: dict[str, object]) -> None:
        workspace = arguments.get("workspace", next(iter(self._workspaces), None))
        if not isinstance(workspace, str) or workspace not in self._workspaces:
            raise ValueError("Workspace is not authorized")
        # Confirmation and results identify the actual root, even when omitted.
        arguments["workspace"] = workspace

    def workspace_for(self, arguments: dict[str, object]) -> Path:
        return self._workspaces[arguments["workspace"]]


def validate_relative_path(path: object) -> str:
    if (
        not isinstance(path, str) or not path.strip()
        or len(path.encode("utf-8")) > 4096 or "\\" in path
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
        or (path != "." and any(part in {"", ".", ".."} for part in path.split("/")))
    ):
        raise ValueError("path must be an unambiguous relative path")
    return path


def encode_text(content: object, limit: int) -> bytes:
    if not isinstance(content, str) or len(content) > limit:
        raise ValueError("content must be bounded UTF-8 text")
    data = content.encode("utf-8")
    if len(data) > limit or any((ord(c) < 32 and c not in "\t\r\n") or ord(c) == 127 for c in content):
        raise ValueError("content must be bounded UTF-8 text")
    return data


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
