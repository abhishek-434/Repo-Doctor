"""RepoDoctor test suite configuration.

Ensures the 'src' directory is in sys.path so tests can be run directly with
`python -m unittest discover -s tests -v` without pre-installation.
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
