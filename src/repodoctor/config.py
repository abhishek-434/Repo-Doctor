"""Configuration loader and validator for RepoDoctor."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when configuration file contains invalid syntax or values."""


@dataclass(slots=True)
class ScoringDeductions:
    """Configurable point deductions for repository findings."""
    uncommitted_changes: float = 5.0
    untracked_files: float = 3.0
    detached_head: float = 4.0
    missing_readme: float = 12.0
    missing_gitignore: float = 8.0
    missing_license: float = 0.0  # Informational by default
    large_files: float = 10.0
    tracked_generated: float = 8.0
    empty_directories: float = 2.0
    stale_repository: float = 5.0
    secrets_detected: float = 20.0
    no_commits: float = 15.0

    def get(self, key: str, default: float = 0.0) -> float:
        """Safe lookup of deduction by key."""
        return getattr(self, key, default)


@dataclass(slots=True)
class RepoDoctorConfig:
    """Consolidated configuration for analysis execution."""
    large_file_mb: float = 10.0
    commit_history_limit: int = 50
    stale_days_threshold: int = 180
    check_secrets: bool = True
    max_scan_file_size_kb: int = 1024
    ignored_dirs: list[str] = field(
        default_factory=lambda: [
            ".git",
            ".venv",
            "venv",
            "env",
            ".env",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".idea",
            ".vscode",
            "build",
            "dist",
            "htmlcov",
        ]
    )
    ignored_patterns: list[str] = field(
        default_factory=lambda: [
            "*.min.js",
            "*.min.css",
            "*.lock",
            "package-lock.json",
            "poetry.lock",
            "*.map",
        ]
    )
    deductions: ScoringDeductions = field(default_factory=ScoringDeductions)
    default_format: str = "text"
    color: bool = True

    @classmethod
    def load(cls, config_path: Path | str | None = None, repo_root: Path | None = None) -> RepoDoctorConfig:
        """Load configuration from specified path, repository root, or fallback to defaults."""
        target_path: Path | None = None

        if config_path:
            target_path = Path(config_path)
            if not target_path.exists():
                raise ConfigError(f"Specified configuration file does not exist: {target_path}")
        elif repo_root:
            candidate = repo_root / "repodoctor.toml"
            if candidate.exists() and candidate.is_file():
                target_path = candidate
        else:
            local_candidate = Path("repodoctor.toml")
            if local_candidate.exists() and local_candidate.is_file():
                target_path = local_candidate

        if not target_path:
            return cls()

        try:
            with open(target_path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as err:
            raise ConfigError(f"Syntax error in configuration file '{target_path}': {err}") from err
        except OSError as err:
            raise ConfigError(f"Could not read configuration file '{target_path}': {err}") from err

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoDoctorConfig:
        """Construct and validate RepoDoctorConfig from dictionary."""
        config = cls()

        analysis = data.get("analysis", {})
        if not isinstance(analysis, dict):
            raise ConfigError("Invalid [analysis] section: expected a table/dictionary")

        if "large_file_mb" in analysis:
            val = analysis["large_file_mb"]
            if not isinstance(val, (int, float)) or val <= 0:
                raise ConfigError(f"Invalid 'large_file_mb': must be a positive number, got {val}")
            config.large_file_mb = float(val)

        if "commit_history_limit" in analysis:
            val = analysis["commit_history_limit"]
            if not isinstance(val, int) or val < 0:
                raise ConfigError(f"Invalid 'commit_history_limit': must be a non-negative integer, got {val}")
            config.commit_history_limit = val

        if "stale_days_threshold" in analysis:
            val = analysis["stale_days_threshold"]
            if not isinstance(val, int) or val < 0:
                raise ConfigError(f"Invalid 'stale_days_threshold': must be a non-negative integer, got {val}")
            config.stale_days_threshold = val

        if "check_secrets" in analysis:
            val = analysis["check_secrets"]
            if not isinstance(val, bool):
                raise ConfigError(f"Invalid 'check_secrets': must be a boolean, got {val}")
            config.check_secrets = val

        if "max_scan_file_size_kb" in analysis:
            val = analysis["max_scan_file_size_kb"]
            if not isinstance(val, int) or val <= 0:
                raise ConfigError(f"Invalid 'max_scan_file_size_kb': must be a positive integer, got {val}")
            config.max_scan_file_size_kb = val

        exclusions = data.get("exclusions", {})
        if not isinstance(exclusions, dict):
            raise ConfigError("Invalid [exclusions] section: expected a table/dictionary")

        if "ignored_dirs" in exclusions:
            val = exclusions["ignored_dirs"]
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise ConfigError("Invalid 'ignored_dirs': must be a list of directory names/strings")
            config.ignored_dirs = val

        if "ignored_patterns" in exclusions:
            val = exclusions["ignored_patterns"]
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise ConfigError("Invalid 'ignored_patterns': must be a list of pattern strings")
            config.ignored_patterns = val

        # Deductions
        scoring = data.get("scoring", {})
        if isinstance(scoring, dict):
            deductions_dict = scoring.get("deductions", {})
            if not isinstance(deductions_dict, dict):
                raise ConfigError("Invalid [scoring.deductions] section: expected a table/dictionary")

            deductions = ScoringDeductions()
            for key, val in deductions_dict.items():
                if not hasattr(deductions, key):
                    logger.warning("Unknown scoring deduction key '%s' ignored", key)
                    continue
                if not isinstance(val, (int, float)) or val < 0:
                    raise ConfigError(f"Invalid deduction for '{key}': must be non-negative number, got {val}")
                setattr(deductions, key, float(val))
            config.deductions = deductions

        output = data.get("output", {})
        if isinstance(output, dict):
            if "default_format" in output:
                val = str(output["default_format"]).lower()
                if val not in ("text", "json", "csv"):
                    raise ConfigError(f"Invalid 'default_format': must be 'text', 'json', or 'csv', got '{val}'")
                config.default_format = val
            if "color" in output:
                val = output["color"]
                if not isinstance(val, bool):
                    raise ConfigError(f"Invalid 'color': must be a boolean, got {val}")
                config.color = val

        return config
