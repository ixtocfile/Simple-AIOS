"""Read basic Linux system information without starting external commands."""

import math
import os
from pathlib import Path

from aios.tools import Tool, ToolResult


class SystemInfoTool(Tool):
    name = "system.info"
    description = "Read hostname, OS, kernel, architecture and uptime."

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments:
            raise ValueError("system.info does not accept arguments")

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        system = os.uname()
        uptime = float(Path("/proc/uptime").read_text(encoding="ascii").split()[0])
        if not math.isfinite(uptime) or uptime < 0:
            raise ValueError("Invalid system uptime")
        return ToolResult(success=True, data={
            "hostname": system.nodename,
            "os": system.sysname,
            "kernel": system.release,
            "architecture": system.machine,
            "uptime_seconds": uptime,
        })
