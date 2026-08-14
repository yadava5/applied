"""
WebSocket endpoints for real-time sync status updates.

DESKTOP ONLY. The router below is mounted by ``jobtracker.main`` and by
nothing else: the Vercel Python runtime does not support WebSocket, so
``jobtracker.main_cloud`` never includes it — and, per
``tests/test_desktop_routers_are_not_mounted.py``, never even *imports* this
module. See :func:`websocket_transport_available` for why ``broadcast`` still
carries an explicit guard when the router cannot be mounted at all.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from jobtracker.config import settings

router = APIRouter(tags=["websocket"])


def websocket_transport_available() -> bool:
    """False where no WebSocket router can be mounted (issue #23, C7).

    The transport is a property of the *deployment*, not of this module: on
    ``deployment == "cloud"`` the app is served by Vercel's Python runtime,
    which has no WebSocket support, so there is no router, no connection, and
    nothing a broadcast could reach.

    Read from ``settings`` at call time rather than captured at import. A
    serverless instance outlives many requests and the test fixtures rebind the
    settings singleton; a module-level snapshot would answer for whatever the
    environment happened to be when the first import ran.

    Why the guard exists at all, given the cloud app cannot import this file:
    ``broadcast`` is called from ``jobtracker/api/sync.py`` on every sync event,
    and the *criterion* in issue #23 is that those call sites keep working in
    both deployments. Relying on "there happen to be no connections" satisfies
    it by accident — it is the same green either way, and it would stop being
    true the moment anything else registered a connection object. An explicit
    predicate is a statement instead of a coincidence, and it is testable.
    """

    return settings.deployment != "cloud"


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
        """Fan a sync event out to every connected client.

        A **no-op** where the WebSocket router is absent (see
        :func:`websocket_transport_available`), checked before the lock is even
        taken so a caller in a deployment with no transport pays nothing. The
        call sites in ``jobtracker/api/sync.py`` are therefore unconditional and
        identical in both deployments — no ``if`` at the call site, no second
        code path to keep correct.
        """

        if not websocket_transport_available():
            return

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

