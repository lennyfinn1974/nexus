"""Mem0 Plugin — Long-term memory management using mem0.ai.

This plugin integrates mem0.ai's memory service to provide persistent,
semantic memory storage and retrieval across conversations. The AI can:
- Store important information, preferences, and facts
- Search for relevant memories based on context
- List and manage stored memories
- Forget specific memories when needed

Memories are automatically injected into the system prompt when relevant.
"""

import logging
from typing import Any, Dict

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.mem0")

try:
    from mem0 import MemoryClient
    MEM0_AVAILABLE = True
except ImportError:
    MEM0_AVAILABLE = False
    logger.warning("mem0 package not available. Install with: pip install mem0ai")


class Mem0Plugin(NexusPlugin):
    name = "mem0"
    description = "Long-term memory management using mem0.ai for persistent context across conversations"
    version = "1.0.0"

    def __init__(self, config, db, router):
        super().__init__(config, db, router)
        self.client = None
        self.user_id = None

    async def setup(self) -> bool:
        """Initialize the mem0 client."""
        if not MEM0_AVAILABLE:
            logger.error("Mem0 plugin disabled: mem0ai package not installed")
            self.enabled = False
            return False

        api_key = self.config.get("MEM0_API_KEY")
        if not api_key:
            logger.warning("MEM0_API_KEY not configured. Mem0 plugin disabled.")
            self.enabled = False
            return False

        try:
            self.client = MemoryClient(api_key=api_key)
            self.user_id = self.config.get("MEM0_USER_ID", "default")
            logger.info(f"  Mem0 initialized for user: {self.user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Mem0 client: {e}")
            self.enabled = False
            return False

    def register_tools(self) -> None:
        """Register memory management tools."""
        self.add_tool(
            "memory_search",
            "Search stored memories for relevant information. Use when you need to recall past conversations, user preferences, or stored facts.",
            {
                "query": "Search query to find relevant memories",
                "limit": "Maximum number of results (default: 5)",
            },
            self._memory_search,
        )

        self.add_tool(
            "memory_store",
            "Store new information in long-term memory. Use when the user shares important facts, preferences, or context worth remembering.",
            {
                "text": "Information to store in memory",
                "metadata": "Optional metadata as JSON string (e.g., category, tags)",
            },
            self._memory_store,
        )

        self.add_tool(
            "memory_list",
            "List all stored memories. Use to review what has been remembered.",
            {},
            self._memory_list,
        )

        self.add_tool(
            "memory_get",
            "Retrieve a specific memory by its ID.",
            {"memory_id": "The ID of the memory to retrieve"},
            self._memory_get,
        )

        self.add_tool(
            "memory_forget",
            "Delete a specific memory by its ID. Use when information is outdated or the user requests deletion.",
            {"memory_id": "The ID of the memory to delete"},
            self._memory_forget,
        )

    def register_commands(self) -> None:
        """Register slash commands."""
        self.add_command(
            "remember",
            "Store information in long-term memory: /remember <text>",
            self._handle_remember,
        )

        self.add_command(
            "memories",
            "List all stored memories",
            self._handle_memories,
        )

        self.add_command(
            "forget",
            "Delete a memory by ID: /forget <memory_id>",
            self._handle_forget,
        )

    # ────────────────────────────────────────────
    # Tool Handlers
    # ────────────────────────────────────────────

    async def _memory_search(self, params: Dict[str, Any]) -> str:
        """Search for relevant memories."""
        if not self.enabled or not self.client:
            return "❌ Mem0 plugin not available"

        query = params.get("query", "").strip()
        if not query:
            return "Error: query parameter required"

        limit = int(params.get("limit", 5))

        try:
            # Mem0 API v2 requires filters parameter
            results = self.client.search(
                query=query,
                user_id=self.user_id,
                limit=limit,
                filters={"user_id": self.user_id}  # Required by v2 API
            )

            # Handle v1.1 format: {"results": [...]}
            if isinstance(results, dict) and "results" in results:
                results = results["results"]

            if not results or len(results) == 0:
                return f"No memories found for: {query}"

            lines = [f"🔍 **Found {len(results)} relevant memories:**\n"]
            for i, memory in enumerate(results, 1):
                memory_id = memory.get("id", "unknown")
                text = memory.get("memory", memory.get("text", ""))
                score = memory.get("score", 0)
                lines.append(f"{i}. **[{memory_id}]** (relevance: {score:.2f})")
                lines.append(f"   {text}")
                lines.append("")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            return f"Error searching memories: {e}"

    async def _memory_store(self, params: Dict[str, Any]) -> str:
        """Store new memory."""
        if not self.enabled or not self.client:
            return "❌ Mem0 plugin not available"

        text = params.get("text", "").strip()
        if not text:
            return "Error: text parameter required"

        metadata_str = params.get("metadata", "")
        metadata = {}
        if metadata_str:
            try:
                import json
                metadata = json.loads(metadata_str)
            except json.JSONDecodeError:
                return "Error: metadata must be valid JSON"

        try:
            result = self.client.add(
                messages=[{"role": "user", "content": text}],
                user_id=self.user_id,
                metadata=metadata if metadata else None,
            )

            memory_id = result.get("id", "unknown") if isinstance(result, dict) else "unknown"
            return f"✅ Memory stored (ID: {memory_id})\n{text}"
        except Exception as e:
            logger.error(f"Memory store failed: {e}")
            return f"Error storing memory: {e}"

    async def _memory_list(self, params: Dict[str, Any]) -> str:
        """List all memories."""
        if not self.enabled or not self.client:
            return "❌ Mem0 plugin not available"

        try:
            # Mem0 API v2 requires filters parameter
            memories = self.client.get_all(
                user_id=self.user_id,
                filters={"user_id": self.user_id}  # Required by v2 API
            )

            if not memories or len(memories) == 0:
                return "No memories stored yet."

            lines = [f"📚 **All Memories ({len(memories)} total):**\n"]
            for i, memory in enumerate(memories, 1):
                memory_id = memory.get("id", "unknown")
                text = memory.get("memory", memory.get("text", ""))
                created = memory.get("created_at", "")
                lines.append(f"{i}. **[{memory_id}]** {created}")
                lines.append(f"   {text}")
                lines.append("")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Memory list failed: {e}")
            return f"Error listing memories: {e}"

    async def _memory_get(self, params: Dict[str, Any]) -> str:
        """Get a specific memory by ID."""
        if not self.enabled or not self.client:
            return "❌ Mem0 plugin not available"

        memory_id = params.get("memory_id", "").strip()
        if not memory_id:
            return "Error: memory_id parameter required"

        try:
            memory = self.client.get(memory_id=memory_id)

            if not memory:
                return f"Memory not found: {memory_id}"

            text = memory.get("memory", memory.get("text", ""))
            created = memory.get("created_at", "")
            metadata = memory.get("metadata", {})

            lines = [
                f"📝 **Memory {memory_id}**",
                f"Created: {created}",
                f"Content: {text}",
            ]
            if metadata:
                lines.append(f"Metadata: {metadata}")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Memory get failed: {e}")
            return f"Error retrieving memory: {e}"

    async def _memory_forget(self, params: Dict[str, Any]) -> str:
        """Delete a memory by ID."""
        if not self.enabled or not self.client:
            return "❌ Mem0 plugin not available"

        memory_id = params.get("memory_id", "").strip()
        if not memory_id:
            return "Error: memory_id parameter required"

        try:
            self.client.delete(memory_id=memory_id)
            return f"✅ Memory {memory_id} deleted"
        except Exception as e:
            logger.error(f"Memory delete failed: {e}")
            return f"Error deleting memory: {e}"

    # ────────────────────────────────────────────
    # Slash Command Handlers
    # ────────────────────────────────────────────

    async def _handle_remember(self, args: str) -> str:
        """Handle /remember command."""
        if not args.strip():
            return "Usage: `/remember <text to remember>`"
        return await self._memory_store({"text": args.strip()})

    async def _handle_memories(self, args: str) -> str:
        """Handle /memories command."""
        return await self._memory_list({})

    async def _handle_forget(self, args: str) -> str:
        """Handle /forget command."""
        memory_id = args.strip()
        if not memory_id:
            return "Usage: `/forget <memory_id>`"
        return await self._memory_forget({"memory_id": memory_id})

    # ────────────────────────────────────────────
    # System Prompt Integration
    # ────────────────────────────────────────────

    def get_system_prompt_addition(self) -> str:
        """Inject relevant memories into the system prompt."""
        if not self.enabled or not self.client:
            return ""

        try:
            # Search for recent or general context
            # This is a simple implementation - you might want to search based on current context
            memories = self.client.get_all(
                user_id=self.user_id,
                filters={"user_id": self.user_id}  # Required by v2 API
            )

            # Handle different response formats from mem0 API
            if isinstance(memories, dict) and "results" in memories:
                memories = memories["results"]

            # Ensure memories is a list
            if not isinstance(memories, list):
                logger.warning(f"Unexpected memories type: {type(memories)}")
                return ""

            if not memories or len(memories) == 0:
                return ""

            lines = ["\n## 🧠 Long-Term Memory"]
            lines.append("You have access to these stored memories from past conversations:\n")

            # Show up to 10 most recent memories
            recent_memories = memories[:10] if len(memories) > 10 else memories
            for memory in recent_memories:
                if isinstance(memory, dict):
                    text = memory.get("memory", memory.get("text", ""))
                    if text:
                        lines.append(f"- {text}")

            lines.append("\nUse memory_search to find specific information, or memory_store to remember new facts.")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Failed to load memories for system prompt: {e}")
            return ""
