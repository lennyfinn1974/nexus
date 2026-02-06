# Web Scraper

Extract data from web pages using HTTP requests and HTML parsing.

## Capabilities
- Fetch HTML content from any public URL
- Extract specific elements using CSS selectors
- Get page titles and metadata
- Handle basic web scraping tasks

## Usage Examples
- scrape_url("https://example.com") - Get full page text
- scrape_url("https://example.com", "h1") - Get all h1 elements
- get_page_title("https://example.com") - Get page title

## Limitations
- JavaScript-rendered content may not be available
- Some sites block automated requests
- Respect robots.txt and rate limits
