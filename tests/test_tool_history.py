"""Persist tool attempts without weakening validation, policy or redaction."""

from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime
import json
import sqlite3
from unittest.mock import Mock

import pytest

from aios.__main__ import main
from aios.core import DIAGNOSTIC_CALLS, build_tool_registry
from aios.config import Config
from aios.history import REDACTED_TASK, TaskHistory
from aios.llm import FakeLLMProvider
from aios.ollama import OllamaError
from aios.tools import RiskLevel, ToolResult


def saved_calls(directory):
    with closing(sqlite3.connect(directory / "history.sqlite3")) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM tool_calls ORDER BY id").fetchall()
    results = []
    for row in rows:
        item = dict(row)
        for field in ("arguments", "result"):
            if item[field] is not None:
                item[field] = json.loads(item[field])
        results.append(item)
    return results


def test_existing_task_database_is_extended_without_losing_tasks_or_pending_calls(tmp_path):
    # Actual schema from step 8.1, with existing history.
    with closing(sqlite3.connect(tmp_path / "history.sqlite3")) as connection, connection:
        connection.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, task TEXT NOT NULL, "
                           "timestamp TEXT NOT NULL, status TEXT NOT NULL)")
        connection.execute("INSERT INTO tasks VALUES (1, 'Ancienne tâche', '2026-10-01T10:00:00+00:00', 'completed')")
    before = datetime.now(UTC)
    with closing(TaskHistory(tmp_path)) as history:
        task_id = history.start("Nouvelle tâche")
        call_id = history.start_tool(task_id, "system.disk", {"path": "a'; DROP TABLE tasks; --"})
        pending = saved_calls(tmp_path)[0]
        assert pending["id"] == call_id and pending["task_id"] == task_id
        assert pending["status"] == "running" and pending["result"] is None
        assert before <= datetime.fromisoformat(pending["timestamp"]) <= datetime.now(UTC)
        assert pending["arguments"] == {"path": "a'; DROP TABLE tasks; --"}
    with closing(TaskHistory(tmp_path)) as history:
        assert saved_calls(tmp_path)[0] == pending
        history.finish_tool(call_id, ToolResult(success=False, error="Tool execution failed"))
        history.finish(task_id, "completed")
    saved = saved_calls(tmp_path)[0]
    assert saved["status"] == "failed"
    assert saved["result"] == {"success": False, "data": None, "error": "Tool execution failed"}
    assert saved["timestamp"] == pending["timestamp"]
    with closing(sqlite3.connect(tmp_path / "history.sqlite3")) as connection:
        assert connection.execute("SELECT * FROM tasks WHERE id = 1").fetchone() == (
            1, "Ancienne tâche", "2026-10-01T10:00:00+00:00", "completed",
        )


def test_tool_records_require_a_running_parent_and_cannot_be_overwritten(tmp_path):
    with closing(TaskHistory(tmp_path)) as history:
        task_id = history.start("Tâche")
        for bad_id in (True, 0, "1", task_id + 10):
            with pytest.raises(ValueError):
                history.start_tool(bad_id, "system.info", {})
        call_id = history.start_tool(task_id, "system.info", {})
        with pytest.raises(TypeError):
            history.finish_tool(call_id, {"success": True})
        with pytest.raises(ValueError):
            history.finish_tool(call_id + 10, None)
        history.finish_tool(call_id, None)
        with pytest.raises(ValueError):
            history.finish_tool(call_id, ToolResult(success=True, data={}))
        history.finish(task_id, "completed")
        with pytest.raises(ValueError):
            history.start_tool(task_id, "system.info", {})
    assert len(saved_calls(tmp_path)) == 1
    assert saved_calls(tmp_path)[0]["status"] == "interrupted"
    assert saved_calls(tmp_path)[0]["result"] is None


@pytest.mark.parametrize("sensitive_key", [
    "password", "api_key", "accessToken", "refresh_token", "Authorization",
    "client-secret", "credentials", "Cookie", "privateKey", "clé privée",
    "accessToken=hidden-name", "pwd",
])
def test_nested_credentials_are_removed_without_mutating_arguments_or_results(tmp_path, sensitive_key):
    arguments = {"path": "/", "limit": 20, "nested": [{sensitive_key: "unmarked-credential", "safe": True}]}
    data = {"count": 2, "nested": [{sensitive_key: {"value": "another-credential"}, "safe": None}]}
    originals = deepcopy((arguments, data))
    with closing(TaskHistory(tmp_path)) as history:
        task_id = history.start("Demande")
        call_id = history.start_tool(task_id, "example.tool", arguments)
        history.finish_tool(call_id, ToolResult(success=True, data=data))
    assert (arguments, data) == originals
    saved = saved_calls(tmp_path)[0]
    assert saved["arguments"]["path"] == "/" and saved["arguments"]["limit"] == 20
    assert saved["arguments"]["nested"][0]["safe"] is True
    assert REDACTED_TASK in saved["arguments"]["nested"][0].values()
    assert saved["result"]["data"]["count"] == 2
    assert saved["status"] == "succeeded"
    raw = (tmp_path / "history.sqlite3").read_bytes()
    assert b"unmarked-credential" not in raw and b"another-credential" not in raw
    assert b"hidden-name" not in raw


