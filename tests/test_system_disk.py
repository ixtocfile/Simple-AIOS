"""Test disk statistics and read-only behavior without a real LLM."""

from dataclasses import asdict
import json
from unittest.mock import Mock

import pytest

from aios.system_disk import SystemDiskTool
from aios.tools import ToolRegistry, ToolResult


@pytest.fixture
def usage(monkeypatch):
    reader = Mock(return_value=(1024, 640, 320))
    monkeypatch.setattr("aios.system_disk.disk_usage", reader)
    return reader


def test_registry_returns_root_usage_without_commands_or_argument_mutation(
    usage, monkeypatch, caplog,
):
    blocked = Mock(side_effect=AssertionError("External command attempted"))
    monkeypatch.setattr("os.system", blocked)
    monkeypatch.setattr("os.popen", blocked)
    monkeypatch.setattr("subprocess.Popen", blocked)
    registry = ToolRegistry()
    registry.register(SystemDiskTool())
    usage.assert_not_called()
    arguments = {}

    result = registry.execute("system.disk", arguments)

    assert result == ToolResult(success=True, data={
        "path": "/", "total_bytes": 1024, "used_bytes": 640,
        "free_bytes": 320, "used_percent": 62.5,
    })
    assert json.loads(json.dumps(asdict(result), allow_nan=False)) == asdict(result)
    assert arguments == {}
    usage.assert_called_once_with("/")
    blocked.assert_not_called()
    assert not caplog.records


@pytest.mark.parametrize("path", ["/var", "/mnt/volume avec espaces/file.txt"])
def test_custom_path_is_used_as_given(usage, path):
    arguments = {"path": path}

    result = SystemDiskTool().execute(arguments)

    assert result.success
    assert result.data["path"] == path
    assert arguments == {"path": path}
    usage.assert_called_once_with(path)


@pytest.mark.parametrize("arguments", [
    None, [], {"other": True}, {"path": None}, {"path": 42}, {"path": ""},
    {"path": "relative"}, {"path": "~/data"}, {"path": "/bad\0name"},
    {"path": "/", "other": True},
])
def test_invalid_arguments_are_rejected_before_disk_access(usage, arguments):
    assert SystemDiskTool().execute(arguments) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    usage.assert_not_called()


@pytest.mark.parametrize(("stats", "percent"), [
    ((0, 0, 0), 0.0),
    ((10, 0, 10), 0.0),
    ((10, 10, 0), 100.0),
    ((3, 1, 2), 33.33),
])
def test_capacity_boundaries_and_percentage_rounding(usage, stats, percent):
    usage.return_value = stats

    result = SystemDiskTool().execute({})

    assert result.success
    assert result.data["used_percent"] == percent
    assert result.data["total_bytes"] == stats[0]
    assert result.data["used_bytes"] == stats[1]
    assert result.data["free_bytes"] == stats[2]


@pytest.mark.parametrize("stats", [
    (-1, 0, 0), (10, -1, 0), (10, 0, -1), (10, 8, 3),
    (10.0, 3, 7), (10, True, 9),
])
def test_invalid_disk_statistics_fail_without_partial_data(usage, stats):
    usage.return_value = stats
    assert SystemDiskTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )


@pytest.mark.parametrize("error", [
    FileNotFoundError("secret missing path"),
    PermissionError("secret permission detail"),
    NotADirectoryError("secret invalid path component"),
])
def test_disk_access_errors_do_not_expose_sensitive_details(usage, error, caplog):
    usage.side_effect = error
    assert SystemDiskTool().execute({"path": "/private-path"}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert not caplog.records


def test_every_execution_refreshes_disk_statistics(usage):
    usage.side_effect = [(100, 50, 40), (100, 60, 30)]
    tool = SystemDiskTool()

    first = tool.execute({})
    second = tool.execute({})

    assert first.success and second.success
    assert first.data["used_bytes"] == 50
    assert second.data["used_bytes"] == 60
    assert usage.call_count == 2


@pytest.mark.parametrize("target", ["directory", "file"])
def test_real_filesystem_query_leaves_files_unchanged(tmp_path, target):
    marker = tmp_path / "existing file.txt"
    marker.write_bytes(b"unchanged content")
    before = marker.stat()
    path = tmp_path if target == "directory" else marker

    result = SystemDiskTool().execute({"path": str(path)})

    assert result.success
    assert result.data["path"] == str(path)
    assert result.data["total_bytes"] > 0
    after = marker.stat()
    assert (after.st_size, after.st_mtime_ns, after.st_mode) == (
        before.st_size, before.st_mtime_ns, before.st_mode,
    )
    assert marker.read_bytes() == b"unchanged content"
    assert list(tmp_path.iterdir()) == [marker]
