from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.db.models import Participant, RoomAction, TaskItem, Vote, VotingRound
from app.schemas.rooms import (
    ActiveTaskRequest,
    EstimateEditorRequest,
    FinalEstimateRequest,
    TaskCreateRequest,
    TaskDeleteRequest,
    TaskReorderRequest,
    TaskResponse,
    TaskUpdateRequest,
)
from app.services.rooms import _require_participant, get_room_or_404


async def create_task(
    session: AsyncSession, code: str, payload: TaskCreateRequest, token: str | None
) -> tuple[TaskResponse, int]:
    room, participant = await _task_creator_room(session, code, token)
    _version(room.version, payload.expected_version)
    position = await session.scalar(
        select(func.coalesce(func.max(TaskItem.position), -1) + 1).where(TaskItem.room_id == room.id)
    )
    task = TaskItem(room_id=room.id, title=_title(payload.title), position=position)
    session.add(task)
    room.version += 1
    await session.flush()
    session.add(
        RoomAction(
            room_id=room.id,
            actor_participant_id=participant.id,
            action_type="task_created",
            expected_version=payload.expected_version,
            payload={"task_id": str(task.id)},
        )
    )
    await session.commit()
    return _serialize(task), room.version


async def reorder_tasks(
    session: AsyncSession, code: str, payload: TaskReorderRequest, token: str | None
) -> int:
    room = await _owner_room(session, code, token)
    _version(room.version, payload.expected_version)
    if len(set(payload.task_ids)) != len(payload.task_ids):
        raise DomainError("duplicate_task", "Задача указана в сортировке дважды", status_code=422)
    tasks = list(
        (await session.scalars(select(TaskItem).where(TaskItem.room_id == room.id).with_for_update())).all()
    )
    by_id = {task.id: task for task in tasks}
    if set(payload.task_ids) != set(by_id):
        raise DomainError("invalid_task_order", "Список задач не совпадает с комнатой", status_code=422)
    locked_task_ids = set(
        (
            await session.scalars(
                select(VotingRound.task_id)
                .join(Vote, Vote.round_id == VotingRound.id)
                .where(VotingRound.room_id == room.id, VotingRound.task_id.is_not(None))
                .distinct()
            )
        ).all()
    )
    if any(by_id[task_id].position != position for position, task_id in enumerate(payload.task_ids) if task_id in locked_task_ids):
        raise DomainError(
            "task_position_locked",
            "Задачу с уже поданными голосами нельзя перемещать",
            status_code=409,
        )
    for position, task_id in enumerate(payload.task_ids):
        by_id[task_id].position = position
    room.version += 1
    await session.commit()
    return room.version


async def update_task(
    session: AsyncSession, code: str, task_id, payload: TaskUpdateRequest, token: str | None
) -> tuple[TaskResponse, int]:
    room, participant = await _task_creator_room(session, code, token)
    _version(room.version, payload.expected_version)
    task = await session.get(TaskItem, task_id, with_for_update=True)
    if task is None or task.room_id != room.id:
        raise DomainError("task_not_found", "Задача не найдена в этой комнате", status_code=404)
    task.title = _title(payload.title)
    room.version += 1
    session.add(
        RoomAction(
            room_id=room.id,
            actor_participant_id=participant.id,
            action_type="task_updated",
            expected_version=payload.expected_version,
            payload={"task_id": str(task.id)},
        )
    )
    await session.commit()
    return _serialize(task), room.version


async def delete_task(
    session: AsyncSession, code: str, task_id, payload: TaskDeleteRequest, token: str | None
) -> int:
    room, participant = await _task_creator_room(session, code, token)
    _version(room.version, payload.expected_version)
    task = await session.get(TaskItem, task_id, with_for_update=True)
    if task is None or task.room_id != room.id:
        raise DomainError("task_not_found", "Задача не найдена в этой комнате", status_code=404)
    has_round = await session.scalar(select(VotingRound.id).where(VotingRound.task_id == task.id).limit(1))
    if has_round is not None:
        raise DomainError(
            "task_has_rounds",
            "Нельзя удалить задачу, по которой уже был начат раунд",
            status_code=409,
        )
    if room.active_task_id == task.id:
        room.active_task_id = None
    await session.delete(task)
    room.version += 1
    session.add(
        RoomAction(
            room_id=room.id,
            actor_participant_id=participant.id,
            action_type="task_deleted",
            expected_version=payload.expected_version,
            payload={"task_id": str(task_id)},
        )
    )
    await session.commit()
    return room.version


