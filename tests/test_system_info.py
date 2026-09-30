"""Test system.info with deterministic system data and no real LLM."""

from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from aios.system_info import SystemInfoTool
from aios.tools import ToolRegistry, ToolResult


@pytest.fixture
def sources(monkeypatch):
    uname = Mock(return_value=SimpleNamespace(
        sysname="Linux", nodename="test-host", release="6.8.0-test",
        machine="x86_64",
    ))
    reader = Mock(return_value="12345.67 99999.00\n")

    def read_text(path, *, encoding):
        return reader(path, encoding=encoding)

    monkeypatch.setattr("aios.system_info.os.uname", uname)
    monkeypatch.setattr("aios.system_info.Path.read_text", read_text)
    return uname, reader


def test_registry_returns_system_information_without_external_commands(
    sources, monkeypatch, caplog,
):
    blocked = Mock(side_effect=AssertionError("External command attempted"))
    monkeypatch.setattr("os.system", blocked)
    monkeypatch.setattr("os.popen", blocked)
    monkeypatch.setattr("subprocess.Popen", blocked)
    uname, reader = sources
    registry = ToolRegistry()
    registry.register(SystemInfoTool())
    uname.assert_not_called()
    reader.assert_not_called()

    result = registry.execute("system.info", {})

    assert result == ToolResult(success=True, data={
        "hostname": "test-host", "os": "Linux", "kernel": "6.8.0-test",
        "architecture": "x86_64", "uptime_seconds": 12345.67,
    })
    assert json.loads(json.dumps(asdict(result), allow_nan=False)) == asdict(result)
    uname.assert_called_once_with()
    reader.assert_called_once_with(Path("/proc/uptime"), encoding="ascii")
    blocked.assert_not_called()
    assert not caplog.records


@pytest.mark.parametrize("arguments", [None, [], {"unexpected": True}, {"path": "/other"}])
def test_arguments_are_rejected_before_accessing_system_data(sources, arguments):
    uname, reader = sources

    assert SystemInfoTool().execute(arguments) == ToolResult(
        success=False, error="Invalid tool arguments",
    )

    uname.assert_not_called()
    reader.assert_not_called()


@pytest.mark.parametrize("contents", [
    "", " \n", "invalid 0.00\n", "-1.00 0.00\n", "nan 0.00\n", "inf 0.00\n",
])
def test_invalid_uptime_produces_a_failed_result(sources, contents):
    _, reader = sources
    reader.return_value = contents

    assert SystemInfoTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )


def test_zero_uptime_is_valid(sources):
    _, reader = sources
    reader.return_value = "0.00 0.00\n"

    result = SystemInfoTool().execute({})

    assert result.success
    assert result.data["uptime_seconds"] == 0.0


@pytest.mark.parametrize(("source", "error"), [
    (0, OSError("secret uname error")),
    (1, FileNotFoundError("secret missing path")),
    (1, PermissionError("secret permission detail")),
])
def test_system_read_errors_have_no_partial_data_or_sensitive_details(
    sources, source, error, caplog,
):
    sources[source].side_effect = error

    assert SystemInfoTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert not caplog.records


def test_each_execution_reads_fresh_data(sources):
    uname, reader = sources
    reader.side_effect = ["1.25 5.00\n", "2.50 9.00\n"]
    tool = SystemInfoTool()

    first = tool.execute({})
    second = tool.execute({})

    assert first.success and second.success
    assert first.data["uptime_seconds"] == 1.25
    assert second.data["uptime_seconds"] == 2.50
    assert uname.call_count == reader.call_count == 2
