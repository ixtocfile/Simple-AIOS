"""Check the installed package's public entry point."""

import json
import os
import subprocess
import sys
from importlib.metadata import version
from unittest.mock import Mock

import pytest

from aios.__main__ import _build_tool_registry, main
from aios.config import Config
from aios.llm import FakeLLMProvider
from aios.ollama import OllamaError
from aios.policy import PolicyEngine
from aios.tools import RiskLevel, Tool, ToolRegistry, ToolResult


HELP = (
    "Écrivez un message pour discuter avec le LLM.\n"
    "/help - Afficher l'aide\n"
    "/version - Afficher la version\n"
    "/exit - Quitter\n"
)
UNKNOWN = "Commande inconnue. Tapez /help pour afficher l'aide.\n"


@pytest.mark.parametrize(
    ("commands", "transcript"),
    [
        pytest.param("/exit\n/help\n", "ai> ", id="exit-stops-reading"),
        pytest.param(" \t/exit \t\n", "ai> ", id="trim-whitespace"),
        pytest.param("/help\n/exit\n", f"ai> {HELP}ai> ", id="help"),
        pytest.param(
            "/version\n/exit\n",
            f"ai> Simple-AIOS {version('simple-aios')}\nai> ",
            id="package-version",
        ),
        pytest.param("\n \t\n/exit\n", "ai> ai> ai> ", id="empty-input"),
        pytest.param(
            "/unknown\n/help\n/exit\n",
            f"ai> {UNKNOWN}ai> {HELP}ai> ",
            id="unknown-command-then-help",
        ),
        pytest.param("", "ai> \n", id="end-of-input"),
    ],
)
def test_interactive_shell(tmp_path, commands, transcript):
    result = subprocess.run(
        [sys.executable, "-I", "-m", "aios"],
        cwd=tmp_path,
        env={**os.environ, "HOME": str(tmp_path)},
        input=commands,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"Simple-AIOS\n{transcript}"
    assert result.stderr == ""

    logs = (tmp_path / ".local/share/simple-aios/logs/simple-aios.log").read_text()
    assert logs.count("INFO Application started") == 1
    assert logs.count("INFO Application stopped") == 1
    assert len(logs.splitlines()) == 2


def test_keyboard_interrupt_exits_cleanly(tmp_path, monkeypatch, capsys):
    def interrupt(prompt):
        print(prompt, end="")
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    monkeypatch.setattr("aios.__main__.load_config", lambda _: Config(data_dir=tmp_path))

    assert main([]) == 0

    captured = capsys.readouterr()
    assert captured.out == "Simple-AIOS\nai> \n"
    assert captured.err == ""
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "Application started" in logs
    assert "Application stopped" in logs


def test_config_option_controls_log_location_and_level(tmp_path):
    config = tmp_path / "settings.toml"
    config.write_text('data_dir = "custom-data"\nlog_level = "ERROR"\n')

    result = subprocess.run(
        [sys.executable, "-I", "-m", "aios", "--config", str(config)],
        cwd=tmp_path,
        input="/exit\n",
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert (tmp_path / "custom-data/logs/simple-aios.log").read_text() == ""


@pytest.mark.parametrize("failure", ["missing-config", "invalid-config", "log-directory"])
def test_initialization_failure_is_reported_without_traceback(tmp_path, capsys, failure):
    config = tmp_path / "settings.toml"
    if failure == "invalid-config":
        config.write_text('model = "unfinished')
    elif failure == "log-directory":
        blocked = tmp_path / "blocked"
        blocked.touch()
        config.write_text(f'data_dir = "{blocked.as_posix()}"\n')

    assert main(["--config", str(config)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Impossible de charger la configuration ou d'initialiser les logs.\n"


def test_application_error_logs_type_without_sensitive_message(tmp_path, monkeypatch, capsys):
    def fail(_prompt):
        raise RuntimeError("password=private-test-value token=secret-test-token")

    monkeypatch.setattr("builtins.input", fail)
    monkeypatch.setattr("aios.__main__.load_config", lambda _: Config(data_dir=tmp_path))

    assert main([]) == 1

    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "ERROR Application error (RuntimeError)" in logs
    assert "Application started" in logs
    assert "Application stopped" in logs
    captured = capsys.readouterr()
    assert captured.err == "Une erreur est survenue. Consultez les logs.\n"
    for secret in ("private-test-value", "secret-test-token"):
        assert secret not in logs + captured.out + captured.err


@pytest.fixture
def cli_session(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path)
    monkeypatch.setattr("aios.__main__.load_config", lambda _: config)

    def run(provider, entries):
        constructor = Mock(return_value=provider)
        monkeypatch.setattr("aios.__main__.OllamaProvider", constructor)
        monkeypatch.setattr("builtins.input", Mock(side_effect=entries))
        status = main([])
        constructor.assert_called_once_with(config)
        return status

    return run


def test_conversation_keeps_history_and_commands_stay_local(cli_session, capsys, tmp_path):
    provider = FakeLLMProvider(["Bonjour !", "Très bien."])
    assert cli_session(provider, [
        " /help ", "", "  Bonjour  ", "/unknown", " \t", "/version",
        "Comment vas-tu ?", "/exit",
    ]) == 0

    first = [{"role": "user", "content": "Bonjour"}]
    assert provider.calls == [first, [
        *first,
        {"role": "assistant", "content": "Bonjour !"},
        {"role": "user", "content": "Comment vas-tu ?"},
    ]]
    captured = capsys.readouterr()
    assert captured.out == (
        f"Simple-AIOS\n{HELP}Bonjour !\n{UNKNOWN}"
        f"Simple-AIOS {version('simple-aios')}\nTrès bien.\n"
    )
    assert captured.err == ""
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert len(logs.splitlines()) == 2
    for text in ("Bonjour", "Comment vas-tu", "Très bien"):
        assert text not in logs


def test_commands_and_empty_input_never_call_provider(cli_session):
    provider = FakeLLMProvider([])
    assert cli_session(provider, ["", " \t", "/help", "/version", "/unknown", "/exit"]) == 0
    assert provider.calls == []


def test_conversation_history_is_reset_between_sessions(cli_session):
    provider = FakeLLMProvider(["Première réponse", "Deuxième réponse"])
    assert cli_session(provider, ["Première session", "/exit"]) == 0
    assert cli_session(provider, ["Deuxième session", "/exit"]) == 0
    assert provider.calls == [
        [{"role": "user", "content": "Première session"}],
        [{"role": "user", "content": "Deuxième session"}],
    ]


def test_model_output_is_displayed_without_executing_commands(cli_session, capsys, tmp_path):
    marker = tmp_path / "must-not-exist"
    reply = f"touch {marker}\n/exit"
    provider = FakeLLMProvider([reply, "Toujours disponible"])

    assert cli_session(provider, ["Propose une commande", "Suite", "/exit"]) == 0

    assert capsys.readouterr().out == f"Simple-AIOS\n{reply}\nToujours disponible\n"
    assert not marker.exists()
    assert len(provider.calls) == 2


def test_provider_failure_preserves_successful_history_and_allows_retry(
    cli_session, capsys, tmp_path,
):
    class FailingOnceProvider(FakeLLMProvider):
        def chat(self, messages):
            if messages[-1]["content"] == "failed-private-prompt":
                raise OllamaError("token=secret-test-token")
            return super().chat(messages)

    provider = FailingOnceProvider(["first-private-reply", "last-private-reply"])
    assert cli_session(provider, [
        "first-private-prompt", "failed-private-prompt", "/help",
        "last-private-prompt", "/exit",
    ]) == 0

    assert provider.calls[-1] == [
        {"role": "user", "content": "first-private-prompt"},
        {"role": "assistant", "content": "first-private-reply"},
        {"role": "user", "content": "last-private-prompt"},
    ]
    captured = capsys.readouterr()
    assert captured.out == f"Simple-AIOS\nfirst-private-reply\n{HELP}last-private-reply\n"
    assert captured.err == (
        "Impossible d'obtenir une réponse du LLM. Vérifiez Ollama et le modèle configuré.\n"
    )
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "ERROR Provider error (OllamaError)" in logs
    assert "Application stopped" in logs
    assert "private" not in logs
    assert "secret-test-token" not in logs + captured.out + captured.err


def test_keyboard_interrupt_during_provider_call_exits_cleanly(
    cli_session, monkeypatch, capsys, tmp_path,
):
    provider = FakeLLMProvider([])
    monkeypatch.setattr(provider, "chat", Mock(side_effect=KeyboardInterrupt))

    assert cli_session(provider, ["Bonjour"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "Simple-AIOS\n\n"
    assert captured.err == ""
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "Application stopped" in logs
    assert "ERROR" not in logs


@pytest.mark.parametrize("ending", [EOFError, KeyboardInterrupt])
def test_conversation_can_end_at_input(cli_session, capsys, ending):
    assert cli_session(FakeLLMProvider(["Bonjour !"]), ["Bonjour", ending]) == 0
    captured = capsys.readouterr()
    assert captured.out == "Simple-AIOS\nBonjour !\n\n"
    assert captured.err == ""


def test_cli_constructs_provider_from_toml(tmp_path, monkeypatch):
    config_path = tmp_path / "settings.toml"
    config_path.write_text(
        'provider = "ollama"\nmodel = "custom-model"\n'
        'ollama_url = "http://localhost:12345"\n'
        f'data_dir = "{tmp_path.as_posix()}"\n',
        encoding="utf-8",
    )
    fake = FakeLLMProvider(["Réponse"])
    constructor = Mock(return_value=fake)
    monkeypatch.setattr("aios.__main__.OllamaProvider", constructor)
    monkeypatch.setattr("builtins.input", Mock(side_effect=["Bonjour", "/exit"]))

    assert main(["--config", str(config_path)]) == 0

    constructor.assert_called_once_with(Config(
        model="custom-model", ollama_url="http://localhost:12345", data_dir=tmp_path,
    ))
    assert fake.calls == [[{"role": "user", "content": "Bonjour"}]]


def test_unsupported_provider_fails_without_network_or_sensitive_details(
    tmp_path, monkeypatch, capsys,
):
    monkeypatch.setattr("aios.__main__.load_config", lambda _: Config(
        provider="unsupported-secret-provider", data_dir=tmp_path,
    ))
    constructor = Mock()
    monkeypatch.setattr("aios.__main__.OllamaProvider", constructor)

    assert main([]) == 1

    constructor.assert_not_called()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == 'Provider LLM non pris en charge. Utilisez provider = "ollama".\n'
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "ERROR Unsupported LLM provider" in logs
    assert "Application stopped" in logs
    assert "unsupported-secret-provider" not in logs + captured.err


class RecordingTool(Tool):
    name = "test.action"
    description = "Record validated arguments in memory for CLI tests."
    risk_level = RiskLevel.READ

    def __init__(self):
        self.calls = []

    def validate_arguments(self, arguments):
        if arguments.keys() - {"target"}:
            raise ValueError("Unexpected argument")
        target = arguments.get("target", "default-target")
        if not isinstance(target, str) or not target.strip():
            raise ValueError("Invalid target")
        arguments["target"] = target.strip()

    def _execute(self, arguments):
        self.calls.append(arguments)
        return ToolResult(success=True, data={"target": arguments["target"]})


@pytest.fixture
def cli_tool(monkeypatch):
    tool = RecordingTool()
    registry = ToolRegistry()
    registry.register(tool)
    monkeypatch.setattr("aios.__main__._build_tool_registry", lambda: registry)
    return tool


def tool_reply(arguments=None):
    return json.dumps({"tool": "test.action", "arguments": arguments or {}})


def test_default_cli_registry_contains_only_existing_read_tools():
    tools = _build_tool_registry().list_tools()
    assert [tool.name for tool in tools] == [
        "system.info", "system.memory", "system.disk", "process.list",
    ]
    assert all(tool.risk_level is RiskLevel.READ for tool in tools)


def test_cli_validates_checks_policy_executes_and_returns_result_with_history(
    cli_session, cli_tool, monkeypatch, capsys, tmp_path,
):
    events = []
    validate = cli_tool.validate_arguments
    evaluate = PolicyEngine.evaluate
    execute = cli_tool._execute

    def validation(arguments):
        events.append("validate")
        validate(arguments)

    def policy(engine, name):
        events.append("policy")
        return evaluate(engine, name)

    def execution(arguments):
        events.append("execute")
        return execute(arguments)

    monkeypatch.setattr(cli_tool, "validate_arguments", validation)
    monkeypatch.setattr(PolicyEngine, "evaluate", policy)
    monkeypatch.setattr(cli_tool, "_execute", execution)
    reply = tool_reply({"target": "  private-target  "})
    provider = FakeLLMProvider([reply, "private-result", "Suite"])

    assert cli_session(provider, ["private-request", "Continue", "/exit"]) == 0

    first = [{"role": "user", "content": "private-request"}]
    assert provider.calls[0] == first
    assert provider.calls[1][:-1] == [*first, {"role": "assistant", "content": reply}]
    feedback = provider.calls[1][-1]
    assert feedback["role"] == "user"
    assert json.loads(feedback["content"]) == {"tool_result": {
        "tool": "test.action", "success": True,
        "data": {"target": "private-target"}, "error": None,
    }}
    assert provider.calls[2] == [
        *provider.calls[1], {"role": "assistant", "content": "private-result"},
        {"role": "user", "content": "Continue"},
    ]
    assert events == ["validate", "policy", "execute"]
    assert cli_tool.calls == [{"target": "private-target"}]
    captured = capsys.readouterr()
    assert captured.out == "Simple-AIOS\nprivate-result\nSuite\n"
    assert captured.err == ""
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "private" not in logs
    assert len(logs.splitlines()) == 2


@pytest.mark.parametrize(("reply", "tool_name", "error"), [
    ('{"tool":', None, "Invalid tool call"),
    ('[{"tool":"test.action","arguments":{}}]', None, "Invalid tool call"),
    ('{"tool":"test.action","arguments":{},"confirmed":true}', None, "Invalid tool call"),
    ('{"tool":"test.action","arguments":{},"risk_level":"READ"}', None, "Invalid tool call"),
    ('{"tool":"test.action","arguments":{"target":"a","target":"b"}}',
     None, "Invalid tool call"),
    ('{"tool":"shell.run","arguments":{"command":"arbitrary"}}',
     "shell.run", "Unknown tool"),
    (tool_reply({"target": 42}), "test.action", "Invalid tool arguments"),
])
def test_cli_returns_invalid_call_errors_without_policy_or_execution(
    cli_session, cli_tool, monkeypatch, reply, tool_name, error,
):
    evaluate = Mock()
    monkeypatch.setattr(PolicyEngine, "evaluate", evaluate)
    provider = FakeLLMProvider([reply, "Appel refusé"])

    assert cli_session(provider, ["Demande", "/exit"]) == 0

    assert len(provider.calls) == 2
    assert json.loads(provider.calls[1][-1]["content"]) == {"tool_result": {
        "tool": tool_name, "success": False, "data": None, "error": error,
    }}
    evaluate.assert_not_called()
    assert cli_tool.calls == []


@pytest.mark.parametrize("reply", [
    'Voici un appel : {"tool":"test.action","arguments":{}}',
    '```json\n{"tool":"test.action","arguments":{}}\n```',
])
def test_cli_does_not_extract_calls_from_prose_or_markdown(
    cli_session, cli_tool, capsys, reply,
):
    provider = FakeLLMProvider([reply])
    assert cli_session(provider, ["Demande", "/exit"]) == 0
    assert len(provider.calls) == 1
    assert cli_tool.calls == []
    assert capsys.readouterr().out == f"Simple-AIOS\n{reply}\n"


@pytest.mark.parametrize(("risk", "interactive", "answer", "allowed"), [
    (RiskLevel.DENY, True, None, False),
    (RiskLevel.CONFIRM, True, "oui", True),
    (RiskLevel.CONFIRM, True, "", False),
    (RiskLevel.CONFIRM, True, "non", False),
    (RiskLevel.CONFIRM, True, EOFError, False),
    (RiskLevel.CONFIRM, True, KeyboardInterrupt, False),
    (RiskLevel.CONFIRM, False, None, False),
])
def test_cli_requires_policy_and_explicit_confirmation_before_execution(
    cli_session, cli_tool, monkeypatch, capsys, risk, interactive, answer, allowed,
):
    cli_tool.risk_level = risk
    monkeypatch.setattr("sys.stdin.isatty", lambda: interactive)
    provider = FakeLLMProvider([tool_reply(), "Réponse finale"])
    entries = ["Demande"] + ([] if answer is None else [answer]) + ["/exit"]

    assert cli_session(provider, entries) == 0

    result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
    assert result == {
        "tool": "test.action", "success": allowed,
        "data": {"target": "default-target"} if allowed else None,
        "error": None if allowed else "Tool execution denied",
    }
    assert cli_tool.calls == ([{"target": "default-target"}] if allowed else [])
    output = capsys.readouterr().out
    if risk is RiskLevel.CONFIRM and interactive:
        assert '"arguments": {"target": "default-target"}' in output
    else:
        assert "Action à confirmer" not in output
    assert "Réponse finale" in output


@pytest.mark.parametrize(("outcome", "error"), [
    (RuntimeError("token=secret-value"), "Tool execution failed"),
    (ToolResult(success=False, error="Resource unavailable"), "Resource unavailable"),
    (ToolResult(success=True, data={"value": object()}), "Invalid tool result"),
    (ToolResult(success=True, data={"value": float("nan")}), "Invalid tool result"),
])
def test_cli_returns_safe_tool_failures_and_stays_available(
    cli_session, cli_tool, monkeypatch, capsys, tmp_path, outcome, error,
):
    execute = Mock(side_effect=[outcome])
    monkeypatch.setattr(cli_tool, "_execute", execute)
    provider = FakeLLMProvider([tool_reply(), "Échec expliqué", "Disponible"])

    assert cli_session(provider, ["Demande", "Suite", "/exit"]) == 0

    result = json.loads(provider.calls[1][-1]["content"])["tool_result"]
    assert result == {
        "tool": "test.action", "success": False, "data": None, "error": error,
    }
    execute.assert_called_once_with({"target": "default-target"})
    captured = capsys.readouterr()
    assert captured.out == "Simple-AIOS\nÉchec expliqué\nDisponible\n"
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "secret-value" not in logs + captured.out + captured.err + repr(provider.calls)


def test_cli_follow_up_is_displayed_without_another_tool_execution(cli_session, cli_tool, capsys):
    reply = tool_reply()
    provider = FakeLLMProvider([reply, reply])

    assert cli_session(provider, ["Demande", "/exit"]) == 0

    assert len(provider.calls) == 2
    assert cli_tool.calls == [{"target": "default-target"}]
    assert capsys.readouterr().out == f"Simple-AIOS\n{reply}\n"


def test_cli_preserves_tool_outcome_after_follow_up_provider_failure(
    cli_session, cli_tool, capsys, tmp_path,
):
    class FailingFollowUpProvider(FakeLLMProvider):
        def chat(self, messages):
            reply = super().chat(messages)
            if len(self.calls) == 2:
                raise OllamaError("token=secret-value")
            return reply

    provider = FailingFollowUpProvider([tool_reply(), "unused", "Disponible"])

    assert cli_session(provider, ["Demande", "Suite", "/exit"]) == 0

    assert len(provider.calls) == 3
    assert provider.calls[2] == [
        *provider.calls[1], {"role": "user", "content": "Suite"},
    ]
    result = json.loads(provider.calls[2][-2]["content"])["tool_result"]
    assert result["success"] is True
    assert result["data"] == {"target": "default-target"}
    assert cli_tool.calls == [{"target": "default-target"}]
    captured = capsys.readouterr()
    assert captured.out == "Simple-AIOS\nDisponible\n"
    assert "Impossible d'obtenir une réponse du LLM." in captured.err
    logs = (tmp_path / "logs/simple-aios.log").read_text()
    assert "ERROR Provider error (OllamaError)" in logs
    assert "secret-value" not in logs + captured.out + captured.err
