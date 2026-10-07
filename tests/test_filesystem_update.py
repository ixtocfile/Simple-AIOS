"""Confirmed replacement, private backups and failures on temporary files only."""

from contextlib import closing
import json
import os
import stat
from unittest.mock import Mock

import pytest

from aios.core import Core, build_tool_registry
from aios.filesystem_read import FilesystemReadTool
from aios.filesystem_update import BACKUP_PREFIX, MAX_UPDATE_BYTES, FilesystemUpdateTool
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


def update(path="notes.txt", content="nouveau"):
    return FilesystemUpdateTool().execute({"path": path, "content": content}, authorize=lambda _: True)


@pytest.mark.parametrize(("previous", "content"), [
    (b"", "Bonjour"), (b"long previous text", ""), (b"long previous text", "court"),
    ("\ufeffété\r\n\t🙂".encode(), "\ufeffnouveau\r\n\t🙂"),
    (b"a" * 65536, "b" * 65536), ("é".encode() * 32768, "🙂" * 16384),
], ids=["empty-original", "empty-new", "shorter", "utf8", "ascii-limit", "utf8-limit"])
def test_atomic_update_preserves_exact_backup_and_reports_real_result(workspace, tmp_path, monkeypatch, previous, content):
    folder = workspace / "dossier été"
    folder.mkdir()
    path = folder / "notes.txt"
    path.write_bytes(previous)
    before = path.stat()
    monkeypatch.chdir(tmp_path)
    with path.open("rb") as old_descriptor:
        result = update("dossier été/notes.txt", content)
        assert result.success and result.error is None
        backup_path = result.data["backup_path"]
        assert result.data == {"path": "dossier été/notes.txt", "updated": True,
                               "size_bytes": len(content.encode()), "backup_path": backup_path}
        assert old_descriptor.read() == previous  # The old inode was never truncated.
    backup = workspace / backup_path
    assert backup.parent.parent == folder and backup.parent.name.startswith(BACKUP_PREFIX)
    assert backup.name == "backup.txt" and backup.read_bytes() == previous
    assert list(backup.parent.iterdir()) == [backup]
    assert stat.S_IMODE(backup.parent.stat().st_mode) & 0o077 == 0
    assert stat.S_IMODE(backup.stat().st_mode) & 0o177 == 0
    after = path.stat()
    assert before.st_ino != after.st_ino
    assert (after.st_mode, after.st_uid, after.st_gid) == (before.st_mode, before.st_uid, before.st_gid)
    assert path.read_bytes() == content.encode()
    assert FilesystemReadTool().execute({"path": backup_path}).data["content"] == previous.decode()


@pytest.mark.parametrize(("mode", "mask"), [(0o600, 0o022), (0o640, 0o077), (0o755, 0o027)])
def test_preserves_original_permissions_and_keeps_preparation_private(workspace, monkeypatch, mode, mask):
    path = workspace / "notes.txt"
    path.write_text("before")
    path.chmod(mode)
    previous_mask = os.umask(mask)
    replace = os.replace

    def inspected_replace(source, target, **kwargs):
        backup_dir = next(workspace.glob(BACKUP_PREFIX + "*"))
        assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700 & ~mask
        assert stat.S_IMODE((backup_dir / "backup.txt").stat().st_mode) == 0o600 & ~mask
        assert path.read_text() == "before"
        return replace(source, target, **kwargs)

    monkeypatch.setattr("os.replace", inspected_replace)
    try:
        result = update()
    finally:
        restored = os.umask(previous_mask)
    assert restored == mask and result.success
    assert stat.S_IMODE(path.stat().st_mode) == mode


def test_each_update_keeps_an_independent_backup(workspace):
    path = workspace / "notes.txt"
    path.write_text("first")
    first = update(content="second")
    second = update(content="third")
    assert first.success and second.success
    assert first.data["backup_path"] != second.data["backup_path"]
    assert (workspace / first.data["backup_path"]).read_text() == "first"
    assert (workspace / second.data["backup_path"]).read_text() == "second"
    assert path.read_text() == "third"


