from collections import Counter
from datetime import UTC, datetime
from math import sqrt
from statistics import median
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import DomainError
from app.db.models import RoomAction, RoundResult, TaskItem, Vote, VotingRound
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
    task_id = data.task_id if data.task_id is not None else room.active_task_id
    if any(not task.is_excluded for task in room.tasks) and task_id is None:
        raise DomainError("task_required", "Выберите задачу перед началом голосования", status_code=409)
    if task_id is not None:
        task = await session.get(TaskItem, task_id)
        if task is None or task.room_id != room.id:
            raise DomainError("task_not_found", "Задача не найдена в этой комнате", status_code=404)
        if task.is_excluded:
            raise DomainError("task_excluded", "Исключённую задачу нельзя оценивать", status_code=409)
    round_ = await _create_round(session, room.id, task_id)
    if task_id is None:
        position = await session.scalar(
            select(func.coalesce(func.max(TaskItem.position), -1) + 1).where(TaskItem.room_id == room.id)
        )
        task = TaskItem(
            room_id=room.id,
            title=f"Задача {position + 1}",
            position=position,
            source="auto",
        )
        session.add(task)
        await session.flush()
        round_.task_id = task.id
        room.active_task_id = task.id
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
    if participant.is_observer:
        raise DomainError("observer_cannot_vote", "Наблюдатель не участвует в голосовании", status_code=403)
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


async def cancel_vote(
    session: AsyncSession, code: str, round_id: UUID, token: str | None
) -> int:
    room = await get_room_or_404(session, code, lock=True)
    participant = await _active_actor(session, room.id, token)
    round_ = await _active_round(session, room.id, round_id)
    vote = (
        await session.scalars(
            select(Vote)
            .where(Vote.round_id == round_.id, Vote.participant_id == participant.id)
            .with_for_update()
        )
    ).one_or_none()
    if vote is None:
        raise DomainError("vote_not_found", "Подтверждённый голос не найден", status_code=404)
    await session.delete(vote)
    room.version += 1
    await session.commit()
    return room.version


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
    metrics = calculate_metrics(revealed)
    if round_.task_id is None:
        position = await session.scalar(
            select(func.coalesce(func.max(TaskItem.position), -1) + 1).where(TaskItem.room_id == room.id)
        )
        task = TaskItem(
            room_id=room.id,
            title=f"Задача {position + 1}",
            position=position,
            source="auto",
        )
        session.add(task)
        await session.flush()
        round_.task_id = task.id
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
    manually_selected_task_id = (
        room.active_task_id if room.active_task_id not in {None, previous.task_id} else None
    )
    next_task = _next_unestimated_task(room)
    task_id = previous.task_id if data.repeat_task else manually_selected_task_id or (next_task.id if next_task else None)
    if task_id is not None:
        task = await session.get(TaskItem, task_id)
        if task is None or task.room_id != room.id:
            raise DomainError("task_not_found", "Задача не найдена в этой комнате", status_code=404)
        if task.is_excluded:
            raise DomainError("task_excluded", "Исключённую задачу нельзя оценивать", status_code=409)
    round_ = await _create_round(session, room.id, task_id)
    if task_id is None:
        position = await session.scalar(
            select(func.coalesce(func.max(TaskItem.position), -1) + 1).where(TaskItem.room_id == room.id)
        )
        task = TaskItem(
            room_id=room.id,
            title=f"Задача {position + 1}",
            position=position,
            source="auto",
        )
        session.add(task)
        await session.flush()
        round_.task_id = task.id
        room.active_task_id = task.id
    else:
        room.active_task_id = task_id
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
    await session.refresh(
        room, attribute_names=["deck", "participants", "tasks", "created_at", "updated_at"]
    )
    return serialize_room(room)


def _next_unestimated_task(room) -> TaskItem | None:
    """Return the first task in the list that has not received a vote yet."""
    tasks = sorted(
        (
            task
            for task in room.tasks
            if not task.is_excluded and not any(round_.votes for round_ in task.rounds)
        ),
        key=lambda task: task.position,
    )
    if not tasks:
        return None
    return tasks[0]


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


def calculate_metrics(revealed_votes: list[dict[str, object]]) -> dict[str, object]:
    numeric_values = [float(vote["card_value"]) for vote in revealed_votes if vote["is_numeric"]]
    numeric_distribution = Counter(
        str(vote["card_value"]) for vote in revealed_votes if vote["is_numeric"]
    )
    special_cards = Counter(
        str(vote["card_value"]) for vote in revealed_votes if not vote["is_numeric"]
    )
    numeric_count = len(numeric_values)
    base: dict[str, object] = {
        "vote_count": len(revealed_votes),
        "numeric_vote_count": numeric_count,
        "special_vote_count": len(revealed_votes) - numeric_count,
        "distribution": dict(numeric_distribution),
        "special_cards": dict(special_cards),
        "mean": None,
        "median": None,
        "min": None,
        "max": None,
        "range": None,
        "stddev": None,
        "coefficient_of_variation": None,
        "mode_share": None,
        "exact_consensus": False,
        "agreement_index": None,
    }
    if not numeric_values:
        return base
    mean = sum(numeric_values) / numeric_count
    minimum, maximum = min(numeric_values), max(numeric_values)
    value_range = maximum - minimum
    stddev = sqrt(sum((value - mean) ** 2 for value in numeric_values) / numeric_count)
    mode_share = max(Counter(numeric_values).values()) / numeric_count
    agreement_index: float | None
    if numeric_count < 2:
        agreement_index = None
    elif value_range == 0:
        agreement_index = 1.0
    else:
        agreement_index = max(0.0, min(1.0, 1 - stddev / value_range))
    base.update(
        {
            "mean": mean,
            "median": float(median(numeric_values)),
            "min": minimum,
            "max": maximum,
            "range": value_range,
            "stddev": stddev,
            "coefficient_of_variation": stddev / mean if mean else None,
            "mode_share": mode_share,
            "exact_consensus": numeric_count >= 2 and value_range == 0,
            "agreement_index": agreement_index,
        }
    )
    return base