def test_sensitive_tool_names_strings_and_errors_are_masked_before_storage(tmp_path):
    with closing(TaskHistory(tmp_path)) as history:
        task_id = history.start("Demande")
        call_id = history.start_tool(task_id, "token=hidden-tool-value", {
            "message": "Bearer hidden-argument-value", "safe": [1, False, None],
        })
        history.finish_tool(call_id, ToolResult(success=False, error="token=hidden-error-value"))
    saved = saved_calls(tmp_path)[0]
    assert saved["tool"] == REDACTED_TASK
    assert saved["arguments"] == {"message": REDACTED_TASK, "safe": [1, False, None]}
    assert saved["result"]["error"] == REDACTED_TASK
    assert b"hidden-" not in (tmp_path / "history.sqlite3").read_bytes()


@pytest.fixture
def tool_session(tmp_path, monkeypatch):
    registry = build_tool_registry()
    executions = {}
    for tool in registry.list_tools():
        execute = Mock(return_value=ToolResult(success=True, data={"observed": tool.name}))
        monkeypatch.setattr(tool, "_execute", execute)
        executions[tool.name] = execute
    monkeypatch.setattr("aios.core.build_tool_registry", lambda: registry)
    monkeypatch.setattr("aios.__main__.load_config", lambda _: Config(data_dir=tmp_path))

    def run(provider, entries):
        reader = Mock(side_effect=entries)
        monkeypatch.setattr("builtins.input", reader)
        monkeypatch.setattr("aios.__main__.OllamaProvider", lambda _: provider)
        code = main([])
        assert reader.call_count == len(entries)
        return code

    return registry, executions, run


def test_cli_commits_attempt_before_validation_and_result_before_followup(tool_session, tmp_path, monkeypatch):
    registry, executions, run = tool_session
    tool = registry.get("system.disk")
    validate = tool.validate_arguments
    observed = []

    def validation(arguments):
        observed.append(saved_calls(tmp_path))
        validate(arguments)

    monkeypatch.setattr(tool, "validate_arguments", validation)
    provider = FakeLLMProvider(['{"tool":"system.disk","arguments":{}}', "Réponse"])
    chat = provider.chat

    def respond(messages):
        if len(provider.calls) == 1:
            assert saved_calls(tmp_path)[0]["status"] == "succeeded"
        return chat(messages)

    provider.chat = respond
    assert run(provider, ["Lis le disque", "/exit"]) == 0
    assert len(observed) == 1 and observed[0][0]["status"] == "running"
    executions["system.disk"].assert_called_once_with({"path": "/"})
    saved = saved_calls(tmp_path)[0]
    assert saved["arguments"] == {}  # Requested arguments, before normalization.
    assert saved["result"] == {"success": True, "data": {"observed": "system.disk"}, "error": None}


@pytest.mark.parametrize(("reply", "risk", "error"), [
    ('{"tool":', RiskLevel.READ, "Invalid tool call"),
    ('{"tool":"unknown.tool","arguments":{}}', RiskLevel.READ, "Unknown tool"),
    ('{"tool":"system.info","arguments":{"extra":1}}', RiskLevel.READ, "Invalid tool arguments"),
    ('{"tool":"system.info","arguments":{}}', RiskLevel.DENY, "Tool execution denied"),
    ('{"tool":"system.info","arguments":{}}', RiskLevel.CONFIRM, "Tool execution denied"),
])
def test_invalid_and_refused_calls_are_recorded_without_execution(tool_session, tmp_path, monkeypatch, reply, risk, error):
    registry, executions, run = tool_session
    monkeypatch.setattr(registry.get("system.info"), "risk_level", risk)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    provider = FakeLLMProvider([reply, "Refus reçu"])
    assert run(provider, ["Demande", "/exit"]) == 0
    saved = saved_calls(tmp_path)
    assert len(saved) == 1 and saved[0]["status"] == "failed"
    assert saved[0]["result"]["error"] == error
    assert all(execute.call_count == 0 for execute in executions.values())
    if error == "Invalid tool call":
        assert saved[0]["tool"] is None and saved[0]["arguments"] is None


