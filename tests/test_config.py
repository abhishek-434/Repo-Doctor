"""Automated unit tests for TOML configuration parsing and validation."""

import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repodoctor.config import ConfigError, RepoDoctorConfig


class TestConfig(unittest.TestCase):
    """Test configuration loading, validation, and defaults."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_default_config(self) -> None:
        """Verify default configuration values."""
        cfg = RepoDoctorConfig()
        self.assertEqual(cfg.large_file_mb, 10.0)
        self.assertEqual(cfg.commit_history_limit, 50)
        self.assertTrue(cfg.check_secrets)
        self.assertIn(".git", cfg.ignored_dirs)
        self.assertEqual(cfg.deductions.missing_readme, 12.0)
        self.assertEqual(cfg.default_format, "text")

    def test_load_valid_toml(self) -> None:
        """Verify loading valid TOML file overrides defaults."""
        toml_content = """
[analysis]
large_file_mb = 25.5
commit_history_limit = 100
check_secrets = false
max_scan_file_size_kb = 2048

[exclusions]
ignored_dirs = [".git", "custom_dir"]
ignored_patterns = ["*.tmp"]

[scoring.deductions]
missing_readme = 20.0
uncommitted_changes = 10.0

[output]
default_format = "json"
color = false
"""
        config_file = self.temp_path / "custom.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        cfg = RepoDoctorConfig.load(config_file)
        self.assertEqual(cfg.large_file_mb, 25.5)
        self.assertEqual(cfg.commit_history_limit, 100)
        self.assertFalse(cfg.check_secrets)
        self.assertEqual(cfg.max_scan_file_size_kb, 2048)
        self.assertEqual(cfg.ignored_dirs, [".git", "custom_dir"])
        self.assertEqual(cfg.ignored_patterns, ["*.tmp"])
        self.assertEqual(cfg.deductions.missing_readme, 20.0)
        self.assertEqual(cfg.deductions.uncommitted_changes, 10.0)
        self.assertEqual(cfg.default_format, "json")
        self.assertFalse(cfg.color)

    def test_missing_file_raises_config_error(self) -> None:
        """Verify non-existent config path raises ConfigError."""
        fake_file = self.temp_path / "does_not_exist.toml"
        with self.assertRaises(ConfigError):
            RepoDoctorConfig.load(fake_file)

    def test_invalid_toml_syntax(self) -> None:
        """Verify malformed TOML raises ConfigError."""
        bad_file = self.temp_path / "bad.toml"
        bad_file.write_text("[analysis\nlarge_file_mb = ", encoding="utf-8")
        with self.assertRaises(ConfigError):
            RepoDoctorConfig.load(bad_file)

    def test_invalid_values_raise_config_error(self) -> None:
        """Verify out-of-range or wrongly-typed values raise ConfigError."""
        # Negative large_file_mb
        with self.assertRaises(ConfigError):
            RepoDoctorConfig.from_dict({"analysis": {"large_file_mb": -1.0}})

        # Non-integer commit_history_limit
        with self.assertRaises(ConfigError):
            RepoDoctorConfig.from_dict({"analysis": {"commit_history_limit": "many"}})

        # Non-boolean check_secrets
        with self.assertRaises(ConfigError):
            RepoDoctorConfig.from_dict({"analysis": {"check_secrets": "yes"}})

        # Negative deduction
        with self.assertRaises(ConfigError):
            RepoDoctorConfig.from_dict({"scoring": {"deductions": {"missing_readme": -5.0}}})

        # Invalid format
        with self.assertRaises(ConfigError):
            RepoDoctorConfig.from_dict({"output": {"default_format": "xml"}})


if __name__ == "__main__":
    unittest.main()
