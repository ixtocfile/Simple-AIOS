"""Exercise real Unix sockets and daemon processes with an offline provider."""

from contextlib import closing
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import Mock

import pytest

from aios.daemon import MAX_REQUEST_BYTES, _listener, main
from aios.__main__ import main as cli_main
from aios.client import DaemonClient, DaemonError
from aios.config import Config


# Run the real entry point in a separate process; only external effects are faked.
FAKE_DAEMON = r'''
import json, signal, sqlite3, sys, time
from pathlib import Path
from unittest.mock import Mock, patch
from aios import core, daemon
from aios.llm import FakeLLMProvider
from aios.ollama import OllamaError
from aios.tools import ToolResult

options = json.loads(sys.argv[1])
provider = FakeLLMProvider(options["responses"])
chat = provider.chat
def respond(messages):
    response = chat(messages)
    if response == "__provider_error__":
        raise OllamaError("password=private-provider-detail")
    if response == "__wait__":
        Path("provider-entered").touch()
        signal.pause()
    if response == "__wait_for_release__":
        Path("provider-entered").touch()
        while not Path("provider-release").exists():
            time.sleep(0.01)
        return "Terminé"
    return response
provider.chat = respond
registry = core.build_tool_registry()
executed = []
def execute(name, arguments):
    executed.append({"tool": name, "arguments": arguments})
    return ToolResult(success=True, data={"observed": name})
for tool in registry.list_tools():
    tool._execute = lambda arguments, name=tool.name: execute(name, arguments)
core.build_tool_registry = lambda: registry
daemon.CLIENT_TIMEOUT = options.get("timeout", 30.0)
if options.get("storage_error"):
    daemon.TaskHistory.start = Mock(side_effect=sqlite3.OperationalError("token=private-storage-detail"))
with patch.object(daemon, "OllamaProvider", return_value=provider), patch("builtins.input", side_effect=AssertionError("No terminal")):
    status = daemon.main(sys.argv[2:])
print(json.dumps({"calls": provider.calls, "executed": executed}))
raise SystemExit(status)
'''


def wait_for(predicate, process):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        assert process.poll() is None, "Daemon exited before it was ready"
        time.sleep(0.01)
    pytest.fail("Daemon did not become ready")


def connect(path):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(5)
    try:
        client.connect(str(path))
    except BaseException:
        client.close()
        raise
    return client


def exchange(client, stream, request):
    client.sendall((json.dumps(request) + "\n").encode())
    return json.loads(stream.readline())


def finish(process, signum=signal.SIGTERM, expected=0):
    if process.poll() is None and signum is not None:
        process.send_signal(signum)
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == expected, stderr
    if expected == 0:
        assert stderr == ""
    else:
        assert stderr == "Le daemon a rencontré une erreur. Consultez les logs.\n"
    return json.loads(stdout) if stdout else None


@pytest.fixture
def daemon_dir():
    # Keep paths below Linux's Unix socket pathname limit, even with long test IDs.
    with TemporaryDirectory(prefix="aiosd-") as directory:
        yield Path(directory)


