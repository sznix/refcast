"""Test that `refcast-mcp` exits cleanly with helpful error when no credentials exist."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_mcp_server_exits_with_help_when_no_creds(tmp_path: Path) -> None:
    """Spawn `refcast-mcp` in a subprocess with NO env vars; expect exit 1 + helpful stderr."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),  # isolate keyring (it'd find nothing)
    }
    # Find the venv's refcast-mcp script
    venv_bin = Path(sys.executable).parent
    script = venv_bin / "refcast-mcp"
    if not script.exists():
        pytest.skip(f"{script} not installed")

    proc = subprocess.run(
        [str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 1
    assert "GEMINI_API_KEY" in proc.stderr
    assert "EXA_API_KEY" in proc.stderr
    assert "refcast auth" in proc.stderr