async def set_estimate_editor(
    session: AsyncSession, code: str, payload: EstimateEditorRequest, token: str | None
) -> int:
    room = await _owner_room(session, code, token)
    _version(room.version, payload.expected_version)
    if payload.participant_id is not None:
        participant = await session.get(Participant, payload.participant_id)
        if participant is None or participant.room_id != room.id:
            raise DomainError("participant_not_found", "Участник не найден в этой комнате", status_code=404)
        if participant.id == room.owner_participant_id:
            payload.participant_id = None
    room.estimate_editor_participant_id = payload.participant_id
    room.version += 1
    await session.commit()
    return room.version


async def set_final_estimate(
    session: AsyncSession,
    code: str,
    task_id,
    payload: FinalEstimateRequest,
    token: str | None,
) -> tuple[TaskResponse, int]:
    room = await get_room_or_404(session, code, lock=True)
    participant = await _require_participant(session, room.id, token)
    if participant.id not in {room.owner_participant_id, room.estimate_editor_participant_id}:
        raise DomainError("estimate_editor_required", "Недостаточно прав для итоговой оценки", status_code=403)
    if room.state == "FINISHED":
        raise DomainError("room_finished", "Сессия завершена", status_code=409)
    _version(room.version, payload.expected_version)
    task = await session.get(TaskItem, task_id, with_for_update=True)
    if task is None or task.room_id != room.id:
        raise DomainError("task_not_found", "Задача не найдена в этой комнате", status_code=404)
    task.final_estimate = _estimate(payload.value)
    room.version += 1
    await session.commit()
    return _serialize(task), room.version


async def set_active_task(
    session: AsyncSession, code: str, payload: ActiveTaskRequest, token: str | None
) -> int:
    room = await get_room_or_404(session, code, lock=True)
    participant = await _require_participant(session, room.id, token)
    if not participant.is_online:
        raise DomainError("participant_offline", "Участник не подключён", status_code=403)
    if room.state == "FINISHED":
        raise DomainError("room_finished", "Сессия завершена", status_code=409)
    _version(room.version, payload.expected_version)
    if payload.task_id is not None:
        task = await session.get(TaskItem, payload.task_id)
        if task is None or task.room_id != room.id:
            raise DomainError("task_not_found", "Задача не найдена в этой комнате", status_code=404)
        if task.is_excluded:
            raise DomainError("task_excluded", "Исключённую задачу нельзя выбрать", status_code=409)
    room.active_task_id = payload.task_id
    room.version += 1
    await session.commit()
    return room.version


async def _owner_room(session: AsyncSession, code: str, token: str | None):
    room = await get_room_or_404(session, code, lock=True)
    participant = await _require_participant(session, room.id, token)
    if participant.id != room.owner_participant_id:
        raise DomainError("owner_required", "Действие доступно только владельцу", status_code=403)
    if room.state == "FINISHED":
        raise DomainError("room_finished", "Сессия завершена", status_code=409)
    return room


async def _task_creator_room(session: AsyncSession, code: str, token: str | None):
    """Allow the owner and the delegated estimate editor to add new tasks."""
    room = await get_room_or_404(session, code, lock=True)
    participant = await _require_participant(session, room.id, token)
    if participant.id not in {room.owner_participant_id, room.estimate_editor_participant_id}:
        raise DomainError(
            "task_creator_required",
            "Добавлять задачи может владелец или назначенный редактор итоговой оценки",
            status_code=403,
        )
    if room.state == "FINISHED":
        raise DomainError("room_finished", "Сессия завершена", status_code=409)
    return room, participant


def _version(current: int, expected: int) -> None:
    if current != expected:
        raise DomainError(
            "room_version_conflict",
            "Состояние комнаты изменилось",
            status_code=409,
            details={"current_version": current},
        )


def _title(value: str) -> str:
    title = " ".join(value.split())
    if not title:
        raise DomainError("invalid_task_title", "Название задачи не может быть пустым", status_code=422)
    return title


def _serialize(task: TaskItem) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        title=task.title,
        position=task.position,
        is_excluded=task.is_excluded,
        final_estimate=task.final_estimate,
    )


def _estimate(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise DomainError("invalid_final_estimate", "Итоговая оценка не может быть пустой", status_code=422)
    return normalized
