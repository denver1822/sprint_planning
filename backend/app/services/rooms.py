from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import DomainError
from app.core.security import new_participant_token, new_public_code, token_hash
from app.db.models import Deck, Participant, Room
from app.schemas.rooms import (
    DeckInput,
    ParticipantResponse,
    ParticipantSessionResponse,
    RoomCreateRequest,
    RoomJoinRequest,
    RoomResponse,
    RoomUpdateRequest,
)
from app.services.decks import deck_response, resolve_cards


def _room_query(code: str):
    return (
        select(Room)
        .where(Room.public_code == code)
        .options(selectinload(Room.deck), selectinload(Room.participants))
    )


async def get_room_or_404(session: AsyncSession, code: str, *, lock: bool = False) -> Room:
    query = _room_query(code)
    if lock:
        query = query.with_for_update()
    room = (await session.scalars(query)).one_or_none()
    if room is None:
        raise DomainError("room_not_found", "Комната не найдена", status_code=404)
    return room


def serialize_participant(participant: Participant, owner_id: UUID | None) -> ParticipantResponse:
    return ParticipantResponse(
        id=participant.id,
        display_name=participant.display_name,
        is_online=participant.is_online,
        is_owner=participant.id == owner_id,
    )


def serialize_room(room: Room) -> RoomResponse:
    if room.deck is None:
        raise RuntimeError("Room has no deck")
    participants = [
        serialize_participant(participant, room.owner_participant_id)
        for participant in sorted(room.participants, key=lambda item: item.created_at)
    ]
    return RoomResponse(
        code=room.public_code,
        name=room.name,
        state=room.state,
        version=room.version,
        deck=deck_response(room.deck.kind, room.deck.cards),
        participants=participants,
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


async def create_room(session: AsyncSession, payload: RoomCreateRequest) -> ParticipantSessionResponse:
    now = datetime.now(UTC)
    room = Room(
        public_code=new_public_code(),
        name=_normalize_name(payload.name),
        state="LOBBY",
        version=0,
    )
    cards = resolve_cards(payload.deck)
    room.deck = Deck(kind=payload.deck.kind.value, cards=cards)

    raw_token = new_participant_token()
    owner = Participant(
        display_name=_normalize_name(payload.owner_name),
        token_hash=token_hash(raw_token),
        is_online=True,
        last_seen_at=now,
    )
    room.participants.append(owner)
    session.add(room)
    await session.flush()
    room.owner_participant_id = owner.id
    await session.commit()
    await session.refresh(room, attribute_names=["deck", "participants", "created_at", "updated_at"])

    return ParticipantSessionResponse(
        room=serialize_room(room),
        participant=serialize_participant(owner, owner.id),
        participant_token=raw_token,
        restored=False,
    )


async def join_room(
    session: AsyncSession,
    code: str,
    payload: RoomJoinRequest,
    presented_token: str | None,
) -> ParticipantSessionResponse:
    room = await get_room_or_404(session, code, lock=True)
    if room.state == "FINISHED":
        raise DomainError("room_finished", "Сессия завершена", status_code=409)

    now = datetime.now(UTC)
    if presented_token:
        participant = await _find_participant_by_token(session, room.id, presented_token)
        if participant is not None:
            participant.is_online = True
            participant.last_seen_at = now
            await session.commit()
            await session.refresh(room, attribute_names=["deck", "participants", "created_at", "updated_at"])
            return ParticipantSessionResponse(
                room=serialize_room(room),
                participant=serialize_participant(participant, room.owner_participant_id),
                participant_token=None,
                restored=True,
            )

    if payload.display_name is None:
        raise DomainError("display_name_required", "Укажите отображаемое имя", status_code=422)

    raw_token = new_participant_token()
    participant = Participant(
        room_id=room.id,
        display_name=_normalize_name(payload.display_name),
        token_hash=token_hash(raw_token),
        is_online=True,
        last_seen_at=now,
    )
    session.add(participant)
    await session.commit()
    await session.refresh(room, attribute_names=["deck", "participants", "created_at", "updated_at"])
    return ParticipantSessionResponse(
        room=serialize_room(room),
        participant=serialize_participant(participant, room.owner_participant_id),
        participant_token=raw_token,
        restored=False,
    )


async def update_room(
    session: AsyncSession,
    code: str,
    payload: RoomUpdateRequest,
    presented_token: str | None,
) -> RoomResponse:
    room = await get_room_or_404(session, code, lock=True)
    participant = await _require_participant(session, room.id, presented_token)
    if participant.id != room.owner_participant_id:
        raise DomainError("owner_required", "Действие доступно только владельцу", status_code=403)
    if room.state == "FINISHED":
        raise DomainError("room_finished", "Сессия завершена", status_code=409)
    if room.version != payload.expected_version:
        raise DomainError(
            "room_version_conflict",
            "Состояние комнаты изменилось",
            status_code=409,
            details={"current_version": room.version},
        )

    if payload.name is not None:
        room.name = _normalize_name(payload.name)
    if payload.deck is not None:
        _apply_deck_update(room.deck, payload.deck)
    room.version += 1
    await session.commit()
    await session.refresh(room, attribute_names=["deck", "participants", "created_at", "updated_at"])
    return serialize_room(room)


async def _find_participant_by_token(
    session: AsyncSession, room_id: UUID, raw_token: str
) -> Participant | None:
    query = select(Participant).where(
        Participant.room_id == room_id,
        Participant.token_hash == token_hash(raw_token),
    )
    return (await session.scalars(query)).one_or_none()


async def _require_participant(
    session: AsyncSession, room_id: UUID, raw_token: str | None
) -> Participant:
    if not raw_token:
        raise DomainError("authentication_required", "Требуется токен участника", status_code=401)
    participant = await _find_participant_by_token(session, room_id, raw_token)
    if participant is None:
        raise DomainError("invalid_participant_token", "Недействительный токен участника", status_code=401)
    return participant


def _apply_deck_update(deck: Deck, payload: DeckInput) -> None:
    deck.kind = payload.kind.value
    deck.cards = resolve_cards(payload)


def _normalize_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise DomainError("invalid_name", "Имя не может быть пустым")
    return normalized

