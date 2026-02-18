"""Git Coordinator — branch-per-agent strategy with merge-as-approval.

Manages git operations for multi-agent conductor builds:
- Creates feature branches per agent/task
- Commits agent work with structured messages
- Merges on review approval
- Tracks diffs for reviewer context

Architecture:
    - Uses asyncio subprocess for git commands (non-blocking)
    - Events emitted to LocalEventBus for conductor visibility
    - Integrates with WorkRegistry for git operation tracking

Usage:
    from core.git_coordinator import git_coordinator

    # In conductor:
    branch = await git_coordinator.create_branch("feature/build-api", conductor_id="cond-abc")
    await git_coordinator.commit(branch, "Implement REST API endpoints", agent_id="builder-1")
    diff = await git_coordinator.get_diff(branch)  # For reviewer
    await git_coordinator.merge(branch, conductor_id="cond-abc")  # On approval
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("nexus.git_coordinator")

_DEFAULT_PROJECT_DIR = "/Users/lennyfinn/Nexus"
_GIT_TIMEOUT = 30  # seconds per git command


@dataclass
class GitBranch:
    """Tracked git branch for a conductor build."""

    name: str
    conductor_id: str
    agent_id: str = ""
    task_description: str = ""
    commit_count: int = 0
    files_changed: int = 0
    status: str = "active"  # "active", "merged", "abandoned"
    created_at: float = field(default_factory=time.time)


class GitCoordinator:
    """Manages git operations for multi-agent builds."""

    def __init__(self):
        self._branches: dict[str, GitBranch] = {}
        self._event_bus: Any = None
        self._project_dir: str = _DEFAULT_PROJECT_DIR
        self._initialized = False

    def init(
        self,
        event_bus: Any = None,
        project_dir: str = _DEFAULT_PROJECT_DIR,
    ) -> None:
        """Initialize. Call from app.py lifespan."""
        self._event_bus = event_bus
        self._project_dir = project_dir
        self._initialized = True
        logger.info("Git coordinator initialized (project=%s)", project_dir)

    # ── Branch Operations ────────────────────────────────────────

    async def create_branch(
        self,
        branch_name: str,
        conductor_id: str = "",
        agent_id: str = "",
        task_description: str = "",
        base_branch: str = "main",
    ) -> GitBranch:
        """Create a new feature branch for an agent task.

        Args:
            branch_name: Name for the branch (e.g., "feature/build-api")
            conductor_id: Conductor run this belongs to
            agent_id: Agent that will work on this branch
            task_description: What this branch is for
            base_branch: Branch to create from (default: main)

        Returns:
            GitBranch tracking object
        """
        # Ensure we're on the base branch first
        await self._git("checkout", base_branch)
        await self._git("pull", "--rebase", "origin", base_branch, allow_fail=True)

        # Create and switch to new branch
        result = await self._git("checkout", "-b", branch_name)

        branch = GitBranch(
            name=branch_name,
            conductor_id=conductor_id,
            agent_id=agent_id,
            task_description=task_description,
        )
        self._branches[branch_name] = branch

        # Emit event
        await self._emit_git_event(
            "branch", branch_name,
            f"Created branch from {base_branch}",
            conductor_id=conductor_id,
            agent_id=agent_id,
        )

        logger.info("Created branch %s for %s", branch_name, task_description[:50])
        return branch

    async def switch_branch(self, branch_name: str) -> str:
        """Switch to an existing branch."""
        result = await self._git("checkout", branch_name)
        return result

    async def commit(
        self,
        branch_name: str,
        message: str,
        agent_id: str = "",
        files: Optional[list[str]] = None,
    ) -> str:
        """Commit changes on a branch.

        Args:
            branch_name: Branch to commit on
            message: Commit message
            agent_id: Agent that made the changes
            files: Specific files to stage (None = all changes)

        Returns:
            Git commit hash
        """
        # Ensure we're on the right branch
        current = await self._git("rev-parse", "--abbrev-ref", "HEAD")
        if current.strip() != branch_name:
            await self._git("checkout", branch_name)

        # Stage files
        if files:
            for f in files:
                await self._git("add", f)
        else:
            await self._git("add", "-A")

        # Check if there are staged changes
        status = await self._git("diff", "--cached", "--stat")
        if not status.strip():
            logger.info("No changes to commit on %s", branch_name)
            return ""

        # Count files changed
        files_changed = len([
            line for line in status.strip().split("\n")
            if line.strip() and "|" in line
        ])

        # Commit with structured message
        full_message = f"{message}\n\nAgent: {agent_id}" if agent_id else message
        result = await self._git("commit", "-m", full_message)

        # Get commit hash
        commit_hash = await self._git("rev-parse", "--short", "HEAD")
        commit_hash = commit_hash.strip()

        # Update tracking
        branch = self._branches.get(branch_name)
        if branch:
            branch.commit_count += 1
            branch.files_changed += files_changed

        # Emit event
        await self._emit_git_event(
            "commit", branch_name, message,
            files_changed=files_changed,
            conductor_id=branch.conductor_id if branch else "",
            agent_id=agent_id,
        )

        logger.info("Committed %s on %s: %s", commit_hash, branch_name, message[:50])
        return commit_hash

    async def get_diff(
        self,
        branch_name: str,
        base_branch: str = "main",
        stat_only: bool = False,
    ) -> str:
        """Get the diff for a branch against the base.

        Args:
            branch_name: Feature branch
            base_branch: Branch to diff against
            stat_only: If True, return only file stats (not full diff)

        Returns:
            Diff output as string
        """
        if stat_only:
            return await self._git("diff", "--stat", f"{base_branch}...{branch_name}")
        return await self._git("diff", f"{base_branch}...{branch_name}")

    async def get_changed_files(
        self,
        branch_name: str,
        base_branch: str = "main",
    ) -> list[str]:
        """Get list of files changed on a branch."""
        result = await self._git(
            "diff", "--name-only", f"{base_branch}...{branch_name}"
        )
        return [f.strip() for f in result.strip().split("\n") if f.strip()]

    async def merge(
        self,
        branch_name: str,
        target_branch: str = "main",
        conductor_id: str = "",
        delete_after: bool = True,
    ) -> str:
        """Merge a feature branch into target.

        Args:
            branch_name: Branch to merge
            target_branch: Branch to merge into
            conductor_id: For event tracking
            delete_after: Delete branch after merge

        Returns:
            Merge result message
        """
        # Switch to target
        await self._git("checkout", target_branch)

        # Merge with no-ff for clean history
        result = await self._git("merge", "--no-ff", branch_name,
                                 "-m", f"Merge {branch_name}: conductor {conductor_id}")

        # Delete branch if requested
        if delete_after:
            await self._git("branch", "-d", branch_name, allow_fail=True)

        # Update tracking
        branch = self._branches.get(branch_name)
        if branch:
            branch.status = "merged"

        # Emit event
        await self._emit_git_event(
            "merge", branch_name,
            f"Merged into {target_branch}",
            conductor_id=conductor_id,
        )

        logger.info("Merged %s into %s", branch_name, target_branch)
        return result

    async def abandon_branch(
        self,
        branch_name: str,
        reason: str = "",
    ) -> None:
        """Abandon a branch (switch away and optionally delete)."""
        current = await self._git("rev-parse", "--abbrev-ref", "HEAD")
        if current.strip() == branch_name:
            await self._git("checkout", "main")

        # Don't force-delete — just mark as abandoned
        branch = self._branches.get(branch_name)
        if branch:
            branch.status = "abandoned"

        logger.info("Abandoned branch %s: %s", branch_name, reason)

    # ── Query Operations ─────────────────────────────────────────

    async def get_status(self) -> str:
        """Get current git status."""
        return await self._git("status", "--short")

    async def get_current_branch(self) -> str:
        """Get the current branch name."""
        result = await self._git("rev-parse", "--abbrev-ref", "HEAD")
        return result.strip()

    async def get_recent_commits(self, count: int = 10) -> str:
        """Get recent commits (one-line format)."""
        return await self._git(
            "log", f"--oneline", f"-{count}", "--no-decorate"
        )

    def get_tracked_branches(
        self, conductor_id: Optional[str] = None
    ) -> list[dict]:
        """Get all tracked branches, optionally filtered by conductor."""
        branches = self._branches.values()
        if conductor_id:
            branches = [b for b in branches if b.conductor_id == conductor_id]
        return [
            {
                "name": b.name,
                "conductor_id": b.conductor_id,
                "agent_id": b.agent_id,
                "task": b.task_description,
                "commits": b.commit_count,
                "files_changed": b.files_changed,
                "status": b.status,
            }
            for b in branches
        ]

    # ── Safety Operations ────────────────────────────────────────

    async def stash_changes(self, message: str = "") -> str:
        """Stash any uncommitted changes."""
        if message:
            return await self._git("stash", "push", "-m", message)
        return await self._git("stash")

    async def ensure_clean(self) -> bool:
        """Check if the working tree is clean."""
        status = await self._git("status", "--porcelain")
        return not status.strip()

    # ── Internal ─────────────────────────────────────────────────

    async def _git(self, *args: str, allow_fail: bool = False) -> str:
        """Execute a git command and return output."""
        cmd = ["git", "-C", self._project_dir, *args]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_GIT_TIMEOUT
            )

            output = stdout.decode().strip()

            if proc.returncode != 0 and not allow_fail:
                error = stderr.decode().strip()
                logger.warning(
                    "Git command failed: %s → %s",
                    " ".join(args), error[:200],
                )
                return error or output

            return output

        except asyncio.TimeoutError:
            logger.error("Git command timed out: %s", " ".join(args))
            return f"[git timeout: {' '.join(args)}]"
        except Exception as e:
            logger.error("Git error: %s", e)
            return f"[git error: {e}]"

    async def _emit_git_event(
        self,
        operation: str,
        branch: str,
        message: str,
        files_changed: int = 0,
        conductor_id: str = "",
        agent_id: str = "",
    ) -> None:
        """Emit a GitEvent to the local event bus."""
        if not self._event_bus:
            return

        try:
            from core.event_bus import GitEvent
            await self._event_bus.publish(GitEvent(
                conductor_id=conductor_id,
                operation=operation,
                branch=branch,
                message=message,
                files_changed=files_changed,
                agent_id=agent_id,
            ))
        except Exception as e:
            logger.debug("Git event emission failed: %s", e)


# ── Global singleton ────────────────────────────────────────────
git_coordinator = GitCoordinator()
