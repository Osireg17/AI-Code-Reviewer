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
    openai_api_key: str | None = Field(
        default=None, description="OpenAI API key for AI models"
    )
    openai_model: str = Field(default="gpt-4.1-nano", description="OpenAI model to use")

    # GitHub Configuration
    # Note: GitHub Actions doesn't allow env var names starting with GITHUB_
    # so we support both GITHUB_* and GH_* / *_TOKEN / WEBHOOK_SECRET variants
    github_token: str | None = Field(
        default=None,
        validation_alias="GH_TOKEN",
        description="GitHub personal access token (legacy, prefer GitHub App)",
    )
    github_webhook_secret: str | None = Field(
        default=None,
        validation_alias="WEBHOOK_SECRET",
        description="GitHub webhook secret for signature verification",
    )

    # GitHub App Configuration
    # Support both GITHUB_APP_* (local) and APP_* (CI) env var names
    github_app_id: str | None = Field(
        default=None, validation_alias="APP_ID", description="GitHub App ID"
    )
    github_app_client_id: str | None = Field(
        default=None,
        validation_alias="APP_CLIENT_ID",
        description="GitHub App Client ID",
    )
    github_app_client_secret: str | None = Field(
        default=None,
        validation_alias="APP_CLIENT_SECRET",
        description="GitHub App Client Secret",
    )
    github_app_installation_id: str | None = Field(
        default=None,
        validation_alias="APP_INSTALLATION_ID",
        description="GitHub App Installation ID",
    )
    github_app_private_key_path: str | None = Field(
        default=None,
        validation_alias="APP_PRIVATE_KEY_PATH",
        description="Path to GitHub App private key .pem file",
    )
    github_app_private_key: str | None = Field(
        default=None,
        validation_alias="APP_PRIVATE_KEY",
        description="GitHub App private key content (alternative to file path)",
    )

    # Observability
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
    bot_name: str = Field(
        default="SearchLightAI", description="Bot name to display in comments"
    )
    max_files_per_review: int = Field(
        default=10, description="Maximum number of files to review per PR"
    )
    max_retries: int = Field(
        default=2, description="Maximum number of retries for API calls"
    )
    review_temperature: float = Field(
        default=0.5, description="Temperature for AI model responses"
    )

    # Server Configuration
    # Use a localhost default to avoid binding to all interfaces.
    # Override via env (e.g., HOST=0.0.0.0) only when needed (containers/proxies).
    host: str = Field(default="127.0.0.1", description="Server host")
    port: int = Field(default=8000, description="Server port")

    # Pinecone Configuration
    pinecone_api_key: str | None = Field(
        default=None, description="Pinecone API key for vector database"
    )
    pinecone_index_name: str = Field(
        default="code-style-guides",
        description="Pinecone index name for RAG knowledge base",
    )

    # Database Configuration
    database_url: str = Field(
        default="postgresql://postgres:password@localhost:5432/ai_code_reviewer_dev",  # pragma: allowlist secret
        description="PostgreSQL database URL (required). Use private URL (postgres.railway.internal) in Railway, public URL for local dev",
    )

    # RAG Configuration
    rag_enabled: bool = Field(default=True, description="Enable RAG style guide search")
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model for RAG",
    )
    rag_top_k: int = Field(
        default=3, description="Number of similar documents to retrieve"
    )
    rag_min_similarity: float = Field(
        default=0.4, description="Minimum similarity score for RAG results (0-1)"
    )

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
    if settings.rag_enabled and not settings.pinecone_api_key:
        missing.append("PINECONE_API_KEY (required for RAG)")
    if missing:
        raise RuntimeError(
            "Missing required environment variables for production: "
            + ", ".join(missing)
        )
