"""Check removal boundaries and failure ordering without touching host services."""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load_script("install")
uninstaller = load_script("uninstall")


@pytest.fixture
def installation(tmp_path, monkeypatch):
    project = tmp_path / "checkout with spaces %h é"
    (project / "systemd").mkdir(parents=True)
    shutil.copyfile(ROOT / "systemd/simple-aios.service", project / "systemd/simple-aios.service")
    user_home = tmp_path / "user"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(uninstaller.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(uninstaller, "PROJECT_DIR", project)
    monkeypatch.chdir(tmp_path)
    installed = project / ".venv/simple-aios.installed"

    def run(command, *, check, timeout=None):
        assert check is True
        if command[1:3] == ["-m", "venv"]:
            venv = Path(command[3])
            (venv / "bin").mkdir(parents=True)
            (venv / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
            (venv / "bin/python").symlink_to(sys.executable)
        elif "install" in command:
            installed.touch()
        elif "uninstall" in command:
            installed.unlink(missing_ok=True)
        return subprocess.CompletedProcess(command, 0)

    runner = Mock(side_effect=run)
    monkeypatch.setattr(uninstaller.subprocess, "run", runner)
    target = installer.install(project)
    runner.reset_mock()
    preserved = [
        project / "source.txt", project / ".venv/other-package.txt",
        user_home / ".config/simple-aios/config.toml",
        user_home / ".local/share/simple-aios/history.sqlite3",
        user_home / ".local/share/simple-aios/logs/simple-aios.log",
    ]
    for path in preserved:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("preserve exactly\n")
    return project, target, installed, preserved, runner


def test_uninstall_stops_and_disables_before_removing_only_its_package_and_unit(installation):
    project, target, installed, preserved, runner = installation
    uninstaller.uninstall(project)
    calls = [call.args[0] for call in runner.call_args_list]
    assert calls[0][:3] == [str(project / ".venv/bin/python"), "-I", "-c"]
    assert calls[0][-1] == str(project / ".venv")
    assert calls[1:] == [
        ["systemctl", "--user", "--no-ask-password", "stop", "simple-aios.service"],
        ["systemctl", "--user", "--no-ask-password", "disable", "simple-aios.service"],
        [str(project / ".venv/bin/python"), "-I", "-m", "pip", "uninstall", "--yes", "simple-aios"],
        ["systemctl", "--user", "--no-ask-password", "daemon-reload"],
    ]
    assert all(call.kwargs == {"check": True, "timeout": 30} for call in runner.call_args_list)
    assert not target.exists() and not installed.exists()
    assert (project / ".venv/bin/python").exists()
    assert all(path.read_text() == "preserve exactly\n" for path in preserved)


def test_repeat_uninstall_is_safe_and_does_not_touch_services(installation):
    project, target, installed, preserved, runner = installation
    uninstaller.uninstall(project)
    runner.reset_mock()
    uninstaller.uninstall(project)
    assert len(runner.call_args_list) == 2  # Validate venv, then pip's idempotent uninstall.
    assert all(call.args[0][0] != "systemctl" for call in runner.call_args_list)
    assert not target.exists() and not installed.exists()
    assert all(path.read_text() == "preserve exactly\n" for path in preserved)


@pytest.mark.parametrize("missing", ["unit", "venv", "both"])
def test_partial_or_absent_installation(installation, missing):
    project, target, installed, _, runner = installation
    if missing in ("unit", "both"):
        target.unlink()
    if missing in ("venv", "both"):
        shutil.rmtree(project / ".venv")
    uninstaller.uninstall(project)
    assert not target.exists() and not installed.exists()
    calls = [call.args[0] for call in runner.call_args_list]
    if missing == "both":
        assert calls == []
    elif missing == "unit":
        assert len(calls) == 2 and all(command[0] != "systemctl" for command in calls)
    else:
        assert len(calls) == 3 and all(command[0] == "systemctl" for command in calls)


def test_uninstall_uses_xdg_config_home(installation, tmp_path, monkeypatch):
    project, original, _, _, _ = installation
    config = tmp_path / "other config"
    target = config / "systemd/user/simple-aios.service"
    target.parent.mkdir(parents=True)
    original.rename(target)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    uninstaller.uninstall(project)
    assert not target.exists()


@pytest.mark.parametrize("kind", ["custom", "other-checkout", "directory", "symlink", "dangling-symlink", "drop-in"])
def test_unrecognized_or_customized_unit_is_preserved_before_any_action(installation, kind):
    project, target, installed, preserved, runner = installation
    if kind == "custom":
        target.write_text(target.read_text() + "# custom\n")
    elif kind == "other-checkout":
        target.write_text(target.read_text().replace("checkout with spaces", "different checkout"))
    elif kind == "drop-in":
        folder = target.with_name(target.name + ".d")
        folder.mkdir()
        (folder / "override.conf").write_text("[Service]\nEnvironment=KEEP=yes\n")
    else:
        target.unlink()
        if kind == "directory":
            target.mkdir()
        else:
            other = project / "other.service"
            if kind == "symlink":
                other.write_text("preserve\n")
            target.symlink_to(other)
    before = target.lstat()
    with pytest.raises(ValueError, match="préserv"):
        uninstaller.uninstall(project)
    runner.assert_not_called()
    assert target.lstat().st_ino == before.st_ino
    assert installed.exists()
    assert all(path.read_text() == "preserve exactly\n" for path in preserved)


@pytest.mark.parametrize("kind", ["root", "python", "platform", "relative-xdg", "invalid-venv", "venv-symlink"])
def test_invalid_prerequisites_prevent_all_actions(installation, monkeypatch, kind):
    project, target, _, _, runner = installation
    if kind == "root":
        monkeypatch.setattr(uninstaller.os, "geteuid", lambda: 0)
    elif kind == "python":
        monkeypatch.setattr(uninstaller.sys, "version_info", (3, 11))
    elif kind == "platform":
        monkeypatch.setattr(uninstaller.sys, "platform", "win32")
    elif kind == "relative-xdg":
        monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
    elif kind == "invalid-venv":
        (project / ".venv/pyvenv.cfg").unlink()
    else:
        saved = project / "saved-venv"
        (project / ".venv").rename(saved)
        (project / ".venv").symlink_to(saved)
    with pytest.raises(ValueError):
        uninstaller.uninstall(project)
    runner.assert_not_called()
    assert target.is_file()


@pytest.mark.parametrize("failed_call", [1, 2, 3, 4, 5])
def test_failure_stops_remaining_actions_and_reports_partial_completion(installation, capsys, failed_call):
    _, target, installed, preserved, runner = installation
    run = runner.side_effect

    def fail(command, **kwargs):
        if runner.call_count == failed_call:
            raise subprocess.CalledProcessError(1, command)
        return run(command, **kwargs)

    runner.side_effect = fail
    assert uninstaller.main([]) == 1
    assert runner.call_count == failed_call
    assert target.exists() == (failed_call < 5)
    assert installed.exists() == (failed_call < 5)
    assert all(path.read_text() == "preserve exactly\n" for path in preserved)
    captured = capsys.readouterr()
    assert "Désinstallation interrompue" in captured.err
    assert "Simple-AIOS désinstallé" not in captured.out


@pytest.mark.parametrize("error", [FileNotFoundError("systemctl"), subprocess.TimeoutExpired("systemctl", 30)])
def test_unavailable_manager_or_timeout_preserves_package_and_unit(installation, error, capsys):
    _, target, installed, _, runner = installation
    run = runner.side_effect

    def fail(command, **kwargs):
        if command[0] == "systemctl":
            raise error
        return run(command, **kwargs)

    runner.side_effect = fail
    assert uninstaller.main([]) == 1
    assert target.is_file() and installed.exists()
    assert "Désinstallation interrompue" in capsys.readouterr().err


def test_concurrent_unit_edit_is_not_deleted(installation):
    project, target, _, _, runner = installation
    run = runner.side_effect

    def edit(command, **kwargs):
        result = run(command, **kwargs)
        if "uninstall" in command:
            target.write_text("new unit contents\n")
        return result

    runner.side_effect = edit
    with pytest.raises(ValueError, match="a changé"):
        uninstaller.uninstall(project)
    assert target.read_text() == "new unit contents\n"
    assert runner.call_count == 4