@pytest.mark.parametrize("arguments", [
    {}, {"path": "notes"}, {"content": "text"}, {"path": "notes", "content": "text", "confirmed": True},
    *({"path": p, "content": "text"} for p in [None, 0, "", ".", "..", "/etc/passwd", "../notes",
        "a/../notes", "a/./notes", "a//notes", "notes/", "a\\notes", "notes\n", "notes\0", "notes\ud800",
        ".aios-update-old/backup.txt", "folder/.aios-update-old", "é" * 2049]),
    *({"path": "notes", "content": c} for c in [None, True, 1, [], {}, b"text", "x\ud800", "x\0", "\x1b[31m", "\x7f"]),
    pytest.param({"path": "notes", "content": "a" * (MAX_UPDATE_BYTES + 1)}, id="too-many-characters"),
    pytest.param({"path": "notes", "content": "é" * (MAX_UPDATE_BYTES // 2 + 1)}, id="too-many-bytes"),
])
def test_invalid_arguments_never_authorize_or_access_files(workspace, monkeypatch, arguments):
    authorize = Mock(return_value=True)
    access = Mock(side_effect=AssertionError("Unexpected access"))
    monkeypatch.setattr("os.open", access)
    monkeypatch.setattr("os.mkdir", access)
    assert FilesystemUpdateTool().execute(arguments, authorize=authorize) == ToolResult(
        success=False, error="Invalid tool arguments",
    )
    authorize.assert_not_called()
    access.assert_not_called()


@pytest.mark.parametrize("answer", [False, None, 1, "oui"])
def test_confirmation_requires_boolean_true(workspace, monkeypatch, answer):
    access = Mock(side_effect=AssertionError("Unexpected access"))
    monkeypatch.setattr("os.open", access)
    result = FilesystemUpdateTool().execute({"path": "notes", "content": "new"}, authorize=lambda _: answer)
    assert result == ToolResult(success=False, error="Tool execution denied")
    access.assert_not_called()


@pytest.mark.parametrize("use_registry", [False, True])
def test_direct_and_registry_calls_without_authorization_are_denied(workspace, monkeypatch, use_registry):
    tool = FilesystemUpdateTool()
    registry = ToolRegistry()
    registry.register(tool)
    access = Mock(side_effect=AssertionError("Unexpected access"))
    monkeypatch.setattr("os.open", access)
    arguments = {"path": "notes", "content": "new"}
    result = registry.execute(tool.name, arguments) if use_registry else tool.execute(arguments)
    assert result == ToolResult(success=False, error="Tool execution denied")
    access.assert_not_called()


def test_confirmation_sees_exact_arguments_and_cannot_change_them(workspace, monkeypatch):
    path = workspace / "notes.txt"
    path.write_text("previous")
    opened = Mock(wraps=os.open)
    monkeypatch.setattr("os.open", opened)
    arguments = {"path": "notes.txt", "content": "new"}

    def authorize(preview):
        opened.assert_not_called()
        assert preview == arguments
        preview.update(path="../outside", content="tampered")
        return True

    result = FilesystemUpdateTool().execute(arguments, authorize=authorize)
    assert result.success and path.read_text() == "new"
    assert arguments == {"path": "notes.txt", "content": "new"}
    assert not (workspace.parent / "outside").exists()


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "broken", "hardlink", "fifo",
    "invalid-utf8", "binary", "oversized", "readonly", "setuid", "setgid", "sticky", "foreign-owner", "xattr"])
def test_unsuitable_original_is_never_modified_or_backed_up(workspace, tmp_path, monkeypatch, kind):
    path = workspace / "notes.txt"
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep outside")
    if kind == "directory":
        path.mkdir()
    elif kind in {"symlink", "broken"}:
        path.symlink_to(outside if kind == "symlink" else tmp_path / "missing")
    elif kind == "hardlink":
        os.link(outside, path)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind != "missing":
        content = {"invalid-utf8": b"\xff", "binary": b"bad\0text", "oversized": b"x" * 65537}.get(kind, b"keep")
        path.write_bytes(content)
        if kind in {"readonly", "setuid", "setgid", "sticky"}:
            path.chmod({"readonly": 0o400, "setuid": 0o4600, "setgid": 0o2600, "sticky": 0o1600}[kind])
        if kind == "foreign-owner":
            monkeypatch.setattr("os.geteuid", lambda: path.stat().st_uid + 1)
        if kind == "xattr":
            os.setxattr(path, "user.test", b"must be preserved")
    before = path.lstat() if kind != "missing" else None
    mutate = Mock(side_effect=AssertionError("Unexpected mutation"))
    monkeypatch.setattr("os.write", mutate)
    monkeypatch.setattr("os.mkdir", mutate)
    assert update() == ToolResult(success=False, error="Tool execution failed")
    mutate.assert_not_called()
    assert list(workspace.glob(BACKUP_PREFIX + "*")) == []
    assert outside.read_bytes() == b"keep outside"
    if before is None:
        assert not path.exists()
    else:
        after = path.lstat()
        assert (after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns) == (
            before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns,
        )


@pytest.mark.parametrize("location", ["workspace", "ancestor", "parent", "internal", "broken"])
def test_no_symlink_component_is_followed(tmp_path, location):
    root = tmp_path / "home/workspace"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.txt").write_text("keep")
    path = "notes.txt"
    if location == "workspace":
        root.rmdir()
        root.symlink_to(outside, target_is_directory=True)
    elif location == "ancestor":
        root.parent.rename(tmp_path / "original-home")
        root.parent.symlink_to(outside, target_is_directory=True)
        (outside / "workspace").mkdir()
        (outside / "workspace/notes.txt").write_text("keep")
    else:
        target = outside
        if location == "internal":
            target = root / "inside"
            target.mkdir()
            (target / "notes.txt").write_text("keep")
        elif location == "broken":
            target = outside / "missing"
        (root / "link").symlink_to(target, target_is_directory=True)
        path = "link/notes.txt"
    result = FilesystemUpdateTool(root).execute({"path": path, "content": "new"}, authorize=lambda _: True)
    assert result == ToolResult(success=False, error="Tool execution failed")
    assert all(p.read_text() == "keep" for p in tmp_path.rglob("notes.txt"))
    assert not list(tmp_path.rglob(BACKUP_PREFIX + "*"))


@pytest.mark.parametrize("where", ["workspace", "parent", "file-parent"])
def test_missing_parents_are_not_created(workspace, where):
    if where == "workspace":
        workspace.rmdir()
    elif where == "file-parent":
        (workspace / "parent").write_text("keep")
    assert update("parent/notes.txt") == ToolResult(success=False, error="Tool execution failed")
    assert not (workspace / "parent/notes.txt").exists()
    assert not list(workspace.glob(BACKUP_PREFIX + "*"))


def test_literal_names_and_content_do_not_execute_commands(workspace, monkeypatch, caplog, capsys):
    name = "literal $(id);*.txt"
    (workspace / name).write_text("old")
    blocked = Mock(side_effect=AssertionError("Unexpected shell or deletion"))
    for function in ("os.system", "os.popen", "subprocess.Popen", "os.unlink", "os.remove", "os.rmdir", "os.truncate", "os.ftruncate"):
        monkeypatch.setattr(function, blocked)
    result = update(name, "$(id); secret-free text")
    assert result.success and (workspace / name).read_text() == "$(id); secret-free text"
    blocked.assert_not_called()
    assert not caplog.records and capsys.readouterr() == ("", "")


def test_short_reads_and_writes_complete_before_replacement(workspace, monkeypatch):
    previous = "é🙂ancien".encode()
    (workspace / "notes.txt").write_bytes(previous)
    original_read, original_write = os.read, os.write
    monkeypatch.setattr("os.read", lambda fd, count: original_read(fd, min(count, 2)))
    monkeypatch.setattr("os.write", lambda fd, data: original_write(fd, data[:2]))
    result = update(content="🙂nouveau")
    assert result.success
    assert (workspace / result.data["backup_path"]).read_bytes() == previous
    assert (workspace / "notes.txt").read_bytes() == "🙂nouveau".encode()


@pytest.mark.parametrize("kind", ["symlink", "fifo", "file"])
def test_original_replaced_before_open_is_rejected(workspace, tmp_path, monkeypatch, kind):
    path = workspace / "notes.txt"
    path.write_text("keep")
    outside = tmp_path / "outside"
    outside.write_text("outside")
    opened = os.open

    def race(name, flags, **kwargs):
        if name == "notes.txt":
            path.rename(workspace / "moved.txt")
            if kind == "symlink":
                path.symlink_to(outside)
            elif kind == "fifo":
                os.mkfifo(path)
            else:
                path.write_text("replacement")
        return opened(name, flags, **kwargs)

    monkeypatch.setattr("os.open", race)
    assert update() == ToolResult(success=False, error="Tool execution failed")
    assert (workspace / "moved.txt").read_text() == "keep"
    assert outside.read_text() == "outside"
    assert not list(workspace.glob(BACKUP_PREFIX + "*"))


@pytest.mark.parametrize("change", ["same-size", "grow", "mode", "hardlink"])
def test_original_changed_while_reading_is_rejected(workspace, monkeypatch, change):
    path = workspace / "notes.txt"
    path.write_text("previous")
    original_read = os.read
    changed = False

    def read(fd, count):
        nonlocal changed
        if not changed:
            changed = True
            if change == "same-size":
                path.write_text("modified")
            elif change == "grow":
                path.write_bytes(b"x" * (MAX_UPDATE_BYTES + 1))
            elif change == "mode":
                path.chmod(0o600)
            else:
                os.link(path, workspace / "linked")
        return original_read(fd, count)

    monkeypatch.setattr("os.read", read)
    assert update() == ToolResult(success=False, error="Tool execution failed")
    assert not list(workspace.glob(BACKUP_PREFIX + "*"))


@pytest.mark.parametrize("change", ["edit", "replace", "symlink", "hardlink", "delete", "backup", "temporary", "backup-directory"])
def test_changes_during_preparation_abort_before_replacement(workspace, tmp_path, monkeypatch, change):
    path = workspace / "notes.txt"
    path.write_text("before")
    outside = tmp_path / "outside"
    outside.write_text("outside")
    sync = os.fsync
    replace = Mock(side_effect=AssertionError("Changed target must not be replaced"))
    calls = 0

    def race(fd):
        nonlocal calls
        sync(fd)
        calls += 1
        if calls != 4:  # Replacement fully written, before final checks.
            return
        folder = next(workspace.glob(BACKUP_PREFIX + "*"))
        if change == "edit":
            path.write_text("concurrent")
        elif change == "delete":
            path.unlink()
        elif change == "hardlink":
            os.link(path, workspace / "linked")
        elif change == "backup":
            (folder / "backup.txt").write_text("tampered")
        elif change == "temporary":
            (folder / "replacement.tmp").unlink()
            (folder / "replacement.tmp").symlink_to(outside)
        elif change == "backup-directory":
            folder.rename(workspace / "moved")
            folder.symlink_to(outside)
        else:
            path.rename(workspace / "moved.txt")
            if change == "replace":
                path.write_text("concurrent")
            else:
                path.symlink_to(outside)

    monkeypatch.setattr("os.fsync", race)
    monkeypatch.setattr("os.replace", replace)
    assert update() == ToolResult(success=False, error="Tool execution failed")
    replace.assert_not_called()
    assert outside.read_text() == "outside"
    if change in {"edit", "replace"}:
        assert path.read_text() == "concurrent"
    elif change not in {"delete", "symlink"}:
        assert path.read_text() == "before"


def test_swapped_parent_path_cannot_redirect_the_update(workspace, tmp_path, monkeypatch):
    parent = workspace / "parent"
    parent.mkdir()
    (parent / "notes.txt").write_text("before")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.txt").write_text("outside")
    mkdir = os.mkdir

    def race(name, mode=0o777, **kwargs):
        parent.rename(workspace / "original-parent")
        parent.symlink_to(outside, target_is_directory=True)
        return mkdir(name, mode=mode, **kwargs)

    monkeypatch.setattr("os.mkdir", race)
    result = update("parent/notes.txt")
    assert result.success
    assert (workspace / "original-parent/notes.txt").read_text() == "nouveau"
    assert (outside / "notes.txt").read_text() == "outside"
    assert list(outside.iterdir()) == [outside / "notes.txt"]


def test_backup_directory_collision_does_not_overwrite_any_entry(workspace, monkeypatch):
    (workspace / "notes.txt").write_text("before")
    (workspace / (BACKUP_PREFIX + "fixed")).symlink_to(workspace / "notes.txt")
    monkeypatch.setattr("aios.filesystem_update.uuid4", lambda: Mock(hex="fixed"))
    assert update() == ToolResult(success=False, error="Tool execution failed")
    assert (workspace / "notes.txt").read_text() == "before"


@pytest.mark.parametrize("failure", ["backup-write", "backup-sync", "backup-close", "directory-sync",
    "replacement-write", "replacement-sync", "replacement-close", "mode", "inherited-acl", "zero-write", "interrupt"])
def test_preparation_failure_preserves_original_and_closes_descriptors(workspace, monkeypatch, caplog, failure):
    path = workspace / "notes.txt"
    path.write_text("before")
    before = path.stat()
    opened, written, sync, close = os.open, os.write, os.fsync, os.close
    descriptors = []
    names = {}

    def open_file(name, flags, **kwargs):
        assert not flags & (os.O_TRUNC | os.O_APPEND)
        descriptor = opened(name, flags, **kwargs)
        descriptors.append(descriptor)
        names[descriptor] = name
        return descriptor

    def write(fd, data):
        name = names[fd]
        if failure == "zero-write":
            return 0
        if failure == "interrupt" and name == "replacement.tmp":
            raise KeyboardInterrupt
        if (failure, name) in {("backup-write", "backup.txt"), ("replacement-write", "replacement.tmp")}:
            written(fd, data[:1])
            raise OSError("private failure detail")
        return written(fd, data)

    def fsync(fd):
        name = names[fd]
        if (failure, name) in {("backup-sync", "backup.txt"), ("replacement-sync", "replacement.tmp")}:
            raise OSError("private failure detail")
        if failure == "directory-sync" and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("private failure detail")
        return sync(fd)

    def close_file(fd):
        close(fd)
        name = names[fd]
        if (failure, name) in {("backup-close", "backup.txt"), ("replacement-close", "replacement.tmp")}:
            raise OSError("private failure detail")

    replace = Mock(side_effect=AssertionError("Original must survive preparation failure"))
    with monkeypatch.context() as patch:
        patch.setattr("os.open", open_file)
        patch.setattr("os.write", write)
        patch.setattr("os.fsync", fsync)
        patch.setattr("os.close", close_file)
        patch.setattr("os.replace", replace)
        if failure == "mode":
            patch.setattr("os.fchmod", Mock(side_effect=OSError("private mode detail")))
        if failure == "inherited-acl":
            patch.setattr("os.listxattr", lambda fd: ["system.posix_acl_access"] if names[fd] == "replacement.tmp" else [])
        if failure == "interrupt":
            with pytest.raises(KeyboardInterrupt):
                update()
        else:
            assert update() == ToolResult(success=False, error="Tool execution failed")
    replace.assert_not_called()
    assert path.read_bytes() == b"before" and path.stat().st_ino == before.st_ino
    for descriptor in set(descriptors):
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert not caplog.records


@pytest.mark.parametrize("failure", ["replace", "sync-after-replace", "close-after-replace"])
def test_uncertain_commit_failure_keeps_backup_and_never_reports_success(workspace, monkeypatch, failure):
    path = workspace / "notes.txt"
    path.write_text("before")
    replace, sync, close = os.replace, os.fsync, os.close
    replaced = False

    def rename(*args, **kwargs):
        nonlocal replaced
        if failure == "replace":
            raise OSError("private failure detail")
        replace(*args, **kwargs)
        replaced = True

    def fsync(fd):
        if replaced and failure == "sync-after-replace":
            raise OSError("private failure detail")
        sync(fd)

    def close_file(fd):
        close(fd)
        if replaced and failure == "close-after-replace":
            raise OSError("private failure detail")

    with monkeypatch.context() as patch:
        patch.setattr("os.replace", rename)
        patch.setattr("os.fsync", fsync)
        patch.setattr("os.close", close_file)
        result = update()
    assert result == ToolResult(success=False, error="File update outcome uncertain; inspect file and backup before retrying")
    assert path.read_text() == ("nouveau" if replaced else "before")
    backups = list(workspace.glob(BACKUP_PREFIX + "*/backup.txt"))
    assert len(backups) == 1 and backups[0].read_text() == "before"


@pytest.mark.parametrize("scenario", ["success", "no-handler", "deny", "invalid-path", "invalid-content", "backup-error"])
def test_core_policy_result_and_sqlite_never_persist_file_contents(workspace, tmp_path, monkeypatch, caplog, scenario):
    old_content, new_content = "Orchid violet 4821", "Azure robin 8253"
    (workspace / "notes.txt").write_text(old_content)
    arguments = {"path": "../outside" if scenario == "invalid-path" else "notes.txt", "content": new_content}
    if scenario == "invalid-content":
        arguments["content"] = [new_content]
    registry = build_tool_registry()
    tool = registry.get("filesystem.update")
    assert tool.risk_level is RiskLevel.CONFIRM
    if scenario == "deny":
        tool.risk_level = RiskLevel.DENY
    if scenario == "backup-error":
        monkeypatch.setattr("os.write", Mock(side_effect=OSError(new_content)))
    handler = None if scenario == "no-handler" else Mock(return_value=True)
    reply = json.dumps({"tool": tool.name, "arguments": arguments})
    provider = FakeLLMProvider([reply, "Résultat reçu"])
    statements = []
    with closing(TaskHistory(tmp_path / "data")) as history:
        history._connection.set_trace_callback(statements.append)
        validate = tool.validate_arguments

        def validate_after_insert(values):
            saved = history.recent()[0]["tools"][0]
            assert saved["status"] == "running"
            assert saved["arguments"]["content"] == "[contenu du fichier non conservé]"
            validate(values)

        monkeypatch.setattr(tool, "validate_arguments", validate_after_insert)
        assert Core(provider, history, registry=registry, permission_handler=handler).chat("Modifier le fichier") == "Résultat reçu"
        result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
        saved = history.recent()[0]["tools"][0]
        assert saved["arguments"] == {**arguments, "content": "[contenu du fichier non conservé]"}
        assert saved["result"] == {key: value for key, value in result.items() if key != "tool"}
        assert saved["status"] == ("succeeded" if scenario == "success" else "failed")
    assert result["success"] is (scenario == "success")
    assert (workspace / "notes.txt").read_text() == (new_content if scenario == "success" else old_content)
    if scenario == "success":
        assert (workspace / result["data"]["backup_path"]).read_text() == old_content
    if handler is not None:
        if scenario.startswith("invalid"):
            handler.assert_not_called()
        else:
            decision = PolicyDecision.DENY if scenario == "deny" else PolicyDecision.CONFIRM
            handler.assert_called_once_with(decision, tool.name, arguments)
    assert provider.calls[1][-2] == {"role": "assistant", "content": reply}
    for text in (old_content, new_content):
        assert all(text not in statement for statement in statements)
        assert text.encode() not in (tmp_path / "data/history.sqlite3").read_bytes()
    assert not caplog.records
