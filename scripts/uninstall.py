#!/usr/bin/env python3
"""Remove the package and generated user unit, preserving configuration and data."""

import argparse
import os
from pathlib import Path
import subprocess
import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]


def uninstall(project_dir: Path) -> None:
    if sys.version_info < (3, 12):
        raise ValueError("Python 3.12 ou ultérieur est requis.")
    if sys.platform != "linux":
        raise ValueError("La désinstallation nécessite Linux.")
    if os.geteuid() == 0:
        raise ValueError("Lancez ce script avec votre compte utilisateur, sans sudo.")

    project_dir = project_dir.resolve()
    venv_dir = project_dir / ".venv"
    python = venv_dir / "bin/python"
    if venv_dir.is_symlink() or (venv_dir.exists() and (
        not (venv_dir / "pyvenv.cfg").is_file() or not python.is_file()
    )):
        raise ValueError("Le chemin .venv existe mais n'est pas un venv utilisable.")

    config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not config_dir.is_absolute():
        raise ValueError("XDG_CONFIG_HOME doit être un chemin absolu.")
    target = config_dir / "systemd/user/simple-aios.service"
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError(f"Unité non reconnue, préservée : {target}")
    has_unit = target.exists()
    if has_unit:
        template = (project_dir / "systemd/simple-aios.service").read_text(encoding="utf-8")
        original = 'ExecStart="%h/Simple-AIOS/.venv/bin/aiosd"'
        if template.count(original) != 1:
            raise ValueError("La commande de l'unité systemd fournie est inattendue.")
        escaped = str(python).replace("%", "%%")
        expected = template.replace(original, f'ExecStart="{escaped}" -m aios.daemon')
        if target.read_text(encoding="utf-8") != expected:
            raise ValueError(f"Unité personnalisée ou liée à un autre dépôt, préservée : {target}")
    overrides = target.with_name(target.name + ".d")
    if overrides.is_symlink() or (overrides.exists() and (
        not overrides.is_dir() or any(overrides.iterdir())
    )):
        raise ValueError(f"Personnalisations systemd présentes, préservées : {overrides}")

    if venv_dir.exists():
        subprocess.run([
            str(python), "-I", "-c",
            "import sys; from pathlib import Path; "
            "sys.exit(0 if sys.version_info >= (3, 12) and sys.prefix != sys.base_prefix "
            "and Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve() else 1)",
            str(venv_dir),
        ], check=True, timeout=30)
    if has_unit:
        for action in ("stop", "disable"):
            subprocess.run([
                "systemctl", "--user", "--no-ask-password", action, target.name,
            ], check=True, timeout=30)
    if venv_dir.exists():
        subprocess.run([
            str(python), "-I", "-m", "pip", "uninstall", "--yes", "simple-aios",
        ], check=True, timeout=30)
    if has_unit:
        # Preserve a unit edited or replaced while subprocesses were running.
        if target.is_symlink() or target.read_text(encoding="utf-8") != expected:
            raise ValueError("L'unité a changé pendant la désinstallation ; elle est préservée.")
        target.unlink()
        subprocess.run([
            "systemctl", "--user", "--no-ask-password", "daemon-reload",
        ], check=True, timeout=30)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        uninstall(PROJECT_DIR)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Désinstallation interrompue : {error}", file=sys.stderr)
        return 1
    print("Simple-AIOS désinstallé. Dépôt, venv, configurations, historique et logs conservés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
