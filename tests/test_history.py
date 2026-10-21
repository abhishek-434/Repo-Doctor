"""Automated unit tests for commit history parsing and contributor metrics."""

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repodoctor.git_runner import GitRunner
from repodoctor.history import analyze_history


class TestHistory(unittest.TestCase):
    """Test commit log parsing and metrics calculation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        self.runner = GitRunner()

        # Initialize repository
        subprocess.run(["git", "init"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Alice Dev"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "alice@example.com"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(self.repo_path), check=True, capture_output=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_empty_repo_history(self) -> None:
        """Verify handling of empty repository without commits."""
        summary = analyze_history(repo_root=self.repo_path, git_runner=self.runner)
        self.assertEqual(summary.total_commits, 0)
        self.assertEqual(len(summary.commits), 0)
        self.assertEqual(len(summary.contributors), 0)
        self.assertFalse(summary.is_stale)
        self.assertIsNone(summary.latest_commit_age_days)

    def test_commit_history_and_contributors(self) -> None:
        """Verify commit parsing, contributor counts, and messages."""
        # Create commit 1 by Alice
        (self.repo_path / "file1.txt").write_text("content 1", encoding="utf-8")
        subprocess.run(["git", "add", "file1.txt"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: add file1"], cwd=str(self.repo_path), check=True, capture_output=True)

        # Create commit 2 by Bob
        (self.repo_path / "file2.txt").write_text("content 2", encoding="utf-8")
        subprocess.run(["git", "config", "user.name", "Bob Contributor"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "bob@example.com"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "add", "file2.txt"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "fix: add file2"], cwd=str(self.repo_path), check=True, capture_output=True)

        summary = analyze_history(repo_root=self.repo_path, git_runner=self.runner)
        self.assertEqual(summary.total_commits, 2)
        self.assertEqual(len(summary.commits), 2)
        self.assertEqual(summary.commits[0].message, "fix: add file2")
        self.assertEqual(summary.commits[1].message, "feat: add file1")

        self.assertIn("Alice Dev <alice@example.com>", summary.contributors)
        self.assertIn("Bob Contributor <bob@example.com>", summary.contributors)
        self.assertEqual(summary.contributors["Alice Dev <alice@example.com>"], 1)
        self.assertEqual(summary.contributors["Bob Contributor <bob@example.com>"], 1)
        self.assertIsNotNone(summary.latest_commit_age_days)

    def test_history_limit(self) -> None:
        """Verify that limit parameter restricts returned commits."""
        for i in range(5):
            f = self.repo_path / f"file_{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            subprocess.run(["git", "add", f.name], cwd=str(self.repo_path), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"commit {i}"], cwd=str(self.repo_path), check=True, capture_output=True)

        summary = analyze_history(repo_root=self.repo_path, git_runner=self.runner, limit=2)
        self.assertEqual(len(summary.commits), 2)

    def test_stale_detection(self) -> None:
        """Verify staleness trigger when threshold is exceeded."""
        (self.repo_path / "old.txt").write_text("old", encoding="utf-8")
        subprocess.run(["git", "add", "old.txt"], cwd=str(self.repo_path), check=True, capture_output=True)
        # Commit with date 200 days ago
        subprocess.run(
            ["git", "commit", "-m", "ancient commit", "--date", "2020-01-01T00:00:00Z"],
            cwd=str(self.repo_path),
            check=True,
            capture_output=True,
        )

        summary = analyze_history(
            repo_root=self.repo_path,
            git_runner=self.runner,
            stale_days_threshold=180,
        )
        self.assertTrue(summary.is_stale)
        self.assertGreater(summary.latest_commit_age_days, 180)


if __name__ == "__main__":
    unittest.main()
