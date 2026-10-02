"""Exercise installer effects in temporary checkouts, without network or services."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
REAL_RUN = subprocess.run
spec = importlib.util.spec_from_file_location("aios_installer", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    project = tmp_path / "checkout with spaces %h é"
    (project / "systemd").mkdir(parents=True)
    shutil.copyfile(ROOT / "systemd/simple-aios.service", project / "systemd/simple-aios.service")
    user_home = tmp_path / "user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(installer.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(installer, "PROJECT_DIR", project)
    monkeypatch.chdir(tmp_path)

    def run(command, *, check):
        assert check is True
        if command[1:3] == ["-m", "venv"]:
            venv = Path(command[3])
            (venv / "bin").mkdir(parents=True)
            (venv / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
            (venv / "bin/python").symlink_to(sys.executable)
        elif command[1:4] == ["-m", "pip", "install"]:
            executable = project / ".venv/bin/aiosd"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
        return subprocess.CompletedProcess(command, 0)

    runner = Mock(side_effect=run)
    monkeypatch.setattr(installer.subprocess, "run", runner)
    target = user_home / ".config/systemd/user/simple-aios.service"
    return project, target, runner


def test_install_creates_venv_package_and_user_unit_from_any_working_directory(installation):
    project, target, runner = installation
    assert installer.install(project) == target
    calls = [call.args[0] for call in runner.call_args_list]
    assert calls[0] == [sys.executable, "-m", "venv", str(project / ".venv")]
    assert calls[1][0:2] == [str(project / ".venv/bin/python"), "-c"]
    assert calls[2] == [str(project / ".venv/bin/python"), "-m", "pip", "install", str(project)]
    assert len(calls) == 3  # No daemon start, systemctl, sudo, or LLM installation.
    contents = target.read_text()
    assert "UMask=0077\nNoNewPrivileges=yes\nRestart=no" in contents
    assert 'ExecStart="' in contents and "%%h" in contents
    assert target.stat().st_mode & 0o777 == 0o600
    assert not (target.parents[3] / ".local/share/simple-aios").exists()


def test_repeat_install_reuses_venv_and_preserves_unit_and_user_data(installation):
    project, target, runner = installation
    installer.install(project)
    identity = target.stat()
    config = target.parents[2] / "simple-aios/config.toml"
    config.parent.mkdir()
    config.write_text('model = "custom-model"\n')
    data = target.parents[3] / ".local/share/simple-aios/history.sqlite3"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"existing-history")
    runner.reset_mock()
    installer.install(project)
    assert len(runner.call_args_list) == 2
    assert target.stat().st_ino == identity.st_ino
    assert target.stat().st_mtime_ns == identity.st_mtime_ns
    assert config.read_text() == 'model = "custom-model"\n'
    assert data.read_bytes() == b"existing-history"


def test_install_respects_absolute_xdg_config_home(installation, tmp_path, monkeypatch):
    project, default, _ = installation
    directory = tmp_path / "custom config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(directory))
    target = installer.install(project)
    assert target == directory / "systemd/user/simple-aios.service"
    assert target.is_file() and not default.exists()


def test_generated_unit_with_special_path_passes_systemd_verification(installation, tmp_path):
    analyzer = shutil.which("systemd-analyze")
    if analyzer is None:
        pytest.skip("systemd-analyze is not installed")
    project, _, _ = installation
    target = installer.install(project)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    result = REAL_RUN(
        [analyzer, "--user", "--man=no", "--generators=no",
         "--recursive-errors=yes", "verify", str(target)],
        env={**os.environ, "XDG_RUNTIME_DIR": str(runtime)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", [
    "invalid\npath", "invalid'path", 'invalid"path', "invalid\\path",
    "invalid$VALUE", "invalid`path", "invalid{path", "invalid}path",
])
def test_unsupported_characters_in_checkout_path_are_rejected(installation, name):
    project, target, runner = installation
    moved = project.rename(project.with_name(name))
    with pytest.raises(ValueError, match="incompatible avec l'installation"):
        installer.install(moved)
    runner.assert_not_called()
    assert not target.exists()


@pytest.mark.parametrize("kind", ["custom", "directory", "symlink", "dangling-symlink"])
def test_existing_unit_is_preserved_before_any_installation(installation, kind):
    project, target, runner = installation
    target.parent.mkdir(parents=True)
    other = target.parent / "other.service"
    if kind == "custom":
        target.write_text("customized unit\n")
    elif kind == "directory":
        target.mkdir()
    else:
        if kind == "symlink":
            other.write_text("preserve\n")
        target.symlink_to(other)
    before = target.lstat()
    with pytest.raises(ValueError, match="préservée"):
        installer.install(project)
    runner.assert_not_called()
    assert target.lstat().st_ino == before.st_ino
    assert not (project / ".venv").exists()
    if kind == "custom":
        assert target.read_text() == "customized unit\n"
    if kind == "symlink":
        assert other.read_text() == "preserve\n"


@pytest.mark.parametrize("kind", ["root", "python", "platform", "relative-xdg", "venv", "venv-symlink", "template"])
def test_invalid_prerequisites_fail_before_mutation(installation, monkeypatch, kind):
    project, target, runner = installation
    if kind == "root":
        monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    elif kind == "python":
        monkeypatch.setattr(installer.sys, "version_info", (3, 11))
    elif kind == "platform":
        monkeypatch.setattr(installer.sys, "platform", "win32")
    elif kind == "relative-xdg":
        monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
    elif kind == "venv":
        (project / ".venv").mkdir()
    elif kind == "venv-symlink":
        (project / ".venv").symlink_to(project.parent / "missing")
    else:
        (project / "systemd/simple-aios.service").write_text("unexpected template\n")
    with pytest.raises(ValueError):
        installer.install(project)
    runner.assert_not_called()
    assert not target.exists()


@pytest.mark.parametrize("failed_call", [1, 2, 3])
def test_subprocess_failure_does_not_publish_a_unit_or_report_success(installation, capsys, failed_call):
    _, target, runner = installation
    run = runner.side_effect

    def fail(command, *, check):
        if runner.call_count == failed_call:
            raise subprocess.CalledProcessError(1, command)
        return run(command, check=check)

    runner.side_effect = fail
    assert installer.main([]) == 1
    assert runner.call_count == failed_call
    assert not target.exists()
    captured = capsys.readouterr()
    assert "Installation échouée" in captured.err
    assert "Simple-AIOS installé" not in captured.out


def test_main_prints_manual_start_and_cli_commands(installation, capsys):
    _, _, runner = installation
    assert installer.main([]) == 0
    output = capsys.readouterr().out
    assert "systemctl --user daemon-reload" in output
    assert "systemctl --user start simple-aios.service" in output
    assert " -m aios\n" in output
    assert runner.call_count == 3
