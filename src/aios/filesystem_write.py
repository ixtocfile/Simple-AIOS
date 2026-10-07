"""Create one bounded UTF-8 text file after explicit authorization."""

from collections.abc import Callable
import os

from aios._filesystem import encode_text, open_directory, validate_relative_path, FilesystemTool
from aios.tools import RiskLevel, ToolResult


MAX_WRITE_BYTES = 64 * 1024


class FilesystemWriteTool(FilesystemTool):
    name = "filesystem.write"
    description = "Create a new UTF-8 file of at most 64 KiB in an authorized workspace after confirmation."
    risk_level = RiskLevel.CONFIRM

    def execute(
        self, arguments: dict[str, object], *,
        authorize: Callable[[dict[str, object]], bool] | None = None,
    ) -> ToolResult:
        if authorize is None:
            authorize = lambda _: False
        return super().execute(arguments, authorize=authorize)

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() not in ({"path", "content"}, {"path", "content", "workspace"}):
            raise ValueError("path and content are required; only workspace is optional")
        path = validate_relative_path(arguments["path"])
        if path == ".":
            raise ValueError("path must identify a new file")
        encode_text(arguments["content"], MAX_WRITE_BYTES)
        self.validate_workspace(arguments)
        arguments["path"] = path

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments["path"]
        data = arguments["content"].encode("utf-8")
        parent, _, name = path.rpartition("/")
        with open_directory(self.workspace_for(arguments), parent or ".") as directory:
            # Exclusive creation refuses all existing entries without truncation.
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptor = os.open(name, flags, mode=0o600, dir_fd=directory)
            try:
                try:
                    remaining = memoryview(data)
                    while remaining:
                        written = os.write(descriptor, remaining)
                        if written <= 0:
                            raise OSError("Write made no progress")
                        remaining = remaining[written:]
                finally:
                    os.close(descriptor)
            except OSError:
                # Do not unlink a pathname that another process could replace.
                return ToolResult(success=False, error="File creation failed; file may be incomplete")
        return ToolResult(success=True, data={
            "workspace": arguments["workspace"], "path": path, "created": True, "size_bytes": len(data),
        })
