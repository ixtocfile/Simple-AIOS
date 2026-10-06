"""List immediate workspace entries without following links or opening files."""

from itertools import islice
import os
from pathlib import Path
import stat

from aios.tools import RiskLevel, Tool, ToolResult


MAX_LIST_ENTRIES = 100


class FilesystemListTool(Tool):
    name = "filesystem.list"
    description = "List up to 100 entries in a directory relative to ~/AIOS-Workspace."
    risk_level = RiskLevel.READ

    def __init__(self, workspace: Path | None = None) -> None:
        # The workspace is chosen by trusted Python code, never by tool arguments.
        self._workspace = Path(workspace) if workspace is not None else Path.home() / "AIOS-Workspace"
        if not self._workspace.is_absolute() or ".." in self._workspace.parts:
            raise ValueError("workspace must be an absolute path without traversal")

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() - {"path"}:
            raise ValueError("Only path is accepted")
        path = arguments.get("path", ".")
        if (
            not isinstance(path, str) or not path.strip()
            or len(path.encode("utf-8")) > 4096 or "\\" in path
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
            or (path != "." and any(part in {"", ".", ".."} for part in path.split("/")))
        ):
            raise ValueError("path must be an unambiguous relative directory path")
        arguments["path"] = path

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments["path"]
        parts = self._workspace.parts[1:] + (() if path == "." else tuple(path.split("/")))
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        directory = os.open("/", flags)
        try:
            # Open each component relative to its already opened parent. A link
            # substituted between validation and opening cannot escape the root.
            for part in parts:
                child = os.open(part, flags, dir_fd=directory)
                os.close(directory)
                directory = child
            with os.scandir(directory) as iterator:
                entries = list(islice(iterator, MAX_LIST_ENTRIES + 1))
            data = []
            for entry in sorted(entries[:MAX_LIST_ENTRIES], key=lambda item: item.name):
                metadata = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
                if stat.S_ISREG(metadata.st_mode):
                    kind = "file"
                elif stat.S_ISDIR(metadata.st_mode):
                    kind = "directory"
                elif stat.S_ISLNK(metadata.st_mode):
                    kind = "symlink"
                else:
                    kind = "other"
                data.append({
                    "name": entry.name, "type": kind,
                    "size_bytes": metadata.st_size if kind == "file" else None,
                })
            return ToolResult(success=True, data={
                "path": path, "entries": data, "truncated": len(entries) > MAX_LIST_ENTRIES,
            })
        finally:
            os.close(directory)
