from .base import BasePlugin

class BrowserPlugin(BasePlugin):
    name = "browser"
    version = "1.2.0"
    tools = ["browser_open", "browser_screenshot"]
    commands = [{"name": "open", "description": "Open a URL in the browser"}]

    async def init(self):
        self.logger = logger.bind(plugin=self.name)
        self.logger.info("Browser plugin initialised")

    async def run(self, url: str):
        # Existing implementation moved here …
        ...

    async def shutdown(self):
        self.logger.info("Browser plugin shutting down")