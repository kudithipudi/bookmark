from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    root_path: str = ""
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-2.5-flash"
    llm_timeout_seconds: float = 15.0
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Inside the app dir so it's writable under the systemd sandbox
    # (ProtectSystem=strict + ReadWritePaths) and shared by both workers.
    embedding_cache_dir: str = ".cache/fastembed"
    semantic_score_threshold: float = 0.55
    semantic_search_limit: int = 12
    # How long an in-worker vector cache may serve before re-reading the
    # bookmarks table. Bounds staleness across gunicorn workers after writes.
    semantic_cache_ttl_seconds: float = 30.0
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
