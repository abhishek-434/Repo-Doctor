"""Commit history analysis and contributor metrics."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from repodoctor.git_runner import GitRunner
from repodoctor.models import CommitInfo, HistorySummary

logger = logging.getLogger(__name__)


def analyze_history(
    repo_root: Path,
    git_runner: GitRunner,
    limit: int | None = 50,
    since: str | None = None,
    stale_days_threshold: int = 180,
) -> HistorySummary:
    """Analyze repository commit history and compute contributor activity metrics."""
    commits: list[CommitInfo] = git_runner.get_commit_log(
        repo_root=repo_root,
        limit=limit,
        since=since,
    )

    if not commits:
        return HistorySummary(
            total_commits=0,
            commits=[],
            contributors={},
            activity_by_date={},
            latest_commit_age_days=None,
            most_active_contributor=None,
            is_stale=False,
        )

    # Contributor counts
    author_counts: Counter[str] = Counter()
    # Activity by date (YYYY-MM-DD)
    date_counts: Counter[str] = Counter()

    for commit in commits:
        author_key = f"{commit.author_name} <{commit.author_email}>"
        author_counts[author_key] += 1

        # Extract YYYY-MM-DD
        if commit.date:
            date_prefix = commit.date[:10]
            date_counts[date_prefix] += 1

    most_active = author_counts.most_common(1)[0] if author_counts else None

    # Calculate age of latest commit
    latest_commit = commits[0]
    now_utc = datetime.now(timezone.utc)
    commit_age_days: int | None = None

    if latest_commit.timestamp > 0:
        commit_dt = datetime.fromtimestamp(latest_commit.timestamp, tz=timezone.utc)
        delta = now_utc - commit_dt
        commit_age_days = max(0, delta.days)

    is_stale = (commit_age_days is not None) and (commit_age_days > stale_days_threshold)

    return HistorySummary(
        total_commits=len(commits),
        commits=commits,
        contributors=dict(author_counts.most_common(15)),
        activity_by_date=dict(sorted(date_counts.items(), reverse=True)[:30]),
        latest_commit_age_days=commit_age_days,
        most_active_contributor=most_active,
        is_stale=is_stale,
    )
