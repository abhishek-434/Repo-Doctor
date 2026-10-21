import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from repodoctor.git_runner import (
    GitCommandError,
    GitNotFoundError,
    GitRunner,
    NotAGitRepositoryError,
)


def init_git_repo(path: Path) -> None:
    """Initialize a git repo with standard test user configuration."""
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Doctor"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "doc@example.com"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(path), check=True, capture_output=True)


class TestGitRunner(unittest.TestCase):
    """Test GitRunner methods against isolated temporary git repositories."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        self.runner = GitRunner()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_git_available(self) -> None:
        """Verify that Git is detected on the test machine."""
        self.assertTrue(self.runner.is_git_available)
        self.runner.ensure_git_available()

    def test_missing_git_binary(self) -> None:
        """Verify that GitNotFoundError is raised when git binary is not found."""
        with patch("shutil.which", return_value=None):
            fake_runner = GitRunner(git_path=None)
            self.assertFalse(fake_runner.is_git_available)
            with self.assertRaises(GitNotFoundError):
                fake_runner.ensure_git_available()

    def test_not_a_git_repository(self) -> None:
        """Verify that running against a plain directory raises NotAGitRepositoryError."""
        with self.assertRaises(NotAGitRepositoryError):
            self.runner.find_repo_root(self.repo_path)

    def test_nonexistent_path(self) -> None:
        """Verify that passing a non-existent path raises NotAGitRepositoryError."""
        fake_path = self.repo_path / "does_not_exist_abc123"
        with self.assertRaises(NotAGitRepositoryError):
            self.runner.find_repo_root(fake_path)

    def test_valid_repo_detection_and_nested_path(self) -> None:
        """Verify repository root resolution from root and nested subdirectories."""
        init_git_repo(self.repo_path)
        resolved_root = self.runner.find_repo_root(self.repo_path)
        self.assertEqual(resolved_root.resolve(), self.repo_path.resolve())

        # Test from a nested subdirectory
        subdir = self.repo_path / "src" / "deep"
        subdir.mkdir(parents=True)
        resolved_from_sub = self.runner.find_repo_root(subdir)
        self.assertEqual(resolved_from_sub.resolve(), self.repo_path.resolve())

    def test_empty_repository_detection(self) -> None:
        """Verify metadata extraction for a freshly initialized repository without commits."""
        init_git_repo(self.repo_path)
        info = self.runner.get_repo_info(self.repo_path)
        self.assertTrue(info.is_empty)
        self.assertEqual(info.latest_commit_hash, "")
        self.assertEqual(info.total_tracked_files, 0)

    def test_repository_with_commits_and_branch(self) -> None:
        """Verify metadata extraction after creating initial commits."""
        init_git_repo(self.repo_path)
        test_file = self.repo_path / "README.md"
        test_file.write_text("# Test Repo\n", encoding="utf-8")

        subprocess.run(["git", "add", "README.md"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(self.repo_path), check=True, capture_output=True)

        info = self.runner.get_repo_info(self.repo_path)
        self.assertFalse(info.is_empty)
        self.assertTrue(len(info.latest_commit_hash) >= 40)
        self.assertEqual(info.total_tracked_files, 1)

    def test_detached_head_detection(self) -> None:
        """Verify that checking out a detached commit is detected."""
        init_git_repo(self.repo_path)
        (self.repo_path / "file1.txt").write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "file1.txt"], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "commit 1"], cwd=str(self.repo_path), check=True, capture_output=True)

        # Detach HEAD by checking out HEAD directly
        subprocess.run(["git", "checkout", "--detach", "HEAD"], cwd=str(self.repo_path), check=True, capture_output=True)

        info = self.runner.get_repo_info(self.repo_path)
        self.assertTrue(info.is_detached_head)
        self.assertIn("detached", info.current_branch.lower())

    def test_status_parsing_clean_and_dirty(self) -> None:
        """Verify parsing of modified, staged, untracked, and deleted files."""
        init_git_repo(self.repo_path)
        file1 = self.repo_path / "file1.txt"
        file2 = self.repo_path / "file2.txt"
        file1.write_text("initial", encoding="utf-8")
        file2.write_text("initial", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=str(self.repo_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "base commit"], cwd=str(self.repo_path), check=True, capture_output=True)

        # 1. Clean status
        clean_status = self.runner.get_status(self.repo_path)
        self.assertTrue(clean_status.clean)

        # 2. Modify file1 (unstaged)
        file1.write_text("modified", encoding="utf-8")
        # 3. Add an untracked file
        untracked = self.repo_path / "new_file.txt"
        untracked.write_text("new content", encoding="utf-8")
        # 4. Delete file2
        file2.unlink()

        dirty_status = self.runner.get_status(self.repo_path)
        self.assertFalse(dirty_status.clean)
        self.assertIn("file1.txt", dirty_status.modified_files)
        self.assertIn("new_file.txt", dirty_status.untracked_files)
        self.assertIn("file2.txt", dirty_status.deleted_files)

    def test_status_with_spaces_and_unicode_filenames(self) -> None:
        """Verify handling of filenames with spaces and unicode characters."""
        init_git_repo(self.repo_path)
        special_name = "report document 🚀.txt"
        file_path = self.repo_path / special_name
        file_path.write_text("unicode test", encoding="utf-8")

        subprocess.run(["git", "add", special_name], cwd=str(self.repo_path), check=True, capture_output=True)
        status = self.runner.get_status(self.repo_path)
        self.assertFalse(status.clean)
        self.assertTrue(any(special_name in f or "report document" in f for f in status.staged_files))

    def test_subprocess_timeout(self) -> None:
        """Verify that timeout causes GitCommandError with returncode 124."""
        init_git_repo(self.repo_path)

        def mock_subprocess(cmd, *args, **kwargs):
            if "--version" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "git version 2.0.0", "")
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=0.1)

        with patch("subprocess.run", side_effect=mock_subprocess):
            with self.assertRaises(GitCommandError) as ctx:
                self.runner.run(["status"], cwd=self.repo_path, timeout=0.1)
            self.assertEqual(ctx.exception.returncode, 124)
            self.assertIn("timed out", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
