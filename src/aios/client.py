"""Synchronous Unix socket client; never creates a Core or executes tools."""

from collections.abc import Callable
import math
from pathlib import Path
import socket

from aios.ipc import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, decode_frame, encode_frame
from aios.policy import PolicyDecision


class DaemonError(RuntimeError):
    """The daemon connection failed; a sent request must not be retried."""


class DaemonProviderError(DaemonError):
    """The provider failed, but the daemon session is still usable."""


class RequestError(ValueError):
    """The request was rejected locally before it could be sent."""


class DaemonClient:
    def __init__(
        self, socket_path: Path, *,
        permission_handler: Callable[[PolicyDecision, str, dict[str, object]], bool] | None = None,
        timeout: float = 600.0,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Invalid timeout")
        self._path = socket_path.expanduser()
        self._permission_handler = permission_handler
        self._timeout = timeout
        self._socket = None
        self._stream = None
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._stream is not None:
                self._stream.close()
        finally:
            if self._socket is not None:
                self._socket.close()

    def chat(self, text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            raise RequestError("Invalid message")
        try:
            text.encode("utf-8")
        except UnicodeError:
            raise RequestError("Invalid message") from None
        request = {"method": "chat", "message": text.strip()}
        if self._permission_handler is not None:
            request["confirmations"] = True
        return self._request(request)

    def diagnose(self) -> str:
        return self._request({"method": "diagnose"})

    def recent_history(self) -> list[dict[str, object]]:
        return self._request({"method": "history"})

    def _request(self, request):
        try:
            raw = encode_frame(request, MAX_REQUEST_BYTES)
        except (ValueError, UnicodeError):
            raise RequestError("Invalid request") from None
        if self._closed:
            raise DaemonError("Connection closed")
        try:
            if self._socket is None:
                self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._socket.settimeout(5.0)
                self._socket.connect(str(self._path))
                self._socket.settimeout(self._timeout)
                self._stream = self._socket.makefile("rb")
            self._socket.sendall(raw)
            confirmations = set()
            while True:
                response = decode_frame(self._stream.readline(MAX_RESPONSE_BYTES + 1), MAX_RESPONSE_BYTES)
                if "event" in response:
                    if request.get("confirmations") is not True:
                        raise ValueError("Unexpected confirmation")
                    self._confirm(response, confirmations)
                    continue
                if response.keys() == {"ok", "error"} and response["ok"] is False:
                    if response["error"] == "Provider unavailable":
                        raise DaemonProviderError("Provider unavailable")
                    raise ValueError("Daemon rejected request")
                if response.keys() != {"ok", "result"} or response["ok"] is not True:
                    raise ValueError("Invalid response")
                result = response["result"]
                if request["method"] == "history":
                    if not isinstance(result, list) or any(
                        not isinstance(task, dict) or not isinstance(task.get("tools"), list)
                        or any(not isinstance(call, dict) for call in task["tools"])
                        for task in result
                    ):
                        raise ValueError("Invalid history")
                else:
                    if not isinstance(result, str):
                        raise ValueError("Invalid reply")
                    result.encode("utf-8")
                return result
        except DaemonProviderError:
            raise
        except (OSError, ValueError, RecursionError):
            self.close()
            raise DaemonError("Daemon communication failed") from None
        except BaseException:
            self.close()
            raise

    def _confirm(self, response, seen):
        if response.keys() != {"event", "id", "tool", "arguments"} or response["event"] != "confirmation":
            raise ValueError("Invalid confirmation")
        identifier = response["id"]
        if (
            not isinstance(identifier, str) or len(identifier) != 32
            or any(char not in "0123456789abcdef" for char in identifier)
            or identifier in seen or len(seen) >= 5
            or not isinstance(response["tool"], str) or not response["tool"]
            or not isinstance(response["arguments"], dict)
        ):
            raise ValueError("Invalid confirmation")
        seen.add(identifier)
        try:
            accepted = self._permission_handler(
                PolicyDecision.CONFIRM, response["tool"], response["arguments"],
            ) is True
        except Exception:
            accepted = False
        self._socket.sendall(encode_frame(
            {"method": "confirm", "id": identifier, "accepted": accepted}, MAX_REQUEST_BYTES,
        ))
