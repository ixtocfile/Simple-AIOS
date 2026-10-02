"""Test bounded service listing without systemd or a real LLM."""

from dataclasses import asdict
import json
import os
import subprocess
from unittest.mock import Mock

import pytest

from aios.systemd_list import SystemdListTool
from aios.tools import ToolRegistry, ToolResult


OUTPUT = (
    "  zeta.service loaded inactive dead Private description\n"
    "  ssh.service loaded active running OpenSSH server\n"
    "  broken.service loaded failed failed Another description\n"
)


@pytest.fixture
def systemctl(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess(["systemctl"], 0, stdout=OUTPUT))
    monkeypatch.setattr("aios.systemd_list.subprocess.run", run)
    return run


def test_listing_uses_one_fixed_read_only_command_and_sorted_structured_data(
    systemctl, monkeypatch, caplog,
):
    monkeypatch.setenv("AIOS_LIST_TEST", "preserved")
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    monkeypatch.setenv("SYSTEMD_COLORS", "1")
    monkeypatch.setenv("SYSTEMD_URLIFY", "1")
    registry = ToolRegistry()
    registry.register(SystemdListTool())
    systemctl.assert_not_called()

    result = registry.execute("systemd.list", {})

    assert result == ToolResult(success=True, data={
        "services": [
            {"service": "broken.service", "load_state": "loaded", "active_state": "failed", "sub_state": "failed"},
            {"service": "ssh.service", "load_state": "loaded", "active_state": "active", "sub_state": "running"},
            {"service": "zeta.service", "load_state": "loaded", "active_state": "inactive", "sub_state": "dead"},
        ],
        "truncated": False,
    })
    assert systemctl.call_count == 1
    assert systemctl.call_args.args == ([
        "systemctl", "--system", "--no-pager", "--no-ask-password",
        "--no-legend", "--plain", "--full", "list-units", "--type=service", "--all",
    ],)
    options = systemctl.call_args.kwargs.copy()
    environment = options.pop("env")
    assert {key: environment[key] for key in ("LC_ALL", "SYSTEMD_COLORS", "SYSTEMD_URLIFY")} == {
        "LC_ALL": "C", "SYSTEMD_COLORS": "0", "SYSTEMD_URLIFY": "0",
    }
    assert environment["AIOS_LIST_TEST"] == "preserved"
    assert os.environ["LC_ALL"] == "fr_FR.UTF-8"
    assert options == {
        "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
        "text": True, "encoding": "utf-8", "shell": False, "check": True, "timeout": 5,
    }
    assert json.loads(json.dumps(asdict(result), allow_nan=False)) == asdict(result)
    assert not caplog.records


@pytest.mark.parametrize(("arguments", "count", "expected_count"), [
    ({}, 0, 0), ({}, 20, 20), ({}, 21, 20), ({"limit": 1}, 3, 1), ({"limit": 100}, 101, 100),
])
def test_result_limit_is_applied_after_sorting_and_marks_truncation(
    systemctl, arguments, count, expected_count,
):
    systemctl.return_value.stdout = "\n \t\n" + "".join(
        f"svc{index:03}.service loaded active running Service {index}\n"
        for index in reversed(range(count))
    )
    original = arguments.copy()

    result = SystemdListTool().execute(arguments)

    assert result.success
    assert [item["service"] for item in result.data["services"]] == [
        f"svc{index:03}.service" for index in range(expected_count)
    ]
    assert result.data["truncated"] is (count > expected_count)
    assert arguments == original
    assert systemctl.call_count == 1


@pytest.mark.parametrize("arguments", [
    None, [], {"limit": None}, {"limit": True}, {"limit": 0}, {"limit": -1},
    {"limit": 101}, {"limit": 1.5}, {"limit": "20"}, {"limit": "1;reboot"},
    {"service": "ssh.service"}, {"limit": 1, "action": "restart"},
])
def test_invalid_arguments_are_rejected_before_starting_a_process(systemctl, arguments):
    assert SystemdListTool().execute(arguments) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    systemctl.assert_not_called()


@pytest.mark.parametrize(("service", "load", "active", "sub"), [
    ("masked.service", "masked", "inactive", "dead"),
    ("missing.service", "not-found", "inactive", "dead"),
    ("worker@node:1.service", "loaded", "activating", "start-pre"),
    (r"worker@name\x2dtest.service", "loaded", "active", "running"),
])
def test_states_instances_and_escaped_names_are_preserved_without_job_or_description(
    systemctl, service, load, active, sub,
):
    systemctl.return_value.stdout = f"{service}\t{load}  {active} {sub} start private-description\n"

    assert SystemdListTool().execute({}) == ToolResult(success=True, data={
        "services": [{"service": service, "load_state": load, "active_state": active, "sub_state": sub}],
        "truncated": False,
    })


@pytest.mark.parametrize("bad_row", [
    "incomplete.service loaded active",
    "wrong.socket loaded active running",
    "ssh.service loaded active running Duplicate unit",
    "UNIT LOAD ACTIVE SUB DESCRIPTION",
    "\x1b[31mcolor.service loaded active running",
    "bad.service loaded active! running",
    "../path.service loaded active running",
    r"bad\xZZ.service loaded active running",
    "a" * 248 + ".service loaded active running",
    "systemd is not available here",
])
def test_malformed_rows_fail_even_beyond_the_limit_without_partial_results(
    systemctl, bad_row, caplog, capsys,
):
    systemctl.return_value.stdout = OUTPUT + bad_row + "\n"

    assert SystemdListTool().execute({"limit": 1}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert systemctl.call_count == 1
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("error", [
    FileNotFoundError("private binary path"),
    PermissionError("private permission detail"),
    subprocess.TimeoutExpired(["systemctl"], 5, output="private partial output"),
    subprocess.CalledProcessError(1, ["systemctl"], output=OUTPUT, stderr="private bus error"),
])
def test_process_errors_are_safe_without_retry_or_fallback(systemctl, error, caplog, capsys):
    systemctl.side_effect = error

    assert SystemdListTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert systemctl.call_count == 1
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


def test_authorization_denial_prevents_service_listing(systemctl):
    result = SystemdListTool().execute({}, authorize=lambda _: False)

    assert result == ToolResult(success=False, error="Tool execution denied")
    systemctl.assert_not_called()


def test_each_call_refreshes_the_list(systemctl):
    tool = SystemdListTool()
    first = tool.execute({})
    systemctl.return_value.stdout = ""
    second = tool.execute({})

    assert first.success and len(first.data["services"]) == 3
    assert second == ToolResult(success=True, data={"services": [], "truncated": False})
    assert systemctl.call_count == 2
