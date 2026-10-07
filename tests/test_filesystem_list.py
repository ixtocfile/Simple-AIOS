"""Exercise workspace listing on temporary files, without a LLM or shell."""

from contextlib import closing, contextmanager
from dataclasses import asdict
import json
import os
import stat
from unittest.mock import Mock

import pytest

from aios.core import Core, build_tool_registry
from aios.filesystem_list import FilesystemListTool, MAX_LIST_ENTRIES
from aios.history import TaskHistory
from aios.llm import FakeLLMProvider
from aios.policy import PolicyDecision, PolicyEngine
from aios.tools import RiskLevel, ToolResult


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "AIOS-Workspace"
    root.mkdir()
    return root


def test_listing_returns_metadata_without_reading_contents_writing_or_running_commands(
    workspace, tmp_path, monkeypatch, caplog, capsys,
):
    marker = workspace / "note été.txt"
    marker.write_bytes(b"private file contents")
    before = marker.stat()
    (workspace / ".empty").touch()
    (workspace / "folder").mkdir()
    (workspace / "folder/nested").write_text("not listed")
    (workspace / "link").symlink_to(marker)
    (workspace / "broken").symlink_to(tmp_path / "missing")
    os.mkfifo(workspace / "pipe")
    registry = build_tool_registry()
    assert registry.get("filesystem.list").risk_level is RiskLevel.READ
    policy = PolicyEngine(registry)
    assert policy.evaluate("filesystem.list") is PolicyDecision.ALLOW
    blocked = Mock(side_effect=AssertionError("Unexpected read, write or command"))
    descriptors = []
    original_open = os.open

    def open_directory(path, flags, **kwargs):
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        descriptor = original_open(path, flags, **kwargs)
        descriptors.append(descriptor)
        assert stat.S_ISDIR(os.fstat(descriptor).st_mode)
        return descriptor

    arguments = {}
    with monkeypatch.context() as patch:
        for name in ("builtins.open", "pathlib.Path.open", "os.mkdir", "os.unlink",
                     "os.rename", "os.system", "os.popen", "subprocess.Popen"):
            patch.setattr(name, blocked)
        patch.setattr("os.open", open_directory)
        result = registry.execute("filesystem.list", arguments, authorize=lambda _: (
            policy.evaluate("filesystem.list") is PolicyDecision.ALLOW
        ))

    assert result == ToolResult(success=True, data={
        "workspace": str(workspace), "path": ".", "entries": [
            {"name": ".empty", "type": "file", "size_bytes": 0},
            {"name": "broken", "type": "symlink", "size_bytes": None},
            {"name": "folder", "type": "directory", "size_bytes": None},
            {"name": "link", "type": "symlink", "size_bytes": None},
            {"name": "note été.txt", "type": "file", "size_bytes": before.st_size},
            {"name": "pipe", "type": "other", "size_bytes": None},
        ], "truncated": False,
    })
    assert json.loads(json.dumps(asdict(result), allow_nan=False)) == asdict(result)
    assert arguments == {}
    blocked.assert_not_called()
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert marker.read_bytes() == b"private file contents"
    after = marker.stat()
    assert (after.st_size, after.st_mtime_ns, after.st_mode) == (
        before.st_size, before.st_mtime_ns, before.st_mode,
    )
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


