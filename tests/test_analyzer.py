"""Automated integration tests for RepoAnalyzer orchestrator."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repodoctor.analyzer import RepoAnalyzer
from repodoctor.config import RepoDoctorConfig
from repodoctor.git_runner import GitRunner


class TestAnalyzer(unittest.TestCase):
    """Test full analysis orchestration and read-only behavior."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        self.runner = GitRunner()

        # Initialize temporary repository
        subprocess.run(["git", "init"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(self.repo_path), check=True, capture_output=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_clean_compliant_repository(self) -> None:
        """Verify report for a repository with README, .gitignore, LICENSE, and clean worktree."""
        (self.repo_path / "README.md").write_text("# My App\nDocumentation", encoding="utf-8")
        (self.repo_path / ".gitignore").write_text("*.pyc\n.venv/\n", encoding="utf-8")
        (self.repo_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        (self.repo_path / "main.py").write_text("print('hello')\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(self.repo_path), check=True, capture_output=True)

        analyzer = RepoAnalyzer(git_runner=self.runner)
        report = analyzer.analyze(self.repo_path)

        self.assertGreaterEqual(report.health.score, 90)
        self.assertEqual(report.health.warn_count, 0)
        self.assertEqual(report.health.error_count, 0)
        self.assertTrue(any(p.id == "README_FOUND" for p in report.passed_checks))
        self.assertTrue(any(p.id == "GITIGNORE_FOUND" for p in report.passed_checks))
        self.assertTrue(any(p.id == "LICENSE_FOUND" for p in report.passed_checks))
        self.assertTrue(any(p.id == "CLEAN_WORKTREE" for p in report.passed_checks))

    def test_repository_with_issues_detected(self) -> None:
        """Verify detection of missing README, uncommitted changes, and untracked files."""
        # Commit file without README, .gitignore, or LICENSE
        (self.repo_path / "code.py").write_text("a = 1", encoding="utf-8")
        subprocess.run(["git", "add", "code.py"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "code commit"], cwd=str(self.repo_path), check=True, capture_output=True)

        # Modify code.py (uncommitted change) and add untracked file
        (self.repo_path / "code.py").write_text("a = 2", encoding="utf-8")
        (self.repo_path / "untracked.log").write_text("log data", encoding="utf-8")

        analyzer = RepoAnalyzer(git_runner=self.runner)
        report = analyzer.analyze(self.repo_path)

        finding_ids = [f.id for f in report.findings]
        self.assertIn("MISSING_README", finding_ids)
        self.assertIn("MISSING_GITIGNORE", finding_ids)
        self.assertIn("UNCOMMITTED_CHANGES", finding_ids)
        self.assertIn("UNTRACKED_FILES", finding_ids)
        self.assertLess(report.health.score, 80)

    def test_read_only_guarantee(self) -> None:
        """Verify that running analysis never modifies repository state, files, or Git history."""
        (self.repo_path / "README.md").write_text("# Readonly Test", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=str(self.repo_path), check=True, capture_output=True)

        # Record HEAD hash before analysis
        res_before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.repo_path), capture_output=True, text=True)
        head_before = res_before.stdout.strip()

        # Run analysis
        analyzer = RepoAnalyzer(git_runner=self.runner)
        analyzer.analyze(self.repo_path)

        # Verify HEAD hash is identical
        res_after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.repo_path), capture_output=True, text=True)
        head_after = res_after.stdout.strip()
        self.assertEqual(head_before, head_after)


if __name__ == "__main__":
    unittest.main()
