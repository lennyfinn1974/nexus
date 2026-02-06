Personal Memory System for Nexus Agent"""

import sqlite3
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any
from dataclasses import dataclass

logger = logging.getLogger("nexus.memory")

@dataclass 
class UserPreference:
    key: str
    value: Any
    category: str
    confidence: float
    usage_count: int = 0
    last_used: str = ""
    created_at: str = ""

class PersonalMemorySystem:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db = None
        self._preferences_cache = {}
        
    async def initialize(self):
        self.db = sqlite3.connect(self.db_path