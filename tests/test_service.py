"""Validate the user unit and its command without installing a host service."""

from configparser import ConfigParser
from contextlib import closing
import os
from pathlib import Path
import shlex
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import pytest

from aios.client import DaemonClient


UNIT = Path(__file__).resolve().parents[1] / "systemd" / "simple-aios.service"


@pytest.fixture
def service():
    # A short path keeps the default Unix socket below Linux's length limit.
    with TemporaryDirectory(prefix="aios-service-") as directory:
        user_home = Path(directory)
        checkout = user_home / "Simple-AIOS"
        checkout.mkdir()
        (checkout / ".venv").symlink_to(Path(sys.executable).parent.parent)
        contents = UNIT.read_text(encoding="utf-8").replace("%h", str(user_home))
        parser = ConfigParser(interpolation=None)
        parser.read_string(contents)
        yield user_home, contents, parser


def test_user_unit_passes_systemd_verification(service):
    analyzer = shutil.which("systemd-analyze")
    if analyzer is None:
        pytest.skip("systemd-analyze is not installed")
    user_home, contents, _ = service
    unit = user_home / UNIT.name
    unit.write_text(contents, encoding="utf-8")
    runtime = user_home / "runtime"
    runtime.mkdir(mode=0o700)
    result = subprocess.run(
        [analyzer, "--user", "--man=no", "--generators=no",
         "--recursive-errors=yes", "verify", str(unit)],
        env={**os.environ, "XDG_RUNTIME_DIR": str(runtime)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_service_command_serves_client_and_stops_without_losing_history(service):
    user_home, _, unit = service
    settings = unit["Service"]
    assert "User" not in settings and "Group" not in settings
    assert unit["Install"]["WantedBy"] == "default.target"
    assert settings["NoNewPrivileges"] == "yes"
    assert settings["Restart"] == "no"
    process = subprocess.Popen(
        shlex.split(settings["ExecStart"]),
        cwd=settings["WorkingDirectory"],
        env={**os.environ, "HOME": str(user_home)},
        umask=int(settings["UMask"], 8), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    data = user_home / ".local/share/simple-aios"
    path = data / "aiosd.sock"
    database = data / "history.sqlite3"
    log = data / "logs/simple-aios.log"
    try:
        deadline = time.monotonic() + 5
        while True:
            assert process.poll() is None, "Service command exited before listening"
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(1)
                    probe.connect(str(path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                assert time.monotonic() < deadline, "Service command did not listen"
                time.sleep(0.01)

        client = DaemonClient(path)
        try:
            assert client.recent_history() == []
        finally:
            client.close()
        for private_file in (path, database, log):
            assert stat.S_IMODE(private_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(data.stat().st_mode) == 0o700
        before = database.read_bytes()
        process.terminate()  # systemd's default stop signal is SIGTERM.
        stdout, stderr = process.communicate(timeout=float(settings["TimeoutStopSec"]))
        assert process.returncode == 0
        assert stdout == stderr == ""
        assert not path.exists()
        assert database.read_bytes() == before
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("BEGIN EXCLUSIVE")
        assert "Daemon stopped" in log.read_text(encoding="utf-8")
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
