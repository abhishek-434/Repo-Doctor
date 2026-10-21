"""Command-line interface (CLI) parsing and command execution for RepoDoctor."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from repodoctor import __app_name__, __version__
from repodoctor.analyzer import RepoAnalyzer
from repodoctor.config import ConfigError, RepoDoctorConfig
from repodoctor.git_runner import (
    GitCommandError,
    GitError,
    GitNotFoundError,
    GitRunner,
    NotAGitRepositoryError,
)
from repodoctor.history import analyze_history
from repodoctor.models import ExitCode
from repodoctor.reporters import (
    CsvReporter,
    FileOverwriteError,
    JsonReporter,
    TerminalReporter,
)

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="repodoctor",
        description=f"{__app_name__} — Git Repository Health Checker. "
        "Analyze Git repositories, detect maintenance problems, evaluate health, and generate reports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"{__app_name__} {__version__}",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # analyze subcommand
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Perform comprehensive health inspection of a Git repository",
        description="Inspect repository status, structure, history, and health scoring.",
    )
    analyze_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the Git repository (default: current directory)",
    )
    analyze_parser.add_argument(
        "--format",
        "-F",
        choices=["text", "json", "csv"],
        default="text",
        help="Report output format (default: text)",
    )
    analyze_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file path to save report (e.g. report.json, findings.csv)",
    )
    analyze_parser.add_argument(
        "--overwrite",
        "-f",
        action="store_true",
        help="Overwrite output file if it already exists",
    )
    analyze_parser.add_argument(
        "--large-file-mb",
        type=float,
        default=None,
        help="Custom threshold in Megabytes for detecting large tracked files (e.g. 25)",
    )

    secrets_group = analyze_parser.add_mutually_exclusive_group()
    secrets_group.add_argument(
        "--check-secrets",
        action="store_true",
        default=None,
        help="Enable scanning for potential API keys and secret patterns (default: enabled)",
    )
    secrets_group.add_argument(
        "--no-secrets",
        action="store_true",
        help="Disable secret pattern scanning",
    )

    analyze_parser.add_argument(
        "--fail-under",
        type=int,
        default=None,
        help="Return exit code 1 if health score is below this threshold (0-100)",
    )
    analyze_parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to custom repodoctor.toml configuration file",
    )
    analyze_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color and rich formatting",
    )
    analyze_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed diagnostic logging",
    )

    # status subcommand
    status_parser = subparsers.add_parser(
        "status",
        help="Display working-tree cleanliness and modified/staged files",
        description="Quick inspect of Git working tree status.",
    )
    status_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the Git repository (default: current directory)",
    )
    status_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored formatting",
    )
    status_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed diagnostic logging",
    )

    # history subcommand
    history_parser = subparsers.add_parser(
        "history",
        help="Analyze commit history, top contributors, and activity metrics",
        description="Inspect recent commit activity and contributor statistics.",
    )
    history_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the Git repository (default: current directory)",
    )
    history_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=20,
        help="Maximum number of commits to analyze (default: 20)",
    )
    history_parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Filter commits since date/duration (e.g. '30d', '2w', '2024-01-01')",
    )
    history_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored formatting",
    )
    history_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed diagnostic logging",
    )

    return parser


def handle_analyze(args: argparse.Namespace) -> int:
    """Execute 'analyze' subcommand."""
    # 1. Validate argument values
    if args.fail_under is not None and not (0 <= args.fail_under <= 100):
        sys.stderr.write(f"Error: --fail-under must be an integer between 0 and 100, got {args.fail_under}\n")
        return ExitCode.CLI_ERROR.value

    if args.large_file_mb is not None and args.large_file_mb <= 0:
        sys.stderr.write(f"Error: --large-file-mb must be a positive number, got {args.large_file_mb}\n")
        return ExitCode.CLI_ERROR.value

    # 2. Initialize Git runner and verify availability
    git_runner = GitRunner()
    try:
        git_runner.ensure_git_available()
    except GitNotFoundError as err:
        sys.stderr.write(f"Error: {err}\n")
        return ExitCode.GIT_ERROR.value

    target_path = Path(args.path)
    if not target_path.exists():
        sys.stderr.write(f"Error: Target path does not exist: '{args.path}'\n")
        return ExitCode.GIT_ERROR.value

    # 3. Load configuration
    try:
        repo_root = git_runner.find_repo_root(target_path)
    except NotAGitRepositoryError as err:
        sys.stderr.write(f"Error: {err}\n")
        return ExitCode.GIT_ERROR.value

    try:
        config = RepoDoctorConfig.load(config_path=args.config, repo_root=repo_root)
    except ConfigError as err:
        sys.stderr.write(f"Configuration Error: {err}\n")
        return ExitCode.CLI_ERROR.value

    # Apply CLI overrides to config
    if args.large_file_mb is not None:
        config.large_file_mb = args.large_file_mb
    if args.no_secrets:
        config.check_secrets = False
    elif args.check_secrets is True:
        config.check_secrets = True

    # 4. Run Analysis
    analyzer = RepoAnalyzer(git_runner=git_runner, config=config)
    try:
        report = analyzer.analyze(repo_root)
    except GitError as err:
        sys.stderr.write(f"Git Execution Error: {err}\n")
        return ExitCode.GIT_ERROR.value
    except Exception as err:
        logger.exception("Unexpected error during analysis")
        sys.stderr.write(f"System Error: {err}\n")
        return ExitCode.SYSTEM_ERROR.value

    # 5. Output Report
    use_color = not args.no_color and config.color
    terminal_reporter = TerminalReporter(color=use_color)

    # Format handling
    fmt = args.format.lower()
    if fmt == "json":
        json_content = JsonReporter.format(report)
        if args.output:
            try:
                JsonReporter.export(report, args.output, overwrite=args.overwrite)
                print(f"JSON analysis report saved to: {args.output}")
            except FileOverwriteError as err:
                sys.stderr.write(f"Error: {err}\n")
                return ExitCode.CLI_ERROR.value
        else:
            print(json_content)
    elif fmt == "csv":
        csv_content = CsvReporter.format(report)
        if args.output:
            try:
                CsvReporter.export(report, args.output, overwrite=args.overwrite)
                print(f"CSV findings report saved to: {args.output}")
            except FileOverwriteError as err:
                sys.stderr.write(f"Error: {err}\n")
                return ExitCode.CLI_ERROR.value
        else:
            print(csv_content)
    else:
        # text / terminal dashboard
        terminal_reporter.render_analysis(report)
        if args.output:
            # Save plain text report to file
            try:
                with open(args.output, "w" if args.overwrite else "x", encoding="utf-8") as f:
                    # Write plain ANSI-stripped or ANSI text
                    plain_reporter = TerminalReporter(color=False)
                    plain_reporter.render_analysis(report, file_out=f)
                print(f"Text report saved to: {args.output}")
            except FileExistsError:
                sys.stderr.write(
                    f"Error: Output file '{args.output}' already exists. Use '--overwrite' to overwrite.\n"
                )
                return ExitCode.CLI_ERROR.value

    # 6. Check --fail-under threshold
    if args.fail_under is not None:
        if report.health.score < args.fail_under:
            sys.stderr.write(
                f"\nCI Check Failed: Repository health score ({report.health.score}) "
                f"is below required threshold ({args.fail_under}).\n"
            )
            return ExitCode.SCORE_BELOW_THRESHOLD.value

    return ExitCode.SUCCESS.value


def handle_status(args: argparse.Namespace) -> int:
    """Execute 'status' subcommand."""
    git_runner = GitRunner()
    try:
        git_runner.ensure_git_available()
        repo_root = git_runner.find_repo_root(args.path)
        repo_info = git_runner.get_repo_info(repo_root)
        status = git_runner.get_status(repo_root)
    except GitError as err:
        sys.stderr.write(f"Error: {err}\n")
        return ExitCode.GIT_ERROR.value

    reporter = TerminalReporter(color=not args.no_color)
    reporter.render_status(repo_info, status)
    return ExitCode.SUCCESS.value


def handle_history(args: argparse.Namespace) -> int:
    """Execute 'history' subcommand."""
    if args.limit <= 0:
        sys.stderr.write(f"Error: --limit must be positive integer, got {args.limit}\n")
        return ExitCode.CLI_ERROR.value

    git_runner = GitRunner()
    try:
        git_runner.ensure_git_available()
        repo_root = git_runner.find_repo_root(args.path)
        repo_info = git_runner.get_repo_info(repo_root)
    except GitError as err:
        sys.stderr.write(f"Error: {err}\n")
        return ExitCode.GIT_ERROR.value

    history = analyze_history(
        repo_root=repo_root,
        git_runner=git_runner,
        limit=args.limit,
        since=args.since,
    )

    reporter = TerminalReporter(color=not args.no_color)
    reporter.render_history(repo_info, history)
    return ExitCode.SUCCESS.value


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint."""
    # Ensure UTF-8 output encoding on Windows consoles
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    if not args.subcommand:
        parser.print_help()
        return ExitCode.SUCCESS.value

    if args.subcommand == "analyze":
        return handle_analyze(args)
    elif args.subcommand == "status":
        return handle_status(args)
    elif args.subcommand == "history":
        return handle_history(args)

    return ExitCode.SUCCESS.value


if __name__ == "__main__":
    sys.exit(main())
