"""Brave Browser Plugin — Browser control and web tools.

Provides tools for:
- Opening URLs
- Getting current URL and page title
- Listing tabs
- Closing tabs
- Navigating (back, forward, reload)
- Executing JavaScript
- Getting page text content
- Google Custom Search API integration
- Web fetching and text extraction

All browser control via osascript targeting "Brave Browser".
Web tools use httpx for HTTP requests.
"""

import asyncio
import json
import logging
import os
import re

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.brave")

MAX_EXEC_TIME = 30  # seconds


class BraveBrowserPlugin(NexusPlugin):
    name = "brave"
    description = "Brave Browser control and web tools — open URLs, tabs, search, execute JS, fetch pages"
    version = "1.0.0"

    def __init__(self, config, db, router):
        super().__init__(config, db, router)
        self.google_api_key = None
        self.google_search_engine_id = None

    async def setup(self):
        # Try to get Google API credentials from config
        if self.config:
            self.google_api_key = getattr(self.config, "google_api_key", None) or os.getenv("GOOGLE_API_KEY")
            self.google_search_engine_id = getattr(self.config, "google_search_engine_id", None) or os.getenv("GOOGLE_SEARCH_ENGINE_ID")

        logger.info("  Brave Browser plugin ready")
        if self.google_api_key:
            logger.info("    Google Search API configured")
        else:
            logger.info("    Google Search API not configured (set GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID)")
        return True

    def register_tools(self):
        # ── Browser Control Tools ──
        self.add_tool(
            "brave_open",
            "Open a URL in Brave Browser (creates new tab)",
            {"url": "URL to open (include http:// or https://)"},
            self._brave_open,
        )
        self.add_tool(
            "brave_get_url",
            "Get the current URL from the active Brave tab",
            {},
            self._brave_get_url,
        )
        self.add_tool(
            "brave_get_title",
            "Get the page title from the active Brave tab",
            {},
            self._brave_get_title,
        )
        self.add_tool(
            "brave_get_tabs",
            "List all open tabs in the frontmost Brave window",
            {},
            self._brave_get_tabs,
        )
        self.add_tool(
            "brave_close_tab",
            "Close a tab by index (or close current tab if no index specified)",
            {"index": "Optional: tab index to close (1-based)"},
            self._brave_close_tab,
        )
        self.add_tool(
            "brave_navigate",
            "Navigate the current tab (back, forward, or reload)",
            {"action": "Action: 'back', 'forward', or 'reload'"},
            self._brave_navigate,
        )
        self.add_tool(
            "brave_execute_js",
            "Execute JavaScript code in the active Brave tab and return the result",
            {"code": "JavaScript code to execute"},
            self._brave_execute_js,
        )
        self.add_tool(
            "brave_get_page_text",
            "Extract all text content from the current page",
            {},
            self._brave_get_page_text,
        )

        # ── Web Tools ──
        self.add_tool(
            "google_search",
            "Search Google and return top results with titles, URLs, and snippets",
            {"query": "Search query", "num_results": "Number of results to return (default: 5)"},
            self._google_search,
        )
        self.add_tool(
            "web_fetch",
            "Fetch a URL and extract its text content (removes HTML tags)",
            {"url": "URL to fetch"},
            self._web_fetch,
        )

    def register_commands(self):
        self.add_command("browse", "Open URL in Brave: /browse <url>", self._handle_browse)
        self.add_command("google", "Google search: /google <query>", self._handle_google)

    # ────────────────────────────────────────────
    # Browser Control Tools
    # ────────────────────────────────────────────

    async def _brave_open(self, params):
        url = params.get("url", "").strip()
        if not url:
            return "Error: url is required"

        # Add https:// if no protocol specified
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        script = f'''
        tell application "Brave Browser"
            activate
            open location "{url}"
        end tell
        '''
        await self._run_osascript(script)
        return f"✅ Opened {url} in Brave"

    async def _brave_get_url(self, params):
        script = '''
        tell application "Brave Browser"
            if (count of windows) > 0 then
                get URL of active tab of front window
            else
                return "No windows open"
            end if
        end tell
        '''
        result = await self._run_osascript(script)
        if "No windows open" in result:
            return "No Brave windows open"
        return f"Current URL: {result}"

    async def _brave_get_title(self, params):
        script = '''
        tell application "Brave Browser"
            if (count of windows) > 0 then
                get title of active tab of front window
            else
                return "No windows open"
            end if
        end tell
        '''
        result = await self._run_osascript(script)
        if "No windows open" in result:
            return "No Brave windows open"
        return f"Page title: {result}"

    async def _brave_get_tabs(self, params):
        script = '''
        tell application "Brave Browser"
            if (count of windows) = 0 then
                return "No windows open"
            end if

            set tabList to {}
            set tabCount to count of tabs of front window

            repeat with i from 1 to tabCount
                set tabTitle to title of tab i of front window
                set tabURL to URL of tab i of front window
                set end of tabList to (i as string) & ". " & tabTitle & " — " & tabURL
            end repeat

            return tabList as string
        end tell
        '''
        result = await self._run_osascript(script)
        if "No windows open" in result:
            return "No Brave windows open"

        lines = ["🌐 **Brave Tabs:**\n"]
        # Parse the result
        tabs = result.split(", ")
        for tab in tabs:
            if tab.strip():
                lines.append(tab.strip())

        return "\n".join(lines) if len(lines) > 1 else "No tabs found"

    async def _brave_close_tab(self, params):
        index = params.get("index", "").strip()

        if index:
            script = f'''
            tell application "Brave Browser"
                if (count of windows) > 0 then
                    close tab {index} of front window
                    return "Closed tab {index}"
                else
                    return "No windows open"
                end if
            end tell
            '''
        else:
            script = '''
            tell application "Brave Browser"
                if (count of windows) > 0 then
                    close active tab of front window
                    return "Closed active tab"
                else
                    return "No windows open"
                end if
            end tell
            '''

        result = await self._run_osascript(script)
        return result

    async def _brave_navigate(self, params):
        action = params.get("action", "").strip().lower()
        if action not in ["back", "forward", "reload"]:
            return "Error: action must be 'back', 'forward', or 'reload'"

        if action == "back":
            js = "window.history.back()"
        elif action == "forward":
            js = "window.history.forward()"
        else:  # reload
            js = "window.location.reload()"

        return await self._brave_execute_js({"code": js})

    async def _brave_execute_js(self, params):
        code = params.get("code", "").strip()
        if not code:
            return "Error: code is required"

        # Escape quotes and newlines for AppleScript
        code = code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

        script = f'''
        tell application "Brave Browser"
            if (count of windows) = 0 then
                return "No windows open"
            end if

            try
                set jsResult to execute active tab of front window javascript "{code}"
                return jsResult as string
            on error errMsg
                return "JavaScript error: " & errMsg
            end try
        end tell
        '''

        result = await self._run_osascript(script)
        if "No windows open" in result:
            return "No Brave windows open"
        if not result or result == "missing value":
            return "✅ JavaScript executed (no return value)"
        return f"JavaScript result:\n{result}"

    async def _brave_get_page_text(self, params):
        # Use JavaScript to extract all text from the page
        js_code = "document.body.innerText"
        result = await self._brave_execute_js({"code": js_code})

        if "No windows open" in result or "JavaScript error" in result:
            return result

        # Clean up the result
        text = result.replace("JavaScript result:\n", "")
        if len(text) > 5000:
            text = text[:5000] + "\n\n... (truncated to 5000 chars)"

        return f"Page text content:\n```\n{text}\n```"

    # ────────────────────────────────────────────
    # Web Tools
    # ────────────────────────────────────────────

    async def _google_search(self, params):
        query = params.get("query", "").strip()
        num_results = int(params.get("num_results", "5"))

        if not query:
            return "Error: query is required"

        if not self.google_api_key or not self.google_search_engine_id:
            return "⚠️ Google Search API not configured. Set GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID environment variables."

        try:
            import httpx

            url = "https://www.googleapis.com/customsearch/v1"
            params_dict = {
                "key": self.google_api_key,
                "cx": self.google_search_engine_id,
                "q": query,
                "num": min(num_results, 10),  # API max is 10
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params_dict)
                response.raise_for_status()
                data = response.json()

            items = data.get("items", [])
            if not items:
                return f"No results found for: {query}"

            lines = [f"🔍 **Google Search Results for '{query}':**\n"]
            for i, item in enumerate(items, 1):
                title = item.get("title", "No title")
                link = item.get("link", "")
                snippet = item.get("snippet", "")
                lines.append(f"{i}. **{title}**")
                lines.append(f"   {link}")
                lines.append(f"   {snippet}\n")

            return "\n".join(lines)

        except ImportError:
            return "Error: httpx not installed. Run: pip install httpx"
        except Exception as e:
            return f"Google Search error: {e}"

    async def _web_fetch(self, params):
        url = params.get("url", "").strip()
        if not url:
            return "Error: url is required"

        # Add https:// if no protocol specified
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")

                # Only process HTML/text content
                if "html" in content_type or "text" in content_type:
                    html = response.text

                    # Simple HTML tag removal
                    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r"<[^>]+>", "", text)

                    # Clean up whitespace
                    text = re.sub(r"\n\s*\n", "\n\n", text)
                    text = text.strip()

                    if len(text) > 10000:
                        text = text[:10000] + "\n\n... (truncated to 10000 chars)"

                    return f"📄 **{url}**\n\n{text}"
                else:
                    return f"⚠️ Unsupported content type: {content_type}"

        except ImportError:
            return "Error: httpx not installed. Run: pip install httpx"
        except Exception as e:
            return f"Web fetch error: {e}"

    # ────────────────────────────────────────────
    # Command Handlers
    # ────────────────────────────────────────────

    async def _handle_browse(self, args):
        url = args.strip()
        if not url:
            return "Usage: /browse <url>"
        return await self._brave_open({"url": url})

    async def _handle_google(self, args):
        query = args.strip()
        if not query:
            return "Usage: /google <search query>"
        return await self._google_search({"query": query})

    # ────────────────────────────────────────────
    # Helper
    # ────────────────────────────────────────────

    async def _run_osascript(self, script: str) -> str:
        """Execute AppleScript and return output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=MAX_EXEC_TIME)

            result = stdout.decode().strip()
            if stderr:
                err = stderr.decode().strip()
                if err and "execution error" in err.lower():
                    return f"Error: {err}"

            return result
        except asyncio.TimeoutError:
            return f"⏱ Timed out after {MAX_EXEC_TIME}s"
        except Exception as e:
            return f"Error: {e}"
