import requests
from typing import Dict

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Nexus/1.0"
}


def fetch_url(params: Dict) -> str:
    """Fetch and extract text content from a URL."""
    url = params.get("url", "").strip()
    if not url:
        return "Error: url is required"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if not BeautifulSoup:
        return "Error: beautifulsoup4 not installed"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove scripts and styles
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        # Collapse blank lines
        lines = [l for l in text.split("\n") if l.strip()]
        content = "\n".join(lines[:100])  # limit to ~100 lines

        title = soup.title.string if soup.title else "No title"
        return f"**{title}**\n\n{content}"
    except Exception as e:
        return f"Error fetching URL: {e}"


def search_web(params: Dict) -> str:
    """Search the web using DuckDuckGo HTML."""
    query = params.get("query", "").strip()
    num_results = int(params.get("num_results", "5"))
    if not query:
        return "Error: query is required"

    if not BeautifulSoup:
        return "Error: beautifulsoup4 not installed"

    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        for r in soup.select(".result"):
            title_el = r.select_one(".result__a")
            snippet_el = r.select_one(".result__snippet")
            if title_el:
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                results.append({"title": title, "url": href, "snippet": snippet})
            if len(results) >= num_results:
                break

        if not results:
            return f"No results found for '{query}'."

        lines = [f"**Search results for '{query}':**"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}**")
            if r["snippet"]:
                lines.append(f"   {r['snippet']}")
            if r["url"]:
                lines.append(f"   {r['url']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching: {e}"


def summarize_page(params: Dict) -> str:
    """Fetch a URL and provide a concise summary of key content."""
    url = params.get("url", "").strip()
    if not url:
        return "Error: url is required"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if not BeautifulSoup:
        return "Error: beautifulsoup4 not installed"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        title = soup.title.string if soup.title else "No title"

        # Extract main content — prefer article, main, or body
        main = soup.find("article") or soup.find("main") or soup.find("body")
        if not main:
            return f"**{title}** — Could not extract content."

        # Get paragraphs
        paragraphs = main.find_all("p")
        text_blocks = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 40]

        if not text_blocks:
            text = main.get_text(separator="\n", strip=True)[:2000]
        else:
            text = "\n\n".join(text_blocks[:10])

        return f"**{title}**\n\n{text}"
    except Exception as e:
        return f"Error summarizing: {e}"
