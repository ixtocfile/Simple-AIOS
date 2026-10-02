"""Check task persistence with real SQLite files and an offline CLI provider."""

from contextlib import closing
from datetime import UTC, datetime
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


def rows(data_dir):
    with closing(sqlite3.connect(data_dir / "history.sqlite3")) as connection:
        return connection.execute(
            "SELECT id, task, timestamp, status FROM tasks ORDER BY id"
        ).fetchall()


def test_tasks_are_committed_persist_across_reopening_and_use_utc(tmp_path):
    directory = tmp_path / "nested" / "data"
    task = "Vérifie l'état du disque '; DROP TABLE tasks; --"
    before = datetime.now(UTC)
    with closing(TaskHistory(directory)) as history:
        first = history.start(task)
        initial = rows(directory)
        assert initial[0][0:2] == (first, task)
        assert initial[0][3] == "running"
        timestamp = datetime.fromisoformat(initial[0][2])
        assert timestamp.utcoffset().total_seconds() == 0
        assert before <= timestamp <= datetime.now(UTC)
        history.finish(first, "completed")
        second = history.start("Une autre tâche")
        assert second != first

    assert (directory / "history.sqlite3").stat().st_mode & 0o777 == 0o600
    with closing(TaskHistory(directory)) as history:
        assert rows(directory) == [
            (first, task, initial[0][2], "completed"),
            (second, "Une autre tâche", rows(directory)[1][2], "running"),
        ]
        # Reopening does not invent a result for an unfinished task.
        history.finish(second, "interrupted")
    assert [row[3] for row in rows(directory)] == ["completed", "interrupted"]


def test_validation_and_finalization_do_not_corrupt_existing_tasks(tmp_path):
    with closing(TaskHistory(tmp_path)) as history:
        for task in (None, 4, "", " \t"):
            with pytest.raises(ValueError):
                history.start(task)
        task_id = history.start("Demande valide")
        initial = rows(tmp_path)
        for invalid_id, invalid_status in (
            (True, "completed"), (0, "completed"), ("1", "completed"),
            (task_id + 100, "completed"), (task_id, "running"),
            (task_id, "unknown"), (task_id, None),
            (task_id, "failed'; DROP TABLE tasks; --"),
        ):
            with pytest.raises(ValueError):
                history.finish(invalid_id, invalid_status)
            assert rows(tmp_path) == initial
        history.finish(task_id, "failed")
        with pytest.raises(ValueError):
            history.finish(task_id, "completed")
        assert rows(tmp_path)[0][3] == "failed"


@pytest.mark.parametrize("task", [
    "password=hunter2", 'Un TOKEN : "abc123"', "mot de passe : bonjour",
    "clé privée : exemple", "api_key=abcd", "un secret\nsur deux lignes",
    "Lis https://alice:credential@example.invalid/",
    "-----BEGIN RSA PRIVATE KEY-----\nexample\n-----END RSA PRIVATE KEY-----",
    "ghp_0123456789abcdefghijklmnop", "sk-0123456789abcdefghijklmnop",
])
def test_sensitive_task_is_masked_before_any_sqlite_write(tmp_path, task):
    with closing(TaskHistory(tmp_path)) as history:
        task_id = history.start(task)
        history.finish(task_id, "completed")
    assert rows(tmp_path)[0][1] == REDACTED_TASK
    assert task.encode() not in (tmp_path / "history.sqlite3").read_bytes()


@pytest.fixture
def history_cli(tmp_path, monkeypatch):
    monkeypatch.setattr("aios.__main__.load_config", lambda _: Config(data_dir=tmp_path))
    histories = []

    def create_history(directory):
        history = TaskHistory(directory)
        histories.append(history)
        return history

    monkeypatch.setattr("aios.__main__.TaskHistory", create_history)

    def run(provider, entries):
        reader = Mock(side_effect=entries)
        monkeypatch.setattr("builtins.input", reader)
        monkeypatch.setattr("aios.__main__.OllamaProvider", lambda _: provider)
        result = main([])
        assert reader.call_count == len(entries)
        for history in histories:
            with pytest.raises(sqlite3.ProgrammingError):
                history.start("Connection must be closed")
        return result

    return run


