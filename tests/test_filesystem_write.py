"""Create bounded temporary files without overwriting, leaking content or bypassing policy."""

from contextlib import closing
from dataclasses import asdict
import json
import os
import stat
from unittest.mock import Mock

import pytest

from aios.core import Core, build_tool_registry
from aios.filesystem_read import FilesystemReadTool
from aios.filesystem_write import FilesystemWriteTool, MAX_WRITE_BYTES
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


@pytest.mark.parametrize("content", ["", "été\r\n\t🙂", "\ufeffBonjour", "a" * 65536, "é" * 32768],
                         ids=["empty", "utf8", "bom", "ascii-limit", "multibyte-limit"])
def test_creates_exact_utf8_content_and_reports_byte_size(workspace, tmp_path, monkeypatch, content):
    (workspace / "dossier été").mkdir()
    monkeypatch.chdir(tmp_path)
    arguments = {"path": "dossier été/notes.txt", "content": content}
    result = FilesystemWriteTool().execute(arguments, authorize=lambda _: True)
    raw = content.encode("utf-8")
    assert result == ToolResult(success=True, data={
        "workspace": str(workspace), "path": arguments["path"], "created": True, "size_bytes": len(raw),
    })
    assert json.loads(json.dumps(asdict(result))) == asdict(result)
    assert (workspace / arguments["path"]).read_bytes() == raw
    assert arguments == {"path": "dossier été/notes.txt", "content": content}
    assert FilesystemReadTool().execute({"path": arguments["path"]}).data["content"] == content


@pytest.mark.parametrize("mask", [0, 0o022, 0o777])
def test_private_non_executable_permissions_respect_umask(workspace, mask):
    previous = os.umask(mask)
    try:
        result = FilesystemWriteTool().execute({"path": "notes", "content": "text"}, authorize=lambda _: True)
    finally:
        after = os.umask(previous)
    assert result.success and after == mask
    assert stat.S_IMODE((workspace / "notes").stat().st_mode) == 0o600 & ~mask


