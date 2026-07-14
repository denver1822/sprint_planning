# Planning Poker

Веб-приложение для совместной оценки задач в story points.

## Структура

- `frontend/` — React, TypeScript и Vite.
- `backend/` — FastAPI, SQLAlchemy, Alembic и pytest.
- `deploy/nginx/` — конфигурация Nginx для польского VPS.
- `docker-compose.yml` — production-окружение: frontend, backend и PostgreSQL.

## Локальный запуск

1. Скопировать `.env.example` в `.env` и заменить тестовые секреты.
2. Запустить инфраструктуру: `docker compose up --build`.
3. Открыть frontend на `http://localhost:18080`, API health-check — `http://localhost:18000/api/health`.

Для production внешние порты не открываются: Nginx на хосте проксирует HTTPS/WSS на loopback-порты контейнеров.
