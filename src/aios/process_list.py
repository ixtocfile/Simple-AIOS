"""Read a bounded list of Linux processes without running commands."""

from pathlib import Path

from aios.tools import Tool, ToolResult


class ProcessListTool(Tool):
    name = "process.list"
    description = "Read process IDs and short names, with a bounded result count."

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() - {"limit"}:
            raise ValueError("Only limit is accepted")
        limit = arguments.get("limit", 20)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        arguments["limit"] = limit

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        entries = sorted(
            (entry for entry in Path("/proc").iterdir() if entry.name.isdecimal()),
            key=lambda entry: int(entry.name),
        )
        processes = []
        for entry in entries:
            try:
                comm = (entry / "comm").read_bytes()
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                # Processes can exit or be inaccessible between listing and reading.
                continue
            processes.append({
                "pid": int(entry.name),
                "name": comm.removesuffix(b"\n").decode("utf-8", errors="replace"),
            })
            if len(processes) == arguments["limit"]:
                break
        return ToolResult(success=True, data={"processes": processes})
