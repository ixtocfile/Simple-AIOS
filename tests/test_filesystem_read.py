"""Read temporary text files under policy, without a real LLM or shell."""

from contextlib import closing
from dataclasses import asdict
import json
import os
from unittest.mock import Mock

import pytest

from aios.core import Core, build_tool_registry
from aios.filesystem_read import FilesystemReadTool, MAX_READ_BYTES
from aios.history import TaskHistory
from aios.llm import FakeLLMProvider
from aios.tools import RiskLevel, ToolResult


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "AIOS-Workspace"
    root.mkdir()
    return root


@pytest.mark.parametrize("content", ["", "été\r\n\t🙂", "\ufeffBonjour", "a" * 65536, "é" * 32768])
def test_reads_complete_utf8_preserving_newlines_and_byte_size(workspace, tmp_path, monkeypatch, content):
    (workspace / "dossier été").mkdir()
    path = workspace / "dossier été/notes.txt"
    raw = content.encode("utf-8")
    path.write_bytes(raw)
    before = path.stat()
    monkeypatch.chdir(tmp_path)
    arguments = {"path": "dossier été/notes.txt"}
    result = FilesystemReadTool().execute(arguments)
    assert result == ToolResult(success=True, data={
        "workspace": str(workspace), "path": arguments["path"], "content": content, "size_bytes": len(raw),
    })
    assert json.loads(json.dumps(asdict(result))) == asdict(result)
    assert arguments == {"path": "dossier été/notes.txt"}
    assert path.read_bytes() == raw
    after = path.stat()
    assert (after.st_mode, after.st_size, after.st_mtime_ns) == (
        before.st_mode, before.st_size, before.st_mtime_ns,
    )


def test_read_only_flags_no_commands_and_descriptors_closed(workspace, monkeypatch, caplog, capsys):
    (workspace / "literal $(command);*.txt").write_text("hello")
    original_open = os.open
    descriptors = []
    blocked = Mock(side_effect=AssertionError("Unexpected write or command"))

    def read_only_open(path, flags, **kwargs):
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        assert flags & os.O_NOFOLLOW
        descriptor = original_open(path, flags, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    with monkeypatch.context() as patch:
        patch.setattr("os.open", read_only_open)
        for name in ("os.write", "os.mkdir", "os.unlink", "os.rename", "os.system",
                     "os.popen", "subprocess.Popen", "builtins.open"):
            patch.setattr(name, blocked)
        result = FilesystemReadTool().execute({"path": "literal $(command);*.txt"})
    assert result.success and result.data["content"] == "hello"
    blocked.assert_not_called()
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("arguments", [
    None, [], {}, {"path": "file", "workspace": "/"}, {"path": "file", "limit": 1},
    {"path": "file", "encoding": "latin-1"}, {"path": None}, {"path": 1},
    {"path": True}, {"path": []}, {"path": b"file"}, {"path": ""}, {"path": " "},
    {"path": "."}, {"path": "/etc/passwd"}, {"path": "../file"}, {"path": "dir/../file"},
    {"path": "./file"}, {"path": "dir/./file"}, {"path": "dir//file"}, {"path": "file/"},
    {"path": "dir\\file"}, {"path": "file\0name"}, {"path": "file\nname"},
    {"path": "file\x7fname"}, {"path": "file\ud800"}, {"path": "é" * 2049},
])
def test_invalid_arguments_are_rejected_without_filesystem_access(workspace, monkeypatch, arguments):
    blocked = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    monkeypatch.setattr("os.open", blocked)
    assert FilesystemReadTool().execute(arguments) == ToolResult(success=False, error="Invalid tool arguments")
    blocked.assert_not_called()


@pytest.mark.parametrize("location", ["workspace", "ancestor", "parent", "leaf", "internal", "broken"])
def test_symlinks_are_never_followed(tmp_path, location):
    root = tmp_path / "home/workspace"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "note").write_text("private outside data")
    tool = FilesystemReadTool(root)
    path = "note"
    if location == "workspace":
        root.rmdir()
        root.symlink_to(outside, target_is_directory=True)
    elif location == "ancestor":
        root.parent.rename(tmp_path / "original-home")
        root.parent.symlink_to(outside, target_is_directory=True)
        (outside / "workspace").symlink_to(outside, target_is_directory=True)
    elif location == "parent":
        (root / "link").symlink_to(outside, target_is_directory=True)
        path = "link/note"
    else:
        target = outside / "note"
        if location == "internal":
            target = root / "original"
            target.write_text("inside")
        elif location == "broken":
            target = outside / "missing"
        (root / "note").symlink_to(target)
    assert tool.execute({"path": path}) == ToolResult(success=False, error="Tool execution failed")


