# 🧠 Nexus Personal Memory System

## Overview

The Personal Memory System gives Nexus the ability to learn from your interactions, remember your preferences, track projects, and maintain context across sessions. It transforms Nexus from a stateless assistant into a personalized AI that gets better the more you use it.

## Features

### 1. **User Preferences Learning**
- Automatically learns your preferred models for different tasks
- Remembers your communication style preferences
- Tracks which tools you use most frequently
- Learns routing preferences (local vs Claude vs hybrid)

### 2. **Project Context Tracking**
- Maintains active project lists with descriptions
- Tracks files associated with each project
- Monitors project status (active/completed/on_hold)
- Links conversations to projects automatically

### 3. **Interaction Pattern Recognition**
- Learns successful workflow patterns
- Tracks which approaches work best for different query types
- Adapts suggestions based on past interactions
- Success rate tracking for continuous improvement

### 4. **Knowledge Association**
- Builds semantic links between concepts
- Creates relationship graphs (uses, requires, related_to, etc.)
- Enables context-aware responses
- Supports manual and automatic knowledge building

### 5. **Session Continuity**
- Tracks tools used in each session
- Remembers topics discussed
- Maintains file context
- Provides \"last time we worked on...\" continuity

## Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Memory System Architecture               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌──────────────────────────────┐   │
│  │  PersonalMemory │    │      MemoryIntegrator         │   │
│  │     System      │◄──►│  (Orchestration Layer)        │   │
│  │                 │    │                               │   │
│  │ • Preferences   │    │ • Session Management          │   │
│  │ • Projects      │    │ • Context Enhancement         │   │
│  │ • Patterns      │    │ • Learning Pipeline           │   │
│  │ • Sessions      │    │ • Suggestion Engine           │   │
│  │ • Knowledge     │    │ • Analytics                   │   │
│  └─────────────────┘    └──────────────────────────────┘   │
│           ▲                          ▲                      │
│           │                          │                      │
│    ┌──────┴──────┐          ┌───────┴────────┐             │
│    │  SQLite DB  │          │  Main Application│             │
│    │  (6 tables) │          │                 │             │
│    └─────────────┘          └─────────────────┘             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Database Schema

The system uses 6 SQLite tables:

1. **user_preferences**: Key-value store with confidence scores and usage tracking
2. **active_projects**: Project metadata, files, status, and timestamps
3. **interaction_patterns**: Pattern descriptions, triggers, success rates
4. **session_context**: Session lifecycle, tools, topics, files
5. **knowledge_associations**: Concept relationships with strength metrics
6. **performance_analytics**: Usage statistics and effectiveness tracking

## Integration Points

### Telegram Bot (`process_message()`)
- Starts memory session on new conversation
- Learns from every user message
- Enhances system prompt with personal context
- Tracks tool usage success/failure
- Adds continuation context for new sessions

### WebSocket Chat (`websocket_chat()`)
- Session lifecycle management (start/update/end)
- Real-time context enhancement
- Automatic learning from interactions
- Disconnect handling with session summary

### Admin Panel (`/admin/memory`)
- Full memory management UI
- View and edit preferences
- Manage projects
- Teach new patterns
- Browse knowledge associations
- Export/import memory data
- Session history analytics

## API Endpoints

### Memory Overview
- `GET /api/admin/memory/overview` - System statistics and suggestions
- `GET /api/admin/memory/status` - Quick status check

### Preferences
- `GET /api/admin/memory/preferences` - List all preferences
- `POST /api/admin/memory/preferences` - Add/update preference

### Projects
- `GET /api/admin/memory/projects` - List all projects
- `POST /api/admin/memory/projects` - Create new project
- `PUT /api/admin/memory/projects/{id}` - Update project

### Patterns
- `GET /api/admin/memory/patterns` - List learned patterns
- `POST /api/admin/memory/patterns/learn` - Teach new pattern

### Sessions
- `GET /api/admin/memory/sessions` - Session history
- `GET /api/admin/memory/sessions/current` - Current session status

### Knowledge
- `GET /api/admin/memory/knowledge/{concept}` - Related concepts
- `POST /api/admin/memory/knowledge/associate` - Create association

### Data Management
- `GET /api/admin/memory/export` - Export all memory
- `POST /api/admin/memory/import` - Import memory data
- `DELETE /api/admin/memory/clear` - Clear memory (with optional filter)

## Usage Examples

### Automatic Learning
The system learns automatically from your interactions:

```python
# User says: \"I prefer Claude for complex coding tasks\"
# System automatically learns:
#   preference_key: \"preferred_model_for_coding\"
#   value: \"claude\"
#   confidence: 0.8 (increases with repetition)

# User asks about \"web scraper improvements\"
# System creates/updates project:
#   project_name: \"Web Scraper Improvements\"
#   topics: [\"web scraper\", \"improvements\"]
#   status: \"active\"
```

### Context Enhancement
The system automatically enhances prompts:

```python
# Before sending to LLM, system prompt is enhanced with:
\"\"\"\n## Personal Context
Based on your interaction history, I've noted:
- You prefer using Claude for coding tasks
- You're currently working on: Web Scraper Improvements
- Previously discussed: caching, performance optimization
- You've successfully used: run_python, read_file

## Project Context: Web Scraper Improvements
Active project with focus on caching and performance.
Recent files: web_scraper.py, cache_manager.py
\"\"\"\n```

### Suggestion Engine
The system provides context-aware suggestions:

```python\n# User asks: \"Can you review my code?\"\n# System suggests:\n[\n  {\n    \"type\": \"project\",\n    \"description\": \"Continue working on Web Scraper Improvements?\",\n    \"confidence\": 0.9\n  },\n  {\n    \"type\": \"action\",\n    \"description\": \"Use code review pattern (detailed line-by-line analysis)\",\n    \"confidence\": 0.85\n  },\n  {\n    \"type\": \"tool\",\n    \"description\": \"Consider using read_file to review web_scraper.py\",\n    \"confidence\": 0.8\n  }\n]\n```\n\n## Admin UI\n\nAccess the memory management UI at: `http://localhost:8000/admin/memory`\n\nFeatures:\n- **Dashboard**: Real-time memory statistics\n- **Preferences**: View and manually add preferences\n- **Patterns**: See learned patterns and teach new ones\n- **Projects**: Manage active projects\n- **Sessions**: Browse conversation history\n- **Knowledge**: Explore concept associations\n- **Export/Import**: Backup and restore memory data\n\n## Configuration\n\nThe memory system works automatically with sensible defaults. You can configure:\n\n```python\n# In config.json (optional)\n{\n  \"memory\": {\n    \"enable_auto_learn\": true,\n    \"context_window_size\": 20,\n    \"suggestion_threshold\": 0.7,\n    \"max_projects_tracked\": 50\n  }\n}\n```\n\n## Performance\n\n- **Database**: Efficient SQLite with proper indexing\n- **Caching**: In-memory LRU caches for hot data\n- **Async**: Non-blocking operations throughout\n- **Lazy Loading**: Context built on-demand, not stored redundantly\n\n## Privacy\n\nAll memory data is stored locally in your SQLite database (`data/nexus.db`). No data is sent to external services for memory operations.\n\n## Future Enhancements\n\nPotential improvements for v2:\n- Vector embeddings for semantic search\n- Cross-project knowledge synthesis\n- Time-decay for old preferences\n- Explicit user feedback on suggestions\n- Memory compression for long-term storage\n\n---\n\n**Your Nexus now remembers. The more you use it, the better it gets.**\n\"\"\