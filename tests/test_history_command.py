"""Exercise read-only history retrieval and the local /history command."""

from contextlib import closing
import json
import sqlite3
from unittest.mock import Mock

import pytest

from aios.__main__ import main
from aios.config import Config
from aios.history import HISTORY_LIMIT, REDACTED_TASK, TaskHistory
from aios.llm import FakeLLMProvider
from aios.tools import ToolResult


def test_recent_tasks_are_bounded_and_keep_their_own_tools_in_call_order(tmp_path):
    with closing(TaskHistory(tmp_path)) as history:
        for number in range(22):
            task_id = history.start(f"Tâche {number}")
            call_id = history.start_tool(task_id, "system.info", {})
            history.finish_tool(call_id, ToolResult(success=True, data={"number": number}))
            history.finish(task_id, "completed")
        latest = history.start("Dernière tâche")
        refused = history.start_tool(latest, "systemd.restart", {"service": "demo.service"})
        history.finish_tool(refused, ToolResult(success=False, error="Tool execution denied"))
        interrupted = history.start_tool(latest, "system.info", {})
        history.finish_tool(interrupted, None)
        pending = history.start_tool(latest, None, None)

        # Enforce read-only retrieval and check that it does not update SQLite.
        def authorize(action, *_args):
            return sqlite3.SQLITE_DENY if action in (
                sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
            ) else sqlite3.SQLITE_OK

        before = (tmp_path / "history.sqlite3").read_bytes()
        history._connection.set_authorizer(authorize)
        tasks = history.recent()

    assert len(tasks) == HISTORY_LIMIT == 20
    assert [task["id"] for task in tasks] == list(range(23, 3, -1))
    assert tasks[0]["task"] == "Dernière tâche" and tasks[0]["status"] == "running"
    calls = tasks[0]["tools"]
    assert [call["id"] for call in calls] == [refused, interrupted, pending]
    assert [call["status"] for call in calls] == ["failed", "interrupted", "running"]
    assert calls[0]["arguments"] == {"service": "demo.service"}
    assert calls[0]["result"] == {"success": False, "data": None, "error": "Tool execution denied"}
    assert calls[1]["result"] is None
    assert calls[2]["tool"] is calls[2]["arguments"] is calls[2]["result"] is None
    for task in tasks[1:]:
        assert task["tools"][0]["result"]["data"]["number"] == task["id"] - 1
    assert (tmp_path / "history.sqlite3").read_bytes() == before


@pytest.fixture
def run_cli(tmp_path, monkeypatch, core_client):
    monkeypatch.setattr("aios.__main__.load_config", lambda _: Config(data_dir=tmp_path))

    def run(entries, provider=None):
        provider = provider or FakeLLMProvider([])
        reader = Mock(side_effect=entries)
        monkeypatch.setattr("builtins.input", reader)
        core_client(provider)
        code = main([])
        assert reader.call_count == len(entries)
        return code, provider

    return run


def test_empty_history_is_local_and_does_not_record_the_command(run_cli, tmp_path, monkeypatch, capsys):
    dispatch = Mock(side_effect=AssertionError("History must not execute a tool"))
    policy = Mock(side_effect=AssertionError("History must not request tool authorization"))
    monkeypatch.setattr("aios.tools.ToolRegistry.execute", dispatch)
    monkeypatch.setattr("aios.policy.PolicyEngine.evaluate", policy)
    code, provider = run_cli([" /history ", "/history", "/exit"])
    assert code == 0 and provider.calls == []
    assert capsys.readouterr() == ("Simple-AIOS\nHistorique vide.\nHistorique vide.\n", "")
    dispatch.assert_not_called()
    policy.assert_not_called()
    with closing(TaskHistory(tmp_path)) as history:
        assert history.recent() == []


