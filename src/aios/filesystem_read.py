"""Read a bounded UTF-8 text file inside the trusted workspace."""

import os
from pathlib import Path
import stat

from aios._filesystem import open_directory, validate_relative_path, workspace_path
from aios.tools import RiskLevel, Tool, ToolResult


MAX_READ_BYTES = 64 * 1024


class FilesystemReadTool(Tool):
    name = "filesystem.read"
    description = "Read a UTF-8 text file of at most 64 KiB relative to ~/AIOS-Workspace."
    risk_level = RiskLevel.READ

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace_path(workspace)

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() != {"path"}:
            raise ValueError("Only the required path is accepted")
        path = validate_relative_path(arguments["path"])
        if path == ".":
            raise ValueError("path must identify a file")
        arguments["path"] = path

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments["path"]
        parent, _, name = path.rpartition("/")
        with open_directory(self._workspace, parent or ".") as directory:
            expected = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(expected.st_mode) or expected.st_size > MAX_READ_BYTES:
                raise ValueError("Only bounded regular files may be read")
            # NONBLOCK prevents waiting on a FIFO substituted after the stat.
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
            descriptor = os.open(name, flags, dir_fd=directory)
            try:
                actual = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(actual.st_mode) or actual.st_size > MAX_READ_BYTES
                    or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino)
                ):
                    raise ValueError("File changed before opening")
                data = bytearray()
                while len(data) <= MAX_READ_BYTES:
                    chunk = os.read(descriptor, MAX_READ_BYTES + 1 - len(data))
                    if not chunk:
                        break
                    data.extend(chunk)
            finally:
                os.close(descriptor)
        if len(data) > MAX_READ_BYTES:
            raise ValueError("File exceeds read limit")
        content = data.decode("utf-8")
        if any((ord(c) < 32 and c not in "\t\r\n") or ord(c) == 127 for c in content):
            raise ValueError("File contains non-text control characters")
        return ToolResult(success=True, data={
            "path": path, "content": content, "size_bytes": len(data),
        })
