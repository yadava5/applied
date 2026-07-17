"""
WebSocket endpoints for real-time sync status updates.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])


class SyncWebSocketManager:
    """Tracks connected websocket clients and broadcasts sync events."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections)

        if not connections:
            return

        dead_connections: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        if dead_connections:
            async with self._lock:
                for connection in dead_connections:
                    self._connections.discard(connection)

    async def connection_count(self) -> int:
        async with self._lock:
            return len(self._connections)


sync_ws_manager = SyncWebSocketManager()


@router.websocket("/ws/sync-status")
async def sync_status_websocket(websocket: WebSocket) -> None:
    """
    Stream sync lifecycle events to connected clients.
    """
    await sync_ws_manager.connect(websocket)

    await websocket.send_json(
        {
            "event": "connected",
            "timestamp": datetime.now(UTC).isoformat(),
            "message": "Connected to sync status stream",
        }
    )

    try:
        while True:
            try:
                payload = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if payload.lower() == "ping":
                    await websocket.send_json(
                        {
                            "event": "pong",
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    )
            except asyncio.TimeoutError:
                await websocket.send_json(
                    {
                        "event": "heartbeat",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "connections": await sync_ws_manager.connection_count(),
                    }
                )
    except WebSocketDisconnect:
        await sync_ws_manager.disconnect(websocket)
    except Exception:
        await sync_ws_manager.disconnect(websocket)

