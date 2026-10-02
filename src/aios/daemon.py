"""Local, sequential Core server using a private Unix stream socket."""

import argparse
from contextlib import closing, contextmanager
import logging
import os
from pathlib import Path
import secrets
import signal
import socket
import stat
import sys

from aios.app_logging import close_logging, configure_logging
from aios.config import load_config
from aios.core import Core
from aios.history import TaskHistory
from aios.ipc import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, decode_frame, encode_frame
from aios.llm import LLMProvider
from aios.ollama import OllamaError, OllamaProvider
from aios.policy import PolicyDecision


CLIENT_TIMEOUT = 30.0


def _parse_request(raw: bytes) -> dict[str, object]:
    request = decode_frame(raw, MAX_REQUEST_BYTES)
    method = request.get("method")
    if method == "chat" and request.keys() in (
        {"method", "message"}, {"method", "message", "confirmations"},
    ):
        message = request["message"]
        if isinstance(message, str) and message.strip() and type(request.get("confirmations", False)) is bool:
            message.encode("utf-8")  # Reject unpaired Unicode surrogates.
            return request
    elif method in ("diagnose", "history") and request.keys() == {"method"}:
        return request
    raise ValueError("Invalid request")


def _send(connection: socket.socket, response: dict[str, object]) -> bool:
    try:
        payload = encode_frame(response, MAX_RESPONSE_BYTES)
    except (ValueError, RecursionError):
        payload = encode_frame({"ok": False, "error": "Invalid response"}, MAX_RESPONSE_BYTES)
    try:
        connection.settimeout(CLIENT_TIMEOUT)
        connection.sendall(payload)
    except OSError:
        return False
    return True


def _read_request(connection, stream):
    # A user may think or read a confirmation indefinitely; partial frames are bounded.
    connection.settimeout(None)
    first = stream.read(1)
    if not first or first == b"\n":
        return first
    connection.settimeout(CLIENT_TIMEOUT)
    return first + stream.readline(MAX_REQUEST_BYTES)


def _handle_client(connection: socket.socket, provider: LLMProvider, history: TaskHistory) -> None:
    with connection.makefile("rb") as stream:
        enabled = False
        broken = False

        def authorize(decision, name, arguments):
            nonlocal broken
            if broken or not enabled or decision is not PolicyDecision.CONFIRM:
                return False
            identifier = secrets.token_hex(16)
            if not _send(connection, {
                "event": "confirmation", "id": identifier, "tool": name, "arguments": arguments,
            }):
                broken = True
                return False
            try:
                answer = decode_frame(_read_request(connection, stream), MAX_REQUEST_BYTES)
                if (
                    answer.keys() != {"method", "id", "accepted"}
                    or answer["method"] != "confirm" or answer["id"] != identifier
                    or type(answer["accepted"]) is not bool
                ):
                    raise ValueError("Invalid consent")
                return answer["accepted"] is True
            except (OSError, ValueError, RecursionError):
                broken = True
                return False

        core = Core(provider, history, permission_handler=authorize)
        while True:
            try:
                raw = _read_request(connection, stream)
            except OSError:
                return
            if not raw:
                return
            try:
                request = _parse_request(raw)
            except (ValueError, UnicodeError, RecursionError):
                _send(connection, {"ok": False, "error": "Invalid request"})
                return

            enabled = request.get("confirmations") is True
            try:
                if request["method"] == "chat":
                    result = core.chat(request["message"])
                elif request["method"] == "diagnose":
                    result = core.diagnose()
                else:
                    result = core.recent_history()
                response = {"ok": True, "result": result}
            except OllamaError:
                logging.getLogger("aios").error("Daemon provider error")
                response = {"ok": False, "error": "Provider unavailable"}
            except Exception:
                # Stop on storage/internal errors; never retry a possible action.
                _send(connection, {"ok": False, "error": "Request failed"})
                raise
            if broken:
                return
            if not _send(connection, response):
                return


@contextmanager
def _listener(socket_path: Path):
    path = socket_path.expanduser().absolute()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    identity = None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        try:
            previous_umask = os.umask(0o177)
            try:
                # bind refuses every existing path, including stale sockets.
                listener.bind(str(path))
            finally:
                os.umask(previous_umask)
            identity = path.lstat()
            listener.listen(1)
            yield listener
        finally:
            listener.close()
            if identity is not None:
                try:
                    current = path.lstat()
                    if stat.S_ISSOCK(current.st_mode) and (
                        current.st_dev, current.st_ino
                    ) == (identity.st_dev, identity.st_ino):
                        path.unlink()
                except FileNotFoundError:
                    pass


def serve(socket_path: Path, provider: LLMProvider, history: TaskHistory) -> None:
    """Serve one session per connection; the caller owns provider and history."""
    with _listener(socket_path) as listener:
        while True:
            connection, _ = listener.accept()
            with connection:
                _handle_client(connection, provider, history)


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simple-AIOS daemon local")
    parser.add_argument("--config", metavar="FILE", help="Fichier de configuration TOML")
    parser.add_argument("--socket", type=Path, metavar="PATH", help="Socket Unix (défaut : <data_dir>/aiosd.sock)")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        logger = configure_logging(config)
    except (OSError, ValueError):
        print("Impossible de charger la configuration ou d'initialiser les logs.", file=sys.stderr)
        return 1

    previous_handlers = {}
    logger.info("Daemon started")
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, _interrupt)
        if config.provider != "ollama":
            logger.error("Unsupported LLM provider")
            print('Provider LLM non pris en charge. Utilisez provider = "ollama".', file=sys.stderr)
            return 1
        with closing(TaskHistory(config.data_dir)) as history:
            serve(args.socket or config.data_dir / "aiosd.sock", OllamaProvider(config), history)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        logger.error("Daemon error (%s)", type(error).__name__)
        print("Le daemon a rencontré une erreur. Consultez les logs.", file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        logger.info("Daemon stopped")
        close_logging()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
