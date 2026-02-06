"""Google Custom Search API handler."""

import logging

logger = logging.getLogger("nexus.skills.google_search")


async def google_search(params: dict) -> str:
    """Search the web using Google Custom Search API."""
    query = params.get("query", "").strip()
    num = min(int(params.get("num_results", 5)), 10)
    config = params.get("_config")

    if not query:
        return "Error: No search query provided."

    api_key = config.get("GOOGLE_API_KEY", "") if config else ""
    cse_id = config.get("GOOGLE_CSE_ID", "") if config else ""

    if not api_key or not cse_id:
        return ("Google Search not configured. "
                "Set GOOGLE_API_KEY and GOOGLE_CSE_ID in Admin > Models/Settings.")

    try:
        import httpx
    except ImportError:
        return "Error: httpx not installed. Run: pip3 install httpx"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": api_key,
                    "cx": cse_id,
                    "q": query,
                    "num": num,
                },
            )

            if resp.status_code != 200:
                error = resp.json().get("error", {}).get("message", resp.text[:200])
                return f"Google Search API error ({resp.status_code}): {error}"

            data = resp.json()
            items = data.get("items", [])

            if not items:
                return f"No results found for: {query}"

            results = []
            for i, item in enumerate(items, 1):
                title = item.get("title", "Untitled")
                snippet = item.get("snippet", "").replace("\n", " ")
                link = item.get("link", "")
                results.append(f"{i}. **{title}**\n   {snippet}\n   {link}")

            total = data.get("searchInformation", {}).get("totalResults", "?")
            header = f"Google Search: '{query}' — {total} total results\n"
            return header + "\n\n".join(results)

    except httpx.TimeoutException:
        return "Google Search timed out. Try again."
    except Exception as e:
        logger.error(f"Google search failed: {e}")
        return f"Search error: {e}"
