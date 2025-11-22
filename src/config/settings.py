"""Application settings using Pydantic Settings for environment variable management."""

# TODO: Import Pydantic Settings and BaseSettings
# TODO: Create Settings class that inherits from BaseSettings
# TODO: Configure model_config with:
#   - env_file=".env"
#   - env_file_encoding="utf-8"
#   - extra="ignore"
#   - case_sensitive=False
# TODO: Add fields for:
#   - openai_api_key: str (required)
#   - openai_model: str (default: "gpt-4o")
#   - github_token: str (required)
#   - github_webhook_secret: str (required)
#   - logfire_token: str | None (optional for observability)
#   - debug: bool (default: False)
#   - log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] (default: "INFO")
#   - environment: Literal["development", "staging", "production"] (default: "development")
#   - max_files_per_review: int (default: 10)
#   - max_retries: int (default: 2)
#   - review_temperature: float (default: 0.3)
#   - host: str (default: "0.0.0.0")
#   - port: int (default: 8000)
# TODO: Add @property methods:
#   - is_production() -> bool
#   - is_development() -> bool
# TODO: Create global settings instance
