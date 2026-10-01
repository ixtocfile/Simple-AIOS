"""Read a single system service's state with a fixed systemctl command."""

import re
import subprocess

from aios.tools import RiskLevel, Tool, ToolResult


_SERVICE_NAME = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.:-]*(?:@[A-Za-z0-9][A-Za-z0-9_.:-]*)?\.service"
)
_PROPERTIES = {
    "LoadState": "load_state",
    "ActiveState": "active_state",
    "SubState": "sub_state",
}


class SystemdStatusTool(Tool):
    name = "systemd.status"
    description = "Read load, active and sub states of one named system .service unit."
    risk_level = RiskLevel.READ

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        if arguments.keys() != {"service"}:
            raise ValueError("Expected only service")
        service = arguments["service"]
        if (
            not isinstance(service, str) or len(service) > 255
            or _SERVICE_NAME.fullmatch(service) is None
        ):
            raise ValueError("Expected a simple, fully qualified .service name")

    def _execute(self, arguments: dict[str, object]) -> ToolResult:
        service = arguments["service"]
        completed = subprocess.run(
            [
                "systemctl", "--system", "--no-pager", "--no-ask-password", "show",
                "--property=" + ",".join(_PROPERTIES), "--", service,
            ],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", shell=False, check=True, timeout=5,
        )
        properties = {}
        for line in completed.stdout.splitlines():
            if not line:
                continue
            key, separator, value = line.partition("=")
            if (
                not separator or key not in _PROPERTIES or key in properties
                or re.fullmatch(r"[a-z][a-z0-9-]*", value) is None
            ):
                raise ValueError("Invalid systemctl properties")
            properties[key] = value
        if properties.keys() != _PROPERTIES.keys() or properties["LoadState"] == "not-found":
            raise ValueError("Missing service or properties")
        return ToolResult(success=True, data={
            "service": service,
            **{field: properties[key] for key, field in _PROPERTIES.items()},
        })
