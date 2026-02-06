import requests
from bs4 import BeautifulSoup
from typing import Dict

def scrape_url(params: Dict) -> str:
    url = params['url']
    selector = params.get('selector', '')
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; Nexus AI Agent)'}
        response = requests.get(url