@pytest.mark.parametrize("kind", ["directory", "fifo", "missing"])
def test_non_files_are_refused_before_opening_the_leaf(workspace, monkeypatch, kind):
    target = workspace / "note"
    if kind == "directory":
        target.mkdir()
    elif kind == "fifo":
        os.mkfifo(target)
    original_open = os.open
    leaf_open = Mock(side_effect=AssertionError("Non-file opened"))

    def open_parent(path, flags, **kwargs):
        if path == "note":
            return leaf_open(path, flags, **kwargs)
        return original_open(path, flags, **kwargs)

    monkeypatch.setattr("os.open", open_parent)
    assert FilesystemReadTool().execute({"path": "note"}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    leaf_open.assert_not_called()


def test_missing_workspace_is_not_created(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert FilesystemReadTool().execute({"path": "note"}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("raw", [b"\xff", b"\xc3", b"\xc0\xaf", b"text\0binary", b"\x1b[31m", b"text\x7f"])
def test_non_utf8_or_binary_controls_fail_without_partial_content(workspace, raw, caplog, capsys):
    (workspace / "note").write_bytes(raw)
    assert FilesystemReadTool().execute({"path": "note"}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


def test_oversized_file_is_refused_before_reading(workspace, monkeypatch):
    (workspace / "note").write_bytes(b"a" * (MAX_READ_BYTES + 1))
    read = Mock(side_effect=AssertionError("Oversized file read"))
    monkeypatch.setattr("os.read", read)
    assert FilesystemReadTool().execute({"path": "note"}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    read.assert_not_called()


def test_file_growth_cannot_exceed_the_byte_budget(workspace, monkeypatch):
    path = workspace / "note"
    path.write_text("small")
    original_read = os.read
    total = 0

    def growing_read(descriptor, count):
        nonlocal total
        if total == 0:
            path.write_bytes(b"a" * (2 * MAX_READ_BYTES))
        chunk = original_read(descriptor, count)
        total += len(chunk)
        assert total <= MAX_READ_BYTES + 1
        return chunk

    monkeypatch.setattr("os.read", growing_read)
    assert FilesystemReadTool().execute({"path": "note"}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    assert total == MAX_READ_BYTES + 1


def test_short_reads_are_combined_before_utf8_decoding(workspace, monkeypatch):
    (workspace / "note").write_text("é🙂texte", encoding="utf-8")
    original_read = os.read
    monkeypatch.setattr("os.read", lambda fd, count: original_read(fd, min(count, 2)))
    result = FilesystemReadTool().execute({"path": "note"})
    assert result.success and result.data["content"] == "é🙂texte"


@pytest.mark.parametrize("replacement", ["symlink", "fifo", "file"])
def test_leaf_replacement_between_stat_and_open_is_rejected(workspace, tmp_path, monkeypatch, replacement):
    path = workspace / "note"
    path.write_text("original")
    outside = tmp_path / "outside"
    outside.write_text("private outside data")
    original_open = os.open
    read = Mock(side_effect=AssertionError("Replacement read"))

    def replace(path_arg, flags, **kwargs):
        if path_arg == "note":
            path.rename(workspace / "original")
            if replacement == "symlink":
                path.symlink_to(outside)
            elif replacement == "fifo":
                assert flags & os.O_NONBLOCK
                os.mkfifo(path)
            else:
                path.write_text("replacement")
        return original_open(path_arg, flags, **kwargs)

    monkeypatch.setattr("os.open", replace)
    monkeypatch.setattr("os.read", read)
    assert FilesystemReadTool().execute({"path": "note"}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    read.assert_not_called()


def test_read_uses_open_file_after_its_path_is_replaced(workspace, tmp_path, monkeypatch):
    path = workspace / "note"
    path.write_text("original")
    outside = tmp_path / "outside"
    outside.write_text("private outside data")
    original_read = os.read

    def replace(descriptor, count):
        if not path.is_symlink():
            path.rename(workspace / "original")
            path.symlink_to(outside)
        return original_read(descriptor, count)

    monkeypatch.setattr("os.read", replace)
    result = FilesystemReadTool().execute({"path": "note"})
    assert result.success and result.data["content"] == "original"


def test_read_error_discards_partial_content_and_closes_file(workspace, monkeypatch, caplog, capsys):
    (workspace / "note").write_text("private contents")
    original_read = os.read
    descriptors = []

    def interrupted(descriptor, count):
        descriptors.append(descriptor)
        if len(descriptors) == 1:
            return original_read(descriptor, 3)
        raise PermissionError("sensitive details")

    monkeypatch.setattr("os.read", interrupted)
    assert FilesystemReadTool().execute({"path": "note"}) == ToolResult(
        success=False, error="Tool execution failed",
    )
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert not caplog.records
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(("risk", "path", "error"), [
    (RiskLevel.READ, "note", None),
    (RiskLevel.DENY, "note", "Tool execution denied"),
    (RiskLevel.READ, "../outside", "Invalid tool arguments"),
])
def test_core_enforces_policy_and_keeps_content_out_of_sqlite(
    workspace, tmp_path, monkeypatch, caplog, risk, path, error,
):
    content = "Violet orchid 4817"
    (workspace / "note").write_text(content)
    registry = build_tool_registry()
    tool = registry.get("filesystem.read")
    assert tool.risk_level is RiskLevel.READ
    tool.risk_level = risk
    execution = Mock(wraps=tool._execute)
    monkeypatch.setattr(tool, "_execute", execution)
    provider = FakeLLMProvider([
        json.dumps({"tool": "filesystem.read", "arguments": {"path": path}}), "Lu.",
    ])
    permission = Mock(return_value=True)
    statements = []
    with closing(TaskHistory(tmp_path / "data")) as history:
        history._connection.set_trace_callback(statements.append)
        core = Core(provider, history, registry=registry, permission_handler=permission)
        assert core.chat("Lire mon fichier") == "Lu."
        result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
        saved = history.recent()[0]["tools"][0]["result"]
        assert result["error"] == error and result["success"] is (error is None)
        if error is None:
            assert result["data"] == {"workspace": str(workspace), "path": "note", "content": content, "size_bytes": len(content)}
            assert saved["data"] == {
                **result["data"], "content": "[contenu du fichier non conservé]",
            }
            assert execution.call_count == 1
        else:
            assert result["data"] is None and saved["error"] == error
            execution.assert_not_called()
        if risk is RiskLevel.READ:
            permission.assert_not_called()
    assert all(content not in statement for statement in statements)
    assert content.encode() not in (tmp_path / "data/history.sqlite3").read_bytes()
    assert not caplog.records
