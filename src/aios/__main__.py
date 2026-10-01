"""Entry point for ``python -m aios``."""

import argparse
from importlib.metadata import version
import json
import logging
import sys

from aios.app_logging import close_logging, configure_logging
from aios.config import load_config
from aios.llm import LLMProvider, Message
from aios.ollama import OllamaError, OllamaProvider
from aios.policy import PolicyDecision, PolicyEngine


def authorize_tool_call(
    policy: PolicyEngine, tool_name: str, arguments: dict[str, object],
) -> bool:
    """Apply a policy decision in the terminal, without executing the tool."""
    decision = policy.evaluate(tool_name)
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


def _run_shell(provider: LLMProvider) -> None:
    print("Simple-AIOS")
    messages: list[Message] = []
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
                "/exit - Quitter"
            )
        elif command == "/version":
            print(f"Simple-AIOS {version('simple-aios')}")
        elif command.startswith("/"):
            print("Commande inconnue. Tapez /help pour afficher l'aide.")
        else:
            pending: list[Message] = [*messages, {"role": "user", "content": command}]
            try:
                reply = provider.chat(pending)
            except OllamaError as error:
                logger.error("Provider error (%s)", type(error).__name__)
                print(
                    "Impossible d'obtenir une réponse du LLM. "
                    "Vérifiez Ollama et le modèle configuré.",
                    file=sys.stderr,
                )
                continue
            messages = [*pending, {"role": "assistant", "content": reply}]
            print(reply)


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
        if config.provider != "ollama":
            logger.error("Unsupported LLM provider")
            print('Provider LLM non pris en charge. Utilisez provider = "ollama".', file=sys.stderr)
            return 1
        _run_shell(OllamaProvider(config))
    except KeyboardInterrupt:
        print()
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
