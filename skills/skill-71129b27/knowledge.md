# Redis Vector Search

## Overview
**Redis vector search** has undergone a transformational evolution from 2024 through 2025, establishing Redis as a first-class vector database and "real-time context engine" for AI applications. What began as an add-on module (RediSearch) has become deeply integrated into Redis core — Redis 8.0 introduced the native **Vector Set** data type (designed by Redis creator Salvatore Sanfilippo), Redis 8.2 brought vector compression and quantization via Intel SVS, and Redis 8.4 (GA November 2025) delivered the landmark **FT.HYBRID** command that unifies full-text and vector similarity search in a single query with server-side score fusion. These capabilities, combined with up to 16× vertical scaling via QPF (Query Performance Factor), position Redis as one of the fastest hybrid search engines available.

The strategic significance is substantial. Redis now targets the entire agentic AI stack: semantic caching (LangCache — up to 70% cost savings on LLM calls), persistent agent memory (integrations with LangGraph, AutoGen, Cognee, A2A), and context-aware retrieval for RAG pipelines. Research from Anthropic (2025) and Apple ML Research (2024) demonstrates that hybrid retrieval reduces context failure rates by up to 49% compared to single-mode retrieval and boosts answer accuracy by 11–15% on complex reasoning tasks — exactly the problem Redis hybrid search now solves natively. With Redis Cloud bundling all modules by default and offering managed services like LangCache, the barrier to entry for vector search has been dramatically lowered.

## Key Concepts
- **Vector Set (native data type)**: A new Redis data type (like Sorted Sets but with vectors instead of scores). Uses HNSW graph internally. Commands: `VADD`, `VSIM`, `VREM`, `VCARD`, `VDIM`, `VEMB`, `VSETATTR`, `VGETATTR`, `VLINKS`, `VRANGE`, `VRANDMEMBER`, `VISMEMBER`, `VINFO`. Supports filtered search via element attributes.

- **FT.HYBRID command (Redis 8.4)**: Unified API combining full-text search (BM25) and vector similarity (KNN/range) with server-side score fusion. Supports **Reciprocal Rank Fusion (RRF)** and **Linear Combination** methods. Eliminates the need for client-side result merging or multi-step pipelines.

- **Redis Query Engine (formerly RediSearch)**: The search and indexing engine supporting HNSW and FLAT vector index types on Hash and JSON documents. Used via `FT.CREATE`, `FT.SEARCH`, `FT.AGGREGATE`, and now `FT.HYBRID`. Supports pre-filtering with ADHOC_BF and BATCHES policies.

- **Vector Quantization & Dimensionality Reduction**: Compress float32 vectors to 8-bit or 4-bit integers; reduce dimensionality using algorithms based on **Intel SVS (Scalable Vector Search)**. Achieves 26–37% memory savings with minimal accuracy loss and 144% faster search speeds.

- **LangCache (Managed Semantic Caching)**: Fully managed service that stores semantically similar LLM prompts/responses. Up to **70% cost reduction** on LLM calls and **15× faster** response times for cache hits. Public preview on Redis Cloud.

- **Query Performance Factor (QPF)**: Vertical scaling mechanism adding up to **16× more processing power** to Redis Query Engine via multi-threading. GA on Redis Cloud.

- **Hybrid Retrieval for RAG**: Combining lexical precision (BM25) with semantic understanding (vector similarity) reduces context failure rates by up to 49% and improves end-to-end answer accuracy by 11–15% (per Anthropic/Apple ML research).

- **Agent Framework Integrations**: Native support for **LangGraph**, **AutoGen**, **Google A2A**, and **Cognee** — Redis serves as the persistent memory and context layer for agentic workloads.

- **JSON Memory Optimization (Redis 8.4)**: Short strings (≤7 bytes) inlined (37% savings), homogeneous numeric arrays stored with type-aware compression (50–92% savings). Makes storing vectors directly in JSON documents practical.

