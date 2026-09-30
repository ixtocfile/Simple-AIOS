"""Exercise Ollama HTTP exchanges without a server, network or real LLM."""

from http.client import IncompleteRead
from io import BytesIO
import json
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from aios.config import Config
from aios.llm import LLMProvider
from aios.ollama import OllamaError, OllamaProvider


@pytest.fixture
def transport(monkeypatch):
    opener = Mock()
    monkeypatch.setattr("aios.ollama.urlopen", opener)
    return opener


@pytest.mark.parametrize("base_url", ["http://localhost:12345", "http://localhost:12345/"])
def test_chat_sends_configured_request_and_preserves_messages(transport, base_url):
    response = BytesIO(json.dumps({
        "message": {"role": "assistant", "content": "Réponse complète."},
        "done": True,
    }, ensure_ascii=False).encode("utf-8"))
    transport.return_value = response
    provider: LLMProvider = OllamaProvider(
        Config(model="test-model", ollama_url=base_url), timeout=2.5
    )
    messages = (
        {"role": "system", "content": "Réponds en français."},
        {"role": "user", "content": "Bonjour"},
        {"role": "assistant", "content": "Salut !"},
        {"role": "user", "content": "Comment vas-tu ?"},
    )
    original = [message.copy() for message in messages]

    assert provider.chat(messages) == "Réponse complète."

    transport.assert_called_once()
    request = transport.call_args.args[0]
    assert request.full_url == "http://localhost:12345/api/chat"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {
        "model": "test-model", "messages": original, "stream": False,
    }
    assert transport.call_args.kwargs == {"timeout": 2.5}
    assert list(messages) == original
    assert response.closed


def test_defaults_and_initialization_without_network(transport):
    config = Config()
    provider = OllamaProvider(config)
    transport.assert_not_called()
    transport.return_value = BytesIO(b'{"message": {"content": ""}}')

    assert provider.chat([]) == ""

    request = transport.call_args.args[0]
    assert request.full_url == config.ollama_url + "/api/chat"
    assert json.loads(request.data)["model"] == config.model
    assert transport.call_args.kwargs == {"timeout": 60.0}


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("-inf"), float("nan")])
def test_timeout_must_be_positive_and_finite(transport, timeout):
    with pytest.raises(ValueError, match="positive finite"):
        OllamaProvider(Config(), timeout=timeout)
    transport.assert_not_called()


@pytest.mark.parametrize(("error", "message"), [
    (TimeoutError("secret"), "Ollama request timed out"),
    (URLError(TimeoutError("secret")), "Ollama request timed out"),
    (URLError(ConnectionRefusedError("secret")), "Could not reach Ollama"),
    (ConnectionResetError("secret"), "Ollama connection failed"),
    (IncompleteRead(b"secret"), "Ollama connection failed"),
])
def test_transport_failures_have_safe_errors(transport, error, message):
    transport.side_effect = error

    with pytest.raises(OllamaError) as raised:
        OllamaProvider(Config()).chat([])

    assert str(raised.value) == message
    assert raised.value.__suppress_context__
    transport.assert_called_once()


@pytest.mark.parametrize("status", [400, 404, 500])
def test_http_errors_report_status_and_close_response(transport, status):
    response = BytesIO(b'{"error": "secret"}')
    transport.side_effect = HTTPError(
        "http://localhost/api/chat", status, "secret", {}, response
    )

    with pytest.raises(OllamaError, match=f"^Ollama returned HTTP {status}$"):
        OllamaProvider(Config()).chat([])

    assert response.closed


@pytest.mark.parametrize(("error", "message"), [
    (TimeoutError("secret"), "Ollama request timed out"),
    (IncompleteRead(b"secret"), "Ollama connection failed"),
])
def test_failures_while_reading_close_response(transport, error, message):
    class BrokenResponse(BytesIO):
        def read(self):
            raise error

    response = BrokenResponse()
    transport.return_value = response

    with pytest.raises(OllamaError) as raised:
        OllamaProvider(Config()).chat([])

    assert str(raised.value) == message
    assert response.closed


@pytest.mark.parametrize("body", [b"not JSON: secret", b"\xff"])
def test_invalid_json_or_encoding(transport, body):
    response = BytesIO(body)
    transport.return_value = response

    with pytest.raises(OllamaError, match="^Invalid Ollama response$"):
        OllamaProvider(Config()).chat([])

    assert response.closed


@pytest.mark.parametrize("payload", [
    None, [], {}, {"message": None}, {"message": {}},
    {"message": {"content": 42}},
])
def test_invalid_response_structure(transport, payload):
    transport.return_value = BytesIO(json.dumps(payload).encode("utf-8"))

    with pytest.raises(OllamaError, match="^Invalid Ollama response$"):
        OllamaProvider(Config()).chat([])


def test_api_error_takes_precedence_over_message_content(transport):
    transport.return_value = BytesIO(json.dumps({
        "error": "secret", "message": {"content": "partial reply"},
    }).encode("utf-8"))

    with pytest.raises(OllamaError, match="^Ollama reported an error$"):
        OllamaProvider(Config()).chat([])
