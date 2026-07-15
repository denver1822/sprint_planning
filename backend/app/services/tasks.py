from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.db.models import RoomAction, TaskItem
from app.schemas.rooms import ActiveTaskRequest, TaskCreateRequest, TaskReorderRequest, TaskResponse
from app.services.rooms import _require_participant, get_room_or_404


async def create_task(
    session: AsyncSession, code: str, payload: TaskCreateRequest, token: str | None
) -> tuple[TaskResponse, int]:
    room = await _owner_room(session, code, token)
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
            actor_participant_id=room.owner_participant_id,
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
    for position, task_id in enumerate(payload.task_ids):
        by_id[task_id].position = position
    room.version += 1
    await session.commit()
    return room.version


async def set_active_task(
    session: AsyncSession, code: str, payload: ActiveTaskRequest, token: str | None
) -> int:
    room = await _owner_room(session, code, token)
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
    return TaskResponse(id=task.id, title=task.title, position=task.position, is_excluded=task.is_excluded)
