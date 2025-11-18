"""Logging and observability setup using Pydantic Logfire."""

# TODO: Import logging and sys
# TODO: Import settings from src.config

# TODO: Create setup_logging() function:
#   - Get log level from settings
#   - Configure logging.basicConfig with:
#     - level=log_level
#     - format string with timestamp, name, level, message
#     - StreamHandler to stdout
#   - Set httpx and urllib3 logging to WARNING to reduce noise

# TODO: Create setup_observability() function:
#   - Call setup_logging() first
#   - If settings.logfire_token exists:
#     - Try to import and configure logfire
#     - Set token, environment, service_name
#     - Call logfire.instrument_pydantic_ai()
#     - Call logfire.instrument_httpx()
#     - Log success message
#   - Handle ImportError if logfire not installed
#   - Handle any other exceptions
#   - Log warning if no token configured