def test_cli_records_each_request_once_and_excludes_local_commands(history_cli, tmp_path):
    provider = FakeLLMProvider(["Première réponse", "Deuxième réponse"])
    observed = []
    chat = provider.chat

    def observe(messages):
        observed.append(rows(tmp_path)[-1])
        return chat(messages)

    provider.chat = observe
    assert history_cli(provider, [
        "", " \t", "/help", "/version", "/unknown", "/history",
        "  Première demande  ", "Deuxième demande", "/exit",
    ]) == 0
    saved = rows(tmp_path)
    assert [(row[1], row[3]) for row in saved] == [
        ("Première demande", "completed"), ("Deuxième demande", "completed"),
    ]
    assert [row[3] for row in observed] == ["running", "running"]
    assert [row[:3] for row in observed] == [row[:3] for row in saved]
    assert "Première réponse" not in (tmp_path / "history.sqlite3").read_bytes().decode(errors="ignore")


def test_sqlite_history_survives_sessions_without_becoming_model_context(history_cli, tmp_path):
    provider = FakeLLMProvider(["Réponse A", "Réponse B"])
    assert history_cli(provider, ["Demande A", "/exit"]) == 0
    assert history_cli(provider, ["Demande B", "/exit"]) == 0
    assert [row[1] for row in rows(tmp_path)] == ["Demande A", "Demande B"]
    assert len(provider.calls[1]) == 2
    assert provider.calls[1][-1]["content"] == "Demande B"


@pytest.mark.parametrize(("error", "status", "exit_code"), [
    (OllamaError("private error detail"), "failed", 0),
    (RuntimeError("private error detail"), "failed", 1),
    (KeyboardInterrupt(), "interrupted", 0),
])
def test_request_errors_and_interruptions_get_a_persistent_status(
    history_cli, tmp_path, capsys, error, status, exit_code,
):
    provider = FakeLLMProvider([])
    provider.chat = Mock(side_effect=error)
    entries = ["Demande"] + (["/exit"] if isinstance(error, OllamaError) else [])
    assert history_cli(provider, entries) == exit_code
    assert [(row[1], row[3]) for row in rows(tmp_path)] == [("Demande", status)]
    assert provider.chat.call_count == 1
    captured = capsys.readouterr()
    persisted = (tmp_path / "history.sqlite3").read_bytes() + (tmp_path / "logs/simple-aios.log").read_bytes()
    assert b"private error detail" not in persisted
    assert "private error detail" not in captured.out + captured.err


@pytest.mark.parametrize("ending", [EOFError, KeyboardInterrupt, "/exit"])
def test_exit_at_prompt_does_not_create_a_task(history_cli, tmp_path, ending):
    assert history_cli(FakeLLMProvider([]), [ending]) == 0
    assert rows(tmp_path) == []


@pytest.mark.parametrize("risk", [RiskLevel.READ, RiskLevel.DENY])
@pytest.mark.parametrize("provider_failure", [False, True])
def test_tool_requests_keep_one_parent_task_and_its_processing_status(
    history_cli, tmp_path, monkeypatch, risk, provider_failure,
):
    registry = build_tool_registry()
    tool = registry.get("system.info")
    monkeypatch.setattr(tool, "risk_level", risk)
    execute = Mock(return_value=ToolResult(success=True, data={"hostname": "private-host"}))
    monkeypatch.setattr(tool, "_execute", execute)
    monkeypatch.setattr("aios.core.build_tool_registry", lambda: registry)
    call = '{"tool":"system.info","arguments":{}}'
    provider = FakeLLMProvider([call, "Résultat reçu"])
    chat = provider.chat

    def respond(messages):
        reply = chat(messages)
        if provider_failure and len(provider.calls) == 2:
            raise OllamaError("private follow-up detail")
        return reply

    provider.chat = respond
    assert history_cli(provider, ["Lis les informations système", "/exit"]) == 0
    assert len(provider.calls) == 2
    assert execute.call_count == int(risk is RiskLevel.READ)
    assert [(row[1], row[3]) for row in rows(tmp_path)] == [
        ("Lis les informations système", "failed" if provider_failure else "completed"),
    ]
    content = (tmp_path / "history.sqlite3").read_bytes()
    for excluded in (call, "Résultat reçu", "tool_result", "private follow-up detail"):
        assert excluded.encode() not in content


