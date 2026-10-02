"""Client boundaries: strict replies, explicit consent and no automatic retry."""

from contextlib import closing
from io import BytesIO
import json
from unittest.mock import Mock

import pytest

from aios.client import DaemonClient, DaemonError, DaemonProviderError, RequestError
from aios.policy import PolicyDecision


def frame(value):
    return (json.dumps(value) + "\n").encode()


@pytest.fixture
def transport(monkeypatch):
    connection = Mock()
    factory = Mock(return_value=connection)
    monkeypatch.setattr("aios.client.socket.socket", factory)

    def prepare(data):
        stream = BytesIO(data)
        connection.makefile.return_value = stream
        return connection, factory, stream

    return prepare


def test_client_connects_lazily_and_reuses_one_connection_for_all_methods(transport, tmp_path):
    connection, factory, stream = transport(b''.join(frame({"ok": True, "result": value}) for value in ["Réponse", "Bilan", []]))
    with closing(DaemonClient(tmp_path / "aiosd.sock")) as client:
        factory.assert_not_called()
        assert client.chat(" Bonjour ") == "Réponse"
        assert client.diagnose() == "Bilan"
        assert client.recent_history() == []
    factory.assert_called_once()
    connection.connect.assert_called_once_with(str(tmp_path / "aiosd.sock"))
    assert [json.loads(call.args[0]) for call in connection.sendall.call_args_list] == [
        {"method": "chat", "message": "Bonjour"}, {"method": "diagnose"}, {"method": "history"},
    ]
    assert stream.closed
    connection.close.assert_called_once()


@pytest.mark.parametrize("raw", [
    b"", b'{"ok":true,"result":"partial"}', b"not json\n", b"[]\n",
    b'{"ok":true,"ok":false,"result":"dup"}\n',
    b'{"ok":1,"result":"wrong bool"}\n', b'{"ok":true,"result":null}\n',
    b'{"ok":true,"result":NaN}\n', b'{"ok":true,"result":"\\ud800"}\n',
    b'{"ok":true,"result":"\xff"}\n', b'{"ok":true,"result":"ok","extra":0}\n',
    b'{"ok":false,"error":"token=private-error"}\n',
    b'{"event":"confirmation","id":"unexpected"}\n',
])
def test_invalid_or_failed_responses_close_session_without_echo_or_retry(transport, tmp_path, raw):
    connection, factory, stream = transport(raw)
    client = DaemonClient(tmp_path / "aiosd.sock")
    with pytest.raises(DaemonError) as error:
        client.chat("Demande")
    assert "private-error" not in str(error.value)
    assert stream.closed
    with pytest.raises(DaemonError):
        client.chat("Ne pas renvoyer")
    assert connection.sendall.call_count == 1 and factory.call_count == 1


def test_oversized_response_closes_without_accepting_a_truncated_result(transport, tmp_path, monkeypatch):
    connection, _, stream = transport(frame({"ok": True, "result": "x" * 100}))
    monkeypatch.setattr("aios.client.MAX_RESPONSE_BYTES", 64)
    with pytest.raises(DaemonError):
        DaemonClient(tmp_path / "aiosd.sock").chat("Demande")
    assert stream.closed and connection.sendall.call_count == 1


@pytest.mark.parametrize("message", [None, "", " \t", "\ud800", "x" * (64 * 1024)], ids=["type", "empty", "blank", "unicode", "size"])
def test_invalid_local_messages_are_not_sent(transport, tmp_path, message):
    connection, factory, _ = transport(b"")
    with closing(DaemonClient(tmp_path / "aiosd.sock")) as client:
        with pytest.raises(RequestError):
            client.chat(message)
    factory.assert_not_called()
    connection.sendall.assert_not_called()


def test_provider_error_preserves_connection_and_never_repeats_request(transport, tmp_path):
    connection, factory, _ = transport(frame({"ok": False, "error": "Provider unavailable"}) + frame({"ok": True, "result": "Suite"}))
    with closing(DaemonClient(tmp_path / "aiosd.sock")) as client:
        with pytest.raises(DaemonProviderError):
            client.chat("Demande")
        assert client.chat("Autre demande") == "Suite"
    assert connection.sendall.call_count == 2 and factory.call_count == 1


