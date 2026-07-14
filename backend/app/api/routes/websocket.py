from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.session import SessionLocal
from app.realtime.manager import room_connections
from app.services.realtime import (
    authenticate_room_participant,
    has_voted_in_active_round,
    presence_message,
    room_snapshot,
    set_presence,
)

router = APIRouter(tags=["realtime"])


@router.websocket("/rooms/{code}")
async def room_websocket(websocket: WebSocket, code: str) -> None:
    if not _origin_is_allowed(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    raw_token = websocket.query_params.get("participant_token")
    async with SessionLocal() as session:
        try:
            room, participant = await authenticate_room_participant(session, code, raw_token)
        except DomainError:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        became_online = await room_connections.connect(code, participant.id, websocket)
        if became_online:
            await set_presence(session, participant, online=True)
            await room_connections.broadcast(
                code,
                presence_message(
                    participant,
                    room.owner_participant_id,
                    await has_voted_in_active_round(session, room.id, participant.id),
                ),
            )

        await room_connections.send(
            websocket,
            {"type": "room.snapshot", "payload": await room_snapshot(session, code)},
        )

        try:
            while True:
                incoming = await websocket.receive_json()
                if incoming.get("type") == "resync":
                    await room_connections.send(
                        websocket,
                        {"type": "room.snapshot", "payload": await room_snapshot(session, code)},
                    )
                elif incoming.get("type") == "ping":
                    await room_connections.send(websocket, {"type": "pong", "payload": {}})
                else:
                    await room_connections.send(
                        websocket,
                        {
                            "type": "error",
                            "payload": {
                                "code": "unsupported_message",
                                "message": "Неподдерживаемое WebSocket-сообщение",
                            },
                        },
                    )
        except WebSocketDisconnect:
            pass
        finally:
            became_offline = await room_connections.disconnect(code, participant.id, websocket)
            if became_offline:
                await set_presence(session, participant, online=False)
                await room_connections.broadcast(
                    code,
                    presence_message(
                        participant,
                        room.owner_participant_id,
                        await has_voted_in_active_round(session, room.id, participant.id),
                    ),
                )


def _origin_is_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    return origin is None or origin == get_settings().frontend_origin
