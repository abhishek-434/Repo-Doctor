"""Automated integration tests for CLI commands and exit codes."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repodoctor.cli import main
from repodoctor.models import ExitCode


class TestCLI(unittest.TestCase):
    """Test CLI commands, flags, outputs, and exit codes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)

        # Initialize temporary repository
        subprocess.run(["git", "init"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(self.repo_path), check=True, capture_output=True)

        (self.repo_path / "README.md").write_text("# Project\n", encoding="utf-8")
        (self.repo_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
        (self.repo_path / "LICENSE").write_text("MIT", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=str(self.repo_path), check=True, capture_output=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cli_help(self) -> None:
        """Verify calling main with no args shows help and exits with 0."""
        code = main([])
        self.assertEqual(code, ExitCode.SUCCESS.value)

    def test_cli_analyze_success(self) -> None:
        """Verify 'analyze' command succeeds on valid repository."""
        code = main(["analyze", str(self.repo_path), "--no-color"])
        self.assertEqual(code, ExitCode.SUCCESS.value)

    def test_cli_analyze_json_and_csv_export(self) -> None:
        """Verify JSON and CSV export flags create output files."""
        json_out = self.repo_path / "out.json"
        csv_out = self.repo_path / "out.csv"

        code_json = main(["analyze", str(self.repo_path), "--format", "json", "--output", str(json_out)])
        self.assertEqual(code_json, ExitCode.SUCCESS.value)
        self.assertTrue(json_out.exists())

        code_csv = main(["analyze", str(self.repo_path), "--format", "csv", "--output", str(csv_out)])
        self.assertEqual(code_csv, ExitCode.SUCCESS.value)
        self.assertTrue(csv_out.exists())

    def test_cli_fail_under_threshold(self) -> None:
        """Verify --fail-under exits with 0 when meeting threshold and 1 when failing."""
        # Clean repo should score 100, so fail-under 80 passes
        code_pass = main(["analyze", str(self.repo_path), "--fail-under", "80", "--no-color"])
        self.assertEqual(code_pass, ExitCode.SUCCESS.value)

        # Requiring score of 101 or above cannot be met (max is 100)
        # But fail-under > 100 is rejected with CLI_ERROR
        code_invalid_threshold = main(["analyze", str(self.repo_path), "--fail-under", "105"])
        self.assertEqual(code_invalid_threshold, ExitCode.CLI_ERROR.value)

        # Break health score by creating dirty files and removing README
        (self.repo_path / "README.md").unlink()
        subprocess.run(["git", "rm", "README.md"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "remove readme"], cwd=str(self.repo_path), check=True, capture_output=True)
        (self.repo_path / "untracked.tmp").write_text("untracked", encoding="utf-8")

        # Now score is < 95
        code_fail = main(["analyze", str(self.repo_path), "--fail-under", "95", "--no-color"])
        self.assertEqual(code_fail, ExitCode.SCORE_BELOW_THRESHOLD.value)

    def test_cli_status_subcommand(self) -> None:
        """Verify 'status' subcommand executes successfully."""
        code = main(["status", str(self.repo_path), "--no-color"])
        self.assertEqual(code, ExitCode.SUCCESS.value)

    def test_cli_history_subcommand(self) -> None:
        """Verify 'history' subcommand executes successfully with limit."""
        code = main(["history", str(self.repo_path), "--limit", "10", "--no-color"])
        self.assertEqual(code, ExitCode.SUCCESS.value)

    def test_cli_invalid_git_repository(self) -> None:
        """Verify running against a non-git directory returns ExitCode.GIT_ERROR."""
        with tempfile.TemporaryDirectory() as non_git_dir:
            code = main(["analyze", str(non_git_dir)])
            self.assertEqual(code, ExitCode.GIT_ERROR.value)

    def test_cli_invalid_argument(self) -> None:
        """Verify invalid arguments return ExitCode.CLI_ERROR."""
        code = main(["analyze", str(self.repo_path), "--large-file-mb", "-5"])
        self.assertEqual(code, ExitCode.CLI_ERROR.value)


if __name__ == "__main__":
    unittest.main()
