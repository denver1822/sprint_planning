from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Temporary liveness endpoint; database readiness follows in the core stage."""
    return {"status": "ok"}

