"""Secret pattern scanner for identifying accidentally committed sensitive tokens."""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

# Patterns for potential secrets
SECRET_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "AWS_KEY",
        "Potential AWS Access Key ID",
        re.compile(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"),
    ),
    (
        "GITHUB_TOKEN",
        "Potential GitHub Personal Access Token",
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{36,255}|github_pat_[a-zA-Z0-9_]{80,90})\b"),
    ),
    (
        "SLACK_TOKEN",
        "Potential Slack API Token",
        re.compile(r"\bxox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,34}\b"),
    ),
    (
        "STRIPE_KEY",
        "Potential Stripe API Secret Key",
        re.compile(r"\b(sk_live_[0-9a-zA-Z]{24,34}|rk_live_[0-9a-zA-Z]{24,34})\b"),
    ),
    (
        "PRIVATE_KEY",
        "Potential Unencrypted Private Key Header",
        re.compile(r"-----BEGIN (?:RSA|DSA|EC|OPENSSH|PGP)?\s*PRIVATE KEY-----"),
    ),
    (
        "GENERIC_ASSIGNMENT",
        "Potential Hardcoded Secret / API Key Assignment",
        re.compile(
            r"""(?i)\b(api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token|private[_-]?key|client[_-]?secret|db_pass(?:word)?)\b\s*[:=]\s*['"]([A-Za-z0-9_\-\.\$\!\@\#\%\^\&\*]{16,})['"]"""
        ),
    ),
]

# Common benign placeholder values that should not trigger false positives
IGNORE_PLACEHOLDERS = {
    "your_api_key_here",
    "your_secret_key_here",
    "your_token_here",
    "insert_secret_here",
    "placeholder_value",
    "change_this_secret",
    "changeme",
    "my_secret_token",
    "dummy_api_key_12345",
    "xxxxxxxxxxxxxxxxxxxx",
    "00000000000000000000",
}


@dataclass(slots=True)
class SecretMatch:
    """Represents a potential secret pattern detected in a tracked file."""
    pattern_id: str
    description: str
    file_path: str
    line_number: int
    masked_value: str


def mask_secret(value: str) -> str:
    """Mask the middle of a secret value, keeping prefix and suffix for identification."""
    val = value.strip()
    if len(val) <= 8:
        return "********"
    if len(val) <= 16:
        return val[:2] + ("*" * (len(val) - 4)) + val[-2:]
    return val[:4] + ("*" * (len(val) - 8)) + val[-4:]


def is_binary_file(file_path: Path) -> bool:
    """Inspect the first chunk of a file to check for null bytes indicating binary content."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(4096)
            return b"\x00" in chunk
    except OSError:
        return True


def scan_for_secrets(
    repo_root: Path,
    tracked_files: Sequence[str],
    max_file_size_kb: int = 1024,
    ignored_dirs: Sequence[str] = (),
    ignored_patterns: Sequence[str] = (),
) -> list[SecretMatch]:
    """Scan tracked repository files for potential secret patterns.

    Skips binary files, files exceeding max_file_size_kb, and excluded paths.
    Never extracts full secret values in outputs.
    """
    matches: list[SecretMatch] = []
    max_size_bytes = max_file_size_kb * 1024
    ignored_dirs_set = set(ignored_dirs)

    for rel_path in tracked_files:
        norm_rel = rel_path.replace("\\", "/")
        parts = Path(norm_rel).parts

        # Check ignored directories
        if any(part in ignored_dirs_set for part in parts[:-1]):
            continue

        # Check ignored file patterns
        file_name = parts[-1]
        if any(fnmatch.fnmatch(norm_rel, pat) or fnmatch.fnmatch(file_name, pat) for pat in ignored_patterns):
            continue

        abs_path = repo_root / rel_path
        if not abs_path.is_file():
            continue

        # Check file size limit
        try:
            if abs_path.stat().st_size > max_size_bytes:
                continue
        except OSError:
            continue

        # Check binary file
        if is_binary_file(abs_path):
            continue

        # Scan text content line by line
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                for line_idx, line in enumerate(f, start=1):
                    # Short circuit long lines (e.g. minified bundles)
                    if len(line) > 1000:
                        continue

                    for pat_id, desc, pattern in SECRET_PATTERNS:
                        match = pattern.search(line)
                        if not match:
                            continue

                        # Extract secret value to mask
                        if pat_id == "GENERIC_ASSIGNMENT":
                            key_name = match.group(1)
                            raw_val = match.group(2)
                            if raw_val.lower() in IGNORE_PLACEHOLDERS:
                                continue
                            masked = f"{key_name}='{mask_secret(raw_val)}'"
                        else:
                            raw_val = match.group(0)
                            masked = mask_secret(raw_val)

                        matches.append(
                            SecretMatch(
                                pattern_id=pat_id,
                                description=desc,
                                file_path=norm_rel,
                                line_number=line_idx,
                                masked_value=masked,
                            )
                        )
                        # Avoid duplicate pattern triggers on same line
                        break
        except OSError as err:
            logger.debug("Could not read file '%s' for secret scanning: %s", rel_path, err)

    return matches
