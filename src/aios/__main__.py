"""Entry point for ``python -m aios``."""

import argparse
from contextlib import closing
from importlib.metadata import version
import json
import logging
from pathlib import Path
import sys

from aios.app_logging import close_logging, configure_logging
from aios.client import DaemonClient, DaemonError, DaemonProviderError, RequestError
from aios.config import load_config
from aios.history import HISTORY_LIMIT
from aios.policy import PolicyDecision


def authorize_tool_call(
    decision: PolicyDecision, tool_name: str, arguments: dict[str, object],
) -> bool:
    """Present a Core policy decision and collect explicit terminal consent."""
    if decision is PolicyDecision.ALLOW:
        return True
    if decision is not PolicyDecision.CONFIRM:
        print("Action refusée.")
        return False

    accepted = False
    try:
        if not sys.stdin.isatty():
            print("Confirmation indisponible : terminal interactif requis.")
        else:
            if not isinstance(arguments, dict) or any(
                not isinstance(key, str) for key in arguments
            ):
                raise ValueError("Arguments must be a string-keyed dictionary")
            # Escape control characters so arguments cannot rewrite the prompt.
            preview = json.dumps(
                {"outil": tool_name, "arguments": arguments},
                ensure_ascii=True, allow_nan=False,
            )
            print(f"Action à confirmer : {preview}")
            answer = input("Confirmer cette action ? Tapez oui [oui/NON] : ")
            accepted = answer.strip().casefold() == "oui"
    except (EOFError, KeyboardInterrupt):
        print()
    except (OSError, TypeError, ValueError):
        # An unreadable confirmation or an unrepresentable action is refused.
        pass
    if not accepted:
        print("Action refusée.")
    return accepted


def _show_history(client: DaemonClient) -> None:
    tasks = client.recent_history()
    if not tasks:
        print("Historique vide.")
        return
    print(f"Historique ({HISTORY_LIMIT} dernières tâches, plus récentes d'abord) :")
    for task in tasks:
        # Escape all stored text, including terminal controls and Unicode bidi.
        summary = {key: value for key, value in task.items() if key != "tools"}
        print("Tâche : " + json.dumps(summary, ensure_ascii=True, allow_nan=False))
        for call in task["tools"]:
            print("  Outil : " + json.dumps(call, ensure_ascii=True, allow_nan=False))


def _run_shell(client: DaemonClient) -> None:
    print("Simple-AIOS")
    logger = logging.getLogger("aios")

    while True:
        try:
            command = input("ai> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not command:
            continue
        if command == "/exit":
            return
        if command == "/help":
            print(
                "Écrivez un message pour discuter avec le LLM.\n"
                "/help - Afficher l'aide\n"
                "/version - Afficher la version\n"
                "/diagnose - Diagnostic général en lecture seule\n"
                "/history - Afficher les dernières tâches et leurs outils\n"
                "/exit - Quitter"
            )
        elif command == "/version":
            print(f"Simple-AIOS {version('simple-aios')}")
        elif command == "/history":
            _show_history(client)
        elif command.startswith("/") and command != "/diagnose":
            print("Commande inconnue. Tapez /help pour afficher l'aide.")
        else:
            try:
                reply = client.diagnose() if command == "/diagnose" else client.chat(command)
            except DaemonProviderError as error:
                logger.error("Provider error (%s)", type(error).__name__)
                print(
                    "Impossible d'obtenir une réponse du LLM. "
                    "Vérifiez Ollama et le modèle configuré.",
                    file=sys.stderr,
                )
                continue
            except RequestError:
                print("Demande invalide ou trop volumineuse.", file=sys.stderr)
                continue
            print(reply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simple-AIOS")
    parser.add_argument("--config", metavar="FILE", help="Fichier de configuration TOML")
    parser.add_argument("--socket", type=Path, metavar="PATH", help="Socket Unix (défaut : <data_dir>/aiosd.sock)")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        logger = configure_logging(config)
    except (OSError, ValueError):
        print("Impossible de charger la configuration ou d'initialiser les logs.", file=sys.stderr)
        return 1

    logger.info("Application started")
    try:
        with closing(DaemonClient(
            args.socket or config.data_dir / "aiosd.sock", permission_handler=authorize_tool_call,
        )) as client:
            _run_shell(client)
    except KeyboardInterrupt:
        print()
    except DaemonError:
        logger.error("Daemon communication failed")
        print("Impossible de communiquer avec aiosd. Vérifiez le daemon et le socket.", file=sys.stderr)
        return 1
    except Exception as error:
        # Exception messages and tracebacks can contain user data or credentials.
        logger.error("Application error (%s)", type(error).__name__)
        print("Une erreur est survenue. Consultez les logs.", file=sys.stderr)
        return 1
    finally:
        logger.info("Application stopped")
        close_logging()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
