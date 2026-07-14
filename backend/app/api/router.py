from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.rooms import router as rooms_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(rooms_router)
