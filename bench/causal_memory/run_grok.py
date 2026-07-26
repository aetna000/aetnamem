"""Compatibility entry point for the registered paid training stage."""

from __future__ import annotations

import sys

from aetnamem.cli import main


if __name__ == "__main__":
    sys.argv[1:1] = ["impact", "run", "--stage", "grok-train"]
    main()
