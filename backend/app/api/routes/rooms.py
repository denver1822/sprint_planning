from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import participant_token
from app.db.session import get_db_session
from app.realtime.manager import room_connections
from app.schemas.rooms import (
    FinishRequest,
    NewRoundRequest,
    ParticipantSessionResponse,
    RevealRequest,
    RevealResponse,
    RoomCreateRequest,
    RoomJoinRequest,
    RoomResponse,
    RoomUpdateRequest,
    RoundResponse,
    RoundStartRequest,
    VoteRequest,
    VoteResponse,
)
from app.services.rooms import create_room, get_room_or_404, join_room, serialize_room, update_room
from app.services.voting import cast_vote, finish_room, new_round, reveal_round, start_round

router = APIRouter(prefix="/rooms", tags=["rooms"])
Session = Annotated[AsyncSession, Depends(get_db_session)]
ParticipantToken = Annotated[str | None, Depends(participant_token)]


@router.post("", response_model=ParticipantSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_room_endpoint(
    payload: RoomCreateRequest, session: Session
) -> ParticipantSessionResponse:
    return await create_room(session, payload)


@router.get("/{code}", response_model=RoomResponse)
async def get_room_endpoint(code: str, session: Session) -> RoomResponse:
    return serialize_room(await get_room_or_404(session, code))


@router.post("/{code}/join", response_model=ParticipantSessionResponse)
async def join_room_endpoint(
    code: str,
    payload: RoomJoinRequest,
    session: Session,
    token: ParticipantToken,
) -> ParticipantSessionResponse:
    return await join_room(session, code, payload, token)


@router.patch("/{code}", response_model=RoomResponse)
async def update_room_endpoint(
    code: str,
    payload: RoomUpdateRequest,
    session: Session,
    token: ParticipantToken,
) -> RoomResponse:
    return await update_room(session, code, payload, token)


@router.post("/{code}/rounds", response_model=RoundResponse)
async def start_round_endpoint(
    code: str, payload: RoundStartRequest, session: Session, token: ParticipantToken
) -> RoundResponse:
    result = await start_round(session, code, payload, token)
    await room_connections.broadcast(
        code, {"type": "round.started", "payload": result.model_dump(mode="json")}
    )
    return result


@router.put("/{code}/rounds/{round_id}/vote", response_model=VoteResponse)
async def vote_endpoint(
    code: str, round_id: UUID, payload: VoteRequest, session: Session, token: ParticipantToken
) -> VoteResponse:
    result = await cast_vote(session, code, round_id, payload, token)
    participant = await _participant_for_vote(session, code, token)
    await room_connections.broadcast(
        code,
        {
            "type": "vote.status_changed",
            "payload": {
                "participant_id": str(participant.id),
                "has_voted": True,
                "version": result.version,
            },
        },
    )
    return result


@router.post("/{code}/rounds/{round_id}/reveal", response_model=RevealResponse)
async def reveal_endpoint(
    code: str, round_id: UUID, payload: RevealRequest, session: Session, token: ParticipantToken
) -> RevealResponse:
    result = await reveal_round(session, code, round_id, payload, token)
    await room_connections.broadcast(
        code, {"type": "round.revealed", "payload": result.model_dump(mode="json")}
    )
    return result


@router.post("/{code}/rounds/{round_id}/new", response_model=RoundResponse)
async def new_round_endpoint(
    code: str, round_id: UUID, payload: NewRoundRequest, session: Session, token: ParticipantToken
) -> RoundResponse:
    result = await new_round(session, code, round_id, payload, token)
    await room_connections.broadcast(
        code, {"type": "round.started", "payload": result.model_dump(mode="json")}
    )
    return result


@router.post("/{code}/finish", response_model=RoomResponse)
async def finish_endpoint(
    code: str, payload: FinishRequest, session: Session, token: ParticipantToken
) -> RoomResponse:
    result = await finish_room(session, code, payload, token)
    await room_connections.broadcast(
        code, {"type": "room.finished", "payload": result.model_dump(mode="json")}
    )
    return result


async def _participant_for_vote(session: AsyncSession, code: str, token: str | None):
    from app.services.rooms import _require_participant

    room = await get_room_or_404(session, code)
    return await _require_participant(session, room.id, token)
