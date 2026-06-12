from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://localhost/sia"

    # LLM providers (Sia core uses LLMs only for internal context operations)
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    openrouter_base_url: str = ""

    # Ollama
    ollama_url: str = "http://host.docker.internal:11434"

    # Auth
    jwt_secret: str = "change-me"
    jwt_expiry_hours: int = 24
    admin_email: str = "admin@example.com"
    admin_password_hash: str = ""

    # Langfuse (Phase 2)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # Feedly
    feedly_access_token: str = ""
    feedly_board_id: str = ""

    # CORS: comma-separated browser origins allowed to call the API (empty = none;
    # MCP/REST consumers are server-side and need no CORS)
    cors_origins: str = ""

    # Content-Security-Policy for the admin UI. Empty = the built-in default
    # (self-only; all frontend assets are vendored under app/static/vendor/).
    csp_header: str = ""

    # Set true when the deployment is served over HTTPS (i.e. behind a TLS proxy):
    # forces the Secure flag on the session cookie and always sends HSTS, even when
    # proxy headers are not wired through to uvicorn. Without it, Secure/HSTS are
    # emitted only when the request scheme is already https (direct TLS, or
    # --proxy-headers with a trusted proxy IP).
    force_https: bool = False

    # Context store (git-backed Markdown files)
    context_store_path: str = "/srv/sia/context"
    context_store_remote: str = ""  # optional push mirror, e.g. git@github.com:user/sia-context

    # Slack
    slack_webhook_secret: str = ""  # verifies inbound ingestion webhooks
    slack_alert_webhook_url: str = ""  # outbound alerts for consolidation failures

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
