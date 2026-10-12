from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables or .env file.
    Includes tuning parameters for high-concurrency and high-throughput scaling.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database Configuration
    database_url: str = "sqlite:///./geo_api.db"
    db_pool_size: int = 50
    db_max_overflow: int = 100
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # Storage
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 50

    # Caching Layer (Redis with in-memory fallback)
    redis_url: Optional[str] = None
    cache_enabled: bool = True
    cache_default_ttl: int = 300  # 5 minutes
    cache_max_memory_items: int = 10000

    # Rate Limiting & Protection
    rate_limit_enabled: bool = False
    rate_limit_requests: int = 10000
    rate_limit_window_seconds: int = 60

    # HTTP & Compression
    enable_gzip: bool = True
    gzip_min_size: int = 1000  # Compress responses larger than 1KB
    workers: int = 4

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def ensure_upload_dir(self) -> Path:
        """Create the upload directory if it doesn't exist and return its path."""
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()

