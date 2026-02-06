import logging

from .base import BasePlugin

logger = logging.getLogger("nexus.plugins.github")

class GithubPlugin(BasePlugin):
    name = "github"
    version = "0.9.3"
    tools = ["github_issue_create", "github_pr_open"]
    commands = [{"name": "issue", "description": "Create a GitHub issue"}]

    async def init(self):
        logger.info("GitHub plugin ready")

    async def run(self, repo: str, title: str, body: str):
        # Existing logic …
        ...

    async def shutdown(self):
        logger.info("GitHub plugin stopped")
