"""Configured allowlists across filesystem tools, Core and daemon, without sockets."""

from contextlib import closing, contextmanager
from io import BytesIO
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from aios import daemon
from aios.core import Core, build_tool_registry
from aios.filesystem_list import FilesystemListTool
from aios.filesystem_mkdir import FilesystemMkdirTool
from aios.filesystem_read import FilesystemReadTool
from aios.filesystem_update import FilesystemUpdateTool
from aios.filesystem_write import FilesystemWriteTool
from aios.history import TaskHistory
from aios.llm import FakeLLMProvider
from aios.policy import PolicyDecision
from aios.system_prompt import build_system_prompt
from aios.tools import RiskLevel, ToolResult


TOOL_TYPES = [FilesystemListTool, FilesystemReadTool, FilesystemMkdirTool, FilesystemWriteTool, FilesystemUpdateTool]


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = (tmp_path / "first", tmp_path / "second")
    for root in (*result, tmp_path / "AIOS-Workspace", tmp_path / "outside", tmp_path / "first-other"):
        root.mkdir()
        (root / "note.txt").write_text(root.name)
    return result


def arguments_for(tool_type):
    if tool_type is FilesystemListTool:
        return {}
    if tool_type in (FilesystemReadTool, FilesystemUpdateTool):
        args = {"path": "note.txt"}
    else:
        args = {"path": "new"}
    if tool_type in (FilesystemWriteTool, FilesystemUpdateTool):
        args["content"] = "texte"
    return args


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
@pytest.mark.parametrize("selection", [None, 0, 1])
def test_all_tools_use_only_selected_configured_root(roots, tmp_path, monkeypatch, tool_type, selection):
    args = arguments_for(tool_type)
    chosen = roots[0 if selection is None else selection]
    other = roots[1 if chosen == roots[0] else 0]
    if selection is not None:
        args["workspace"] = str(chosen)
    authorize = Mock(return_value=True)
    monkeypatch.chdir(tmp_path / "outside")
    result = tool_type(filesystem_roots=roots).execute(args, authorize=authorize)
    assert result.success and result.data["workspace"] == str(chosen)
    expected = {**args, "workspace": str(chosen)}
    if tool_type is FilesystemListTool:
        expected["path"] = "."
        assert [entry["name"] for entry in result.data["entries"]] == ["note.txt"]
    elif tool_type is FilesystemReadTool:
        assert result.data["content"] == chosen.name
    elif tool_type is FilesystemMkdirTool:
        assert (chosen / "new").is_dir()
    elif tool_type is FilesystemWriteTool:
        assert (chosen / "new").read_text() == "texte"
    else:
        assert (chosen / "note.txt").read_text() == "texte"
        assert (chosen / result.data["backup_path"]).read_text() == chosen.name
    authorize.assert_called_once_with(expected)
    for untouched in (other, tmp_path / "AIOS-Workspace", tmp_path / "outside", tmp_path / "first-other"):
        assert list(untouched.iterdir()) == [untouched / "note.txt"]
        assert (untouched / "note.txt").read_text() == untouched.name


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
@pytest.mark.parametrize("selection", ["outside", "default", "prefix", "child", "traversal", "relative", "tilde", "invalid-type", "null"])
def test_unlisted_workspace_is_rejected_before_confirmation_or_access(roots, tmp_path, monkeypatch, tool_type, selection):
    values = {"outside": str(tmp_path / "outside"), "default": str(tmp_path / "AIOS-Workspace"),
              "prefix": str(tmp_path / "first-other"), "child": str(roots[0] / "child"),
              "traversal": str(roots[0]) + "/../outside", "relative": "first", "tilde": "~/first",
              "invalid-type": [str(roots[0])], "null": None}
    tool = tool_type(filesystem_roots=roots)
    authorize = Mock(return_value=True)
    opened = Mock(side_effect=AssertionError("Unauthorized filesystem access"))
    monkeypatch.setattr("os.open", opened)
    result = tool.execute({**arguments_for(tool_type), "workspace": values[selection]}, authorize=authorize)
    assert result == ToolResult(success=False, error="Invalid tool arguments")
    opened.assert_not_called()
    authorize.assert_not_called()


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
@pytest.mark.parametrize("explicit", [False, True])
def test_empty_allowlist_disables_every_filesystem_tool(roots, monkeypatch, tool_type, explicit):
    tool = tool_type(filesystem_roots=())
    args = arguments_for(tool_type)
    if explicit:
        args["workspace"] = str(roots[0])
    opened = Mock(side_effect=AssertionError("Empty allowlist must not open a directory"))
    authorize = Mock(return_value=True)
    monkeypatch.setattr("os.open", opened)
    assert tool.execute(args, authorize=authorize) == ToolResult(success=False, error="Invalid tool arguments")
    opened.assert_not_called()
    authorize.assert_not_called()


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
@pytest.mark.parametrize("path", ["../outside/note.txt", "/etc/passwd", "sub/../../note.txt"])
def test_relative_path_guards_remain_active_for_other_roots(roots, monkeypatch, tool_type, path):
    opened = Mock(side_effect=AssertionError("Unsafe path must not open a directory"))
    authorize = Mock(return_value=True)
    monkeypatch.setattr("os.open", opened)
    result = tool_type(filesystem_roots=roots).execute(
        {**arguments_for(tool_type), "workspace": str(roots[1]), "path": path}, authorize=authorize,
    )
    assert result == ToolResult(success=False, error="Invalid tool arguments")
    opened.assert_not_called()
    authorize.assert_not_called()


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
@pytest.mark.parametrize("location", ["root", "parent"])
def test_configured_symlinks_do_not_grant_access_to_their_targets(roots, tmp_path, tool_type, location):
    selected = roots[1]
    if location == "root":
        selected.rename(tmp_path / "saved")
        selected.symlink_to(tmp_path / "outside", target_is_directory=True)
        args = arguments_for(tool_type)
    else:
        (selected / "link").symlink_to(tmp_path / "outside", target_is_directory=True)
        args = arguments_for(tool_type)
        args["path"] = "link/" + args.get("path", "note.txt")
    result = tool_type(filesystem_roots=roots).execute({**args, "workspace": str(selected)}, authorize=lambda _: True)
    assert result == ToolResult(success=False, error="Tool execution failed")
    assert list((tmp_path / "outside").iterdir()) == [tmp_path / "outside/note.txt"]
    assert (tmp_path / "outside/note.txt").read_text() == "outside"


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
def test_missing_first_root_does_not_fall_back_or_get_created(roots, tmp_path, tool_type):
    missing = tmp_path / "missing"
    result = tool_type(filesystem_roots=(missing, roots[0])).execute(arguments_for(tool_type), authorize=lambda _: True)
    assert result == ToolResult(success=False, error="Tool execution failed")
    assert not missing.exists()
    assert list(roots[0].iterdir()) == [roots[0] / "note.txt"]


