import requests
from bs4 import BeautifulSoup
from typing import Dict, Optional

def scrape_url(url: str, selector: Optional[str] = None) -> Dict:
    \"\"\"Scrape content from a URL.
    
    Args:
        url: URL to scrape
        selector: Optional CSS selector to extract specific content
    
    Returns:
        Dict with scraped content
    \"\"\"
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Nexus AI Agent)'
        }
        
        response = requests.get(url