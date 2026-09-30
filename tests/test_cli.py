"""Check the installed package's public entry point."""

import os
import subprocess
import sys
from importlib.metadata import version
from unittest.mock import Mock

import pytest

from aios.__main__ import main
from aios.config import Config
from aios.llm import FakeLLMProvider
from aios.ollama import OllamaError


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
