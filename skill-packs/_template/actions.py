"""Action handlers for My Skill.

Each function listed in skill.yaml 'actions' section needs a matching
async function here.  The function receives a dict of parameters
(plus _config for accessing Nexus settings).

Return a string with the result.
"""

import logging

logger = logging.getLogger("nexus.skills.my_skill")


async def my_skill_search(params: dict) -> str:
    """Search My Service."""
    query = params.get("query", "")
    limit = int(params.get("limit", 5))
    config = params.get("_config")

    # Read config values set in admin
    api_key = config.get("MY_API_KEY", "") if config else ""
    endpoint = config.get("MY_ENDPOINT", "https://api.example.com") if config else ""

    if not api_key:
        return "Error: MY_API_KEY not configured. Set it in Admin > Settings."

    # Your API call goes here
    # Example:
    # import httpx
    # async with httpx.AsyncClient() as client:
    #     resp = await client.get(
    #         f"{endpoint}/search",
    #         params={"q": query, "limit": limit},
    #         headers={"Authorization": f"Bearer {api_key}"},
    #     )
    #     data = resp.json()
    #     return format_results(data)

    return f"[Template] Would search for: '{query}' (limit: {limit})"
