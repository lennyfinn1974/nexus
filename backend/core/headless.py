"""Headless browser rendering — Playwright-based JS execution.

Provides a local headless Chromium browser for rendering JavaScript-heavy
pages (SPAs, React apps, etc.) that return empty content via HTTP GET.

The browser is lazy-initialized on first use and kept alive as a singleton
for fast subsequent renders. Gracefully degrades if Playwright is not installed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("nexus.headless")

# Timeout for page navigation (ms)
_NAV_TIMEOUT = 15000
# Default wait after navigation for JS to settle (ms)
_DEFAULT_WAIT_MS = 3000


class HeadlessRenderer:
    """Local headless Chromium for JS-rendered page content.

    Usage:
        renderer = HeadlessRenderer()
        content = await renderer.render("https://example.com")
        # ... later ...
        await renderer.close()
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._available: Optional[bool] = None  # None = not checked yet

    async def _ensure_browser(self) -> bool:
        """Lazy-init: start Playwright and launch Chromium on first use.

        Returns True if browser is ready, False if Playwright is unavailable.
        """
        if self._browser is not None:
            return True

        if self._available is False:
            return False  # Already tried and failed

        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--no-first-run",
                ],
            )
            self._available = True
            logger.info("Headless Chromium launched successfully")
            return True

        except ImportError:
            self._available = False
            logger.warning(
                "Playwright not installed — headless rendering unavailable. "
                "Install: pip3 install playwright && python3 -m playwright install chromium"
            )
            return False
        except Exception as e:
            self._available = False
            logger.error(f"Failed to launch headless Chromium: {e}")
            return False

    async def render(
        self,
        url: str,
        wait_ms: int = _DEFAULT_WAIT_MS,
        max_chars: int = 8000,
    ) -> Optional[str]:
        """Render a page with JavaScript execution, return extracted Markdown.

        Args:
            url: URL to render.
            wait_ms: Milliseconds to wait after navigation for JS to settle.
            max_chars: Maximum output length.

        Returns:
            Structured Markdown string, or None if rendering failed/unavailable.
        """
        if not await self._ensure_browser():
            return None

        page = None
        try:
            page = await self._browser.new_page()

            # Block unnecessary resources for speed
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,eot}",
                lambda route: route.abort(),
            )

            # Navigate with networkidle wait
            try:
                await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=_NAV_TIMEOUT,
                )
            except Exception:
                # networkidle can timeout on streaming sites — try domcontentloaded
                logger.debug(f"networkidle timeout for {url}, trying domcontentloaded")
                try:
                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=_NAV_TIMEOUT,
                    )
                except Exception as nav_err:
                    logger.warning(f"Navigation failed for {url}: {nav_err}")
                    return None

            # Wait for JS to settle (SPA rendering, lazy loading, etc.)
            await page.wait_for_timeout(wait_ms)

            # Get the fully rendered HTML
            html = await page.content()

            # Extract with web_extract (same pipeline as HTTP fetch)
            from core.web_extract import extract_content

            result = extract_content(html, url=url, max_chars=max_chars)
            logger.info(f"Headless rendered {url}: {len(result)} chars extracted")
            return result

        except Exception as e:
            logger.error(f"Headless render error for {url}: {e}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    @property
    def is_available(self) -> Optional[bool]:
        """Check if headless rendering is available (None = not checked yet)."""
        return self._available

    async def close(self) -> None:
        """Shutdown the browser and Playwright."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        logger.info("Headless renderer shut down")
