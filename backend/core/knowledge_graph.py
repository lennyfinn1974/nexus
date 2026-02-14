"""Knowledge Graph — entity and relationship extraction + graph queries.

Builds a knowledge graph from conversations and documents:
    1. Entity extraction — identifies people, projects, tools, concepts
    2. Relationship mapping — connects entities with typed edges
    3. Graph queries — find related entities for context enrichment

Storage uses PostgreSQL (knowledge_associations table already exists in
PersonalMemorySystem) + Redis for hot graph cache.

This is a lightweight, LLM-free approach using regex/NLP patterns.
For production, an LLM-based extractor can be plugged in.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("nexus.knowledge_graph")

# Entity types
ENTITY_TYPES = {
    "person",
    "project",
    "technology",
    "tool",
    "concept",
    "file",
    "url",
    "organization",
    "location",
}

# Relationship types
RELATIONSHIP_TYPES = {
    "uses",          # person USES technology
    "works_on",     # person WORKS_ON project
    "part_of",      # technology PART_OF project
    "related_to",   # concept RELATED_TO concept
    "depends_on",   # project DEPENDS_ON technology
    "created_by",   # project CREATED_BY person
    "located_at",   # file LOCATED_AT path
    "implements",   # technology IMPLEMENTS concept
    "mentioned_with",  # co-occurrence
}

# Technology keywords (expanded)
TECH_PATTERNS = {
    "languages": [
        "python", "javascript", "typescript", "rust", "go", "java", "c\\+\\+",
        "ruby", "swift", "kotlin", "scala", "php", "html", "css", "sql",
    ],
    "frameworks": [
        "react", "vue", "angular", "svelte", "next\\.js", "nuxt", "fastapi",
        "django", "flask", "express", "nest\\.js", "spring", "rails",
        "tailwind", "bootstrap", "radix",
    ],
    "tools": [
        "docker", "kubernetes", "redis", "postgresql", "postgres", "mongodb",
        "sqlite", "nginx", "vite", "webpack", "git", "github", "ollama",
        "claude", "openai", "playwright", "pytest", "npm", "pip",
        "uvicorn", "gunicorn",
    ],
    "concepts": [
        "api", "rest", "graphql", "websocket", "sse", "oauth",
        "jwt", "microservices", "clustering", "rag", "embedding",
        "vector search", "knowledge graph", "machine learning",
        "deep learning", "nlp", "llm",
    ],
}

# Person patterns (regex)
PERSON_PATTERNS = [
    r"(?:my\s+(?:colleague|friend|boss|manager|team\s*mate)\s+)(\w+)",
    r"(?:ask|tell|email|message|ping)\s+(\w+)",
    r"(\w+)\s+(?:said|mentioned|suggested|recommended|asked|told)",
]

# Project patterns
PROJECT_PATTERNS = [
    r"(?:working\s+on|building|developing|project\s+called?)\s+[\"']?(\w[\w\s-]{2,30})[\"']?",
    r"(?:the\s+)?(\w[\w-]+)\s+(?:project|app|application|service|repo|repository|codebase)",
]

# File path patterns
FILE_PATTERNS = [
    r"(?:`|\")((?:/[\w.-]+)+(?:\.\w+)?)`?\"?",
    r"(?:file|path|directory)\s+(?:`|\")?([/\w.-]+(?:\.\w+)?)",
]

# URL patterns
URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'`\])]+",
    re.IGNORECASE,
)


@dataclass
class Entity:
    """A node in the knowledge graph."""
    id: str
    name: str
    entity_type: str
    properties: dict = field(default_factory=dict)
    mention_count: int = 1
    first_seen: float = 0.0
    last_seen: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.entity_type,
            "properties": self.properties,
            "mention_count": self.mention_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


@dataclass
class Relationship:
    """An edge in the knowledge graph."""
    source_id: str
    target_id: str
    relationship_type: str
    strength: float = 1.0
    properties: dict = field(default_factory=dict)
    mention_count: int = 1

    def to_dict(self) -> dict:
        return {
            "source": self.source_id,
            "target": self.target_id,
            "type": self.relationship_type,
            "strength": self.strength,
            "properties": self.properties,
            "mention_count": self.mention_count,
        }


def _entity_id(name: str, entity_type: str) -> str:
    """Generate a stable entity ID from name + type."""
    key = f"{entity_type}:{name.lower().strip()}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _rel_id(source_id: str, target_id: str, rel_type: str) -> str:
    """Generate a stable relationship ID."""
    key = f"{source_id}:{target_id}:{rel_type}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class KnowledgeGraph:
    """In-memory knowledge graph with PostgreSQL persistence.

    Entities and relationships are held in-memory for fast queries,
    with periodic flush to PostgreSQL for durability.

    The graph is built incrementally from conversation turns
    and document ingestion.
    """

    def __init__(self, db=None, redis=None):
        """Initialize the knowledge graph.

        Args:
            db: Database instance for persistence (optional)
            redis: Redis connection for hot cache (optional)
        """
        self.db = db
        self.redis = redis

        # In-memory graph
        self._entities: dict[str, Entity] = {}
        self._relationships: dict[str, Relationship] = {}

        # Adjacency index (entity_id -> list of relationship_ids)
        self._adjacency: dict[str, list[str]] = defaultdict(list)

        # Name → entity_id index
        self._name_index: dict[str, str] = {}

        # Stats
        self._total_extractions = 0
        self._total_extract_ms = 0

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def relationship_count(self) -> int:
        return len(self._relationships)

    async def start(self) -> None:
        """Load graph from PostgreSQL if available."""
        if not self.db:
            return

        try:
            # Load from knowledge_associations table
            mem_sys = getattr(self.db, "memory_system", None)
            if not mem_sys:
                return

            # The PersonalMemorySystem already has associate_concepts()
            # We'll load existing associations into our graph
            logger.info("Knowledge graph: loading from PostgreSQL...")
            loaded = await self._load_from_db()
            logger.info(
                f"Knowledge graph loaded: {self.entity_count} entities, "
                f"{self.relationship_count} relationships (from {loaded} associations)"
            )
        except Exception as e:
            logger.warning(f"Knowledge graph load failed: {e}")

    async def _load_from_db(self) -> int:
        """Load entities and relationships from knowledge_associations table."""
        from storage.engine import get_session_factory
        from sqlalchemy import text

        count = 0
        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                result = await session.execute(
                    text("SELECT from_concept, to_concept, relationship_type, strength, source "
                         "FROM knowledge_associations WHERE strength > 0.1 ORDER BY strength DESC LIMIT 1000")
                )
                rows = result.fetchall()

                for row in rows:
                    from_name, to_name, rel_type, strength, source = row

                    # Create or update entities
                    from_entity = self._get_or_create_entity(
                        from_name, self._guess_entity_type(from_name),
                    )
                    to_entity = self._get_or_create_entity(
                        to_name, self._guess_entity_type(to_name),
                    )

                    # Create relationship
                    self._add_relationship(
                        from_entity.id, to_entity.id,
                        rel_type or "related_to",
                        strength=strength or 0.5,
                    )
                    count += 1

        except Exception as e:
            logger.debug(f"Knowledge graph DB load: {e}")

        return count

    def _guess_entity_type(self, name: str) -> str:
        """Guess entity type from name patterns."""
        name_lower = name.lower()

        # Check for URLs first (before file paths, since URLs contain /)
        if name_lower.startswith("http://") or name_lower.startswith("https://"):
            return "url"

        # Check tech patterns
        for category, patterns in TECH_PATTERNS.items():
            for pattern in patterns:
                if re.search(rf"\b{pattern}\b", name_lower):
                    if category in ("languages", "frameworks"):
                        return "technology"
                    elif category == "tools":
                        return "tool"
                    elif category == "concepts":
                        return "concept"

        # Check for file paths
        if "/" in name or ("." in name and len(name) > 5):
            return "file"

        return "concept"  # Default

    def _get_or_create_entity(
        self, name: str, entity_type: str, properties: dict = None,
    ) -> Entity:
        """Get or create an entity by name and type."""
        eid = _entity_id(name, entity_type)
        now = time.time()

        if eid in self._entities:
            entity = self._entities[eid]
            entity.mention_count += 1
            entity.last_seen = now
            if properties:
                entity.properties.update(properties)
            return entity

        entity = Entity(
            id=eid,
            name=name.strip(),
            entity_type=entity_type,
            properties=properties or {},
            mention_count=1,
            first_seen=now,
            last_seen=now,
        )
        self._entities[eid] = entity
        self._name_index[name.lower().strip()] = eid
        return entity

    def _add_relationship(
        self, source_id: str, target_id: str,
        rel_type: str, strength: float = 1.0,
        properties: dict = None,
    ) -> Relationship:
        """Add or reinforce a relationship."""
        rid = _rel_id(source_id, target_id, rel_type)

        if rid in self._relationships:
            rel = self._relationships[rid]
            rel.mention_count += 1
            # Strengthen with diminishing returns
            rel.strength = min(1.0, rel.strength + 0.1 * (1 - rel.strength))
            if properties:
                rel.properties.update(properties)
            return rel

        rel = Relationship(
            source_id=source_id,
            target_id=target_id,
            relationship_type=rel_type,
            strength=strength,
            properties=properties or {},
            mention_count=1,
        )
        self._relationships[rid] = rel
        self._adjacency[source_id].append(rid)
        self._adjacency[target_id].append(rid)
        return rel

    async def extract_and_store(
        self,
        text: str,
        source_conv: str = "",
        context: str = "",
    ) -> dict:
        """Extract entities and relationships from text and store in graph.

        Args:
            text: Text to extract from (user message + assistant response)
            source_conv: Conversation ID for provenance
            context: Additional context (e.g., conversation title)

        Returns:
            Summary of what was extracted: {entities: [], relationships: []}
        """
        start = time.time()
        extracted_entities: list[Entity] = []
        extracted_relationships: list[Relationship] = []

        try:
            # 1. Extract technology entities
            for category, patterns in TECH_PATTERNS.items():
                for pattern in patterns:
                    matches = re.finditer(
                        rf"\b({pattern})\b", text, re.IGNORECASE,
                    )
                    for match in matches:
                        name = match.group(1)
                        etype = "technology" if category in ("languages", "frameworks") else (
                            "tool" if category == "tools" else "concept"
                        )
                        entity = self._get_or_create_entity(name, etype)
                        if entity not in extracted_entities:
                            extracted_entities.append(entity)

            # 2. Extract project references
            for pattern in PROJECT_PATTERNS:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    name = match.group(1).strip()
                    if len(name) > 2 and not name.lower() in ("the", "this", "that", "our", "your"):
                        entity = self._get_or_create_entity(name, "project")
                        if entity not in extracted_entities:
                            extracted_entities.append(entity)

            # 3. Extract file paths
            for pattern in FILE_PATTERNS:
                matches = re.finditer(pattern, text)
                for match in matches:
                    path = match.group(1)
                    if len(path) > 3 and "/" in path:
                        entity = self._get_or_create_entity(path, "file")
                        if entity not in extracted_entities:
                            extracted_entities.append(entity)

            # 4. Extract URLs
            for match in URL_PATTERN.finditer(text):
                url = match.group(0).rstrip(".,;:!?)")
                entity = self._get_or_create_entity(url, "url")
                if entity not in extracted_entities:
                    extracted_entities.append(entity)

            # 5. Build relationships (co-occurrence)
            for i, e1 in enumerate(extracted_entities):
                for e2 in extracted_entities[i + 1:]:
                    rel_type = self._infer_relationship(e1, e2)
                    rel = self._add_relationship(
                        e1.id, e2.id, rel_type,
                        properties={"source": source_conv} if source_conv else {},
                    )
                    extracted_relationships.append(rel)

            # 6. Persist to PostgreSQL (fire-and-forget)
            if self.db and extracted_relationships:
                try:
                    await self._persist_to_db(extracted_entities, extracted_relationships)
                except Exception as e:
                    logger.debug(f"KG persist failed: {e}")

            self._total_extractions += 1
            self._total_extract_ms += int((time.time() - start) * 1000)

        except Exception as e:
            logger.warning(f"Knowledge graph extraction error: {e}")

        return {
            "entities": [e.to_dict() for e in extracted_entities],
            "relationships": [r.to_dict() for r in extracted_relationships],
        }

    def _infer_relationship(self, e1: Entity, e2: Entity) -> str:
        """Infer the most likely relationship type between two entities."""
        t1, t2 = e1.entity_type, e2.entity_type

        # Project + Technology → USES / DEPENDS_ON
        if t1 == "project" and t2 in ("technology", "tool"):
            return "uses"
        if t2 == "project" and t1 in ("technology", "tool"):
            return "part_of"

        # Person + Project → WORKS_ON
        if t1 == "person" and t2 == "project":
            return "works_on"
        if t2 == "person" and t1 == "project":
            return "created_by"

        # Person + Technology → USES
        if t1 == "person" and t2 in ("technology", "tool"):
            return "uses"

        # File + Project → PART_OF
        if t1 == "file" and t2 == "project":
            return "part_of"
        if t2 == "file" and t1 == "project":
            return "part_of"

        # Technology + Concept → IMPLEMENTS
        if t1 == "technology" and t2 == "concept":
            return "implements"

        return "mentioned_with"

    async def _persist_to_db(
        self, entities: list[Entity], relationships: list[Relationship],
    ) -> None:
        """Persist extracted knowledge to PostgreSQL."""
        mem_sys = getattr(self.db, "memory_system", None)
        if not mem_sys:
            return

        for rel in relationships:
            source = self._entities.get(rel.source_id)
            target = self._entities.get(rel.target_id)
            if source and target:
                try:
                    await mem_sys.associate_concepts(
                        from_concept=source.name,
                        to_concept=target.name,
                        relationship_type=rel.relationship_type,
                        source="knowledge_graph",
                    )
                except Exception:
                    pass  # Non-blocking

    async def query_related(
        self,
        text: str,
        limit: int = 10,
        max_depth: int = 2,
    ) -> str:
        """Query the knowledge graph for context related to a text.

        Finds entities mentioned in the text, then traverses their
        neighborhood in the graph to find related knowledge.

        Args:
            text: Text to find related entities for
            limit: Max entities to return
            max_depth: Max traversal depth

        Returns:
            Formatted markdown string of related knowledge
        """
        text_lower = text.lower()

        # Find directly mentioned entities
        mentioned: list[Entity] = []
        for name, eid in self._name_index.items():
            if name in text_lower and len(name) > 2:
                entity = self._entities.get(eid)
                if entity:
                    mentioned.append(entity)

        if not mentioned:
            return ""

        # BFS traversal from mentioned entities
        visited: set[str] = set()
        related_entities: list[tuple[Entity, float, str]] = []  # (entity, relevance, via_rel)

        for seed in mentioned[:5]:  # Limit seed entities
            self._bfs_traverse(
                seed.id, visited, related_entities,
                depth=0, max_depth=max_depth,
            )

        if not related_entities:
            return ""

        # Sort by relevance (higher is better)
        related_entities.sort(key=lambda x: x[1], reverse=True)
        top = related_entities[:limit]

        # Format as context
        lines: list[str] = []
        for entity, relevance, via_rel in top:
            line = f"- **{entity.name}** ({entity.entity_type})"
            if via_rel:
                line += f" — {via_rel}"
            if entity.mention_count > 1:
                line += f" (mentioned {entity.mention_count}x)"
            lines.append(line)

        if not lines:
            return ""

        return "### Related Knowledge\n" + "\n".join(lines)

    def _bfs_traverse(
        self,
        entity_id: str,
        visited: set,
        results: list,
        depth: int,
        max_depth: int,
    ) -> None:
        """BFS traversal of the knowledge graph."""
        if depth > max_depth or entity_id in visited:
            return

        visited.add(entity_id)

        for rid in self._adjacency.get(entity_id, []):
            rel = self._relationships.get(rid)
            if not rel:
                continue

            # Find the other end of the relationship
            other_id = rel.target_id if rel.source_id == entity_id else rel.source_id
            other = self._entities.get(other_id)
            if not other or other.id in visited:
                continue

            # Relevance decays with depth
            relevance = rel.strength * (0.7 ** depth)

            # Build human-readable relationship description
            source_entity = self._entities.get(rel.source_id)
            via = ""
            if source_entity and source_entity.id == entity_id:
                via = f"{rel.relationship_type} {other.name}"
            else:
                via = f"{source_entity.name if source_entity else '?'} {rel.relationship_type} this"

            results.append((other, relevance, via))

            # Recurse
            self._bfs_traverse(other.id, visited, results, depth + 1, max_depth)

    def get_entity(self, name: str) -> Optional[Entity]:
        """Look up an entity by name."""
        eid = self._name_index.get(name.lower().strip())
        if eid:
            return self._entities.get(eid)
        return None

    def get_neighbors(self, entity_id: str) -> list[dict]:
        """Get all entities connected to a given entity."""
        neighbors: list[dict] = []
        for rid in self._adjacency.get(entity_id, []):
            rel = self._relationships.get(rid)
            if not rel:
                continue
            other_id = rel.target_id if rel.source_id == entity_id else rel.source_id
            other = self._entities.get(other_id)
            if other:
                neighbors.append({
                    "entity": other.to_dict(),
                    "relationship": rel.to_dict(),
                })
        return neighbors

    def get_stats(self) -> dict:
        """Get knowledge graph statistics."""
        type_counts: dict[str, int] = defaultdict(int)
        for e in self._entities.values():
            type_counts[e.entity_type] += 1

        rel_type_counts: dict[str, int] = defaultdict(int)
        for r in self._relationships.values():
            rel_type_counts[r.relationship_type] += 1

        avg_extract = (
            self._total_extract_ms / self._total_extractions
            if self._total_extractions > 0
            else 0
        )

        return {
            "total_entities": self.entity_count,
            "total_relationships": self.relationship_count,
            "entity_types": dict(type_counts),
            "relationship_types": dict(rel_type_counts),
            "total_extractions": self._total_extractions,
            "avg_extract_ms": round(avg_extract, 1),
        }

    def export_graph(self, max_entities: int = 200) -> dict:
        """Export graph data for visualization.

        Returns a format suitable for D3.js or similar graph viz.
        """
        # Get top entities by mention count
        entities = sorted(
            self._entities.values(),
            key=lambda e: e.mention_count,
            reverse=True,
        )[:max_entities]

        entity_ids = {e.id for e in entities}

        # Get relationships between these entities
        rels = [
            r for r in self._relationships.values()
            if r.source_id in entity_ids and r.target_id in entity_ids
        ]

        return {
            "nodes": [e.to_dict() for e in entities],
            "links": [r.to_dict() for r in rels],
        }
