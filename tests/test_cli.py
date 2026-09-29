"""Check the installed package's public entry point."""

import subprocess
import sys
from importlib.metadata import version

import pytest

from aios.__main__ import main


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
        input=commands,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"Simple-AIOS\n{transcript}"
    assert result.stderr == ""


def test_keyboard_interrupt_exits_cleanly(monkeypatch, capsys):
    def interrupt(prompt):
        print(prompt, end="")
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)

    main()

    captured = capsys.readouterr()
    assert captured.out == "Simple-AIOS\nai> \n"
    assert captured.err == ""
