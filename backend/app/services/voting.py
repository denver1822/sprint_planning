from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import DomainError
from app.db.models import RoomAction, RoundResult, Vote, VotingRound
from app.schemas.rooms import (
    FinishRequest,
    NewRoundRequest,
    RevealRequest,
    RevealResponse,
    RoundResponse,
    RoundStartRequest,
    VoteRequest,
    VoteResponse,
)
from app.services.rooms import _require_participant, get_room_or_404, serialize_room


async def start_round(
    session: AsyncSession, code: str, data: RoundStartRequest, token: str | None
) -> RoundResponse:
    room = await get_room_or_404(session, code, lock=True)
    actor = await _active_actor(session, room.id, token)
    existing = await _idempotent_round(session, room.id, data.client_command_id)
    if existing:
        return _round_response(existing, room.version)
    await _version(session, room, data.expected_version)
    if room.state != "LOBBY":
        raise DomainError(
            "invalid_room_state", "Раунд можно начать только из лобби", status_code=409
        )
    round_ = await _create_round(session, room.id, data.task_id)
    room.state, room.version = "VOTING", room.version + 1
    session.add(
        RoomAction(
            room_id=room.id,
            actor_participant_id=actor.id,
            action_type="round_started",
            expected_version=data.expected_version,
            client_command_id=data.client_command_id,
            payload={"round_id": str(round_.id)},
        )
    )
    await session.commit()
    return _round_response(round_, room.version)


async def cast_vote(
    session: AsyncSession, code: str, round_id: UUID, data: VoteRequest, token: str | None
) -> VoteResponse:
    room = await get_room_or_404(session, code, lock=True)
    participant = await _active_actor(session, room.id, token)
    if participant.id == room.owner_participant_id:
        raise DomainError("owner_cannot_vote", "Владелец не голосует в MVP", status_code=403)
    round_ = await _active_round(session, room.id, round_id)
    card = next((card for card in room.deck.cards if card["value"] == data.card_value), None)
    if card is None:
        raise DomainError("invalid_card", "Карта отсутствует в колоде", status_code=422)
    vote = (
        await session.scalars(
            select(Vote)
            .where(Vote.round_id == round_.id, Vote.participant_id == participant.id)
            .with_for_update()
        )
    ).one_or_none()
    if vote is None:
        vote = Vote(
            round_id=round_.id,
            participant_id=participant.id,
            card_value=data.card_value,
            is_numeric=card["type"] == "numeric",
        )
        session.add(vote)
    else:
        vote.card_value, vote.is_numeric = data.card_value, card["type"] == "numeric"
    room.version += 1
    await session.commit()
    return VoteResponse(round_id=round_.id, card_value=vote.card_value, version=room.version)


async def reveal_round(
    session: AsyncSession, code: str, round_id: UUID, data: RevealRequest, token: str | None
) -> RevealResponse:
    room = await get_room_or_404(session, code, lock=True)
    actor = await _active_actor(session, room.id, token)
    round_ = (
        await session.scalars(
            select(VotingRound)
            .where(VotingRound.id == round_id, VotingRound.room_id == room.id)
            .options(selectinload(VotingRound.votes).selectinload(Vote.participant))
            .with_for_update()
        )
    ).one_or_none()
    if round_ is None:
        raise DomainError("round_not_found", "Раунд не найден", status_code=404)
    if round_.state == "REVEALED":
        return await _reveal_response(session, round_, room.version)
    await _version(session, room, data.expected_version)
    if round_.state != "VOTING" or room.state != "VOTING":
        raise DomainError("invalid_round_state", "Раунд нельзя раскрыть", status_code=409)
    if not round_.votes:
        raise DomainError("no_votes", "Нельзя раскрыть раунд без голосов", status_code=409)
    revealed = [
        {
            "participant_id": str(v.participant_id),
            "display_name": v.participant.display_name,
            "card_value": v.card_value,
            "is_numeric": v.is_numeric,
        }
        for v in round_.votes
    ]
    metrics = {
        "vote_count": len(revealed),
        "numeric_vote_count": sum(v["is_numeric"] for v in revealed),
    }
    round_.state, round_.revealed_at = "REVEALED", datetime.now(UTC)
    room.state, room.version = "REVEALED", room.version + 1
    session.add(RoundResult(round_id=round_.id, revealed_votes=revealed, metrics=metrics))
    session.add(
        RoomAction(
            room_id=room.id,
            actor_participant_id=actor.id,
            action_type="round_revealed",
            expected_version=data.expected_version,
            client_command_id=data.client_command_id,
            payload={"round_id": str(round_.id)},
        )
    )
    await session.commit()
    return RevealResponse(
        round=_round_response(round_, room.version), revealed_votes=revealed, metrics=metrics
    )


