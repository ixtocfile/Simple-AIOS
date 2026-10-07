"""List immediate workspace entries without following links or opening files."""

from itertools import islice
import os
import stat

from aios._filesystem import open_directory, validate_relative_path, FilesystemTool
from aios.tools import RiskLevel, ToolResult


MAX_LIST_ENTRIES = 100


class FilesystemListTool(FilesystemTool):
    name = "filesystem.list"
    description = "List up to 100 entries in a directory relative to an authorized workspace."
    risk_level = RiskLevel.READ

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() - {"path", "workspace"}:
            raise ValueError("Only path and workspace are accepted")
        self.validate_workspace(arguments)
        arguments["path"] = validate_relative_path(arguments.get("path", "."))

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments["path"]
        with open_directory(self.workspace_for(arguments), path) as directory:
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
                "workspace": arguments["workspace"], "path": path, "entries": data, "truncated": len(entries) > MAX_LIST_ENTRIES,
            })
