"""
Application settings managed via environment variables.

Uses pydantic-settings to load configuration from .env files
and environment variables with type validation and defaults.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # MongoDB
    MONGO_URI: str = "mongodb://mongodb:27017"
    MONGO_DB_NAME: str = "metadata_inventory"

    # HTTP client
    REQUEST_TIMEOUT: int = 30  # seconds

    # Application
    LOG_LEVEL: str = "INFO"


# Singleton settings instance
settings = Settings()
