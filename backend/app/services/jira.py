import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.db.models import RoomAction, TaskItem
from app.schemas.rooms import (
    JiraImportRequest,
    JiraImportResponse,
    JiraConnectionTestRequest,
    JiraIssueResponse,
    JiraPreviewRequest,
    JiraPreviewResponse,
    TaskResponse,
)
from app.services.rooms import _require_participant, get_room_or_404

JIRA_TIMEOUT_SECONDS = 10.0
JIRA_MAX_RESPONSE_BYTES = 1_000_000


async def preview_jira(
    session: AsyncSession, code: str, payload: JiraPreviewRequest, token: str | None
) -> JiraPreviewResponse:
    await _owner_room(session, code, token)
    return await _search(payload)


async def test_jira_connection(
    session: AsyncSession, code: str, payload: JiraConnectionTestRequest, token: str | None
) -> None:
    await _owner_room(session, code, token)
    base_url = _safe_jira_base_url(payload.connection.base_url)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {payload.connection.api_token.get_secret_value()}",
    }
    try:
        async with httpx.AsyncClient(timeout=JIRA_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.get(f"{base_url}/rest/api/3/myself", headers=headers)
            response.raise_for_status()
            if len(response.content) > JIRA_MAX_RESPONSE_BYTES:
                raise DomainError("jira_response_too_large", "Ответ Jira превышает допустимый размер", status_code=422)
    except DomainError:
        raise
    except httpx.HTTPError:
        raise DomainError(
            "jira_connection_failed",
            "Не удалось подключиться к Jira. Проверьте адрес и токен.",
            status_code=422,
        ) from None


async def import_jira(
    session: AsyncSession, code: str, payload: JiraImportRequest, token: str | None
) -> JiraImportResponse:
    room = await _owner_room(session, code, token, lock=True)
    if room.version != payload.expected_version:
        raise DomainError(
            "room_version_conflict",
            "Состояние комнаты изменилось",
            status_code=409,
            details={"current_version": room.version},
        )
    preview = await _search(payload)
    selected = {issue.key: issue for issue in preview.issues if issue.key in payload.selected_keys}
    if set(payload.selected_keys) != set(selected):
        raise DomainError(
            "jira_selection_invalid",
            "Выберите задачи из текущей страницы preview",
            status_code=422,
        )
    position = await session.scalar(
        select(func.coalesce(func.max(TaskItem.position), -1) + 1).where(TaskItem.room_id == room.id)
    )
    tasks: list[TaskItem] = []
    for offset, key in enumerate(payload.selected_keys):
        issue = selected[key]
        task = TaskItem(
            room_id=room.id,
            source="jira",
            title=issue.title,
            position=position + offset,
            jira_key=issue.key,
            jira_url=issue.url,
            jira_snapshot=issue.snapshot,
        )
        session.add(task)
        tasks.append(task)
    if room.active_task_id is None and tasks:
        room.active_task_id = tasks[0].id
    room.version += 1
    await session.flush()
    session.add(
        RoomAction(
            room_id=room.id,
            actor_participant_id=room.owner_participant_id,
            action_type="jira_imported",
            expected_version=payload.expected_version,
            payload={"issue_count": len(tasks), "issue_keys": [task.jira_key for task in tasks]},
        )
    )
    await session.commit()
    return JiraImportResponse(imported=[_task_response(task) for task in tasks], version=room.version)


async def _owner_room(session: AsyncSession, code: str, token: str | None, *, lock: bool = False):
    room = await get_room_or_404(session, code, lock=lock)
    participant = await _require_participant(session, room.id, token)
    if participant.id != room.owner_participant_id:
        raise DomainError("owner_required", "Действие доступно только владельцу", status_code=403)
    if room.state == "FINISHED":
        raise DomainError("room_finished", "Сессия завершена", status_code=409)
    return room


async def _search(payload: JiraPreviewRequest) -> JiraPreviewResponse:
    base_url = _safe_jira_base_url(payload.connection.base_url)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {payload.connection.api_token.get_secret_value()}",
    }
    try:
        async with httpx.AsyncClient(timeout=JIRA_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.get(
                f"{base_url}/rest/api/3/search/jql",
                params={
                    "jql": payload.jql,
                    "startAt": payload.start_at,
                    "maxResults": payload.max_results,
                    "fields": "summary,issuetype,status,project",
                },
                headers=headers,
            )
            response.raise_for_status()
            if len(response.content) > JIRA_MAX_RESPONSE_BYTES:
                raise DomainError("jira_response_too_large", "Ответ Jira превышает допустимый размер", status_code=422)
            data = response.json()
    except DomainError:
        raise
    except (httpx.HTTPError, ValueError):
        raise DomainError(
            "jira_request_failed",
            "Не удалось получить задачи из Jira. Проверьте адрес, права и JQL.",
            status_code=422,
        ) from None
    issues = [_normalize_issue(base_url, issue) for issue in data.get("issues", [])]
    return JiraPreviewResponse(
        issues=issues,
        start_at=int(data.get("startAt", payload.start_at)),
        max_results=int(data.get("maxResults", payload.max_results)),
        total=min(int(data.get("total", len(issues))), 10_000),
    )


def _safe_jira_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise DomainError("unsafe_jira_url", "Укажите корректный HTTPS-адрес Jira", status_code=422)
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise DomainError("unsafe_jira_url", "Адрес Jira не должен содержать путь или параметры", status_code=422)
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        raise DomainError("jira_host_unavailable", "Адрес Jira недоступен", status_code=422) from None
    if not addresses or any(not _public_address(address) for address in addresses):
        raise DomainError("unsafe_jira_url", "Адрес Jira недопустим", status_code=422)
    return f"https://{parsed.netloc}"


def _public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _normalize_issue(base_url: str, issue: object) -> JiraIssueResponse:
    if not isinstance(issue, dict):
        raise DomainError("jira_invalid_response", "Jira вернула некорректный ответ", status_code=422)
    key = str(issue.get("key", "")).strip().upper()
    fields = issue.get("fields")
    if not key or not isinstance(fields, dict) or not isinstance(fields.get("summary"), str):
        raise DomainError("jira_invalid_response", "Jira вернула задачу без ключа или названия", status_code=422)
    issue_type = fields.get("issuetype") if isinstance(fields.get("issuetype"), dict) else {}
    status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
    project = fields.get("project") if isinstance(fields.get("project"), dict) else {}
    snapshot = {
        "key": key,
        "summary": fields["summary"].strip()[:500],
        "issue_type": _name(issue_type),
        "status": _name(status),
        "project_key": str(project.get("key")) if project.get("key") else None,
    }
    return JiraIssueResponse(key=key, title=snapshot["summary"], url=f"{base_url}/browse/{key}", snapshot=snapshot)


def _name(value: dict[str, object]) -> str | None:
    name = value.get("name")
    return str(name) if name else None


def _task_response(task: TaskItem) -> TaskResponse:
    return TaskResponse(id=task.id, title=task.title, position=task.position, is_excluded=task.is_excluded)
