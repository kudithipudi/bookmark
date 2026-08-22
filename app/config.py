from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    root_path: str = ""
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-2.5-flash"
    llm_timeout_seconds: float = 15.0
    delete_password: str | None = None
    # DB_PATH is the standard env var name; DATABASE_PATH is kept as a
    # legacy fallback for existing deployments.
    db_path: str = Field(
        default="data/bookmarks.db",
        validation_alias=AliasChoices("DB_PATH", "DATABASE_PATH"),
    )
    log_level: str = "info"
    rate_limit_per_minute: int = 20
    rate_limit_window_seconds: int = 60


settings = Settings()
