"""Application configuration for the fully local ITR preparation system."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables prefixed with ITR_."""

    model_config = SettingsConfigDict(env_prefix="ITR_", env_file=".env", extra="ignore")

    app_name: str = "Local ITR Income Calculator"
    host: str = "127.0.0.1"
    port: int = 8000
    open_browser: bool = True
    data_dir: Path = Path("./data")
    max_upload_mb: int = 500
    db_key: str | None = None
    worker_count: int = 2
    duplicate_day_window: int = 3
    duplicate_amount_tolerance: float = 1.0
    self_transfer_day_window: int = 3

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "temp"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "itr_local.db"

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.upload_dir, self.export_dir, self.temp_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
