"""Safe subprocess wrapper for executing read-only Git commands."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from repodoctor.models import CommitInfo, RepoInfo, RepoStatus

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Base exception for Git operations."""


class GitNotFoundError(GitError):
    """Raised when the git executable is not available on PATH."""


class NotAGitRepositoryError(GitError):
    """Raised when the target directory is not a Git repository."""


class GitCommandError(GitError):
    """Raised when a git command exits with a nonzero status code."""

    def __init__(self, cmd: Sequence[str], returncode: int, stderr: str):
        self.cmd = list(cmd)
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"Git command failed [{returncode}]: {' '.join(cmd)}\n{self.stderr}")


class GitRunner:
    """Executes safe, read-only Git commands using subprocess."""

    DEFAULT_TIMEOUT_SECONDS: int = 15

    def __init__(self, git_path: str | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self._git_binary = git_path or shutil.which("git")
        self.timeout = timeout
        if not self._git_binary:
            logger.warning("Git executable not found in system PATH.")

    @property
    def is_git_available(self) -> bool:
        """Check whether git executable exists and can be executed."""
        if not self._git_binary:
            return False
        try:
            res = subprocess.run(
                [self._git_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
            return res.returncode == 0
        except Exception:
            return False

    def ensure_git_available(self) -> None:
        """Raise GitNotFoundError if git is not accessible."""
        if not self.is_git_available:
            raise GitNotFoundError(
                "Git executable could not be found or executed. "
                "Please verify that Git is installed and available in your system PATH."
            )

    def run(
        self,
        args: Sequence[str],
        cwd: Path | str,
        timeout: int | None = None,
        check: bool = True,
    ) -> tuple[int, str, str]:
        """Run a Git command safely with list arguments and shell=False.

        Returns (returncode, stdout, stderr).
        """
        self.ensure_git_available()
        assert self._git_binary is not None

        cmd = [self._git_binary, *args]
        working_dir = Path(cwd).resolve()

        if not working_dir.exists() or not working_dir.is_dir():
            raise NotAGitRepositoryError(f"Directory does not exist or is not a directory: {working_dir}")

        effective_timeout = timeout or self.timeout
        logger.debug("Executing Git command: %s (cwd=%s)", cmd, working_dir)

        try:
            # We enforce GIT_TERMINAL_PROMPT=0 and LC_ALL=C to prevent interactive prompts and ensure deterministic output
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["LC_ALL"] = "C.UTF-8"

            result = subprocess.run(
                cmd,
                cwd=str(working_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
                shell=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            logger.error("Git command timed out after %s seconds: %s", effective_timeout, cmd)
            raise GitCommandError(cmd, 124, f"Command timed out after {effective_timeout}s") from exc
        except FileNotFoundError as exc:
            raise GitNotFoundError("Git binary not found during command execution") from exc

        if check and result.returncode != 0:
            raise GitCommandError(cmd, result.returncode, result.stderr)

        return result.returncode, result.stdout, result.stderr

    def find_repo_root(self, path: Path | str) -> Path:
        """Resolve the top-level repository root directory.

        Raises NotAGitRepositoryError if target is not inside a Git worktree.
        """
        target = Path(path).resolve()
        if not target.exists():
            raise NotAGitRepositoryError(f"Specified path does not exist: {target}")

        # If a file was passed, use its parent directory
        inspect_dir = target if target.is_dir() else target.parent

        code, out, err = self.run(
            ["rev-parse", "--show-toplevel"],
            cwd=inspect_dir,
            check=False,
        )
        if code != 0 or not out.strip():
            raise NotAGitRepositoryError(f"Path is not inside a valid Git repository: {target}")

        return Path(out.strip()).resolve()

    def is_inside_work_tree(self, path: Path | str) -> bool:
        """Determine whether the specified path is inside a Git work tree."""
        try:
            code, out, _ = self.run(
                ["rev-parse", "--is-inside-work-tree"],
                cwd=path if Path(path).is_dir() else Path(path).parent,
                check=False,
            )
            return code == 0 and out.strip() == "true"
        except Exception:
            return False

    def get_repo_info(self, repo_root: Path) -> RepoInfo:
        """Collect basic repository metadata (branch, commit, empty status, sizes)."""
        repo_name = repo_root.name

        # Check current branch
        code, branch_out, _ = self.run(
            ["branch", "--show-current"],
            cwd=repo_root,
            check=False,
        )
        current_branch = branch_out.strip()
        is_detached = False

        if not current_branch:
            # Check if HEAD is detached
            code_detach, head_desc, _ = self.run(
                ["describe", "--tags", "--always", "HEAD"],
                cwd=repo_root,
                check=False,
            )
            if code_detach == 0 and head_desc.strip():
                current_branch = f"HEAD (detached at {head_desc.strip()})"
                is_detached = True
            else:
                current_branch = "HEAD (detached)"
                is_detached = True

        # Check if repository has commits
        code_rev, latest_hash, _ = self.run(
            ["rev-parse", "HEAD"],
            cwd=repo_root,
            check=False,
        )
        is_empty = code_rev != 0
        latest_commit_hash = latest_hash.strip() if not is_empty else ""
        latest_commit_date = ""

        if not is_empty:
            code_date, commit_date, _ = self.run(
                ["log", "-1", "--format=%cd", "--date=iso"],
                cwd=repo_root,
                check=False,
            )
            if code_date == 0:
                latest_commit_date = commit_date.strip()

        # Tracked files count
        code_files, tracked_out, _ = self.run(
            ["ls-files"],
            cwd=repo_root,
            check=False,
        )
        tracked_files = [line.strip() for line in tracked_out.splitlines() if line.strip()] if code_files == 0 else []

        # Calculate approximate repo and .git sizes safely without scanning unnecessary files
        git_dir = repo_root / ".git"
        git_dir_size = 0
        repo_size = 0

        if git_dir.exists():
            try:
                for root, _, files in os.walk(git_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            git_dir_size += os.path.getsize(fp)
                        except OSError:
                            pass
            except OSError:
                pass

        # Calculate size of tracked files
        for rel_file in tracked_files:
            try:
                abs_file = repo_root / rel_file
                if abs_file.exists() and abs_file.is_file():
                    repo_size += abs_file.stat().st_size
            except OSError:
                pass

        return RepoInfo(
            name=repo_name,
            root_path=str(repo_root),
            current_branch=current_branch if not is_empty else (current_branch or "initial"),
            is_detached_head=is_detached,
            latest_commit_hash=latest_commit_hash,
            latest_commit_date=latest_commit_date,
            is_empty=is_empty,
            total_tracked_files=len(tracked_files),
            repo_size_bytes=repo_size,
            git_dir_size_bytes=git_dir_size,
        )

    def get_status(self, repo_root: Path) -> RepoStatus:
        """Inspect working tree status using porcelain v1 output."""
        code, out, _ = self.run(
            ["status", "--porcelain=v1", "-uall"],
            cwd=repo_root,
            check=False,
        )

        modified: list[str] = []
        staged: list[str] = []
        untracked: list[str] = []
        deleted: list[str] = []
        renamed: list[str] = []
        unmerged: list[str] = []

        if code != 0 or not out.strip():
            return RepoStatus(
                clean=True,
                modified_files=modified,
                staged_files=staged,
                untracked_files=untracked,
                deleted_files=deleted,
                renamed_files=renamed,
                unmerged_files=unmerged,
            )

        for line in out.splitlines():
            if len(line) < 3:
                continue

            x = line[0]
            y = line[1]
            # Filename starts after 3rd character. If quoted, strip quotes and unescape.
            filepath = line[3:].strip()
            if filepath.startswith('"') and filepath.endswith('"'):
                try:
                    filepath = filepath[1:-1].encode("utf-8").decode("unicode_escape")
                except Exception:
                    filepath = filepath[1:-1]

            # Handle rename format "old -> new"
            if " -> " in filepath:
                filepath = filepath.split(" -> ")[-1].strip()

            # Status codes in porcelain format:
            # X: index status, Y: working tree status
            # '??' = untracked
            # '!!' = ignored
            # 'DD', 'AU', 'UD', 'UA', 'DU', 'AA', 'UU' = unmerged
            if x == "?" and y == "?":
                untracked.append(filepath)
            elif x in ("U",) or y in ("U",) or (x == "A" and y == "A") or (x == "D" and y == "D"):
                unmerged.append(filepath)
            else:
                # Staged changes (X is not space or '?')
                if x in ("M", "A", "C"):
                    staged.append(filepath)
                elif x == "R":
                    renamed.append(filepath)
                elif x == "D":
                    deleted.append(filepath)

                # Working tree changes (Y is not space or '?')
                if y == "M":
                    if filepath not in modified:
                        modified.append(filepath)
                elif y == "D":
                    if filepath not in deleted:
                        deleted.append(filepath)

        clean = not (modified or staged or untracked or deleted or renamed or unmerged)

        return RepoStatus(
            clean=clean,
            modified_files=modified,
            staged_files=staged,
            untracked_files=untracked,
            deleted_files=deleted,
            renamed_files=renamed,
            unmerged_files=unmerged,
        )

    def get_tracked_files(self, repo_root: Path) -> list[str]:
        """Get list of all tracked relative file paths in repository."""
        code, out, _ = self.run(["ls-files"], cwd=repo_root, check=False)
        if code != 0 or not out.strip():
            return []

        files: list[str] = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('"') and line.endswith('"'):
                try:
                    line = line[1:-1].encode("utf-8").decode("unicode_escape")
                except Exception:
                    line = line[1:-1]
            files.append(line)
        return files

    def get_commit_log(
        self,
        repo_root: Path,
        limit: int | None = 50,
        since: str | None = None,
    ) -> list[CommitInfo]:
        """Fetch commit history with machine-readable separator format.

        Format: %H%x1f%h%x1f%an%x1f%ae%x1f%aI%x1f%at%x1f%s%x1e
        Separator \x1f separates fields, \x1e separates records.
        """
        args = ["log", "--format=%H%x1f%h%x1f%an%x1f%ae%x1f%aI%x1f%at%x1f%s%x1e"]
        if limit is not None and limit > 0:
            args.extend(["-n", str(limit)])
        if since:
            args.append(f"--since={since}")

        code, out, _ = self.run(args, cwd=repo_root, check=False)
        if code != 0 or not out.strip():
            return []

        commits: list[CommitInfo] = []
        records = out.strip().split("\x1e")

        for record in records:
            record = record.strip()
            if not record:
                continue
            fields = record.split("\x1f")
            if len(fields) >= 7:
                full_hash = fields[0].strip()
                short_hash = fields[1].strip()
                author_name = fields[2].strip()
                author_email = fields[3].strip()
                date_iso = fields[4].strip()
                try:
                    timestamp = int(fields[5].strip())
                except ValueError:
                    timestamp = 0
                subject = fields[6].strip()

                commits.append(
                    CommitInfo(
                        hash=full_hash,
                        short_hash=short_hash,
                        author_name=author_name,
                        author_email=author_email,
                        date=date_iso,
                        timestamp=timestamp,
                        message=subject,
                    )
                )

        return commits
