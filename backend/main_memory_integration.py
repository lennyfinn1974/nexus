\"\"\"Memory Integration Updates for main.py

This shows the key changes needed to integrate the Personal Memory System
into the main Nexus application.
\"\"\"

# Add these imports at the top of main.py
from memory_integration import MemoryIntegrator
from admin_memory import router as memory_admin_router, init_memory_admin

# Add this global variable with other globals
memory_integrator: MemoryIntegrator = None

# In the lifespan function, after initializing other components:

async def lifespan(app: FastAPI):
    global cfg, db, skills_engine, model_router, task_queue, plugin_manager, telegram_channel, memory_integrator

    # ... existing initialization code ...

    # Memory System (add this after db initialization)
    memory_integrator = MemoryIntegrator(DB_PATH, cfg)
    await memory_integrator.initialize()

    # ... rest of existing initialization ...

    # Admin API (update the existing admin_init call)
    from admin import init as admin_init
    admin_init(cfg, plugin_manager, model_router, db, task_queue, skills_engine)
    
    # Initialize memory admin endpoints
    init_memory_admin(memory_integrator)

    # ... rest of lifespan function ...

    yield

    # Shutdown (add to existing shutdown section)
    if memory_integrator:
        await memory_integrator.close()
    # ... rest of existing shutdown ...

# Add memory admin router to the app
app.include_router(memory_admin_router)

# Update the process_message function to use memory:

async def process_message(user_id: str, text: str, force_model: str = None) -> str:
    text = text.strip()
    
    # ... existing slash command handling ...

    # Enhanced conversation handling with memory
    conv = None
    convs = await db.list_conversations(limit=1)
    if not hasattr(process_message, '_tg_convs'):
        process_message._tg_convs = {}
    conv_id = process_message._tg_convs.get(user_id)
    if conv_id:
        conv = await db.get_conversation(conv_id)
    if not conv:
        conv_id = f\"conv-{uuid.uuid4().hex[:8]}\"
        await db.create_conversation(conv_id