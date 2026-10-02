"""Read a bounded list of service units known to the local system manager."""

import os
import re
import subprocess

from aios.tools import RiskLevel, Tool, ToolResult


class SystemdListTool(Tool):
    name = "systemd.list"
    description = "List known system services and their states, with a bounded result count."
    risk_level = RiskLevel.READ

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() - {"limit"}:
            raise ValueError("Only limit is accepted")
        limit = arguments.get("limit", 20)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        arguments["limit"] = limit

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        completed = subprocess.run(
            [
                "systemctl", "--system", "--no-pager", "--no-ask-password",
                "--no-legend", "--plain", "--full", "list-units", "--type=service", "--all",
            ],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", shell=False, check=True, timeout=5,
            env={**os.environ, "LC_ALL": "C", "SYSTEMD_COLORS": "0", "SYSTEMD_URLIFY": "0"},
        )
        services = {}
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            # Only the first four columns are needed; jobs and descriptions are ignored.
            fields = line.split(maxsplit=4)
            if len(fields) < 4:
                raise ValueError("Incomplete service row")
            service, load, active, sub = fields[:4]
            if (
                len(service) > 255 or service in services
                or re.fullmatch(r"(?:[A-Za-z0-9:_.@-]|\\x[0-9a-fA-F]{2})+\.service", service) is None
                or any(re.fullmatch(r"[a-z][a-z0-9-]*", state) is None for state in (load, active, sub))
            ):
                raise ValueError("Invalid service row")
            services[service] = {
                "service": service, "load_state": load, "active_state": active, "sub_state": sub,
            }
        names = sorted(services)
        limit = arguments["limit"]
        return ToolResult(success=True, data={
            "services": [services[name] for name in names[:limit]],
            "truncated": len(names) > limit,
        })
