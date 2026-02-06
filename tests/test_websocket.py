"""Tests for WebSocket chat flow and connection management."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestWebSocketManager:
    """Unit tests for WebSocketManager."""

    async def test_connect_creates_session(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()
        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()

        ws_id = await mgr.connect(mock_ws)
        assert ws_id.startswith("ws-")
        assert ws_id in mgr.connections
        assert ws_id in mgr.session_data
        mock_ws.accept.assert_awaited_once()

    async def test_disconnect_removes_connection(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()
        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()

        ws_id = await mgr.connect(mock_ws)
        await mgr.disconnect(ws_id, keep_session=False)
        assert ws_id not in mgr.connections
        assert ws_id not in mgr.session_data

    async def test_disconnect_keeps_session(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()
        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()

        ws_id = await mgr.connect(mock_ws)
        await mgr.disconnect(ws_id, keep_session=True)
        assert ws_id not in mgr.connections
        assert ws_id in mgr.session_data  # Session preserved

    async def test_reconnect_restores_session(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()
        mock_ws1 = AsyncMock()
        mock_ws1.send_text = AsyncMock()

        ws_id = await mgr.connect(mock_ws1)
        mgr.update_session_data(ws_id, {"conv_id": "conv-123"})
        await mgr.disconnect(ws_id, keep_session=True)

        # Reconnect with same session_id
        mock_ws2 = AsyncMock()
        mock_ws2.send_text = AsyncMock()
        ws_id_2 = await mgr.connect(mock_ws2, session_id=ws_id)
        assert ws_id_2 == ws_id
        assert mgr.get_session_data(ws_id)["conv_id"] == "conv-123"

    async def test_send_to_online_client(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()
        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()

        ws_id = await mgr.connect(mock_ws)
        await mgr.send_to_client(ws_id, {"type": "test", "data": "hello"})
        # Should have sent session_info + our message
        assert mock_ws.send_text.call_count >= 2

    async def test_send_to_offline_client_queues(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()
        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()

        ws_id = await mgr.connect(mock_ws)
        await mgr.disconnect(ws_id, keep_session=True)

        # Send to offline client
        await mgr.send_to_client(ws_id, {"type": "test", "data": "queued"})
        assert len(mgr.message_queues[ws_id]) == 1

    async def test_update_session_data(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()
        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()

        ws_id = await mgr.connect(mock_ws)
        mgr.update_session_data(ws_id, {"conv_id": "conv-xyz", "force_model": "claude"})

        data = mgr.get_session_data(ws_id)
        assert data["conv_id"] == "conv-xyz"
        assert data["force_model"] == "claude"

    async def test_broadcast(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()

        ws1, ws2 = AsyncMock(), AsyncMock()
        ws1.send_text = AsyncMock()
        ws2.send_text = AsyncMock()

        id1 = await mgr.connect(ws1)
        id2 = await mgr.connect(ws2)

        await mgr.broadcast({"type": "announcement", "msg": "hello all"})
        # Both should have received the broadcast (plus session_info)
        assert ws1.send_text.call_count >= 2
        assert ws2.send_text.call_count >= 2

    async def test_broadcast_with_exclude(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()

        ws1, ws2 = AsyncMock(), AsyncMock()
        ws1.send_text = AsyncMock()
        ws2.send_text = AsyncMock()

        id1 = await mgr.connect(ws1)
        id2 = await mgr.connect(ws2)

        initial_count_1 = ws1.send_text.call_count

        await mgr.broadcast({"type": "msg"}, exclude=[id1])
        # ws1 should NOT have received the broadcast
        assert ws1.send_text.call_count == initial_count_1


class TestWebSocketChatFlow:
    """Integration tests for the WebSocket chat endpoint."""

    async def test_websocket_connect(self, test_app):
        from httpx import ASGITransport, AsyncClient
        from starlette.testclient import TestClient

        # Use Starlette's TestClient for WebSocket testing
        with TestClient(test_app) as tc:
            with tc.websocket_connect("/ws/chat") as ws:
                data = ws.receive_json()
                assert data["type"] == "session_info"
                assert "session_id" in data

    async def test_websocket_set_conversation(self, test_app, test_db):
        from starlette.testclient import TestClient

        await test_db.create_conversation("conv-ws-test", title="WS Test")

        with TestClient(test_app) as tc:
            with tc.websocket_connect("/ws/chat") as ws:
                ws.receive_json()  # session_info
                ws.send_json({"type": "set_conversation", "conv_id": "conv-ws-test"})
                resp = ws.receive_json()
                # Skip pings
                while resp.get("type") == "ping":
                    ws.send_json({"type": "pong"})
                    resp = ws.receive_json()
                assert resp["type"] == "conversation_set"
                assert resp["conv_id"] == "conv-ws-test"

    async def test_websocket_create_new_conversation(self, test_app):
        from starlette.testclient import TestClient

        with TestClient(test_app) as tc:
            with tc.websocket_connect("/ws/chat") as ws:
                ws.receive_json()  # session_info
                ws.send_json({"type": "set_conversation"})
                resp = ws.receive_json()
                while resp.get("type") == "ping":
                    ws.send_json({"type": "pong"})
                    resp = ws.receive_json()
                assert resp["type"] == "conversation_set"
                assert resp["conv_id"].startswith("conv-")

    async def test_websocket_slash_command(self, test_app):
        from starlette.testclient import TestClient

        with TestClient(test_app) as tc:
            with tc.websocket_connect("/ws/chat") as ws:
                ws.receive_json()  # session_info
                ws.send_json({"type": "message", "text": "/skills"})
                resp = ws.receive_json()
                while resp.get("type") == "ping":
                    ws.send_json({"type": "pong"})
                    resp = ws.receive_json()
                assert resp["type"] == "message"

    async def test_websocket_empty_message_ignored(self, test_app):
        from starlette.testclient import TestClient

        with TestClient(test_app) as tc:
            with tc.websocket_connect("/ws/chat") as ws:
                ws.receive_json()  # session_info
                ws.send_json({"type": "message", "text": ""})
                # Should not crash, no response for empty message
                # Send a valid message to verify connection is still alive
                ws.send_json({"type": "message", "text": "/status"})
                resp = ws.receive_json()
                while resp.get("type") == "ping":
                    ws.send_json({"type": "pong"})
                    resp = ws.receive_json()
                assert resp["type"] in ("message", "system")
