"""Read Linux RAM statistics without external commands or dependencies."""

from pathlib import Path

from aios.tools import Tool, ToolResult


class SystemMemoryTool(Tool):
    name = "system.memory"
    description = "Read total, free, available and used RAM."

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments:
            raise ValueError("system.memory does not accept arguments")

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        required = {"MemTotal", "MemFree", "MemAvailable"}
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, _, raw = line.partition(":")
            key = key.strip()
            if key not in required:
                continue
            fields = raw.split()
            if (
                key in values
                or len(fields) != 2
                or not fields[0].isdecimal()
                or fields[1] != "kB"
            ):
                raise ValueError("Invalid memory information")
            # Linux meminfo labels units of 1024 bytes as kB.
            values[key] = int(fields[0]) * 1024

        if values.keys() != required:
            raise ValueError("Missing memory information")
        total = values["MemTotal"]
        free = values["MemFree"]
        available = values["MemAvailable"]
        if total <= 0 or not 0 <= free <= total or not 0 <= available <= total:
            raise ValueError("Inconsistent memory information")
        used = total - available
        return ToolResult(success=True, data={
            "total_bytes": total,
            "free_bytes": free,
            "available_bytes": available,
            "used_bytes": used,
            "used_percent": round(used / total * 100, 2),
        })
