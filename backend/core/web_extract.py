"""Web content extraction — HTML to structured Markdown.

Replaces regex-based HTML tag stripping with semantic extraction using
BeautifulSoup + html2text. Provides Ollama (and Claude) with structured
content that preserves headings, lists, links, and page hierarchy.

Reuses extraction patterns from skills/web-research/actions.py.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("nexus.web_extract")

# Model-aware content limits (chars, ~4 chars/token)
MODEL_CONTENT_LIMITS = {
    "ollama": 8000,     # ~2000 tokens — fits in 32K with room for tools
    "claude": 30000,    # ~7500 tokens — fits in 200K easily
    "claude_code": 30000,
}

# Tags to remove entirely (content + tag)
NOISE_TAGS = [
    "script", "style", "nav", "footer", "header", "aside",
    "noscript", "iframe", "svg", "form",
]

# CSS selectors for noise elements
NOISE_SELECTORS = [
    '[role="banner"]',
    '[role="navigation"]',
    '[role="contentinfo"]',
    '[class*="cookie"]',
    '[class*="popup"]',
    '[class*="modal"]',
    '[class*="overlay"]',
    '[class*="banner"]',
    '[class*="advertisement"]',
    '[class*="sidebar"]',
    '[id*="cookie"]',
    '[id*="popup"]',
    '[id*="modal"]',
]


def extract_content(
    html: str,
    url: str = "",
    max_chars: int = 9000,
    include_links: bool = True,
    include_meta: bool = True,
) -> str:
    """Extract readable content from HTML as structured Markdown.

    Args:
        html: Raw HTML string.
        url: Source URL (for display).
        max_chars: Maximum output length in characters.
        include_links: Whether to extract key page links.
        include_meta: Whether to include meta description/keywords.

    Returns:
        Structured Markdown string with title, content, links, and metadata.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed — falling back to regex extraction")
        return _regex_fallback(html, url, max_chars)

    try:
        import html2text as h2t
    except ImportError:
        logger.warning("html2text not installed — falling back to BS4 text-only")
        return _bs4_text_only(html, url, max_chars)

    soup = BeautifulSoup(html, "html.parser")

    # ── Extract metadata before stripping ──
    title = _extract_title(soup)
    meta = _extract_metadata(soup) if include_meta else {}
    key_links = _extract_key_links(soup, url) if include_links else []

    # ── Remove noise elements ──
    for tag_name in NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for selector in NOISE_SELECTORS:
        try:
            for el in soup.select(selector):
                el.decompose()
        except Exception:
            pass  # Some selectors may not be supported

    # ── Find main content area ──
    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find("body")
    )

    if not main:
        main = soup

    # ── Convert to Markdown via html2text ──
    converter = h2t.HTML2Text()
    converter.body_width = 0          # No line wrapping
    converter.ignore_images = True    # Skip image tags (Ollama can't see them)
    converter.ignore_emphasis = False # Keep bold/italic
    converter.protect_links = True    # Preserve link URLs
    converter.unicode_snob = True     # Use Unicode chars
    converter.skip_internal_links = True

    markdown = converter.handle(str(main))

    # ── Clean up the markdown ──
    # Remove excessive blank lines
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    # Remove leading/trailing whitespace per line
    lines = [line.rstrip() for line in markdown.split("\n")]
    markdown = "\n".join(lines).strip()

    # ── Build structured output ──
    parts = []

    # Title
    if title:
        parts.append(f"# {title}")
    parts.append(f"**URL:** {url}" if url else "")

    # Meta description
    if meta.get("description"):
        parts.append(f"**Description:** {meta['description']}")

    parts.append("")  # blank line

    # Main content
    if markdown:
        parts.append(markdown)
    else:
        parts.append("*No readable content extracted from this page.*")

    # Key links (if space permits)
    if key_links:
        parts.append("\n## Key Links")
        for link_text, link_url in key_links[:10]:
            parts.append(f"- [{link_text}]({link_url})")

    result = "\n".join(p for p in parts if p is not None)

    # ── Truncate at paragraph boundary ──
    if len(result) > max_chars:
        result = _truncate_at_boundary(result, max_chars)

    return result


