"""Check the installed package's public entry point."""

import os
import subprocess
import sys
from importlib.metadata import version

import pytest

from aios.__main__ import main
from aios.config import Config


HELP = (
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
        pytest.param("Bonjour\n/exit\n", f"ai> {UNKNOWN}ai> ", id="unknown-text"),
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