def test_allowlists_are_copied_and_explicit_python_workspace_remains_supported(roots, tmp_path):
    configured = list(roots)
    tool = FilesystemListTool(filesystem_roots=configured)
    configured.append(tmp_path / "outside")
    assert not tool.execute({"workspace": str(tmp_path / "outside")}).success
    assert FilesystemReadTool(roots[1]).execute({"path": "note.txt"}).data["content"] == "second"
    with pytest.raises(ValueError):
        FilesystemListTool(roots[0], filesystem_roots=roots)


@pytest.mark.parametrize("accepted", [False, True])
def test_core_confirmation_cannot_change_the_root_and_history_identifies_it(roots, tmp_path, accepted):
    args = {"path": "new", "content": "Orchid 8253"}
    provider = FakeLLMProvider([json.dumps({"tool": "filesystem.write", "arguments": args}), "Terminé"])
    confirmations = []

    def authorize(decision, name, values):
        confirmations.append((decision, name, values.copy()))
        values["workspace"] = str(tmp_path / "outside")
        return accepted

    with closing(TaskHistory(tmp_path / "history")) as history:
        core = Core(provider, history, filesystem_roots=roots, permission_handler=authorize)
        assert core.chat("Créer le fichier") == "Terminé"
        result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
        saved = history.recent()[0]["tools"][0]
        assert result["success"] is accepted
        assert saved["arguments"]["content"] == "[contenu du fichier non conservé]"
        if accepted:
            assert saved["result"]["data"]["workspace"] == str(roots[0])
            assert (roots[0] / "new").read_text() == args["content"]
        else:
            assert not (roots[0] / "new").exists()
    assert confirmations == [(PolicyDecision.CONFIRM, "filesystem.write", {**args, "workspace": str(roots[0])})]
    assert not (tmp_path / "outside/new").exists()
    assert provider.calls[0][0]["content"] == build_system_prompt(roots)


