"""Health scoring engine and finding aggregation for RepoDoctor."""

from __future__ import annotations

import logging
from typing import Sequence

from repodoctor.config import ScoringDeductions
from repodoctor.models import (
    Finding,
    HealthScore,
    HealthTier,
    PassedCheck,
    Severity,
)

logger = logging.getLogger(__name__)


def calculate_health_score(
    findings: Sequence[Finding],
    passed_checks: Sequence[PassedCheck],
) -> HealthScore:
    """Calculate transparent health score from findings and passed checks.

    Starting score is 100. Deductions are subtracted down to a minimum of 0.
    Duplicate finding IDs only deduct points once.
    """
    applied_deductions = 0.0
    deducted_ids: set[str] = set()

    pass_count = len(passed_checks)
    warn_count = 0
    error_count = 0
    info_count = 0

    for finding in findings:
        if finding.severity in (Severity.CRITICAL, Severity.HIGH):
            error_count += 1
        elif finding.severity in (Severity.MEDIUM, Severity.LOW):
            warn_count += 1
        elif finding.severity == Severity.INFO:
            info_count += 1

        # Prevent duplicate deductions for findings sharing the same rule ID
        if finding.id not in deducted_ids:
            deducted_ids.add(finding.id)
            applied_deductions += max(0.0, finding.point_deduction)

    raw_score = 100.0 - applied_deductions
    final_score = max(0, min(100, round(raw_score)))
    classification = HealthTier.from_score(final_score)

    return HealthScore(
        score=final_score,
        classification=classification,
        total_deductions=applied_deductions,
        pass_count=pass_count,
        warn_count=warn_count,
        error_count=error_count,
        info_count=info_count,
    )