def test_literal_filename_single_creation_no_commands_and_closed_descriptors(workspace, monkeypatch, caplog, capsys):
    original_open = os.open
    descriptors = []
    creations = []

    def opened(path, flags, **kwargs):
        assert flags & os.O_NOFOLLOW
        assert not flags & (os.O_TRUNC | os.O_APPEND)
        if flags & os.O_CREAT:
            assert flags & os.O_EXCL and flags & os.O_WRONLY
            creations.append(path)
        else:
            assert flags & os.O_DIRECTORY
        descriptor = original_open(path, flags, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    blocked = Mock(side_effect=AssertionError("Unexpected command or unrelated mutation"))
    with monkeypatch.context() as patch:
        patch.setattr("os.open", opened)
        for name in ("os.mkdir", "os.unlink", "os.rename", "os.chmod", "os.chown",
                     "os.system", "os.popen", "subprocess.Popen", "builtins.open"):
            patch.setattr(name, blocked)
        result = FilesystemWriteTool().execute(
            {"path": "literal $(id);*.txt", "content": "private contents"}, authorize=lambda _: True,
        )
    assert result.success and creations == ["literal $(id);*.txt"]
    assert (workspace / creations[0]).read_bytes() == b"private contents"
    blocked.assert_not_called()
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("arguments", [
    None, [], {}, {"path": "notes"}, {"content": "text"}, {1: "notes", "content": "text"},
    *({"path": "notes", "content": "text", key: value} for key, value in [
        ("workspace", "/"), ("overwrite", True), ("append", True), ("mode", 0o777),
        ("parents", True), ("encoding", "latin-1"), ("confirmed", True), ("risk_level", "READ"),
    ]),
    *({"path": path, "content": "text"} for path in [
        None, True, 1, [], b"notes", "", " ", ".", "/tmp/notes", "..", "../notes",
        "parent/../notes", "./notes", "parent/./notes", "parent//notes", "notes/",
        "parent\\notes", "notes\0name", "notes\nname", "notes\x7fname", "notes\ud800", "é" * 2049,
    ]),
])
def test_invalid_arguments_fail_before_confirmation_or_access(workspace, monkeypatch, arguments):
    blocked = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    authorize = Mock(return_value=True)
    monkeypatch.setattr("os.open", blocked)
    monkeypatch.setattr("os.write", blocked)
    assert FilesystemWriteTool().execute(arguments, authorize=authorize) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    authorize.assert_not_called()
    blocked.assert_not_called()


@pytest.mark.parametrize("content", [None, True, 1, [], {}, b"text", "bad\ud800", "nul\0", "\x1b[31m", "\x7f",
    pytest.param("a" * (MAX_WRITE_BYTES + 1), id="too-many-characters"),
    pytest.param("é" * (MAX_WRITE_BYTES // 2 + 1), id="too-many-utf8-bytes"),
])
def test_non_text_or_oversized_content_never_authorizes_or_creates(workspace, monkeypatch, content):
    blocked = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    authorize = Mock(return_value=True)
    monkeypatch.setattr("os.open", blocked)
    assert FilesystemWriteTool().execute({"path": "notes", "content": content}, authorize=authorize) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    authorize.assert_not_called()
    blocked.assert_not_called()


@pytest.mark.parametrize("use_registry", [False, True])
def test_no_authorization_denies_direct_and_registry_calls(workspace, monkeypatch, use_registry):
    tool = FilesystemWriteTool()
    registry = ToolRegistry()
    registry.register(tool)
    blocked = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    monkeypatch.setattr("os.open", blocked)
    arguments = {"path": "notes", "content": "text"}
    result = registry.execute(tool.name, arguments) if use_registry else tool.execute(arguments)
    assert result == ToolResult(success=False, error="Tool execution denied")
    blocked.assert_not_called()


@pytest.mark.parametrize("answer", [False, None, 1, "oui"])
def test_only_boolean_true_authorizes_creation(workspace, monkeypatch, answer):
    blocked = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    monkeypatch.setattr("os.open", blocked)
    assert FilesystemWriteTool().execute(
        {"path": "notes", "content": "text"}, authorize=lambda _: answer,
    ) == ToolResult(success=False, error="Tool execution denied")
    blocked.assert_not_called()


def test_confirmation_cannot_modify_the_validated_path_or_content(workspace, monkeypatch):
    opened = Mock(wraps=os.open)
    monkeypatch.setattr("os.open", opened)
    arguments = {"path": "notes", "content": "original"}

    def authorize(preview):
        opened.assert_not_called()
        assert preview == {**arguments, "workspace": str(workspace)}
        preview.update(path="../outside", content="changed")
        return True

    assert FilesystemWriteTool().execute(arguments, authorize=authorize).success
    assert (workspace / "notes").read_bytes() == b"original"
    assert arguments == {"path": "notes", "content": "original"}
    assert not (workspace.parent / "outside").exists()


@pytest.mark.parametrize("kind", ["file", "directory", "hardlink", "symlink", "broken", "fifo"])
def test_existing_entries_are_preserved_without_any_write(workspace, tmp_path, monkeypatch, kind):
    outside = tmp_path / "outside"
    outside.write_bytes(b"preserved")
    path = workspace / "notes"
    if kind == "file":
        path.write_bytes(b"preserved")
    elif kind == "directory":
        path.mkdir()
        (path / "keep").write_bytes(b"preserved")
    elif kind == "hardlink":
        os.link(outside, path)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.symlink_to(outside if kind == "symlink" else tmp_path / "missing")
    before = path.lstat()
    write = Mock(side_effect=AssertionError("Existing entry written"))
    monkeypatch.setattr("os.write", write)
    assert FilesystemWriteTool().execute({"path": "notes", "content": "new"}, authorize=lambda _: True) == ToolResult(
        success=False, error="Tool execution failed",
    )
    write.assert_not_called()
    after = path.lstat()
    assert (after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns) == (
        before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns,
    )
    assert outside.read_bytes() == b"preserved"
    if kind == "file":
        assert path.read_bytes() == b"preserved"
    elif kind == "directory":
        assert (path / "keep").read_bytes() == b"preserved"
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("location", ["workspace", "ancestor", "parent", "internal", "broken"])
def test_parent_symlinks_are_never_followed(tmp_path, location):
    root = tmp_path / "home/workspace"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    tool = FilesystemWriteTool(root)
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
    assert tool.execute({"path": path, "content": "text"}, authorize=lambda _: True) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert not list(tmp_path.rglob("notes"))


@pytest.mark.parametrize("kind", ["workspace", "parent", "file-parent"])
def test_missing_parents_are_not_created(workspace, kind):
    path = "parent/notes"
    if kind == "workspace":
        workspace.rmdir()
        path = "notes"
    elif kind == "file-parent":
        (workspace / "parent").write_bytes(b"preserved")
    assert FilesystemWriteTool().execute({"path": path, "content": "text"}, authorize=lambda _: True) == ToolResult(
        success=False, error="Tool execution failed",
    )
    if kind == "workspace":
        assert not workspace.exists()
    elif kind == "parent":
        assert list(workspace.iterdir()) == []
    else:
        assert (workspace / "parent").read_bytes() == b"preserved"


@pytest.mark.parametrize("replacement", ["file", "symlink", "hardlink"])
def test_destination_created_concurrently_is_not_overwritten(workspace, tmp_path, monkeypatch, replacement):
    outside = tmp_path / "outside"
    outside.write_bytes(b"preserved")
    original_open = os.open

    def raced_open(path, flags, **kwargs):
        if flags & os.O_CREAT:
            destination = workspace / "notes"
            if replacement == "file":
                destination.write_bytes(b"preserved")
            elif replacement == "symlink":
                destination.symlink_to(outside)
            else:
                os.link(outside, destination)
        return original_open(path, flags, **kwargs)

    monkeypatch.setattr("os.open", raced_open)
    assert FilesystemWriteTool().execute({"path": "notes", "content": "new"}, authorize=lambda _: True) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert outside.read_bytes() == (workspace / "notes").read_bytes() == b"preserved"


def test_replaced_parent_path_does_not_redirect_creation(workspace, tmp_path, monkeypatch):
    parent = workspace / "parent"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original_open = os.open

    def raced_open(path, flags, **kwargs):
        if flags & os.O_CREAT:
            parent.rename(workspace / "original-parent")
            parent.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, **kwargs)

    monkeypatch.setattr("os.open", raced_open)
    assert FilesystemWriteTool().execute({"path": "parent/notes", "content": "text"}, authorize=lambda _: True).success
    assert (workspace / "original-parent/notes").read_bytes() == b"text"
    assert list(outside.iterdir()) == []


def test_write_uses_open_file_if_its_path_is_replaced(workspace, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.write_bytes(b"preserved")
    original_write = os.write

    def raced_write(descriptor, data):
        (workspace / "notes").rename(workspace / "original-notes")
        (workspace / "notes").symlink_to(outside)
        return original_write(descriptor, data)

    monkeypatch.setattr("os.write", raced_write)
    assert FilesystemWriteTool().execute({"path": "notes", "content": "text"}, authorize=lambda _: True).success
    assert (workspace / "original-notes").read_bytes() == b"text"
    assert outside.read_bytes() == b"preserved"


def test_short_writes_complete_multibyte_text(workspace, monkeypatch):
    original_write = os.write
    monkeypatch.setattr("os.write", lambda fd, data: original_write(fd, data[:2]))
    content = "é🙂texte"
    result = FilesystemWriteTool().execute({"path": "notes", "content": content}, authorize=lambda _: True)
    assert result.success and result.data["size_bytes"] == len(content.encode("utf-8"))
    assert (workspace / "notes").read_bytes() == content.encode("utf-8")


@pytest.mark.parametrize("failure", ["zero", "write", "close", "interrupt"])
def test_io_failure_never_reports_success_or_deletes_a_path_and_closes_file(
    workspace, monkeypatch, caplog, capsys, failure,
):
    original_open, original_write, original_close = os.open, os.write, os.close
    descriptors = []
    writes = 0

    def opened(path, flags, **kwargs):
        descriptor = original_open(path, flags, **kwargs)
        if flags & os.O_CREAT:
            descriptors.append(descriptor)
        return descriptor

    def write(descriptor, data):
        nonlocal writes
        writes += 1
        if failure == "zero":
            return 0
        if failure == "close":
            return original_write(descriptor, data)
        if writes == 1:
            return original_write(descriptor, data[:1])
        if failure == "interrupt":
            raise KeyboardInterrupt
        raise OSError("private contents and failure details")

    def close(descriptor):
        original_close(descriptor)
        if failure == "close" and descriptor in descriptors:
            raise OSError("private close details")

    blocked = Mock(side_effect=AssertionError("Unexpected deletion"))
    with monkeypatch.context() as patch:
        patch.setattr("os.open", opened)
        patch.setattr("os.write", write)
        patch.setattr("os.close", close)
        patch.setattr("os.unlink", blocked)
        if failure == "interrupt":
            with pytest.raises(KeyboardInterrupt):
                FilesystemWriteTool().execute({"path": "notes", "content": "éabc"}, authorize=lambda _: True)
        else:
            result = FilesystemWriteTool().execute({"path": "notes", "content": "éabc"}, authorize=lambda _: True)
            assert result == ToolResult(success=False, error="File creation failed; file may be incomplete")
    blocked.assert_not_called()
    assert len(descriptors) == 1 and writes == (1 if failure in {"zero", "close"} else 2)
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    expected = b"" if failure == "zero" else ("éabc".encode() if failure == "close" else b"\xc3")
    assert (workspace / "notes").read_bytes() == expected
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("scenario", ["success", "no-handler", "deny", "invalid-path", "invalid-content", "write-error"])
def test_core_masks_content_before_validation_and_preserves_confirmation_and_result(
    workspace, tmp_path, monkeypatch, caplog, scenario,
):
    content = "Violet orchid 4821"  # No credential keyword for the heuristic filter.
    arguments = {"path": "../outside" if scenario == "invalid-path" else "notes", "content": content}
    if scenario == "invalid-content":
        arguments["content"] = [content]
    registry = build_tool_registry()
    tool = registry.get("filesystem.write")
    assert tool.risk_level is RiskLevel.CONFIRM
    if scenario == "deny":
        tool.risk_level = RiskLevel.DENY
    handler = Mock(return_value=True) if scenario != "no-handler" else None
    execution = Mock(wraps=tool._execute)
    monkeypatch.setattr(tool, "_execute", execution)
    if scenario == "write-error":
        monkeypatch.setattr("os.write", Mock(side_effect=OSError(content)))
    reply = json.dumps({"tool": "filesystem.write", "arguments": arguments})
    provider = FakeLLMProvider([reply, "Résultat reçu"])
    statements = []
    with closing(TaskHistory(tmp_path / "data")) as history:
        history._connection.set_trace_callback(statements.append)
        original_validate = tool.validate_arguments

        def validate(validated):
            pending = history.recent()[0]["tools"][0]
            assert pending["status"] == "running"
            assert pending["arguments"]["content"] == "[contenu du fichier non conservé]"
            original_validate(validated)

        monkeypatch.setattr(tool, "validate_arguments", validate)
        core = Core(provider, history, registry=registry, permission_handler=handler)
        assert core.chat("Créer le fichier") == "Résultat reçu"
        result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
        saved = history.recent()[0]["tools"][0]
        assert saved["arguments"] == {**arguments, "content": "[contenu du fichier non conservé]"}
        assert saved["result"] == {key: value for key, value in result.items() if key != "tool"}
        assert saved["status"] == ("succeeded" if scenario == "success" else "failed")
    if scenario == "success":
        assert result["data"] == {"workspace": str(workspace), "path": "notes", "created": True, "size_bytes": len(content)}
        assert result["success"] is True and result["error"] is None
        assert (workspace / "notes").read_text() == content
    else:
        error = ("Invalid tool arguments" if scenario.startswith("invalid") else
                 "File creation failed; file may be incomplete" if scenario == "write-error" else
                 "Tool execution denied")
        assert result["success"] is False and result["data"] is None and result["error"] == error
        assert (workspace / "notes").exists() is (scenario == "write-error")
    assert execution.call_count == int(scenario in {"success", "write-error"})
    if handler is not None:
        if scenario.startswith("invalid"):
            handler.assert_not_called()
        else:
            decision = PolicyDecision.DENY if scenario == "deny" else PolicyDecision.CONFIRM
            handler.assert_called_once_with(decision, "filesystem.write", {**arguments, "workspace": str(workspace)})
    assert provider.calls[1][-2] == {"role": "assistant", "content": reply}
    assert all(content not in statement for statement in statements)
    assert content.encode() not in (tmp_path / "data/history.sqlite3").read_bytes()
    assert not caplog.records
