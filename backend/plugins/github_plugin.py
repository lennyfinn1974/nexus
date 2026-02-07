"""GitHub plugin — repository search, issues, PRs via `gh` CLI."""

import asyncio
import json
import logging
import shutil

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.github")


class GithubPlugin(NexusPlugin):
    name = "github"
    description = "GitHub integration — search repos, manage issues and PRs via gh CLI"
    version = "1.0.0"

    async def setup(self):
        """Verify gh CLI is installed and authenticated."""
        if not shutil.which("gh"):
            logger.warning("gh CLI not found — GitHub plugin disabled")
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                "gh", "auth", "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                logger.warning(f"gh not authenticated — GitHub plugin disabled: {stderr.decode().strip()}")
                return False
        except Exception as e:
            logger.warning(f"gh auth check failed: {e}")
            return False

        logger.info("GitHub plugin ready (gh CLI authenticated)")
        return True

    def register_tools(self):
        self.add_tool(
            "github_search_repos",
            "Search GitHub repositories by query",
            {"query": "Search query string", "limit": "Max results (default 5)"},
            self._search_repos,
        )
        self.add_tool(
            "github_get_repo_info",
            "Get detailed information about a GitHub repository",
            {"repo": "Repository in owner/name format"},
            self._get_repo_info,
        )
        self.add_tool(
            "github_list_issues",
            "List issues for a repository",
            {"repo": "Repository in owner/name format", "state": "open/closed/all (default open)", "limit": "Max results (default 10)"},
            self._list_issues,
        )
        self.add_tool(
            "github_create_issue",
            "Create a new issue in a repository",
            {"repo": "Repository in owner/name format", "title": "Issue title", "body": "Issue body"},
            self._create_issue,
        )
        self.add_tool(
            "github_create_pr",
            "Create a pull request",
            {"repo": "Repository in owner/name format", "title": "PR title", "body": "PR body", "head": "Source branch", "base": "Target branch (default main)"},
            self._create_pr,
        )

    def register_commands(self):
        self.add_command("github", "GitHub operations: /github search|issues|info <args>", self._handle_command)

    # ── Helpers ──

    async def _run_gh(self, *args: str, timeout: float = 30) -> tuple[str, str, int]:
        """Run a gh CLI command and return (stdout, stderr, returncode)."""
        proc = await asyncio.create_subprocess_exec(
            "gh", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode().strip(), stderr.decode().strip(), proc.returncode

    # ── Tool Handlers ──

    async def _search_repos(self, params: dict) -> str:
        query = params.get("query", "")
        limit = params.get("limit", "5")
        if not query:
            return "Error: query is required"

        stdout, stderr, rc = await self._run_gh(
            "search", "repos", query, "--limit", str(limit), "--json",
            "fullName,description,stargazersCount,language,updatedAt",
        )
        if rc != 0:
            return f"Error: {stderr}"

        try:
            repos = json.loads(stdout)
            lines = []
            for r in repos:
                stars = r.get("stargazersCount", 0)
                lang = r.get("language", "")
                desc = r.get("description", "")[:80]
                lines.append(f"- **{r['fullName']}** ({lang}, {stars} stars): {desc}")
            return "\n".join(lines) if lines else "No repositories found."
        except json.JSONDecodeError:
            return stdout or "No results."

    async def _get_repo_info(self, params: dict) -> str:
        repo = params.get("repo", "")
        if not repo:
            return "Error: repo is required (owner/name)"

        stdout, stderr, rc = await self._run_gh(
            "repo", "view", repo, "--json",
            "name,owner,description,stargazersCount,forksCount,openIssues,language,defaultBranchRef,createdAt,updatedAt,url",
        )
        if rc != 0:
            return f"Error: {stderr}"

        try:
            info = json.loads(stdout)
            owner = info.get("owner", {}).get("login", "")
            branch = info.get("defaultBranchRef", {}).get("name", "main")
            return (
                f"**{owner}/{info['name']}**\n"
                f"Description: {info.get('description', 'N/A')}\n"
                f"Language: {info.get('language', 'N/A')}\n"
                f"Stars: {info.get('stargazersCount', 0)} | Forks: {info.get('forksCount', 0)} | Open Issues: {info.get('openIssues', {}).get('totalCount', 0)}\n"
                f"Default Branch: {branch}\n"
                f"URL: {info.get('url', '')}"
            )
        except json.JSONDecodeError:
            return stdout

    async def _list_issues(self, params: dict) -> str:
        repo = params.get("repo", "")
        state = params.get("state", "open")
        limit = params.get("limit", "10")
        if not repo:
            return "Error: repo is required (owner/name)"

        stdout, stderr, rc = await self._run_gh(
            "issue", "list", "--repo", repo, "--state", state,
            "--limit", str(limit), "--json", "number,title,state,author,createdAt,labels",
        )
        if rc != 0:
            return f"Error: {stderr}"

        try:
            issues = json.loads(stdout)
            if not issues:
                return f"No {state} issues found in {repo}."
            lines = []
            for i in issues:
                author = i.get("author", {}).get("login", "unknown")
                labels = ", ".join(l.get("name", "") for l in i.get("labels", []))
                label_str = f" [{labels}]" if labels else ""
                lines.append(f"- #{i['number']} {i['title']} (by {author}){label_str}")
            return "\n".join(lines)
        except json.JSONDecodeError:
            return stdout

    async def _create_issue(self, params: dict) -> str:
        repo = params.get("repo", "")
        title = params.get("title", "")
        body = params.get("body", "")
        if not repo or not title:
            return "Error: repo and title are required"

        args = ["issue", "create", "--repo", repo, "--title", title]
        if body:
            args.extend(["--body", body])

        stdout, stderr, rc = await self._run_gh(*args)
        if rc != 0:
            return f"Error creating issue: {stderr}"
        return f"Issue created: {stdout}"

    async def _create_pr(self, params: dict) -> str:
        repo = params.get("repo", "")
        title = params.get("title", "")
        body = params.get("body", "")
        head = params.get("head", "")
        base = params.get("base", "main")
        if not repo or not title or not head:
            return "Error: repo, title, and head branch are required"

        args = ["pr", "create", "--repo", repo, "--title", title, "--head", head, "--base", base]
        if body:
            args.extend(["--body", body])

        stdout, stderr, rc = await self._run_gh(*args)
        if rc != 0:
            return f"Error creating PR: {stderr}"
        return f"PR created: {stdout}"

    # ── Slash Command Handler ──

    async def _handle_command(self, args: str) -> str:
        parts = args.strip().split(None, 1)
        if not parts:
            return (
                "**GitHub Commands:**\n"
                "- `/github search <query>` — search repositories\n"
                "- `/github issues <owner/repo>` — list open issues\n"
                "- `/github info <owner/repo>` — get repo details"
            )

        sub = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if sub == "search":
            return await self._search_repos({"query": rest})
        elif sub == "issues":
            return await self._list_issues({"repo": rest})
        elif sub == "info":
            return await self._get_repo_info({"repo": rest})
        else:
            return f"Unknown subcommand: {sub}. Use search, issues, or info."
