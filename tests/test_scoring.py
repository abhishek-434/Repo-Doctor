"""Automated unit tests for health scoring calculations and boundaries."""

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repodoctor.models import (
    Finding,
    FindingCategory,
    HealthTier,
    PassedCheck,
    Severity,
)
from repodoctor.scoring import calculate_health_score


class TestScoring(unittest.TestCase):
    """Test health scoring logic, deduction capping, deduplication, and tier classification."""

    def test_perfect_score(self) -> None:
        """Verify that a repository with no findings achieves a 100/100 score."""
        passed = [
            PassedCheck(id="P1", category=FindingCategory.STATUS, title="Clean"),
            PassedCheck(id="P2", category=FindingCategory.DOCUMENTATION, title="README"),
        ]
        score = calculate_health_score(findings=[], passed_checks=passed)
        self.assertEqual(score.score, 100)
        self.assertEqual(score.classification, HealthTier.EXCELLENT)
        self.assertEqual(score.pass_count, 2)
        self.assertEqual(score.warn_count, 0)
        self.assertEqual(score.error_count, 0)
        self.assertEqual(score.info_count, 0)

    def test_deductions_subtraction(self) -> None:
        """Verify deduction arithmetic."""
        findings = [
            Finding(
                id="F1",
                severity=Severity.HIGH,
                category=FindingCategory.DOCUMENTATION,
                title="Missing README",
                description="desc",
                point_deduction=12.0,
            ),
            Finding(
                id="F2",
                severity=Severity.MEDIUM,
                category=FindingCategory.STRUCTURE,
                title="Missing .gitignore",
                description="desc",
                point_deduction=8.0,
            ),
        ]
        score = calculate_health_score(findings=findings, passed_checks=[])
        self.assertEqual(score.score, 80)
        self.assertEqual(score.classification, HealthTier.GOOD)
        self.assertEqual(score.total_deductions, 20.0)
        self.assertEqual(score.error_count, 1)
        self.assertEqual(score.warn_count, 1)

    def test_score_bounded_at_zero(self) -> None:
        """Verify score never drops below 0 even with excessive deductions."""
        findings = [
            Finding(
                id="F_CRIT",
                severity=Severity.CRITICAL,
                category=FindingCategory.SECURITY,
                title="Secret",
                description="desc",
                point_deduction=80.0,
            ),
            Finding(
                id="F_NO_COMMITS",
                severity=Severity.HIGH,
                category=FindingCategory.STATUS,
                title="No commits",
                description="desc",
                point_deduction=50.0,
            ),
        ]
        score = calculate_health_score(findings=findings, passed_checks=[])
        self.assertEqual(score.score, 0)
        self.assertEqual(score.classification, HealthTier.POOR)
        self.assertEqual(score.total_deductions, 130.0)

    def test_deduplication_by_finding_id(self) -> None:
        """Verify duplicate findings sharing the same ID do not deduct points multiple times."""
        findings = [
            Finding(
                id="LARGE_FILES",
                severity=Severity.HIGH,
                category=FindingCategory.STRUCTURE,
                title="Large file 1",
                description="desc",
                point_deduction=10.0,
            ),
            Finding(
                id="LARGE_FILES",
                severity=Severity.HIGH,
                category=FindingCategory.STRUCTURE,
                title="Large file 2",
                description="desc",
                point_deduction=10.0,
            ),
        ]
        score = calculate_health_score(findings=findings, passed_checks=[])
        # Only 10 points deducted once
        self.assertEqual(score.score, 90)
        self.assertEqual(score.total_deductions, 10.0)

    def test_tier_classifications(self) -> None:
        """Verify score to tier mapping boundaries."""
        self.assertEqual(HealthTier.from_score(100), HealthTier.EXCELLENT)
        self.assertEqual(HealthTier.from_score(90), HealthTier.EXCELLENT)
        self.assertEqual(HealthTier.from_score(89), HealthTier.GOOD)
        self.assertEqual(HealthTier.from_score(75), HealthTier.GOOD)
        self.assertEqual(HealthTier.from_score(74), HealthTier.NEEDS_ATTENTION)
        self.assertEqual(HealthTier.from_score(50), HealthTier.NEEDS_ATTENTION)
        self.assertEqual(HealthTier.from_score(49), HealthTier.POOR)
        self.assertEqual(HealthTier.from_score(0), HealthTier.POOR)


if __name__ == "__main__":
    unittest.main()
