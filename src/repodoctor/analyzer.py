"""Main repository analysis orchestrator."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from repodoctor import __app_name__, __version__
from repodoctor.checks import (
    check_empty_directories,
    check_generated_files,
    check_gitignore,
    check_large_files,
    check_license,
    check_readme,
)
from repodoctor.config import RepoDoctorConfig
from repodoctor.git_runner import GitRunner, NotAGitRepositoryError
from repodoctor.history import analyze_history
from repodoctor.models import (
    AnalysisReport,
    Finding,
    FindingCategory,
    PassedCheck,
    RepoInfo,
    RepoStatus,
    Severity,
)
from repodoctor.scoring import calculate_health_score
from repodoctor.secret_scanner import scan_for_secrets

logger = logging.getLogger(__name__)


class RepoAnalyzer:
    """Orchestrates comprehensive health inspections for a Git repository."""

    def __init__(
        self,
        git_runner: GitRunner | None = None,
        config: RepoDoctorConfig | None = None,
    ):
        self.git_runner = git_runner or GitRunner()
        self.config = config or RepoDoctorConfig()

    def analyze(self, target_path: Path | str = ".") -> AnalysisReport:
        """Run full health analysis against the specified repository path."""
        start_time = time.perf_counter()

        # Step 1: Detect repository root
        repo_root = self.git_runner.find_repo_root(target_path)
        logger.info("Analyzing repository at '%s'", repo_root)

        # Step 2: Query repository status & metadata
        repo_info: RepoInfo = self.git_runner.get_repo_info(repo_root)
        status: RepoStatus = self.git_runner.get_status(repo_root)
        tracked_files: list[str] = self.git_runner.get_tracked_files(repo_root)

        findings: list[Finding] = []
        passed_checks: list[PassedCheck] = []
        deductions = self.config.deductions

        # Check: Git repository detection
        passed_checks.append(
            PassedCheck(
                id="VALID_GIT_REPO",
                category=FindingCategory.STATUS,
                title="Valid Git repository detected",
                details=f"Top-level root: {repo_root}",
            )
        )

        # Check: Empty repository / commits existence
        if repo_info.is_empty:
            findings.append(
                Finding(
                    id="NO_COMMITS",
                    severity=Severity.HIGH,
                    category=FindingCategory.STATUS,
                    title="Repository has no commits",
                    description="The repository is initialized but contains no commit history.",
                    evidence=[f"Branch: {repo_info.current_branch}"],
                    recommendation="Stage and commit your initial project files using `git commit`.",
                    point_deduction=deductions.no_commits,
                )
            )
        else:
            passed_checks.append(
                PassedCheck(
                    id="COMMITS_EXIST",
                    category=FindingCategory.STATUS,
                    title="Commit history found",
                    details=f"Latest commit: {repo_info.latest_commit_hash[:8]}",
                )
            )

        # Check: Detached HEAD state
        if repo_info.is_detached_head:
            findings.append(
                Finding(
                    id="DETACHED_HEAD",
                    severity=Severity.MEDIUM,
                    category=FindingCategory.STATUS,
                    title="Detached HEAD state detected",
                    description="HEAD is currently detached from any local branch. New commits may become orphaned.",
                    evidence=[f"Current state: {repo_info.current_branch}"],
                    recommendation="Switch to an existing branch (`git switch <branch>`) or create a new branch (`git switch -c <name>`).",
                    point_deduction=deductions.detached_head,
                )
            )
        else:
            passed_checks.append(
                PassedCheck(
                    id="VALID_BRANCH",
                    category=FindingCategory.STATUS,
                    title="Active branch attached",
                    details=f"Branch: {repo_info.current_branch}",
                )
            )

        # Check: Working tree cleanliness
        if status.clean:
            passed_checks.append(
                PassedCheck(
                    id="CLEAN_WORKTREE",
                    category=FindingCategory.STATUS,
                    title="Working tree is clean",
                    details="No uncommitted modifications, deletions, or untracked files.",
                )
            )
        else:
            uncommitted_evidence: list[str] = []
            if status.staged_files:
                uncommitted_evidence.append(f"Staged ({len(status.staged_files)}): {', '.join(status.staged_files[:3])}")
            if status.modified_files:
                uncommitted_evidence.append(f"Modified ({len(status.modified_files)}): {', '.join(status.modified_files[:3])}")
            if status.deleted_files:
                uncommitted_evidence.append(f"Deleted ({len(status.deleted_files)}): {', '.join(status.deleted_files[:3])}")

            if uncommitted_evidence:
                findings.append(
                    Finding(
                        id="UNCOMMITTED_CHANGES",
                        severity=Severity.LOW,
                        category=FindingCategory.STATUS,
                        title="Working tree has uncommitted changes",
                        description="There are modified, staged, or deleted tracked files awaiting commit.",
                        evidence=uncommitted_evidence,
                        recommendation="Commit your changes (`git commit -m ...`) or stash them (`git stash`) before releasing.",
                        point_deduction=deductions.uncommitted_changes,
                    )
                )

            if status.untracked_files:
                sample_untracked = status.untracked_files[:5]
                findings.append(
                    Finding(
                        id="UNTRACKED_FILES",
                        severity=Severity.LOW,
                        category=FindingCategory.STATUS,
                        title="Untracked files present in repository",
                        description=f"Detected {len(status.untracked_files)} untracked file(s) that may need to be tracked or ignored.",
                        evidence=[f"Sample: {', '.join(sample_untracked)}"],
                        recommendation="Add needed files to Git (`git add`) or add ignored patterns to `.gitignore`.",
                        point_deduction=deductions.untracked_files,
                    )
                )

        # Check: README file
        has_readme, readme_name = check_readme(repo_root)
        if has_readme:
            passed_checks.append(
                PassedCheck(
                    id="README_FOUND",
                    category=FindingCategory.DOCUMENTATION,
                    title=f"Documentation found ({readme_name})",
                    details=f"File: {readme_name}",
                )
            )
        else:
            findings.append(
                Finding(
                    id="MISSING_README",
                    severity=Severity.HIGH,
                    category=FindingCategory.DOCUMENTATION,
                    title="Missing README documentation",
                    description="No README, README.md, or README.rst file was found in the repository root.",
                    evidence=["Repository root lacks standard README file"],
                    recommendation="Add a clear README.md explaining project purpose, installation, and usage.",
                    point_deduction=deductions.missing_readme,
                )
            )

        # Check: .gitignore file
        has_gitignore, gitignore_name = check_gitignore(repo_root)
        if has_gitignore:
            passed_checks.append(
                PassedCheck(
                    id="GITIGNORE_FOUND",
                    category=FindingCategory.STRUCTURE,
                    title=".gitignore configuration found",
                    details=f"File: {gitignore_name}",
                )
            )
        else:
            findings.append(
                Finding(
                    id="MISSING_GITIGNORE",
                    severity=Severity.MEDIUM,
                    category=FindingCategory.STRUCTURE,
                    title="Missing .gitignore file",
                    description="No root .gitignore file exists to exclude build artifacts, caches, or virtual environments.",
                    evidence=["No .gitignore in root"],
                    recommendation="Create a .gitignore file tailored to your language and framework.",
                    point_deduction=deductions.missing_gitignore,
                )
            )

        # Check: License file
        has_license, license_name = check_license(repo_root)
        if has_license:
            passed_checks.append(
                PassedCheck(
                    id="LICENSE_FOUND",
                    category=FindingCategory.DOCUMENTATION,
                    title=f"License file detected ({license_name})",
                    details=f"File: {license_name}",
                )
            )
        else:
            findings.append(
                Finding(
                    id="MISSING_LICENSE",
                    severity=Severity.INFO,
                    category=FindingCategory.DOCUMENTATION,
                    title="Missing open-source license file",
                    description="No standard LICENSE, COPYING, or UNLICENSE file found. Others cannot freely use your code without a license.",
                    evidence=["No license file detected in repository root"],
                    recommendation="Add an open-source license file (e.g. MIT, Apache 2.0, or BSD) before publishing.",
                    point_deduction=deductions.missing_license,
                )
            )

        # Check: Large tracked files
        large_files = check_large_files(
            repo_root=repo_root,
            tracked_files=tracked_files,
            threshold_mb=self.config.large_file_mb,
        )
        if large_files:
            evidence = [f"{path} ({size_mb:.1f} MB)" for path, size_mb in large_files[:5]]
            findings.append(
                Finding(
                    id="LARGE_FILES",
                    severity=Severity.HIGH,
                    category=FindingCategory.STRUCTURE,
                    title=f"Large tracked file(s) exceed {self.config.large_file_mb:g}MB threshold",
                    description=f"Found {len(large_files)} tracked file(s) exceeding {self.config.large_file_mb:g} MB. Large files bloat repository clones.",
                    evidence=evidence,
                    recommendation="Consider using Git LFS (Large File Storage) or moving large datasets/binaries out of Git.",
                    point_deduction=deductions.large_files,
                )
            )
        else:
            passed_checks.append(
                PassedCheck(
                    id="NO_LARGE_FILES",
                    category=FindingCategory.STRUCTURE,
                    title="No oversized tracked files",
                    details=f"All files under {self.config.large_file_mb:g} MB threshold.",
                )
            )

        # Check: Accidental generated / temporary files tracked
        generated_files = check_generated_files(tracked_files)
        if generated_files:
            evidence = [f"{path} ({desc})" for path, desc in generated_files[:6]]
            findings.append(
                Finding(
                    id="TRACKED_GENERATED",
                    severity=Severity.MEDIUM,
                    category=FindingCategory.STRUCTURE,
                    title="Generated or temporary files tracked in Git",
                    description=f"Detected {len(generated_files)} file(s) such as bytecode, cache, or logs committed to version control.",
                    evidence=evidence,
                    recommendation="Untrack these files (`git rm --cached <file>`) and add patterns to `.gitignore`.",
                    point_deduction=deductions.tracked_generated,
                )
            )
        else:
            passed_checks.append(
                PassedCheck(
                    id="NO_TRACKED_GENERATED",
                    category=FindingCategory.STRUCTURE,
                    title="No generated/cache files tracked",
                    details="No accidental bytecode, cache, or temporary files committed.",
                )
            )

        # Check: Empty directories
        empty_dirs = check_empty_directories(repo_root, self.config.ignored_dirs)
        if empty_dirs:
            findings.append(
                Finding(
                    id="EMPTY_DIRECTORIES",
                    severity=Severity.LOW,
                    category=FindingCategory.STRUCTURE,
                    title="Empty directories detected in project",
                    description=f"Found {len(empty_dirs)} empty directory(ies). Git will not track empty directories without files.",
                    evidence=empty_dirs[:5],
                    recommendation="Remove unused empty folders or add a `.gitkeep` file inside them if they are required structure.",
                    point_deduction=deductions.empty_directories,
                )
            )

        # Check: Commit history & staleness
        history_summary = None
        if not repo_info.is_empty:
            history_summary = analyze_history(
                repo_root=repo_root,
                git_runner=self.git_runner,
                limit=self.config.commit_history_limit,
                stale_days_threshold=self.config.stale_days_threshold,
            )
            if history_summary.is_stale:
                findings.append(
                    Finding(
                        id="STALE_REPOSITORY",
                        severity=Severity.LOW,
                        category=FindingCategory.HISTORY,
                        title=f"Repository commit activity is stale (> {self.config.stale_days_threshold} days)",
                        description=f"Latest commit was made {history_summary.latest_commit_age_days} days ago.",
                        evidence=[f"Last active: {history_summary.latest_commit_age_days} days ago"],
                        recommendation="Review project status and refresh dependencies or documentation if actively maintained.",
                        point_deduction=deductions.stale_repository,
                    )
                )
            else:
                passed_checks.append(
                    PassedCheck(
                        id="ACTIVE_HISTORY",
                        category=FindingCategory.HISTORY,
                        title="Recent commit activity analyzed",
                        details=f"{history_summary.total_commits} recent commit(s) inspected.",
                    )
                )

        # Check: Secret-pattern warnings (if enabled)
        if self.config.check_secrets:
            secret_matches = scan_for_secrets(
                repo_root=repo_root,
                tracked_files=tracked_files,
                max_file_size_kb=self.config.max_scan_file_size_kb,
                ignored_dirs=self.config.ignored_dirs,
                ignored_patterns=self.config.ignored_patterns,
            )
            if secret_matches:
                evidence = [
                    f"{m.file_path}:{m.line_number} — {m.description} ({m.masked_value})"
                    for m in secret_matches[:5]
                ]
                findings.append(
                    Finding(
                        id="SECRETS_DETECTED",
                        severity=Severity.CRITICAL,
                        category=FindingCategory.SECURITY,
                        title="Potential hardcoded secrets or API keys detected",
                        description=f"Found {len(secret_matches)} potential credential pattern(s) in tracked repository files. Note: these are heuristic matches, not confirmed credentials.",
                        evidence=evidence,
                        recommendation="Immediately rotate compromised credentials, remove them from files, and store secrets in environment variables or a vault.",
                        point_deduction=deductions.secrets_detected,
                    )
                )
            else:
                passed_checks.append(
                    PassedCheck(
                        id="NO_SECRETS_FOUND",
                        category=FindingCategory.SECURITY,
                        title="No exposed secret patterns detected",
                        details="Tracked files scanned for common API key and token patterns.",
                    )
                )

        # Compute transparent health score
        health_score = calculate_health_score(findings, passed_checks)

        # Actionable recommendations compiled from findings
        recommendations: list[str] = []
        for finding in sorted(
            findings,
            key=lambda f: (
                0 if f.severity == Severity.CRITICAL
                else 1 if f.severity == Severity.HIGH
                else 2 if f.severity == Severity.MEDIUM
                else 3 if f.severity == Severity.LOW
                else 4
            ),
        ):
            if finding.recommendation and finding.recommendation not in recommendations:
                recommendations.append(finding.recommendation)

        duration = time.perf_counter() - start_time
        iso_timestamp = datetime.now(timezone.utc).isoformat()

        return AnalysisReport(
            tool_name=__app_name__,
            tool_version=__version__,
            timestamp=iso_timestamp,
            duration_seconds=duration,
            repo_info=repo_info,
            status=status,
            health=health_score,
            passed_checks=passed_checks,
            findings=findings,
            recommendations=recommendations,
            history=history_summary,
        )
