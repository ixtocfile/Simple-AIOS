"""Read filesystem capacity without writing files or running commands."""

from pathlib import Path
from shutil import disk_usage

from aios.tools import RiskLevel, Tool, ToolResult


class SystemDiskTool(Tool):
    name = "system.disk"
    description = "Read filesystem capacity and usage for an absolute path."
    risk_level = RiskLevel.READ

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() - {"path"}:
            raise ValueError("Only path is accepted")
        path = arguments.get("path", "/")
        if not isinstance(path, str) or "\0" in path or not Path(path).is_absolute():
            raise ValueError("path must be an absolute path string without null bytes")
        arguments["path"] = path

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        path = arguments["path"]
        total, used, free = disk_usage(path)
        if (
            any(type(value) is not int or value < 0 for value in (total, used, free))
            or used + free > total
        ):
            raise ValueError("Invalid disk usage information")
        return ToolResult(success=True, data={
            "path": path,
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "used_percent": round(used / total * 100, 2) if total else 0.0,
        })
