"""Application settings using Pydantic Settings for environment variable management."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # OpenAI Configuration
    openai_api_key: str | None = Field(default=None, description="OpenAI API key for AI models")
    openai_model: str = Field(default="gpt-4o", description="OpenAI model to use")

    # GitHub Configuration
    github_token: str | None = Field(default=None, description="GitHub personal access token")
    github_webhook_secret: str | None = Field(
        default=None, description="GitHub webhook secret for signature verification"
    )

    # Observability (Optional)
    logfire_token: str | None = Field(
        default=None, description="Pydantic Logfire token for observability"
    )

    # Application Settings
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )
    environment: Literal["development", "staging", "production"] = Field(
        default="development", description="Application environment"
    )

    # Review Configuration
    max_files_per_review: int = Field(
        default=10, description="Maximum number of files to review per PR"
    )
    max_retries: int = Field(
        default=2, description="Maximum number of retries for API calls"
    )
    review_temperature: float = Field(
        default=0.3, description="Temperature for AI model responses"
    )

    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"


# Global settings instance
settings = Settings()

# Validate required secrets in production to avoid silent failures
if settings.is_production:
    missing = []
    if not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if not settings.github_token:
        missing.append("GITHUB_TOKEN")
    if not settings.github_webhook_secret:
        missing.append("GITHUB_WEBHOOK_SECRET")
    if missing:
        raise RuntimeError(
            "Missing required environment variables for production: "
            + ", ".join(missing)
        )
