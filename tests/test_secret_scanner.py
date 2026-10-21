"""Automated unit tests for secret pattern scanner."""

import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repodoctor.secret_scanner import mask_secret, scan_for_secrets


class TestSecretScanner(unittest.TestCase):
    """Test detection of sensitive tokens and safe masking."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_mask_secret(self) -> None:
        """Verify that mask_secret masks intermediate characters."""
        masked_aws = mask_secret("AKIA1234567890EXAMPLE")
        self.assertTrue(masked_aws.startswith("AKIA"))
        self.assertTrue(masked_aws.endswith("MPLE"))
        self.assertIn("****", masked_aws)
        self.assertNotIn("1234567890", masked_aws)

        short_mask = mask_secret("short")
        self.assertEqual(short_mask, "********")

    def test_detect_aws_and_github_token(self) -> None:
        """Verify detection of synthetic AWS and GitHub tokens."""
        # Synthetic credentials for test purposes only
        test_content = (
            "# Config\n"
            "AWS_ACCESS_KEY = AKIAIOSFODNN7EXAMPLE\n"
            "GH_TOKEN = ghp_0123456789abcdef0123456789abcdef0123\n"
        )
        (self.root / "config.py").write_text(test_content, encoding="utf-8")

        matches = scan_for_secrets(
            repo_root=self.root,
            tracked_files=["config.py"],
        )

        match_ids = [m.pattern_id for m in matches]
        self.assertIn("AWS_KEY", match_ids)
        self.assertIn("GITHUB_TOKEN", match_ids)

        for m in matches:
            # Ensure full secret is not present in masked_value
            self.assertNotIn("IOSFODNN7EXAMPLE", m.masked_value)
            self.assertNotIn("0123456789abcdef0123456789abcdef0123", m.masked_value)

    def test_detect_private_key_header(self) -> None:
        """Verify detection of unencrypted private key header."""
        key_content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA..."
        (self.root / "id_rsa").write_text(key_content, encoding="utf-8")

        matches = scan_for_secrets(
            repo_root=self.root,
            tracked_files=["id_rsa"],
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].pattern_id, "PRIVATE_KEY")

    def test_detect_generic_secret_assignment(self) -> None:
        """Verify detection of generic secret assignment."""
        content = "api_key = 'super_secret_token_value_987654321'\n"
        (self.root / "secrets.py").write_text(content, encoding="utf-8")

        matches = scan_for_secrets(
            repo_root=self.root,
            tracked_files=["secrets.py"],
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].pattern_id, "GENERIC_ASSIGNMENT")
        self.assertIn("api_key", matches[0].masked_value)
        self.assertNotIn("super_secret_token_value_987654321", matches[0].masked_value)

    def test_ignore_placeholders(self) -> None:
        """Verify benign placeholders are not flagged."""
        content = "api_key = 'your_api_key_here'\n"
        (self.root / "sample.py").write_text(content, encoding="utf-8")

        matches = scan_for_secrets(
            repo_root=self.root,
            tracked_files=["sample.py"],
        )
        self.assertEqual(len(matches), 0)

    def test_binary_file_skipped(self) -> None:
        """Verify binary files containing null bytes are safely skipped."""
        bin_file = self.root / "app.exe"
        bin_file.write_bytes(b"MZ\x00\x00AKIAIOSFODNN7EXAMPLE\x00")

        matches = scan_for_secrets(
            repo_root=self.root,
            tracked_files=["app.exe"],
        )
        self.assertEqual(len(matches), 0)

    def test_oversized_file_skipped(self) -> None:
        """Verify files exceeding size limit are skipped."""
        large_file = self.root / "large.txt"
        large_file.write_text("AKIAIOSFODNN7EXAMPLE\n" + ("x" * 2000), encoding="utf-8")

        # Threshold set to 1 KB (1024 bytes), file is ~2020 bytes
        matches = scan_for_secrets(
            repo_root=self.root,
            tracked_files=["large.txt"],
            max_file_size_kb=1,
        )
        self.assertEqual(len(matches), 0)

    def test_ignored_directory_and_patterns(self) -> None:
        """Verify files in ignored dirs or matching ignored patterns are skipped."""
        venv_dir = self.root / ".venv"
        venv_dir.mkdir()
        (venv_dir / "dep.py").write_text("AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")

        (self.root / "bundle.min.js").write_text("AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")

        matches = scan_for_secrets(
            repo_root=self.root,
            tracked_files=[".venv/dep.py", "bundle.min.js"],
            ignored_dirs=[".venv"],
            ignored_patterns=["*.min.js"],
        )
        self.assertEqual(len(matches), 0)


if __name__ == "__main__":
    unittest.main()
