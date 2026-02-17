# Redis Vector Search Developments

## Overview
**Redis vector search** has undergone a transformational evolution from 2024 through 2025, evolving from a module-based add-on (RediSearch) into a first-class, built-in capability of Redis itself. With the release of Redis 8.0 (which unified Redis Community Edition and Redis Stack into "Redis Open Source"), vector search via the **Redis Query Engine** became a native feature requiring no separate module installation. Redis 8.4 (November 2025) then introduced the landmark **FT.HYBRID** command, combining full-text search and vector similarity search into a single query path with Reciprocal Rank Fusion (RRF) scoring — a critical capability for production RAG (Retrieval-Augmented Generation) systems and AI agents.

Two other major developments define the current landscape: the **Vector Set** native data type (beta in 8.0, GA in Redis Cloud 8.2) which provides a simple, Sorted-Set-like interface for vector similarity operations using commands like `VADD` and `VSIM`; and **LangCache**, a fully managed semantic caching service that stores and reuses LLM prompts/responses to reduce inference costs by up to 70% and deliver 15× faster responses on cache hits. Combined with the Intel-partnered **SVS-VAMANA** index algorithm supporting Locally-adaptive Vector Quantization (LVQ) and LeanVec dimensionality reduction — which reduces vector memory footprint by 51–74% while maintaining accuracy — Redis has positioned itself as one of the most performant and cost-efficient vector database options available, particularly for real-time AI workloads that already leverage Redis for caching and session management.

These developments matter because they lower the barrier to adopting vector search in production. Teams already using Redis no longer need a separate vector database; they can run semantic search, recommendations, and RAG pipelines from the same infrastructure they use for caching and data storage, with sub-millisecond latencies, horizontal scaling, and enterprise-grade reliability.

## Key Concepts
- **Redis Query Engine (formerly RediSearch)**: Now built into Redis Open Source 8.0+. Supports vector search, full-text search, geospatial queries, and aggregations over Hash and JSON documents. Scoring default changed from TF-IDF to BM25.

- **Vector Set Data Type**: A new native Redis data type (beta in 8.0, GA in Cloud 8.2). Like Sorted Sets but elements have vectors instead of scores. Commands include `VADD`, `VSIM`, `VREM`, `VCARD`, `VDIM`, `VEMB`, `VSETATTR`, `VGETATTR`, `VRANGE`, `VRANDMEMBER`. Supports filtered search with attribute-based expressions (e.g., `.year > 1950`).

- **FT.HYBRID Command (Redis 8.4)**: Combines full-text and vector similarity search in a single query. Supports Reciprocal Rank Fusion (RRF) for merging ranking signals. Eliminates need for multi-step logic or manual score merging. Supports GEO/GEOSHAPE filters.

- **Index Types — FLAT, HNSW, and SVS-VAMANA**: FLAT for exact search on <1M vectors; HNSW for approximate nearest-neighbor on >1M vectors with tunable `M`, `EF_CONSTRUCTION`, `EF_RUNTIME`; SVS-VAMANA (added in 8.2) for Intel-optimized graph-based search with built-in compression.

- **Vector Quantization & Dimensionality Reduction**: Intel SVS partnership enables LVQ (Locally-adaptive Vector Quantization) and LeanVec (linear dimensionality reduction + LVQ). Achieves 51–74% reduction in graph index memory and 26–37% overall memory savings. Supports two-level compression for high-dimensional embeddings.

- **LangCache (Semantic Caching Service)**: Fully managed REST API service on Redis Cloud. Caches LLM prompts/responses using semantic similarity. Reduces LLM API costs by up to 70%, delivers 15× faster responses on cache hits. Integrates with AI agent workflows.

- **Supported Vector Types**: FLOAT32, FLOAT64, FLOAT16, BFLOAT16 (v2.10+), INT8, UINT8 (v8.0+). Distance metrics: L2 (Euclidean), IP (Inner Product), COSINE.

- **"One Redis" Unification**: Redis 8.0 merged Redis Stack and Redis Community Edition into a single distribution. All previously modular functionality (Search, JSON, TimeSeries, Probabilistic, Vector) is now built-in. No separate module management.

- **Performance Benchmarks (Redis 8.x series)**: Up to 87% lower command latency, 16× more query processing capacity with scaling, 30%+ throughput improvement for caching (8.4), 4.7× improvement for large distributed search operations with multi-threaded I/O, up to 144% higher QPS with vector compression.