- **HNSW Index Algorithm**: The core approximate nearest neighbor algorithm powering both Vector Sets and Redis Query Engine vector indexes. Configurable via `M` (connections per node), `EF_CONSTRUCTION` (build-time accuracy), and `EF_RUNTIME` (query-time accuracy/speed tradeoff).

## Decision Guide
**If the user asks about choosing between Vector Sets vs. Redis Query Engine vector search:**
→ **Vector Sets** (`VADD`/`VSIM`) are ideal for simple, self-contained similarity search with minimal schema — think lightweight recommendations, face recognition, or quick semantic lookup. They are a native data type requiring no index creation.
→ **Redis Query Engine** (`FT.CREATE`/`FT.SEARCH`/`FT.HYBRID`) is better for complex, multi-field queries combining vector similarity with text search, numeric/tag/geo filters, aggregations, and scoring fusion. Use this for production RAG pipelines and enterprise search.

**If the user asks about reducing memory costs for vector workloads:**
→ Enable **quantization** (8-bit or 4-bit) and **dimensionality reduction** via Intel SVS in Redis Cloud. Expect 26–37% memory savings with 144% faster search and low accuracy impact. Also leverage Redis 8.4's JSON memory optimizations for embedded vectors.

**If the user asks about speeding up LLM applications:**
→ Deploy **LangCache** for semantic caching (70% cost savings, 15× faster cache hits). Use **QPF** to scale query engine performance up to 16×. Use **FT.HYBRID** with RRF to improve retrieval quality and reduce hallucination.

**If the user asks about hybrid search implementation:**
→ Redis 8.4's `FT.HYBRID` is the recommended approach. It replaces manual aggregation pipelines with a single command supporting RRF (default, good general-purpose) or Linear Combination (when you need explicit weight control via alpha/beta). Pre-8.4, use `FT.AGGREGATE` with vector pre-filtering.

**If the user asks about agent memory architecture:**
→ Redis integrates with LangGraph (checkpointing + memory), AutoGen (memory layer), Cognee (summarization/reasoning), and Google A2A (task storage + event queues). Redis provides persistent, low-latency memory for stateful agents.

**If the user asks about HNSW tuning:**
→ Increase `EF_CONSTRUCTION` (default 200) for better recall at index build time. Increase `EF_RUNTIME` (default 10) for better query accuracy at the cost of latency. Increase `M` (default 16) for denser graphs (higher recall, more memory). For exact search, use FLAT index type.

**If the user asks about Redis vs. dedicated vector DBs (Pinecone, Weaviate, Milvus):**
→ Redis advantages: sub-millisecond latency, unified data platform (cache + search + streams + pub/sub), hybrid search natively, managed cloud offering, familiar Redis API. Redis trade-offs: HNSW-only ANN (no IVF/PQ natively beyond quantization), vector sets still in beta, less mature pure-vector-DB ecosystem tooling.

## Quick Reference
### Versions & Timeline
| Version | Date | Key Vector Features |
|---------|------|-------------------|
| Redis 8.0 | Apr 2025 | Vector Set data type (beta), all modules bundled |
| Redis 8.2 | Jul 2025 | Vector compression, quantization (Intel SVS), QPF GA |
| Redis 8.4 | Nov 2025 | `FT.HYBRID` command, RRF/Linear fusion, multi-threaded I/O |

### Vector Set Commands
```
VADD key [FP32|VALUES dim] val1 val2... element  # Add vector
VSIM key [ELE element | VALUES dim v1 v2...]     # Similarity search
     [COUNT n] [FILTER ".attr > value"]
VREM key element                                  # Remove element
VCARD key                                         # Count elements
VDIM key                                          # Get dimensions
VEMB key element                                  # Get stored vector
VSETATTR key element '{"k":"v"}'                  # Set attributes
VGETATTR key element                              # Get attributes
VINFO key                                         # Index metadata
```