def extract_metadata(html: str) -> dict:
    """Extract page metadata — title, description, og:tags.

    Useful for quick page classification without full content extraction.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    return _extract_metadata(soup)


def is_sparse_content(text: str, threshold: int = 200) -> bool:
    """Check if extracted content is too sparse (likely a JS-heavy SPA).

    Args:
        text: Extracted text content.
        threshold: Minimum chars for non-sparse content.
    """
    # Strip markdown formatting for accurate length check
    clean = re.sub(r"[#*\[\]()_`>-]", "", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return len(clean) < threshold


# ── Internal helpers ──


def _extract_title(soup) -> str:
    """Extract the best page title."""
    # Try og:title first (most descriptive)
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    # Then <title>
    if soup.title and soup.title.string:
        return soup.title.string.strip()

    # Then first <h1>
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    return ""


def _extract_metadata(soup) -> dict:
    """Extract structured metadata from <head>."""
    meta = {}

    # Description
    desc_tag = (
        soup.find("meta", attrs={"name": "description"})
        or soup.find("meta", property="og:description")
    )
    if desc_tag and desc_tag.get("content"):
        meta["description"] = desc_tag["content"].strip()[:300]

    # Keywords
    kw_tag = soup.find("meta", attrs={"name": "keywords"})
    if kw_tag and kw_tag.get("content"):
        meta["keywords"] = kw_tag["content"].strip()[:200]

    # OG type
    og_type = soup.find("meta", property="og:type")
    if og_type and og_type.get("content"):
        meta["type"] = og_type["content"].strip()

    # OG image
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        meta["image"] = og_image["content"].strip()

    return meta


def _extract_key_links(soup, base_url: str = "") -> list[tuple[str, str]]:
    """Extract important navigation links from the page."""
    from urllib.parse import urljoin

    links = []
    seen = set()

    # Look for nav links, or top-level <a> tags
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)

        # Skip empty, anchors, javascript:
        if not text or not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        # Resolve relative URLs
        if base_url and not href.startswith(("http://", "https://")):
            href = urljoin(base_url, href)

        # Deduplicate
        if href in seen:
            continue
        seen.add(href)

        # Filter to meaningful links (skip tiny text, social icons etc.)
        if len(text) < 3 or len(text) > 80:
            continue

        links.append((text, href))

    return links[:15]  # Cap at 15 links


def _truncate_at_boundary(text: str, max_chars: int) -> str:
    """Truncate text at a paragraph boundary near max_chars."""
    if len(text) <= max_chars:
        return text

    # Find last double-newline before the limit
    cutoff = text.rfind("\n\n", 0, max_chars)
    if cutoff < max_chars * 0.5:
        # No good paragraph break — try single newline
        cutoff = text.rfind("\n", 0, max_chars)
    if cutoff < max_chars * 0.5:
        # No good break at all — hard cut
        cutoff = max_chars

    return text[:cutoff] + "\n\n*... (content truncated)*"


def _regex_fallback(html: str, url: str, max_chars: int) -> str:
    """Fallback extraction using regex only (no BS4)."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    text = text.strip()

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n... (truncated)"

    header = f"# {url}\n\n" if url else ""
    return f"{header}{text}"


def _bs4_text_only(html: str, url: str, max_chars: int) -> str:
    """Extract text using BS4 without html2text (no Markdown formatting)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    for tag_name in NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    title = _extract_title(soup)
    main = soup.find("article") or soup.find("main") or soup.find("body") or soup

    # Get paragraphs (reuse pattern from skills/web-research/actions.py)
    paragraphs = main.find_all("p")
    text_blocks = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 40]

    if text_blocks:
        text = "\n\n".join(text_blocks)
    else:
        text = main.get_text(separator="\n", strip=True)

    if len(text) > max_chars:
        text = _truncate_at_boundary(text, max_chars)

    header = f"# {title}\n**URL:** {url}\n\n" if title else (f"**URL:** {url}\n\n" if url else "")
    return f"{header}{text}"