- **JSON Memory Optimizations (Redis 8.4)**: Short strings (≤7 bytes) inlined for ~37% memory reduction. Homogeneous numeric arrays stored with type-once encoding for 50–92% memory reduction. Makes storing vectors directly in JSON practical.

## Decision Guide
**If the user asks about choosing between Vector Sets vs. Redis Query Engine vector search:**
→ Vector Sets are ideal for simple, self-contained similarity search use cases (recommendations, semantic search) where you want a Sorted-Set-like API with `VADD`/`VSIM`. The Query Engine is better when you need complex queries combining vector search with full-text search, aggregations, geospatial filtering, or when data is stored in Hash/JSON documents with rich metadata schemas.

**If the user asks about which index algorithm to use (FLAT vs. HNSW vs. SVS-VAMANA):**
→ Use FLAT for datasets <1M vectors where 100% recall accuracy is required. Use HNSW for >1M vectors where speed matters more than perfect accuracy. Use SVS-VAMANA when running on Intel hardware and memory reduction is critical — it provides 51–74% memory savings on vector indexes with competitive performance.

**If the user asks about reducing memory costs for vector workloads:**
→ Consider SVS-VAMANA with LVQ/LeanVec compression (26–37% overall savings). Also leverage Redis 8.4's JSON optimizations (50–92% for numeric arrays). For HNSW, use FLOAT16 or INT8 types instead of FLOAT32 where precision allows.

**If the user asks about hybrid search (combining keyword + semantic):**
→ Upgrade to Redis 8.4 and use `FT.HYBRID`. It natively combines full-text and vector search with RRF scoring in a single command, eliminating the need for application-level score merging pipelines.

**If the user asks about semantic caching for LLMs:**
→ Point them to LangCache (managed service on Redis Cloud) or building a custom semantic cache using Vector Sets or the Query Engine. LangCache offers up to 70% cost reduction and 15× faster responses. Redis + DeepLearning.AI have a course on this topic.

**If the user asks about Redis vs. dedicated vector databases (Pinecone, Weaviate, Milvus, Qdrant):**
→ Redis excels when the team already uses Redis, needs sub-millisecond latency, or wants to avoid a separate database for vectors. It's particularly strong for real-time use cases. Dedicated vector DBs may offer more specialized features (e.g., billion-scale datasets, advanced filtering). Redis now competes well with quantization support and hybrid search.

**If the user asks about deploying Redis vector search:**
→ Redis Open Source 8.0+ includes everything built-in. For managed services: Redis Cloud (Essentials or Pro) or Azure Cache for Redis Enterprise tier. For self-managed: Redis Software 8.0.2+. Client libraries: redis-py, Lettuce (Java), node-redis, go-redis, Jedis all support Vector Sets and Query Engine.

## Quick Reference
### Version Timeline
| Version | Key Vector Feature | Date |
|---------|-------------------|------|
| Redis 8.0 | Vector Set (beta), unified "One Redis", Query Engine built-in | Early 2025 |
| Redis 8.2 | SVS-VAMANA index, vector compression, 144% higher QPS | Mid 2025 |
| Redis 8.4 | FT.HYBRID command, multi-threaded search I/O, JSON memory opts | Nov 2025 |

### Key Commands — Vector Sets
```
VADD key VALUES <dim> <v1> <v2> ... <element>   # Add vector
VSIM key VALUES <dim> <v1> <v2> ... [COUNT n]   # Search by vector
VSIM key ELE <element> [COUNT n]                 # Search by element
VSIM key ... FILTER ".price < 100"               # Filtered search
VREM key <element>                               # Remove element
VCARD key                                        # Count elements
VDIM key                                         # Get dimensions
VEMB key <element>                               # Get embedding
VSETATTR key <element> '{"k":"v"}'               # Set attributes
VGETATTR key <element>                           # Get attributes
```

### Key Commands — Query Engine Vector Search
```
# Create HNSW index
FT.CREATE idx ON HASH PREFIX 1 doc: SCHEMA
  vec VECTOR HNSW 6 TYPE FLOAT32 DIM 1536 DISTANCE_METRIC COSINE

# KNN search
FT.SEARCH idx "*=>[KNN 10 @vec $query_vec AS score]"
  PARAMS 2 query_vec <blob> SORTBY score

# Hybrid search (Redis 8.4+)
FT.HYBRID idx "search terms"
  VECTOR_FIELD vec VECTOR_QUERY <blob> K 10

# Create SVS-VAMANA index with compression
FT.CREATE idx ON HASH PREFIX 1 doc: SCHEMA
  vec VECTOR SVS-VAMANA 8 TYPE FLOAT32 DIM 768
  DISTANCE_METRIC COSINE COMPRESSION LVQ4x4
```

