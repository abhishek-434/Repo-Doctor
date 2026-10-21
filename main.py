#!/usr/bin/env python3
"""RepoDoctor — Git Repository Health Checker.

Main entry point for running the RepoDoctor command-line application directly.
Example:
    python main.py analyze .
    python main.py status .
    python main.py history . --limit 20
"""

import sys
from pathlib import Path

# Add src/ to Python search path so repodoctor can be imported without pip install -e .
SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from repodoctor.cli import main

if __name__ == "__main__":
    sys.exit(main())
