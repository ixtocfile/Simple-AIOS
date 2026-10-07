"""Create only temporary directories, with explicit authorization and no shell."""

from contextlib import closing
from dataclasses import asdict
import json
import os
import stat
from unittest.mock import Mock

import pytest

from aios.core import Core, build_tool_registry
from aios.filesystem_mkdir import FilesystemMkdirTool
from aios.history import TaskHistory
from aios.llm import FakeLLMProvider
from aios.policy import PolicyDecision
from aios.tools import RiskLevel, ToolRegistry, ToolResult


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "AIOS-Workspace"
    root.mkdir()
    return root


@pytest.mark.parametrize("path", ["notes", "parent/été", "literal $(id);*", "--parents", ".hidden"])
def test_creates_only_the_requested_empty_directory(workspace, tmp_path, monkeypatch, path):
    (workspace / "parent").mkdir()
    before = set(workspace.rglob("*"))
    monkeypatch.chdir(tmp_path)
    arguments = {"path": path}
    result = FilesystemMkdirTool().execute(arguments, authorize=lambda _: True)
    assert result == ToolResult(success=True, data={"workspace": str(workspace), "path": path, "created": True})
    assert set(workspace.rglob("*")) == before | {workspace / path}
    assert list((workspace / path).iterdir()) == []
    assert (workspace / path).stat().st_mode & 0o077 == 0
    assert arguments == {"path": path}
    assert json.loads(json.dumps(asdict(result))) == asdict(result)


@pytest.mark.parametrize("mask", [0, 0o022, 0o777])
def test_private_permissions_respect_umask_without_changing_it(workspace, mask):
    previous = os.umask(mask)
    try:
        result = FilesystemMkdirTool().execute({"path": "notes"}, authorize=lambda _: True)
    finally:
        after = os.umask(previous)
    assert result.success
    assert after == mask
    assert stat.S_IMODE((workspace / "notes").stat().st_mode) == 0o700 & ~mask


def test_authorization_precedes_access_and_cannot_change_the_target(workspace, monkeypatch):
    opened = Mock(wraps=os.open)
    mkdir = Mock(wraps=os.mkdir)
    monkeypatch.setattr("os.open", opened)
    monkeypatch.setattr("os.mkdir", mkdir)
    registry = ToolRegistry()
    registry.register(FilesystemMkdirTool())

    def authorize(arguments):
        opened.assert_not_called()
        mkdir.assert_not_called()
        assert arguments == {"path": "notes", "workspace": str(workspace)}
        arguments["path"] = "../outside"
        return True

    assert registry.execute("filesystem.mkdir", {"path": "notes"}, authorize=authorize).success
    assert list(workspace.iterdir()) == [workspace / "notes"]
    mkdir.assert_called_once()
    assert not (workspace.parent / "outside").exists()


@pytest.mark.parametrize("arguments", [
    None, [], {}, {1: "notes"}, {"path": None}, {"path": True}, {"path": 1},
    {"path": []}, {"path": b"notes"}, {"path": "notes", "workspace": "/"},
    {"path": "notes", "parents": True}, {"path": "notes", "exist_ok": True},
    {"path": "notes", "mode": 0o777}, {"path": "notes", "confirmed": True},
    {"path": "notes", "risk_level": "READ"}, {"path": ""}, {"path": " "},
    {"path": "."}, {"path": "/tmp/notes"}, {"path": ".."}, {"path": "../notes"},
    {"path": "parent/../notes"}, {"path": "./notes"}, {"path": "parent/./notes"},
    {"path": "parent//notes"}, {"path": "notes/"}, {"path": "parent\\notes"},
    {"path": "notes\0name"}, {"path": "notes\nname"}, {"path": "notes\x7fname"},
    {"path": "notes\ud800"}, {"path": "é" * 2049},
])
def test_invalid_arguments_never_authorize_or_access_filesystem(workspace, monkeypatch, arguments):
    blocked = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    authorize = Mock(return_value=True)
    monkeypatch.setattr("os.open", blocked)
    monkeypatch.setattr("os.mkdir", blocked)
    assert FilesystemMkdirTool().execute(arguments, authorize=authorize) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    authorize.assert_not_called()
    blocked.assert_not_called()


