# Browser Automation Skill

This skill provides comprehensive browser automation capabilities for Brave or Chrome browsers using Selenium WebDriver. It allows complete keyboardless navigation and control.

## Features

### Browser Control
- Launch Brave or Chrome browser instances
- Navigate to URLs programmatically
- Manage multiple tabs and windows
- Take screenshots and capture page content
- Execute custom JavaScript

### Element Interaction
- Click buttons, links, and any clickable elements
- Fill form fields (text inputs, dropdowns, checkboxes)
- Scroll to specific elements or positions
- Find elements using various selectors (ID, class, XPath, CSS)

### Advanced Capabilities
- Handle dynamic content and wait for elements
- Interact with iframes and modal dialogs
- Manage cookies and browser storage
- Capture network requests and responses
- Handle file uploads and downloads

## Supported Browsers

### Brave Browser
- Automatic detection of Brave installation
- Supports all Chromium-based features
- Privacy-focused browsing capabilities

### Google Chrome
- Standard Chrome browser support
- Full feature compatibility
- Headless mode available

## Common Use Cases

- **Web Testing**: Automated testing of web applications
- **Data Extraction**: Scraping dynamic content that requires JavaScript
- **Form Automation**: Filling out forms and submitting data
- **Navigation**: Browsing websites programmatically
- **Content Capture**: Taking screenshots and saving page content
- **Social Media**: Interacting with social platforms
- **E-commerce**: Product research and price monitoring

## Safety Features

- Respectful crawling with configurable delays
- User-agent rotation to avoid detection
- Proper resource cleanup and browser closure
- Error handling for missing elements
- Timeout management for page loads

## Technical Details

Uses Selenium WebDriver with automatic driver management:
- ChromeDriver for Chrome/Brave compatibility
- WebDriver Manager for automatic updates
- Support for both visible and headless modes
- Cross-platform compatibility (Windows, macOS, Linux)
