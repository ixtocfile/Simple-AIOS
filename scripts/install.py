#!/usr/bin/env python3
"""Install Simple-AIOS and its user unit from a local checkout."""

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]


def install(project_dir: Path) -> Path:
    if sys.version_info < (3, 12):
        raise ValueError("Python 3.12 ou ultérieur est requis.")
    if sys.platform != "linux":
        raise ValueError("L'installation nécessite Linux.")
    if os.geteuid() == 0:
        raise ValueError("Lancez ce script avec votre compte utilisateur, sans sudo.")

    project_dir = project_dir.resolve()
    venv_dir = project_dir / ".venv"
    python = venv_dir / "bin/python"
    executable = str(python)
    if any(ord(character) < 32 or ord(character) == 127 or character in "\\\"'$`{}"
           for character in executable):
        raise ValueError("Le chemin du dépôt contient un caractère incompatible avec l'installation.")
    # Quote spaces and escape systemd's percent specifiers.
    escaped = executable.replace("%", "%%")
    template = (project_dir / "systemd/simple-aios.service").read_text(encoding="utf-8")
    original = 'ExecStart="%h/Simple-AIOS/.venv/bin/aiosd"'
    if template.count(original) != 1:
        raise ValueError("La commande de l'unité systemd fournie est inattendue.")
    unit = template.replace(original, f'ExecStart="{escaped}" -m aios.daemon')

    config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not config_dir.is_absolute():
        raise ValueError("XDG_CONFIG_HOME doit être un chemin absolu.")
    target = config_dir / "systemd/user/simple-aios.service"
    if target.is_symlink() or (target.exists() and (
        not target.is_file() or target.read_text(encoding="utf-8") != unit
    )):
        raise ValueError(f"Unité existante différente, préservée : {target}")
    if venv_dir.is_symlink() or (venv_dir.exists() and (
        not (venv_dir / "pyvenv.cfg").is_file() or not python.is_file()
    )):
        raise ValueError("Le chemin .venv existe mais n'est pas un venv utilisable.")

    if not venv_dir.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    subprocess.run([
        str(python), "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 12) "
        "and sys.prefix != sys.base_prefix else 1)",
    ], check=True)
    subprocess.run([str(python), "-m", "pip", "install", str(project_dir)], check=True)

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also refuses a file/symlink created concurrently.
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(unit)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        target = install(PROJECT_DIR)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Installation échouée : {error}", file=sys.stderr)
        return 1
    print(f"Simple-AIOS installé. Unité utilisateur : {target}")
    print("Pour démarrer le daemon :")
    print("  systemctl --user daemon-reload")
    print("  systemctl --user start simple-aios.service")
    print("Pour ouvrir le CLI :")
    print(f"  {shlex.quote(str(PROJECT_DIR / '.venv/bin/python'))} -m aios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
