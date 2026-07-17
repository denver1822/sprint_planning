from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import DomainError
from app.db.models import Participant, Room, Vote, VotingRound
from app.schemas.rooms import ParticipantResponse
from app.services.rooms import find_participant_by_token, get_room_or_404, serialize_room


async def authenticate_room_participant(
    session: AsyncSession, room_code: str, raw_token: str | None
) -> tuple[Room, Participant]:
    if not raw_token:
        raise DomainError("authentication_required", "Требуется токен участника", status_code=401)
    room = await get_room_or_404(session, room_code)
    participant = await find_participant_by_token(session, room.id, raw_token)
    if participant is None:
        raise DomainError("invalid_participant_token", "Недействительный токен участника", status_code=401)
    return room, participant


async def set_presence(session: AsyncSession, participant: Participant, online: bool) -> None:
    participant.is_online = online
    participant.last_seen_at = datetime.now(UTC)
    await session.commit()


async def has_voted_in_active_round(
    session: AsyncSession, room_id: UUID, participant_id: UUID
) -> bool:
    vote_id = await session.scalar(
        select(Vote.id)
        .join(VotingRound, VotingRound.id == Vote.round_id)
        .where(
            VotingRound.room_id == room_id,
            VotingRound.state == "VOTING",
            Vote.participant_id == participant_id,
        )
        .limit(1)
    )
    return vote_id is not None


async def room_snapshot(session: AsyncSession, room_code: str) -> dict[str, object]:
    room = await get_room_or_404(session, room_code)
    snapshot_round = None
    if room.state == "VOTING":
        snapshot_round = (
            await session.scalars(
                select(VotingRound)
                .where(VotingRound.room_id == room.id, VotingRound.state == "VOTING")
                .options(selectinload(VotingRound.votes))
            )
        ).one_or_none()
    elif room.state == "REVEALED":
        snapshot_round = (
            await session.scalars(
                select(VotingRound)
                .where(VotingRound.room_id == room.id, VotingRound.state == "REVEALED")
                .order_by(VotingRound.sequence.desc())
                .limit(1)
            )
        ).one_or_none()
    voted_participant_ids: set[UUID] = set()
    active_round_payload: dict[str, object] | None = None
    if snapshot_round is not None:
        if room.state == "VOTING":
            voted_participant_ids = {vote.participant_id for vote in snapshot_round.votes}
        active_round_payload = {
            "id": snapshot_round.id,
            "task_id": snapshot_round.task_id,
            "sequence": snapshot_round.sequence,
            "state": snapshot_round.state,
            "version": room.version,
            "started_at": snapshot_round.started_at,
        }

    serialized_room = serialize_room(room).model_dump(mode="json")
    serialized_room["participants"] = [
        ParticipantResponse(
            id=participant.id,
            display_name=participant.display_name,
            is_online=participant.is_online,
            is_owner=participant.id == room.owner_participant_id,
            is_observer=participant.is_observer,
            has_voted=participant.id in voted_participant_ids,
        ).model_dump(mode="json")
        for participant in sorted(room.participants, key=lambda item: item.created_at)
    ]
    # Do not add Vote.card_value to this structure. Only the future round.revealed event may do so.
    return {"room": serialized_room, "active_round": active_round_payload}


def presence_message(participant: Participant, owner_id: UUID | None, has_voted: bool = False) -> dict[str, object]:
    return {
        "type": "presence.changed",
        "payload": ParticipantResponse(
            id=participant.id,
            display_name=participant.display_name,
            is_online=participant.is_online,
            is_owner=participant.id == owner_id,
            is_observer=participant.is_observer,
            has_voted=has_voted,
        ).model_dump(mode="json"),
    }
