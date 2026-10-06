"""Create one explicitly authorized directory inside the trusted workspace."""

from collections.abc import Callable
import os
from pathlib import Path

from aios._filesystem import open_directory, validate_relative_path, workspace_path
from aios.tools import RiskLevel, Tool, ToolResult


class FilesystemMkdirTool(Tool):
    name = "filesystem.mkdir"
    description = "Create one directory relative to ~/AIOS-Workspace after explicit confirmation."
    risk_level = RiskLevel.CONFIRM

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace_path(workspace)

    def execute(
        self, arguments: dict[str, object], *,
        authorize: Callable[[dict[str, object]], bool] | None = None,
    ) -> ToolResult:
        # Like systemd.restart, direct Python calls must also fail closed.
        if authorize is None:
            authorize = lambda _: False
        return super().execute(arguments, authorize=authorize)

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() != {"path"}:
            raise ValueError("Only the required path is accepted")
        path = validate_relative_path(arguments["path"])
        if path == ".":
            raise ValueError("path must identify a new directory")
        arguments["path"] = path

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments["path"]
        parent, _, name = path.rpartition("/")
        with open_directory(self._workspace, parent or ".") as directory:
            # A single mkdir refuses every existing entry, including symlinks.
            os.mkdir(name, mode=0o700, dir_fd=directory)
        return ToolResult(success=True, data={"path": path, "created": True})