### Index Algorithm Cheat Sheet
| Algorithm | Best For | Memory | Accuracy | Speed |
|-----------|----------|--------|----------|-------|
| FLAT | <1M vectors | High | Exact | Slower |
| HNSW | >1M vectors | High | ~95-99% | Fast |
| SVS-VAMANA | >1M, Intel HW | Low (51-74% less) | ~95-99% | Fast |

### Distance Metrics
- **COSINE**: Best for text embeddings (direction matters, not magnitude)
- **L2**: Best for image/spatial data (absolute distance)
- **IP**: Best for pre-normalized vectors (dot product)

### Supported Vector Types
`FLOAT32` | `FLOAT64` | `FLOAT16` | `BFLOAT16` | `INT8` | `UINT8`

### Performance Numbers (Redis 8.x)
- Up to **87% lower** command latency
- **30%+ throughput** improvement for caching (8.4)
- **4.7× faster** distributed search queries (multi-threaded I/O)
- **144% higher QPS** with vector compression
- **51–74% memory reduction** on vector indexes (SVS-VAMANA + LVQ)
- **50–92% JSON memory reduction** for numeric arrays (8.4)
- LangCache: **70% LLM cost reduction**, **15× faster** on cache hits

## Sources & Notes
### Primary Sources
1. **Redis Official Docs — What's New in Redis 8.0**: https://redis.io/docs/latest/develop/whats-new/8-0/ — Authoritative reference for Vector Sets, Query Engine, and One Redis unification.
2. **Redis Official Docs — Vector Search Concepts**: https://redis.io/docs/latest/develop/ai/search-and-query/vectors/ — Comprehensive guide to FLAT, HNSW, SVS-VAMANA indexes, vector types, and search patterns.
3. **Redis Official Docs — Vector Sets**: https://redis.io/docs/latest/develop/data-types/vector-sets/ — Full command reference with code examples in Python, Node.js, Java, Go, C#, PHP.
4. **Redis Blog — Tech Dive: Quantization & Dimensionality Reduction (Sep 2025)**: https://redis.io/blog/tech-dive-comprehensive-compression-leveraging-quantization-and-dimensionality-reduction/ — Detailed technical explanation of Intel SVS partnership, LVQ, and LeanVec.
5. **Redis Blog — What's New in Two, November 2025**: https://redis.io/blog/whats-new-in-two-november-2025-edition/ — Redis 8.4 GA announcement covering FT.HYBRID, performance, and JSON optimizations.
6. **Linuxiac — Redis 8.4 Launches with Hybrid Full-Text + Vector Search**: https://linuxiac.com/redis-8-4-launches-with-hybrid-full-text-plus-vector-search/ — Independent coverage of 8.4 features and benchmarks.
7. **Redis Blog — Spring Release 2025 (LangCache & Vector Sets)**: https://redis.io/blog/spring-release-2025/ — LangCache announcement and Vector Sets GA.
8. **Open Source For You — Redis Expands with LangCache**: https://www.opensourceforu.com/2025/09/redis-expands-with-decodable-and-langcache/ — LangCache cost/performance claims (70% cost reduction, 15× faster).

### Caveats
- **Vector Sets are still relatively new** — beta in 8.0, GA in Cloud 8.2. APIs may still evolve. Production use should be validated.
- **SVS-VAMANA is Intel-optimized** — performance gains are most significant on Intel hardware with SIMD support. AMD/ARM results may differ.
- **LangCache is a managed service** — only available on Redis Cloud, not self-hosted. Pricing details should be verified.
- **Benchmark numbers** (87% latency reduction, 144% QPS, etc.) are from Redis's own publications and may reflect optimal conditions. Independent benchmarks should be consulted for comparative evaluations.
- **FT.HYBRID** is new in 8.4 (Nov 2025) — community adoption patterns and edge cases are still emerging.
- **Licensing context**: Redis transitioned from BSD to dual SSPL/RSALv2 licensing in 2024, then to AGPLv3 in 2025 for Redis Open Source. This may impact deployment decisions for some organizations.
