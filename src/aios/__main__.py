"""Entry point for ``python -m aios``."""

from importlib.metadata import version


def main() -> None:
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


if __name__ == "__main__":
    main()
