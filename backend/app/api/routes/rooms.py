from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import participant_token
from app.db.session import get_db_session
from app.realtime.manager import room_connections
from app.services.realtime import room_snapshot
from app.schemas.rooms import (
    ActiveTaskRequest,
    FinishRequest,
    NewRoundRequest,
    ParticipantSessionResponse,
    RevealRequest,
    RevealResponse,
    RoomCreateRequest,
    RoomJoinRequest,
    RoomResponse,
    RoomUpdateRequest,
    RoundHistoryResponse,
    RoundResponse,
    RoundStartRequest,
    VoteRequest,
    VoteResponse,
    TaskCreateRequest,
    TaskReorderRequest,
    TaskResponse,
)
from app.services.rooms import create_room, get_room_or_404, join_room, serialize_room, update_room
from app.services.tasks import create_task, reorder_tasks, set_active_task
from app.services.voting import cancel_vote, cast_vote, finish_room, new_round, reveal_round, start_round

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


@router.get("/{code}/snapshot")
async def get_room_snapshot_endpoint(code: str, session: Session) -> dict[str, object]:
    """Return the current realtime-safe snapshot for HTTP resynchronization."""
    return await room_snapshot(session, code)


@router.get("/{code}/history", response_model=list[RoundHistoryResponse])
async def get_history_endpoint(code: str, session: Session) -> list[RoundHistoryResponse]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models import VotingRound

    room = await get_room_or_404(session, code)
    rounds = (
        await session.scalars(
            select(VotingRound)
            .where(VotingRound.room_id == room.id, VotingRound.state == "REVEALED")
            .options(selectinload(VotingRound.result), selectinload(VotingRound.task))
            .order_by(VotingRound.sequence)
        )
    ).all()
    return [
        RoundHistoryResponse(
            id=round_.id,
            sequence=round_.sequence,
            task_id=round_.task_id,
            task_title=round_.task.title if round_.task else None,
            revealed_at=round_.revealed_at,
            revealed_votes=round_.result.revealed_votes,
            metrics=round_.result.metrics,
        )
        for round_ in rounds
        if round_.result is not None and round_.revealed_at is not None
    ]


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


@router.post("/{code}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task_endpoint(
    code: str, payload: TaskCreateRequest, session: Session, token: ParticipantToken
) -> TaskResponse:
    task, _ = await create_task(session, code, payload, token)
    return task


@router.put("/{code}/tasks/order", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_tasks_endpoint(
    code: str, payload: TaskReorderRequest, session: Session, token: ParticipantToken
) -> None:
    await reorder_tasks(session, code, payload, token)


@router.put("/{code}/active-task", status_code=status.HTTP_204_NO_CONTENT)
async def set_active_task_endpoint(
    code: str, payload: ActiveTaskRequest, session: Session, token: ParticipantToken
) -> None:
    await set_active_task(session, code, payload, token)


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


@router.delete("/{code}/rounds/{round_id}/vote", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_vote_endpoint(
    code: str, round_id: UUID, session: Session, token: ParticipantToken
) -> None:
    version = await cancel_vote(session, code, round_id, token)
    participant = await _participant_for_vote(session, code, token)
    await room_connections.broadcast(
        code,
        {
            "type": "vote.status_changed",
            "payload": {
                "participant_id": str(participant.id),
                "has_voted": False,
                "version": version,
            },
        },
    )


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
