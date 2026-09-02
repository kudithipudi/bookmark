from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    root_path: str = ""
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-2.5-flash-lite"
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
    # Gates the admin-only routes (currently the bulk link checker). Falls
    # back to DELETE_PASSWORD so existing deployments that already set one
    # get admin access without touching their .env.
    admin_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ADMIN_PASSWORD", "DELETE_PASSWORD"),
    )
    # Bulk link checker (admin). Concurrency bounds simultaneous outbound
    # requests. A link is only "confirmed broken" once it has this many
    # consecutive failing sweeps — the default of 1 trusts a single 404 /
    # 410 / DNS failure (those are deterministic); bot walls and rate limits
    # are recorded as "uncertain" and never auto-promote to broken. Raise to
    # 2+ if you want a temporary outage to need repeating before it counts.
    link_check_concurrency: int = 10
    link_check_timeout_seconds: float = 10.0
    link_check_broken_threshold: int = 1
    # A run whose row still has finished_at IS NULL after this long is
    # treated as dead (worker restart mid-run), not as "already running".
    link_check_stale_after_seconds: int = 1800
    # DB_PATH is the standard env var name; DATABASE_PATH is kept as a
    # legacy fallback for existing deployments.
    db_path: str = Field(
        default="data/bookmarks.db",
        validation_alias=AliasChoices("DB_PATH", "DATABASE_PATH"),
    )
    # Where downloaded favicons are cached and served from (mounted at
    # /favicons), so browsers stop re-fetching them from the source site.
    favicon_dir: str = "data/favicons"
    favicon_max_bytes: int = 512 * 1024
    log_level: str = "info"
    rate_limit_per_minute: int = 20
    rate_limit_window_seconds: int = 60


settings = Settings()
