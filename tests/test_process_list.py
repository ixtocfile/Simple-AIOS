"""Test bounded process listing without a real LLM or real process lifecycle."""

from dataclasses import asdict
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from aios.process_list import ProcessListTool
from aios.tools import ToolRegistry, ToolResult


@pytest.fixture
def proc(monkeypatch):
    entries = Mock(return_value=[
        Path("/proc/10"), Path("/proc/self"), Path("/proc/2"),
        Path("/proc/uptime"), Path("/proc/thread-self"),
    ])
    reader = Mock(side_effect=[b"worker\n", b"python\n"])
    monkeypatch.setattr(Path, "iterdir", entries)
    monkeypatch.setattr(Path, "read_bytes", reader)
    return entries, reader


def test_registry_returns_structured_processes_without_commands_or_mutation(
    proc, monkeypatch, caplog,
):
    entries, reader = proc
    blocked = Mock(side_effect=AssertionError("External command attempted"))
    monkeypatch.setattr("os.system", blocked)
    monkeypatch.setattr("os.popen", blocked)
    monkeypatch.setattr("subprocess.Popen", blocked)
    registry = ToolRegistry()
    registry.register(ProcessListTool())
    entries.assert_not_called()
    reader.assert_not_called()
    arguments = {}

    result = registry.execute("process.list", arguments)

    assert result == ToolResult(success=True, data={"processes": [
        {"pid": 2, "name": "worker"}, {"pid": 10, "name": "python"},
    ]})
    assert json.loads(json.dumps(asdict(result), allow_nan=False)) == asdict(result)
    assert arguments == {}
    assert reader.call_count == 2
    blocked.assert_not_called()
    assert not caplog.records


@pytest.mark.parametrize(("arguments", "expected_count"), [
    ({}, 20), ({"limit": 1}, 1), ({"limit": 3}, 3), ({"limit": 100}, 100),
])
def test_results_and_reads_stop_at_limit(proc, arguments, expected_count):
    entries, reader = proc
    entries.return_value = [Path(f"/proc/{pid}") for pid in range(105, 0, -1)]
    reader.side_effect = None
    reader.return_value = b"worker\n"
    original = arguments.copy()

    result = ProcessListTool().execute(arguments)

    assert result.success
    assert [item["pid"] for item in result.data["processes"]] == list(
        range(1, expected_count + 1),
    )
    assert reader.call_count == expected_count
    assert arguments == original


@pytest.mark.parametrize("arguments", [
    None, [], {1: 2}, {"other": True}, {"limit": 2, "other": True},
    {"limit": None}, {"limit": "2"}, {"limit": 2.0}, {"limit": True},
    {"limit": False}, {"limit": 0}, {"limit": -1}, {"limit": 101},
])
def test_invalid_arguments_are_rejected_before_proc_access(proc, arguments):
    entries, reader = proc
    assert ProcessListTool().execute(arguments) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    entries.assert_not_called()
    reader.assert_not_called()


@pytest.mark.parametrize("error", [
    FileNotFoundError("secret exited process"),
    ProcessLookupError("secret vanished process"),
    PermissionError("secret access detail"),
])
def test_unavailable_process_is_skipped_and_does_not_consume_limit(proc, error, caplog):
    _, reader = proc
    reader.side_effect = [error, b"available\n"]

    result = ProcessListTool().execute({"limit": 1})

    assert result == ToolResult(success=True, data={
        "processes": [{"pid": 10, "name": "available"}],
    })
    assert reader.call_count == 2
    assert not caplog.records


@pytest.mark.parametrize("all_unavailable", [False, True])
def test_no_readable_processes_returns_an_empty_list(proc, all_unavailable):
    entries, reader = proc
    if all_unavailable:
        reader.side_effect = FileNotFoundError("process exited")
    else:
        entries.return_value = [Path("/proc/self"), Path("/proc/uptime")]

    assert ProcessListTool().execute({}) == ToolResult(
        success=True, data={"processes": []},
    )
    if not all_unavailable:
        reader.assert_not_called()


@pytest.mark.parametrize("error", [
    FileNotFoundError("secret proc path"), PermissionError("secret access detail"),
])
def test_cannot_enumerate_proc_returns_a_generic_error(proc, error, caplog):
    entries, reader = proc
    entries.side_effect = error

    assert ProcessListTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    reader.assert_not_called()
    assert not caplog.records


def test_unexpected_read_error_discards_partial_results(proc, caplog):
    _, reader = proc
    reader.side_effect = [b"worker\n", OSError("secret I/O detail")]

    assert ProcessListTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert not caplog.records


def test_every_execution_refreshes_processes(proc):
    entries, reader = proc
    entries.side_effect = [[Path("/proc/2")], [Path("/proc/10")]]
    tool = ProcessListTool()

    first = tool.execute({})
    second = tool.execute({})

    assert first == ToolResult(success=True, data={
        "processes": [{"pid": 2, "name": "worker"}],
    })
    assert second == ToolResult(success=True, data={
        "processes": [{"pid": 10, "name": "python"}],
    })


def test_only_comm_is_read_and_process_files_remain_unchanged(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    samples = [b" name (x) \n", b"line\nbreak\n", b"invalid\xff\n", b"\n"]
    originals = {}
    for pid, comm in enumerate(samples, start=1):
        directory = proc / str(pid)
        directory.mkdir()
        for name, content in {
            "comm": comm, "cmdline": b"private arguments", "environ": b"private env",
        }.items():
            path = directory / name
            path.write_bytes(content)
            originals[path] = (content, path.stat().st_mtime_ns)

    reads = []
    read_bytes = Path.read_bytes

    def read_comm(path):
        assert path.name == "comm"
        reads.append(path)
        return read_bytes(path)

    with monkeypatch.context() as patch:
        path_factory = Mock(return_value=proc)
        patch.setattr("aios.process_list.Path", path_factory)
        patch.setattr(Path, "read_bytes", read_comm)
        result = ProcessListTool().execute({})

    assert result == ToolResult(success=True, data={"processes": [
        {"pid": 1, "name": " name (x) "},
        {"pid": 2, "name": "line\nbreak"},
        {"pid": 3, "name": "invalid\ufffd"},
        {"pid": 4, "name": ""},
    ]})
    path_factory.assert_called_once_with("/proc")
    assert reads == [proc / str(pid) / "comm" for pid in range(1, 5)]
    assert set(proc.rglob("*")) == set(originals) | {path.parent for path in originals}
    for path, (content, mtime) in originals.items():
        assert path.read_bytes() == content
        assert path.stat().st_mtime_ns == mtime