def test_diagnostic_is_one_task_committed_before_readings(history_cli, tmp_path, monkeypatch):
    registry = build_tool_registry()
    observations = []

    def execute(_arguments):
        observations.append(rows(tmp_path))
        return ToolResult(success=False, error="Reading unavailable")

    for name, _ in DIAGNOSTIC_CALLS:
        monkeypatch.setattr(registry.get(name), "_execute", execute)
    monkeypatch.setattr("aios.core.build_tool_registry", lambda: registry)
    provider = FakeLLMProvider(["Domaines non évalués"])
    assert history_cli(provider, ["/diagnose", "/exit"]) == 0
    assert len(observations) == 5
    assert all(len(observation) == 1 and observation[0][3] == "running" for observation in observations)
    assert [(row[1], row[3]) for row in rows(tmp_path)] == [("/diagnose", "completed")]
    assert b"Reading unavailable" in (tmp_path / "history.sqlite3").read_bytes()


def test_budget_exhaustion_completes_the_request_without_extra_history_rows(
    history_cli, tmp_path, monkeypatch,
):
    registry = build_tool_registry()
    monkeypatch.setattr(registry.get("system.info"), "risk_level", RiskLevel.DENY)
    monkeypatch.setattr("aios.core.build_tool_registry", lambda: registry)
    provider = FakeLLMProvider(['{"tool":"system.info","arguments":{}}'] * 6)
    assert history_cli(provider, ["Demande bornée", "/exit"]) == 0
    assert len(provider.calls) == 6
    assert [(row[1], row[3]) for row in rows(tmp_path)] == [("Demande bornée", "completed")]


def test_redaction_does_not_modify_the_message_sent_to_the_provider(history_cli, tmp_path):
    task = "Mon mot de passe est un-exemple-sensible"
    provider = FakeLLMProvider(["Réponse non persistée"])
    assert history_cli(provider, [task, "/exit"]) == 0
    assert provider.calls[0][-1]["content"] == task
    assert rows(tmp_path)[0][1] == REDACTED_TASK
    for path in (tmp_path / "history.sqlite3", tmp_path / "logs/simple-aios.log"):
        assert b"un-exemple-sensible" not in path.read_bytes()


@pytest.mark.parametrize("failure", ["corrupt", "directory"])
def test_unusable_database_stops_before_input_or_provider_without_exposing_details(
    tmp_path, monkeypatch, capsys, failure,
):
    path = tmp_path / "history.sqlite3"
    if failure == "corrupt":
        path.write_text("private database content")
    else:
        path.mkdir()
    monkeypatch.setattr("aios.__main__.load_config", lambda _: Config(data_dir=tmp_path))
    connect = sqlite3.connect
    connections = []

    def track_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr("aios.history.sqlite3.connect", track_connection)
    reader, provider = Mock(), Mock()
    monkeypatch.setattr("builtins.input", reader)
    monkeypatch.setattr("aios.__main__.OllamaProvider", provider)
    assert main([]) == 1
    reader.assert_not_called()
    provider.assert_not_called()
    captured = capsys.readouterr()
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "private database content" not in captured.out + captured.err + logs
    assert "Application stopped" in logs
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


@pytest.mark.parametrize("method", ["start", "finish"])
def test_write_failure_stops_without_retry_or_unrecorded_execution(
    history_cli, tmp_path, monkeypatch, capsys, method,
):
    def fail(*_args):
        raise sqlite3.OperationalError("private database detail")

    # Leave start callable after closure so the fixture can verify resource release.
    original = getattr(TaskHistory, method)
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            return fail(*args)
        return original(*args)

    monkeypatch.setattr(TaskHistory, method, fail_once)
    provider = FakeLLMProvider(["Réponse"])
    assert history_cli(provider, ["Demande"]) == 1
    assert len(provider.calls) == int(method == "finish")
    saved = rows(tmp_path)
    assert len(saved) == int(method == "finish")
    if saved:
        assert saved[0][3] == "running"
    captured = capsys.readouterr()
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "private database detail" not in captured.out + captured.err + logs
    assert "Application stopped" in logs