### Redis Query Engine Commands
```
FT.CREATE idx ON HASH PREFIX 1 doc: SCHEMA
  title TEXT content TEXT
  vec VECTOR HNSW 6 TYPE FLOAT32 DIM 768 DISTANCE_METRIC COSINE

FT.SEARCH idx "*=>[KNN 10 @vec $query_vec AS score]"
  PARAMS 2 query_vec <blob> SORTBY score ASC

FT.HYBRID idx
  SEARCH "@category:{tech}"
  VSIM @vec $query_vec KNN 4 K 10
  COMBINE RRF 4 WINDOW 20 CONSTANT 60
  LOAD * LIMIT 0 10
  PARAMS 2 query_vec <blob>
```

### Key Performance Numbers
- **30%+ throughput gain** (Redis 8.4 vs 8.2, caching workloads)
- **4.7× improvement** for distributed search queries (multi-threaded I/O)
- **16× faster** vector search with QPF vertical scaling
- **144% faster** search speeds with quantization
- **26–37% memory savings** with vector compression
- **50–92% JSON memory savings** for numeric arrays
- **70% cost savings** on LLM calls with LangCache
- **15× faster** response times for LangCache cache hits
- **49% reduction** in context failure rates with hybrid retrieval

### Index Types
| Type | Algorithm | Use Case |
|------|-----------|----------|
| HNSW | Hierarchical Navigable Small World | ANN — fast, scalable (default) |
| FLAT | Brute-force | Exact KNN — small datasets |

### Distance Metrics
- `COSINE` — normalized text embeddings (most common)
- `IP` — inner product
- `L2` — Euclidean distance

### Score Fusion Methods (FT.HYBRID)
- **RRF** (default): `score = Σ 1/(constant + rank_i)` — robust, parameter-light
- **Linear**: `score = α × text_score + β × vector_score` — explicit weighting

### Client Libraries with Vector Support
- `redis-py` (Python) — `r.vset().vadd()`, `r.ft().search()`
- `Jedis` 6.2+ (Java) — `VectorSetCommands`
- `Lettuce` 6.7+ (Java) — vector set support
- `node-redis` (JavaScript)
- `go-redis` (Go)
- `RedisVL` (Python) — high-level vector library with `SearchIndex`, `VectorQuery`

## Sources & Notes
### Primary Sources
1. **Redis Official Blog — Fall Release 2025** (redis.io/blog/fall-release-2025/) — Comprehensive overview of LangCache, hybrid search, quantization, QPF, and agent integrations
2. **Redis Official Blog — What's New Nov 2025** (redis.io/blog/whats-new-in-two-november-2025-edition/) — Redis 8.4 GA details, Vector Set in Cloud, performance benchmarks
3. **Redis Docs — Vector Sets** (redis.io/docs/latest/develop/data-types/vector-sets/) — Complete command reference and examples
4. **Redis Docs — FT.HYBRID** (redis.io/docs/latest/commands/ft.hybrid/) — Full syntax, parameters, and defaults for hybrid search
5. **Redis Blog — Hybrid Search in Redis 8.4** (redis.io/blog/revamping-context-oriented-retrieval-with-hybrid-search-in-redis-84/) — Architecture, research citations (Anthropic, Apple ML), use case patterns
6. **Linuxiac — Redis 8.4 Launch** (linuxiac.com/redis-8-4-launches-with-hybrid-full-text-plus-vector-search/) — Independent coverage of performance benchmarks and features

### Caveats
- **Vector Sets are still in beta** — API may change; not recommended for mission-critical production without testing
- **LangCache is in public preview** — pricing and SLA details may evolve
- **Quantization accuracy trade-offs** vary by embedding model and use case — always benchmark on your specific data
- **Redis Cloud vs. Open Source feature parity** — QPF, LangCache, and some quantization features are Cloud/Enterprise-only
- **Performance numbers** are from Redis's own benchmarks — independent third-party validation is limited
- **HNSW is the only ANN algorithm** — no IVF, ScaNN, or DiskANN support natively (unlike some purpose-built vector databases)
- **Vector Set filtered search** uses simple mathematical attribute filters, not the full query syntax of FT.SEARCH
