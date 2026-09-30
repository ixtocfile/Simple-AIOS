"""Entry point for ``python -m aios``."""

import argparse
from importlib.metadata import version
import sys

from aios.app_logging import close_logging, configure_logging
from aios.config import load_config


def _run_shell() -> None:
    print("Simple-AIOS")

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
                "/help - Afficher l'aide\n"
                "/version - Afficher la version\n"
                "/exit - Quitter"
            )
        elif command == "/version":
            print(f"Simple-AIOS {version('simple-aios')}")
        else:
            print("Commande inconnue. Tapez /help pour afficher l'aide.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simple-AIOS")
    parser.add_argument("--config", metavar="FILE", help="Fichier de configuration TOML")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        logger = configure_logging(config)
    except (OSError, ValueError):
        print("Impossible de charger la configuration ou d'initialiser les logs.", file=sys.stderr)
        return 1

    logger.info("Application started")
    try:
        _run_shell()
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
