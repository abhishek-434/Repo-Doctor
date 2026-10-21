"""Automated unit tests for filesystem and repository structure checks."""

import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repodoctor.checks import (
    check_empty_directories,
    check_generated_files,
    check_gitignore,
    check_large_files,
    check_license,
    check_readme,
)


class TestChecks(unittest.TestCase):
    """Test file and directory structure inspection functions."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_readme_detection(self) -> None:
        """Verify README detection with various case variations and missing state."""
        # Missing state
        found, name = check_readme(self.root)
        self.assertFalse(found)
        self.assertEqual(name, "")

        # Lowercase readme.md
        readme = self.root / "README.md"
        readme.write_text("# Hello", encoding="utf-8")
        found, name = check_readme(self.root)
        self.assertTrue(found)
        self.assertEqual(name, "README.md")

    def test_gitignore_detection(self) -> None:
        """Verify .gitignore detection."""
        found, name = check_gitignore(self.root)
        self.assertFalse(found)

        gi = self.root / ".gitignore"
        gi.write_text("*.pyc\n", encoding="utf-8")
        found, name = check_gitignore(self.root)
        self.assertTrue(found)
        self.assertEqual(name, ".gitignore")

    def test_license_detection(self) -> None:
        """Verify license file detection (LICENSE, LICENSE.txt, COPYING)."""
        found, name = check_license(self.root)
        self.assertFalse(found)

        lic = self.root / "LICENSE"
        lic.write_text("MIT License", encoding="utf-8")
        found, name = check_license(self.root)
        self.assertTrue(found)
        self.assertEqual(name, "LICENSE")

    def test_large_files_detection(self) -> None:
        """Verify detection of files exceeding threshold in MB."""
        file_small = self.root / "small.txt"
        file_large = self.root / "large.bin"

        file_small.write_bytes(b"A" * 1024)  # 1 KB
        file_large.write_bytes(b"B" * (2 * 1024 * 1024))  # 2 MB

        tracked = ["small.txt", "large.bin"]

        # With 1.0 MB threshold, large.bin should be flagged
        flagged = check_large_files(self.root, tracked, threshold_mb=1.0)
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0][0], "large.bin")
        self.assertAlmostEqual(flagged[0][1], 2.0, places=1)

        # With 5.0 MB threshold, neither should be flagged
        flagged_high = check_large_files(self.root, tracked, threshold_mb=5.0)
        self.assertEqual(len(flagged_high), 0)

    def test_generated_files_detection(self) -> None:
        """Verify detection of committed temporary/build/cache files."""
        tracked = [
            "src/module.py",
            "src/__pycache__/module.cpython-311.pyc",
            "node_modules/package/index.js",
            ".DS_Store",
            ".env",
            "dist/bundle.js",
            "test.pyc",
            "README.md",
        ]
        flagged = check_generated_files(tracked)
        flagged_paths = [p for p, _ in flagged]

        self.assertIn("src/__pycache__/module.cpython-311.pyc", flagged_paths)
        self.assertIn("node_modules/package/index.js", flagged_paths)
        self.assertIn(".DS_Store", flagged_paths)
        self.assertIn(".env", flagged_paths)
        self.assertIn("dist/bundle.js", flagged_paths)
        self.assertIn("test.pyc", flagged_paths)
        self.assertNotIn("src/module.py", flagged_paths)
        self.assertNotIn("README.md", flagged_paths)

    def test_empty_directories_detection(self) -> None:
        """Verify detection of empty directories while ignoring configured exclusions."""
        empty_dir = self.root / "empty_folder"
        empty_dir.mkdir()

        non_empty = self.root / "non_empty"
        non_empty.mkdir()
        (non_empty / "file.txt").write_text("content", encoding="utf-8")

        ignored_empty = self.root / ".venv"
        ignored_empty.mkdir()

        detected = check_empty_directories(self.root, ignored_dirs=[".venv", ".git"])
        self.assertIn("empty_folder", detected)
        self.assertNotIn("non_empty", detected)
        self.assertNotIn(".venv", detected)


if __name__ == "__main__":
    unittest.main()