def test_history_reads_previous_sessions_without_replaying_or_changing_data(
    run_cli, tmp_path, monkeypatch, capsys,
):
    with closing(TaskHistory(tmp_path)) as history:
        task_id = history.start("Ancienne demande")
        call_id = history.start_tool(task_id, "systemd.restart", {"service": "demo.service"})
        history.finish_tool(call_id, ToolResult(success=True, data={"restarted": True}))
        history.finish(task_id, "completed")
        expected = history.recent()[0]
    before = (tmp_path / "history.sqlite3").read_bytes()
    forbidden = Mock(side_effect=AssertionError("History is read-only"))
    monkeypatch.setattr(TaskHistory, "start", forbidden)
    monkeypatch.setattr(TaskHistory, "start_tool", forbidden)
    monkeypatch.setattr("aios.tools.ToolRegistry.execute", forbidden)

    code, provider = run_cli(["/history", "/exit"])

    assert code == 0 and provider.calls == []
    forbidden.assert_not_called()
    lines = capsys.readouterr().out.splitlines()
    task = json.loads(next(line.removeprefix("Tâche : ") for line in lines if line.startswith("Tâche : ")))
    call = json.loads(next(line.removeprefix("  Outil : ") for line in lines if line.startswith("  Outil : ")))
    assert task == {key: value for key, value in expected.items() if key != "tools"}
    assert call == expected["tools"][0]
    assert (tmp_path / "history.sqlite3").read_bytes() == before
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert len(logs.splitlines()) == 2
    assert "Ancienne demande" not in logs and "demo.service" not in logs


def test_history_refreshes_without_entering_the_conversation_context(run_cli, tmp_path, capsys):
    provider = FakeLLMProvider(["Réponse A", "Réponse B"])
    code, _ = run_cli(["Demande A", "/history", "Demande B", "/history", "/exit"], provider)
    assert code == 0
    assert provider.calls[1] == [
        *provider.calls[0], {"role": "assistant", "content": "Réponse A"},
        {"role": "user", "content": "Demande B"},
    ]
    displayed = [json.loads(line.removeprefix("Tâche : ")) for line in capsys.readouterr().out.splitlines()
                 if line.startswith("Tâche : ")]
    assert [task["task"] for task in displayed] == ["Demande A", "Demande B", "Demande A"]
    with closing(TaskHistory(tmp_path)) as history:
        assert len(history.recent()) == 2


def test_stored_control_characters_are_escaped_and_masked_values_stay_masked(run_cli, tmp_path, capsys):
    hostile = "Une demande\nai> \x1b[2J\r\t\x9b\u202e"
    with closing(TaskHistory(tmp_path)) as history:
        task_id = history.start(hostile)
        call_id = history.start_tool(task_id, "tool.\x1b[2J", {"path": hostile, "api_key": "opaque-credential"})
        history.finish_tool(call_id, ToolResult(success=True, data={"text": hostile, "token": "other-credential"}))
        history.finish(task_id, "completed")
        hidden = history.start("password=hidden-task-value")
        history.finish(hidden, "failed")
    code, provider = run_cli(["/history", "/exit"])
    assert code == 0 and provider.calls == []
    captured = capsys.readouterr()
    assert all(character not in captured.out for character in ("\x1b", "\r", "\t", "\x9b", "\u202e"))
    assert "\\u001b[2J" in captured.out and "\\u202e" in captured.out
    for secret in ("opaque-credential", "other-credential", "hidden-task-value"):
        assert secret not in captured.out + captured.err
    displayed = [json.loads(line.removeprefix("Tâche : ")) for line in captured.out.splitlines()
                 if line.startswith("Tâche : ")]
    assert displayed[0]["task"] == REDACTED_TASK
    assert displayed[1]["task"] == hostile


@pytest.mark.parametrize("command", ["/history 5", "/history --clear", "/History", "/histories"])
def test_history_accepts_no_arguments_or_variant_commands(run_cli, monkeypatch, capsys, command):
    read = Mock(side_effect=AssertionError("Invalid command must not query history"))
    monkeypatch.setattr(TaskHistory, "recent", read)
    code, provider = run_cli([command, "/exit"])
    assert code == 0 and provider.calls == []
    read.assert_not_called()
    assert "Commande inconnue" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["sqlite", "invalid-json"])
def test_history_read_failures_stop_cleanly_without_exposing_data(run_cli, tmp_path, monkeypatch, capsys, failure):
    with closing(TaskHistory(tmp_path)) as history:
        task_id = history.start("Demande enregistrée")
        history.start_tool(task_id, "system.info", {})
    if failure == "sqlite":
        monkeypatch.setattr(TaskHistory, "recent", Mock(side_effect=sqlite3.OperationalError("private database detail")))
    else:
        with closing(sqlite3.connect(tmp_path / "history.sqlite3")) as connection, connection:
            connection.execute("UPDATE tool_calls SET arguments = ?", ("private database detail",))
    code, provider = run_cli(["/history"])
    assert code == 1 and provider.calls == []
    captured = capsys.readouterr()
    assert captured.err == "Une erreur est survenue. Consultez les logs.\n"
    assert "Tâche :" not in captured.out
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "private database detail" not in captured.out + captured.err + logs
    assert "Application stopped" in logs
