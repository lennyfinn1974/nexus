"""Tests for WebSocket connection management."""

from unittest.mock import AsyncMock


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
        assert ws_id in mgr.session_data

    async def test_reconnect_restores_session(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()
        mock_ws1 = AsyncMock()
        mock_ws1.send_text = AsyncMock()

        ws_id = await mgr.connect(mock_ws1)
        mgr.update_session_data(ws_id, {"conv_id": "conv-123"})
        await mgr.disconnect(ws_id, keep_session=True)

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
        assert mock_ws.send_text.call_count >= 2

    async def test_send_to_offline_client_queues(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()
        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()

        ws_id = await mgr.connect(mock_ws)
        await mgr.disconnect(ws_id, keep_session=True)

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

        await mgr.connect(ws1)
        await mgr.connect(ws2)

        await mgr.broadcast({"type": "announcement", "msg": "hello all"})
        assert ws1.send_text.call_count >= 2
        assert ws2.send_text.call_count >= 2

    async def test_broadcast_with_exclude(self):
        from websocket_manager import WebSocketManager

        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        ws1.send_text = AsyncMock()
        ws2.send_text = AsyncMock()

        id1 = await mgr.connect(ws1)
        await mgr.connect(ws2)

        initial_count_1 = ws1.send_text.call_count
        await mgr.broadcast({"type": "msg"}, exclude=[id1])
        assert ws1.send_text.call_count == initial_count_1
