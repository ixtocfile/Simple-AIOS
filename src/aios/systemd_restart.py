"""Restart one explicitly authorized system service with a fixed command."""

from collections.abc import Callable
import re
import subprocess

from aios.tools import RiskLevel, Tool, ToolResult


_SERVICE_NAME = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.:-]*(?:@[A-Za-z0-9][A-Za-z0-9_.:-]*)?\.service"
)


class SystemdRestartTool(Tool):
    name = "systemd.restart"
    description = "Restart one named system .service unit after explicit confirmation."
    risk_level = RiskLevel.CONFIRM

    def execute(
        self, arguments: dict[str, object], *,
        authorize: Callable[[dict[str, object]], bool] | None = None,
    ) -> ToolResult:
        # A missing authorization callback must never allow a real mutation.
        if authorize is None:
            authorize = lambda _: False
        return super().execute(arguments, authorize=authorize)

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
        try:
            subprocess.run(
                [
                    "systemctl", "--system", "--no-pager", "--no-ask-password",
                    "restart", "--", service,
                ],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                shell=False, check=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            # Killing systemctl does not establish the outcome of the systemd job.
            return ToolResult(success=False, error="Service restart timed out; outcome unknown")
        return ToolResult(success=True, data={"service": service, "restarted": True})
