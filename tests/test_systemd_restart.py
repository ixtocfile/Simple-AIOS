"""Test restart validation and authorization without touching real services."""

from dataclasses import asdict
import json
import subprocess
from unittest.mock import Mock

import pytest

from aios.systemd_restart import SystemdRestartTool
from aios.tools import ToolRegistry, ToolResult


@pytest.fixture
def systemctl(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess(["systemctl"], 0))
    monkeypatch.setattr("aios.systemd_restart.subprocess.run", run)
    return run


def test_one_fixed_command_runs_only_after_authorization(systemctl, caplog):
    registry = ToolRegistry()
    registry.register(SystemdRestartTool())
    events = []
    arguments = {"service": "demo.service"}

    def authorize(validated):
        assert validated == arguments
        systemctl.assert_not_called()
        events.append("authorize")
        # The authorization preview is a copy, not the executed target.
        validated["service"] = "other.service"
        return True

    def run(*args, **kwargs):
        events.append("restart")
        return subprocess.CompletedProcess(args[0], 0)

    systemctl.side_effect = run
    result = registry.execute("systemd.restart", arguments, authorize=authorize)

    assert result == ToolResult(success=True, data={"service": "demo.service", "restarted": True})
    assert events == ["authorize", "restart"]
    assert arguments == {"service": "demo.service"}
    systemctl.assert_called_once_with(
        [
            "systemctl", "--system", "--no-pager", "--no-ask-password",
            "restart", "--", "demo.service",
        ],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        shell=False, check=True, timeout=30,
    )
    assert json.loads(json.dumps(asdict(result), allow_nan=False)) == asdict(result)
    assert not caplog.records


@pytest.mark.parametrize("service", [
    "systemd-journald.service", "openvpn-server@server.service",
    "worker@node:1.service", "Example_v2.3.service", "a" * 247 + ".service",
])
def test_explicit_service_name_is_one_literal_argument(systemctl, service):
    result = SystemdRestartTool().execute({"service": service}, authorize=lambda _: True)

    assert result == ToolResult(success=True, data={"service": service, "restarted": True})
    assert systemctl.call_count == 1
    assert systemctl.call_args.args[0][-2:] == ["--", service]


@pytest.mark.parametrize("arguments", [
    None, [], {}, {"service": None}, {"service": True}, {"service": 42},
    {"service": ["demo.service"]}, {1: "demo.service"},
    {"service": "demo.service", "confirmed": True},
    {"service": "demo.service", "risk_level": "READ"},
    {"service": "demo.service", "action": "stop"},
])
def test_invalid_arguments_never_authorize_or_execute(systemctl, arguments):
    authorize = Mock(return_value=True)

    assert SystemdRestartTool().execute(arguments, authorize=authorize) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    authorize.assert_not_called()
    systemctl.assert_not_called()


@pytest.mark.parametrize("service", [
    "", "demo", "demo.socket", "reboot.target", ".service", "demo@.service",
    "demo@@prod.service", " demo.service", "demo.service\n", "demo\t.service",
    "-demo.service", "--all", "*.service", "demo?.service", "demo[ab].service",
    "/etc/systemd/system/demo.service", "../demo.service", "demo.service;id",
    "$(id).service", "`id`.service", "demo.service other.service",
    r"demo\x2dfoo.service", "demo\x00.service", "café.service", "a" * 248 + ".service",
])
def test_ambiguous_or_unsafe_names_fail_before_confirmation(systemctl, service):
    authorize = Mock(return_value=True)

    assert SystemdRestartTool().execute({"service": service}, authorize=authorize) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    authorize.assert_not_called()
    systemctl.assert_not_called()


@pytest.mark.parametrize("use_registry", [False, True])
def test_authorization_is_required_even_for_direct_python_calls(systemctl, use_registry):
    tool = SystemdRestartTool()
    arguments = {"service": "demo.service"}
    registry = ToolRegistry()
    registry.register(tool)

    result = registry.execute(tool.name, arguments) if use_registry else tool.execute(arguments)

    assert result == ToolResult(success=False, error="Tool execution denied")
    systemctl.assert_not_called()


@pytest.mark.parametrize("answer", [False, None, 1, "oui"])
def test_only_boolean_true_from_authorization_allows_restart(systemctl, answer):
    authorize = Mock(return_value=answer)

    assert SystemdRestartTool().execute({"service": "demo.service"}, authorize=authorize) == ToolResult(
        success=False, error="Tool execution denied",
    )
    authorize.assert_called_once_with({"service": "demo.service"})
    systemctl.assert_not_called()


def test_authorization_error_does_not_restart_or_leak_details(systemctl, caplog, capsys):
    result = SystemdRestartTool().execute(
        {"service": "demo.service"},
        authorize=Mock(side_effect=RuntimeError("private authorization detail")),
    )

    assert result == ToolResult(success=False, error="Tool authorization failed")
    systemctl.assert_not_called()
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(("error", "message"), [
    (FileNotFoundError("private missing binary"), "Tool execution failed"),
    (PermissionError("private permission detail"), "Tool execution failed"),
    (subprocess.CalledProcessError(1, ["systemctl"], stderr="private masked service"),
     "Tool execution failed"),
    (subprocess.CalledProcessError(5, ["systemctl"], stderr="private missing unit"),
     "Tool execution failed"),
    (subprocess.TimeoutExpired(["systemctl"], 30, output="private partial output"),
     "Service restart timed out; outcome unknown"),
])
def test_process_failures_are_safe_without_retry_or_fallback(systemctl, error, message, caplog, capsys):
    systemctl.side_effect = error

    result = SystemdRestartTool().execute({"service": "demo.service"}, authorize=lambda _: True)

    assert result == ToolResult(success=False, error=message)
    assert systemctl.call_count == 1
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


def test_authorization_is_not_remembered_by_the_tool(systemctl):
    tool = SystemdRestartTool()
    arguments = {"service": "demo.service"}
    assert tool.execute(arguments, authorize=lambda _: True).success
    assert tool.execute(arguments) == ToolResult(success=False, error="Tool execution denied")
    assert tool.execute(arguments, authorize=lambda _: False) == ToolResult(
        success=False, error="Tool execution denied",
    )
    assert systemctl.call_count == 1