@pytest.fixture
def start_daemon(daemon_dir):
    processes = []

    def start(responses=(), *, timeout=30.0, storage_error=False, installed=False, custom=False):
        config = daemon_dir / "config.toml"
        config.write_text('data_dir = "data"\n', encoding="utf-8")
        path = daemon_dir / ("custom.sock" if custom else "data/aiosd.sock")
        options = {"responses": responses, "timeout": timeout, "storage_error": storage_error}
        command = (
            [str(Path(sys.executable).with_name("aiosd"))] if installed else
            [sys.executable, "-I", "-c", FAKE_DAEMON, json.dumps(options)]
        )
        command += ["--config", str(config)]
        if custom:
            command += ["--socket", str(path)]
        process = subprocess.Popen(
            command, cwd=daemon_dir, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(process)

        def ready():
            try:
                with connect(path):
                    return True
            except OSError:
                return False

        wait_for(ready, process)
        return process, path

    yield start
    for process in processes:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


def test_conversation_context_belongs_to_connection_and_history_is_shared(start_daemon, daemon_dir):
    process, path = start_daemon(["Réponse A", "Suite A", "Réponse B"])
    with connect(path) as client, client.makefile("rb") as stream:
        assert exchange(client, stream, {"method": "chat", "message": "  Demande A  "}) == {
            "ok": True, "result": "Réponse A",
        }
        assert exchange(client, stream, {"method": "chat", "message": "Suite"})["result"] == "Suite A"
    with connect(path) as client, client.makefile("rb") as stream:
        assert exchange(client, stream, {"method": "chat", "message": "Demande B"})["result"] == "Réponse B"
        history = exchange(client, stream, {"method": "history"})["result"]
    report = finish(process)

    assert [row["task"] for row in history] == ["Demande B", "Suite", "Demande A"]
    assert all(row["status"] == "completed" for row in history)
    first, followup, new = report["calls"]
    assert [message["role"] for message in first] == ["system", "user"]
    assert followup == [*first, {"role": "assistant", "content": "Réponse A"}, {"role": "user", "content": "Suite"}]
    assert new == [first[0], {"role": "user", "content": "Demande B"}]
    assert not path.exists()
    logs = (daemon_dir / "data/logs/simple-aios.log").read_text()
    assert "Daemon started" in logs and "Daemon stopped" in logs
    assert not any(text in logs for text in ("Demande", "Réponse", "Suite"))


def test_stream_framing_accepts_fragmented_and_concatenated_requests(start_daemon):
    process, path = start_daemon(["Une réponse\nsur deux lignes", "Fin"])
    with connect(path) as client, client.makefile("rb") as stream:
        client.sendall(b'{"method":"chat","message":"')
        client.sendall('Bonjour é"}\n{"method":"chat","message":"Suite"}\n'.encode())
        assert json.loads(stream.readline()) == {"ok": True, "result": "Une réponse\nsur deux lignes"}
        assert json.loads(stream.readline()) == {"ok": True, "result": "Fin"}
    assert len(finish(process)["calls"]) == 2


@pytest.mark.parametrize("raw", [
    b"\n", b"{}\n", b"{broken}\n", b"[]\n",
    b'{"method":"unknown"}\n', b'{"method":[]}\n',
    b'{"method":"history","method":"diagnose"}\n',
    b'{"method":"history","extra":true}\n',
    b'{"method":"chat","message":"ok","confirmed":true}\n',
    b'{"method":"chat","message":"ok","confirmations":1}\n',
    b'{"method":"confirm","id":"preauthorized","accepted":true}\n',
    b'{"method":"chat","message":""}\n',
    b'{"method":"chat","message":"  "}\n',
    b'{"method":"chat","message":42}\n',
    b'{"method":"chat","message":NaN}\n',
    b'{"method":"chat","message":"\\ud800"}\n',
    b'{"method":"chat","message":"\xff"}\n',
    b'{"method":"history"}',
    b'{"method":"history"} {"method":"history"}\n',
    b" " * MAX_REQUEST_BYTES + b"\n",
    b'{"method":"history","extra":' + b"[" * 1500 + b"0" + b"]" * 1500 + b"}\n",
], ids=[
    "empty", "missing-method", "malformed", "array", "unknown-method", "wrong-method-type",
    "duplicate-field", "extra-field", "injected-consent", "invalid-capability", "preauthorized",
    "empty-message", "blank-message",
    "wrong-message-type", "non-finite", "surrogate", "invalid-utf8", "truncated",
    "multiple-objects", "oversized", "too-deep",
])
def test_invalid_requests_are_refused_before_core_and_close_only_that_client(start_daemon, raw):
    process, path = start_daemon()
    with connect(path) as client, client.makefile("rb") as stream:
        client.sendall(raw)
        client.shutdown(socket.SHUT_WR)
        assert json.loads(stream.readline()) == {"ok": False, "error": "Invalid request"}
        assert stream.readline() == b""
    with connect(path) as client, client.makefile("rb") as stream:
        assert exchange(client, stream, {"method": "history"}) == {"ok": True, "result": []}
    assert finish(process) == {"calls": [], "executed": []}


def test_request_at_byte_limit_is_accepted(start_daemon):
    process, path = start_daemon(["Reçu"])
    prefix = b'{"method":"chat","message":"'
    suffix = b'"}\n'
    message = b"x" * (MAX_REQUEST_BYTES - len(prefix) - len(suffix))
    with connect(path) as client, client.makefile("rb") as stream:
        client.sendall(prefix + message + suffix)
        assert json.loads(stream.readline()) == {"ok": True, "result": "Reçu"}
    assert finish(process)["calls"][0][-1]["content"] == message.decode()


def test_idle_client_times_out_without_starting_a_task(start_daemon):
    process, path = start_daemon(timeout=0.1)
    with connect(path) as client:
        client.sendall(b'{"method":')
        assert client.recv(1) == b""
    with connect(path) as client, client.makefile("rb") as stream:
        assert exchange(client, stream, {"method": "history"}) == {"ok": True, "result": []}
    assert finish(process)["calls"] == []


def test_daemon_keeps_policy_and_tool_budget_without_terminal_confirmation(start_daemon):
    restart = '{"tool":"systemd.restart","arguments":{"service":"demo.service"}}'
    read = '{"tool":"system.info","arguments":{}}'
    process, path = start_daemon([restart, "Refus reçu"] + [read] * 6)
    with connect(path) as client, client.makefile("rb") as stream:
        assert exchange(client, stream, {"method": "chat", "message": "Redémarre"})["result"] == "Refus reçu"
        assert "Limite de 5" in exchange(client, stream, {"method": "chat", "message": "Consulte"})["result"]
        history = exchange(client, stream, {"method": "history"})["result"]
    report = finish(process)
    assert [call["tool"] for call in report["executed"]] == ["system.info"] * 5
    refused = json.loads(report["calls"][1][-1]["content"])["tool_result"]
    assert refused["success"] is False and refused["error"] == "Tool execution denied"
    assert len(history[0]["tools"]) == 5
    assert history[1]["tools"][0]["status"] == "failed"


def test_diagnostic_uses_five_read_tools_and_records_one_task(start_daemon):
    process, path = start_daemon(["Diagnostic reçu"])
    with connect(path) as client, client.makefile("rb") as stream:
        assert exchange(client, stream, {"method": "diagnose"}) == {"ok": True, "result": "Diagnostic reçu"}
        history = exchange(client, stream, {"method": "history"})["result"]
    report = finish(process)
    assert [call["tool"] for call in report["executed"]] == [
        "system.info", "system.memory", "system.disk", "process.list", "systemd.list",
    ]
    assert len(report["calls"]) == 1 and len(history) == 1
    assert history[0]["task"] == "/diagnose" and len(history[0]["tools"]) == 5


def test_provider_failure_preserves_tool_result_and_session_without_retry(start_daemon, daemon_dir):
    call = '{"tool":"system.info","arguments":{}}'
    process, path = start_daemon([call, "__provider_error__", "Suite"])
    with connect(path) as client, client.makefile("rb") as stream:
        assert exchange(client, stream, {"method": "chat", "message": "Demande"}) == {
            "ok": False, "error": "Provider unavailable",
        }
        assert exchange(client, stream, {"method": "chat", "message": "Reprends"})["result"] == "Suite"
        history = exchange(client, stream, {"method": "history"})["result"]
    report = finish(process)
    assert len(report["executed"]) == 1 and len(report["calls"]) == 3
    assert report["calls"][2] == [*report["calls"][1], {"role": "user", "content": "Reprends"}]
    assert history[1]["status"] == "failed" and history[1]["tools"][0]["status"] == "succeeded"
    assert "private-provider-detail" not in (daemon_dir / "data/logs/simple-aios.log").read_text()
    assert "private-provider-detail" not in json.dumps(history)


def test_storage_failure_returns_generic_error_and_stops_without_calling_provider(start_daemon, daemon_dir):
    process, path = start_daemon(storage_error=True)
    with connect(path) as client, client.makefile("rb") as stream:
        assert exchange(client, stream, {"method": "chat", "message": "Demande"}) == {
            "ok": False, "error": "Request failed",
        }
    assert finish(process, signum=None, expected=1)["calls"] == []
    assert not path.exists()
    assert "private-storage-detail" not in (daemon_dir / "data/logs/simple-aios.log").read_text()


def test_disconnect_does_not_retry_an_executed_tool_or_break_the_next_session(start_daemon, daemon_dir):
    call = '{"tool":"system.info","arguments":{}}'
    process, path = start_daemon([call, "__wait_for_release__", "Nouvelle session"])
    with connect(path) as client:
        client.sendall(b'{"method":"chat","message":"Demande"}\n')
        wait_for(lambda: (daemon_dir / "provider-entered").exists(), process)
    (daemon_dir / "provider-release").touch()
    with connect(path) as client, client.makefile("rb") as stream:
        history = exchange(client, stream, {"method": "history"})["result"]
        assert history[0]["status"] == "completed"
        assert history[0]["tools"][0]["status"] == "succeeded"
        assert exchange(client, stream, {"method": "chat", "message": "Suite"})["result"] == "Nouvelle session"
    report = finish(process)
    assert len(report["executed"]) == 1 and len(report["calls"]) == 3
    assert [message["role"] for message in report["calls"][2]] == ["system", "user"]


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_shutdown_during_provider_call_records_interruption_and_removes_socket(start_daemon, daemon_dir, signum):
    process, path = start_daemon(["__wait__"])
    with connect(path) as client:
        client.sendall(b'{"method":"chat","message":"En cours"}\n')
        wait_for(lambda: (daemon_dir / "provider-entered").exists(), process)
        assert len(finish(process, signum=signum)["calls"]) == 1
        assert client.recv(1) == b""
    assert not path.exists()
    with closing(sqlite3.connect(daemon_dir / "data/history.sqlite3")) as connection:
        assert connection.execute("SELECT status FROM tasks").fetchall() == [("interrupted",)]


@pytest.mark.parametrize("custom", [False, True])
def test_installed_aiosd_serves_history_without_ollama_and_closes_resources(start_daemon, daemon_dir, custom):
    process, path = start_daemon(installed=True, custom=custom)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with connect(path) as client, client.makefile("rb") as stream:
        assert exchange(client, stream, {"method": "history"}) == {"ok": True, "result": []}
    assert finish(process) is None
    assert not path.exists()
    with closing(sqlite3.connect(daemon_dir / "data/history.sqlite3")) as connection:
        connection.execute("BEGIN EXCLUSIVE")


@pytest.mark.parametrize("kind", ["file", "symlink", "stale-socket", "live-socket"])
def test_listener_never_replaces_existing_paths(daemon_dir, kind):
    path = daemon_dir / "occupied.sock"
    target = daemon_dir / "target"
    target.write_text("preserve")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as existing:
        if kind == "file":
            path.write_text("preserve")
        elif kind == "symlink":
            path.symlink_to(target)
        else:
            existing.bind(str(path))
            if kind == "live-socket":
                existing.listen(1)
            else:
                existing.close()
        identity = path.lstat()
        with pytest.raises(OSError), _listener(path):
            pytest.fail("An occupied path must not be bound")
        assert path.lstat().st_ino == identity.st_ino
        assert target.read_text() == "preserve"
        if kind == "file":
            assert path.read_text() == "preserve"


def test_listener_is_private_at_bind_and_restores_umask_and_cleans_on_error(daemon_dir):
    path = daemon_dir / "new" / "aiosd.sock"
    old_umask = os.umask(0)
    try:
        with pytest.raises(RuntimeError), _listener(path):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert os.umask(0) == 0
            raise RuntimeError("simulated error")
        assert not path.exists()
    finally:
        os.umask(old_umask)


def test_cleanup_preserves_a_replacement_file(daemon_dir):
    path = daemon_dir / "aiosd.sock"
    with _listener(path):
        path.unlink()
        path.write_text("replacement")
    assert path.read_text() == "replacement"


def test_main_reports_startup_errors_without_details_and_restores_handlers(daemon_dir, capsys):
    config = daemon_dir / "config.toml"
    config.write_text(f'data_dir = "{daemon_dir}/data"\n')
    occupied = daemon_dir / "occupied.sock"
    occupied.write_text("preserve")
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    assert main(["--config", str(config), "--socket", str(occupied)]) == 1
    assert occupied.read_text() == "preserve"
    assert all(signal.getsignal(sig) is handler for sig, handler in before.items())
    captured = capsys.readouterr()
    assert captured.out == "" and "Traceback" not in captured.err
    assert str(occupied) not in captured.err


@pytest.mark.parametrize("setting", ["missing", "provider"])
def test_invalid_configuration_or_unsupported_provider_never_starts_a_socket(daemon_dir, setting, capsys):
    config = daemon_dir / "config.toml"
    if setting == "provider":
        config.write_text(f'data_dir = "{daemon_dir}/data"\nprovider = "unsupported"\n')
    assert main(["--config", str(config)]) == 1
    assert not (daemon_dir / "data/aiosd.sock").exists()
    captured = capsys.readouterr()
    assert captured.out == "" and "Traceback" not in captured.err


@pytest.mark.parametrize("custom", [False, True])
def test_installed_cli_uses_daemon_for_chat_diagnostic_and_history(start_daemon, daemon_dir, custom):
    process, path = start_daemon(["Bonjour du daemon", "Suite du daemon", "Bilan du daemon"], custom=custom)
    command = [sys.executable, "-I", "-m", "aios", "--config", str(daemon_dir / "config.toml")]
    if custom:
        command += ["--socket", str(path)]
    result = subprocess.run(
        command, input="/help\n/version\n\n/unknown\nBonjour\nSuite\n/diagnose\n/history\n/exit\n",
        text=True, capture_output=True, cwd=daemon_dir, timeout=5,
    )
    assert result.returncode == 0 and result.stderr == ""
    assert all(text in result.stdout for text in (
        "Simple-AIOS", "Bonjour du daemon", "Suite du daemon", "Bilan du daemon", "Tâche :", "Outil :",
    ))
    assert process.poll() is None  # /exit closes the client, not the daemon.
    with connect(path) as client, client.makefile("rb") as stream:
        history = exchange(client, stream, {"method": "history"})["result"]
    report = finish(process)
    assert len(history) == 3 and len(report["calls"]) == 3
    assert report["calls"][1] == [*report["calls"][0],
        {"role": "assistant", "content": "Bonjour du daemon"}, {"role": "user", "content": "Suite"},
    ]
    assert len(report["executed"]) == 5


@pytest.mark.parametrize(("answer", "interactive", "allowed"), [
    ("oui", True, True), ("", True, False), ("oui", False, False),
    (EOFError, True, False), (KeyboardInterrupt, True, False),
])
def test_cli_confirmation_round_trip_is_explicit_and_executes_only_in_daemon(
    start_daemon, daemon_dir, monkeypatch, capsys, answer, interactive, allowed,
):
    call = '{"tool":"systemd.restart","arguments":{"service":"demo.service"}}'
    process, path = start_daemon([call, "Résultat reçu"])
    entries = ["Redémarre", *([answer] if interactive else []), "/exit"]
    reader = Mock(side_effect=entries)
    monkeypatch.setattr("builtins.input", reader)
    monkeypatch.setattr("sys.stdin.isatty", lambda: interactive)
    monkeypatch.setattr("aios.__main__.load_config", lambda _: Config(data_dir=daemon_dir / "client"))
    blocked = Mock(side_effect=AssertionError("No local Core, provider or SQLite"))
    for target in ("aios.core.Core", "aios.ollama.OllamaProvider", "aios.history.TaskHistory"):
        monkeypatch.setattr(target, blocked)
    assert cli_main(["--socket", str(path)]) == 0
    blocked.assert_not_called()
    assert reader.call_count == len(entries)
    assert not (daemon_dir / "client/history.sqlite3").exists()
    report = finish(process)
    assert len(report["executed"]) == int(allowed)
    feedback = json.loads(report["calls"][1][-1]["content"])["tool_result"]
    assert feedback["success"] is allowed
    captured = capsys.readouterr()
    assert "Résultat reçu" in captured.out and captured.err == ""
    assert "Action à confirmer" in captured.out if interactive else "terminal interactif requis" in captured.out


def test_confirmation_nonce_cannot_be_reused_for_the_next_action(start_daemon):
    call = '{"tool":"systemd.restart","arguments":{"service":"demo.service"}}'
    process, path = start_daemon([call, call, "Terminé"])
    with connect(path) as client, client.makefile("rb") as stream:
        prompt = exchange(client, stream, {"method": "chat", "message": "Redémarre", "confirmations": True})
        assert prompt["event"] == "confirmation" and prompt["arguments"] == {"service": "demo.service"}
        second = exchange(client, stream, {"method": "confirm", "id": prompt["id"], "accepted": True})
        assert second["event"] == "confirmation" and second["id"] != prompt["id"]
        client.sendall((json.dumps({"method": "confirm", "id": prompt["id"], "accepted": True}) + "\n").encode())
        assert stream.readline() == b""
    report = finish(process)
    assert len(report["executed"]) == 1
    assert json.loads(report["calls"][2][-1]["content"])["tool_result"]["error"] == "Tool execution denied"


@pytest.mark.parametrize("answer", ["truthy", "extra", "disconnect", "partial-timeout"])
def test_invalid_or_lost_confirmation_fails_closed(start_daemon, answer):
    call = '{"tool":"systemd.restart","arguments":{"service":"demo.service"}}'
    process, path = start_daemon([call, "Refus"], timeout=0.1)
    with connect(path) as client, client.makefile("rb") as stream:
        prompt = exchange(client, stream, {"method": "chat", "message": "Redémarre", "confirmations": True})
        response = {"method": "confirm", "id": prompt["id"], "accepted": True}
        if answer == "disconnect":
            client.shutdown(socket.SHUT_WR)
        elif answer == "partial-timeout":
            client.sendall(b'{"method":')
        else:
            if answer == "truthy":
                response["accepted"] = 1
            else:
                response["arguments"] = {"service": "other.service"}
            client.sendall((json.dumps(response) + "\n").encode())
        assert stream.readline() == b""
    report = finish(process)
    assert report["executed"] == []
    assert json.loads(report["calls"][1][-1]["content"])["tool_result"]["error"] == "Tool execution denied"


def test_invalid_service_is_rejected_before_remote_confirmation(start_daemon):
    call = '{"tool":"systemd.restart","arguments":{"service":"demo.service;reboot"}}'
    process, path = start_daemon([call, "Refus"])
    handler = Mock(return_value=True)
    with closing(DaemonClient(path, permission_handler=handler)) as client:
        assert client.chat("Demande") == "Refus"
    handler.assert_not_called()
    assert finish(process)["executed"] == []


def test_cli_can_continue_after_provider_error_without_reconnection(start_daemon, daemon_dir):
    process, path = start_daemon(["__provider_error__", "Disponible"])
    result = subprocess.run(
        [sys.executable, "-I", "-m", "aios", "--config", str(daemon_dir / "config.toml")],
        cwd=daemon_dir, input="Demande\nSuite\n/exit\n", text=True, capture_output=True, timeout=5,
    )
    assert result.returncode == 0 and "Disponible" in result.stdout
    assert "Impossible d'obtenir une réponse du LLM" in result.stderr
    assert "private-provider-detail" not in result.stderr
    assert len(finish(process)["calls"]) == 2


def test_client_session_survives_user_thinking_past_frame_timeout(start_daemon):
    process, path = start_daemon(["Début", "Suite"], timeout=0.1)
    with closing(DaemonClient(path)) as client:
        assert client.chat("Première demande") == "Début"
        time.sleep(0.15)
        assert client.chat("Autre demande") == "Suite"
    calls = finish(process)["calls"]
    assert calls[1] == [*calls[0], {"role": "assistant", "content": "Début"}, {"role": "user", "content": "Autre demande"}]


def test_client_timeout_does_not_retry_or_replace_the_session(start_daemon):
    process, path = start_daemon(["__wait__"])
    with closing(DaemonClient(path, timeout=0.1)) as client:
        with pytest.raises(DaemonError):
            client.chat("Demande")
        with pytest.raises(DaemonError):
            client.chat("Ne pas relancer")
    assert len(finish(process)["calls"]) == 1
