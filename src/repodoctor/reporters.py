"""Report formatters: Terminal (Rich + ANSI fallback), JSON, and CSV."""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from repodoctor import __app_name__, __version__
from repodoctor.models import (
    AnalysisReport,
    Finding,
    FindingCategory,
    HealthTier,
    HistorySummary,
    PassedCheck,
    RepoInfo,
    RepoStatus,
    Severity,
)

# Detect optional rich library
try:
    from rich.box import ROUNDED, SIMPLE
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class FileOverwriteError(Exception):
    """Raised when an output file already exists and overwrite flag was not provided."""


def safe_write_file(target_file: Path | str, content: str, overwrite: bool = False) -> None:
    """Safely write content to target path, preventing accidental overwrites."""
    path = Path(target_file).resolve()
    if path.exists() and not overwrite:
        raise FileOverwriteError(
            f"Output file '{path}' already exists. Use '--overwrite' or '-f' to confirm overwrite."
        )

    # Ensure parent directories exist
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ANSI Color Codes for standard terminal fallback
class ANSI:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_RED = "\033[41m"
    BG_BLUE = "\033[44m"


class TerminalReporter:
    """Renders polished terminal reports with rich styling and ANSI fallback."""

    def __init__(self, color: bool = True):
        self.color = color
        self.rich_console = Console(no_color=not color) if HAS_RICH else None

    def render_analysis(self, report: AnalysisReport, file_out: Any = None) -> None:
        """Render the complete repository analysis dashboard."""
        out = file_out or sys.stdout

        if HAS_RICH and self.color and file_out is None:
            self._render_analysis_rich(report)
        else:
            self._render_analysis_ansi(report, out)

    def _render_analysis_rich(self, report: AnalysisReport) -> None:
        """Render analysis using Rich library."""
        console = self.rich_console or Console()

        # Header panel
        header_text = Text()
        header_text.append(f"{report.tool_name} ", style="bold cyan")
        header_text.append(f"v{report.tool_version}", style="dim")
        header_text.append(" — Git Repository Health Checker\n", style="bold white")
        header_text.append("Professional repository diagnostics & health evaluation\n\n", style="dim italic")

        header_text.append("Repository: ", style="bold blue")
        header_text.append(f"{report.repo_info.name}  ", style="bold white")
        header_text.append(f"({report.repo_info.root_path})\n", style="dim")

        header_text.append("Branch:     ", style="bold blue")
        header_text.append(f"{report.repo_info.current_branch}  ", style="cyan")

        if report.repo_info.latest_commit_hash:
            header_text.append("Latest Commit: ", style="bold blue")
            header_text.append(f"{report.repo_info.latest_commit_hash[:8]}  ", style="yellow")
            if report.repo_info.latest_commit_date:
                header_text.append(f"({report.repo_info.latest_commit_date[:10]})", style="dim")

        console.print(Panel(header_text, border_style="cyan", box=ROUNDED))

        # Health score badge
        score = report.health.score
        tier = report.health.classification.value.upper()
        if score >= 90:
            score_color = "bold green"
            tier_badge = f"[bold white on green] {tier} [/bold white on green]"
        elif score >= 75:
            score_color = "bold green"
            tier_badge = f"[bold black on green] {tier} [/bold black on green]"
        elif score >= 50:
            score_color = "bold yellow"
            tier_badge = f"[bold black on yellow] {tier} [/bold black on yellow]"
        else:
            score_color = "bold red"
            tier_badge = f"[bold white on red] {tier} [/bold white on red]"

        console.print(
            f" [bold white]Repository Health:[/bold white] [{score_color}]{score}/100[/{score_color}] — {tier_badge}\n"
        )

        # Overview Table
        status_table = Table(box=ROUNDED, border_style="blue", show_header=True, header_style="bold cyan")
        status_table.add_column("Check / Metric", style="bold white")
        status_table.add_column("Result / Status", style="cyan")
        status_table.add_column("Category", style="dim")

        # Passed checks in table
        for check in report.passed_checks:
            status_table.add_row(f"[green]✓ PASS[/green]  {check.title}", check.details or "Compliant", check.category.value)

        # Findings in table
        for finding in report.findings:
            if finding.severity == Severity.CRITICAL:
                tag = "[bold red]✖ CRIT[/bold red]"
            elif finding.severity == Severity.HIGH:
                tag = "[bold red]✖ FAIL[/bold red]"
            elif finding.severity in (Severity.MEDIUM, Severity.LOW):
                tag = "[bold yellow]⚠ WARN[/bold yellow]"
            else:
                tag = "[bold blue]ℹ INFO[/bold blue]"

            deduction_str = f"(-{finding.point_deduction:g} pts)" if finding.point_deduction > 0 else ""
            status_table.add_row(
                f"{tag}  {finding.title}",
                f"{finding.description} {deduction_str}".strip(),
                finding.category.value,
            )

        console.print(status_table)

        # Detailed Findings with Evidence (if any warnings/errors)
        actionable_findings = [f for f in report.findings if f.evidence]
        if actionable_findings:
            console.print("\n[bold cyan]Detailed Findings & Evidence:[/bold cyan]")
            for f in actionable_findings:
                if f.severity in (Severity.CRITICAL, Severity.HIGH):
                    icon = "[bold red]●[/bold red]"
                elif f.severity in (Severity.MEDIUM, Severity.LOW):
                    icon = "[bold yellow]●[/bold yellow]"
                else:
                    icon = "[bold blue]●[/bold blue]"

                console.print(f" {icon} [bold]{f.title}[/bold] ({f.severity.value})")
                for ev in f.evidence:
                    console.print(f"    [dim]↳ {ev}[/dim]")

        # Summary box
        summary_panel = Text()
        summary_panel.append("Passed checks: ", style="dim")
        summary_panel.append(f"{report.health.pass_count}\n", style="bold green")
        summary_panel.append("Warnings:      ", style="dim")
        summary_panel.append(f"{report.health.warn_count}\n", style="bold yellow")
        summary_panel.append("Errors:        ", style="dim")
        summary_panel.append(f"{report.health.error_count}\n", style="bold red")
        summary_panel.append("Info notices:  ", style="dim")
        summary_panel.append(f"{report.health.info_count}", style="bold blue")

        console.print(Panel(summary_panel, title="[bold cyan]Analysis Summary[/bold cyan]", border_style="cyan", box=ROUNDED))

        # Recommendations
        if report.recommendations:
            rec_text = Text()
            for idx, rec in enumerate(report.recommendations, start=1):
                rec_text.append(f" {idx}. ", style="bold cyan")
                rec_text.append(f"{rec}\n", style="white")
            console.print(Panel(rec_text, title="[bold green]Actionable Recommendations[/bold green]", border_style="green", box=ROUNDED))
        else:
            console.print("[bold green]✔ No critical recommendations — repository meets all health benchmarks![/bold green]\n")

        # Footer
        console.print(
            f"[dim]Completed in {report.duration_seconds:.2f}s • RepoDoctor heuristic analysis is read-only.[/dim]\n"
        )

    def _render_analysis_ansi(self, report: AnalysisReport, out: Any) -> None:
        """Render analysis using standard ANSI formatting or plain text."""
        c = self.color

        def colorize(text: str, code: str) -> str:
            return f"{code}{text}{ANSI.RESET}" if c else text

        lines: list[str] = []
        lines.append("")
        lines.append(colorize("=" * 72, ANSI.CYAN))
        lines.append(
            colorize(f" {report.tool_name} — Git Repository Health Checker (v{report.tool_version})", ANSI.BOLD + ANSI.CYAN)
        )
        lines.append(colorize("=" * 72, ANSI.CYAN))
        lines.append("")
        lines.append(f" Repository:  {colorize(report.repo_info.name, ANSI.BOLD)} ({report.repo_info.root_path})")
        lines.append(f" Branch:      {colorize(report.repo_info.current_branch, ANSI.CYAN)}")

        if report.repo_info.latest_commit_hash:
            lines.append(
                f" Latest Hash: {colorize(report.repo_info.latest_commit_hash[:8], ANSI.YELLOW)} "
                f"({report.repo_info.latest_commit_date[:10] if report.repo_info.latest_commit_date else ''})"
            )
        lines.append("")

        # Score & Classification
        score = report.health.score
        tier = report.health.classification.value.upper()
        if score >= 75:
            score_str = colorize(f"{score}/100 — {tier}", ANSI.BOLD + ANSI.GREEN)
        elif score >= 50:
            score_str = colorize(f"{score}/100 — {tier}", ANSI.BOLD + ANSI.YELLOW)
        else:
            score_str = colorize(f"{score}/100 — {tier}", ANSI.BOLD + ANSI.RED)

        lines.append(f" Repository Health: {score_str}")
        lines.append("")

        # Diagnostic items list
        lines.append(colorize("-" * 72, ANSI.DIM))
        for check in report.passed_checks:
            tag = colorize("[PASS]", ANSI.BOLD + ANSI.GREEN)
            lines.append(f" {tag} {check.title}")

        for finding in report.findings:
            if finding.severity in (Severity.CRITICAL, Severity.HIGH):
                tag = colorize("[FAIL]", ANSI.BOLD + ANSI.RED)
            elif finding.severity in (Severity.MEDIUM, Severity.LOW):
                tag = colorize("[WARN]", ANSI.BOLD + ANSI.YELLOW)
            else:
                tag = colorize("[INFO]", ANSI.BOLD + ANSI.BLUE)

            deduction = f" (-{finding.point_deduction:g} pts)" if finding.point_deduction > 0 else ""
            lines.append(f" {tag} {finding.title}{deduction}")
            if finding.evidence:
                for ev in finding.evidence:
                    lines.append(f"        ↳ {colorize(ev, ANSI.DIM)}")

        lines.append(colorize("-" * 72, ANSI.DIM))
        lines.append("")

        # Summary
        lines.append(colorize("Summary:", ANSI.BOLD))
        lines.append(f" Passed checks: {report.health.pass_count}")
        lines.append(f" Warnings:      {report.health.warn_count}")
        lines.append(f" Errors:        {report.health.error_count}")
        lines.append(f" Info notices:  {report.health.info_count}")
        lines.append("")

        # Recommendations
        lines.append(colorize("Recommendations:", ANSI.BOLD + ANSI.GREEN))
        if report.recommendations:
            for idx, rec in enumerate(report.recommendations, start=1):
                lines.append(f" {idx}. {rec}")
        else:
            lines.append(" None — Repository is in excellent health!")

        lines.append("")
        lines.append(colorize(f"Analysis completed in {report.duration_seconds:.2f}s (Read-only).", ANSI.DIM))
        lines.append("")

        out.write("\n".join(lines) + "\n")
        out.flush()

    def render_status(self, repo_info: RepoInfo, status: RepoStatus) -> None:
        """Render focused status view for 'repodoctor status' command."""
        if HAS_RICH and self.color:
            console = self.rich_console or Console()
            table = Table(title=f"Git Status: {repo_info.name} ({repo_info.current_branch})", box=ROUNDED)
            table.add_column("Category", style="bold cyan")
            table.add_column("Count", style="bold white", justify="right")
            table.add_column("Files / Details", style="dim")

            table.add_row(
                "Staged Changes",
                str(len(status.staged_files)),
                ", ".join(status.staged_files[:3]) + ("..." if len(status.staged_files) > 3 else ""),
            )
            table.add_row(
                "Modified (Tracked)",
                str(len(status.modified_files)),
                ", ".join(status.modified_files[:3]) + ("..." if len(status.modified_files) > 3 else ""),
            )
            table.add_row(
                "Untracked Files",
                str(len(status.untracked_files)),
                ", ".join(status.untracked_files[:3]) + ("..." if len(status.untracked_files) > 3 else ""),
            )
            table.add_row(
                "Deleted Files",
                str(len(status.deleted_files)),
                ", ".join(status.deleted_files[:3]) + ("..." if len(status.deleted_files) > 3 else ""),
            )

            console.print(table)
            if status.clean:
                console.print("[bold green]✔ Working tree is completely clean.[/bold green]")
            else:
                console.print("[yellow]Working tree contains uncommitted changes.[/yellow]")
        else:
            print(f"Repository: {repo_info.name}")
            print(f"Branch:     {repo_info.current_branch}")
            print(f"Clean:      {'Yes' if status.clean else 'No'}")
            print(f"Staged:     {len(status.staged_files)} file(s)")
            print(f"Modified:   {len(status.modified_files)} file(s)")
            print(f"Untracked:  {len(status.untracked_files)} file(s)")
            print(f"Deleted:    {len(status.deleted_files)} file(s)")

    def render_history(self, repo_info: RepoInfo, history: HistorySummary) -> None:
        """Render commit history summary for 'repodoctor history' command."""
        if HAS_RICH and self.color:
            console = self.rich_console or Console()
            console.print(
                Panel(
                    f"[bold cyan]{repo_info.name}[/bold cyan] — Commit History Summary\n"
                    f"Total inspected commits: [bold green]{history.total_commits}[/bold green] | "
                    f"Latest commit age: [yellow]{history.latest_commit_age_days if history.latest_commit_age_days is not None else 'N/A'} days ago[/yellow]",
                    box=ROUNDED,
                )
            )

            # Contributors table
            contributor_table = Table(title="Top Contributors", box=ROUNDED)
            contributor_table.add_column("Author", style="bold cyan")
            contributor_table.add_column("Commits", justify="right", style="bold green")
            for author, count in history.contributors.items():
                contributor_table.add_row(author, str(count))
            console.print(contributor_table)

            # Recent commits table
            commit_table = Table(title="Recent Commits", box=ROUNDED)
            commit_table.add_column("Hash", style="yellow")
            commit_table.add_column("Date", style="dim")
            commit_table.add_column("Author", style="cyan")
            commit_table.add_column("Subject", style="white")

            for c in history.commits[:15]:
                commit_table.add_row(c.short_hash, c.date[:10] if c.date else "", c.author_name, c.message)
            console.print(commit_table)
        else:
            print(f"Commit History for {repo_info.name}:")
            print(f"Total commits inspected: {history.total_commits}")
            print(f"Latest commit age: {history.latest_commit_age_days} days")
            print("\nTop Contributors:")
            for author, count in history.contributors.items():
                print(f"  {author}: {count} commit(s)")
            print("\nRecent Commits:")
            for c in history.commits[:10]:
                print(f"  [{c.short_hash}] {c.date[:10]} - {c.author_name}: {c.message}")


class JsonReporter:
    """Formats and exports analysis report in JSON format."""

    @staticmethod
    def format(report: AnalysisReport, indent: int = 2) -> str:
        """Convert report to formatted JSON string."""
        return report.to_json(indent=indent)

    @classmethod
    def export(cls, report: AnalysisReport, output_file: Path | str, overwrite: bool = False) -> None:
        """Export JSON report to disk safely."""
        content = cls.format(report)
        safe_write_file(output_file, content, overwrite=overwrite)


class CsvReporter:
    """Formats and exports analysis findings in tabular CSV format."""

    @staticmethod
    def format(report: AnalysisReport) -> str:
        """Convert findings into CSV formatted string."""
        rows = report.to_csv_rows()
        output = io.StringIO()
        fieldnames = [
            "repository",
            "finding_id",
            "severity",
            "category",
            "title",
            "description",
            "evidence",
            "recommendation",
            "point_deduction",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return output.getvalue()

    @classmethod
    def export(cls, report: AnalysisReport, output_file: Path | str, overwrite: bool = False) -> None:
        """Export CSV findings report to disk safely."""
        content = cls.format(report)
        safe_write_file(output_file, content, overwrite=overwrite)