@pytest.mark.parametrize("use_registry", [False, True])
def test_missing_authorization_denies_direct_and_registry_calls(workspace, monkeypatch, use_registry):
    tool = FilesystemMkdirTool()
    registry = ToolRegistry()
    registry.register(tool)
    blocked = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    monkeypatch.setattr("os.open", blocked)
    monkeypatch.setattr("os.mkdir", blocked)
    arguments = {"path": "notes"}
    result = registry.execute(tool.name, arguments) if use_registry else tool.execute(arguments)
    assert result == ToolResult(success=False, error="Tool execution denied")
    blocked.assert_not_called()


@pytest.mark.parametrize("answer", [False, None, 1, "oui"])
def test_only_boolean_true_authorizes_access(workspace, monkeypatch, answer):
    blocked = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    monkeypatch.setattr("os.open", blocked)
    monkeypatch.setattr("os.mkdir", blocked)
    assert FilesystemMkdirTool().execute({"path": "notes"}, authorize=lambda _: answer) == ToolResult(
        success=False, error="Tool execution denied",
    )
    blocked.assert_not_called()


def test_authorization_error_is_safe_without_access(workspace, monkeypatch, caplog, capsys):
    blocked = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    monkeypatch.setattr("os.open", blocked)
    monkeypatch.setattr("os.mkdir", blocked)
    authorize = Mock(side_effect=PermissionError("private authorization detail"))
    assert FilesystemMkdirTool().execute({"path": "notes"}, authorize=authorize) == ToolResult(
        success=False, error="Tool authorization failed",
    )
    blocked.assert_not_called()
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "broken", "fifo"])
def test_existing_entries_are_never_replaced_or_modified(workspace, tmp_path, kind):
    target = workspace / "notes"
    outside = tmp_path / "outside"
    outside.mkdir()
    if kind == "directory":
        target.mkdir()
        (target / "keep").write_text("preserved")
    elif kind == "file":
        target.write_text("preserved")
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        target.symlink_to(outside if kind == "symlink" else outside / "missing")
    before = target.lstat()
    assert FilesystemMkdirTool().execute({"path": "notes"}, authorize=lambda _: True) == ToolResult(
        success=False, error="Tool execution failed",
    )
    after = target.lstat()
    assert (after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns) == (
        before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns,
    )
    assert list(outside.iterdir()) == []
    if kind in {"file", "directory"}:
        assert (target if kind == "file" else target / "keep").read_text() == "preserved"


@pytest.mark.parametrize("kind", ["workspace", "parent", "file-parent"])
def test_workspace_and_parents_must_already_be_directories(workspace, kind):
    path = "parent/notes"
    if kind == "workspace":
        workspace.rmdir()
        path = "notes"
    elif kind == "file-parent":
        (workspace / "parent").write_text("preserved")
    assert FilesystemMkdirTool().execute({"path": path}, authorize=lambda _: True) == ToolResult(
        success=False, error="Tool execution failed",
    )
    if kind == "workspace":
        assert not workspace.exists()
    elif kind == "parent":
        assert list(workspace.iterdir()) == []
    else:
        assert (workspace / "parent").read_text() == "preserved"


@pytest.mark.parametrize("location", ["workspace", "ancestor", "parent", "internal", "broken"])
def test_symlinked_parents_are_refused(tmp_path, location):
    root = tmp_path / "home/workspace"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    tool = FilesystemMkdirTool(root)
    path = "notes"
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
        elif location == "broken":
            target = outside / "missing"
        (root / "link").symlink_to(target, target_is_directory=True)
        path = "link/notes"
    assert tool.execute({"path": path}, authorize=lambda _: True) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert not list(tmp_path.rglob("notes"))


def test_parent_replaced_during_confirmation_is_not_followed(workspace, tmp_path):
    parent = workspace / "parent"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    def authorize(_):
        parent.rmdir()
        parent.symlink_to(outside, target_is_directory=True)
        return True

    assert FilesystemMkdirTool().execute({"path": "parent/notes"}, authorize=authorize) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert list(outside.iterdir()) == []


