import time
import json
from typing import Dict, List, Optional, Any, Union
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException,
    ElementNotInteractableException, StaleElementReferenceException
)
from webdriver_manager.chrome import ChromeDriverManager
import os
import platform

class BrowserAutomation:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.default_timeout = 10
        
    def _get_browser_executable_path(self, browser: str = "chrome") -> Optional[str]:
        \"\"\"Find the executable path for Chrome or Brave browser.\"\"\"
        system = platform.system().lower()
        browser = browser.lower()
        
        paths = []
        
        if browser == "brave":
            if system == "darwin":  # macOS
                paths = [
                    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                    "/Applications/Brave Browser Beta.app/Contents/MacOS/Brave Browser Beta",
                    "/Applications/Brave Browser Dev.app/Contents/MacOS/Brave Browser Dev"
                ]
            elif system == "windows":
                paths = [
                    r"C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
                    r"C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
                    r"C:\\Users\\%USERNAME%\\AppData\\Local\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"
                ]
            elif system == "linux":
                paths = [
                    "/usr/bin/brave-browser",
                    "/usr/bin/brave",
                    "/opt/brave.com/brave/brave-browser"
                ]
        else:  # chrome
            if system == "darwin":  # macOS
                paths = [
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                ]
            elif system == "windows":
                paths = [
                    r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                    r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
                ]
            elif system == "linux":
                paths = [
                    "/usr/bin/google-chrome",
                    "/usr/bin/chromium-browser",
                    "/usr/bin/chromium"
                ]
        
        for path in paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def _setup_driver_options(self, browser: str = "chrome", headless: bool = False, 
                            window_size: tuple = (1920, 1080)) -> Options:
        \"\"\"Setup Chrome/Brave driver options.\"\"\"
        options = Options()
        
        # Find browser executable
        browser_path = self._get_browser_executable_path(browser)
        if browser_path:
            options.binary_location = browser_path
        
        # Basic options
        if headless:
            options.add_argument("--headless")
        
        options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-web-security")
        options.add_argument("--disable-features=VizDisplayCompositor")
        
        # User agent
        options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # Disable notifications and popups
        prefs = {
            "profile.default_content_setting_values.notifications": 2,
            "profile.default_content_settings.popups": 0,
            "profile.managed_default_content_settings.images": 2  # Don't load images for faster browsing
        }
        options.add_experimental_option("prefs", prefs)
        
        return options
    
    def launch_browser(self, browser: str = "chrome", headless: bool = False, 
                      window_size: tuple = (1920, 1080)) -> Dict:
        \"\"\"Launch a browser instance.\"\"\"
        try:
            if self.driver:
                self.close_browser()
            
            options = self._setup_driver_options(browser, headless, window_size)
            
            # Setup service with automatic driver management
            service = Service(ChromeDriverManager().install())
            
            # Create driver
            self.driver = webdriver.Chrome(service=service