"""Exercise systemd.status without systemd, real services or an LLM."""

from dataclasses import asdict
import json
import subprocess
from unittest.mock import Mock

import pytest

from aios.systemd_status import SystemdStatusTool
from aios.tools import ToolRegistry, ToolResult


OUTPUT = "LoadState=loaded\nActiveState=active\nSubState=running\n"


@pytest.fixture
def systemctl(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess(["systemctl"], 0, stdout=OUTPUT))
    monkeypatch.setattr("aios.systemd_status.subprocess.run", run)
    return run


def test_status_uses_a_fixed_read_only_command_and_returns_structured_data(systemctl, caplog):
    registry = ToolRegistry()
    registry.register(SystemdStatusTool())
    systemctl.assert_not_called()

    result = registry.execute("systemd.status", {"service": "ssh.service"})

    assert result == ToolResult(success=True, data={
        "service": "ssh.service", "load_state": "loaded",
        "active_state": "active", "sub_state": "running",
    })
    systemctl.assert_called_once_with(
        [
            "systemctl", "--system", "--no-pager", "--no-ask-password", "show",
            "--property=LoadState,ActiveState,SubState", "--", "ssh.service",
        ],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", shell=False, check=True, timeout=5,
    )
    assert json.loads(json.dumps(asdict(result), allow_nan=False)) == asdict(result)
    assert not caplog.records


@pytest.mark.parametrize("service", [
    "systemd-journald.service", "openvpn-server@server.service",
    "worker@node:1.service", "Example_v2.3.service", "a" * 247 + ".service",
])
def test_explicit_service_names_are_passed_as_one_literal_argument(systemctl, service):
    arguments = {"service": service}

    result = SystemdStatusTool().execute(arguments)

    assert result.success
    assert result.data["service"] == service
    assert systemctl.call_args.args[0][-2:] == ["--", service]
    assert arguments == {"service": service}


@pytest.mark.parametrize("arguments", [
    None, [], {}, {"service": None}, {"service": True}, {"service": ["ssh.service"]},
    {"service": "ssh.service", "action": "restart"},
])
def test_invalid_arguments_never_start_a_process(systemctl, arguments):
    assert SystemdStatusTool().execute(arguments) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    systemctl.assert_not_called()


@pytest.mark.parametrize("service", [
    "", "ssh", "ssh.socket", ".service", "ssh@.service", "ssh@@prod.service",
    " ssh.service", "ssh.service\n", "-ssh.service", "ssh*.service", "ssh?.service",
    "ssh[ab].service", "/etc/systemd/system/ssh.service", "../ssh.service",
    "ssh.service;id", "$(id).service", "ssh.service other.service",
    r"ssh\x2dfoo.service", "ssh\x00.service", "café.service", "a" * 248 + ".service",
])
def test_ambiguous_names_options_paths_and_shell_syntax_are_rejected(systemctl, service):
    assert SystemdStatusTool().execute({"service": service}) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    systemctl.assert_not_called()


@pytest.mark.parametrize(("load", "active", "sub"), [
    ("loaded", "inactive", "dead"),
    ("loaded", "failed", "failed"),
    ("masked", "inactive", "dead"),
    ("loaded", "activating", "start-pre"),
])
def test_inactive_failed_masked_and_transition_states_are_successful_reads(
    systemctl, load, active, sub,
):
    # Property order is not part of systemctl's interface.
    systemctl.return_value.stdout = f"SubState={sub}\n\nLoadState={load}\nActiveState={active}\n"

    assert SystemdStatusTool().execute({"service": "ssh.service"}) == ToolResult(
        success=True, data={
            "service": "ssh.service", "load_state": load, "active_state": active, "sub_state": sub,
        },
    )


@pytest.mark.parametrize("output", [
    "", "LoadState=loaded\nActiveState=active\n",
    OUTPUT + "ActiveState=inactive\n",
    OUTPUT + "Environment=token=secret-value\n",
    OUTPUT.replace("ActiveState=active", "ActiveState="),
    OUTPUT.replace("SubState=running", "SubState=running\x1b[2J"),
    OUTPUT.replace("LoadState=loaded", "LoadState=not-found"),
    "systemd is not available\n",
])
def test_missing_services_or_malformed_properties_fail_without_partial_data(
    systemctl, output, caplog, capsys,
):
    systemctl.return_value.stdout = output

    assert SystemdStatusTool().execute({"service": "ssh.service"}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert systemctl.call_count == 1
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("error", [
    FileNotFoundError("private missing binary"),
    PermissionError("private access detail"),
    subprocess.TimeoutExpired(["systemctl"], 5, output="private partial output"),
    subprocess.CalledProcessError(1, ["systemctl"], output=OUTPUT, stderr="private bus error"),
    subprocess.CalledProcessError(4, ["systemctl"], stderr="private missing unit"),
])
def test_process_errors_are_safe_and_never_retry_or_use_a_fallback(
    systemctl, error, caplog, capsys,
):
    systemctl.side_effect = error

    assert SystemdStatusTool().execute({"service": "ssh.service"}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert systemctl.call_count == 1
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


def test_authorization_denial_prevents_systemctl_execution(systemctl):
    result = SystemdStatusTool().execute({"service": "ssh.service"}, authorize=lambda _: False)

    assert result == ToolResult(success=False, error="Tool execution denied")
    systemctl.assert_not_called()


def test_each_call_reads_the_current_service_state(systemctl):
    tool = SystemdStatusTool()
    first = tool.execute({"service": "ssh.service"})
    systemctl.return_value.stdout = OUTPUT.replace("active\n", "inactive\n").replace("running", "dead")
    second = tool.execute({"service": "ssh.service"})

    assert first.success and second.success
    assert first.data["active_state"] == "active"
    assert second.data["active_state"] == "inactive"
    assert systemctl.call_count == 2
