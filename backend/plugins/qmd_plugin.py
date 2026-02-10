"""QMD Plugin — Document search and indexing using qmd CLI.

This plugin integrates the qmd (Quick Markdown Documentation) tool to provide:
- Semantic document search across indexed collections
- Document retrieval by path or ID
- Document indexing for new content
- Collection management

The qmd CLI must be installed at /Users/lennyfinn/.bun/bin/qmd
"""

import asyncio
import json
import logging
import os
import shutil
from typing import Any, Dict

from plugins.base import NexusPlugin

logger = logging.getLogger("nexus.plugins.qmd")

QMD_PATH = "/Users/lennyfinn/.bun/bin/qmd"
MAX_EXEC_TIME = 30  # seconds


class QMDPlugin(NexusPlugin):
    name = "qmd"
    description = "Document search and indexing using qmd CLI for semantic documentation retrieval"
    version = "1.0.0"

    def __init__(self, config, db, router):
        super().__init__(config, db, router)
        self.qmd_available = False
        self.qmd_path = QMD_PATH

    async def setup(self) -> bool:
        """Verify qmd is installed and available."""
        # Check if qmd exists at the specified path
        if os.path.exists(self.qmd_path) and os.access(self.qmd_path, os.X_OK):
            self.qmd_available = True
            logger.info(f"  QMD found at: {self.qmd_path}")
            return True

        # Try to find it in PATH as fallback
        qmd_in_path = shutil.which("qmd")
        if qmd_in_path:
            self.qmd_path = qmd_in_path
            self.qmd_available = True
            logger.info(f"  QMD found in PATH: {self.qmd_path}")
            return True

        logger.warning(f"qmd not found at {QMD_PATH} or in PATH. QMD plugin disabled.")
        self.enabled = False
        return False

    def register_tools(self) -> None:
        """Register document search and indexing tools."""
        self.add_tool(
            "doc_search",
            "Search indexed documents for relevant information. Use when you need to find documentation, code examples, or technical information.",
            {
                "query": "Search query for semantic document search",
                "collection": "Optional: specific collection to search (default: all)",
                "limit": "Maximum number of results (default: 5)",
            },
            self._doc_search,
        )

        self.add_tool(
            "doc_get",
            "Retrieve a specific document by its path or document ID.",
            {"path_or_docid": "Document path or ID to retrieve"},
            self._doc_get,
        )

        self.add_tool(
            "doc_index",
            "Index a document or directory for semantic search. Use to add new documentation to the searchable corpus.",
            {
                "path": "File or directory path to index",
                "name": "Optional: collection name (default: uses path basename)",
            },
            self._doc_index,
        )

        self.add_tool(
            "doc_list_collections",
            "List all indexed document collections.",
            {},
            self._doc_list_collections,
        )

    def register_commands(self) -> None:
        """Register slash commands."""
        self.add_command(
            "search",
            "Search indexed documents: /search <query>",
            self._handle_search,
        )

        self.add_command(
            "index",
            "Index a document or directory: /index <path> [collection_name]",
            self._handle_index,
        )

    # ────────────────────────────────────────────
    # QMD Execution Helper
    # ────────────────────────────────────────────

    async def _run_qmd(self, args: list[str]) -> Dict[str, Any]:
        """Execute qmd with --json flag and parse the result."""
        if not self.qmd_available:
            return {"error": "QMD not available"}

        try:
            # Always add --json flag for structured output
            cmd_args = [self.qmd_path, "--json"] + args

            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=MAX_EXEC_TIME
                )
            except asyncio.TimeoutError:
                proc.kill()
                return {"error": f"QMD command timed out after {MAX_EXEC_TIME}s"}

            if proc.returncode != 0:
                error_msg = stderr.decode(errors="replace").strip()
                return {"error": f"QMD command failed: {error_msg}"}

            # Parse JSON output
            output = stdout.decode(errors="replace").strip()
            if not output:
                return {"error": "No output from QMD"}

            try:
                return json.loads(output)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse QMD JSON output: {e}")
                return {"error": f"Invalid JSON from QMD: {output[:200]}"}

        except Exception as e:
            logger.error(f"QMD execution failed: {e}")
            return {"error": str(e)}

    # ────────────────────────────────────────────
    # Tool Handlers
    # ────────────────────────────────────────────

    async def _doc_search(self, params: Dict[str, Any]) -> str:
        """Search for documents."""
        if not self.enabled:
            return "❌ QMD plugin not available"

        query = params.get("query", "").strip()
        if not query:
            return "Error: query parameter required"

        collection = params.get("collection", "").strip()
        limit = int(params.get("limit", 5))

        # Build qmd search command
        args = ["search", query, "--limit", str(limit)]
        if collection:
            args.extend(["--collection", collection])

        result = await self._run_qmd(args)

        if "error" in result:
            return f"❌ {result['error']}"

        # Parse search results
        results = result.get("results", [])
        if not results:
            return f"No documents found for: {query}"

        lines = [f"🔍 **Found {len(results)} documents:**\n"]
        for i, doc in enumerate(results, 1):
            title = doc.get("title", doc.get("path", "Untitled"))
            path = doc.get("path", "")
            score = doc.get("score", 0)
            snippet = doc.get("snippet", doc.get("content", ""))[:200]

            lines.append(f"{i}. **{title}** (relevance: {score:.2f})")
            if path:
                lines.append(f"   Path: `{path}`")
            if snippet:
                lines.append(f"   {snippet}...")
            lines.append("")

        return "\n".join(lines)

    async def _doc_get(self, params: Dict[str, Any]) -> str:
        """Retrieve a specific document."""
        if not self.enabled:
            return "❌ QMD plugin not available"

        path_or_docid = params.get("path_or_docid", "").strip()
        if not path_or_docid:
            return "Error: path_or_docid parameter required"

        # Build qmd get command
        args = ["get", path_or_docid]

        result = await self._run_qmd(args)

        if "error" in result:
            return f"❌ {result['error']}"

        # Parse document
        title = result.get("title", "Untitled")
        path = result.get("path", path_or_docid)
        content = result.get("content", "")
        metadata = result.get("metadata", {})

        lines = [
            f"📄 **{title}**",
            f"Path: `{path}`",
        ]

        if metadata:
            lines.append(f"Metadata: {json.dumps(metadata, indent=2)}")

        lines.append("\n---\n")
        lines.append(content)

        return "\n".join(lines)

    async def _doc_index(self, params: Dict[str, Any]) -> str:
        """Index a document or directory."""
        if not self.enabled:
            return "❌ QMD plugin not available"

        path = params.get("path", "").strip()
        if not path:
            return "Error: path parameter required"

        name = params.get("name", "").strip()

        # Build qmd index command
        args = ["index", path]
        if name:
            args.extend(["--name", name])

        result = await self._run_qmd(args)

        if "error" in result:
            return f"❌ {result['error']}"

        # Parse indexing result
        indexed_count = result.get("indexed", 0)
        collection = result.get("collection", name or os.path.basename(path))
        errors = result.get("errors", [])

        lines = [f"✅ Indexed {indexed_count} documents"]
        lines.append(f"Collection: **{collection}**")

        if errors:
            lines.append(f"\n⚠️  {len(errors)} errors:")
            for error in errors[:5]:  # Show first 5 errors
                lines.append(f"  - {error}")
            if len(errors) > 5:
                lines.append(f"  ... and {len(errors) - 5} more")

        return "\n".join(lines)

    async def _doc_list_collections(self, params: Dict[str, Any]) -> str:
        """List all indexed collections."""
        if not self.enabled:
            return "❌ QMD plugin not available"

        # Build qmd list command
        args = ["list"]

        result = await self._run_qmd(args)

        if "error" in result:
            return f"❌ {result['error']}"

        # Parse collections
        collections = result.get("collections", [])
        if not collections:
            return "No collections indexed yet."

        lines = [f"📚 **Indexed Collections ({len(collections)} total):**\n"]
        for i, collection in enumerate(collections, 1):
            name = collection.get("name", "Unknown")
            doc_count = collection.get("documents", 0)
            path = collection.get("path", "")

            lines.append(f"{i}. **{name}** ({doc_count} documents)")
            if path:
                lines.append(f"   Path: `{path}`")
            lines.append("")

        return "\n".join(lines)

    # ────────────────────────────────────────────
    # Slash Command Handlers
    # ────────────────────────────────────────────

    async def _handle_search(self, args: str) -> str:
        """Handle /search command."""
        if not args.strip():
            return "Usage: `/search <query>`"

        parts = args.strip().split(None, 1)
        query = parts[0] if parts else ""

        if not query:
            return "Usage: `/search <query>`"

        return await self._doc_search({"query": query})

    async def _handle_index(self, args: str) -> str:
        """Handle /index command."""
        if not args.strip():
            return "Usage: `/index <path> [collection_name]`"

        parts = args.strip().split(None, 1)
        path = parts[0] if parts else ""
        name = parts[1] if len(parts) > 1 else ""

        if not path:
            return "Usage: `/index <path> [collection_name]`"

        return await self._doc_index({"path": path, "name": name})

    # ────────────────────────────────────────────
    # System Prompt Integration
    # ────────────────────────────────────────────

    def get_system_prompt_addition(self) -> str:
        """Add QMD tool information to system prompt."""
        if not self.enabled:
            return ""

        return (
            "\n## 📚 Document Search (QMD)\n"
            "You have access to semantic document search via the qmd tool.\n"
            "Use `doc_search` to find relevant documentation, code examples, or technical information.\n"
            "Use `doc_index` to add new documentation to the searchable corpus.\n"
        )
