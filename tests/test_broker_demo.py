from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "examples" / "flagship-demo" / "broker_demo.py"


def test_broker_demo_all_gates_hold():
    result = subprocess.run(
        [sys.executable, str(DEMO)],
        capture_output=True,
        text=True,
        cwd=DEMO.parents[2],
    )
    assert result.returncode == 0, result.stderr
    assert "All enforcement gates held" in result.stdout
