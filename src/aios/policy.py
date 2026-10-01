"""Decide tool authorization from trusted registry metadata, without execution."""

from enum import Enum

from aios.tools import RiskLevel, ToolRegistry


class PolicyDecision(Enum):
    ALLOW = "ALLOW"
    CONFIRM = "CONFIRM"
    DENY = "DENY"


class PolicyEngine:
    def __init__(self, registry: ToolRegistry) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        self._registry = registry

    def evaluate(self, tool_name: str) -> PolicyDecision:
        """Read the current risk; never execute a tool or collect confirmation."""
        if not isinstance(tool_name, str):
            return PolicyDecision.DENY
        try:
            tool = self._registry.get(tool_name)
        except KeyError:
            return PolicyDecision.DENY

        risk_level = getattr(tool, "risk_level", RiskLevel.DENY)
        if risk_level is RiskLevel.READ:
            return PolicyDecision.ALLOW
        if risk_level is RiskLevel.CONFIRM:
            return PolicyDecision.CONFIRM
        return PolicyDecision.DENY
