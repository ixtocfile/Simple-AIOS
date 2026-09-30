"""Test memory readings using simulated proc data and no real LLM."""

from dataclasses import asdict
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from aios.system_memory import SystemMemoryTool
from aios.tools import ToolRegistry, ToolResult


def meminfo(total=8192, free=1024, available=3072):
    return (
        f"MemFree:\t{free} kB\nMemTotal:   {total} kB\n"
        f"MemAvailable: {available} kB\nCached: 2048 kB\nHugePages_Total: 0\n"
    )


@pytest.fixture
def reader(monkeypatch):
    source = Mock(return_value=meminfo())

    def read_text(path, *, encoding):
        return source(path, encoding=encoding)

    monkeypatch.setattr("aios.system_memory.Path.read_text", read_text)
    return source


def test_registry_returns_ram_in_bytes_without_external_commands(reader, monkeypatch, caplog):
    blocked = Mock(side_effect=AssertionError("External command attempted"))
    monkeypatch.setattr("os.system", blocked)
    monkeypatch.setattr("os.popen", blocked)
    monkeypatch.setattr("subprocess.Popen", blocked)
    registry = ToolRegistry()
    registry.register(SystemMemoryTool())
    reader.assert_not_called()

    result = registry.execute("system.memory", {})

    assert result == ToolResult(success=True, data={
        "total_bytes": 8388608,
        "free_bytes": 1048576,
        "available_bytes": 3145728,
        "used_bytes": 5242880,
        "used_percent": 62.5,
    })
    assert json.loads(json.dumps(asdict(result), allow_nan=False)) == asdict(result)
    reader.assert_called_once_with(Path("/proc/meminfo"), encoding="ascii")
    blocked.assert_not_called()
    assert not caplog.records


@pytest.mark.parametrize("arguments", [None, [], {"unexpected": True}, {"path": "/other"}])
def test_arguments_are_rejected_before_reading_memory(reader, arguments):
    assert SystemMemoryTool().execute(arguments) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    reader.assert_not_called()


@pytest.mark.parametrize(("total", "free", "available", "percent"), [
    (8192, 0, 0, 100.0),
    (8192, 8192, 8192, 0.0),
    (3, 1, 2, 33.33),
    (8192, 2048, 1024, 87.5),
])
def test_usage_boundaries_rounding_and_available_below_free(
    reader, total, free, available, percent,
):
    reader.return_value = meminfo(total, free, available)

    result = SystemMemoryTool().execute({})

    assert result.success
    assert result.data["used_bytes"] == (total - available) * 1024
    assert result.data["used_percent"] == percent


@pytest.mark.parametrize("missing", ["MemTotal", "MemFree", "MemAvailable"])
def test_missing_required_fields_fail_without_partial_data(reader, missing):
    reader.return_value = "\n".join(
        line for line in meminfo().splitlines() if not line.startswith(missing + ":")
    )
    assert SystemMemoryTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )


@pytest.mark.parametrize("value", [
    "-1 kB", "1.5 kB", "nan kB", "1 MB", "1", "", "1 kB extra",
])
def test_malformed_numbers_or_units_fail(reader, value):
    reader.return_value = meminfo().replace("3072 kB", value)
    assert SystemMemoryTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )


@pytest.mark.parametrize("contents", [
    "", meminfo() + "MemTotal: 8192 kB\n", meminfo(total=0),
    meminfo(free=8193), meminfo(available=8193),
])
def test_empty_duplicate_or_inconsistent_data_fails(reader, contents):
    reader.return_value = contents
    assert SystemMemoryTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )


@pytest.mark.parametrize("error", [
    FileNotFoundError("secret missing path"),
    PermissionError("secret permission detail"),
])
def test_read_errors_have_no_sensitive_details(reader, error, caplog):
    reader.side_effect = error
    assert SystemMemoryTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert not caplog.records


def test_memory_is_read_again_on_every_execution(reader):
    reader.side_effect = [meminfo(available=3072), meminfo(available=4096)]
    tool = SystemMemoryTool()

    first = tool.execute({})
    second = tool.execute({})

    assert first.success and second.success
    assert first.data["available_bytes"] == 3145728
    assert second.data["available_bytes"] == 4194304
    assert first.data["used_percent"] == 62.5
    assert second.data["used_percent"] == 50.0
    assert reader.call_count == 2