@pytest.mark.parametrize("failure", ["execution", "serialization", "interruption"])
def test_tool_errors_and_interruptions_have_honest_persistent_outcomes(tool_session, tmp_path, failure):
    _, executions, run = tool_session
    execute = executions["system.info"]
    if failure == "execution":
        execute.side_effect = RuntimeError("private exception detail")
    elif failure == "serialization":
        execute.return_value = ToolResult(success=True, data={"invalid": object()})
    else:
        execute.side_effect = KeyboardInterrupt
    provider = FakeLLMProvider(['{"tool":"system.info","arguments":{}}', "Réponse"])
    entries = ["Demande"] + ([] if failure == "interruption" else ["/exit"])
    assert run(provider, entries) == 0
    saved = saved_calls(tmp_path)[0]
    assert execute.call_count == 1
    if failure == "interruption":
        assert saved["status"] == "interrupted" and saved["result"] is None
    else:
        assert saved["status"] == "failed"
        error = "Tool execution failed" if failure == "execution" else "Invalid tool result"
        assert saved["result"]["error"] == error
    assert b"private exception detail" not in (tmp_path / "history.sqlite3").read_bytes()


@pytest.mark.parametrize("answer", ["oui", "non"])
def test_restart_confirmation_stays_required_and_is_not_stored(tool_session, tmp_path, monkeypatch, answer):
    _, executions, run = tool_session
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    provider = FakeLLMProvider(['{"tool":"systemd.restart","arguments":{"service":"demo.service"}}', "Réponse"])
    assert run(provider, ["Redémarre le service", answer, "/exit"]) == 0
    saved = saved_calls(tmp_path)[0]
    assert saved["arguments"] == {"service": "demo.service"}
    assert saved["status"] == ("succeeded" if answer == "oui" else "failed")
    assert executions["systemd.restart"].call_count == int(answer == "oui")
    assert answer not in repr(saved)


def test_five_diagnostic_checks_and_five_loop_attempts_link_to_their_tasks(tool_session, tmp_path):
    _, executions, run = tool_session
    call = '{"tool":"system.info","arguments":{}}'
    provider = FakeLLMProvider([call, *([call] * 6)])
    assert run(provider, ["/diagnose", "Demande bornée", "/exit"]) == 0
    saved = saved_calls(tmp_path)
    assert len(saved) == 10
    assert [item["tool"] for item in saved[:5]] == [name for name, _ in DIAGNOSTIC_CALLS]
    assert [item["arguments"] for item in saved[:5]] == [arguments for _, arguments in DIAGNOSTIC_CALLS]
    assert [item["task_id"] for item in saved] == [1] * 5 + [2] * 5
    assert all(item["status"] == "succeeded" for item in saved)
    assert executions["system.info"].call_count == 6
    assert executions["systemd.restart"].call_count == 0


def test_provider_failure_keeps_completed_tool_outcome_without_retry(tool_session, tmp_path):
    _, executions, run = tool_session
    provider = FakeLLMProvider(['{"tool":"system.info","arguments":{}}', "unused"])
    chat = provider.chat

    def respond(messages):
        reply = chat(messages)
        if len(provider.calls) == 2:
            raise OllamaError("private provider detail")
        return reply

    provider.chat = respond
    assert run(provider, ["Demande", "/exit"]) == 0
    assert len(saved_calls(tmp_path)) == 1
    assert saved_calls(tmp_path)[0]["status"] == "succeeded"
    assert executions["system.info"].call_count == 1


@pytest.mark.parametrize("method", ["start_tool", "finish_tool"])
def test_storage_failure_stops_before_execution_or_further_provider_calls(tool_session, tmp_path, monkeypatch, capsys, method):
    _, executions, run = tool_session
    monkeypatch.setattr(TaskHistory, method, Mock(side_effect=sqlite3.OperationalError("private storage detail")))
    provider = FakeLLMProvider(['{"tool":"system.info","arguments":{}}', "unused"])
    assert run(provider, ["Demande"]) == 1
    assert len(provider.calls) == 1
    assert executions["system.info"].call_count == int(method == "finish_tool")
    saved = saved_calls(tmp_path)
    assert len(saved) == int(method == "finish_tool")
    if saved:
        assert saved[0]["status"] == "running" and saved[0]["result"] is None
    captured = capsys.readouterr()
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "private storage detail" not in captured.out + captured.err + logs


def test_redacted_history_does_not_change_live_tool_arguments_or_provider_result(tool_session, tmp_path):
    _, executions, run = tool_session
    path = "/tmp/password=example-only"
    executions["system.disk"].return_value = ToolResult(success=True, data={"api_key": "opaque-credential", "total_bytes": 10})
    provider = FakeLLMProvider([json.dumps({"tool": "system.disk", "arguments": {"path": path}}), "Réponse"])
    assert run(provider, ["Lis le disque", "/exit"]) == 0
    executions["system.disk"].assert_called_once_with({"path": path})
    result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
    assert result["data"] == {"api_key": "opaque-credential", "total_bytes": 10}
    saved = saved_calls(tmp_path)[0]
    assert saved["arguments"] == {"path": REDACTED_TASK}
    assert saved["result"]["data"]["total_bytes"] == 10
    for path in (tmp_path / "history.sqlite3", tmp_path / "logs/simple-aios.log"):
        assert b"opaque-credential" not in path.read_bytes()
        assert b"example-only" not in path.read_bytes()
