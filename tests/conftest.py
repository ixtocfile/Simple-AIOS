"""Keep Core/terminal regression tests independent of the socket transport."""

from unittest.mock import Mock

import pytest

from aios.client import DaemonProviderError
from aios.core import Core
from aios.history import TaskHistory
from aios.ollama import OllamaError


@pytest.fixture
def core_client(monkeypatch):
    """Supply an in-process backend only to tests that exercise Core behavior.

    Production CLI/daemon communication is covered separately over real sockets.
    """
    def bind(provider, history_factory=TaskHistory):
        class InProcessClient(Core):
            def __init__(self, socket_path, *, permission_handler):
                self.history = history_factory(socket_path.parent)
                super().__init__(provider, self.history, permission_handler=permission_handler)

            def _request(self, text, *, diagnostic):
                try:
                    return super()._request(text, diagnostic=diagnostic)
                except OllamaError:
                    raise DaemonProviderError("Provider unavailable") from None

            def close(self):
                self.history.close()

        constructor = Mock(side_effect=InProcessClient)
        monkeypatch.setattr("aios.__main__.DaemonClient", constructor)
        return constructor

    return bind
