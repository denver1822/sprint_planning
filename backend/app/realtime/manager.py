import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

logger = logging.getLogger("planning_poker.websocket")


@dataclass(frozen=True)
class Connection:
    websocket: WebSocket
    participant_id: UUID


class RoomConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[Connection]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, room_code: str, participant_id: UUID, websocket: WebSocket) -> bool:
        await websocket.accept()
        async with self._lock:
            was_online = self.is_participant_connected(room_code, participant_id)
            self._connections[room_code].add(Connection(websocket, participant_id))
        return not was_online

    async def disconnect(self, room_code: str, participant_id: UUID, websocket: WebSocket) -> bool:
        async with self._lock:
            connections = self._connections.get(room_code)
            if connections is None:
                return False
            connections.discard(Connection(websocket, participant_id))
            is_still_online = self.is_participant_connected(room_code, participant_id)
            if not connections:
                self._connections.pop(room_code, None)
        return not is_still_online

    async def send(self, websocket: WebSocket, message: dict[str, object]) -> None:
        await websocket.send_json(jsonable_encoder(message))

    async def broadcast(self, room_code: str, message: dict[str, object]) -> None:
        async with self._lock:
            connections = list(self._connections.get(room_code, set()))
        stale_connections: list[Connection] = []
        for connection in connections:
            try:
                await connection.websocket.send_json(jsonable_encoder(message))
            except Exception:
                stale_connections.append(connection)
        for connection in stale_connections:
            logger.debug("removing stale websocket room_code=%s", room_code)
            await self.disconnect(room_code, connection.participant_id, connection.websocket)

    def is_participant_connected(self, room_code: str, participant_id: UUID) -> bool:
        return any(
            connection.participant_id == participant_id
            for connection in self._connections.get(room_code, set())
        )


room_connections = RoomConnectionManager()
