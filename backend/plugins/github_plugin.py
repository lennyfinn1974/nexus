from .base import BasePlugin

class GithubPlugin(BasePlugin):
    name = "github"
    version = "0.9.3"
    tools = ["github_issue_create", "github_pr_open"]
    commands = [{"name": "issue", "description": "Create a GitHub issue"}]

    async def init(self):
        self.logger = logger.bind(plugin=self.name)
        self.logger.info("GitHub plugin ready")

    async def run(self, repo: str, title: str, body: str):
        # Existing logic …
        ...

    async def shutdown(self):
        self.logger.info("GitHub plugin stopped")