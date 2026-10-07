"""Replace bounded text only after confirmation and a durable private backup."""

from collections.abc import Callable
import os
from pathlib import Path
import stat
from uuid import uuid4

from aios._filesystem import encode_text, open_directory, validate_relative_path, workspace_path
from aios.tools import RiskLevel, Tool, ToolResult


MAX_UPDATE_BYTES = 64 * 1024
BACKUP_PREFIX = ".aios-update-"


def _version(info: os.stat_result) -> tuple[int, ...]:
    # Reading may change atime; every field relevant to replacement is checked.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _check_version(directory: int, name: str, expected: os.stat_result) -> None:
    if _version(os.stat(name, dir_fd=directory, follow_symlinks=False)) != _version(expected):
        raise ValueError("File changed during update")


def _read_original(directory: int, name: str) -> tuple[os.stat_result, bytes]:
    expected = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if (
        not stat.S_ISREG(expected.st_mode) or expected.st_nlink != 1
        or expected.st_size > MAX_UPDATE_BYTES or expected.st_uid != os.geteuid()
        or expected.st_mode & 0o7000 or not expected.st_mode & 0o222
    ):
        raise ValueError("Only owned, writable, singly linked text files may be updated")
    # Require write permission without truncating or writing to the original inode.
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
    descriptor = os.open(name, flags, dir_fd=directory)
    try:
        if _version(os.fstat(descriptor)) != _version(expected):
            raise ValueError("File changed before opening")
        if os.listxattr(descriptor):
            raise ValueError("Extended attributes cannot be preserved by this tool")
        data = bytearray()
        while len(data) <= MAX_UPDATE_BYTES:
            chunk = os.read(descriptor, MAX_UPDATE_BYTES + 1 - len(data))
            if not chunk:
                break
            data.extend(chunk)
        if _version(os.fstat(descriptor)) != _version(expected):
            raise ValueError("File changed while reading")
    finally:
        os.close(descriptor)
    return expected, encode_text(data.decode("utf-8"), MAX_UPDATE_BYTES)


def _write_copy(
    directory: int, name: str, data: bytes, original: os.stat_result | None = None,
) -> os.stat_result:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(name, flags, mode=0o600, dir_fd=directory)
    try:
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("Write made no progress")
            remaining = remaining[written:]
        if original is not None:
            if os.listxattr(descriptor):
                raise ValueError("Replacement must not inherit extended permissions")
            if os.fstat(descriptor).st_gid != original.st_gid:
                os.fchown(descriptor, -1, original.st_gid)
            os.fchmod(descriptor, stat.S_IMODE(original.st_mode))
        os.fsync(descriptor)
        return os.fstat(descriptor)
    finally:
        os.close(descriptor)


class FilesystemUpdateTool(Tool):
    name = "filesystem.update"
    description = "Replace an existing UTF-8 file of at most 64 KiB in ~/AIOS-Workspace after confirmation and backup."
    risk_level = RiskLevel.CONFIRM

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace_path(workspace)

    def execute(
        self, arguments: dict[str, object], *,
        authorize: Callable[[dict[str, object]], bool] | None = None,
    ) -> ToolResult:
        if authorize is None:
            authorize = lambda _: False
        return super().execute(arguments, authorize=authorize)

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() != {"path", "content"}:
            raise ValueError("Only the required path and content are accepted")
        path = validate_relative_path(arguments["path"])
        if path == "." or any(part.startswith(BACKUP_PREFIX) for part in path.split("/")):
            raise ValueError("path must identify a file outside the tool's backups")
        encode_text(arguments["content"], MAX_UPDATE_BYTES)
        arguments["path"] = path

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments["path"]
        data = arguments["content"].encode("utf-8")
        parent, _, name = path.rpartition("/")
        replacing = False
        try:
            with open_directory(self._workspace, parent or ".") as directory:
                original, previous = _read_original(directory, name)
                backup_name = BACKUP_PREFIX + uuid4().hex
                os.mkdir(backup_name, mode=0o700, dir_fd=directory)
                saved_directory = os.stat(backup_name, dir_fd=directory, follow_symlinks=False)
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
                backup_directory = os.open(backup_name, flags, dir_fd=directory)
                try:
                    if _version(os.fstat(backup_directory)) != _version(saved_directory):
                        raise ValueError("Backup directory changed before opening")
                    backup = _write_copy(backup_directory, "backup.txt", previous)
                    # Persist the backup and its directory entries before replacement.
                    os.fsync(backup_directory)
                    os.fsync(directory)
                    replacement = _write_copy(backup_directory, "replacement.tmp", data, original)
                    _check_version(backup_directory, "backup.txt", backup)
                    _check_version(backup_directory, "replacement.tmp", replacement)
                    current_directory = os.stat(backup_name, dir_fd=directory, follow_symlinks=False)
                    if (current_directory.st_dev, current_directory.st_ino, current_directory.st_mode) != (
                        saved_directory.st_dev, saved_directory.st_ino, saved_directory.st_mode,
                    ):
                        raise ValueError("Backup directory moved")
                    _check_version(directory, name, original)
                    # Atomic rename, not a compare-and-swap against external writers.
                    replacing = True
                    os.replace("replacement.tmp", name, src_dir_fd=backup_directory, dst_dir_fd=directory)
                    os.fsync(directory)
                    os.fsync(backup_directory)
                finally:
                    os.close(backup_directory)
        except OSError:
            if replacing:
                return ToolResult(success=False, error="File update outcome uncertain; inspect file and backup before retrying")
            raise
        # Keep backups (and any incomplete preparation on failure); never unlink by path.
        backup_path = f"{parent}/" if parent else ""
        return ToolResult(success=True, data={
            "path": path, "updated": True, "size_bytes": len(data),
            "backup_path": f"{backup_path}{backup_name}/backup.txt",
        })