def test_explicit_root_cannot_bypass_deny_or_authorize_a_new_root(roots, tmp_path):
    registry = build_tool_registry(filesystem_roots=roots)
    registry.get("filesystem.mkdir").risk_level = RiskLevel.DENY
    args = {"path": "new", "workspace": str(roots[1])}
    provider = FakeLLMProvider([json.dumps({"tool": "filesystem.mkdir", "arguments": args}), "Refus"])
    handler = Mock(return_value=True)
    with closing(TaskHistory(tmp_path / "history")) as history:
        Core(provider, history, registry=registry, filesystem_roots=roots, permission_handler=handler).chat("Créer")
    handler.assert_called_once_with(PolicyDecision.DENY, "filesystem.mkdir", args)
    assert not (roots[1] / "new").exists()
    result = registry.execute("filesystem.mkdir", {**args, "filesystem_roots": [str(tmp_path)]}, authorize=lambda _: True)
    assert result == ToolResult(success=False, error="Invalid tool arguments")


def test_core_sessions_keep_distinct_configured_roots(roots, tmp_path):
    providers = [FakeLLMProvider(['{"tool":"filesystem.read","arguments":{"path":"note.txt"}}', "Lu"]) for _ in roots]
    with closing(TaskHistory(tmp_path / "history")) as history:
        cores = [Core(provider, history, filesystem_roots=(root,)) for root, provider in zip(roots, providers)]
        for core, provider, root in zip(cores, providers, roots):
            assert core.chat("Lire") == "Lu"
            result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
            assert result["data"]["workspace"] == str(root) and result["data"]["content"] == root.name


class MemoryConnection:
    def __init__(self, requests):
        self.stream = BytesIO(b"".join(json.dumps(item).encode() + b"\n" for item in requests))
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.stream.close()

    def makefile(self, mode):
        assert mode == "rb"
        return self.stream

    def settimeout(self, timeout):
        pass

    def sendall(self, payload):
        self.sent.append(json.loads(payload))


@pytest.mark.parametrize("scenario", ["default-root", "second-root", "unlisted", "empty", "client-override", "confirmed", "refused"])
def test_daemon_loads_and_enforces_its_config_with_in_memory_transport(roots, tmp_path, monkeypatch, scenario):
    config = tmp_path / "settings.toml"
    configured = [] if scenario == "empty" else [str(root) for root in roots]
    config.write_text('data_dir = ' + json.dumps(str(tmp_path / "data")) + '\nfilesystem_roots = ' + json.dumps(configured) + '\n')
    modifying = scenario in {"confirmed", "refused"}
    args = {"path": "new" if modifying else "note.txt"}
    if scenario == "second-root" or modifying:
        args["workspace"] = str(roots[1])
    elif scenario == "unlisted":
        args["workspace"] = str(tmp_path / "AIOS-Workspace")
    if modifying:
        args["content"] = "nouveau"
    call = {"tool": "filesystem.write" if modifying else "filesystem.read", "arguments": args}
    provider = FakeLLMProvider([json.dumps(call), "Résultat reçu"])
    request = {"method": "chat", "message": "Traiter le fichier", "confirmations": True}
    if scenario == "client-override":
        request["filesystem_roots"] = [str(tmp_path / "outside")]
    requests = [request]
    if modifying:
        requests.append({"method": "confirm", "id": "consent-id", "accepted": scenario == "confirmed"})
    connection = MemoryConnection(requests)

    @contextmanager
    def listener(_path):
        yield Mock(accept=Mock(side_effect=[(connection, None), KeyboardInterrupt]))

    monkeypatch.setattr(daemon, "_listener", listener)
    monkeypatch.setattr(daemon, "OllamaProvider", lambda _config: provider)
    monkeypatch.setattr(daemon.secrets, "token_hex", lambda _size: "consent-id")
    assert daemon.main(["--config", str(config)]) == 0
    if scenario == "client-override":
        assert connection.sent == [{"ok": False, "error": "Invalid request"}]
        assert provider.calls == []
    else:
        assert connection.sent[-1] == {"ok": True, "result": "Résultat reçu"}
        assert provider.calls[0][0]["content"] == build_system_prompt(tuple(Path(root) for root in configured))
        result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
        assert result["success"] is (scenario in {"default-root", "second-root", "confirmed"})
        if scenario in {"default-root", "second-root"}:
            assert result["data"]["content"] == ("first" if scenario == "default-root" else "second")
        if modifying:
            assert connection.sent[0]["event"] == "confirmation"
            assert connection.sent[0]["arguments"] == args
            assert (roots[1] / "new").exists() is (scenario == "confirmed")
    assert (tmp_path / "AIOS-Workspace/note.txt").read_text() == "AIOS-Workspace"
    assert (tmp_path / "outside/note.txt").read_text() == "outside"
    assert not (tmp_path / "outside/new").exists()