async def new_round(
    session: AsyncSession, code: str, previous_id: UUID, data: NewRoundRequest, token: str | None
) -> RoundResponse:
    room = await get_room_or_404(session, code, lock=True)
    actor = await _active_actor(session, room.id, token)
    existing = await _idempotent_round(session, room.id, data.client_command_id)
    if existing:
        return _round_response(existing, room.version)
    await _version(session, room, data.expected_version)
    previous = (
        await session.scalars(
            select(VotingRound).where(VotingRound.id == previous_id, VotingRound.room_id == room.id)
        )
    ).one_or_none()
    if previous is None or previous.state != "REVEALED" or room.state != "REVEALED":
        raise DomainError(
            "invalid_round_state", "Новый раунд доступен после reveal", status_code=409
        )
    round_ = await _create_round(session, room.id, previous.task_id)
    room.state, room.version = "VOTING", room.version + 1
    session.add(
        RoomAction(
            room_id=room.id,
            actor_participant_id=actor.id,
            action_type="round_started",
            expected_version=data.expected_version,
            client_command_id=data.client_command_id,
            payload={"round_id": str(round_.id)},
        )
    )
    await session.commit()
    return _round_response(round_, room.version)


async def finish_room(session: AsyncSession, code: str, data: FinishRequest, token: str | None):
    room = await get_room_or_404(session, code, lock=True)
    participant = await _require_participant(session, room.id, token)
    if participant.id != room.owner_participant_id:
        raise DomainError(
            "owner_required", "Завершить сессию может только владелец", status_code=403
        )
    await _version(session, room, data.expected_version)
    if room.state == "FINISHED":
        return serialize_room(room)
    room.state, room.finished_at, room.version = "FINISHED", datetime.now(UTC), room.version + 1
    session.add(
        RoomAction(
            room_id=room.id,
            actor_participant_id=participant.id,
            action_type="room_finished",
            expected_version=data.expected_version,
            client_command_id=data.client_command_id,
            payload={},
        )
    )
    await session.commit()
    return serialize_room(room)


async def _create_round(session, room_id, task_id):
    sequence = (
        await session.scalar(
            select(func.coalesce(func.max(VotingRound.sequence), 0)).where(
                VotingRound.room_id == room_id
            )
        )
    ) + 1
    round_ = VotingRound(
        room_id=room_id,
        task_id=task_id,
        sequence=sequence,
        state="VOTING",
        started_at=datetime.now(UTC),
    )
    session.add(round_)
    await session.flush()
    return round_


async def _active_actor(session, room_id, token):
    participant = await _require_participant(session, room_id, token)
    if not participant.is_online:
        raise DomainError("participant_offline", "Участник не подключён", status_code=403)
    return participant


async def _active_round(session, room_id, round_id):
    round_ = (
        await session.scalars(
            select(VotingRound)
            .where(VotingRound.id == round_id, VotingRound.room_id == room_id)
            .with_for_update()
        )
    ).one_or_none()
    if round_ is None:
        raise DomainError("round_not_found", "Раунд не найден", status_code=404)
    if round_.state != "VOTING":
        raise DomainError("invalid_round_state", "Голосование закрыто", status_code=409)
    return round_


async def _idempotent_round(session, room_id, command_id):
    action = (
        await session.scalars(
            select(RoomAction).where(
                RoomAction.room_id == room_id, RoomAction.client_command_id == command_id
            )
        )
    ).one_or_none()
    return (
        await session.get(VotingRound, UUID(action.payload["round_id"]))
        if action and action.payload.get("round_id")
        else None
    )


async def _reveal_response(session, round_, version):
    result = await session.get(RoundResult, round_.id)
    return RevealResponse(
        round=_round_response(round_, version),
        revealed_votes=result.revealed_votes,
        metrics=result.metrics,
    )


async def _version(session: AsyncSession, room, expected: int) -> None:
    if room.version != expected:
        from app.services.realtime import room_snapshot

        raise DomainError(
            "room_version_conflict",
            "Состояние комнаты изменилось",
            status_code=409,
            details={
                "current_version": room.version,
                "snapshot": await room_snapshot(session, room.public_code),
            },
        )


def _round_response(round_, version):
    return RoundResponse(
        id=round_.id,
        task_id=round_.task_id,
        sequence=round_.sequence,
        state=round_.state,
        version=version,
    )
