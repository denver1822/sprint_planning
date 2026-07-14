from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import participant_token
from app.db.session import get_db_session
from app.schemas.rooms import ParticipantSessionResponse, RoomCreateRequest, RoomJoinRequest, RoomResponse, RoomUpdateRequest
from app.services.rooms import create_room, get_room_or_404, join_room, serialize_room, update_room

router = APIRouter(prefix="/rooms", tags=["rooms"])
Session = Annotated[AsyncSession, Depends(get_db_session)]
ParticipantToken = Annotated[str | None, Depends(participant_token)]


@router.post("", response_model=ParticipantSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_room_endpoint(payload: RoomCreateRequest, session: Session) -> ParticipantSessionResponse:
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
