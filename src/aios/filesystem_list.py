"""List immediate workspace entries without following links or opening files."""

from itertools import islice
import os
from pathlib import Path
import stat

from aios._filesystem import open_directory, validate_relative_path, workspace_path
from aios.tools import RiskLevel, Tool, ToolResult


MAX_LIST_ENTRIES = 100


class FilesystemListTool(Tool):
    name = "filesystem.list"
    description = "List up to 100 entries in a directory relative to ~/AIOS-Workspace."
    risk_level = RiskLevel.READ

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace_path(workspace)

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() - {"path"}:
            raise ValueError("Only path is accepted")
        arguments["path"] = validate_relative_path(arguments.get("path", "."))

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments["path"]
        with open_directory(self._workspace, path) as directory:
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
