import logging

from .base import BasePlugin

logger = logging.getLogger("nexus.plugins.browser")

class BrowserPlugin(BasePlugin):
    name = "browser"
    version = "1.2.0"
    tools = ["browser_open", "browser_screenshot"]
    commands = [{"name": "open", "description": "Open a URL in the browser"}]

    async def init(self):
        logger.info("Browser plugin initialised")

    async def run(self, url: str):
        # Existing implementation moved here …
        ...

    async def shutdown(self):
        logger.info("Browser plugin shutting down")
