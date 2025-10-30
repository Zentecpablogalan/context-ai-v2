from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    app_name: str = "Context Search AI V2"
    env: str = "dev"

    # Secrets from Key Vault (injected via App Settings as env vars)
    openai_api_key: str | None = None
    stripe_secret_key: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None

    # CORS
    cors_origins: str = "*"  # comma-separated if needed

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()