def test_creation_stays_in_open_parent_after_path_replacement(workspace, tmp_path, monkeypatch):
    parent = workspace / "parent"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original_mkdir = os.mkdir

    def replace(path, mode, *, dir_fd):
        parent.rename(workspace / "original-parent")
        parent.symlink_to(outside, target_is_directory=True)
        original_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr("os.mkdir", replace)
    result = FilesystemMkdirTool().execute({"path": "parent/notes"}, authorize=lambda _: True)
    assert result.success
    assert (workspace / "original-parent/notes").is_dir()
    assert list(outside.iterdir()) == []


def test_destination_link_created_concurrently_is_not_followed(workspace, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    original_mkdir = os.mkdir

    def replace(path, mode, *, dir_fd):
        (workspace / "notes").symlink_to(outside, target_is_directory=True)
        original_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr("os.mkdir", replace)
    assert FilesystemMkdirTool().execute({"path": "notes"}, authorize=lambda _: True) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert not outside.exists()
    assert (workspace / "notes").is_symlink()


@pytest.mark.parametrize("fail", [False, True])
def test_one_attempt_closes_descriptors_without_other_writes_or_commands(
    workspace, monkeypatch, caplog, capsys, fail,
):
    original_open = os.open
    descriptors = []

    def opened(path, flags, **kwargs):
        assert flags & os.O_NOFOLLOW and flags & os.O_DIRECTORY
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        descriptor = original_open(path, flags, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    mkdir = Mock(wraps=os.mkdir, side_effect=PermissionError("private failure") if fail else None)
    blocked = Mock(side_effect=AssertionError("Unexpected write or command"))
    with monkeypatch.context() as patch:
        patch.setattr("os.open", opened)
        patch.setattr("os.mkdir", mkdir)
        for name in ("os.write", "os.chmod", "os.chown", "os.unlink", "os.rename",
                     "os.system", "os.popen", "subprocess.Popen", "builtins.open"):
            patch.setattr(name, blocked)
        result = FilesystemMkdirTool().execute({"path": "notes"}, authorize=lambda _: True)
    assert result.success is not fail
    if fail:
        assert result == ToolResult(success=False, error="Tool execution failed")
        assert not (workspace / "notes").exists()
    mkdir.assert_called_once()
    blocked.assert_not_called()
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(("risk", "answer", "allowed"), [
    (RiskLevel.CONFIRM, True, True), (RiskLevel.CONFIRM, False, False),
    (RiskLevel.CONFIRM, "oui", False), (RiskLevel.CONFIRM, None, False),
    (RiskLevel.DENY, True, False),
])
def test_core_applies_policy_and_records_real_result(
    workspace, tmp_path, monkeypatch, caplog, risk, answer, allowed,
):
    registry = build_tool_registry()
    tool = registry.get("filesystem.mkdir")
    assert tool.risk_level is RiskLevel.CONFIRM
    tool.risk_level = risk
    execution = Mock(wraps=tool._execute)
    monkeypatch.setattr(tool, "_execute", execution)
    handler = Mock(return_value=answer) if answer is not None else None
    provider = FakeLLMProvider([
        '{"tool":"filesystem.mkdir","arguments":{"path":"notes"}}', "Résultat reçu",
    ])
    with closing(TaskHistory(tmp_path / "data")) as history:
        core = Core(provider, history, registry=registry, permission_handler=handler)
        assert core.chat("Créer le dossier") == "Résultat reçu"
        result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
        assert result == {
            "tool": "filesystem.mkdir", "success": allowed,
            "data": {"workspace": str(workspace), "path": "notes", "created": True} if allowed else None,
            "error": None if allowed else "Tool execution denied",
        }
        saved = history.recent()[0]["tools"][0]
        assert saved["status"] == ("succeeded" if allowed else "failed")
        assert saved["arguments"] == {"path": "notes"}
        assert saved["result"] == {key: value for key, value in result.items() if key != "tool"}
    if handler is not None:
        decision = PolicyDecision.DENY if risk is RiskLevel.DENY else PolicyDecision.CONFIRM
        handler.assert_called_once_with(decision, "filesystem.mkdir", {"path": "notes", "workspace": str(workspace)})
    assert execution.call_count == int(allowed)
    assert (workspace / "notes").is_dir() is allowed
    assert not caplog.records
