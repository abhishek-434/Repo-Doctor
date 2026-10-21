"""Core data models and data structures for RepoDoctor."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """Finding severity levels."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingCategory(str, Enum):
    """Category classification for repository findings."""
    STATUS = "status"
    STRUCTURE = "structure"
    HISTORY = "history"
    SECURITY = "security"
    DOCUMENTATION = "documentation"


class HealthTier(str, Enum):
    """Health classification score bands."""
    EXCELLENT = "Excellent"
    GOOD = "Good"
    NEEDS_ATTENTION = "Needs Attention"
    POOR = "Poor"

    @classmethod
    def from_score(cls, score: float | int) -> HealthTier:
        """Derive classification from integer health score (0-100)."""
        rounded = round(float(score))
        if rounded >= 90:
            return cls.EXCELLENT
        elif rounded >= 75:
            return cls.GOOD
        elif rounded >= 50:
            return cls.NEEDS_ATTENTION
        else:
            return cls.POOR


class ExitCode(int, Enum):
    """Process exit codes for automation and CI."""
    SUCCESS = 0
    SCORE_BELOW_THRESHOLD = 1
    CLI_ERROR = 2
    GIT_ERROR = 3
    SYSTEM_ERROR = 4


@dataclass(slots=True)
class Finding:
    """Represents a specific issue or recommendation detected in the repository."""
    id: str
    severity: Severity
    category: FindingCategory
    title: str
    description: str
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""
    point_deduction: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert finding to standard dictionary representation."""
        return {
            "id": self.id,
            "severity": self.severity.value,
            "category": self.category.value,
            "title": self.title,
            "description": self.description,
            "evidence": list(self.evidence),
            "recommendation": self.recommendation,
            "point_deduction": round(self.point_deduction, 2),
        }


@dataclass(slots=True)
class PassedCheck:
    """Represents a check that completed successfully without finding issues."""
    id: str
    category: FindingCategory
    title: str
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert passed check to dictionary representation."""
        return {
            "id": self.id,
            "category": self.category.value,
            "title": self.title,
            "details": self.details,
        }


@dataclass(slots=True)
class RepoInfo:
    """High-level repository metadata."""
    name: str
    root_path: str
    current_branch: str
    is_detached_head: bool = False
    latest_commit_hash: str = ""
    latest_commit_date: str = ""
    is_empty: bool = False
    total_tracked_files: int = 0
    repo_size_bytes: int = 0
    git_dir_size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RepoStatus:
    """Working-tree cleanliness and state details."""
    clean: bool
    modified_files: list[str] = field(default_factory=list)
    staged_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    renamed_files: list[str] = field(default_factory=list)
    unmerged_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CommitInfo:
    """Individual commit metadata."""
    hash: str
    short_hash: str
    author_name: str
    author_email: str
    date: str
    timestamp: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HistorySummary:
    """Commit history analytics and contributor metrics."""
    total_commits: int
    commits: list[CommitInfo] = field(default_factory=list)
    contributors: dict[str, int] = field(default_factory=dict)
    activity_by_date: dict[str, int] = field(default_factory=dict)
    latest_commit_age_days: int | None = None
    most_active_contributor: tuple[str, int] | None = None
    is_stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_commits": self.total_commits,
            "commits": [c.to_dict() for c in self.commits],
            "contributors": dict(self.contributors),
            "activity_by_date": dict(self.activity_by_date),
            "latest_commit_age_days": self.latest_commit_age_days,
            "most_active_contributor": (
                {"author": self.most_active_contributor[0], "commits": self.most_active_contributor[1]}
                if self.most_active_contributor else None
            ),
            "is_stale": self.is_stale,
        }


@dataclass(slots=True)
class HealthScore:
    """Calculated repository health score and classification."""
    score: int
    classification: HealthTier
    total_deductions: float
    pass_count: int
    warn_count: int
    error_count: int
    info_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "classification": self.classification.value,
            "total_deductions": round(self.total_deductions, 2),
            "pass_count": self.pass_count,
            "warn_count": self.warn_count,
            "error_count": self.error_count,
            "info_count": self.info_count,
        }


@dataclass(slots=True)
class AnalysisReport:
    """Unified repository health analysis report."""
    tool_name: str
    tool_version: str
    timestamp: str
    duration_seconds: float
    repo_info: RepoInfo
    status: RepoStatus
    health: HealthScore
    passed_checks: list[PassedCheck] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    history: HistorySummary | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert entire report into a serializable dictionary."""
        return {
            "tool": {
                "name": self.tool_name,
                "version": self.tool_version,
            },
            "timestamp": self.timestamp,
            "duration_seconds": round(self.duration_seconds, 3),
            "repository": self.repo_info.to_dict(),
            "status": self.status.to_dict(),
            "health": self.health.to_dict(),
            "summary": {
                "score": self.health.score,
                "classification": self.health.classification.value,
                "passed_checks": self.health.pass_count,
                "warnings": self.health.warn_count,
                "errors": self.health.error_count,
                "info": self.health.info_count,
            },
            "passed_checks": [p.to_dict() for p in self.passed_checks],
            "findings": [f.to_dict() for f in self.findings],
            "recommendations": list(self.recommendations),
            "history": self.history.to_dict() if self.history else None,
        }

    def to_json(self, indent: int = 2) -> str:
        """Export report as formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_csv_rows(self) -> list[dict[str, Any]]:
        """Return findings formatted for tabular CSV export."""
        rows: list[dict[str, Any]] = []
        for finding in self.findings:
            rows.append({
                "repository": self.repo_info.name,
                "finding_id": finding.id,
                "severity": finding.severity.value,
                "category": finding.category.value,
                "title": finding.title,
                "description": finding.description,
                "evidence": "; ".join(finding.evidence) if finding.evidence else "",
                "recommendation": finding.recommendation,
                "point_deduction": finding.point_deduction,
            })
        return rows
