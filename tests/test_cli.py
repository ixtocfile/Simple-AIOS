"""Check the installed package's public entry point."""

import subprocess
import sys


def test_module_prints_banner_and_exits(tmp_path):
    result = subprocess.run(
        [sys.executable, "-I", "-m", "aios"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Simple-AIOS\n"
    assert result.stderr == ""
