from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://localhost/sia"

    # Anthropic
    anthropic_api_key: str = ""

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
