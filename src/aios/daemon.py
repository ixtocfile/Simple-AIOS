"""Local, sequential Core server using a private Unix stream socket."""

import argparse
from contextlib import closing, contextmanager
import json
import logging
import os
from pathlib import Path
import signal
import socket
import stat
import sys

from aios.app_logging import close_logging, configure_logging
from aios.config import load_config
from aios.core import Core
from aios.history import TaskHistory
from aios.llm import LLMProvider
from aios.ollama import OllamaError, OllamaProvider


MAX_REQUEST_BYTES = 64 * 1024
CLIENT_TIMEOUT = 30.0


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite number")


def _parse_request(raw: bytes) -> dict[str, object]:
    if len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
        raise ValueError("Invalid frame")
    request = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(request, dict):
        raise ValueError("Invalid request")
    method = request.get("method")
    if method == "chat" and request.keys() == {"method", "message"}:
        message = request["message"]
        if isinstance(message, str) and message.strip():
            message.encode("utf-8")  # Reject unpaired Unicode surrogates.
            return request
    elif method in ("diagnose", "history") and request.keys() == {"method"}:
        return request
    raise ValueError("Invalid request")


def _send(connection: socket.socket, response: dict[str, object]) -> bool:
    payload = (json.dumps(response, ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    try:
        connection.sendall(payload)
    except OSError:
        return False
    return True


def _handle_client(connection: socket.socket, core: Core) -> None:
    connection.settimeout(CLIENT_TIMEOUT)
    with connection.makefile("rb") as stream:
        while True:
            try:
                raw = stream.readline(MAX_REQUEST_BYTES + 1)
            except OSError:
                return
            if not raw:
                return
            try:
                request = _parse_request(raw)
            except (ValueError, UnicodeError, RecursionError):
                _send(connection, {"ok": False, "error": "Invalid request"})
                return

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
                # No terminal consent is available: CONFIRM and DENY stay refused.
                _handle_client(connection, Core(provider, history))


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