def test_nested_directory_is_relative_to_workspace_not_current_directory(workspace, tmp_path, monkeypatch):
    (workspace / "dossier été/sub").mkdir(parents=True)
    name = "literal $(command);*\nname.txt"
    (workspace / "dossier été/sub" / name).write_text("é", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    arguments = {"path": "dossier été/sub"}

    result = FilesystemListTool().execute(arguments)

    assert result == ToolResult(success=True, data={
        "workspace": str(workspace), "path": "dossier été/sub", "entries": [
            {"name": name, "type": "file", "size_bytes": 2},
        ], "truncated": False,
    })
    assert arguments == {"path": "dossier été/sub"}


@pytest.mark.parametrize("arguments", [
    None, [], {"unknown": True}, {"workspace": "/"}, {"path": ".", "limit": 1},
    {"path": None}, {"path": True}, {"path": 1}, {"path": []}, {"path": b"dir"},
    {"path": ""}, {"path": " "}, {"path": "/"}, {"path": "/etc"},
    {"path": ".."}, {"path": "../outside"}, {"path": "dir/../../outside"},
    {"path": "dir/.."}, {"path": "./dir"}, {"path": "dir/."},
    {"path": "dir//child"}, {"path": "dir/"}, {"path": "dir\\child"},
    {"path": "bad\0name"}, {"path": "bad\nname"}, {"path": "bad\x1bname"},
    {"path": "bad\x7fname"}, {"path": "bad\ud800name"}, {"path": "é" * 2049},
])
def test_invalid_arguments_fail_before_any_filesystem_access(workspace, monkeypatch, arguments):
    tool = FilesystemListTool()
    blocked = Mock(side_effect=AssertionError("Filesystem access before validation"))
    monkeypatch.setattr("os.open", blocked)
    monkeypatch.setattr("os.scandir", blocked)
    assert tool.execute(arguments) == ToolResult(success=False, error="Invalid tool arguments")
    blocked.assert_not_called()


def test_denial_prevents_opening_even_the_workspace(workspace, monkeypatch):
    tool = FilesystemListTool()
    blocked = Mock(side_effect=AssertionError("Filesystem access after denial"))
    monkeypatch.setattr("os.open", blocked)
    assert tool.execute({}, authorize=lambda _: False) == ToolResult(
        success=False, error="Tool execution denied",
    )
    blocked.assert_not_called()


@pytest.mark.parametrize("path", ["missing", "file", "file/child"])
def test_missing_or_non_directory_paths_fail_safely(workspace, path):
    (workspace / "file").touch()
    assert FilesystemListTool().execute({"path": path}) == ToolResult(
        success=False, error="Tool execution failed",
    )


def test_missing_workspace_is_never_created(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert FilesystemListTool().execute({}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert not (tmp_path / "AIOS-Workspace").exists()


@pytest.mark.parametrize("location", ["workspace", "ancestor", "leaf", "intermediate", "internal"])
def test_symlinks_in_directory_paths_are_refused(tmp_path, location):
    root = tmp_path / "home/workspace"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / "sub").mkdir(parents=True)
    (outside / "private").write_text("private contents")
    tool = FilesystemListTool(root)
    path = "."
    if location == "workspace":
        root.rmdir()
        root.symlink_to(outside, target_is_directory=True)
    elif location == "ancestor":
        root.parent.rename(tmp_path / "original-home")
        root.parent.symlink_to(outside, target_is_directory=True)
        (outside / "workspace").mkdir()
    else:
        target = outside
        if location == "internal":
            target = root / "inside"
            target.mkdir()
        (root / "link").symlink_to(target, target_is_directory=True)
        path = "link/sub" if location == "intermediate" else "link"
    assert tool.execute({"path": path}) == ToolResult(success=False, error="Tool execution failed")


def test_link_substituted_after_validation_is_not_followed(workspace, tmp_path):
    folder = workspace / "folder"
    folder.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private").touch()

    def authorize(_):
        folder.rmdir()
        folder.symlink_to(outside, target_is_directory=True)
        return True

    assert FilesystemListTool().execute({"path": "folder"}, authorize=authorize) == ToolResult(
        success=False, error="Tool execution failed",
    )


def test_metadata_uses_open_directory_after_path_replacement(workspace, tmp_path, monkeypatch):
    folder = workspace / "folder"
    folder.mkdir()
    (folder / "file").write_bytes(b"ok")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"outside private contents")
    original_scandir = os.scandir

    def replace_path(descriptor):
        folder.rename(workspace / "original-folder")
        folder.symlink_to(outside, target_is_directory=True)
        return original_scandir(descriptor)

    monkeypatch.setattr("os.scandir", replace_path)
    result = FilesystemListTool().execute({"path": "folder"})
    assert result.success
    assert result.data["entries"] == [{"name": "file", "type": "file", "size_bytes": 2}]


@pytest.mark.parametrize("count", [0, 100, 150])
def test_listing_is_bounded_and_marks_truncation(workspace, monkeypatch, count):
    for index in range(count):
        (workspace / f"entry-{index:03}").touch()
    original_scandir = os.scandir
    visited = []

    @contextmanager
    def bounded_scandir(descriptor):
        with original_scandir(descriptor) as iterator:
            def entries():
                for entry in iterator:
                    visited.append(entry.name)
                    assert len(visited) <= MAX_LIST_ENTRIES + 1
                    yield entry
            yield entries()

    monkeypatch.setattr("os.scandir", bounded_scandir)
    result = FilesystemListTool().execute({})
    assert result.success
    assert [entry["name"] for entry in result.data["entries"]] == sorted(visited[:100])
    assert len(result.data["entries"]) == min(count, 100)
    assert result.data["truncated"] is (count > 100)


@pytest.mark.parametrize("operation", ["open", "scandir", "stat"])
def test_io_errors_have_no_partial_data_or_sensitive_details(workspace, monkeypatch, caplog, capsys, operation):
    (workspace / "file").touch()
    blocked = Mock(side_effect=PermissionError("private sensitive details"))
    with monkeypatch.context() as patch:
        patch.setattr(f"os.{operation}", blocked)
        result = FilesystemListTool().execute({})
    assert result == ToolResult(success=False, error="Tool execution failed")
    assert blocked.call_count == 1
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


def test_each_call_refreshes_entries(workspace):
    tool = FilesystemListTool()
    assert tool.execute({}).data["entries"] == []
    (workspace / "new").touch()
    assert tool.execute({}).data["entries"] == [{"name": "new", "type": "file", "size_bytes": 0}]


@pytest.mark.parametrize(("risk", "path", "error"), [
    (RiskLevel.READ, ".", None),
    (RiskLevel.DENY, ".", "Tool execution denied"),
    (RiskLevel.READ, "../outside", "Invalid tool arguments"),
])
def test_core_validates_applies_policy_and_returns_real_results_to_model(
    workspace, tmp_path, monkeypatch, risk, path, error,
):
    (workspace / "file").write_bytes(b"data")
    registry = build_tool_registry()
    tool = registry.get("filesystem.list")
    tool.risk_level = risk
    execution = Mock(wraps=tool._execute)
    monkeypatch.setattr(tool, "_execute", execution)
    provider = FakeLLMProvider([
        json.dumps({"tool": "filesystem.list", "arguments": {"path": path}}),
        "Résultat reçu.",
    ])
    permission = Mock(return_value=True)
    with closing(TaskHistory(tmp_path / "history")) as history:
        core = Core(provider, history, registry=registry, permission_handler=permission)
        assert core.chat("Lister mon workspace") == "Résultat reçu."
        result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
        assert result["tool"] == "filesystem.list" and result["error"] == error
        assert result["success"] is (error is None)
        if error is None:
            assert result["data"]["entries"] == [{"name": "file", "type": "file", "size_bytes": 4}]
            assert execution.call_count == 1
        else:
            assert result["data"] is None
            execution.assert_not_called()
        if risk is RiskLevel.READ:
            permission.assert_not_called()
