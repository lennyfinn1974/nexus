"""WebSocket chat handler with streaming and tool loop."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from core.message_processor import process_message, process_skill_actions
from core.system_prompt import build_system_prompt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websocket_manager import websocket_manager

logger = logging.getLogger("nexus.ws")

router = APIRouter()

MAX_TOOL_ROUNDS = 5


def _get_state(ws: WebSocket) -> Any:
    """Access AppState from the WebSocket's app."""
    return ws.app.state.nexus


@router.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    s = _get_state(ws)

    # ── Origin check ──
    allowed_origins = s.allowed_origins
    origin = ws.headers.get("origin")
    if origin and origin not in allowed_origins:
        logger.warning(f"WebSocket rejected: origin {origin!r} not in ALLOWED_ORIGINS")
        await ws.close(code=4003, reason="Origin not allowed")
        return

    # ── Reconnection ──
    session_id = ws.query_params.get("session_id")
    ws_id = await websocket_manager.connect(ws, session_id)

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "pong":
                continue

            # ── Switch conversation ──
            if msg.get("type") == "set_conversation":
                await _handle_set_conversation(ws_id, msg, s)
                continue

            text = msg.get("text", "").strip()
            if not text:
                continue

            # ── Model override ──
            if text.startswith("/model "):
                choice = text[7:].strip().lower()
                if choice in ("claude", "local", "ollama"):
                    force = "claude" if choice == "claude" else "ollama"
                    websocket_manager.update_session_data(ws_id, {"force_model": force})
                    await websocket_manager.send_to_client(
                        ws_id, {"type": "system", "content": f"Model set to: {choice}"}
                    )
                else:
                    websocket_manager.update_session_data(ws_id, {"force_model": None})
                    await websocket_manager.send_to_client(ws_id, {"type": "system", "content": "Model set to: auto"})
                continue

            # ── Slash commands ──
            if text.startswith("/"):
                session_data = websocket_manager.get_session_data(ws_id)
                force_model = session_data.get("force_model") if session_data else None
                response = await process_message(
                    ws_id,
                    text,
                    cfg=s.cfg,
                    db=s.db,
                    skills_engine=s.skills_engine,
                    model_router=s.model_router,
                    task_queue=s.task_queue,
                    plugin_manager=s.plugin_manager,
                    tool_executor=getattr(s, "tool_executor", None),
                    force_model=force_model,
                )
                await websocket_manager.send_to_client(
                    ws_id, {"type": "message", "content": response, "model": "system"}
                )
                continue

            # ── Ensure conversation exists ──
            session_data = websocket_manager.get_session_data(ws_id)
            conv_id = session_data.get("conv_id") if session_data else None
            force_model = session_data.get("force_model") if session_data else None

            if not conv_id:
                conv_id = f"conv-{uuid.uuid4().hex[:8]}"
                await s.db.create_conversation(conv_id, title=text[:50])
                websocket_manager.update_session_data(ws_id, {"conv_id": conv_id})
                await websocket_manager.send_to_client(
                    ws_id,
                    {
                        "type": "conversation_set",
                        "conv_id": conv_id,
                        "title": text[:50],
                    },
                )

            try:
                await _stream_and_tool_loop(ws_id, text, conv_id, force_model, s)
            except Exception as e:
                logger.error(f"Message processing error: {e}", exc_info=True)
                await websocket_manager.send_to_client(ws_id, {"type": "error", "content": f"Error: {e}"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {ws_id}")
        await websocket_manager.disconnect(ws_id, keep_session=True)
    except Exception as e:
        logger.error(f"WebSocket fatal error: {e}", exc_info=True)
        try:
            await websocket_manager.send_to_client(ws_id, {"type": "error", "content": f"Server error: {e}"})
        except Exception:
            pass
        finally:
            await websocket_manager.disconnect(ws_id, keep_session=True)


async def _handle_set_conversation(ws_id: str, msg: dict, s: Any) -> None:
    """Handle set_conversation message type."""
    new_id = msg.get("conv_id")
    if new_id:
        conv = await s.db.get_conversation(new_id)
        if conv:
            websocket_manager.update_session_data(ws_id, {"conv_id": new_id})
            logger.info(f"[{ws_id}] Switched to conversation {new_id}")
            await websocket_manager.send_to_client(
                ws_id,
                {
                    "type": "conversation_set",
                    "conv_id": new_id,
                    "title": conv["title"],
                },
            )
        else:
            logger.warning(f"[{ws_id}] Conversation {new_id} not found, creating new")
            conv_id = f"conv-{uuid.uuid4().hex[:8]}"
            await s.db.create_conversation(conv_id, title="New Conversation")
            websocket_manager.update_session_data(ws_id, {"conv_id": conv_id})
            await websocket_manager.send_to_client(
                ws_id,
                {
                    "type": "conversation_set",
                    "conv_id": conv_id,
                    "title": "New Conversation",
                },
            )
    else:
        conv_id = f"conv-{uuid.uuid4().hex[:8]}"
        await s.db.create_conversation(conv_id, title="New Conversation")
        websocket_manager.update_session_data(ws_id, {"conv_id": conv_id})
        logger.info(f"[{ws_id}] Created new conversation {conv_id}")
        await websocket_manager.send_to_client(
            ws_id,
            {
                "type": "conversation_set",
                "conv_id": conv_id,
                "title": "New Conversation",
            },
        )


async def _stream_and_tool_loop(
    ws_id: str,
    text: str,
    conv_id: str,
    force_model: str | None,
    s: Any,
) -> None:
    """Build context, stream AI response, and run the tool loop."""
    tool_mode = getattr(s.cfg, "tool_calling_mode", "legacy") if s.cfg else "legacy"

    # Build context
    skill_context = await s.skills_engine.build_skill_context(text)
    system = build_system_prompt(s.cfg, s.plugin_manager, tool_calling_mode=tool_mode)
    if skill_context:
        system += f"\n\n{skill_context}"

    history = await s.db.get_conversation_messages(conv_id, limit=20)
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": text})
    await s.db.add_message(conv_id, "user", text)

    # Auto-title after first message
    if len(history) == 0:
        title = text[:60].strip()
        if len(text) > 60:
            title = title.rsplit(" ", 1)[0] + "..."
        await s.db.rename_conversation(conv_id, title)
        await websocket_manager.send_to_client(
            ws_id,
            {
                "type": "conversation_renamed",
                "conv_id": conv_id,
                "title": title,
            },
        )

    # ── Stream + Tool Loop ──
    round_num = 0
    final_response = ""

    while round_num <= MAX_TOOL_ROUNDS:
        model_name, stream = await s.model_router.chat_stream(messages, system=system, force_model=force_model)
        await websocket_manager.send_to_client(ws_id, {"type": "stream_start", "model": model_name})

        full_response = ""
        async for chunk in stream:
            full_response += chunk
            await websocket_manager.send_to_client(ws_id, {"type": "stream_chunk", "content": chunk})

        await websocket_manager.send_to_client(ws_id, {"type": "stream_end", "model": model_name})

        # ── Check for tool calls ──
        tool_results = []

        # Native tool calling (if tool_executor available and mode is native)
        tool_executor = getattr(s, "tool_executor", None)
        if tool_executor and tool_mode == "native":
            # In native mode, tool calls come as structured data from the model
            # For now, also check legacy patterns as fallback
            pass

        # Legacy regex-based tool calls
        cleaned, plugin_results = await s.plugin_manager.process_tool_calls(full_response)
        if plugin_results:
            tool_results.extend(plugin_results)

        skill_results = await process_skill_actions(full_response, s.skills_engine)
        if skill_results:
            tool_results.extend(skill_results)

        if not tool_results:
            final_response = full_response
            break

        round_num += 1
        if round_num > MAX_TOOL_ROUNDS:
            final_response = full_response
            logger.warning(f"[{ws_id}] Hit max tool rounds ({MAX_TOOL_ROUNDS})")
            break

        # Format tool feedback
        tool_feedback_parts = []
        for tr in tool_results:
            name = tr["tool"]
            if "result" in tr:
                tool_feedback_parts.append(f"**{name}** returned:\n{tr['result']}")
            else:
                tool_feedback_parts.append(f"**{name}** error: {tr.get('error', 'unknown')}")
        tool_feedback = "\n\n".join(tool_feedback_parts)

        await websocket_manager.send_to_client(
            ws_id, {"type": "system", "content": f"Executed {len(tool_results)} tool(s)..."}
        )

        messages.append({"role": "assistant", "content": full_response})
        messages.append(
            {
                "role": "user",
                "content": f"[Tool Results -- Round {round_num}]\n\n"
                f"{tool_feedback}\n\n"
                f"Use these results to continue. If you need more tools, "
                f"call them. Otherwise give your final answer.",
            }
        )

    await s.db.add_message(conv_id, "assistant", final_response, model_used=model_name)
