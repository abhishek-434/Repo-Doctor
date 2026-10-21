"""Filesystem and repository structure inspections."""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

# Common README variants
README_NAMES = ("readme.md", "readme", "readme.rst", "readme.txt", "readme.markdown")

# Common License variants
LICENSE_NAMES = ("license", "license.md", "license.txt", "copying", "copying.txt", "unlicense")

# Patterns for generated/temporary files that should generally not be tracked
GENERATED_FILE_PATTERNS = [
    # Python
    ("**/__pycache__/**", "Python bytecode cache directory"),
    ("*__pycache__*", "Python bytecode cache"),
    ("*.pyc", "Compiled Python bytecode file"),
    ("*.pyo", "Optimized Python bytecode file"),
    ("*.pyd", "Python compiled module"),
    (".pytest_cache/**", "Pytest test runner cache"),
    (".coverage", "Python test coverage data file"),
    (".coverage.*", "Python test coverage data file"),
    ("coverage.xml", "Test coverage XML report"),
    ("htmlcov/**", "Coverage HTML report directory"),
    (".tox/**", "Tox automation cache"),
    (".nox/**", "Nox automation cache"),
    # OS files
    (".DS_Store", "macOS desktop services store"),
    ("Thumbs.db", "Windows thumbnail database"),
    ("desktop.ini", "Windows folder desktop configuration"),
    # Node / Web
    ("node_modules/**", "Node.js dependencies directory"),
    # Environment & Local secrets
    (".env", "Environment variable secret file"),
    (".env.local", "Local environment variable file"),
    # Build & Distribution
    ("dist/**", "Build distribution directory"),
    ("build/**", "Compilation build directory"),
    ("*.egg-info/**", "Python egg metadata directory"),
    ("*.class", "Java/JVM compiled bytecode"),
    ("*.o", "Compiled C/C++ object file"),
    ("*.so", "Compiled shared library file"),
    ("*.dylib", "macOS dynamic library file"),
]


def check_readme(repo_root: Path) -> tuple[bool, str]:
    """Check if repository contains a recognizable README file in root directory.

    Returns (found, matched_filename).
    """
    for entry in repo_root.iterdir():
        if entry.is_file() and entry.name.lower() in README_NAMES:
            return True, entry.name
    return False, ""


def check_gitignore(repo_root: Path) -> tuple[bool, str]:
    """Check if repository contains a .gitignore file in root directory.

    Returns (found, filename).
    """
    gi = repo_root / ".gitignore"
    if gi.exists() and gi.is_file():
        return True, ".gitignore"
    return False, ""


def check_license(repo_root: Path) -> tuple[bool, str]:
    """Check if repository contains an open-source license file in root directory.

    Returns (found, matched_filename).
    """
    for entry in repo_root.iterdir():
        if entry.is_file() and entry.name.lower() in LICENSE_NAMES:
            return True, entry.name
    return False, ""


def check_large_files(
    repo_root: Path,
    tracked_files: Sequence[str],
    threshold_mb: float = 10.0,
) -> list[tuple[str, float]]:
    """Inspect tracked files and identify any exceeding the threshold size in MB.

    Returns a list of (relative_path, size_mb).
    """
    threshold_bytes = threshold_mb * 1024 * 1024
    large_files: list[tuple[str, float]] = []

    for rel_path in tracked_files:
        abs_path = repo_root / rel_path
        try:
            if abs_path.is_file():
                size = abs_path.stat().st_size
                if size > threshold_bytes:
                    size_mb = round(size / (1024 * 1024), 2)
                    large_files.append((rel_path, size_mb))
        except OSError as err:
            logger.debug("Could not inspect file size for '%s': %s", rel_path, err)

    # Sort descending by file size
    large_files.sort(key=lambda x: x[1], reverse=True)
    return large_files


def check_generated_files(
    tracked_files: Sequence[str],
) -> list[tuple[str, str]]:
    """Detect common generated, cached, or transient files that are tracked in Git.

    Returns list of (relative_path, description).
    """
    detected: list[tuple[str, str]] = []
    seen: set[str] = set()

    for rel_path in tracked_files:
        norm_path = rel_path.replace("\\", "/")
        for pattern, desc in GENERATED_FILE_PATTERNS:
            if fnmatch.fnmatch(norm_path, pattern) or fnmatch.fnmatch(os.path.basename(norm_path), pattern):
                if norm_path not in seen:
                    seen.add(norm_path)
                    detected.append((rel_path, desc))
                break

    return detected


def check_empty_directories(
    repo_root: Path,
    ignored_dirs: Sequence[str],
) -> list[str]:
    """Identify project directories that are empty or contain no non-ignored files.

    Git does not track empty directories natively. Empty directories might be
    unintended leftovers or missing required `.gitkeep` files.
    """
    empty_dirs: list[str] = []
    ignored_set = set(ignored_dirs)

    for root, dirs, files in os.walk(repo_root):
        rel_root = os.path.relpath(root, repo_root)
        if rel_root == ".":
            # Don't consider the root itself
            # Filter in-place to avoid descending into ignored directories
            dirs[:] = [d for d in dirs if d not in ignored_set and not d.startswith(".git")]
            continue

        # Check if current directory or any ancestor is ignored
        parts = Path(rel_root).parts
        if any(part in ignored_set or part == ".git" for part in parts):
            dirs[:] = []
            continue

        # Prune ignored child dirs
        dirs[:] = [d for d in dirs if d not in ignored_set and not d.startswith(".git")]

        # If directory has neither subdirectories nor files, it is empty
        if not dirs and not files:
            empty_dirs.append(rel_root.replace("\\", "/"))

    return sorted(empty_dirs)
