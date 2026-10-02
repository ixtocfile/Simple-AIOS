"""Exercise policy decisions without executing tools or using an LLM."""

from unittest.mock import Mock

import pytest

from aios.policy import PolicyDecision, PolicyEngine
from aios.process_list import ProcessListTool
from aios.system_disk import SystemDiskTool
from aios.system_info import SystemInfoTool
from aios.system_memory import SystemMemoryTool
from aios.systemd_list import SystemdListTool
from aios.systemd_restart import SystemdRestartTool
from aios.systemd_status import SystemdStatusTool
from aios.tools import RiskLevel, Tool, ToolRegistry


class StubTool(Tool):
    name = "test.tool"
    description = "An in-memory tool that must not run during policy evaluation."

    def validate_arguments(self, arguments):
        raise AssertionError("Policy must not validate tool arguments")

    def _execute(self, arguments):
        raise AssertionError("Policy must not execute tools")


@pytest.fixture
def registered_tool(monkeypatch):
    registry = ToolRegistry()
    tool = StubTool()
    registry.register(tool)
    blocked = Mock(side_effect=AssertionError("Policy must only read metadata"))
    for method in ("execute", "validate_arguments", "_execute"):
        monkeypatch.setattr(tool, method, blocked)
    monkeypatch.setattr(registry, "execute", blocked)
    monkeypatch.setattr("builtins.input", blocked)
    yield registry, tool
    blocked.assert_not_called()


@pytest.mark.parametrize(("risk_level", "expected"), [
    (RiskLevel.READ, PolicyDecision.ALLOW),
    (RiskLevel.CONFIRM, PolicyDecision.CONFIRM),
    (RiskLevel.DENY, PolicyDecision.DENY),
])
def test_decisions_use_registered_risk_without_execution_or_confirmation(
    registered_tool, risk_level, expected, caplog,
):
    registry, tool = registered_tool
    tool.risk_level = risk_level
    policy = PolicyEngine(registry)

    assert policy.evaluate(tool.name) is expected
    assert policy.evaluate(tool.name) is expected
    assert tool.risk_level is risk_level
    assert registry.list_tools() == (tool,)
    assert not caplog.records


def test_tool_without_explicit_risk_is_denied(registered_tool):
    registry, tool = registered_tool
    assert PolicyEngine(registry).evaluate(tool.name) is PolicyDecision.DENY


@pytest.mark.parametrize("name", [
    "test.unknown", "test.tool ", "TEST.TOOL", "", None, [],
    {"name": "test.tool", "risk_level": "READ", "confirmed": True}, 42,
])
def test_unknown_or_invalid_names_are_denied(registered_tool, name, caplog):
    registry, tool = registered_tool
    tool.risk_level = RiskLevel.READ

    assert PolicyEngine(registry).evaluate(name) is PolicyDecision.DENY
    assert not caplog.records


@pytest.mark.parametrize("risk_level", [
    None, "READ", "CONFIRM", "DENY", PolicyDecision.ALLOW, True, [], {},
])
def test_invalid_risk_after_registration_is_denied(registered_tool, risk_level):
    registry, tool = registered_tool
    tool.risk_level = risk_level

    assert PolicyEngine(registry).evaluate(tool.name) is PolicyDecision.DENY


def test_decisions_are_refreshed_from_the_same_registry(registered_tool):
    registry, tool = registered_tool
    policy = PolicyEngine(registry)
    other_policy = PolicyEngine(ToolRegistry())
    assert policy.evaluate("test.later") is PolicyDecision.DENY

    later = StubTool()
    later.name = "test.later"
    later.risk_level = RiskLevel.READ
    registry.register(later)
    assert policy.evaluate(later.name) is PolicyDecision.ALLOW
    assert other_policy.evaluate(later.name) is PolicyDecision.DENY

    tool.risk_level = RiskLevel.READ
    assert policy.evaluate(tool.name) is PolicyDecision.ALLOW
    tool.risk_level = RiskLevel.CONFIRM
    assert policy.evaluate(tool.name) is PolicyDecision.CONFIRM
    tool.risk_level = RiskLevel.DENY
    assert policy.evaluate(tool.name) is PolicyDecision.DENY


@pytest.mark.parametrize(("tool_class", "decision"), [
    (SystemInfoTool, PolicyDecision.ALLOW), (SystemMemoryTool, PolicyDecision.ALLOW),
    (SystemDiskTool, PolicyDecision.ALLOW), (ProcessListTool, PolicyDecision.ALLOW),
    (SystemdStatusTool, PolicyDecision.ALLOW), (SystemdListTool, PolicyDecision.ALLOW),
    (SystemdRestartTool, PolicyDecision.CONFIRM),
])
def test_existing_tools_receive_their_policy_without_running(tool_class, decision, monkeypatch):
    registry = ToolRegistry()
    tool = tool_class()
    blocked = Mock(side_effect=AssertionError("Tool must not run"))
    monkeypatch.setattr(tool, "execute", blocked)
    monkeypatch.setattr(tool, "validate_arguments", blocked)
    monkeypatch.setattr(tool, "_execute", blocked)
    registry.register(tool)

    assert PolicyEngine(registry).evaluate(tool.name) is decision
    blocked.assert_not_called()


@pytest.mark.parametrize("registry", [None, {}, StubTool()])
def test_engine_requires_a_tool_registry(registry):
    with pytest.raises(TypeError, match="ToolRegistry"):
        PolicyEngine(registry)
