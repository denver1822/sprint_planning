# Planning Poker

Веб-приложение для совместной оценки задач в story points. Участники входят по ссылке без регистрации, голосуют картами, раскрывают оценки одновременно и сохраняют историю раундов.

## Стек и структура

- `frontend/` — React, TypeScript, Vite.
- `backend/` — FastAPI, SQLAlchemy, Alembic, PostgreSQL.
- `deploy/` и `docker-compose.yml` — заготовки production-развёртывания.
- [MVP_Contract_Planning_Poker.md](MVP_Contract_Planning_Poker.md) — контракт MVP.

## Локальный запуск без Docker

### Требования

- Python 3.12+;
- Node.js 20+ и npm;
- PostgreSQL 15+;
- свободные порты `5173` (frontend) и `8001` (backend).

### 1. Создать базу данных

Создайте в PostgreSQL отдельную базу, например `planning_poker_dev`. Это можно сделать через pgAdmin или командой:

```sql
CREATE DATABASE planning_poker_dev;
```

Пользователь PostgreSQL должен иметь права на эту базу и создание таблиц.

### 2. Настроить и запустить backend

В PowerShell из корня проекта:

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item ..\.env.example .env
```

Откройте `backend/.env` и замените значения для локальной разработки:

```dotenv
ENVIRONMENT=development
DATABASE_URL=postgresql+asyncpg://<POSTGRES_USER>:<POSTGRES_PASSWORD>@127.0.0.1:5432/planning_poker_dev
SECRET_KEY=<длинная-случайная-строка>
FRONTEND_ORIGIN=http://127.0.0.1:5173
PUBLIC_BASE_URL=http://127.0.0.1:5173
LOG_LEVEL=INFO
```

Не добавляйте `backend/.env` в Git: в нём находятся реквизиты доступа к локальной БД.

Примените миграции и запустите API:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Проверка:

- API: <http://127.0.0.1:8001/docs>
- liveness: <http://127.0.0.1:8001/api/health>
- PostgreSQL readiness: <http://127.0.0.1:8001/api/ready>

### 3. Запустить frontend

Откройте второе окно PowerShell:

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

Откройте <http://127.0.0.1:5173>. Vite направляет запросы `/api` и `/ws` на backend `127.0.0.1:8001`.

### 4. Остановить приложение

В окнах с Vite и Uvicorn нажмите `Ctrl+C`. PostgreSQL при этом можно оставить запущенным.

## Проверки

Backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Frontend:

```powershell
cd frontend
npm run lint
npm run typecheck
npm run build
```

## Если порт занят

Проверьте процесс на нужном порту:

```powershell
netstat -ano | Select-String ':8001|:5173'
```

Не завершайте неизвестный процесс. Либо освободите порт, либо запустите backend на другом порту и измените proxy в [frontend/vite.config.ts](frontend/vite.config.ts).

## Jira

Jira-интеграция необязательна для локального запуска. Адрес Jira и API-токен вводятся владельцем комнаты только для проверки подключения, preview и import; токен не сохраняется в базе данных.

## Docker и production

Инструкции для container-based deployment находятся в [Deployment_Planning_Poker_Poland_Server.docx](Deployment_Planning_Poker_Poland_Server.docx). Для локальной разработки рекомендуется сценарий выше: он быстрее и упрощает отладку backend, frontend и миграций.
