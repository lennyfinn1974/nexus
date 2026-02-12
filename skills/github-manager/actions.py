import subprocess
import json
import os
from typing import Dict


def _run_gh(*args: str, timeout: int = 30) -> tuple:
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except FileNotFoundError:
        return "", "gh CLI not found", 1
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1


def github_clone(params: Dict) -> str:
    """Clone a GitHub repository."""
    repo = params.get("repo", "").strip()
    directory = params.get("directory", "").strip()
    if not repo:
        return "Error: repo is required (owner/name)"

    args = ["repo", "clone", repo]
    if directory:
        args.append(os.path.expanduser(directory))

    stdout, stderr, rc = _run_gh(*args, timeout=120)
    if rc != 0:
        return f"Error cloning: {stderr}"
    return f"Cloned {repo} successfully.\n{stdout}"


def github_list_repos(params: Dict) -> str:
    """List your GitHub repositories."""
    limit = params.get("limit", "10")
    sort = params.get("sort", "updated")

    stdout, stderr, rc = _run_gh(
        "repo", "list", "--limit", str(limit), "--sort", sort,
        "--json", "nameWithOwner,description,stargazerCount,updatedAt,isPrivate",
    )
    if rc != 0:
        return f"Error: {stderr}"

    try:
        repos = json.loads(stdout)
        if not repos:
            return "No repositories found."

        lines = ["**Your Repositories:**"]
        for r in repos:
            stars = r.get("stargazerCount", 0)
            desc = (r.get("description") or "")[:60]
            vis = "private" if r.get("isPrivate") else "public"
            lines.append(f"- **{r['nameWithOwner']}** ({vis}, {stars} stars): {desc}")
        return "\n".join(lines)
    except json.JSONDecodeError:
        return stdout or "No repos found."


def github_pr_list(params: Dict) -> str:
    """List pull requests for a repository."""
    repo = params.get("repo", "").strip()
    state = params.get("state", "open")
    if not repo:
        return "Error: repo is required"

    stdout, stderr, rc = _run_gh(
        "pr", "list", "--repo", repo, "--state", state,
        "--json", "number,title,author,state,createdAt,headRefName",
    )
    if rc != 0:
        return f"Error: {stderr}"

    try:
        prs = json.loads(stdout)
        if not prs:
            return f"No {state} PRs in {repo}."

        lines = [f"**Pull Requests ({state}) — {repo}:**"]
        for pr in prs[:15]:
            author = pr.get("author", {}).get("login", "?")
            branch = pr.get("headRefName", "?")
            lines.append(f"- #{pr['number']} {pr['title']} (by {author}, {branch})")
        return "\n".join(lines)
    except json.JSONDecodeError:
        return stdout


def github_pr_view(params: Dict) -> str:
    """View details of a specific pull request."""
    repo = params.get("repo", "").strip()
    number = params.get("number", "").strip()
    if not repo or not number:
        return "Error: repo and number are required"

    stdout, stderr, rc = _run_gh(
        "pr", "view", number, "--repo", repo,
        "--json", "number,title,body,author,state,createdAt,additions,deletions,files,reviewDecision",
    )
    if rc != 0:
        return f"Error: {stderr}"

    try:
        pr = json.loads(stdout)
        author = pr.get("author", {}).get("login", "?")
        files = pr.get("files", [])
        file_count = len(files)
        body = (pr.get("body") or "No description")[:500]

        return (
            f"**PR #{pr['number']}: {pr['title']}**\n"
            f"Author: {author} | State: {pr.get('state', '?')}\n"
            f"Changes: +{pr.get('additions', 0)} / -{pr.get('deletions', 0)} across {file_count} files\n"
            f"Review: {pr.get('reviewDecision', 'pending')}\n\n"
            f"{body}"
        )
    except json.JSONDecodeError:
        return stdout