@pytest.mark.parametrize("failure", ["connect", "send", "read", "interrupt"])
def test_transport_failures_release_resources_without_reconnect(transport, tmp_path, failure):
    connection, factory, stream = transport(b"")
    error = KeyboardInterrupt() if failure == "interrupt" else OSError("password=private-detail")
    if failure == "connect":
        connection.connect.side_effect = error
    elif failure == "send":
        connection.sendall.side_effect = error
    else:
        stream = Mock()
        stream.readline.side_effect = error
        connection.makefile.return_value = stream
    client = DaemonClient(tmp_path / "aiosd.sock")
    with pytest.raises(KeyboardInterrupt if failure == "interrupt" else DaemonError):
        client.chat("Demande")
    with pytest.raises(DaemonError):
        client.chat("Suite")
    factory.assert_called_once()
    connection.close.assert_called_once()


@pytest.mark.parametrize("answer", [True, False, "oui", 1, None, RuntimeError("private callback detail")])
def test_only_exact_callback_true_is_sent_as_approval(transport, tmp_path, answer):
    event = {"event": "confirmation", "id": "a" * 32, "tool": "systemd.restart", "arguments": {"service": "demo.service"}}
    connection, _, _ = transport(frame(event) + frame({"ok": True, "result": "Résultat"}))
    handler = Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
    with closing(DaemonClient(tmp_path / "aiosd.sock", permission_handler=handler)) as client:
        assert client.chat("Redémarre") == "Résultat"
    handler.assert_called_once_with(PolicyDecision.CONFIRM, "systemd.restart", {"service": "demo.service"})
    assert json.loads(connection.sendall.call_args_list[1].args[0]) == {
        "method": "confirm", "id": "a" * 32, "accepted": answer is True,
    }


def test_replayed_confirmation_is_not_presented_twice(transport, tmp_path):
    event = {"event": "confirmation", "id": "a" * 32, "tool": "systemd.restart", "arguments": {"service": "demo.service"}}
    connection, _, _ = transport(frame(event) * 2)
    handler = Mock(return_value=True)
    with closing(DaemonClient(tmp_path / "aiosd.sock", permission_handler=handler)) as client:
        with pytest.raises(DaemonError):
            client.chat("Redémarre")
    assert handler.call_count == 1 and connection.sendall.call_count == 2


@pytest.mark.parametrize(("key", "value"), [
    ("event", "other"), ("id", "invalid"), ("arguments", []), ("tool", 42), ("extra", True),
])
def test_malformed_confirmation_is_rejected_without_prompt(transport, tmp_path, key, value):
    event = {"event": "confirmation", "id": "a" * 32, "tool": "systemd.restart", "arguments": {}}
    event[key] = value
    connection, _, _ = transport(frame(event))
    handler = Mock(return_value=True)
    with closing(DaemonClient(tmp_path / "aiosd.sock", permission_handler=handler)) as client:
        with pytest.raises(DaemonError):
            client.chat("Demande")
    handler.assert_not_called()
    assert connection.sendall.call_count == 1


def test_client_never_presents_a_sixth_confirmation(transport, tmp_path):
    events = b"".join(frame({
        "event": "confirmation", "id": f"{number:032x}", "tool": "systemd.restart", "arguments": {},
    }) for number in range(6))
    connection, _, _ = transport(events)
    handler = Mock(return_value=True)
    with closing(DaemonClient(tmp_path / "aiosd.sock", permission_handler=handler)) as client:
        with pytest.raises(DaemonError):
            client.chat("Demande")
    assert handler.call_count == 5 and connection.sendall.call_count == 6


@pytest.mark.parametrize("history", [["invalid"], [{}], [{"tools": ["invalid"]}]])
def test_invalid_history_is_rejected_before_rendering(transport, tmp_path, history):
    transport(frame({"ok": True, "result": history}))
    with closing(DaemonClient(tmp_path / "aiosd.sock")) as client:
        with pytest.raises(DaemonError):
            client.recent_history()
