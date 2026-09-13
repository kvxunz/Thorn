# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = ["fastapi==0.140.13", "ruff==0.16.1"]
# ///
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
for command in (
    [sys.executable, "-m", "unittest", "discover", "-s", "sidecar", "-p", "test_*.py"],
    [sys.executable, "sidecar/service_checks.py"],
    ["ruff", "check", "sidecar", "scripts"],
):
    subprocess.run(command, cwd=root, check=True)
