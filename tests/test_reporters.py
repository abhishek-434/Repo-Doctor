"""Automated unit tests for report generation (Terminal, JSON, CSV)."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repodoctor.models import (
    AnalysisReport,
    Finding,
    FindingCategory,
    HealthScore,
    HealthTier,
    PassedCheck,
    RepoInfo,
    RepoStatus,
    Severity,
)
from repodoctor.reporters import (
    CsvReporter,
    FileOverwriteError,
    JsonReporter,
    TerminalReporter,
)


def create_sample_report() -> AnalysisReport:
    """Construct a deterministic sample AnalysisReport for testing."""
    return AnalysisReport(
        tool_name="RepoDoctor",
        tool_version="1.0.0",
        timestamp="2026-10-21T12:00:00Z",
        duration_seconds=0.45,
        repo_info=RepoInfo(
            name="SampleApp",
            root_path="/tmp/SampleApp",
            current_branch="main",
            latest_commit_hash="abcdef1234567890abcdef1234567890abcdef12",
            latest_commit_date="2026-10-20T10:00:00Z",
            is_empty=False,
            total_tracked_files=12,
            repo_size_bytes=50000,
            git_dir_size_bytes=100000,
        ),
        status=RepoStatus(
            clean=False,
            modified_files=["app.py"],
            staged_files=[],
            untracked_files=["notes.txt"],
            deleted_files=[],
            renamed_files=[],
            unmerged_files=[],
        ),
        health=HealthScore(
            score=85,
            classification=HealthTier.GOOD,
            total_deductions=15.0,
            pass_count=5,
            warn_count=2,
            error_count=0,
            info_count=1,
        ),
        passed_checks=[
            PassedCheck(id="P1", category=FindingCategory.STATUS, title="Valid Git repository detected"),
            PassedCheck(id="P2", category=FindingCategory.DOCUMENTATION, title="README found"),
        ],
        findings=[
            Finding(
                id="UNCOMMITTED_CHANGES",
                severity=Severity.LOW,
                category=FindingCategory.STATUS,
                title="Working tree has uncommitted changes",
                description="Modified files exist",
                evidence=["Modified: app.py"],
                recommendation="Commit changes",
                point_deduction=5.0,
            ),
            Finding(
                id="MISSING_GITIGNORE",
                severity=Severity.MEDIUM,
                category=FindingCategory.STRUCTURE,
                title="Missing .gitignore file",
                description="No .gitignore found",
                evidence=["Root directory"],
                recommendation="Create .gitignore",
                point_deduction=8.0,
            ),
        ],
        recommendations=["Commit changes", "Create .gitignore"],
    )


class TestReporters(unittest.TestCase):
    """Test JSON, CSV, and Terminal report generation."""

    def setUp(self) -> None:
        self.report = create_sample_report()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_json_reporter_formatting(self) -> None:
        """Verify JSON export contains all expected keys and valid syntax."""
        json_str = JsonReporter.format(self.report)
        data = json.loads(json_str)

        self.assertEqual(data["tool"]["name"], "RepoDoctor")
        self.assertEqual(data["repository"]["name"], "SampleApp")
        self.assertEqual(data["health"]["score"], 85)
        self.assertEqual(data["health"]["classification"], "Good")
        self.assertEqual(len(data["findings"]), 2)
        self.assertEqual(len(data["passed_checks"]), 2)
        self.assertEqual(len(data["recommendations"]), 2)

    def test_json_file_export_and_overwrite_protection(self) -> None:
        """Verify JSON file writing and safe overwrite protection."""
        target_file = self.temp_path / "report.json"

        # 1. First write succeeds
        JsonReporter.export(self.report, target_file)
        self.assertTrue(target_file.exists())

        # 2. Second write without overwrite flag raises FileOverwriteError
        with self.assertRaises(FileOverwriteError):
            JsonReporter.export(self.report, target_file, overwrite=False)

        # 3. Write with overwrite=True succeeds
        JsonReporter.export(self.report, target_file, overwrite=True)

    def test_csv_reporter_formatting(self) -> None:
        """Verify CSV export contains valid header and rows."""
        csv_str = CsvReporter.format(self.report)
        lines = [line.strip() for line in csv_str.strip().splitlines()]

        self.assertGreaterEqual(len(lines), 3)  # Header + 2 findings
        header = lines[0]
        self.assertIn("finding_id", header)
        self.assertIn("severity", header)
        self.assertIn("point_deduction", header)

        self.assertIn("UNCOMMITTED_CHANGES", lines[1])
        self.assertIn("MISSING_GITIGNORE", lines[2])

    def test_csv_file_export_and_overwrite_protection(self) -> None:
        """Verify CSV file writing and overwrite protection."""
        target_file = self.temp_path / "findings.csv"

        CsvReporter.export(self.report, target_file)
        self.assertTrue(target_file.exists())

        with self.assertRaises(FileOverwriteError):
            CsvReporter.export(self.report, target_file, overwrite=False)

        CsvReporter.export(self.report, target_file, overwrite=True)

    def test_terminal_reporter_ansi(self) -> None:
        """Verify ANSI/plain terminal report renders cleanly to string buffer."""
        buffer = io.StringIO()
        reporter = TerminalReporter(color=False)
        reporter.render_analysis(self.report, file_out=buffer)

        output = buffer.getvalue()
        self.assertIn("RepoDoctor", output)
        self.assertIn("SampleApp", output)
        self.assertIn("85/100", output)
        self.assertIn("[PASS]", output)
        self.assertIn("[WARN]", output)
        self.assertIn("Recommendations:", output)

    def test_terminal_reporter_rich(self) -> None:
        """Verify Rich rendering executes without exceptions."""
        reporter = TerminalReporter(color=True)
        # Calling rich render to ensure no exceptions are raised
        reporter.render_analysis(self.report)


if __name__ == "__main__":
    unittest.main()
