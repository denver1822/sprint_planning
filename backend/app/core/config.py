from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://planning_user:planning_password@postgres:5432/planning_poker"
    secret_key: str = "change-me-before-production"
    frontend_origin: str = "http://localhost:5173"
    public_base_url: str = "http://localhost:5173"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

