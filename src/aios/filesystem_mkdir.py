"""Create one explicitly authorized directory inside the trusted workspace."""

from collections.abc import Callable
import os

from aios._filesystem import open_directory, validate_relative_path, FilesystemTool
from aios.tools import RiskLevel, ToolResult


class FilesystemMkdirTool(FilesystemTool):
    name = "filesystem.mkdir"
    description = "Create one directory relative to an authorized workspace after explicit confirmation."
    risk_level = RiskLevel.CONFIRM

    def execute(
        self, arguments: dict[str, object], *,
        authorize: Callable[[dict[str, object]], bool] | None = None,
    ) -> ToolResult:
        # Like systemd.restart, direct Python calls must also fail closed.
        if authorize is None:
            authorize = lambda _: False
        return super().execute(arguments, authorize=authorize)

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() not in ({"path"}, {"path", "workspace"}):
            raise ValueError("path is required; only workspace is optional")
        path = validate_relative_path(arguments["path"])
        if path == ".":
            raise ValueError("path must identify a new directory")
        self.validate_workspace(arguments)
        arguments["path"] = path

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments["path"]
        parent, _, name = path.rpartition("/")
        with open_directory(self.workspace_for(arguments), parent or ".") as directory:
            # A single mkdir refuses every existing entry, including symlinks.
            os.mkdir(name, mode=0o700, dir_fd=directory)
        return ToolResult(success=True, data={"workspace": arguments["workspace"], "path": path, "created": True})
