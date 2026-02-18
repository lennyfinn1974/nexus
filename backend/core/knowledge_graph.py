"""Knowledge Graph — entity and relationship extraction + graph queries.

Builds a knowledge graph from conversations and documents:
    1. Entity extraction — identifies people, projects, tools, concepts
    2. Relationship mapping — connects entities with typed edges
    3. Graph queries — find related entities for context enrichment
    4. Temporal reasoning — Contradicts edges track superseded facts
    5. PostgreSQL persistence — proper KG tables (kg_entities, kg_relationships)

Storage: In-memory graph for fast BFS queries, backed by PostgreSQL for
durability. Loaded on startup, saved periodically.

Spacebot-inspired enhancements (Feb 2026):
    - Contradicts relationship type for temporal supersession
    - Typed entity properties with merge semantics
    - Temporal validity (valid_from/valid_until) on relationships
    - Importance scoring on entities (access frequency, recency, centrality)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("nexus.knowledge_graph")

# ── Entity types ──────────────────────────────────────────────────

ENTITY_TYPES = {
    "person", "project", "technology", "tool", "concept",
    "file", "url", "organization", "location",
}

# ── Relationship types (expanded with Contradicts) ────────────────

RELATIONSHIP_TYPES = {
    "uses",              # person USES technology
    "works_on",          # person WORKS_ON project
    "part_of",           # technology PART_OF project
    "related_to",        # concept RELATED_TO concept
    "depends_on",        # project DEPENDS_ON technology
    "created_by",        # project CREATED_BY person
    "located_at",        # file LOCATED_AT path
    "implements",        # technology IMPLEMENTS concept
    "mentioned_with",    # co-occurrence
    "contradicts",       # NEW: fact A CONTRADICTS fact B (temporal supersession)
    "updates",           # NEW: fact A UPDATES fact B (refinement)
    "caused_by",         # NEW: event CAUSED_BY event
}

# ── Technology patterns ───────────────────────────────────────────

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
    importance: float = 0.0  # Computed: access_freq * recency * type_weight

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.entity_type,
            "properties": self.properties,
            "mention_count": self.mention_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "importance": round(self.importance, 3),
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
    valid_from: float = 0.0       # Unix timestamp, 0 = always valid
    valid_until: float = 0.0      # Unix timestamp, 0 = still valid
    superseded_by: str = ""       # Contradicts: ID of the newer relationship
    first_seen: float = 0.0
    last_seen: float = 0.0

    @property
    def is_current(self) -> bool:
        """Check if this relationship is still temporally valid."""
        if self.superseded_by:
            return False
        if self.valid_until > 0 and self.valid_until < time.time():
            return False
        return True

    def to_dict(self) -> dict:
        d = {
            "source": self.source_id,
            "target": self.target_id,
            "type": self.relationship_type,
            "strength": self.strength,
            "properties": self.properties,
            "mention_count": self.mention_count,
            "is_current": self.is_current,
        }
        if self.superseded_by:
            d["superseded_by"] = self.superseded_by
        if self.valid_from:
            d["valid_from"] = self.valid_from
        if self.valid_until:
            d["valid_until"] = self.valid_until
        return d


# ── Importance scoring weights ────────────────────────────────────

ENTITY_TYPE_WEIGHTS = {
    "person": 1.5,
    "project": 1.4,
    "organization": 1.3,
    "technology": 1.2,
    "tool": 1.1,
    "concept": 1.0,
    "file": 0.8,
    "url": 0.7,
    "location": 0.9,
}

IMPORTANCE_HALF_LIFE_DAYS = 30  # Recency weight halves every 30 days


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

    Spacebot-inspired features:
        - Contradicts edges for temporal supersession
        - Importance scoring (access * recency * type_weight * centrality)
        - Entity properties with merge semantics
        - Temporal validity on relationships
    """

    def __init__(self, db=None, redis=None):
        self.db = db
        self.redis = redis

        # In-memory graph
        self._entities: dict[str, Entity] = {}
        self._relationships: dict[str, Relationship] = {}
        self._adjacency: dict[str, list[str]] = defaultdict(list)
        self._name_index: dict[str, str] = {}

        # Dirty tracking for persistence
        self._dirty_entities: set[str] = set()
        self._dirty_relationships: set[str] = set()
        self._last_save_time: float = 0

        # Stats
        self._total_extractions = 0
        self._total_extract_ms = 0

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def relationship_count(self) -> int:
        return len(self._relationships)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Load graph from PostgreSQL if available."""
        if not self.db:
            return

        try:
            logger.info("Knowledge graph: loading from PostgreSQL...")
            loaded = await self._load_from_db()
            # Compute importance for all loaded entities
            self._recompute_all_importance()
            logger.info(
                f"Knowledge graph loaded: {self.entity_count} entities, "
                f"{self.relationship_count} relationships (from {loaded} rows)"
            )
        except Exception as e:
            logger.warning(f"Knowledge graph load failed: {e}")

    async def _load_from_db(self) -> int:
        """Load entities and relationships from dedicated KG tables.

        Falls back to legacy knowledge_associations table if KG tables are empty.
        """
        from storage.engine import get_session_factory
        from sqlalchemy import text

        count = 0
        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                # Try new KG tables first
                try:
                    result = await session.execute(
                        text("SELECT id, name, entity_type, properties, mention_count, "
                             "EXTRACT(EPOCH FROM first_seen), EXTRACT(EPOCH FROM last_seen) "
                             "FROM kg_entities ORDER BY mention_count DESC LIMIT 2000")
                    )
                    entity_rows = result.fetchall()
                except Exception:
                    entity_rows = []

                if entity_rows:
                    # Load from new tables
                    for row in entity_rows:
                        eid, name, etype, props, mentions, first_s, last_s = row
                        entity = Entity(
                            id=eid, name=name, entity_type=etype,
                            properties=props or {},
                            mention_count=mentions or 1,
                            first_seen=float(first_s or 0),
                            last_seen=float(last_s or 0),
                        )
                        self._entities[eid] = entity
                        self._name_index[name.lower().strip()] = eid
                        count += 1

                    # Load relationships
                    try:
                        result = await session.execute(
                            text("SELECT id, from_entity_id, to_entity_id, rel_type, properties, "
                                 "strength, mention_count, "
                                 "EXTRACT(EPOCH FROM valid_from), EXTRACT(EPOCH FROM valid_until), "
                                 "superseded_by, "
                                 "EXTRACT(EPOCH FROM first_seen), EXTRACT(EPOCH FROM last_seen) "
                                 "FROM kg_relationships ORDER BY strength DESC LIMIT 5000")
                        )
                        rel_rows = result.fetchall()
                        for row in rel_rows:
                            rid, from_id, to_id, rtype, props, strength, mentions, \
                                valid_f, valid_u, superseded, first_s, last_s = row
                            rel = Relationship(
                                source_id=from_id, target_id=to_id,
                                relationship_type=rtype,
                                strength=float(strength or 0.5),
                                properties=props or {},
                                mention_count=mentions or 1,
                                valid_from=float(valid_f or 0),
                                valid_until=float(valid_u or 0),
                                superseded_by=superseded or "",
                                first_seen=float(first_s or 0),
                                last_seen=float(last_s or 0),
                            )
                            self._relationships[rid] = rel
                            self._adjacency[from_id].append(rid)
                            self._adjacency[to_id].append(rid)
                            count += 1
                    except Exception as e:
                        logger.debug(f"KG relationships load: {e}")

                else:
                    # Fall back to legacy knowledge_associations table
                    result = await session.execute(
                        text("SELECT from_concept, to_concept, relationship_type, strength, created_from "
                             "FROM knowledge_associations WHERE strength > 0.1 "
                             "ORDER BY strength DESC LIMIT 1000")
                    )
                    rows = result.fetchall()

                    for row in rows:
                        from_name, to_name, rel_type, strength, source = row
                        from_entity = self._get_or_create_entity(
                            from_name, self._guess_entity_type(from_name),
                        )
                        to_entity = self._get_or_create_entity(
                            to_name, self._guess_entity_type(to_name),
                        )
                        self._add_relationship(
                            from_entity.id, to_entity.id,
                            rel_type or "related_to",
                            strength=strength or 0.5,
                        )
                        count += 1

        except Exception as e:
            logger.debug(f"Knowledge graph DB load: {e}")

        return count

    async def save_to_db(self) -> int:
        """Persist dirty entities and relationships to PostgreSQL.

        Only saves items marked as dirty since the last save.
        Returns total items saved.
        """
        if not self._dirty_entities and not self._dirty_relationships:
            return 0

        from storage.engine import get_session_factory
        from sqlalchemy import text

        saved = 0
        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                # Save dirty entities
                for eid in list(self._dirty_entities):
                    entity = self._entities.get(eid)
                    if not entity:
                        continue
                    await session.execute(
                        text("""
                            INSERT INTO kg_entities (id, name, entity_type, properties,
                                mention_count, first_seen, last_seen)
                            VALUES (:id, :name, :etype, :props, :mentions,
                                TO_TIMESTAMP(:first_seen), TO_TIMESTAMP(:last_seen))
                            ON CONFLICT (id) DO UPDATE SET
                                properties = COALESCE(kg_entities.properties, '{}'::jsonb) || :props,
                                mention_count = :mentions,
                                last_seen = TO_TIMESTAMP(:last_seen)
                        """),
                        {
                            "id": entity.id, "name": entity.name,
                            "etype": entity.entity_type,
                            "props": json.dumps(entity.properties),
                            "mentions": entity.mention_count,
                            "first_seen": entity.first_seen,
                            "last_seen": entity.last_seen,
                        },
                    )
                    saved += 1

                # Save dirty relationships
                for rid in list(self._dirty_relationships):
                    rel = self._relationships.get(rid)
                    if not rel:
                        continue
                    await session.execute(
                        text("""
                            INSERT INTO kg_relationships (id, from_entity_id, to_entity_id,
                                rel_type, properties, strength, mention_count,
                                valid_from, valid_until, superseded_by, first_seen, last_seen)
                            VALUES (:id, :from_id, :to_id, :rtype, :props, :strength, :mentions,
                                CASE WHEN :valid_from > 0 THEN TO_TIMESTAMP(:valid_from) ELSE NULL END,
                                CASE WHEN :valid_until > 0 THEN TO_TIMESTAMP(:valid_until) ELSE NULL END,
                                NULLIF(:superseded, ''),
                                TO_TIMESTAMP(:first_seen), TO_TIMESTAMP(:last_seen))
                            ON CONFLICT (id) DO UPDATE SET
                                properties = COALESCE(kg_relationships.properties, '{}'::jsonb) || :props,
                                strength = :strength,
                                mention_count = :mentions,
                                valid_until = CASE WHEN :valid_until > 0 THEN TO_TIMESTAMP(:valid_until) ELSE kg_relationships.valid_until END,
                                superseded_by = COALESCE(NULLIF(:superseded, ''), kg_relationships.superseded_by),
                                last_seen = TO_TIMESTAMP(:last_seen)
                        """),
                        {
                            "id": rid, "from_id": rel.source_id,
                            "to_id": rel.target_id, "rtype": rel.relationship_type,
                            "props": json.dumps(rel.properties),
                            "strength": rel.strength,
                            "mentions": rel.mention_count,
                            "valid_from": rel.valid_from,
                            "valid_until": rel.valid_until,
                            "superseded": rel.superseded_by,
                            "first_seen": rel.first_seen,
                            "last_seen": rel.last_seen,
                        },
                    )
                    saved += 1

                await session.commit()

                self._dirty_entities.clear()
                self._dirty_relationships.clear()
                self._last_save_time = time.time()

                if saved > 0:
                    logger.info(f"KG saved to PostgreSQL: {saved} items")

        except Exception as e:
            logger.warning(f"KG save to DB failed: {e}")

        return saved

    # ── Entity Management ─────────────────────────────────────────

    def _guess_entity_type(self, name: str) -> str:
        """Guess entity type from name patterns."""
        name_lower = name.lower()

        if name_lower.startswith("http://") or name_lower.startswith("https://"):
            return "url"

        for category, patterns in TECH_PATTERNS.items():
            for pattern in patterns:
                if re.search(rf"\b{pattern}\b", name_lower):
                    if category in ("languages", "frameworks"):
                        return "technology"
                    elif category == "tools":
                        return "tool"
                    elif category == "concepts":
                        return "concept"

        if "/" in name or ("." in name and len(name) > 5):
            return "file"

        return "concept"

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
            self._dirty_entities.add(eid)
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
        self._dirty_entities.add(eid)
        return entity

    def update_entity_properties(self, entity_id: str, props: dict) -> Optional[Entity]:
        """Merge properties into an existing entity (non-destructive)."""
        entity = self._entities.get(entity_id)
        if not entity:
            return None
        entity.properties.update(props)
        entity.last_seen = time.time()
        self._dirty_entities.add(entity_id)
        return entity

    def get_entity_by_property(self, prop_name: str, prop_value: str) -> list[Entity]:
        """Reverse lookup: find entities with a specific property value."""
        results = []
        val_lower = prop_value.lower()
        for entity in self._entities.values():
            v = entity.properties.get(prop_name, "")
            if isinstance(v, str) and v.lower() == val_lower:
                results.append(entity)
        return results

    # ── Relationship Management ───────────────────────────────────

    def _add_relationship(
        self, source_id: str, target_id: str,
        rel_type: str, strength: float = 1.0,
        properties: dict = None,
        valid_from: float = 0.0,
    ) -> Relationship:
        """Add or reinforce a relationship."""
        rid = _rel_id(source_id, target_id, rel_type)
        now = time.time()

        if rid in self._relationships:
            rel = self._relationships[rid]
            rel.mention_count += 1
            rel.last_seen = now
            # Strengthen with diminishing returns
            rel.strength = min(1.0, rel.strength + 0.1 * (1 - rel.strength))
            if properties:
                rel.properties.update(properties)
            self._dirty_relationships.add(rid)
            return rel

        rel = Relationship(
            source_id=source_id,
            target_id=target_id,
            relationship_type=rel_type,
            strength=strength,
            properties=properties or {},
            mention_count=1,
            valid_from=valid_from or now,
            first_seen=now,
            last_seen=now,
        )
        self._relationships[rid] = rel
        self._adjacency[source_id].append(rid)
        self._adjacency[target_id].append(rid)
        self._dirty_relationships.add(rid)
        return rel

    def add_contradicts(
        self,
        old_source_id: str, old_target_id: str, old_rel_type: str,
        new_source_id: str, new_target_id: str, new_rel_type: str,
        reason: str = "",
    ) -> Optional[Relationship]:
        """Mark an old relationship as superseded by a new one.

        Spacebot-inspired: Instead of deleting old facts, we preserve
        temporal history with a Contradicts edge. The old relationship
        gets a `superseded_by` pointer and `valid_until` timestamp.

        Example: "John works at Acme" → later "John works at Globex"
            → old works_on gets superseded_by=new_works_on, valid_until=now
        """
        old_rid = _rel_id(old_source_id, old_target_id, old_rel_type)
        old_rel = self._relationships.get(old_rid)
        if not old_rel:
            return None

        # Create the new relationship
        new_rel = self._add_relationship(
            new_source_id, new_target_id, new_rel_type,
        )
        new_rid = _rel_id(new_source_id, new_target_id, new_rel_type)

        # Mark old as superseded
        old_rel.superseded_by = new_rid
        old_rel.valid_until = time.time()
        if reason:
            old_rel.properties["superseded_reason"] = reason
        self._dirty_relationships.add(old_rid)

        # Create explicit contradicts edge for graph queries
        self._add_relationship(
            new_rid, old_rid, "contradicts",
            properties={"reason": reason} if reason else {},
        )

        logger.info(
            f"KG contradicts: {old_rel_type}({old_source_id[:8]}→{old_target_id[:8]}) "
            f"superseded by {new_rel_type}({new_source_id[:8]}→{new_target_id[:8]})"
        )
        return new_rel

    def get_current_relationships(
        self, entity_id: str, rel_type: str = None,
    ) -> list[Relationship]:
        """Get only current (non-superseded) relationships for an entity."""
        results = []
        for rid in self._adjacency.get(entity_id, []):
            rel = self._relationships.get(rid)
            if not rel or not rel.is_current:
                continue
            if rel_type and rel.relationship_type != rel_type:
                continue
            results.append(rel)
        return results

    def find_path(
        self, from_entity_id: str, to_entity_id: str, max_depth: int = 4,
    ) -> list[tuple[Entity, Relationship]]:
        """Find shortest path between two entities using BFS.

        Only follows current (non-superseded) relationships.
        Returns list of (entity, relationship) pairs forming the path.
        """
        if from_entity_id == to_entity_id:
            return []

        visited = {from_entity_id}
        queue = [(from_entity_id, [])]

        while queue:
            current_id, path = queue.pop(0)
            if len(path) >= max_depth:
                continue

            for rid in self._adjacency.get(current_id, []):
                rel = self._relationships.get(rid)
                if not rel or not rel.is_current:
                    continue

                other_id = rel.target_id if rel.source_id == current_id else rel.source_id
                if other_id in visited:
                    continue

                other = self._entities.get(other_id)
                if not other:
                    continue

                new_path = path + [(other, rel)]

                if other_id == to_entity_id:
                    return new_path

                visited.add(other_id)
                queue.append((other_id, new_path))

        return []

    # ── Importance Scoring ────────────────────────────────────────

    def compute_importance(self, entity: Entity) -> float:
        """Compute entity importance score.

        Score = mention_count * recency_weight * type_weight * centrality_weight

        Inspired by Spacebot's memory importance scoring:
        - High-mention entities are more important
        - Recently seen entities score higher (exponential decay)
        - People and projects score higher than URLs/files
        - Highly connected entities (graph centrality) get a boost
        """
        now = time.time()

        # Recency weight: exponential decay with 30-day half-life
        days_since_seen = max(0, (now - entity.last_seen) / 86400) if entity.last_seen else 30
        recency_weight = 0.5 ** (days_since_seen / IMPORTANCE_HALF_LIFE_DAYS)

        # Type weight
        type_weight = ENTITY_TYPE_WEIGHTS.get(entity.entity_type, 1.0)

        # Centrality: number of current relationships (capped)
        centrality = len(self._adjacency.get(entity.id, []))
        centrality_weight = 1.0 + min(centrality * 0.05, 0.5)  # Max 1.5x boost

        # Mention count (logarithmic scale to prevent runaway scores)
        import math
        mention_score = 1 + math.log2(max(1, entity.mention_count))

        importance = mention_score * recency_weight * type_weight * centrality_weight
        return round(importance, 3)

    def _recompute_all_importance(self) -> None:
        """Recompute importance scores for all entities."""
        for entity in self._entities.values():
            entity.importance = self.compute_importance(entity)

    # ── Extraction ────────────────────────────────────────────────

    async def extract_and_store(
        self,
        text: str,
        source_conv: str = "",
        context: str = "",
    ) -> dict:
        """Extract entities and relationships from text and store in graph."""
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
                    if len(name) > 2 and name.lower() not in ("the", "this", "that", "our", "your"):
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

            # 6. Update importance scores for affected entities
            for entity in extracted_entities:
                entity.importance = self.compute_importance(entity)

            # 7. Auto-save if enough dirty items (fire-and-forget)
            dirty_count = len(self._dirty_entities) + len(self._dirty_relationships)
            time_since_save = time.time() - self._last_save_time
            if dirty_count > 20 or (dirty_count > 0 and time_since_save > 300):
                try:
                    await self.save_to_db()
                except Exception:
                    pass  # Non-blocking

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

        if t1 == "project" and t2 in ("technology", "tool"):
            return "uses"
        if t2 == "project" and t1 in ("technology", "tool"):
            return "part_of"
        if t1 == "person" and t2 == "project":
            return "works_on"
        if t2 == "person" and t1 == "project":
            return "created_by"
        if t1 == "person" and t2 in ("technology", "tool"):
            return "uses"
        if t1 == "file" and t2 == "project":
            return "part_of"
        if t2 == "file" and t1 == "project":
            return "part_of"
        if t1 == "technology" and t2 == "concept":
            return "implements"

        return "mentioned_with"

    # ── Querying ──────────────────────────────────────────────────

    async def query_related(
        self,
        text: str,
        limit: int = 10,
        max_depth: int = 2,
    ) -> str:
        """Query the knowledge graph for context related to text.

        Only follows current (non-superseded) relationships in traversal.
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
        related_entities: list[tuple[Entity, float, str]] = []

        for seed in mentioned[:5]:
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
        """BFS traversal of the knowledge graph.

        Only follows current (non-superseded) relationships.
        """
        if depth > max_depth or entity_id in visited:
            return

        visited.add(entity_id)

        for rid in self._adjacency.get(entity_id, []):
            rel = self._relationships.get(rid)
            if not rel or not rel.is_current:
                continue  # Skip superseded relationships

            other_id = rel.target_id if rel.source_id == entity_id else rel.source_id
            other = self._entities.get(other_id)
            if not other or other.id in visited:
                continue

            relevance = rel.strength * (0.7 ** depth) * (other.importance or 1.0)

            source_entity = self._entities.get(rel.source_id)
            via = ""
            if source_entity and source_entity.id == entity_id:
                via = f"{rel.relationship_type} {other.name}"
            else:
                via = f"{source_entity.name if source_entity else '?'} {rel.relationship_type} this"

            results.append((other, relevance, via))
            self._bfs_traverse(other.id, visited, results, depth + 1, max_depth)

    # ── Query API Methods ─────────────────────────────────────────

    def get_entity(self, name: str) -> Optional[Entity]:
        """Look up an entity by name."""
        eid = self._name_index.get(name.lower().strip())
        if eid:
            return self._entities.get(eid)
        return None

    def search_entities(
        self, query: str = "", entity_type: str = "", limit: int = 20,
    ) -> list[Entity]:
        """Search entities by name substring and/or type."""
        q_lower = query.lower()
        results = []
        for entity in self._entities.values():
            if entity_type and entity.entity_type != entity_type:
                continue
            if q_lower and q_lower not in entity.name.lower():
                continue
            results.append(entity)

        # Sort by importance
        results.sort(key=lambda e: e.importance, reverse=True)
        return results[:limit]

    def get_neighbors(self, entity_id: str) -> list[dict]:
        """Get all entities connected to a given entity (current relationships only)."""
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

    def get_entity_history(self, entity_id: str) -> list[dict]:
        """Get temporal history of an entity's relationships.

        Returns all relationships (including superseded ones) for
        understanding how facts evolved over time.
        """
        history = []
        for rid in self._adjacency.get(entity_id, []):
            rel = self._relationships.get(rid)
            if not rel:
                continue
            other_id = rel.target_id if rel.source_id == entity_id else rel.source_id
            other = self._entities.get(other_id)
            history.append({
                "relationship": rel.to_dict(),
                "entity": other.to_dict() if other else None,
                "is_current": rel.is_current,
            })

        # Sort: current first, then by last_seen descending
        history.sort(key=lambda h: (not h["is_current"], -h["relationship"].get("strength", 0)))
        return history

    # ── Stats & Export ────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get knowledge graph statistics."""
        type_counts: dict[str, int] = defaultdict(int)
        for e in self._entities.values():
            type_counts[e.entity_type] += 1

        rel_type_counts: dict[str, int] = defaultdict(int)
        superseded_count = 0
        for r in self._relationships.values():
            rel_type_counts[r.relationship_type] += 1
            if r.superseded_by:
                superseded_count += 1

        avg_extract = (
            self._total_extract_ms / self._total_extractions
            if self._total_extractions > 0
            else 0
        )

        # Top entities by importance
        top_entities = sorted(
            self._entities.values(),
            key=lambda e: e.importance,
            reverse=True,
        )[:5]

        return {
            "total_entities": self.entity_count,
            "total_relationships": self.relationship_count,
            "entity_types": dict(type_counts),
            "relationship_types": dict(rel_type_counts),
            "superseded_relationships": superseded_count,
            "dirty_entities": len(self._dirty_entities),
            "dirty_relationships": len(self._dirty_relationships),
            "total_extractions": self._total_extractions,
            "avg_extract_ms": round(avg_extract, 1),
            "top_entities": [
                {"name": e.name, "type": e.entity_type, "importance": e.importance}
                for e in top_entities
            ],
        }

    def export_graph(self, max_entities: int = 200) -> dict:
        """Export graph data for visualization (D3.js format)."""
        entities = sorted(
            self._entities.values(),
            key=lambda e: e.importance,
            reverse=True,
        )[:max_entities]

        entity_ids = {e.id for e in entities}

        rels = [
            r for r in self._relationships.values()
            if r.source_id in entity_ids and r.target_id in entity_ids
        ]

        return {
            "nodes": [e.to_dict() for e in entities],
            "links": [r.to_dict() for r in rels],
        }
